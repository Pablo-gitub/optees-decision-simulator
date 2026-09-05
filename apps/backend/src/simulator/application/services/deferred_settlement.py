"""Deferred decision settlement service and settlement result DTO (DS-02D2B2).

Reuses `ExecutionService`'s accounting formulas (notional, linear/fixed fee,
balance and valuation composition) for the pending's single action, but never
imports or calls `ExecutionService` and never mutates its records. Reuses
`PriceEvidence` from the pricing port for injected valuation marks, but does
not implement or call `PricingPort`/`MarketKlinePricingAdapter`: target-bar
selection here is governed by the pending's own `target_bar_rule.series_id`
and the retained `payload["open_time"]` field, never `event_time` (see
"Why not `MarketKlinePricingAdapter`" in the frozen settlement plan).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from functools import wraps
from typing import Final, Mapping

from simulator.application.ports.pricing import PriceEvidence
from simulator.application.services.deferred_admission import _compute_pending_transition_id
from simulator.domain.canonical import compute_record_hash, format_decimal
from simulator.domain.errors import InvalidTimestampError
from simulator.domain.lifecycle import ActionType, CostType, SettlementStatus
from simulator.domain.models import (
    BalanceItem,
    CostItem,
    CostModelSpec,
    CumulativeCostItem,
    DeferredTransitionRecord,
    EpisodeDefinition,
    ObservationRecord,
    PendingTransitionRecord,
    ReferenceValuation,
    RejectionReason,
    RequestedAction,
    ResourceDelta,
    SettlementOutcome,
    VirtualAccountState,
)
from simulator.domain.time import parse_utc_timestamp


def _settlement_decimal_context(function):
    """Isolate precision, rounding, exponent limits and traps from the caller."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        with localcontext(
            Context(
                prec=64,
                rounding=ROUND_HALF_EVEN,
                Emin=-999999,
                Emax=999999,
                capitals=1,
                clamp=0,
                flags=[],
                traps=[InvalidOperation, DivisionByZero, Overflow],
            )
        ):
            return function(*args, **kwargs)

    return wrapped


def _settlement_id(prefix, pending, round_id):
    digest = compute_record_hash(
        {"pending_transition_id": pending.pending_transition_id, "settlement_round_id": round_id}
    )
    return f"{prefix}_{digest[7:]}"


# Application-owned rejection codes for deferred settlement
REJECTION_INVALID_EXECUTION_PRICE: Final[str] = "INVALID_EXECUTION_PRICE"
REJECTION_INSUFFICIENT_FUNDS_AT_SETTLEMENT: Final[str] = "INSUFFICIENT_FUNDS_AT_SETTLEMENT"
REJECTION_SHORT_POSITIONS_FORBIDDEN: Final[str] = "SHORT_POSITIONS_FORBIDDEN"
REJECTION_MISSING_VALUATION_MARK: Final[str] = "MISSING_VALUATION_MARK"
REJECTION_MISSING_EXECUTION_BAR: Final[str] = "MISSING_EXECUTION_BAR"
REJECTION_UNSETTLED_EPISODE_TERMINATION: Final[str] = "UNSETTLED_EPISODE_TERMINATION"
REJECTION_EPISODE_CANCELLED: Final[str] = "EPISODE_CANCELLED"

_TERMINATE_REASON_CODES: Final[frozenset[str]] = frozenset(
    {
        REJECTION_MISSING_EXECUTION_BAR,
        REJECTION_UNSETTLED_EPISODE_TERMINATION,
        REJECTION_EPISODE_CANCELLED,
    }
)

_DEFAULT_TERMINATE_MESSAGES: Final[dict[str, str]] = {
    REJECTION_MISSING_EXECUTION_BAR: ("Execution bar did not arrive within the settlement window"),
    REJECTION_UNSETTLED_EPISODE_TERMINATION: (
        "Episode terminated with an unsettled pending transition"
    ),
    REJECTION_EPISODE_CANCELLED: (
        "Episode was cancelled while a transition was pending settlement"
    ),
}

