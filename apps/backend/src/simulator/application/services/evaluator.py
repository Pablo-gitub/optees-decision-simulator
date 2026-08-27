"""Metric evaluation and performance calculation service."""

from __future__ import annotations

import math
from decimal import Decimal

from simulator.domain.models import (
    DecisionOutcome,
    DecisionStatus,
    MetricRecord,
    MetricsData,
    TransitionRecord,
    VirtualAccountState,
)


class EvaluatorService:
    """Calculates deterministic explanatory and primary metrics for policies."""

    @staticmethod
    def calculate_metrics(
        run_id: str,
        policy_id: str,
        initial_account: VirtualAccountState,
        account_states: list[VirtualAccountState],
        outcomes: list[DecisionOutcome],
        transitions: list[TransitionRecord],
        wall_time_seconds: float = 0.0,
        round_index: int | None = None,
        calculated_at: str = "2026-08-01T00:00:00Z",
    ) -> MetricRecord:
        """Compute primary and explanatory metrics for a policy trajectory."""
        v_initial = initial_account.reference_valuation.net_total_value
        current_state = account_states[-1] if account_states else initial_account
        v_final = current_state.reference_valuation.net_total_value

        # Total return
        if v_initial > Decimal("0"):
            total_return = float((v_final - v_initial) / v_initial)
        else:
            total_return = 0.0

        # Trajectory values for drawdown and volatility
        values: list[float] = [float(initial_account.reference_valuation.net_total_value)]
        for s in account_states:
            values.append(float(s.reference_valuation.net_total_value))

        # Max drawdown
        peak = values[0]
        max_dd = 0.0
        for val in values:
            if val > peak:
                peak = val
            if peak > 0:
                dd = (peak - val) / peak
                if dd > max_dd:
                    max_dd = dd

        # Return volatility
        returns: list[float] = []
        for i in range(1, len(values)):
            if values[i - 1] > 0:
                returns.append((values[i] - values[i - 1]) / values[i - 1])
            else:
                returns.append(0.0)

        if len(returns) > 1:
            mean_ret = sum(returns) / len(returns)
            variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
            volatility = math.sqrt(variance)
        else:
            volatility = 0.0

        # Total transaction costs and turnover
        total_costs = Decimal("0.00")
        total_traded_volume = Decimal("0.00")
        for t in transitions:
            total_costs += t.total_cost_reference_unit
            for d in t.resource_deltas:
                total_traded_volume += abs(d.delta_quantity * d.valuation_price)

        avg_val = (v_initial + v_final) / Decimal("2")
        if avg_val > Decimal("0"):
            turnover = float(total_traded_volume / avg_val)
        else:
            turnover = 0.0

        # Rejected decision count
        rejected_count = sum(1 for o in outcomes if o.status == DecisionStatus.REJECTED)

        metrics_data = MetricsData(
            final_net_value=v_final,
            total_return=round(total_return, 6),
            max_drawdown=round(max_dd, 6),
            volatility=round(volatility, 6),
            turnover=round(turnover, 6),
            total_transaction_costs=total_costs,
            rejected_decision_count=rejected_count,
            solver_call_count=0,
            validation_failure_count=0,
            execution_wall_time_seconds=round(wall_time_seconds, 4),
            sharpe_ratio=None,
        )

        metric_id = (
            f"met_{run_id}_{policy_id}_round{round_index}"
            if round_index is not None
            else f"met_{run_id}_{policy_id}_final"
        )

        return MetricRecord(
            metric_record_id=metric_id,
            run_id=run_id,
            policy_id=policy_id,
            round_index=round_index,
            calculated_at=calculated_at,
            metrics=metrics_data,
        )
