"""Equal allocation baseline policy."""

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


class EqualAllocationPolicy(PolicyPort):
    """Deterministic policy that divides available reference resources equally
    across allowed resources.
    """

    def __init__(
        self,
        target_resources: tuple[str, ...],
        reference_resource_id: str = "USD",
        policy_id: str = "pol-def_equal_allocation",
        policy_version_id: str = "pol-ver_equal_v1",
    ) -> None:
        self._target_resources = target_resources
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

        # Find reference resource balance
        ref_balance = Decimal("0.00")
        for b in context.account_state.balances:
            if b.resource_id == self._reference_resource_id:
                ref_balance = b.quantity
                break

        # Calculate allocation per resource
        num_targets = len(self._target_resources)
        if num_targets > 0 and ref_balance > Decimal("0"):
            amount_per_res = ref_balance / Decimal(num_targets)
            for res_id in self._target_resources:
                # Find observation price if available to calculate quantity
                price = Decimal("1.00")
                for obs in reversed(context.eligible_observations):
                    if obs.series_id == f"{res_id}_PRICE" and "price" in obs.payload:
                        price = Decimal(str(obs.payload["price"]))
                        break
                target_qty = (amount_per_res / price).quantize(Decimal("0.01"))
                desired_allocations.append(
                    DesiredAllocation(resource_id=res_id, target_quantity=target_qty)
                )
                requested_actions.append(
                    RequestedAction(
                        action_type=ActionType.ALLOCATE,
                        resource_id=res_id,
                        quantity=target_qty,
                    )
                )

        return ProposedDecision(
            decision_id=f"dec-prop_{context.round_id}_{self.policy_id}_equal",
            round_id=context.round_id,
            policy_id=self.policy_id,
            policy_version_id=self.policy_version_id,
            knowledge_cutoff=context.knowledge_cutoff,
            generated_at=context.knowledge_cutoff,
            desired_allocations=tuple(desired_allocations),
            requested_actions=tuple(requested_actions),
            rationale=DecisionRationale(
                method="equal_allocation",
                objective_value=float(ref_balance),
                solver_status=None,
            ),
        )