_ROUND_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^rnd_[a-zA-Z0-9_-]+$")

_CENTS: Final[Decimal] = Decimal("0.01")


@dataclass(frozen=True)
class DeferredSettlementResult:
    """Immutable result of one settlement evaluation for a pending transition."""

    pending_transition: PendingTransitionRecord
    settlement_outcome: SettlementOutcome | None
    deferred_transition: DeferredTransitionRecord | None
    next_account: VirtualAccountState
    is_settled: bool
    is_still_pending: bool

    def __post_init__(self) -> None:
        if self.is_settled and self.is_still_pending:
            raise ValueError("Result cannot be both settled and still pending")

        if self.is_still_pending:
            if self.settlement_outcome is not None or self.deferred_transition is not None:
                raise ValueError(
                    "Still-pending result cannot include a settlement outcome or transition"
                )
        elif self.is_settled:
            if self.settlement_outcome is None or self.settlement_outcome.status != (
                SettlementStatus.SETTLED
            ):
                raise ValueError("Settled result requires a SETTLED settlement outcome")
            if self.deferred_transition is None:
                raise ValueError("Settled result requires a deferred transition record")
        else:
            if self.settlement_outcome is None or self.settlement_outcome.status != (
                SettlementStatus.REJECTED
            ):
                raise ValueError("Rejected result requires a REJECTED settlement outcome")
            if self.deferred_transition is not None:
                raise ValueError("Rejected result cannot include a deferred transition record")


def _validate_common_context(
    episode_def: EpisodeDefinition,
    current_account: VirtualAccountState,
    pending: PendingTransitionRecord,
    settlement_round_id: str,
    settlement_time: str,
    admission_account: VirtualAccountState | None = None,
) -> tuple[datetime, datetime]:
    """Validate caller-supplied context shared by both entry points.

    Returns (knowledge_cutoff_instant, settlement_instant) on success.
    Raises TypeError/ValueError on any caller error.
    """
    if not isinstance(episode_def, EpisodeDefinition):
        raise TypeError(
            f"episode_def must be an EpisodeDefinition instance, got {type(episode_def)}"
        )
    if not isinstance(current_account, VirtualAccountState):
        raise TypeError(
            f"current_account must be a VirtualAccountState instance, got {type(current_account)}"
        )
    if not isinstance(pending, PendingTransitionRecord):
        raise TypeError(f"pending must be a PendingTransitionRecord instance, got {type(pending)}")

    if pending.policy_id != current_account.policy_id:
        raise ValueError(
            f"pending policy_id '{pending.policy_id}' does not match "
            f"current_account policy_id '{current_account.policy_id}'"
        )

    anchor = admission_account if admission_account is not None else current_account
    if not isinstance(anchor, VirtualAccountState):
        raise TypeError("admission_account must be a VirtualAccountState")
    if anchor.compute_hash() != pending.predecessor_account_hash:
        raise ValueError(
            "current_account hash does not match pending.predecessor_account_hash; "
            "provide the exact admission_account when current account was revalued"
        )
    if (
        current_account.policy_id != anchor.policy_id
        or current_account.balances != anchor.balances
        or current_account.cumulative_costs != anchor.cumulative_costs
        or current_account.reference_valuation.reference_resource_id
        != anchor.reference_valuation.reference_resource_id
    ):
        raise ValueError("Account balances or costs changed while pending")

    expected_id = _compute_pending_transition_id(
        episode_def.episode_id, pending.round_id, pending.policy_id, pending.decision_id
    )
    pinned = {p.policy_id: p.policy_version_id for p in episode_def.policy_versions}
    if (
        pending.pending_transition_id != expected_id
        or pinned.get(pending.policy_id) != pending.policy_version_id
    ):
        raise ValueError("Pending identity or pinned policy version does not belong to episode")

    if not isinstance(settlement_round_id, str) or not _ROUND_ID_PATTERN.match(settlement_round_id):
        raise ValueError(f"settlement_round_id is malformed: {settlement_round_id!r}")

    if not isinstance(settlement_time, str):
        raise TypeError(f"settlement_time must be a str, got {type(settlement_time)}")
    settlement_dt = parse_utc_timestamp(settlement_time)
    cutoff_dt = parse_utc_timestamp(pending.knowledge_cutoff)
    if settlement_dt < cutoff_dt:
        raise ValueError(
            f"settlement_time ({settlement_time}) cannot precede "
            f"pending.knowledge_cutoff ({pending.knowledge_cutoff})"
        )
    if (
        not parse_utc_timestamp(anchor.as_of_time)
        <= parse_utc_timestamp(current_account.as_of_time)
        <= settlement_dt
    ):
        raise ValueError("Account time is outside admission/settlement chronology")

    if pending.requested_action.action_type not in (ActionType.ALLOCATE, ActionType.TRANSFER):
        raise TypeError(
            "pending.requested_action.action_type must be ALLOCATE or TRANSFER; "
            f"got {pending.requested_action.action_type!r}. A real pending transition "
            "produced by DeferredAdmissionService can never carry HOLD or ADJUST."
        )
    qty = pending.requested_action.quantity
    if pending.requested_action.resource_id == episode_def.reference_resource_id:
        raise ValueError("Cannot trade the reference resource")
    if (
        not qty.is_finite()
        or qty == 0
        or (pending.requested_action.action_type == ActionType.ALLOCATE and qty < 0)
    ):
        raise ValueError("Pending trade quantity violates admission profile")

    return cutoff_dt, settlement_dt


