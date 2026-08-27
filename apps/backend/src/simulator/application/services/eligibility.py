"""Observation eligibility service enforcing knowledge cutoffs, revisions, and tie-breaking."""

from __future__ import annotations

from simulator.domain.models import ObservationRecord
from simulator.domain.time import is_knowledge_eligible, parse_utc_timestamp


class EligibilityService:
    """Filters, deduplicates revisions, and sorts observations at an exact knowledge cutoff."""

    @staticmethod
    def get_eligible_observations(
        all_observations: tuple[ObservationRecord, ...],
        knowledge_cutoff: str,
    ) -> tuple[ObservationRecord, ...]:
        """Return the canonical, deterministically ordered tuple of eligible observations.

        Rules:
        1. Eligibility: t_knowledge <= knowledge_cutoff.
        2. Revision handling: For identical (series_id, event_time), the record with
           the maximum revision among those with t_knowledge <= knowledge_cutoff is kept.
        3. Deterministic Ordering: Sorted by
           (t_knowledge, t_event, series_id, revision, observation_id).
        """
        # Step 1: Filter by knowledge cutoff
        eligible_candidates: list[ObservationRecord] = [
            obs
            for obs in all_observations
            if is_knowledge_eligible(obs.knowledge_time, knowledge_cutoff)
        ]

        # Step 2: Resolve revisions (group by series_id and event_time)
        revisions_by_key: dict[tuple[str, str], ObservationRecord] = {}
        for obs in eligible_candidates:
            key = (obs.series_id, obs.event_time)
            if key not in revisions_by_key:
                revisions_by_key[key] = obs
            else:
                existing = revisions_by_key[key]
                if obs.revision > existing.revision:
                    revisions_by_key[key] = obs

        deduped = list(revisions_by_key.values())

        # Step 3: Deterministic tie-breaking sort
        def sort_key(obs: ObservationRecord) -> tuple[float, float, str, int, str]:
            k_ts = parse_utc_timestamp(obs.knowledge_time).timestamp()
            e_ts = parse_utc_timestamp(obs.event_time).timestamp()
            return (k_ts, e_ts, obs.series_id, obs.revision, obs.observation_id)

        deduped.sort(key=sort_key)
        return tuple(deduped)
