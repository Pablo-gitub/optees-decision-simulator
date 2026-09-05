"""Unit tests for deferred atomic persistence in InMemoryStore (DS-02D2C1A)."""

from dataclasses import replace
from decimal import Decimal

import pytest

from simulator.application.ports.persistence import RoundCommit, TerminalCommit
from simulator.domain.deferred_round import (
    DeferredPolicyRoundRecord,
    DeferredRoundRecord,
    PendingStateReference,
    compute_deferred_state_merkle_hash,
)
from simulator.domain.deferred_terminal import (
    DeferredRunTerminalRecord,
    PolicyTerminalRecord,
    compute_terminal_record_id,
    compute_terminal_state_merkle_hash,
)
from simulator.domain.errors import (
    DuplicateIdentityError,
    FrozenRecordMutationError,
)
from simulator.domain.lifecycle import (
    ActionType,
    DecisionStatus,
    LifecycleStatus,
    SettlementStatus,
)
from simulator.domain.models import (
    AccountBalanceSpec,
    BalanceItem,
    CalendarSpec,
    CostModelSpec,
    DatasetSnapshotRef,
    DecisionOutcome,
    DecisionRationale,
    EpisodeDefinition,
    EpisodeRulesSpec,
    EpisodeRun,
    FailurePolicySpec,
    InitialAccountSpec,
    MetricRecord,
    MetricsData,
    PendingTransitionRecord,
    PolicyVersionRef,
    ProposedDecision,
    ReferenceValuation,
    RejectionReason,
    RequestedAction,
    RoundRecord,
    SettlementOutcome,
    TargetBarRule,
    VirtualAccountState,
)
from simulator.infrastructure.adapters.in_memory_store import InMemoryStore


def _make_episode(episode_id="ep-def_001", policy_ids=("pol-def_alpha", "pol-def_beta")):
    return EpisodeDefinition(
        episode_id=episode_id,
        title="Test Episode",
        description="Deferred testing",
        created_at="2026-08-01T00:00:00Z",
        dataset_snapshot=DatasetSnapshotRef(
            snapshot_id="snap_001",
            source_uri="file:///data/snapshot_001",
            checksum_sha256="sha256:" + "0" * 64,
            retrieval_time="2026-08-01T00:00:00Z",
            calendar_frequency="1d",
        ),
        calendar=CalendarSpec(
            round_cutoffs=("2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z"),
            interval_duration="1d",
            evaluation_delay="1d",
        ),
        policy_versions=tuple(
            PolicyVersionRef(
                policy_id=p,
                policy_version_id=f"pol-ver_{p}",
                policy_version="1.0.0",
                policy_hash="sha256:" + "1" * 64,
                config_hash="sha256:" + "2" * 64,
            )
            for p in sorted(policy_ids)
        ),
        initial_accounts=tuple(
            InitialAccountSpec(
                policy_id=p,
                balances=(AccountBalanceSpec(resource_id="res_usd", quantity=Decimal("10000.00")),),
            )
            for p in sorted(policy_ids)
        ),
        reference_resource_id="res_usd",
        rules=EpisodeRulesSpec(
            allow_short_positions=False,
            allow_borrowing=False,
            cost_model=CostModelSpec(Decimal("0"), Decimal("0"), Decimal("0")),
            failure_policy=FailurePolicySpec(),
        ),
    )


def _make_run(run_id="ep-run_001", episode_id="ep-def_001", status=LifecycleStatus.RUNNING):
    return EpisodeRun(
        run_id=run_id,
        episode_id=episode_id,
        episode_definition_hash="sha256:" + "0" * 64,
        lifecycle_status=status,
        started_at="2026-08-01T00:00:00Z",
        ended_at=None,
        current_round_index=0,
        total_rounds=3,
        final_state_hash=None,
    )


def _make_genesis_account(run_id, policy_id):
    return VirtualAccountState(
        account_state_id=f"acc-state_{run_id}_genesis_{policy_id}",
        policy_id=policy_id,
        round_index=0,
        as_of_time="2026-08-01T00:00:00Z",
        balances=(BalanceItem("res_usd", Decimal("10000.00"), Decimal("0.00")),),
        cumulative_costs=(),
        reference_valuation=ReferenceValuation(
            reference_resource_id="res_usd",
            unallocated_cash=Decimal("10000.00"),
            allocated_resources_value=Decimal("0.00"),
            net_total_value=Decimal("10000.00"),
        ),
        parent_state_hash=None,
    )


