"""Infrastructure adapter resolving pricing for generic synthetic episodes."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from simulator.application.ports.pricing import (
    PriceEvidence,
    PriceResolutionResult,
    PricingPort,
)
from simulator.domain.models import ObservationRecord, RejectionReason
from simulator.domain.time import parse_utc_timestamp


class SyntheticPricingAdapter(PricingPort):
    """Resolves prices from generic synthetic observations ({RESOURCE}_PRICE payload)."""

    def resolve_pricing(
        self,
        all_observations: tuple[ObservationRecord, ...],
        knowledge_cutoff: str,
        effective_time: str,
        valuation_resources: tuple[str, ...],
        execution_resources: tuple[str, ...],
        reference_resource_id: str,
    ) -> PriceResolutionResult:
        """Resolve valuation marks and execution prices for synthetic episodes."""
        cutoff_dt = parse_utc_timestamp(knowledge_cutoff)
        parse_utc_timestamp(effective_time)

        valuation_marks: dict[str, PriceEvidence] = {}
        execution_prices: dict[str, PriceEvidence] = {}
        rejection_reasons: list[RejectionReason] = []

        resources = tuple(sorted(set(valuation_resources) | set(execution_resources)))
        execution_resource_set = set(execution_resources)
        for resource_id in resources:
            # 1. Reference resource is always 1.00
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
                if resource_id in execution_resource_set:
                    execution_prices[resource_id] = ref_evidence
                continue

            # Match series for this resource: {resource_id}_PRICE or resource_id
            candidates = [
                obs
                for obs in all_observations
                if obs.series_id in (f"{resource_id}_PRICE", resource_id)
            ]

            # 2. Valuation mark candidates (event_time <= T, knowledge_time <= T)
            val_candidates = [
                obs
                for obs in candidates
                if obs.event_time <= knowledge_cutoff and obs.knowledge_time <= knowledge_cutoff
            ]

            # Revision resolution
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
                            f"No eligible synthetic valuation price for {resource_id} "
                            f"at cutoff {knowledge_cutoff}"
                        ),
                        violating_field=f"balances[{resource_id}]",
                    )
                )
            else:

                def val_sort_key(o: ObservationRecord) -> tuple[float, float, int, str]:
                    return (
                        parse_utc_timestamp(o.event_time).timestamp(),
                        parse_utc_timestamp(o.knowledge_time).timestamp(),
                        o.revision,
                        o.observation_id,
                    )

                val_unique.sort(key=val_sort_key)
                latest_obs = val_unique[-1]
                raw_price = latest_obs.payload.get("price", latest_obs.payload.get("close"))

                try:
                    if raw_price is None:
                        raise ValueError("Missing price field in payload")
                    price_dec = Decimal(str(raw_price))
                    if price_dec.is_nan() or price_dec.is_infinite() or price_dec <= Decimal("0"):
                        raise ValueError(f"Non-positive or non-finite price: {price_dec}")

                    obs_event_dt = parse_utc_timestamp(latest_obs.event_time)
                    staleness = Decimal(str((cutoff_dt - obs_event_dt).total_seconds()))
                    if staleness < Decimal("0"):
                        raise ValueError(f"Negative staleness: {staleness}")

                    evidence = PriceEvidence(
                        resource_id=resource_id,
                        price=price_dec,
                        observation_id=latest_obs.observation_id,
                        event_time=latest_obs.event_time,
                        knowledge_time=latest_obs.knowledge_time,
                        revision=latest_obs.revision,
                        staleness_seconds=staleness,
                    )
                    valuation_marks[resource_id] = evidence
                except (InvalidOperation, ValueError, TypeError) as exc:
                    rejection_reasons.append(
                        RejectionReason(
                            code="MISSING_VALUATION_MARK",
                            message=(
                                f"Invalid synthetic valuation price for {resource_id} "
                                f"at cutoff {knowledge_cutoff}: {exc}"
                            ),
                            violating_field=f"balances[{resource_id}]",
                        )
                    )

            if resource_id not in execution_resource_set:
                continue

            # 3. Execution price candidates:
            # Check for future bar (event_time > T and knowledge_time <= effective_time)
            future_candidates = [
                obs
                for obs in candidates
                if obs.event_time > knowledge_cutoff and obs.knowledge_time <= effective_time
            ]

            if future_candidates:
                future_by_event: dict[str, ObservationRecord] = {}
                for obs in future_candidates:
                    if (
                        obs.event_time not in future_by_event
                        or obs.revision > future_by_event[obs.event_time].revision
                    ):
                        future_by_event[obs.event_time] = obs

                future_unique = list(future_by_event.values())
                future_unique.sort(
                    key=lambda o: (
                        parse_utc_timestamp(o.event_time).timestamp(),
                        parse_utc_timestamp(o.knowledge_time).timestamp(),
                        o.revision,
                        o.observation_id,
                    )
                )
                first_future = future_unique[0]
                raw_exec_price = first_future.payload.get("open", first_future.payload.get("price"))
                try:
                    if raw_exec_price is None:
                        raise ValueError("Missing open/price field in future payload")
                    exec_dec = Decimal(str(raw_exec_price))
                    if exec_dec.is_nan() or exec_dec.is_infinite() or exec_dec <= Decimal("0"):
                        raise ValueError(f"Non-positive or non-finite price: {exec_dec}")

                    execution_prices[resource_id] = PriceEvidence(
                        resource_id=resource_id,
                        price=exec_dec,
                        observation_id=first_future.observation_id,
                        event_time=first_future.event_time,
                        knowledge_time=first_future.knowledge_time,
                        revision=first_future.revision,
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
            elif resource_id in valuation_marks:
                # Synchronous fallback: use the resolved valuation mark as execution price
                execution_prices[resource_id] = valuation_marks[resource_id]
            else:
                rejection_reasons.append(
                    RejectionReason(
                        code="MISSING_EXECUTION_PRICE",
                        message=(
                            f"No available execution price for {resource_id} "
                            f"at cutoff {knowledge_cutoff}"
                        ),
                        violating_field=f"requested_actions[{resource_id}]",
                    )
                )

        rejection_reasons.sort(key=lambda r: (r.code, r.violating_field or "", r.message))

        return PriceResolutionResult(
            valuation_marks=valuation_marks,
            execution_prices=execution_prices,
            rejection_reasons=tuple(rejection_reasons),
        )
