"""Reactive observation baseline policy."""

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


class ReactiveObservationPolicy(PolicyPort):
    """Deterministic policy allocating based on the latest eligible observation."""

    def __init__(
        self,
        target_resource_id: str = "RES_ALPHA",
        reference_resource_id: str = "USD",
        policy_id: str = "pol-def_reactive_baseline",
        policy_version_id: str = "pol-ver_reactive_v1",
    ) -> None:
        self._target_resource_id = target_resource_id
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

        # Find available reference balance
        ref_balance = Decimal("0.00")
        for b in context.account_state.balances:
            if b.resource_id == self._reference_resource_id:
                ref_balance = b.quantity
                break

        # Find latest observation price for target resource
        latest_price = Decimal("100.00")
        series_id = f"{self._target_resource_id}_PRICE"
        for obs in reversed(context.eligible_observations):
            if obs.series_id == series_id and "price" in obs.payload:
                latest_price = Decimal(str(obs.payload["price"]))
                break

        # Check if hyperparameters specify allocation percentage or fixed quantity
        alloc_fraction = Decimal(str(context.hyperparameters.get("allocation_fraction", "0.20")))
        spend_amount = (ref_balance * alloc_fraction).quantize(Decimal("0.01"))

        if spend_amount > Decimal("0") and latest_price > Decimal("0"):
            target_qty = (spend_amount / latest_price).quantize(Decimal("0.01"))
            desired_allocations.append(
                DesiredAllocation(
                    resource_id=self._target_resource_id,
                    target_quantity=target_qty,
                )
            )
            requested_actions.append(
                RequestedAction(
                    action_type=ActionType.ALLOCATE,
                    resource_id=self._target_resource_id,
                    quantity=target_qty,
                    parameters={"observed_price": format(latest_price, "f")},
                )
            )

        return ProposedDecision(
            decision_id=f"dec-prop_{context.round_id}_{self.policy_id}_reactive",
            round_id=context.round_id,
            policy_id=self.policy_id,
            policy_version_id=self.policy_version_id,
            knowledge_cutoff=context.knowledge_cutoff,
            generated_at=context.knowledge_cutoff,
            desired_allocations=tuple(desired_allocations),
            requested_actions=tuple(requested_actions),
            rationale=DecisionRationale(
                method="reactive_momentum",
                objective_value=float(spend_amount),
                solver_status=None,
            ),
        )