def _make_proposal(
    decision_id: str,
    round_id: str,
    policy_id: str,
    requested_actions: tuple[RequestedAction, ...] = (),
) -> ProposedDecision:
    return ProposedDecision(
        decision_id=decision_id,
        round_id=round_id,
        policy_id=policy_id,
        policy_version_id=f"pol-ver_{policy_id}",
        knowledge_cutoff="2026-08-01T00:00:00Z",
        generated_at="2026-08-01T00:00:00Z",
        desired_allocations=(),
        requested_actions=requested_actions,
        rationale=DecisionRationale(method="test"),
    )


def _make_metric(run_id: str, metric_id="metric_001") -> MetricRecord:
    return MetricRecord(
        metric_record_id=metric_id,
        run_id=run_id,
        policy_id="pol-def_alpha",
        round_index=0,
        calculated_at="2026-08-01T00:00:02Z",
        metrics=MetricsData(
            final_net_value=Decimal("10000.00"),
            total_return=0.0,
            max_drawdown=0.0,
            volatility=0.0,
            turnover=0.0,
            total_transaction_costs=Decimal("0.00"),
            rejected_decision_count=0,
            solver_call_count=0,
            validation_failure_count=0,
            execution_wall_time_seconds=0.0,
        ),
    )


@pytest.fixture
def store_with_run():
    store = InMemoryStore()
    ep = _make_episode()
    store.save_episode_definition(ep)

    run = _make_run()
    store.save_episode_run(run)

    for p in ("pol-def_alpha", "pol-def_beta"):
        acc = _make_genesis_account(run.run_id, p)
        store.save_account_state(run.run_id, acc)

    return store, ep, run


def test_deferred_round_commit(store_with_run):
    store, ep, run = store_with_run
    run_id = run.run_id

    acc_a_0 = store.get_latest_account_state(run_id, "pol-def_alpha")
    acc_b_0 = store.get_latest_account_state(run_id, "pol-def_beta")

    # Round 0: Alpha proposes and admits pending order; Beta proposes HOLD
    prop_a = _make_proposal(
        decision_id="dec-prop_alpha_0",
        round_id="rnd_000",
        policy_id="pol-def_alpha",
        requested_actions=(
            RequestedAction(
                action_type=ActionType.ALLOCATE,
                resource_id="res_btc",
                quantity=Decimal("1.0"),
            ),
        ),
    )
    pending_a = PendingTransitionRecord(
        pending_transition_id="pnd_alpha_0",
        decision_id=prop_a.decision_id,
        round_id="rnd_000",
        policy_id="pol-def_alpha",
        policy_version_id=prop_a.policy_version_id,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        admitted_at="2026-08-01T00:00:00Z",
        predecessor_account_hash=acc_a_0.compute_hash(),
        requested_action=prop_a.requested_actions[0],
        target_bar_rule=TargetBarRule(
            series_id="series_btc_1d",
            expected_open_time="2026-08-01T00:00:00Z",
        ),
    )
    pending_ref_a = PendingStateReference(
        pending_transition_hash=pending_a.compute_hash(),
        admission_account_hash=acc_a_0.compute_hash(),
        expected_open_time="2026-08-01T00:00:00Z",
        settlement_deadline="2026-08-03T00:00:00Z",
    )

    prop_b = _make_proposal(
        decision_id="dec-prop_beta_0",
        round_id="rnd_000",
        policy_id="pol-def_beta",
        requested_actions=(),
    )
    outcome_b = DecisionOutcome(
        outcome_id="dec-out_beta_0",
        decision_id=prop_b.decision_id,
        round_id="rnd_000",
        policy_id="pol-def_beta",
        status=DecisionStatus.ACCEPTED,
        rejection_reasons=(),
        evaluated_at="2026-08-01T00:00:00Z",
    )

    pol_record_a = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=acc_a_0.compute_hash(),
        account_state_after_hash=acc_a_0.compute_hash(),
        pending_before=None,
        pending_after=pending_ref_a,
        settlement_outcome_hash=None,
        deferred_transition_hash=None,
        proposed_decision_hash=prop_a.compute_hash(),
        decision_outcome_hash=None,
    )
    pol_record_b = DeferredPolicyRoundRecord(
        policy_id="pol-def_beta",
        account_state_before_hash=acc_b_0.compute_hash(),
        account_state_after_hash=acc_b_0.compute_hash(),
        pending_before=None,
        pending_after=None,
        settlement_outcome_hash=None,
        deferred_transition_hash=None,
        proposed_decision_hash=prop_b.compute_hash(),
        decision_outcome_hash=outcome_b.compute_hash(),
    )

    merkle_0 = compute_deferred_state_merkle_hash(None, (pol_record_a, pol_record_b))
    round_0 = DeferredRoundRecord(
        round_id="rnd_000",
        run_id=run_id,
        round_index=0,
        parent_round_hash=None,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        execution_start_time="2026-08-01T00:00:01Z",
        execution_end_time="2026-08-01T00:00:02Z",
        effective_time="2026-08-01T00:00:02Z",
        eligible_observation_hashes=(),
        policy_round_records=(pol_record_a, pol_record_b),
        state_merkle_hash=merkle_0,
    )

    commit_0 = RoundCommit(
        run=EpisodeRun(
            run_id=run_id,
            episode_id=ep.episode_id,
            episode_definition_hash=run.episode_definition_hash,
            lifecycle_status=LifecycleStatus.RUNNING,
            started_at=run.started_at,
            ended_at=None,
            current_round_index=1,
            total_rounds=3,
            final_state_hash=None,
        ),
        round_record=round_0,
        proposed_decisions=(prop_a, prop_b),
        decision_outcomes=(outcome_b,),
        pending_transitions=(pending_a,),
    )

    store.commit_round(commit_0)

    # Verifications
    assert store.get_rounds(run_id) == [round_0]
    assert store.get_active_pending_reference(run_id, "pol-def_alpha") == pending_ref_a
    assert store.get_active_pending_reference(run_id, "pol-def_beta") is None
    assert store.get_pending_transition(pending_a.pending_transition_id) == pending_a
    assert store.get_pending_transitions(run_id) == [pending_a]
    assert store.get_pending_transitions(run_id, "pol-def_alpha") == [pending_a]
    assert store.get_pending_transitions(run_id, "pol-def_beta") == []