def _select_target_observation(
    all_observations: tuple[ObservationRecord, ...],
    series_id: str,
    settlement_dt: datetime,
    expected_open_dt: datetime,
) -> ObservationRecord | None:
    """Select an eligible revision at exactly the frozen scheduled opening.

    Availability never defines the schedule: absent or invalid targets wait,
    rather than falling through to another opening.
    """
    candidates: list[ObservationRecord] = []
    for obs in all_observations:
        if obs.series_id != series_id:
            continue
        raw_open_time = obs.payload.get("open_time")
        if not isinstance(raw_open_time, str):
            continue
        try:
            open_time_dt = parse_utc_timestamp(raw_open_time)
        except InvalidTimestampError:
            continue
        if open_time_dt != expected_open_dt:
            continue
        knowledge_dt = parse_utc_timestamp(obs.knowledge_time)
        if open_time_dt >= knowledge_dt:
            continue
        candidates.append(obs)

    if not candidates:
        return None

    eligible = [
        obs for obs in candidates if parse_utc_timestamp(obs.knowledge_time) <= settlement_dt
    ]
    if not eligible:
        return None
    identities = {}
    for obs in eligible:
        identity = (obs.revision, obs.observation_id)
        if identity in identities and identities[identity] != obs.to_dict():
            raise ValueError("Conflicting observations share the same revision and identity")
        identities[identity] = obs.to_dict()

    eligible.sort(key=lambda o: (o.revision, o.observation_id))
    return eligible[-1]


