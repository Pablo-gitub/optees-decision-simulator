"""Unit tests for DeferredRunTerminalRecord and PolicyTerminalRecord (DS-02D2C1A)."""

import pytest

from simulator.domain.deferred_terminal import (
    DeferredRunTerminalRecord,
    PolicyTerminalRecord,
    compute_terminal_record_id,
    compute_terminal_state_merkle_hash,
)
from simulator.domain.errors import DuplicateIdentityError


@pytest.fixture
def clean_policies():
    return (
        PolicyTerminalRecord("pol-def_alpha", "sha256:" + "a" * 64),
        PolicyTerminalRecord("pol-def_beta", "sha256:" + "b" * 64),
    )


@pytest.fixture
def unsettled_policies():
    return (
        PolicyTerminalRecord(
            "pol-def_alpha",
            "sha256:" + "a" * 64,
            pending_transition_hash="sha256:" + "c" * 64,
            settlement_outcome_hash="sha256:" + "d" * 64,
        ),
        PolicyTerminalRecord("pol-def_beta", "sha256:" + "b" * 64),
    )


def test_clean_completion(clean_policies):
    run_id = "ep-run_clean"
    parent_hash = "sha256:" + "1" * 64
    term_id = compute_terminal_record_id(run_id, "COMPLETED", parent_hash)
    merkle = compute_terminal_state_merkle_hash(parent_hash, clean_policies)

    rec = DeferredRunTerminalRecord(
        terminal_record_id=term_id,
        run_id=run_id,
        episode_id="ep-def_001",
        terminal_status="COMPLETED",
        reason_code="CLEAN_COMPLETION",
        reason_message="Clean completion",
        simulation_frontier_time="2026-08-05T00:00:00Z",
        execution_timestamp="2026-08-05T00:00:01Z",
        parent_round_hash=parent_hash,
        policy_terminal_records=clean_policies,
        terminal_state_merkle_hash=merkle,
    )

    assert rec.terminal_record_id == term_id
    assert rec.compute_hash().startswith("sha256:")

    # from_dict / to_dict roundtrip
    data = rec.to_dict()
    loaded = DeferredRunTerminalRecord.from_dict(data)
    assert loaded == rec
    assert loaded.compute_hash() == rec.compute_hash()


def test_completed_with_unsettled_pending(unsettled_policies):
    run_id = "ep-run_unsettled"
    parent_hash = "sha256:" + "1" * 64
    term_id = compute_terminal_record_id(run_id, "COMPLETED", parent_hash)
    merkle = compute_terminal_state_merkle_hash(parent_hash, unsettled_policies)

    rec = DeferredRunTerminalRecord(
        terminal_record_id=term_id,
        run_id=run_id,
        episode_id="ep-def_001",
        terminal_status="COMPLETED",
        reason_code="UNSETTLED_EPISODE_TERMINATION",
        reason_message="Pending terminated",
        simulation_frontier_time="2026-08-05T00:00:00Z",
        execution_timestamp="2026-08-05T00:00:01Z",
        parent_round_hash=parent_hash,
        policy_terminal_records=unsettled_policies,
        terminal_state_merkle_hash=merkle,
    )
    assert rec.reason_code == "UNSETTLED_EPISODE_TERMINATION"


def test_cancelled_mid_episode(unsettled_policies):
    run_id = "ep-run_cancelled"
    parent_hash = "sha256:" + "1" * 64
    term_id = compute_terminal_record_id(run_id, "CANCELLED", parent_hash)
    merkle = compute_terminal_state_merkle_hash(parent_hash, unsettled_policies)

    rec = DeferredRunTerminalRecord(
        terminal_record_id=term_id,
        run_id=run_id,
        episode_id="ep-def_001",
        terminal_status="CANCELLED",
        reason_code="EPISODE_CANCELLED",
        reason_message="Cancelled by user",
        simulation_frontier_time="2026-08-05T00:00:00Z",
        execution_timestamp="2026-08-05T00:00:01Z",
        parent_round_hash=parent_hash,
        policy_terminal_records=unsettled_policies,
        terminal_state_merkle_hash=merkle,
    )
    assert rec.terminal_status == "CANCELLED"
    assert rec.reason_code == "EPISODE_CANCELLED"