def test_final_round_plus_terminal_commit(store_with_run):
    store, ep, run = store_with_run
    run_id = run.run_id

    # Commit round 0 as final round with active pending terminated
    acc_a_0 = store.get_latest_account_state(run_id, "pol-def_alpha")
    acc_b_0 = store.get_latest_account_state(run_id, "pol-def_beta")

    prop_a = _make_proposal(
        decision_id="dec-prop_alpha_0",
        round_id="rnd_000",
        policy_id="pol-def_alpha",
        requested_actions=(
            RequestedAction(
                action_type=ActionType.ALLOCATE,
                resource_id="res_btc",
                quantity=Decimal("1.0"),
            ),
        ),
    )
    pending_a = PendingTransitionRecord(
        pending_transition_id="pnd_alpha_0",
        decision_id=prop_a.decision_id,
        round_id="rnd_000",
        policy_id="pol-def_alpha",
        policy_version_id=prop_a.policy_version_id,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        admitted_at="2026-08-01T00:00:00Z",
        predecessor_account_hash=acc_a_0.compute_hash(),
        requested_action=prop_a.requested_actions[0],
        target_bar_rule=TargetBarRule(
            series_id="series_btc_1d",
            expected_open_time="2026-08-01T00:00:00Z",
        ),
    )
    pending_ref_a = PendingStateReference(
        pending_transition_hash=pending_a.compute_hash(),
        admission_account_hash=acc_a_0.compute_hash(),
        expected_open_time="2026-08-01T00:00:00Z",
        settlement_deadline="2026-08-03T00:00:00Z",
    )

    pol_record_a = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=acc_a_0.compute_hash(),
        account_state_after_hash=acc_a_0.compute_hash(),
        pending_before=None,
        pending_after=pending_ref_a,
        settlement_outcome_hash=None,
        deferred_transition_hash=None,
        proposed_decision_hash=prop_a.compute_hash(),
        decision_outcome_hash=None,
    )
    pol_record_b = DeferredPolicyRoundRecord(
        policy_id="pol-def_beta",
        account_state_before_hash=acc_b_0.compute_hash(),
        account_state_after_hash=acc_b_0.compute_hash(),
        pending_before=None,
        pending_after=None,
        settlement_outcome_hash=None,
        deferred_transition_hash=None,
        proposed_decision_hash=None,
        decision_outcome_hash=None,
    )

    round_0 = DeferredRoundRecord(
        round_id="rnd_000",
        run_id=run_id,
        round_index=0,
        parent_round_hash=None,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        execution_start_time="2026-08-01T00:00:01Z",
        execution_end_time="2026-08-01T00:00:02Z",
        effective_time="2026-08-01T00:00:02Z",
        eligible_observation_hashes=(),
        policy_round_records=(pol_record_a, pol_record_b),
        state_merkle_hash=compute_deferred_state_merkle_hash(None, (pol_record_a, pol_record_b)),
    )

    term_so_a = SettlementOutcome(
        settlement_outcome_id="set-out_term_alpha",
        pending_transition_id=pending_a.pending_transition_id,
        decision_id=prop_a.decision_id,
        round_id="rnd_000",
        policy_id="pol-def_alpha",
        status=SettlementStatus.REJECTED,
        settled_at="2026-08-01T00:00:00Z",
        rejection_reasons=(
            RejectionReason("UNSETTLED_EPISODE_TERMINATION", "Final round pending termination"),
        ),
    )

    p_term_a = PolicyTerminalRecord(
        policy_id="pol-def_alpha",
        account_state_hash=acc_a_0.compute_hash(),
        pending_transition_hash=pending_a.compute_hash(),
        settlement_outcome_hash=term_so_a.compute_hash(),
    )
    p_term_b = PolicyTerminalRecord(
        policy_id="pol-def_beta",
        account_state_hash=acc_b_0.compute_hash(),
        pending_transition_hash=None,
        settlement_outcome_hash=None,
    )

    parent_round_hash = round_0.compute_hash()
    term_id = compute_terminal_record_id(run_id, "COMPLETED", parent_round_hash)
    term_merkle = compute_terminal_state_merkle_hash(parent_round_hash, (p_term_a, p_term_b))

    terminal_rec = DeferredRunTerminalRecord(
        terminal_record_id=term_id,
        run_id=run_id,
        episode_id=ep.episode_id,
        terminal_status="COMPLETED",
        reason_code="UNSETTLED_EPISODE_TERMINATION",
        reason_message="Final round completed with active pending terminated",
        simulation_frontier_time="2026-08-01T00:00:00Z",
        execution_timestamp="2026-08-01T00:00:02Z",
        parent_round_hash=parent_round_hash,
        policy_terminal_records=(p_term_a, p_term_b),
        terminal_state_merkle_hash=term_merkle,
    )

    completed_run = EpisodeRun(
        run_id=run_id,
        episode_id=ep.episode_id,
        episode_definition_hash=run.episode_definition_hash,
        lifecycle_status=LifecycleStatus.COMPLETED,
        started_at=run.started_at,
        ended_at="2026-08-01T00:00:02Z",
        current_round_index=1,
        total_rounds=run.total_rounds,
        final_state_hash=terminal_rec.compute_hash(),
    )

    commit = RoundCommit(
        run=completed_run,
        round_record=round_0,
        proposed_decisions=(prop_a,),
        pending_transitions=(pending_a,),
        settlement_outcomes=(term_so_a,),
        terminal_record=terminal_rec,
    )

    store.commit_round(commit)

    # Check store state
    assert store.get_terminal_record(run_id) == terminal_rec
    assert store.get_episode_run(run_id).lifecycle_status == LifecycleStatus.COMPLETED
    assert store.get_active_pending_reference(run_id, "pol-def_alpha") is None
    assert store.get_settlement_outcome(term_so_a.settlement_outcome_id) == term_so_a


