"""Static baseline policy (holds existing positions, no rebalance)."""

from __future__ import annotations

from simulator.application.ports.policy import PolicyContext, PolicyPort
from simulator.domain.lifecycle import ActionType
from simulator.domain.models import (
    DecisionRationale,
    DesiredAllocation,
    ProposedDecision,
    RequestedAction,
)


class StaticBaselinePolicy(PolicyPort):
    """Deterministic static policy that retains existing resource allocations."""

    def __init__(
        self,
        policy_id: str = "pol-def_static_baseline",
        policy_version_id: str = "pol-ver_static_v1",
    ) -> None:
        self._policy_id = policy_id
        self._policy_version_id = policy_version_id

    @property
    def policy_id(self) -> str:
        return self._policy_id

    @property
    def policy_version_id(self) -> str:
        return self._policy_version_id

    def propose_decision(self, context: PolicyContext) -> ProposedDecision:
        desired_allocations: list[DesiredAllocation] = []
        requested_actions: list[RequestedAction] = []

        for b in context.account_state.balances:
            desired_allocations.append(
                DesiredAllocation(resource_id=b.resource_id, target_quantity=b.quantity)
            )
            requested_actions.append(
                RequestedAction(
                    action_type=ActionType.HOLD,
                    resource_id=b.resource_id,
                    quantity=b.quantity,
                )
            )

        return ProposedDecision(
            decision_id=f"dec-prop_{context.round_id}_{self.policy_id}_hold",
            round_id=context.round_id,
            policy_id=self.policy_id,
            policy_version_id=self.policy_version_id,
            knowledge_cutoff=context.knowledge_cutoff,
            generated_at=context.knowledge_cutoff,
            desired_allocations=tuple(desired_allocations),
            requested_actions=tuple(requested_actions),
            rationale=DecisionRationale(
                method="static_hold",
                objective_value=0.0,
                solver_status=None,
            ),
        )