def _compute_action_economics(
    action: RequestedAction,
    execution_price: Decimal,
    cost_model: CostModelSpec,
    reference_resource_id: str,
) -> tuple[Decimal, Decimal, tuple[CostItem, ...], Decimal]:
    """Compute (cash_delta, asset_delta, cost_items, total_action_cost).

    Mirrors ExecutionService's ALLOCATE/TRANSFER formulas exactly, with
    explicit ROUND_HALF_EVEN rounding on every quantization instead of relying
    on the ambient decimal context.
    """
    qty = action.quantity

    if action.action_type == ActionType.ALLOCATE:
        notional = (qty * execution_price).quantize(_CENTS, rounding=ROUND_HALF_EVEN)
        linear_fee = (notional * cost_model.linear_transaction_fee_rate).quantize(
            _CENTS, rounding=ROUND_HALF_EVEN
        )
        fixed_fee = cost_model.fixed_transaction_fee.quantize(_CENTS, rounding=ROUND_HALF_EVEN)
        action_cost = linear_fee + fixed_fee
        cash_delta = -(notional + action_cost)
        asset_delta = qty
    else:
        notional = (abs(qty) * execution_price).quantize(_CENTS, rounding=ROUND_HALF_EVEN)
        linear_fee = (notional * cost_model.linear_transaction_fee_rate).quantize(
            _CENTS, rounding=ROUND_HALF_EVEN
        )
        fixed_fee = cost_model.fixed_transaction_fee.quantize(_CENTS, rounding=ROUND_HALF_EVEN)
        action_cost = linear_fee + fixed_fee
        asset_delta = qty
        if qty >= Decimal("0"):
            cash_delta = -(notional + action_cost)
        else:
            cash_delta = notional - action_cost

    cost_items: list[CostItem] = []
    if linear_fee > Decimal("0"):
        cost_items.append(
            CostItem(
                cost_type=CostType.TRANSACTION_FEE,
                resource_id=reference_resource_id,
                amount=linear_fee,
            )
        )
    if fixed_fee > Decimal("0"):
        cost_items.append(
            CostItem(
                cost_type=CostType.TRANSACTION_FEE,
                resource_id=reference_resource_id,
                amount=fixed_fee,
            )
        )

    return cash_delta, asset_delta, tuple(cost_items), action_cost