def test_genesis_cancellation_terminal_commit(store_with_run):
    store, ep, run = store_with_run
    run_id = run.run_id

    acc_a_0 = store.get_latest_account_state(run_id, "pol-def_alpha")
    acc_b_0 = store.get_latest_account_state(run_id, "pol-def_beta")

    p_term_a = PolicyTerminalRecord("pol-def_alpha", acc_a_0.compute_hash())
    p_term_b = PolicyTerminalRecord("pol-def_beta", acc_b_0.compute_hash())

    term_id = compute_terminal_record_id(run_id, "CANCELLED", None)
    term_merkle = compute_terminal_state_merkle_hash(None, (p_term_a, p_term_b))

    terminal_rec = DeferredRunTerminalRecord(
        terminal_record_id=term_id,
        run_id=run_id,
        episode_id=ep.episode_id,
        terminal_status="CANCELLED",
        reason_code="EPISODE_CANCELLED",
        reason_message="Genesis cancellation",
        simulation_frontier_time=None,
        execution_timestamp="2026-08-01T00:00:01Z",
        parent_round_hash=None,
        policy_terminal_records=(p_term_a, p_term_b),
        terminal_state_merkle_hash=term_merkle,
    )

    cancelled_run = EpisodeRun(
        run_id=run_id,
        episode_id=ep.episode_id,
        episode_definition_hash=run.episode_definition_hash,
        lifecycle_status=LifecycleStatus.CANCELLED,
        started_at=run.started_at,
        ended_at="2026-08-01T00:00:01Z",
        current_round_index=0,
        total_rounds=3,
        final_state_hash=terminal_rec.compute_hash(),
    )

    commit = TerminalCommit(
        expected_run_hash=run.compute_hash(),
        run=cancelled_run,
        terminal_record=terminal_rec,
    )

    store.commit_terminal(commit)

    assert store.get_terminal_record(run_id) == terminal_rec
    assert store.get_episode_run(run_id).lifecycle_status == LifecycleStatus.CANCELLED


