"""Integration test for complete 3-round synthetic episode execution."""

from decimal import Decimal

import pytest

from simulator.application.policies.reactive import ReactiveObservationPolicy
from simulator.application.policies.static import StaticBaselinePolicy
from simulator.application.services.runner import EpisodeRunner
from simulator.domain.lifecycle import LifecycleStatus
from simulator.domain.models import EpisodeDefinition
from simulator.infrastructure.adapters.in_memory_clock import InMemoryClock
from simulator.infrastructure.adapters.in_memory_store import InMemoryStore
from simulator.infrastructure.adapters.synthetic_dataset import SyntheticDatasetAdapter
from simulator.infrastructure.adapters.synthetic_pricing import SyntheticPricingAdapter


def test_complete_synthetic_episode_execution(synthetic_episode_def: EpisodeDefinition) -> None:
    store = InMemoryStore()
    dataset = SyntheticDatasetAdapter()
    clock = InMemoryClock(initial_time="2026-08-01T00:00:00Z")

    policies = {
        "pol-def_static_baseline": StaticBaselinePolicy(),
        "pol-def_reactive_baseline": ReactiveObservationPolicy(
            target_resource_id="RES_ALPHA",
            reference_resource_id="USD",
        ),
    }

    runner = EpisodeRunner(
        persistence=store,
        dataset=dataset,
        clock=clock,
        policies=policies,
        pricing=SyntheticPricingAdapter(),
    )

    episode_def = synthetic_episode_def
    run_id = "ep-run_synth_001"

    init_run = runner.initialize_episode(episode_def, run_id)
    assert init_run.lifecycle_status == LifecycleStatus.CONFIGURED

    final_run = runner.run_all_rounds(run_id)
    assert final_run.lifecycle_status == LifecycleStatus.COMPLETED
    assert final_run.current_round_index == 3
    assert final_run.final_state_hash is not None

    # Check 3 rounds were recorded
    rounds = store.get_rounds(run_id)
    assert len(rounds) == 3
    assert [record.compute_hash() for record in rounds] == [
        "sha256:491a35d4c55cb03cc6fa0f9b04c6f4d32dbd44533ef52f50858314fcd162ef7b",
        "sha256:64123d4977deafc4c59249c368fab5dc4d72263d6f562a625b9af84e6f1e9fe1",
        "sha256:0680c7a456ea2b44b995ca0febeb463ba2d946b1ae9a17b90e7ceda600aab0ae",
    ]
    assert (
        final_run.final_state_hash
        == "sha256:0680c7a456ea2b44b995ca0febeb463ba2d946b1ae9a17b90e7ceda600aab0ae"
    )

    # Check round hashes are chained
    assert rounds[0].parent_round_hash is None
    assert rounds[1].parent_round_hash == rounds[0].compute_hash()
    assert rounds[2].parent_round_hash == rounds[1].compute_hash()

    # Check Static policy account: unchanged at 10000 USD
    static_states = store.get_account_states(run_id, "pol-def_static_baseline")
    assert len(static_states) == 4  # genesis + 3 rounds
    assert static_states[-1].reference_valuation.net_total_value == Decimal("10000.00")

    # Check Reactive policy account: bought RES_ALPHA in round 0
    # In round 0: price = 100.00, alloc 20% of 10000 = 2000 USD / 100 = 20 units
    # Fee: 2.00 + 1.00 = 3.00 USD -> cash: 7997.00 USD
    # In round 1: RES_ALPHA price = 105.00 -> 20 units worth 2100.00 USD + cash
    # Alloc 20% of 7997 = 1599.40 / 105 = 15.23 units
    reactive_states = store.get_account_states(run_id, "pol-def_reactive_baseline")
    assert len(reactive_states) == 4
    assert reactive_states[1].reference_valuation.unallocated_cash == Decimal("7997.00")
    assert reactive_states[1].reference_valuation.allocated_resources_value == Decimal("2000.00")
    assert (
        static_states[-1].compute_hash()
        == "sha256:3ac64f13d3ba1a9cbd32b16ad025a53fc999a9aa28e9fa3321dae3331543367e"
    )
    assert (
        reactive_states[-1].compute_hash()
        == "sha256:98a92dc14f5e3ed660f33fdf473af7fbd15ba17aca756140331a3d24a6c179f9"
    )

    # Check metrics
    metrics = store.get_metric_records(run_id)
    assert len(metrics) == 2  # one final metric per policy
    static_m = next(m for m in metrics if m.policy_id == "pol-def_static_baseline")
    reactive_m = next(m for m in metrics if m.policy_id == "pol-def_reactive_baseline")
    assert static_m.metrics.total_return == 0.0
    reactive_transitions = store.get_transitions(run_id, "pol-def_reactive_baseline")
    assert reactive_m.metrics.total_transaction_costs == sum(
        (item.total_cost_reference_unit for item in reactive_transitions),
        Decimal("0.00"),
    )


