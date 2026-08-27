"""All-reference / Cash holding policy."""

from __future__ import annotations

from decimal import Decimal

from simulator.application.ports.policy import PolicyContext, PolicyPort
from simulator.domain.lifecycle import ActionType
from simulator.domain.models import (
    DecisionRationale,
    DesiredAllocation,
    ProposedDecision,
    RequestedAction,
)


class AllReferenceCashPolicy(PolicyPort):
    """Deterministic policy that liquidates non-reference resources into reference currency."""

    def __init__(
        self,
        reference_resource_id: str = "USD",
        policy_id: str = "pol-def_cash_hold",
        policy_version_id: str = "pol-ver_cash_v1",
    ) -> None:
        self._reference_resource_id = reference_resource_id
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

        total_est_cash = Decimal("0.00")
        for b in context.account_state.balances:
            if b.resource_id == self._reference_resource_id:
                total_est_cash += b.quantity
            else:
                if b.quantity > Decimal("0"):
                    requested_actions.append(
                        RequestedAction(
                            action_type=ActionType.TRANSFER,
                            resource_id=b.resource_id,
                            quantity=-b.quantity,
                        )
                    )
                desired_allocations.append(
                    DesiredAllocation(
                        resource_id=b.resource_id,
                        target_quantity=Decimal("0.00"),
                    )
                )

        desired_allocations.append(
            DesiredAllocation(
                resource_id=self._reference_resource_id,
                target_quantity=total_est_cash,
            )
        )

        return ProposedDecision(
            decision_id=f"dec-prop_{context.round_id}_{self.policy_id}_cash",
            round_id=context.round_id,
            policy_id=self.policy_id,
            policy_version_id=self.policy_version_id,
            knowledge_cutoff=context.knowledge_cutoff,
            generated_at=context.knowledge_cutoff,
            desired_allocations=tuple(desired_allocations),
            requested_actions=tuple(requested_actions),
            rationale=DecisionRationale(
                method="all_reference_cash",
                objective_value=0.0,
                solver_status=None,
            ),
        )