def test_exact_retry_idempotency(store_with_run):
    store, ep, run = store_with_run
    run_id = run.run_id

    # Genesis cancellation
    acc_a_0 = store.get_latest_account_state(run_id, "pol-def_alpha")
    acc_b_0 = store.get_latest_account_state(run_id, "pol-def_beta")
    p_term_a = PolicyTerminalRecord("pol-def_alpha", acc_a_0.compute_hash())
    p_term_b = PolicyTerminalRecord("pol-def_beta", acc_b_0.compute_hash())
    term_id = compute_terminal_record_id(run_id, "CANCELLED", None)
    term_merkle = compute_terminal_state_merkle_hash(None, (p_term_a, p_term_b))

    terminal_rec = DeferredRunTerminalRecord(
        terminal_record_id=term_id,
        run_id=run_id,
        episode_id=ep.episode_id,
        terminal_status="CANCELLED",
        reason_code="EPISODE_CANCELLED",
        reason_message="Genesis cancellation",
        simulation_frontier_time=None,
        execution_timestamp="2026-08-01T00:00:01Z",
        parent_round_hash=None,
        policy_terminal_records=(p_term_a, p_term_b),
        terminal_state_merkle_hash=term_merkle,
    )
    cancelled_run = EpisodeRun(
        run_id=run_id,
        episode_id=ep.episode_id,
        episode_definition_hash=run.episode_definition_hash,
        lifecycle_status=LifecycleStatus.CANCELLED,
        started_at=run.started_at,
        ended_at="2026-08-01T00:00:01Z",
        current_round_index=0,
        total_rounds=3,
        final_state_hash=terminal_rec.compute_hash(),
    )
    commit = TerminalCommit(
        expected_run_hash=run.compute_hash(),
        run=cancelled_run,
        terminal_record=terminal_rec,
    )

    store.commit_terminal(commit)

    # Identical retry must succeed without error (idempotent no-op)
    store.commit_terminal(commit)


def test_modified_retry_fails_closed(store_with_run):
    store, ep, run = store_with_run
    run_id = run.run_id

    acc_a_0 = store.get_latest_account_state(run_id, "pol-def_alpha")
    acc_b_0 = store.get_latest_account_state(run_id, "pol-def_beta")
    p_term_a = PolicyTerminalRecord("pol-def_alpha", acc_a_0.compute_hash())
    p_term_b = PolicyTerminalRecord("pol-def_beta", acc_b_0.compute_hash())
    term_id = compute_terminal_record_id(run_id, "CANCELLED", None)
    term_merkle = compute_terminal_state_merkle_hash(None, (p_term_a, p_term_b))

    terminal_rec = DeferredRunTerminalRecord(
        terminal_record_id=term_id,
        run_id=run_id,
        episode_id=ep.episode_id,
        terminal_status="CANCELLED",
        reason_code="EPISODE_CANCELLED",
        reason_message="Genesis cancellation",
        simulation_frontier_time=None,
        execution_timestamp="2026-08-01T00:00:01Z",
        parent_round_hash=None,
        policy_terminal_records=(p_term_a, p_term_b),
        terminal_state_merkle_hash=term_merkle,
    )
    cancelled_run = EpisodeRun(
        run_id=run_id,
        episode_id=ep.episode_id,
        episode_definition_hash=run.episode_definition_hash,
        lifecycle_status=LifecycleStatus.CANCELLED,
        started_at=run.started_at,
        ended_at="2026-08-01T00:00:01Z",
        current_round_index=0,
        total_rounds=3,
        final_state_hash=terminal_rec.compute_hash(),
    )
    commit = TerminalCommit(
        expected_run_hash=run.compute_hash(),
        run=cancelled_run,
        terminal_record=terminal_rec,
    )
    store.commit_terminal(commit)

    # Mutated payload with same ID -> fails closed
    drifted_term = DeferredRunTerminalRecord(
        terminal_record_id=term_id,
        run_id=run_id,
        episode_id=ep.episode_id,
        terminal_status="CANCELLED",
        reason_code="EPISODE_CANCELLED",
        reason_message="DIFFERENT MESSAGE",
        simulation_frontier_time=None,
        execution_timestamp="2026-08-01T00:00:01Z",
        parent_round_hash=None,
        policy_terminal_records=(p_term_a, p_term_b),
        terminal_state_merkle_hash=term_merkle,
    )
    drifted_commit = TerminalCommit(
        expected_run_hash=run.compute_hash(),
        run=cancelled_run,
        terminal_record=drifted_term,
    )
    with pytest.raises(FrozenRecordMutationError):
        store.commit_terminal(drifted_commit)


