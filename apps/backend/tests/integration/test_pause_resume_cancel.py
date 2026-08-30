"""Integration tests for episode pausing, idempotent resumption, and cancellation."""

from simulator.application.policies.static import StaticBaselinePolicy
from simulator.application.services.runner import EpisodeRunner
from simulator.domain.lifecycle import LifecycleStatus
from simulator.domain.models import EpisodeDefinition
from simulator.infrastructure.adapters.in_memory_clock import InMemoryClock
from simulator.infrastructure.adapters.in_memory_store import InMemoryStore
from simulator.infrastructure.adapters.synthetic_dataset import SyntheticDatasetAdapter
from simulator.infrastructure.adapters.synthetic_pricing import SyntheticPricingAdapter


def test_pause_idempotent_resume_and_completion(synthetic_episode_def: EpisodeDefinition) -> None:
    store = InMemoryStore()
    dataset = SyntheticDatasetAdapter()
    clock = InMemoryClock()
    policies = {
        "pol-def_static_baseline": StaticBaselinePolicy(),
        "pol-def_reactive_baseline": StaticBaselinePolicy(
            policy_id="pol-def_reactive_baseline",
            policy_version_id="pol-ver_reactive_v1",
        ),
    }
    runner = EpisodeRunner(store, dataset, clock, policies, SyntheticPricingAdapter())
    ep_def = synthetic_episode_def
    run_id = "run_pause_test"

    runner.initialize_episode(ep_def, run_id)
    runner.start_run(run_id)

    # Execute round 0
    r0 = runner.execute_next_round(run_id)
    assert r0 is not None
    assert r0.round_index == 0

    # Pause at round boundary
    paused_run = runner.pause_run(run_id)
    assert paused_run.lifecycle_status == LifecycleStatus.PAUSED

    # Attempting to execute next round while paused returns None
    assert runner.execute_next_round(run_id) is None

    # Idempotent resume
    resumed1 = runner.resume_run(run_id)
    assert resumed1.lifecycle_status == LifecycleStatus.RUNNING
    resumed2 = runner.resume_run(run_id)
    assert resumed2.lifecycle_status == LifecycleStatus.RUNNING

    # Continue remaining rounds
    final_run = runner.run_all_rounds(run_id)
    assert final_run.lifecycle_status == LifecycleStatus.COMPLETED
    assert final_run.current_round_index == 3


def test_cancellation_at_boundary(synthetic_episode_def: EpisodeDefinition) -> None:
    store = InMemoryStore()
    dataset = SyntheticDatasetAdapter()
    clock = InMemoryClock()
    policies = {
        "pol-def_static_baseline": StaticBaselinePolicy(),
        "pol-def_reactive_baseline": StaticBaselinePolicy(
            policy_id="pol-def_reactive_baseline",
            policy_version_id="pol-ver_reactive_v1",
        ),
    }
    runner = EpisodeRunner(store, dataset, clock, policies, SyntheticPricingAdapter())
    ep_def = synthetic_episode_def
    run_id = "run_cancel_test"

    runner.initialize_episode(ep_def, run_id)
    runner.start_run(run_id)

    # Execute round 0
    runner.execute_next_round(run_id)

    # Cancel run
    cancelled_run = runner.cancel_run(run_id, reason="User test cancellation")
    assert cancelled_run.lifecycle_status == LifecycleStatus.CANCELLED
    assert cancelled_run.failure_reason == "User test cancellation"

    # Further executions return None
    assert runner.execute_next_round(run_id) is None
