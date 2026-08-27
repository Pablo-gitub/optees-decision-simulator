"""Unit tests for observation eligibility, revision handling, and deterministic tie-breaking."""

from simulator.application.services.eligibility import EligibilityService
from simulator.domain.models import ObservationRecord


def test_eligibility_service_cutoff_filtering() -> None:
    obs1 = ObservationRecord(
        observation_id="obs_1",
        snapshot_id="ds_1",
        series_id="S1",
        event_time="2026-07-31T12:00:00Z",
        knowledge_time="2026-07-31T12:05:00Z",
        revision=1,
        payload={"val": 1},
    )
    obs2 = ObservationRecord(
        observation_id="obs_2",
        snapshot_id="ds_1",
        series_id="S1",
        event_time="2026-07-31T23:59:00Z",
        knowledge_time="2026-08-01T00:00:00Z",
        revision=1,
        payload={"val": 2},
    )
    obs3 = ObservationRecord(
        observation_id="obs_3",
        snapshot_id="ds_1",
        series_id="S1",
        event_time="2026-07-31T23:59:00Z",
        knowledge_time="2026-08-01T00:01:00Z",
        revision=1,
        payload={"val": 3},
    )

    all_obs = (obs1, obs2, obs3)

    # At cutoff 2026-08-01T00:00:00Z, obs1 and obs2 are eligible, obs3 is not
    eligible_r0 = EligibilityService.get_eligible_observations(all_obs, "2026-08-01T00:00:00Z")
    assert len(eligible_r0) == 2
    assert [o.observation_id for o in eligible_r0] == ["obs_1", "obs_2"]

    # At cutoff 2026-08-02T00:00:00Z, all 3 are eligible
    eligible_r1 = EligibilityService.get_eligible_observations(all_obs, "2026-08-02T00:00:00Z")
    assert (
        len(eligible_r1) == 2
    )  # obs2 and obs3 share (S1, 2026-07-31T23:59:00Z), so revision rules apply


def test_eligibility_service_revision_resolution() -> None:
    obs_rev1 = ObservationRecord(
        observation_id="obs_rev1",
        snapshot_id="ds_1",
        series_id="ALPHA",
        event_time="2026-07-31T23:59:00Z",
        knowledge_time="2026-08-01T00:00:00Z",
        revision=1,
        payload={"price": "100.00"},
    )
    obs_rev2 = ObservationRecord(
        observation_id="obs_rev2",
        snapshot_id="ds_1",
        series_id="ALPHA",
        event_time="2026-07-31T23:59:00Z",
        knowledge_time="2026-08-01T00:05:00Z",
        revision=2,
        payload={"price": "100.50"},
    )
    all_obs = (obs_rev1, obs_rev2)

    # At 2026-08-01T00:00:00Z: only rev1 is known
    r0_obs = EligibilityService.get_eligible_observations(all_obs, "2026-08-01T00:00:00Z")
    assert len(r0_obs) == 1
    assert r0_obs[0].observation_id == "obs_rev1"
    assert r0_obs[0].payload["price"] == "100.00"

    # At 2026-08-01T00:10:00Z: rev2 is known and supersedes rev1
    r1_obs = EligibilityService.get_eligible_observations(all_obs, "2026-08-01T00:10:00Z")
    assert len(r1_obs) == 1
    assert r1_obs[0].observation_id == "obs_rev2"
    assert r1_obs[0].payload["price"] == "100.50"


def test_eligibility_service_tie_breaking_order() -> None:
    # Observations with same knowledge time
    obs_a = ObservationRecord(
        observation_id="obs_a",
        snapshot_id="ds_1",
        series_id="BETA",
        event_time="2026-07-31T23:59:00Z",
        knowledge_time="2026-08-01T00:00:00Z",
        revision=1,
        payload={},
    )
    obs_b = ObservationRecord(
        observation_id="obs_b",
        snapshot_id="ds_1",
        series_id="ALPHA",
        event_time="2026-07-31T23:59:00Z",
        knowledge_time="2026-08-01T00:00:00Z",
        revision=1,
        payload={},
    )
    all_obs = (obs_a, obs_b)
    ordered = EligibilityService.get_eligible_observations(all_obs, "2026-08-01T00:00:00Z")
    assert len(ordered) == 2
    # Alphabetical by series_id: ALPHA before BETA
    assert ordered[0].observation_id == "obs_b"
    assert ordered[1].observation_id == "obs_a"
