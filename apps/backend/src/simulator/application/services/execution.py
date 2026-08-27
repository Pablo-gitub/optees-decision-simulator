"""Decision execution, validation, cost calculation, and account transition service."""

from __future__ import annotations

from decimal import Decimal

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
        eligible_observations: tuple[ObservationRecord, ...],
        round_id: str,
        round_index: int,
        effective_time: str,
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

        # Lookup available reference balance and asset balances
        ref_id = episode_def.reference_resource_id
        balances_map: dict[str, Decimal] = {
            b.resource_id: b.quantity for b in current_account.balances
        }
        available_cash = balances_map.get(ref_id, Decimal("0.00"))

        # Price lookup helper from latest eligible observations
        prices_map: dict[str, Decimal] = {ref_id: Decimal("1.00")}
        for obs in eligible_observations:
            for res_id in balances_map.keys():
                if obs.series_id == f"{res_id}_PRICE" and "price" in obs.payload:
                    prices_map[res_id] = Decimal(str(obs.payload["price"]))

        # Check action feasibility & compute deltas
        deltas_map: dict[str, Decimal] = {k: Decimal("0.00") for k in balances_map.keys()}
        cost_items: list[CostItem] = []
        total_cost = Decimal("0.00")

        cost_model = episode_def.rules.cost_model

        for idx, action in enumerate(proposal.requested_actions):
            res_id = action.resource_id
            if res_id not in balances_map and res_id not in deltas_map:
                deltas_map[res_id] = Decimal("0.00")
                balances_map[res_id] = Decimal("0.00")

            res_price = prices_map.get(res_id, Decimal("1.00"))

            if action.action_type == ActionType.HOLD:
                continue

            elif action.action_type == ActionType.ALLOCATE:
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
                notional = qty * res_price
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
                            cost_type=CostType.TRANSACTION_FEE, resource_id=ref_id, amount=fixed_fee
                        )
                    )

            elif action.action_type == ActionType.TRANSFER:
                qty = action.quantity
                # Transfer positive means transferring into resource; negative means liquidating
                notional = abs(qty) * res_price
                linear_fee = (notional * cost_model.linear_transaction_fee_rate).quantize(
                    Decimal("0.01")
                )
                fixed_fee = (
                    cost_model.fixed_transaction_fee if abs(qty) > Decimal("0") else Decimal("0.00")
                )
                action_cost = linear_fee + fixed_fee

                total_cost += action_cost
                deltas_map[res_id] += qty
                deltas_map[ref_id] += -qty * res_price - action_cost

                if action_cost > Decimal("0"):
                    cost_items.append(
                        CostItem(
                            cost_type=CostType.TRANSACTION_FEE,
                            resource_id=ref_id,
                            amount=action_cost,
                        )
                    )

        # Check balance feasibility if borrowing/shorting not allowed
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
                if r_id != ref_id and (balances_map[r_id] + d_qty) < Decimal("0.00"):
                    rejection_reasons.append(
                        RejectionReason(
                            code="SHORT_POSITIONS_FORBIDDEN",
                            message=(
                                f"Negative balance in {r_id} resulting from transition is forbidden"
                            ),
                            violating_field="requested_actions",
                        )
                    )

        # If any rejection reason occurred:
        if rejection_reasons:
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

        # Build next account state
        new_balances: list[BalanceItem] = []
        allocated_val = Decimal("0.00")
        for res_id, old_qty in balances_map.items():
            final_qty = (old_qty + deltas_map[res_id]).quantize(Decimal("0.01"))
            new_balances.append(
                BalanceItem(
                    resource_id=res_id,
                    quantity=final_qty,
                    reserved_quantity=Decimal("0.00"),
                )
            )
            if res_id != ref_id:
                allocated_val += (final_qty * prices_map.get(res_id, Decimal("1.00"))).quantize(
                    Decimal("0.01")
                )

        final_cash = (available_cash + deltas_map[ref_id]).quantize(Decimal("0.01"))
        net_val = (final_cash + allocated_val).quantize(Decimal("0.01"))

        # Update cumulative costs
        new_cum_costs: list[CumulativeCostItem] = []
        old_cost_map = {c.cost_type: c.amount for c in current_account.cumulative_costs}
        old_cost_map["TRANSACTION_FEE"] = (
            old_cost_map.get("TRANSACTION_FEE", Decimal("0.00")) + total_cost
        )
        for c_type, c_amt in old_cost_map.items():
            new_cum_costs.append(CumulativeCostItem(cost_type=c_type, amount=c_amt))

        # Sort balances deterministically
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
                resource_deltas.append(
                    ResourceDelta(
                        resource_id=res_id,
                        delta_quantity=d_qty,
                        valuation_price=prices_map.get(res_id, Decimal("1.00")),
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