def test_genesis_cancellation(clean_policies):
    run_id = "ep-run_genesis"
    term_id = compute_terminal_record_id(run_id, "CANCELLED", None)
    merkle = compute_terminal_state_merkle_hash(None, clean_policies)

    rec = DeferredRunTerminalRecord(
        terminal_record_id=term_id,
        run_id=run_id,
        episode_id="ep-def_001",
        terminal_status="CANCELLED",
        reason_code="EPISODE_CANCELLED",
        reason_message="Cancelled at genesis",
        simulation_frontier_time=None,
        execution_timestamp="2026-08-05T00:00:01Z",
        parent_round_hash=None,
        policy_terminal_records=clean_policies,
        terminal_state_merkle_hash=merkle,
    )
    assert rec.parent_round_hash is None
    assert rec.simulation_frontier_time is None


def test_co_presence_invariants():
    # Pending without outcome -> raises ValueError
    with pytest.raises(ValueError, match="settlement_outcome_hash must be a valid SHA-256"):
        PolicyTerminalRecord(
            "pol-def_alpha",
            "sha256:" + "a" * 64,
            pending_transition_hash="sha256:" + "c" * 64,
            settlement_outcome_hash=None,
        )

    # Outcome without pending -> raises ValueError
    with pytest.raises(ValueError, match="settlement_outcome_hash must be None"):
        PolicyTerminalRecord(
            "pol-def_alpha",
            "sha256:" + "a" * 64,
            pending_transition_hash=None,
            settlement_outcome_hash="sha256:" + "d" * 64,
        )


def test_status_reason_incompatibilities(clean_policies, unsettled_policies):
    run_id = "ep-run_test"
    parent_hash = "sha256:" + "1" * 64
    term_id = compute_terminal_record_id(run_id, "COMPLETED", parent_hash)

    # COMPLETED with pending but reason CLEAN_COMPLETION
    merkle_unsettled = compute_terminal_state_merkle_hash(parent_hash, unsettled_policies)
    with pytest.raises(ValueError, match="UNSETTLED_EPISODE_TERMINATION"):
        DeferredRunTerminalRecord(
            terminal_record_id=term_id,
            run_id=run_id,
            episode_id="ep-def_001",
            terminal_status="COMPLETED",
            reason_code="CLEAN_COMPLETION",
            reason_message="Test",
            simulation_frontier_time="2026-08-05T00:00:00Z",
            execution_timestamp="2026-08-05T00:00:01Z",
            parent_round_hash=parent_hash,
            policy_terminal_records=unsettled_policies,
            terminal_state_merkle_hash=merkle_unsettled,
        )

    # COMPLETED without pending but reason UNSETTLED_EPISODE_TERMINATION
    merkle_clean = compute_terminal_state_merkle_hash(parent_hash, clean_policies)
    with pytest.raises(ValueError, match="CLEAN_COMPLETION"):
        DeferredRunTerminalRecord(
            terminal_record_id=term_id,
            run_id=run_id,
            episode_id="ep-def_001",
            terminal_status="COMPLETED",
            reason_code="UNSETTLED_EPISODE_TERMINATION",
            reason_message="Test",
            simulation_frontier_time="2026-08-05T00:00:00Z",
            execution_timestamp="2026-08-05T00:00:01Z",
            parent_round_hash=parent_hash,
            policy_terminal_records=clean_policies,
            terminal_state_merkle_hash=merkle_clean,
        )

    # CANCELLED with reason CLEAN_COMPLETION
    term_id_canc = compute_terminal_record_id(run_id, "CANCELLED", parent_hash)
    with pytest.raises(ValueError, match="EPISODE_CANCELLED"):
        DeferredRunTerminalRecord(
            terminal_record_id=term_id_canc,
            run_id=run_id,
            episode_id="ep-def_001",
            terminal_status="CANCELLED",
            reason_code="CLEAN_COMPLETION",
            reason_message="Test",
            simulation_frontier_time="2026-08-05T00:00:00Z",
            execution_timestamp="2026-08-05T00:00:01Z",
            parent_round_hash=parent_hash,
            policy_terminal_records=clean_policies,
            terminal_state_merkle_hash=merkle_clean,
        )