class DeferredSettlementService:
    """Pure, stateless settlement service for pending transitions awaiting execution."""

    @staticmethod
    @_settlement_decimal_context
    def attempt_settlement(
        episode_def: EpisodeDefinition,
        current_account: VirtualAccountState,
        pending: PendingTransitionRecord,
        settlement_round_id: str,
        settlement_round_index: int,
        settlement_time: str,
        all_observations: tuple[ObservationRecord, ...],
        valuation_marks: Mapping[str, Decimal | PriceEvidence],
        *,
        expected_open_time: str,
        admission_account: VirtualAccountState | None = None,
    ) -> DeferredSettlementResult:
        """Attempt causal, observation-driven settlement of an ADMITTED_PENDING transition.

        Does not decide settlement-window timeouts, episode termination or
        cancellation; see `terminate_unsettled` for those exogenous outcomes.
        """
        cutoff_dt, settlement_dt = _validate_common_context(
            episode_def,
            current_account,
            pending,
            settlement_round_id,
            settlement_time,
            admission_account,
        )
        expected_open_dt = parse_utc_timestamp(expected_open_time)
        if expected_open_dt < cutoff_dt:
            raise ValueError("Expected opening cannot precede admission cutoff")
        retained_open = pending.target_bar_rule.expected_open_time
        if retained_open is not None and parse_utc_timestamp(retained_open) != expected_open_dt:
            raise ValueError("Expected opening conflicts with pending target rule")

        if not isinstance(all_observations, tuple) or not all(
            isinstance(o, ObservationRecord) for o in all_observations
        ):
            raise TypeError("all_observations must be a tuple of ObservationRecord instances")
        if isinstance(valuation_marks, bool) or not isinstance(valuation_marks, Mapping):
            raise TypeError(f"valuation_marks must be a Mapping, got {type(valuation_marks)}")
        if (
            isinstance(settlement_round_index, bool)
            or not isinstance(settlement_round_index, int)
            or settlement_round_index < 0
        ):
            raise ValueError(
                f"settlement_round_index must be a non-negative int, got {settlement_round_index!r}"
            )

        marks: dict[str, Decimal] = {episode_def.reference_resource_id: Decimal("1.00")}
        for res_id, ev in valuation_marks.items():
            if not isinstance(res_id, str) or not res_id:
                raise ValueError("valuation_marks keys must be non-empty strings")
            if isinstance(ev, PriceEvidence):
                if ev.resource_id != res_id or (
                    ev.knowledge_time is not None
                    and parse_utc_timestamp(ev.knowledge_time) > settlement_dt
                ):
                    raise ValueError(
                        "Valuation evidence has wrong resource or future knowledge time"
                    )
                marks[res_id] = ev.price
            elif isinstance(ev, Decimal) and not isinstance(ev, bool):
                marks[res_id] = ev
            else:
                raise TypeError(f"valuation_marks[{res_id!r}] must be a Decimal or PriceEvidence")

        action = pending.requested_action
        outcome_id = _settlement_id("set-out", pending, settlement_round_id)

        target_observation = _select_target_observation(
            tuple(
                o
                for o in all_observations
                if o.snapshot_id == episode_def.dataset_snapshot.snapshot_id
            ),
            pending.target_bar_rule.series_id,
            settlement_dt,
            expected_open_dt,
        )
        if target_observation is None:
            return DeferredSettlementResult(
                pending_transition=pending,
                settlement_outcome=None,
                deferred_transition=None,
                next_account=current_account,
                is_settled=False,
                is_still_pending=True,
            )

        raw_price = target_observation.payload.get("open")
        execution_price: Decimal | None = None
        if raw_price is not None and not isinstance(raw_price, bool):
            try:
                candidate_price = Decimal(str(raw_price))
                if candidate_price.is_finite() and candidate_price > Decimal("0"):
                    execution_price = candidate_price
            except (InvalidOperation, ValueError):
                execution_price = None

        if execution_price is None:
            outcome = SettlementOutcome(
                settlement_outcome_id=outcome_id,
                pending_transition_id=pending.pending_transition_id,
                decision_id=pending.decision_id,
                round_id=settlement_round_id,
                policy_id=pending.policy_id,
                status=SettlementStatus.REJECTED,
                settled_at=settlement_time,
                rejection_reasons=(
                    RejectionReason(
                        code=REJECTION_INVALID_EXECUTION_PRICE,
                        message=f"Execution price is missing or invalid: {raw_price!r}",
                        violating_field="payload.open",
                    ),
                ),
                applied_transition_id=None,
                settlement_evidence={},
            )
            return DeferredSettlementResult(
                pending_transition=pending,
                settlement_outcome=outcome,
                deferred_transition=None,
                next_account=current_account,
                is_settled=False,
                is_still_pending=False,
            )

        fill_time = target_observation.payload["open_time"]
        full_evidence_base = {
            "observation_id": target_observation.observation_id,
            "selected_revision": target_observation.revision,
            "execution_fill_time": fill_time,
            "observation_knowledge_time": target_observation.knowledge_time,
            "execution_price": format_decimal(execution_price),
        }

        rejection_reasons: list[RejectionReason] = []

        balances_map: dict[str, Decimal] = {
            b.resource_id: b.quantity for b in current_account.balances
        }
        required_marks = {
            res_id for res_id in balances_map if res_id != episode_def.reference_resource_id
        }
        required_marks.add(action.resource_id)
        for res_id in sorted(required_marks):
            mark = marks.get(res_id)
            if (
                mark is None
                or not isinstance(mark, Decimal)
                or mark.is_nan()
                or mark.is_infinite()
                or mark <= Decimal("0")
            ):
                rejection_reasons.append(
                    RejectionReason(
                        code=REJECTION_MISSING_VALUATION_MARK,
                        message=f"Missing or invalid valuation mark for resource {res_id}",
                        violating_field=f"balances[{res_id}]",
                    )
                )

        cash_delta, asset_delta, cost_items, action_cost = _compute_action_economics(
            action, execution_price, episode_def.rules.cost_model, episode_def.reference_resource_id
        )

        available_cash = balances_map.get(episode_def.reference_resource_id, Decimal("0.00"))
        existing_asset_qty = balances_map.get(action.resource_id, Decimal("0.00"))

        new_cash = available_cash + cash_delta
        if not episode_def.rules.allow_borrowing and new_cash < Decimal("0.00"):
            rejection_reasons.append(
                RejectionReason(
                    code=REJECTION_INSUFFICIENT_FUNDS_AT_SETTLEMENT,
                    message=(
                        f"Required balance exceeds available "
                        f"{episode_def.reference_resource_id} balance {available_cash} "
                        f"and borrowing is disabled (resulting: {new_cash})"
                    ),
                    violating_field="requested_action",
                )
            )

        new_asset_qty = existing_asset_qty + asset_delta
        if not episode_def.rules.allow_short_positions and new_asset_qty < Decimal("0.00"):
            rejection_reasons.append(
                RejectionReason(
                    code=REJECTION_SHORT_POSITIONS_FORBIDDEN,
                    message=(
                        f"Negative balance in {action.resource_id} resulting from "
                        "settlement is forbidden"
                    ),
                    violating_field="requested_action",
                )
            )

        if rejection_reasons:
            rejection_reasons.sort(key=lambda r: (r.code, r.violating_field or "", r.message))
            evidence: dict[str, object] = dict(full_evidence_base)
            evidence["total_fee_deducted"] = "0.00"
            if any(r.code == REJECTION_INSUFFICIENT_FUNDS_AT_SETTLEMENT for r in rejection_reasons):
                evidence["cash_available"] = format_decimal(available_cash)
                evidence["cash_required"] = format_decimal(max(Decimal("0.00"), -cash_delta))
            outcome = SettlementOutcome(
                settlement_outcome_id=outcome_id,
                pending_transition_id=pending.pending_transition_id,
                decision_id=pending.decision_id,
                round_id=settlement_round_id,
                policy_id=pending.policy_id,
                status=SettlementStatus.REJECTED,
                settled_at=settlement_time,
                rejection_reasons=tuple(rejection_reasons),
                applied_transition_id=None,
                settlement_evidence=evidence,
            )
            return DeferredSettlementResult(
                pending_transition=pending,
                settlement_outcome=outcome,
                deferred_transition=None,
                next_account=current_account,
                is_settled=False,
                is_still_pending=False,
            )

        # --- Feasible: mint the settled account state and deferred transition ---
        ref_id = episode_def.reference_resource_id
        deltas_map: dict[str, Decimal] = {ref_id: cash_delta, action.resource_id: asset_delta}
        if action.resource_id not in balances_map:
            balances_map[action.resource_id] = Decimal("0.00")

        new_balances: list[BalanceItem] = []
        allocated_val = Decimal("0.00")
        for res_id, old_qty in balances_map.items():
            if res_id == ref_id:
                continue
            final_qty = old_qty + deltas_map.get(res_id, Decimal("0.00"))
            new_balances.append(
                BalanceItem(
                    resource_id=res_id, quantity=final_qty, reserved_quantity=Decimal("0.00")
                )
            )
            allocated_val += (final_qty * marks[res_id]).quantize(_CENTS, rounding=ROUND_HALF_EVEN)

        final_cash = (available_cash + cash_delta).quantize(_CENTS, rounding=ROUND_HALF_EVEN)
        new_balances.append(
            BalanceItem(resource_id=ref_id, quantity=final_cash, reserved_quantity=Decimal("0.00"))
        )
        net_val = (final_cash + allocated_val).quantize(_CENTS, rounding=ROUND_HALF_EVEN)
        new_balances.sort(key=lambda b: (b.resource_id != ref_id, b.resource_id))

        new_cum_costs: list[CumulativeCostItem] = []
        old_cost_map = {c.cost_type: c.amount for c in current_account.cumulative_costs}
        old_cost_map["TRANSACTION_FEE"] = (
            old_cost_map.get("TRANSACTION_FEE", Decimal("0.00")) + action_cost
        )
        for c_type, c_amt in old_cost_map.items():
            new_cum_costs.append(CumulativeCostItem(cost_type=c_type, amount=c_amt))

        account_before_hash = current_account.compute_hash()
        account_state_id = _settlement_id("acc-state", pending, settlement_round_id)
        provisional_account = VirtualAccountState(
            account_state_id=account_state_id,
            policy_id=current_account.policy_id,
            round_index=settlement_round_index,
            as_of_time=settlement_time,
            balances=tuple(new_balances),
            cumulative_costs=tuple(new_cum_costs),
            reference_valuation=ReferenceValuation(
                reference_resource_id=ref_id,
                unallocated_cash=final_cash,
                allocated_resources_value=allocated_val,
                net_total_value=net_val,
            ),
            parent_state_hash=account_before_hash,
        )
        account_after_hash = provisional_account.compute_hash()

        transition_id = _settlement_id("trn", pending, settlement_round_id)
        resource_deltas = (
            ResourceDelta(
                resource_id=action.resource_id,
                delta_quantity=asset_delta,
                valuation_price=execution_price,
            ),
            ResourceDelta(
                resource_id=ref_id,
                delta_quantity=cash_delta,
                valuation_price=Decimal("1.00"),
            ),
        )
        deferred_transition = DeferredTransitionRecord(
            transition_id=transition_id,
            round_id=settlement_round_id,
            policy_id=pending.policy_id,
            settlement_outcome_id=outcome_id,
            economic_fill_time=fill_time,
            effective_time=settlement_time,
            resource_deltas=resource_deltas,
            costs=cost_items,
            total_cost_reference_unit=action_cost,
            account_state_before_hash=account_before_hash,
            account_state_after_hash=account_after_hash,
        )

        settled_evidence = dict(full_evidence_base)
        settled_evidence["total_fee_deducted"] = format_decimal(action_cost)
        outcome = SettlementOutcome(
            settlement_outcome_id=outcome_id,
            pending_transition_id=pending.pending_transition_id,
            decision_id=pending.decision_id,
            round_id=settlement_round_id,
            policy_id=pending.policy_id,
            status=SettlementStatus.SETTLED,
            settled_at=settlement_time,
            rejection_reasons=(),
            applied_transition_id=transition_id,
            settlement_evidence=settled_evidence,
        )

        return DeferredSettlementResult(
            pending_transition=pending,
            settlement_outcome=outcome,
            deferred_transition=deferred_transition,
            next_account=provisional_account,
            is_settled=True,
            is_still_pending=False,
        )

    @staticmethod
    @_settlement_decimal_context
    def terminate_unsettled(
        episode_def: EpisodeDefinition,
        current_account: VirtualAccountState,
        pending: PendingTransitionRecord,
        settlement_round_id: str,
        settlement_time: str,
        reason_code: str,
        reason_message: str | None = None,
        *,
        admission_account: VirtualAccountState | None = None,
    ) -> DeferredSettlementResult:
        """Record an exogenous terminal rejection the caller has already decided.

        This service does not decide settlement-window timeouts, episode
        termination, or cancellation; the caller (a future runner) does, and
        calls this entry point only to record the terminal outcome correctly.
        """
        _validate_common_context(
            episode_def,
            current_account,
            pending,
            settlement_round_id,
            settlement_time,
            admission_account,
        )

        if reason_code not in _TERMINATE_REASON_CODES:
            raise ValueError(
                f"reason_code must be one of {sorted(_TERMINATE_REASON_CODES)}, got {reason_code!r}"
            )

        if reason_message is not None and (
            not isinstance(reason_message, str) or not reason_message
        ):
            raise ValueError("reason_message must be a non-empty string when provided")
        message = (
            reason_message
            if reason_message is not None
            else _DEFAULT_TERMINATE_MESSAGES[reason_code]
        )

        outcome = SettlementOutcome(
            settlement_outcome_id=_settlement_id("set-out", pending, settlement_round_id),
            pending_transition_id=pending.pending_transition_id,
            decision_id=pending.decision_id,
            round_id=settlement_round_id,
            policy_id=pending.policy_id,
            status=SettlementStatus.REJECTED,
            settled_at=settlement_time,
            rejection_reasons=(
                RejectionReason(code=reason_code, message=message, violating_field=None),
            ),
            applied_transition_id=None,
            settlement_evidence={},
        )
        return DeferredSettlementResult(
            pending_transition=pending,
            settlement_outcome=outcome,
            deferred_transition=None,
            next_account=current_account,
            is_settled=False,
            is_still_pending=False,
        )