def test_policy_order_independence(synthetic_episode_def: EpisodeDefinition) -> None:
    # Running policies in reversed dictionary order produces identical per-policy hashes
    store1 = InMemoryStore()
    dataset1 = SyntheticDatasetAdapter()
    clock1 = InMemoryClock()
    policies1 = {
        "pol-def_static_baseline": StaticBaselinePolicy(),
        "pol-def_reactive_baseline": ReactiveObservationPolicy(),
    }
    runner1 = EpisodeRunner(store1, dataset1, clock1, policies1, SyntheticPricingAdapter())
    runner1.initialize_episode(synthetic_episode_def, "run_order_test")
    res1 = runner1.run_all_rounds("run_order_test")

    store2 = InMemoryStore()
    dataset2 = SyntheticDatasetAdapter()
    clock2 = InMemoryClock()
    # Reversed dictionary insertion order
    policies2 = {
        "pol-def_reactive_baseline": ReactiveObservationPolicy(),
        "pol-def_static_baseline": StaticBaselinePolicy(),
    }
    runner2 = EpisodeRunner(store2, dataset2, clock2, policies2, SyntheticPricingAdapter())
    runner2.initialize_episode(synthetic_episode_def, "run_order_test")
    res2 = runner2.run_all_rounds("run_order_test")

    # Hashes and final state hashes must match
    assert res1.final_state_hash == res2.final_state_hash


def test_two_runs_share_a_store_without_record_identity_collisions(
    synthetic_episode_def: EpisodeDefinition,
) -> None:
    store = InMemoryStore()
    runner = EpisodeRunner(
        store,
        SyntheticDatasetAdapter(),
        InMemoryClock(),
        {
            "pol-def_static_baseline": StaticBaselinePolicy(),
            "pol-def_reactive_baseline": ReactiveObservationPolicy(),
        },
        SyntheticPricingAdapter(),
    )

    for run_id in ("ep-run_repeat_001", "ep-run_repeat_002"):
        runner.initialize_episode(synthetic_episode_def, run_id)
        assert runner.run_all_rounds(run_id).lifecycle_status == LifecycleStatus.COMPLETED
        assert len(store.get_rounds(run_id)) == 3

    first_ids = {record.round_id for record in store.get_rounds("ep-run_repeat_001")}
    second_ids = {record.round_id for record in store.get_rounds("ep-run_repeat_002")}
    assert first_ids.isdisjoint(second_ids)


def test_failed_round_commit_publishes_no_partial_records(
    synthetic_episode_def: EpisodeDefinition,
) -> None:
    class RejectingCommitStore(InMemoryStore):
        def commit_round(self, commit) -> None:
            raise RuntimeError("injected commit failure")

    store = RejectingCommitStore()
    runner = EpisodeRunner(
        store,
        SyntheticDatasetAdapter(),
        InMemoryClock(),
        {
            "pol-def_static_baseline": StaticBaselinePolicy(),
            "pol-def_reactive_baseline": ReactiveObservationPolicy(),
        },
        SyntheticPricingAdapter(),
    )
    run_id = "ep-run_atomic_failure"
    runner.initialize_episode(synthetic_episode_def, run_id)
    runner.start_run(run_id)

    with pytest.raises(RuntimeError, match="injected commit failure"):
        runner.execute_next_round(run_id)

    assert store.get_rounds(run_id) == []
    assert store._proposed_decisions == {}
    assert store._decision_outcomes == {}
    assert store._transitions == {}
    assert all(len(states) == 1 for states in store._account_states.values())
    assert store.get_episode_run(run_id).current_round_index == 0