def test_policy_ordering_and_duplicates():
    p1 = PolicyTerminalRecord("pol-def_beta", "sha256:" + "b" * 64)
    p2 = PolicyTerminalRecord("pol-def_alpha", "sha256:" + "a" * 64)
    parent = "sha256:" + "1" * 64
    merkle = compute_terminal_state_merkle_hash(parent, (p1, p2))
    term_id = compute_terminal_record_id("ep-run_001", "COMPLETED", parent)

    # Unsorted policies
    with pytest.raises(ValueError, match="sorted strictly by policy_id"):
        DeferredRunTerminalRecord(
            terminal_record_id=term_id,
            run_id="ep-run_001",
            episode_id="ep-def_001",
            terminal_status="COMPLETED",
            reason_code="CLEAN_COMPLETION",
            reason_message="Test",
            simulation_frontier_time="2026-08-05T00:00:00Z",
            execution_timestamp="2026-08-05T00:00:01Z",
            parent_round_hash=parent,
            policy_terminal_records=(p1, p2),
            terminal_state_merkle_hash=merkle,
        )

    # Duplicate policy
    p_dup = PolicyTerminalRecord("pol-def_alpha", "sha256:" + "b" * 64)
    with pytest.raises(DuplicateIdentityError):
        DeferredRunTerminalRecord(
            terminal_record_id=term_id,
            run_id="ep-run_001",
            episode_id="ep-def_001",
            terminal_status="COMPLETED",
            reason_code="CLEAN_COMPLETION",
            reason_message="Test",
            simulation_frontier_time="2026-08-05T00:00:00Z",
            execution_timestamp="2026-08-05T00:00:01Z",
            parent_round_hash=parent,
            policy_terminal_records=(p2, p_dup),
            terminal_state_merkle_hash=merkle,
        )


def test_frontier_parent_inconsistencies(clean_policies):
    run_id = "ep-run_001"
    parent = "sha256:" + "1" * 64
    merkle = compute_terminal_state_merkle_hash(parent, clean_policies)
    term_id = compute_terminal_record_id(run_id, "COMPLETED", parent)

    # parent is None but simulation_frontier_time is provided
    term_id_genesis = compute_terminal_record_id(run_id, "CANCELLED", None)
    merkle_genesis = compute_terminal_state_merkle_hash(None, clean_policies)
    with pytest.raises(ValueError, match="simulation_frontier_time must be None"):
        DeferredRunTerminalRecord(
            terminal_record_id=term_id_genesis,
            run_id=run_id,
            episode_id="ep-def_001",
            terminal_status="CANCELLED",
            reason_code="EPISODE_CANCELLED",
            reason_message="Test",
            simulation_frontier_time="2026-08-05T00:00:00Z",
            execution_timestamp="2026-08-05T00:00:01Z",
            parent_round_hash=None,
            policy_terminal_records=clean_policies,
            terminal_state_merkle_hash=merkle_genesis,
        )

    # parent is not None but simulation_frontier_time is None
    with pytest.raises(ValueError, match="simulation_frontier_time must be provided"):
        DeferredRunTerminalRecord(
            terminal_record_id=term_id,
            run_id=run_id,
            episode_id="ep-def_001",
            terminal_status="COMPLETED",
            reason_code="CLEAN_COMPLETION",
            reason_message="Test",
            simulation_frontier_time=None,
            execution_timestamp="2026-08-05T00:00:01Z",
            parent_round_hash=parent,
            policy_terminal_records=clean_policies,
            terminal_state_merkle_hash=merkle,
        )


def test_merkle_tamper_detection(clean_policies):
    run_id = "ep-run_001"
    parent = "sha256:" + "1" * 64
    term_id = compute_terminal_record_id(run_id, "COMPLETED", parent)
    tampered_merkle = "sha256:" + "9" * 64

    with pytest.raises(ValueError, match="terminal_state_merkle_hash mismatch"):
        DeferredRunTerminalRecord(
            terminal_record_id=term_id,
            run_id=run_id,
            episode_id="ep-def_001",
            terminal_status="COMPLETED",
            reason_code="CLEAN_COMPLETION",
            reason_message="Test",
            simulation_frontier_time="2026-08-05T00:00:00Z",
            execution_timestamp="2026-08-05T00:00:01Z",
            parent_round_hash=parent,
            policy_terminal_records=clean_policies,
            terminal_state_merkle_hash=tampered_merkle,
        )
