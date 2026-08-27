"""Integration tests for record replay, deterministic re-execution, and divergence detection."""

from simulator.application.policies.reactive import ReactiveObservationPolicy
from simulator.application.policies.static import StaticBaselinePolicy
from simulator.application.services.replay import ReplayService
from simulator.application.services.runner import EpisodeRunner
from simulator.domain.lifecycle import DivergenceCategory, ReplayStatus
from simulator.domain.models import EpisodeDefinition
from simulator.infrastructure.adapters.in_memory_clock import InMemoryClock
from simulator.infrastructure.adapters.in_memory_store import InMemoryStore
from simulator.infrastructure.adapters.synthetic_dataset import SyntheticDatasetAdapter


def test_record_replay_success(synthetic_episode_def: EpisodeDefinition) -> None:
    store = InMemoryStore()
    dataset = SyntheticDatasetAdapter()
    clock = InMemoryClock()
    policies = {
        "pol-def_static_baseline": StaticBaselinePolicy(),
        "pol-def_reactive_baseline": ReactiveObservationPolicy(),
    }
    runner = EpisodeRunner(store, dataset, clock, policies)
    ep_def = synthetic_episode_def
    run_id = "run_replay_ok"

    runner.initialize_episode(ep_def, run_id)
    runner.run_all_rounds(run_id)

    replay_svc = ReplayService(store, dataset, clock)
    report = replay_svc.record_replay(run_id, "rep-rep_record_001")

    assert report.overall_status == ReplayStatus.MATCH
    assert report.rounds_evaluated == 3
    assert report.matched_round_count == 3
    assert report.diverged_round_count == 0
    assert report.initial_state_hash_match is True
    assert report.final_state_hash_match is True


def test_deterministic_re_execution_success(synthetic_episode_def: EpisodeDefinition) -> None:
    store = InMemoryStore()
    dataset = SyntheticDatasetAdapter()
    clock = InMemoryClock()
    policies = {
        "pol-def_static_baseline": StaticBaselinePolicy(),
        "pol-def_reactive_baseline": ReactiveObservationPolicy(),
    }
    runner = EpisodeRunner(store, dataset, clock, policies)
    ep_def = synthetic_episode_def
    run_id = "run_reexec_ok"

    runner.initialize_episode(ep_def, run_id)
    runner.run_all_rounds(run_id)

    replay_svc = ReplayService(store, dataset, clock)
    report = replay_svc.deterministic_re_execution(run_id, "rep-rep_reexec_001", policies)

    assert report.overall_status == ReplayStatus.MATCH
    assert report.matched_round_count == 3
    assert report.diverged_round_count == 0


def test_deterministic_re_execution_divergence_detection(
    synthetic_episode_def: EpisodeDefinition,
) -> None:
    store = InMemoryStore()
    dataset = SyntheticDatasetAdapter()
    clock = InMemoryClock()
    policies = {
        "pol-def_static_baseline": StaticBaselinePolicy(),
        "pol-def_reactive_baseline": ReactiveObservationPolicy(),
    }
    runner = EpisodeRunner(store, dataset, clock, policies)
    ep_def = synthetic_episode_def
    run_id = "run_diverge_test"

    runner.initialize_episode(ep_def, run_id)
    runner.run_all_rounds(run_id)

    # Re-execute with a DIFFERENT policy implementation under the same policy_id
    tampered_policies = {
        "pol-def_static_baseline": StaticBaselinePolicy(),
        # Use Static instead of Reactive to induce divergence
        "pol-def_reactive_baseline": StaticBaselinePolicy(policy_id="pol-def_reactive_baseline"),
    }

    replay_svc = ReplayService(store, dataset, clock)
    report = replay_svc.deterministic_re_execution(run_id, "rep-rep_diverge_001", tampered_policies)

    assert report.overall_status == ReplayStatus.DIVERGED
    assert report.diverged_round_count > 0
    assert len(report.divergence_report_ids) > 0

    divergences = store.get_divergence_reports("rep-rep_diverge_001")
    assert len(divergences) > 0
    assert any(d.category == DivergenceCategory.DECISION_DIVERGENCE for d in divergences)
