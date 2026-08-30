"""Infrastructure adapter resolving Binance spot kline valuation marks and execution prices."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Final

from simulator.application.ports.pricing import (
    PriceEvidence,
    PriceResolutionResult,
    PricingPort,
)
from simulator.domain.models import ObservationRecord, RejectionReason
from simulator.domain.time import parse_utc_timestamp
from simulator.infrastructure.adapters.market_normalizer import ALLOWED_MARKET_SYMBOLS

RESOURCE_TO_SERIES: Final[dict[str, str]] = {
    resource_id: series_id for _, (series_id, resource_id, _) in ALLOWED_MARKET_SYMBOLS.items()
}


class MarketKlinePricingAdapter(PricingPort):
    """Resolves valuation close marks and future open execution prices from normalized klines."""

    def resolve_pricing(
        self,
        all_observations: tuple[ObservationRecord, ...],
        knowledge_cutoff: str,
        effective_time: str,
        required_resources: tuple[str, ...],
        reference_resource_id: str,
    ) -> PriceResolutionResult:
        """Resolve valuation marks at cutoff and next-bar open execution prices."""
        cutoff_dt = parse_utc_timestamp(knowledge_cutoff)
        parse_utc_timestamp(effective_time)

        valuation_marks: dict[str, PriceEvidence] = {}
        execution_prices: dict[str, PriceEvidence] = {}
        rejection_reasons: list[RejectionReason] = []

        for resource_id in required_resources:
            # 1. Reference resource (USDT) is always 1.00 with zero staleness
            if resource_id == reference_resource_id:
                ref_evidence = PriceEvidence(
                    resource_id=resource_id,
                    price=Decimal("1.00"),
                    observation_id=None,
                    event_time=None,
                    knowledge_time=None,
                    revision=None,
                    staleness_seconds=Decimal("0"),
                )
                valuation_marks[resource_id] = ref_evidence
                execution_prices[resource_id] = ref_evidence
                continue

            # 2. Check if resource is supported
            if resource_id not in RESOURCE_TO_SERIES:
                rejection_reasons.append(
                    RejectionReason(
                        code="UNSUPPORTED_RESOURCE",
                        message=f"Resource {resource_id} is unsupported by market pricing adapter",
                        violating_field="resource_id",
                    )
                )
                continue

            series_id = RESOURCE_TO_SERIES[resource_id]

            # Filter candidate observations for this series
            series_obs = [obs for obs in all_observations if obs.series_id == series_id]

            # 3. Resolve valuation mark (latest eligible close with event_time/knowledge_time <= T)
            val_candidates: list[ObservationRecord] = []
            for obs in series_obs:
                if obs.event_time <= knowledge_cutoff and obs.knowledge_time <= knowledge_cutoff:
                    val_candidates.append(obs)

            # Revision resolution: for identical event_time, keep highest revision <= cutoff
            val_by_event: dict[str, ObservationRecord] = {}
            for obs in val_candidates:
                if (
                    obs.event_time not in val_by_event
                    or obs.revision > val_by_event[obs.event_time].revision
                ):
                    val_by_event[obs.event_time] = obs

            val_unique = list(val_by_event.values())
            if not val_unique:
                rejection_reasons.append(
                    RejectionReason(
                        code="MISSING_VALUATION_MARK",
                        message=(
                            f"No eligible valuation mark for {resource_id} "
                            f"at cutoff {knowledge_cutoff}"
                        ),
                        violating_field=f"balances[{resource_id}]",
                    )
                )
            else:
                # Deterministic sorting to pick latest close
                def val_sort_key(o: ObservationRecord) -> tuple[float, float, int, str]:
                    return (
                        parse_utc_timestamp(o.event_time).timestamp(),
                        parse_utc_timestamp(o.knowledge_time).timestamp(),
                        o.revision,
                        o.observation_id,
                    )

                val_unique.sort(key=val_sort_key)
                latest_val_obs = val_unique[-1]

                # Extract close price
                close_raw = latest_val_obs.payload.get("close")
                try:
                    if close_raw is None:
                        raise ValueError("Missing close price field in payload")
                    close_dec = Decimal(str(close_raw))
                    if close_dec.is_nan() or close_dec.is_infinite() or close_dec <= Decimal("0"):
                        raise ValueError(f"Non-positive or non-finite close price: {close_dec}")

                    obs_event_dt = parse_utc_timestamp(latest_val_obs.event_time)
                    staleness = Decimal(str((cutoff_dt - obs_event_dt).total_seconds()))
                    if staleness < Decimal("0"):
                        raise ValueError(f"Negative staleness: {staleness}")

                    valuation_marks[resource_id] = PriceEvidence(
                        resource_id=resource_id,
                        price=close_dec,
                        observation_id=latest_val_obs.observation_id,
                        event_time=latest_val_obs.event_time,
                        knowledge_time=latest_val_obs.knowledge_time,
                        revision=latest_val_obs.revision,
                        staleness_seconds=staleness,
                    )
                except (InvalidOperation, ValueError, TypeError) as exc:
                    rejection_reasons.append(
                        RejectionReason(
                            code="MISSING_VALUATION_MARK",
                            message=(
                                f"Invalid valuation mark for {resource_id} "
                                f"at cutoff {knowledge_cutoff}: {exc}"
                            ),
                            violating_field=f"balances[{resource_id}]",
                        )
                    )

            # 4. Resolve paper execution price (first future daily bar event_time > T)
            exec_candidates: list[ObservationRecord] = []
            for obs in series_obs:
                if obs.event_time > knowledge_cutoff and obs.knowledge_time <= effective_time:
                    exec_candidates.append(obs)

            # Revision resolution for execution candidates
            exec_by_event: dict[str, ObservationRecord] = {}
            for obs in exec_candidates:
                if (
                    obs.event_time not in exec_by_event
                    or obs.revision > exec_by_event[obs.event_time].revision
                ):
                    exec_by_event[obs.event_time] = obs

            exec_unique = list(exec_by_event.values())
            if not exec_unique:
                rejection_reasons.append(
                    RejectionReason(
                        code="MISSING_EXECUTION_PRICE",
                        message=(
                            f"No available future execution bar for {resource_id} "
                            f"after cutoff {knowledge_cutoff} at effective time {effective_time}"
                        ),
                        violating_field=f"requested_actions[{resource_id}]",
                    )
                )
            else:
                # Deterministic sorting to pick first (earliest) future bar
                def exec_sort_key(o: ObservationRecord) -> tuple[float, float, int, str]:
                    return (
                        parse_utc_timestamp(o.event_time).timestamp(),
                        parse_utc_timestamp(o.knowledge_time).timestamp(),
                        o.revision,
                        o.observation_id,
                    )

                exec_unique.sort(key=exec_sort_key)
                first_future_obs = exec_unique[0]

                # Extract open price
                open_raw = first_future_obs.payload.get("open")
                try:
                    if open_raw is None:
                        raise ValueError("Missing open price field in payload")
                    open_dec = Decimal(str(open_raw))
                    if open_dec.is_nan() or open_dec.is_infinite() or open_dec <= Decimal("0"):
                        raise ValueError(f"Non-positive or non-finite open price: {open_dec}")

                    execution_prices[resource_id] = PriceEvidence(
                        resource_id=resource_id,
                        price=open_dec,
                        observation_id=first_future_obs.observation_id,
                        event_time=first_future_obs.event_time,
                        knowledge_time=first_future_obs.knowledge_time,
                        revision=first_future_obs.revision,
                        staleness_seconds=Decimal("0"),
                    )
                except (InvalidOperation, ValueError, TypeError) as exc:
                    rejection_reasons.append(
                        RejectionReason(
                            code="MISSING_EXECUTION_PRICE",
                            message=(
                                f"Invalid future execution price for {resource_id} "
                                f"after cutoff {knowledge_cutoff}: {exc}"
                            ),
                            violating_field=f"requested_actions[{resource_id}]",
                        )
                    )

        # Deterministic sorting of rejection reasons
        rejection_reasons.sort(key=lambda r: (r.code, r.violating_field or "", r.message))

        return PriceResolutionResult(
            valuation_marks=valuation_marks,
            execution_prices=execution_prices,
            rejection_reasons=tuple(rejection_reasons),
        )
