"""Decision execution, validation, cost calculation, and account transition service."""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping

from simulator.application.ports.pricing import (
    PriceEvidence,
    PriceResolutionResult,
)
from simulator.domain.lifecycle import ActionType, CostType, DecisionStatus
from simulator.domain.models import (
    BalanceItem,
    CostItem,
    CumulativeCostItem,
    DecisionOutcome,
    EpisodeDefinition,
    ObservationRecord,
    ProposedDecision,
    ReferenceValuation,
    RejectionReason,
    ResourceDelta,
    TransitionRecord,
    VirtualAccountState,
)


class ExecutionService:
    """Evaluates proposed decisions, applies transitions, and calculates deterministic costs."""

    @staticmethod
    def evaluate_and_apply_decision(
        episode_def: EpisodeDefinition,
        current_account: VirtualAccountState,
        proposal: ProposedDecision,
        round_id: str,
        round_index: int,
        effective_time: str,
        pricing_result: PriceResolutionResult | None = None,
        valuation_marks: Mapping[str, Decimal | PriceEvidence] | None = None,
        execution_prices: Mapping[str, Decimal | PriceEvidence] | None = None,
        eligible_observations: tuple[ObservationRecord, ...] | None = None,
    ) -> tuple[DecisionOutcome, TransitionRecord | None, VirtualAccountState]:
        """Validate proposal, calculate transition costs and resource deltas,

        and produce new account state.
        """
        account_before_hash = current_account.compute_hash()
        rejection_reasons: list[RejectionReason] = []

        # 1. Policy ownership & cross-policy contamination check
        if proposal.policy_id != current_account.policy_id:
            rejection_reasons.append(
                RejectionReason(
                    code="CROSS_POLICY_ACCOUNT_CONTAMINATION",
                    message=(
                        f"Proposal policy_id {proposal.policy_id} does not match "
                        f"account policy_id {current_account.policy_id}"
                    ),
                    violating_field="policy_id",
                )
            )

        for idx, action in enumerate(proposal.requested_actions):
            src_policy = action.parameters.get("source_policy_id")
            if src_policy is not None and src_policy != current_account.policy_id:
                rejection_reasons.append(
                    RejectionReason(
                        code="CROSS_POLICY_ACCOUNT_CONTAMINATION",
                        message=f"Action references external source_policy_id {src_policy}",
                        violating_field=f"requested_actions[{idx}].parameters.source_policy_id",
                    )
                )

        # 2. Max transition count constraint
        max_trans = episode_def.rules.constraints.max_transition_count_per_round
        if max_trans is not None and len(proposal.requested_actions) > max_trans:
            rejection_reasons.append(
                RejectionReason(
                    code="TRANSITION_LIMIT_EXCEEDED",
                    message=(
                        f"Action count {len(proposal.requested_actions)} exceeds limit {max_trans}"
                    ),
                    violating_field="requested_actions",
                )
            )

        # 3. Resolve and unpack price maps
        ref_id = episode_def.reference_resource_id
        marks_map: dict[str, Decimal] = {ref_id: Decimal("1.00")}
        exec_map: dict[str, Decimal] = {ref_id: Decimal("1.00")}

        if pricing_result is not None:
            if not pricing_result.is_valid:
                rejection_reasons.extend(pricing_result.rejection_reasons)
            for res, ev in pricing_result.valuation_marks.items():
                marks_map[res] = ev.price if isinstance(ev, PriceEvidence) else Decimal(str(ev))
            for res, ev in pricing_result.execution_prices.items():
                exec_map[res] = ev.price if isinstance(ev, PriceEvidence) else Decimal(str(ev))

        elif valuation_marks is not None or execution_prices is not None:
            if valuation_marks:
                for res, ev in valuation_marks.items():
                    marks_map[res] = ev.price if isinstance(ev, PriceEvidence) else Decimal(str(ev))
            if execution_prices:
                for res, ev in execution_prices.items():
                    exec_map[res] = ev.price if isinstance(ev, PriceEvidence) else Decimal(str(ev))

        elif eligible_observations is not None:
            # Domain-neutral fallback for synthetic observations: resolve latest eligible price
            for obs in eligible_observations:
                for res_id in [b.resource_id for b in current_account.balances] + [
                    a.resource_id for a in proposal.requested_actions
                ]:
                    if obs.series_id in (f"{res_id}_PRICE", res_id):
                        raw_p = obs.payload.get("price", obs.payload.get("close"))
                        if raw_p is not None:
                            try:
                                p_dec = Decimal(str(raw_p))
                                if (
                                    not p_dec.is_nan()
                                    and not p_dec.is_infinite()
                                    and p_dec > Decimal("0")
                                ):
                                    marks_map[res_id] = p_dec
                                    exec_map[res_id] = p_dec
                            except Exception:
                                pass
        else:
            rejection_reasons.append(
                RejectionReason(
                    code="MISSING_PRICING_CONTEXT",
                    message=(
                        "No pricing context, explicit marks, or observations provided "
                        "to ExecutionService"
                    ),
                )
            )

        # Lookup balances
        balances_map: dict[str, Decimal] = {
            b.resource_id: b.quantity for b in current_account.balances
        }
        available_cash = balances_map.get(ref_id, Decimal("0.00"))

        # 4. Check that all non-reference held balances have a valid positive mark
        for res_id in balances_map.keys():
            if res_id == ref_id:
                continue
            if (
                res_id not in marks_map
                or marks_map[res_id] <= Decimal("0")
                or marks_map[res_id].is_nan()
            ):
                rejection_reasons.append(
                    RejectionReason(
                        code="MISSING_VALUATION_MARK",
                        message=f"Missing or invalid valuation mark for held resource {res_id}",
                        violating_field=f"balances[{res_id}]",
                    )
                )

        # 5. Check action feasibility & compute deltas
        deltas_map: dict[str, Decimal] = {k: Decimal("0.00") for k in balances_map.keys()}
        cost_items: list[CostItem] = []
        total_cost = Decimal("0.00")
        cost_model = episode_def.rules.cost_model

        for idx, action in enumerate(proposal.requested_actions):
            res_id = action.resource_id
            if res_id not in balances_map and res_id not in deltas_map:
                deltas_map[res_id] = Decimal("0.00")
                balances_map[res_id] = Decimal("0.00")

            if action.action_type == ActionType.HOLD:
                continue

            # Validate execution price for action resource
            if (
                res_id not in exec_map
                or exec_map[res_id] <= Decimal("0")
                or exec_map[res_id].is_nan()
            ):
                rejection_reasons.append(
                    RejectionReason(
                        code="MISSING_EXECUTION_PRICE",
                        message=f"Missing or invalid execution price for resource {res_id}",
                        violating_field=f"requested_actions[{idx}].resource_id",
                    )
                )
                continue

            # If opening a new position, validate that a mark is also available for valuation
            if (
                res_id not in marks_map
                or marks_map[res_id] <= Decimal("0")
                or marks_map[res_id].is_nan()
            ):
                rejection_reasons.append(
                    RejectionReason(
                        code="MISSING_VALUATION_MARK",
                        message=f"Missing or invalid valuation mark for resource {res_id}",
                        violating_field=f"requested_actions[{idx}].resource_id",
                    )
                )
                continue

            exec_price = exec_map[res_id]

            if action.action_type == ActionType.ALLOCATE:
                qty = action.quantity
                if qty < Decimal("0"):
                    rejection_reasons.append(
                        RejectionReason(
                            code="INVALID_QUANTITY",
                            message=f"Allocation quantity must be non-negative, got {qty}",
                            violating_field=f"requested_actions[{idx}].quantity",
                        )
                    )
                    continue

                # Notional value and fees
                notional = (qty * exec_price).quantize(Decimal("0.01"))
                linear_fee = (notional * cost_model.linear_transaction_fee_rate).quantize(
                    Decimal("0.01")
                )
                fixed_fee = (
                    cost_model.fixed_transaction_fee if qty > Decimal("0") else Decimal("0.00")
                )
                action_cost = linear_fee + fixed_fee

                total_cost += action_cost
                deltas_map[res_id] += qty
                deltas_map[ref_id] -= notional + action_cost

                if linear_fee > Decimal("0"):
                    cost_items.append(
                        CostItem(
                            cost_type=CostType.TRANSACTION_FEE,
                            resource_id=ref_id,
                            amount=linear_fee,
                        )
                    )
                if fixed_fee > Decimal("0"):
                    cost_items.append(
                        CostItem(
                            cost_type=CostType.TRANSACTION_FEE,
                            resource_id=ref_id,
                            amount=fixed_fee,
                        )
                    )

            elif action.action_type == ActionType.TRANSFER:
                qty = action.quantity
                notional = (abs(qty) * exec_price).quantize(Decimal("0.01"))
                linear_fee = (notional * cost_model.linear_transaction_fee_rate).quantize(
                    Decimal("0.01")
                )
                fixed_fee = (
                    cost_model.fixed_transaction_fee if abs(qty) > Decimal("0") else Decimal("0.00")
                )
                action_cost = linear_fee + fixed_fee

                total_cost += action_cost
                deltas_map[res_id] += qty

                if qty >= Decimal("0"):
                    deltas_map[ref_id] -= notional + action_cost
                else:
                    deltas_map[ref_id] += notional - action_cost

                if action_cost > Decimal("0"):
                    cost_items.append(
                        CostItem(
                            cost_type=CostType.TRANSACTION_FEE,
                            resource_id=ref_id,
                            amount=action_cost,
                        )
                    )

        # 6. Check balance feasibility if borrowing/shorting not allowed
        new_cash = available_cash + deltas_map[ref_id]
        if not episode_def.rules.allow_borrowing and new_cash < Decimal("0.00"):
            rejection_reasons.append(
                RejectionReason(
                    code="INSUFFICIENT_UNALLOCATED_RESOURCE",
                    message=(
                        f"Required balance exceeds available {ref_id} balance {available_cash} "
                        f"and borrowing is disabled (resulting: {new_cash})"
                    ),
                    violating_field="requested_actions",
                )
            )

        if not episode_def.rules.allow_short_positions:
            for r_id, d_qty in deltas_map.items():
                if r_id != ref_id and (balances_map.get(r_id, Decimal("0.00")) + d_qty) < Decimal(
                    "0.00"
                ):
                    rejection_reasons.append(
                        RejectionReason(
                            code="SHORT_POSITIONS_FORBIDDEN",
                            message=(
                                f"Negative balance in {r_id} resulting from transition is forbidden"
                            ),
                            violating_field="requested_actions",
                        )
                    )

        # 7. If any rejection occurred, return unchanged account
        if rejection_reasons:
            rejection_reasons.sort(key=lambda r: (r.code, r.violating_field or "", r.message))
            outcome = DecisionOutcome(
                outcome_id=f"dec-out_{round_id}_{proposal.policy_id}",
                decision_id=proposal.decision_id,
                round_id=round_id,
                policy_id=proposal.policy_id,
                status=DecisionStatus.REJECTED,
                rejection_reasons=tuple(rejection_reasons),
                evaluated_at=effective_time,
                applied_transition_id=None,
            )
            # Account remains unchanged (with incremented round_index and new as_of_time)
            next_account = VirtualAccountState(
                account_state_id=f"acc-state_{round_id}_{proposal.policy_id}",
                policy_id=current_account.policy_id,
                round_index=round_index,
                as_of_time=effective_time,
                balances=current_account.balances,
                cumulative_costs=current_account.cumulative_costs,
                reference_valuation=current_account.reference_valuation,
                parent_state_hash=account_before_hash,
            )
            return outcome, None, next_account

        # 8. Build next account state on acceptance
        new_balances: list[BalanceItem] = []
        allocated_val = Decimal("0.00")
        for res_id, old_qty in balances_map.items():
            if res_id == ref_id:
                continue
            # Preserve fractional asset quantities without rounding to 2 decimals
            final_qty = old_qty + deltas_map[res_id]
            new_balances.append(
                BalanceItem(
                    resource_id=res_id,
                    quantity=final_qty,
                    reserved_quantity=Decimal("0.00"),
                )
            )
            allocated_val += (final_qty * marks_map[res_id]).quantize(Decimal("0.01"))

        final_cash = (available_cash + deltas_map[ref_id]).quantize(Decimal("0.01"))
        new_balances.append(
            BalanceItem(
                resource_id=ref_id,
                quantity=final_cash,
                reserved_quantity=Decimal("0.00"),
            )
        )
        net_val = (final_cash + allocated_val).quantize(Decimal("0.01"))

        # Update cumulative costs
        new_cum_costs: list[CumulativeCostItem] = []
        old_cost_map = {c.cost_type: c.amount for c in current_account.cumulative_costs}
        old_cost_map["TRANSACTION_FEE"] = (
            old_cost_map.get("TRANSACTION_FEE", Decimal("0.00")) + total_cost
        )
        for c_type, c_amt in old_cost_map.items():
            new_cum_costs.append(CumulativeCostItem(cost_type=c_type, amount=c_amt))

        # Sort balances deterministically (reference resource first, then alphabetical)
        new_balances.sort(key=lambda b: (b.resource_id != ref_id, b.resource_id))

        # Provisional next account (to compute after hash)
        provisional_account = VirtualAccountState(
            account_state_id=f"acc-state_{round_id}_{proposal.policy_id}",
            policy_id=current_account.policy_id,
            round_index=round_index,
            as_of_time=effective_time,
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

        # Build resource deltas list for transition
        resource_deltas: list[ResourceDelta] = []
        for res_id, d_qty in deltas_map.items():
            if d_qty != Decimal("0.00"):
                val_p = exec_map.get(res_id, marks_map.get(res_id, Decimal("1.00")))
                resource_deltas.append(
                    ResourceDelta(
                        resource_id=res_id,
                        delta_quantity=d_qty,
                        valuation_price=val_p,
                    )
                )

        if resource_deltas:
            transition_id = f"trn_{round_id}_{proposal.policy_id}"
            transition = TransitionRecord(
                transition_id=transition_id,
                round_id=round_id,
                policy_id=proposal.policy_id,
                outcome_id=f"dec-out_{round_id}_{proposal.policy_id}",
                effective_time=effective_time,
                resource_deltas=tuple(resource_deltas),
                costs=tuple(cost_items),
                total_cost_reference_unit=total_cost,
                account_state_before_hash=account_before_hash,
                account_state_after_hash=account_after_hash,
            )
            applied_transition_id: str | None = transition_id
        else:
            transition = None
            applied_transition_id = None

        outcome = DecisionOutcome(
            outcome_id=f"dec-out_{round_id}_{proposal.policy_id}",
            decision_id=proposal.decision_id,
            round_id=round_id,
            policy_id=proposal.policy_id,
            status=DecisionStatus.ACCEPTED,
            rejection_reasons=(),
            evaluated_at=effective_time,
            applied_transition_id=applied_transition_id,
        )

        return outcome, transition, provisional_account