def test_stale_parent_race_rejected(store_with_run):
    store, ep, run = store_with_run
    run_id = run.run_id

    # Round with non-matching parent hash
    pol_a = DeferredPolicyRoundRecord(
        "pol-def_alpha",
        "sha256:" + "a" * 64,
        "sha256:" + "a" * 64,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    pol_b = DeferredPolicyRoundRecord(
        "pol-def_beta",
        "sha256:" + "b" * 64,
        "sha256:" + "b" * 64,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    merkle = compute_deferred_state_merkle_hash("sha256:" + "9" * 64, (pol_a, pol_b))

    round_race = DeferredRoundRecord(
        round_id="rnd_000",
        run_id=run_id,
        round_index=0,
        parent_round_hash="sha256:" + "9" * 64,  # Stale! Expected None at round 0
        knowledge_cutoff="2026-08-01T00:00:00Z",
        execution_start_time="2026-08-01T00:00:01Z",
        execution_end_time="2026-08-01T00:00:02Z",
        effective_time="2026-08-01T00:00:02Z",
        eligible_observation_hashes=(),
        policy_round_records=(pol_a, pol_b),
        state_merkle_hash=merkle,
    )
    commit = RoundCommit(run=run, round_record=round_race)
    with pytest.raises(FrozenRecordMutationError, match="Parent round hash mismatch"):
        store.commit_round(commit)


def test_fault_injection_leaves_store_intact(store_with_run):
    store, ep, run = store_with_run
    run_id = run.run_id

    initial_rounds = store.get_rounds(run_id)
    initial_run = store.get_episode_run(run_id)

    # Invalid commit (duplicate proposed decision ID)
    prop1 = _make_proposal("dec-prop_01", "rnd_000", "pol-def_alpha")
    prop2 = _make_proposal("dec-prop_01", "rnd_000", "pol-def_alpha")

    pol_a = DeferredPolicyRoundRecord(
        "pol-def_alpha",
        "sha256:" + "a" * 64,
        "sha256:" + "a" * 64,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    pol_b = DeferredPolicyRoundRecord(
        "pol-def_beta",
        "sha256:" + "b" * 64,
        "sha256:" + "b" * 64,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    round_0 = DeferredRoundRecord(
        round_id="rnd_000",
        run_id=run_id,
        round_index=0,
        parent_round_hash=None,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        execution_start_time="2026-08-01T00:00:01Z",
        execution_end_time="2026-08-01T00:00:02Z",
        effective_time="2026-08-01T00:00:02Z",
        eligible_observation_hashes=(),
        policy_round_records=(pol_a, pol_b),
        state_merkle_hash=compute_deferred_state_merkle_hash(None, (pol_a, pol_b)),
    )
    progressed_run = EpisodeRun(
        run_id=run.run_id,
        episode_id=run.episode_id,
        episode_definition_hash=run.episode_definition_hash,
        lifecycle_status=LifecycleStatus.RUNNING,
        started_at=run.started_at,
        ended_at=None,
        current_round_index=1,
        total_rounds=run.total_rounds,
        final_state_hash=None,
    )
    commit = RoundCommit(
        run=progressed_run,
        round_record=round_0,
        proposed_decisions=(prop1, prop2),
    )

    with pytest.raises(DuplicateIdentityError):
        store.commit_round(commit)

    # Store maps must be completely untouched
    assert store.get_rounds(run_id) == initial_rounds
    assert store.get_episode_run(run_id) == initial_run
    assert store.get_proposed_decision("dec-prop_01") is None


def test_v1_synchronous_round_commit_regression(store_with_run):
    store, ep, run = store_with_run
    run_id = run.run_id

    # Ensure v1 RoundCommit continues working without regressions
    v1_round = RoundRecord(
        round_id="rnd_v1_000",
        run_id=run_id,
        round_index=0,
        parent_round_hash=None,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        execution_start_time="2026-08-01T00:00:01Z",
        execution_end_time="2026-08-01T00:00:02Z",
        effective_time="2026-08-01T00:00:02Z",
        eligible_observation_hashes=(),
        policy_round_records=(),
        state_merkle_hash="sha256:" + "0" * 64,
    )
    commit = RoundCommit(
        run=EpisodeRun(
            run_id=run_id,
            episode_id=ep.episode_id,
            episode_definition_hash=run.episode_definition_hash,
            lifecycle_status=LifecycleStatus.RUNNING,
            started_at=run.started_at,
            ended_at=None,
            current_round_index=1,
            total_rounds=3,
            final_state_hash=None,
        ),
        round_record=v1_round,
    )
    store.commit_round(commit)

    assert store.get_rounds(run_id) == [v1_round]


def test_round_commit_exact_retry_idempotency_and_drift(store_with_run):
    store, ep, run = store_with_run
    run_id = run.run_id

    v1_round = RoundRecord(
        round_id="rnd_v1_000",
        run_id=run_id,
        round_index=0,
        parent_round_hash=None,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        execution_start_time="2026-08-01T00:00:01Z",
        execution_end_time="2026-08-01T00:00:02Z",
        effective_time="2026-08-01T00:00:02Z",
        eligible_observation_hashes=(),
        policy_round_records=(),
        state_merkle_hash="sha256:" + "0" * 64,
    )
    metric = _make_metric(run_id)
    commit = RoundCommit(
        run=EpisodeRun(
            run_id=run_id,
            episode_id=ep.episode_id,
            episode_definition_hash=run.episode_definition_hash,
            lifecycle_status=LifecycleStatus.RUNNING,
            started_at=run.started_at,
            ended_at=None,
            current_round_index=1,
            total_rounds=3,
            final_state_hash=None,
        ),
        round_record=v1_round,
        metrics=(metric,),
    )
    store.commit_round(commit)

    # A retry that silently omits part of the original batch is not exact.
    with pytest.raises(FrozenRecordMutationError, match="payload is not identical"):
        store.commit_round(replace(commit, metrics=()))

    # Identical retry must succeed idempotently
    store.commit_round(commit)

    # Drifted round with same round_id must fail closed
    drifted_round = RoundRecord(
        round_id="rnd_v1_000",
        run_id=run_id,
        round_index=0,
        parent_round_hash=None,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        execution_start_time="2026-08-01T00:00:01Z",
        execution_end_time="2026-08-01T00:00:02Z",
        effective_time="2026-08-01T00:00:09Z",  # Drifted!
        eligible_observation_hashes=(),
        policy_round_records=(),
        state_merkle_hash="sha256:" + "0" * 64,
    )
    drifted_commit = RoundCommit(
        run=commit.run,
        round_record=drifted_round,
    )
    with pytest.raises(FrozenRecordMutationError):
        store.commit_round(drifted_commit)


def test_cross_policy_isolation_deferred_getters(store_with_run):
    store, ep, run = store_with_run
    run_id = run.run_id

    acc_a_0 = store.get_latest_account_state(run_id, "pol-def_alpha")
    acc_b_0 = store.get_latest_account_state(run_id, "pol-def_beta")

    # Round 0: Alpha admits pending_a, Beta HOLD
    prop_a = _make_proposal(
        decision_id="dec-prop_alpha_0",
        round_id="rnd_000",
        policy_id="pol-def_alpha",
        requested_actions=(RequestedAction(ActionType.ALLOCATE, "res_btc", Decimal("1.0")),),
    )
    pending_a = PendingTransitionRecord(
        pending_transition_id="pnd_alpha_0",
        decision_id=prop_a.decision_id,
        round_id="rnd_000",
        policy_id="pol-def_alpha",
        policy_version_id=prop_a.policy_version_id,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        admitted_at="2026-08-01T00:00:00Z",
        predecessor_account_hash=acc_a_0.compute_hash(),
        requested_action=prop_a.requested_actions[0],
        target_bar_rule=TargetBarRule("series_btc_1d", expected_open_time="2026-08-01T00:00:00Z"),
    )
    pending_ref_a = PendingStateReference(
        pending_transition_hash=pending_a.compute_hash(),
        admission_account_hash=acc_a_0.compute_hash(),
        expected_open_time="2026-08-01T00:00:00Z",
        settlement_deadline="2026-08-03T00:00:00Z",
    )

    pol_a_0 = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=acc_a_0.compute_hash(),
        account_state_after_hash=acc_a_0.compute_hash(),
        pending_before=None,
        pending_after=pending_ref_a,
        settlement_outcome_hash=None,
        deferred_transition_hash=None,
        proposed_decision_hash=prop_a.compute_hash(),
        decision_outcome_hash=None,
    )
    pol_b_0 = DeferredPolicyRoundRecord(
        policy_id="pol-def_beta",
        account_state_before_hash=acc_b_0.compute_hash(),
        account_state_after_hash=acc_b_0.compute_hash(),
        pending_before=None,
        pending_after=None,
        settlement_outcome_hash=None,
        deferred_transition_hash=None,
        proposed_decision_hash=None,
        decision_outcome_hash=None,
    )

    round_0 = DeferredRoundRecord(
        round_id="rnd_000",
        run_id=run_id,
        round_index=0,
        parent_round_hash=None,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        execution_start_time="2026-08-01T00:00:01Z",
        execution_end_time="2026-08-01T00:00:02Z",
        effective_time="2026-08-01T00:00:02Z",
        eligible_observation_hashes=(),
        policy_round_records=(pol_a_0, pol_b_0),
        state_merkle_hash=compute_deferred_state_merkle_hash(None, (pol_a_0, pol_b_0)),
    )

    commit_0 = RoundCommit(
        run=EpisodeRun(
            run_id=run_id,
            episode_id=ep.episode_id,
            episode_definition_hash=run.episode_definition_hash,
            lifecycle_status=LifecycleStatus.RUNNING,
            started_at=run.started_at,
            ended_at=None,
            current_round_index=1,
            total_rounds=3,
            final_state_hash=None,
        ),
        round_record=round_0,
        proposed_decisions=(prop_a,),
        pending_transitions=(pending_a,),
    )
    store.commit_round(commit_0)

    # Round 1: Alpha settles pending_a, Beta admits pending_b
    so_a_1 = SettlementOutcome(
        settlement_outcome_id="set-out_alpha_1",
        pending_transition_id=pending_a.pending_transition_id,
        decision_id=prop_a.decision_id,
        round_id="rnd_001",
        policy_id="pol-def_alpha",
        status=SettlementStatus.REJECTED,
        rejection_reasons=(RejectionReason("INSUFFICIENT_FUNDS", "Failed settlement"),),
        settled_at="2026-08-02T00:00:00Z",
    )
    prop_b_1 = _make_proposal(
        decision_id="dec-prop_beta_1",
        round_id="rnd_001",
        policy_id="pol-def_beta",
        requested_actions=(RequestedAction(ActionType.ALLOCATE, "res_eth", Decimal("5.0")),),
    )
    pending_b_1 = PendingTransitionRecord(
        pending_transition_id="pnd_beta_1",
        decision_id=prop_b_1.decision_id,
        round_id="rnd_001",
        policy_id="pol-def_beta",
        policy_version_id=prop_b_1.policy_version_id,
        knowledge_cutoff="2026-08-02T00:00:00Z",
        admitted_at="2026-08-02T00:00:00Z",
        predecessor_account_hash=acc_b_0.compute_hash(),
        requested_action=prop_b_1.requested_actions[0],
        target_bar_rule=TargetBarRule("series_eth_1d", expected_open_time="2026-08-02T00:00:00Z"),
    )
    pending_ref_b_1 = PendingStateReference(
        pending_transition_hash=pending_b_1.compute_hash(),
        admission_account_hash=acc_b_0.compute_hash(),
        expected_open_time="2026-08-02T00:00:00Z",
        settlement_deadline="2026-08-04T00:00:00Z",
    )

    pol_a_1 = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=acc_a_0.compute_hash(),
        account_state_after_hash=acc_a_0.compute_hash(),
        pending_before=pending_ref_a,
        pending_after=None,  # Settled!
        settlement_outcome_hash=so_a_1.compute_hash(),
        deferred_transition_hash=None,
        proposed_decision_hash=None,
        decision_outcome_hash=None,
    )
    pol_b_1 = DeferredPolicyRoundRecord(
        policy_id="pol-def_beta",
        account_state_before_hash=acc_b_0.compute_hash(),
        account_state_after_hash=acc_b_0.compute_hash(),
        pending_before=None,
        pending_after=pending_ref_b_1,
        settlement_outcome_hash=None,
        deferred_transition_hash=None,
        proposed_decision_hash=prop_b_1.compute_hash(),
        decision_outcome_hash=None,
    )

    round_1 = DeferredRoundRecord(
        round_id="rnd_001",
        run_id=run_id,
        round_index=1,
        parent_round_hash=round_0.compute_hash(),
        knowledge_cutoff="2026-08-02T00:00:00Z",
        execution_start_time="2026-08-02T00:00:01Z",
        execution_end_time="2026-08-02T00:00:02Z",
        effective_time="2026-08-02T00:00:02Z",
        eligible_observation_hashes=(),
        policy_round_records=(pol_a_1, pol_b_1),
        state_merkle_hash=compute_deferred_state_merkle_hash(
            round_0.compute_hash(), (pol_a_1, pol_b_1)
        ),
    )

    commit_1 = RoundCommit(
        run=EpisodeRun(
            run_id=run_id,
            episode_id=ep.episode_id,
            episode_definition_hash=run.episode_definition_hash,
            lifecycle_status=LifecycleStatus.RUNNING,
            started_at=run.started_at,
            ended_at=None,
            current_round_index=2,
            total_rounds=3,
            final_state_hash=None,
        ),
        round_record=round_1,
        proposed_decisions=(prop_b_1,),
        pending_transitions=(pending_b_1,),
        settlement_outcomes=(so_a_1,),
    )
    store.commit_round(commit_1)

    # Cross-policy assertions
    assert store.get_active_pending_reference(run_id, "pol-def_alpha") is None
    assert store.get_active_pending_reference(run_id, "pol-def_beta") == pending_ref_b_1

    assert store.get_pending_transitions(run_id, "pol-def_alpha") == [pending_a]
    assert store.get_pending_transitions(run_id, "pol-def_beta") == [pending_b_1]
    assert store.get_pending_transitions(run_id) == [pending_a, pending_b_1]

    assert store.get_settlement_outcomes(run_id, "pol-def_alpha") == [so_a_1]
    assert store.get_settlement_outcomes(run_id, "pol-def_beta") == []
    assert store.get_settlement_outcomes(run_id) == [so_a_1]
