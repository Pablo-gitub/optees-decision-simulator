"""Deferred decision admission service and admission result DTO (DS-02D2B1)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Mapping

from simulator.domain.canonical import compute_record_hash
from simulator.domain.lifecycle import ActionType, DecisionStatus, PendingStatus
from simulator.domain.models import (
    DecisionOutcome,
    EpisodeDefinition,
    PendingTransitionRecord,
    ProposedDecision,
    RejectionReason,
    TargetBarRule,
    VirtualAccountState,
)
from simulator.domain.time import parse_utc_timestamp

# Application-owned rejection codes for deferred admission
REJECTION_CROSS_POLICY_ACCOUNT_CONTAMINATION: Final[str] = "CROSS_POLICY_ACCOUNT_CONTAMINATION"
REJECTION_POLICY_VERSION_MISMATCH: Final[str] = "POLICY_VERSION_MISMATCH"
REJECTION_INVALID_DECISION_CONTEXT: Final[str] = "INVALID_DECISION_CONTEXT"
REJECTION_UNSUPPORTED_DESIRED_ALLOCATIONS: Final[str] = "UNSUPPORTED_DESIRED_ALLOCATIONS"
REJECTION_TRANSITION_LIMIT_EXCEEDED: Final[str] = "TRANSITION_LIMIT_EXCEEDED"
REJECTION_INVALID_ACTION_SYNTAX: Final[str] = "INVALID_ACTION_SYNTAX"
REJECTION_UNSUPPORTED_RESOURCE: Final[str] = "UNSUPPORTED_RESOURCE"
REJECTION_POLICY_HAS_PENDING_SETTLEMENT: Final[str] = "POLICY_HAS_PENDING_SETTLEMENT"
REJECTION_DECISION_ID_CONFLICT: Final[str] = "DECISION_ID_CONFLICT"

_ROUND_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^rnd_[a-zA-Z0-9_-]+$")
_DECISION_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^dec-prop_[a-zA-Z0-9_-]+$")
_POLICY_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^pol-def_[a-zA-Z0-9_-]+$")
_POLICY_VERSION_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^pol-ver_[a-zA-Z0-9_-]+$")


@dataclass(frozen=True)
class DeferredAdmissionResult:
    """Immutable result of a deferred decision admission evaluation."""

    pending_transition: PendingTransitionRecord | None
    decision_outcome: DecisionOutcome | None
    is_newly_admitted: bool
    is_reused_pending: bool

    def __post_init__(self) -> None:
        if self.is_newly_admitted and self.is_reused_pending:
            raise ValueError("Result cannot be both newly admitted and reused pending")
        if self.is_newly_admitted or self.is_reused_pending:
            if self.decision_outcome is not None:
                raise ValueError(
                    "Admitted or reused pending cannot have an immediate decision outcome"
                )
            if self.pending_transition is None:
                raise ValueError(
                    "Admitted or reused pending must include a pending_transition record"
                )
        else:
            if self.decision_outcome is None:
                raise ValueError(
                    "HOLD or REJECTED admission results must include an immediate decision outcome"
                )


def _safe_proposal_hash(proposal: ProposedDecision) -> str:
    try:
        return proposal.compute_hash()
    except Exception:
        raw_payload = {
            "$type": "malformed_proposed_decision",
            "decision_id": str(proposal.decision_id),
            "round_id": str(proposal.round_id),
            "policy_id": str(proposal.policy_id),
            "policy_version_id": str(proposal.policy_version_id),
            "knowledge_cutoff": str(proposal.knowledge_cutoff),
            "generated_at": str(proposal.generated_at),
            "actions": [
                {
                    "action_type": (
                        a.action_type.value
                        if hasattr(a.action_type, "value")
                        else str(a.action_type)
                    ),
                    "resource_id": str(a.resource_id),
                    "quantity": str(a.quantity),
                }
                for a in proposal.requested_actions
            ],
        }
        return compute_record_hash(raw_payload)


def _compute_outcome_id(
    episode_id: str,
    round_id: str,
    policy_id: str,
    decision_id: str,
    proposal_hash: str,
) -> str:
    payload = {
        "$type": "decision_outcome_identity",
        "episode_id": episode_id,
        "round_id": round_id,
        "policy_id": policy_id,
        "decision_id": decision_id,
        "proposal_hash": proposal_hash,
    }
    digest = compute_record_hash(payload)
    return f"dec-out_{digest[7:]}"


def _compute_pending_transition_id(
    episode_id: str,
    round_id: str,
    policy_id: str,
    decision_id: str,
) -> str:
    payload = {
        "$type": "pending_transition_identity",
        "episode_id": episode_id,
        "round_id": round_id,
        "policy_id": policy_id,
        "decision_id": decision_id,
    }
    digest = compute_record_hash(payload)
    return f"pnd_{digest[7:]}"


class DeferredAdmissionService:
    """Pure, stateless admission service for proposed decisions in deferred execution."""

    @staticmethod
    def admit_decision(
        episode_def: EpisodeDefinition,
        current_account: VirtualAccountState,
        proposal: ProposedDecision,
        authoritative_round_id: str,
        authoritative_cutoff: str,
        resource_to_series_map: Mapping[str, str],
        current_pending: PendingTransitionRecord | None = None,
    ) -> DeferredAdmissionResult:
        """Validate context, admit order or reject proposal, or handle valid HOLD.

        Does not perform pricing, financial checks, or account mutation.
        """
        # 1. Caller context validations (exceptions on caller errors)
        if not isinstance(episode_def, EpisodeDefinition):
            raise TypeError(
                f"episode_def must be an EpisodeDefinition instance, got {type(episode_def)}"
            )
        if not isinstance(current_account, VirtualAccountState):
            raise TypeError(
                "current_account must be a VirtualAccountState instance, "
                f"got {type(current_account)}"
            )
        if not isinstance(proposal, ProposedDecision):
            raise TypeError(f"proposal must be a ProposedDecision instance, got {type(proposal)}")

        if not isinstance(authoritative_round_id, str) or not _ROUND_ID_PATTERN.match(
            authoritative_round_id
        ):
            raise ValueError(f"authoritative_round_id is malformed: {authoritative_round_id!r}")

        if not isinstance(authoritative_cutoff, str):
            raise TypeError(f"authoritative_cutoff must be a str, got {type(authoritative_cutoff)}")
        cutoff_instant = parse_utc_timestamp(authoritative_cutoff)

        account_instant = parse_utc_timestamp(current_account.as_of_time)
        if account_instant > cutoff_instant:
            raise ValueError(
                f"current_account.as_of_time ({current_account.as_of_time}) "
                f"cannot be later than authoritative_cutoff ({authoritative_cutoff})"
            )

        if not _DECISION_ID_PATTERN.match(proposal.decision_id):
            raise ValueError(f"proposal.decision_id is malformed: {proposal.decision_id!r}")
        if not _POLICY_ID_PATTERN.match(proposal.policy_id):
            raise ValueError(f"proposal.policy_id is malformed: {proposal.policy_id!r}")
        if not _POLICY_VERSION_ID_PATTERN.match(proposal.policy_version_id):
            raise ValueError(
                f"proposal.policy_version_id is malformed: {proposal.policy_version_id!r}"
            )
        if not _POLICY_ID_PATTERN.match(current_account.policy_id):
            raise ValueError(
                f"current_account.policy_id is malformed: {current_account.policy_id!r}"
            )

        if isinstance(resource_to_series_map, bool) or not isinstance(
            resource_to_series_map, Mapping
        ):
            raise TypeError(
                f"resource_to_series_map must be a Mapping, got {type(resource_to_series_map)}"
            )

        mapping_copy: dict[str, str] = {}
        for k, v in resource_to_series_map.items():
            if not isinstance(k, str) or not k:
                raise ValueError("resource_to_series_map keys must be non-empty strings")
            if not isinstance(v, str) or not v:
                raise ValueError("resource_to_series_map values must be non-empty strings")
            mapping_copy[k] = v

        if current_pending is not None:
            if not isinstance(current_pending, PendingTransitionRecord):
                raise TypeError(
                    "current_pending must be a PendingTransitionRecord instance, "
                    f"got {type(current_pending)}"
                )
            if current_pending.policy_id != current_account.policy_id:
                raise ValueError(
                    f"current_pending policy_id '{current_pending.policy_id}' "
                    f"does not match current_account policy_id '{current_account.policy_id}'"
                )

        # 2. Proposal structural and contextual checks
        rejection_reasons: list[RejectionReason] = []

        # Policy ownership & pinned policy version
        if proposal.policy_id != current_account.policy_id:
            rejection_reasons.append(
                RejectionReason(
                    code=REJECTION_CROSS_POLICY_ACCOUNT_CONTAMINATION,
                    message=(
                        f"Proposal policy_id '{proposal.policy_id}' does not match "
                        f"account policy_id '{current_account.policy_id}'"
                    ),
                    violating_field="policy_id",
                )
            )

        pinned_versions = {pv.policy_id: pv.policy_version_id for pv in episode_def.policy_versions}
        if proposal.policy_id not in pinned_versions:
            rejection_reasons.append(
                RejectionReason(
                    code=REJECTION_POLICY_VERSION_MISMATCH,
                    message=(
                        f"Proposal policy_id '{proposal.policy_id}' is not pinned "
                        "in episode policy versions"
                    ),
                    violating_field="policy_id",
                )
            )
        elif proposal.policy_version_id != pinned_versions[proposal.policy_id]:
            rejection_reasons.append(
                RejectionReason(
                    code=REJECTION_POLICY_VERSION_MISMATCH,
                    message=(
                        f"Proposal policy_version_id '{proposal.policy_version_id}' does not match "
                        f"pinned version '{pinned_versions[proposal.policy_id]}'"
                    ),
                    violating_field="policy_version_id",
                )
            )

        # Authoritative context checks
        if proposal.round_id != authoritative_round_id:
            rejection_reasons.append(
                RejectionReason(
                    code=REJECTION_INVALID_DECISION_CONTEXT,
                    message=(
                        f"Proposal round_id '{proposal.round_id}' does not match "
                        f"authoritative round_id '{authoritative_round_id}'"
                    ),
                    violating_field="round_id",
                )
            )

        prop_cutoff = parse_utc_timestamp(proposal.knowledge_cutoff)
        if prop_cutoff != cutoff_instant:
            rejection_reasons.append(
                RejectionReason(
                    code=REJECTION_INVALID_DECISION_CONTEXT,
                    message=(
                        f"Proposal knowledge_cutoff '{proposal.knowledge_cutoff}' does not match "
                        f"authoritative cutoff '{authoritative_cutoff}'"
                    ),
                    violating_field="knowledge_cutoff",
                )
            )

        prop_generated = parse_utc_timestamp(proposal.generated_at)
        if prop_generated != cutoff_instant:
            rejection_reasons.append(
                RejectionReason(
                    code=REJECTION_INVALID_DECISION_CONTEXT,
                    message=(
                        f"Proposal generated_at '{proposal.generated_at}' does not match "
                        f"authoritative cutoff '{authoritative_cutoff}'"
                    ),
                    violating_field="generated_at",
                )
            )

        # Desired allocations check
        if len(proposal.desired_allocations) > 0:
            rejection_reasons.append(
                RejectionReason(
                    code=REJECTION_UNSUPPORTED_DESIRED_ALLOCATIONS,
                    message=(
                        "Desired allocations are not supported for deferred admission; "
                        f"found {len(proposal.desired_allocations)} item(s)"
                    ),
                    violating_field="desired_allocations",
                )
            )

        # Action cardinality & transition limit constraint
        action_count = len(proposal.requested_actions)
        if action_count != 1:
            rejection_reasons.append(
                RejectionReason(
                    code=REJECTION_INVALID_ACTION_SYNTAX,
                    message=f"Proposal must contain exactly 1 requested action, got {action_count}",
                    violating_field="requested_actions",
                )
            )

        max_trans = episode_def.rules.constraints.max_transition_count_per_round
        if max_trans is not None and action_count > max_trans:
            rejection_reasons.append(
                RejectionReason(
                    code=REJECTION_TRANSITION_LIMIT_EXCEEDED,
                    message=f"Action count {action_count} exceeds limit {max_trans}",
                    violating_field="requested_actions",
                )
            )

        # Detailed action syntax, parameters, quantity, and resource checks
        if action_count == 1:
            action = proposal.requested_actions[0]

            # Parameters check
            params = action.parameters
            unsupported_params = set(params.keys()) - {"source_policy_id"}
            if unsupported_params:
                rejection_reasons.append(
                    RejectionReason(
                        code=REJECTION_INVALID_ACTION_SYNTAX,
                        message=f"Unsupported action parameters: {sorted(unsupported_params)}",
                        violating_field="requested_actions[0].parameters",
                    )
                )
            if "source_policy_id" in params:
                src_pol = params["source_policy_id"]
                if src_pol != current_account.policy_id:
                    rejection_reasons.append(
                        RejectionReason(
                            code=REJECTION_CROSS_POLICY_ACCOUNT_CONTAMINATION,
                            message=f"Action references external source_policy_id '{src_pol}'",
                            violating_field="requested_actions[0].parameters.source_policy_id",
                        )
                    )

            # Action type and quantity
            qty = action.quantity
            is_valid_qty = (
                isinstance(qty, Decimal) and not isinstance(qty, bool) and qty.is_finite()
            )

            if not is_valid_qty:
                rejection_reasons.append(
                    RejectionReason(
                        code=REJECTION_INVALID_ACTION_SYNTAX,
                        message=f"Action quantity must be a finite Decimal, got {qty!r}",
                        violating_field="requested_actions[0].quantity",
                    )
                )

            if action.action_type == ActionType.ADJUST:
                rejection_reasons.append(
                    RejectionReason(
                        code=REJECTION_INVALID_ACTION_SYNTAX,
                        message="Action type ADJUST is not supported by admission service",
                        violating_field="requested_actions[0].action_type",
                    )
                )
            elif action.action_type == ActionType.ALLOCATE:
                if is_valid_qty and qty <= Decimal("0"):
                    rejection_reasons.append(
                        RejectionReason(
                            code=REJECTION_INVALID_ACTION_SYNTAX,
                            message=(
                                f"ALLOCATE action quantity must be strictly positive, got {qty}"
                            ),
                            violating_field="requested_actions[0].quantity",
                        )
                    )
            elif action.action_type == ActionType.TRANSFER:
                if is_valid_qty and qty == Decimal("0"):
                    rejection_reasons.append(
                        RejectionReason(
                            code=REJECTION_INVALID_ACTION_SYNTAX,
                            message="TRANSFER action quantity must be non-zero",
                            violating_field="requested_actions[0].quantity",
                        )
                    )
            elif action.action_type == ActionType.HOLD:
                if is_valid_qty and qty != Decimal("0"):
                    rejection_reasons.append(
                        RejectionReason(
                            code=REJECTION_INVALID_ACTION_SYNTAX,
                            message=f"HOLD action quantity must be zero, got {qty}",
                            violating_field="requested_actions[0].quantity",
                        )
                    )

            # Resource configuration check
            ref_id = episode_def.reference_resource_id
            tradable_resources = set(mapping_copy.keys()) - {ref_id}

            if action.action_type in (ActionType.ALLOCATE, ActionType.TRANSFER):
                if action.resource_id == ref_id:
                    rejection_reasons.append(
                        RejectionReason(
                            code=REJECTION_UNSUPPORTED_RESOURCE,
                            message=(
                                f"Direct trade in reference resource '{ref_id}' is not supported"
                            ),
                            violating_field="requested_actions[0].resource_id",
                        )
                    )
                elif action.resource_id not in tradable_resources:
                    rejection_reasons.append(
                        RejectionReason(
                            code=REJECTION_UNSUPPORTED_RESOURCE,
                            message=(
                                f"Resource '{action.resource_id}' is not configured "
                                "as a tradable resource"
                            ),
                            violating_field="requested_actions[0].resource_id",
                        )
                    )
            elif action.action_type == ActionType.HOLD:
                if action.resource_id != ref_id and action.resource_id not in tradable_resources:
                    rejection_reasons.append(
                        RejectionReason(
                            code=REJECTION_UNSUPPORTED_RESOURCE,
                            message=(
                                f"Resource '{action.resource_id}' for HOLD is not configured "
                                "as reference or tradable resource"
                            ),
                            violating_field="requested_actions[0].resource_id",
                        )
                    )

        # 3. Handle rejections
        if rejection_reasons:
            rejection_reasons.sort(key=lambda r: (r.code, r.violating_field or "", r.message))
            prop_hash = _safe_proposal_hash(proposal)
            outcome_id = _compute_outcome_id(
                episode_id=episode_def.episode_id,
                round_id=authoritative_round_id,
                policy_id=proposal.policy_id,
                decision_id=proposal.decision_id,
                proposal_hash=prop_hash,
            )
            outcome = DecisionOutcome(
                outcome_id=outcome_id,
                decision_id=proposal.decision_id,
                round_id=authoritative_round_id,
                policy_id=proposal.policy_id,
                status=DecisionStatus.REJECTED,
                rejection_reasons=tuple(rejection_reasons),
                evaluated_at=authoritative_cutoff,
                applied_transition_id=None,
            )
            return DeferredAdmissionResult(
                pending_transition=current_pending,
                decision_outcome=outcome,
                is_newly_admitted=False,
                is_reused_pending=False,
            )

        # 4. Handle admissible HOLD
        action = proposal.requested_actions[0]
        if action.action_type == ActionType.HOLD:
            outcome_id = _compute_outcome_id(
                episode_id=episode_def.episode_id,
                round_id=authoritative_round_id,
                policy_id=proposal.policy_id,
                decision_id=proposal.decision_id,
                proposal_hash=proposal.compute_hash(),
            )
            outcome = DecisionOutcome(
                outcome_id=outcome_id,
                decision_id=proposal.decision_id,
                round_id=authoritative_round_id,
                policy_id=proposal.policy_id,
                status=DecisionStatus.ACCEPTED,
                rejection_reasons=(),
                evaluated_at=authoritative_cutoff,
                applied_transition_id=None,
            )
            return DeferredAdmissionResult(
                pending_transition=current_pending,
                decision_outcome=outcome,
                is_newly_admitted=False,
                is_reused_pending=False,
            )

        # 5. Handle admissible trade with existing pending
        if current_pending is not None:
            if proposal.decision_id == current_pending.decision_id:
                # Retry verification of active pending transition
                stored_proposal_hash = current_pending.admission_evidence.get("proposal_hash")
                target_series_id = mapping_copy.get(action.resource_id)

                is_exact_retry = (
                    stored_proposal_hash is not None
                    and stored_proposal_hash == proposal.compute_hash()
                    and current_pending.policy_id == proposal.policy_id
                    and current_pending.policy_version_id == proposal.policy_version_id
                    and current_pending.round_id == proposal.round_id
                    and parse_utc_timestamp(current_pending.knowledge_cutoff) == cutoff_instant
                    and current_pending.requested_action == action
                    and current_pending.target_bar_rule.series_id == target_series_id
                    and current_pending.predecessor_account_hash == current_account.compute_hash()
                )

                if is_exact_retry:
                    return DeferredAdmissionResult(
                        pending_transition=current_pending,
                        decision_outcome=None,
                        is_newly_admitted=False,
                        is_reused_pending=True,
                    )
                else:
                    drift_reason = RejectionReason(
                        code=REJECTION_DECISION_ID_CONFLICT,
                        message=(
                            f"Decision ID '{proposal.decision_id}' matches active pending "
                            f"transition '{current_pending.pending_transition_id}' "
                            "but content or linkages have drifted"
                        ),
                        violating_field="decision_id",
                    )
                    outcome_id = _compute_outcome_id(
                        episode_id=episode_def.episode_id,
                        round_id=authoritative_round_id,
                        policy_id=proposal.policy_id,
                        decision_id=proposal.decision_id,
                        proposal_hash=_safe_proposal_hash(proposal),
                    )
                    outcome = DecisionOutcome(
                        outcome_id=outcome_id,
                        decision_id=proposal.decision_id,
                        round_id=authoritative_round_id,
                        policy_id=proposal.policy_id,
                        status=DecisionStatus.REJECTED,
                        rejection_reasons=(drift_reason,),
                        evaluated_at=authoritative_cutoff,
                        applied_transition_id=None,
                    )
                    return DeferredAdmissionResult(
                        pending_transition=current_pending,
                        decision_outcome=outcome,
                        is_newly_admitted=False,
                        is_reused_pending=False,
                    )
            else:
                # Attempting a different trade while a pending transition is active
                conflict_reason = RejectionReason(
                    code=REJECTION_POLICY_HAS_PENDING_SETTLEMENT,
                    message=(
                        f"Policy '{proposal.policy_id}' already has active pending transition "
                        f"'{current_pending.pending_transition_id}' awaiting settlement"
                    ),
                    violating_field=None,
                )
                outcome_id = _compute_outcome_id(
                    episode_id=episode_def.episode_id,
                    round_id=authoritative_round_id,
                    policy_id=proposal.policy_id,
                    decision_id=proposal.decision_id,
                    proposal_hash=_safe_proposal_hash(proposal),
                )
                outcome = DecisionOutcome(
                    outcome_id=outcome_id,
                    decision_id=proposal.decision_id,
                    round_id=authoritative_round_id,
                    policy_id=proposal.policy_id,
                    status=DecisionStatus.REJECTED,
                    rejection_reasons=(conflict_reason,),
                    evaluated_at=authoritative_cutoff,
                    applied_transition_id=None,
                )
                return DeferredAdmissionResult(
                    pending_transition=current_pending,
                    decision_outcome=outcome,
                    is_newly_admitted=False,
                    is_reused_pending=False,
                )

        # 6. Admissible new trade: create PendingTransitionRecord
        series_id = mapping_copy[action.resource_id]
        target_rule = TargetBarRule(
            series_id=series_id,
            selection_rule="FIRST_OPEN_GE_CUTOFF",
            expected_open_time=None,
        )
        pending_id = _compute_pending_transition_id(
            episode_id=episode_def.episode_id,
            round_id=authoritative_round_id,
            policy_id=proposal.policy_id,
            decision_id=proposal.decision_id,
        )
        new_pending = PendingTransitionRecord(
            pending_transition_id=pending_id,
            decision_id=proposal.decision_id,
            round_id=authoritative_round_id,
            policy_id=proposal.policy_id,
            policy_version_id=proposal.policy_version_id,
            knowledge_cutoff=authoritative_cutoff,
            admitted_at=authoritative_cutoff,
            predecessor_account_hash=current_account.compute_hash(),
            requested_action=action,
            target_bar_rule=target_rule,
            admission_evidence={"proposal_hash": proposal.compute_hash()},
            status=PendingStatus.ADMITTED_PENDING,
            schema_version="1.0.0",
        )
        return DeferredAdmissionResult(
            pending_transition=new_pending,
            decision_outcome=None,
            is_newly_admitted=True,
            is_reused_pending=False,
        )
