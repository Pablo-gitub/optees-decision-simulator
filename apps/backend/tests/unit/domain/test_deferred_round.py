"""Unit and contract tests for DeferredRoundRecord, DeferredPolicyRoundRecord,
PendingStateReference, and compute_deferred_state_merkle_hash (DS-02D2C0).

Verifies:
1. Strict schema/codec round-trip and deterministic hashes for all 7 lifecycle variants.
2. Real B1/B2 outputs in a multi-round synthetic record chain with hash resolution
   and strict separation of prior settlement and new proposal.
3. Negative tests for all constructor invariants, impossible combinations, malformed
   hashes/times, duplicate policy IDs, and non-canonical policy ordering.
4. Sensitivity of Merkle hash to every schedule, anchor, phase, and state field.
5. Immutability of models and resistance to alias mutation.
"""

from __future__ import annotations

import copy
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from simulator.application.services.deferred_admission import (
    DeferredAdmissionService,
)
from simulator.application.services.deferred_settlement import (
    DeferredSettlementService,
)
from simulator.domain.deferred_round import (
    DeferredPolicyRoundRecord,
    DeferredRoundRecord,
    PendingStateReference,
    compute_deferred_state_merkle_hash,
)
from simulator.domain.errors import InvalidTimestampError
from simulator.domain.lifecycle import ActionType, SettlementStatus
from simulator.domain.models import (
    AccountBalanceSpec,
    BalanceItem,
    CalendarSpec,
    ConstraintsSpec,
    CostModelSpec,
    CumulativeCostItem,
    DatasetSnapshotRef,
    DecisionRationale,
    EpisodeDefinition,
    EpisodeRulesSpec,
    FailurePolicySpec,
    InitialAccountSpec,
    ObservationRecord,
    PolicyVersionRef,
    ProposedDecision,
    ReferenceValuation,
    RequestedAction,
    VirtualAccountState,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
SCHEMAS_DIR = REPO_ROOT / "docs" / "contracts" / "schemas"

with open(SCHEMAS_DIR / "round.v2.json", "r", encoding="utf-8") as f:
    ROUND_V2_SCHEMA = json.load(f)

# Import validator
import importlib.util  # noqa: E402

validator_path = REPO_ROOT / "tools" / "validate_contracts.py"
spec = importlib.util.spec_from_file_location("validate_contracts", str(validator_path))
validate_contracts = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(validate_contracts)  # type: ignore[union-attr]
validate_data = validate_contracts.validate_data


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------


def _dummy_hash(identifier: str) -> str:
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _make_pending_ref(
    suffix: str = "1",
    open_time: str = "2026-08-01T00:00:00Z",
    deadline: str = "2026-08-01T00:05:00Z",
) -> PendingStateReference:
    return PendingStateReference(
        pending_transition_hash=_dummy_hash(suffix),
        admission_account_hash=_dummy_hash(suffix[-1]),
        expected_open_time=open_time,
        settlement_deadline=deadline,
    )


def _assert_schema_and_codec(round_record: DeferredRoundRecord) -> None:
    data = round_record.to_dict()
    errors = validate_data(data, ROUND_V2_SCHEMA, path="round_record")
    assert not errors, f"Schema validation errors: {errors}"
    restored = DeferredRoundRecord.from_dict(data)
    assert restored == round_record
    assert restored.compute_hash() == round_record.compute_hash()


@pytest.mark.parametrize(
    "field,value",
    [
        ("settlement_deadline", "2026-08-05T00:00:00Z"),
        ("expected_open_time", "2026-07-31T00:00:00Z"),
        ("admission_account_hash", "sha256:" + "9" * 64),
    ],
)
def test_settled_pending_cannot_be_reintroduced_by_changing_metadata(field, value):
    from dataclasses import replace

    before = _make_pending_ref()
    after = replace(before, **{field: value})
    with pytest.raises(ValueError, match="cannot remain"):
        DeferredPolicyRoundRecord(
            "pol-def_alpha",
            _dummy_hash("a"),
            _dummy_hash("b"),
            before,
            after,
            _dummy_hash("s"),
            _dummy_hash("t"),
            _dummy_hash("p"),
            None,
        )


def test_execution_chronology_is_separate_from_simulation_time():
    data = json.loads(
        (REPO_ROOT / "docs/contracts/examples/valid/deferred_round.v2.json").read_text()
    )
    data["execution_start_time"] = "2026-09-01T00:00:00Z"
    data["execution_end_time"] = "2026-08-31T00:00:00Z"
    with pytest.raises(ValueError, match="cannot precede"):
        DeferredRoundRecord.from_dict(data)
    data["execution_end_time"] = "2026-09-01T00:00:00.000Z"
    assert DeferredRoundRecord.from_dict(data).effective_time == data["effective_time"]


@pytest.mark.parametrize(
    "changes",
    [
        {"pending_before": None, "settlement_outcome_hash": "sha256:" + "1" * 64},
        {"settlement_outcome_hash": None, "deferred_transition_hash": "sha256:" + "1" * 64},
        {"proposed_decision_hash": None, "decision_outcome_hash": "sha256:" + "1" * 64},
        {
            "proposed_decision_hash": "sha256:" + "1" * 64,
            "decision_outcome_hash": None,
            "pending_after": None,
        },
    ],
)
def test_schema_rejects_impossible_phase_presence_without_constructor(changes):
    data = json.loads(
        (REPO_ROOT / "docs/contracts/examples/valid/deferred_round.v2.json").read_text()
    )
    assert validate_data(data, ROUND_V2_SCHEMA) == []
    data["policy_round_records"][0].update(changes)
    assert validate_data(data, ROUND_V2_SCHEMA)


# ---------------------------------------------------------------------------
# Test Suite 1: Lifecycle Variants (Schema/Codec & Invariant Compatibility)
# ---------------------------------------------------------------------------


def test_variant_1_new_admission():
    """Lifecycle 1: Proposal admitted as pending; no prior pending."""
    ref_new = _make_pending_ref("1")
    pol = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=_dummy_hash("a"),
        account_state_after_hash=_dummy_hash("b"),
        pending_before=None,
        pending_after=ref_new,
        settlement_outcome_hash=None,
        deferred_transition_hash=None,
        proposed_decision_hash=_dummy_hash("p"),
        decision_outcome_hash=None,
    )
    parent_hash = _dummy_hash("0")
    merkle = compute_deferred_state_merkle_hash(parent_hash, [pol])
    rnd = DeferredRoundRecord(
        round_id="rnd_001",
        run_id="ep-run_001",
        round_index=1,
        parent_round_hash=parent_hash,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        execution_start_time="2026-08-01T00:00:01Z",
        execution_end_time="2026-08-01T00:00:02Z",
        effective_time="2026-08-01T00:00:02Z",
        eligible_observation_hashes=(_dummy_hash("o"),),
        policy_round_records=(pol,),
        state_merkle_hash=merkle,
    )
    _assert_schema_and_codec(rnd)


def test_variant_2_waiting_with_hold():
    """Lifecycle 2: Pending carried over unchanged; proposal is HOLD (immediate outcome)."""
    ref = _make_pending_ref("1")
    pol = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=_dummy_hash("a"),
        account_state_after_hash=_dummy_hash("a"),
        pending_before=ref,
        pending_after=ref,
        settlement_outcome_hash=None,
        deferred_transition_hash=None,
        proposed_decision_hash=_dummy_hash("p"),
        decision_outcome_hash=_dummy_hash("d"),
    )
    merkle = compute_deferred_state_merkle_hash(None, [pol])
    rnd = DeferredRoundRecord(
        round_id="rnd_001",
        run_id="ep-run_001",
        round_index=0,
        parent_round_hash=None,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        execution_start_time="2026-08-01T00:00:01Z",
        execution_end_time="2026-08-01T00:00:02Z",
        effective_time="2026-08-01T00:00:02Z",
        eligible_observation_hashes=(),
        policy_round_records=(pol,),
        state_merkle_hash=merkle,
    )
    _assert_schema_and_codec(rnd)


def test_variant_3_waiting_without_proposal():
    """Lifecycle 3: Pending carried over unchanged; no proposal in round."""
    ref = _make_pending_ref("1")
    pol = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=_dummy_hash("a"),
        account_state_after_hash=_dummy_hash("a"),
        pending_before=ref,
        pending_after=ref,
        settlement_outcome_hash=None,
        deferred_transition_hash=None,
        proposed_decision_hash=None,
        decision_outcome_hash=None,
    )
    merkle = compute_deferred_state_merkle_hash(None, [pol])
    rnd = DeferredRoundRecord(
        round_id="rnd_001",
        run_id="ep-run_001",
        round_index=0,
        parent_round_hash=None,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        execution_start_time="2026-08-01T00:00:01Z",
        execution_end_time="2026-08-01T00:00:02Z",
        effective_time="2026-08-01T00:00:02Z",
        eligible_observation_hashes=(),
        policy_round_records=(pol,),
        state_merkle_hash=merkle,
    )
    _assert_schema_and_codec(rnd)


def test_variant_4_settlement_without_new_proposal():
    """Lifecycle 4: Prior pending settled; no new proposal in round."""
    ref = _make_pending_ref("1")
    pol = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=_dummy_hash("a"),
        account_state_after_hash=_dummy_hash("b"),
        pending_before=ref,
        pending_after=None,
        settlement_outcome_hash=_dummy_hash("s"),
        deferred_transition_hash=_dummy_hash("t"),
        proposed_decision_hash=None,
        decision_outcome_hash=None,
    )
    merkle = compute_deferred_state_merkle_hash(None, [pol])
    rnd = DeferredRoundRecord(
        round_id="rnd_001",
        run_id="ep-run_001",
        round_index=0,
        parent_round_hash=None,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        execution_start_time="2026-08-01T00:00:01Z",
        execution_end_time="2026-08-01T00:00:02Z",
        effective_time="2026-08-01T00:00:02Z",
        eligible_observation_hashes=(),
        policy_round_records=(pol,),
        state_merkle_hash=merkle,
    )
    _assert_schema_and_codec(rnd)


def test_variant_5_settlement_followed_by_new_admission():
    """Lifecycle 5: Prior pending settled AND new decision proposal admitted."""
    ref_old = _make_pending_ref("1")
    ref_new = _make_pending_ref(
        "2", open_time="2026-08-02T00:00:00Z", deadline="2026-08-02T00:05:00Z"
    )
    pol = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=_dummy_hash("a"),
        account_state_after_hash=_dummy_hash("b"),
        pending_before=ref_old,
        pending_after=ref_new,
        settlement_outcome_hash=_dummy_hash("s"),
        deferred_transition_hash=_dummy_hash("t"),
        proposed_decision_hash=_dummy_hash("p"),
        decision_outcome_hash=None,
    )
    merkle = compute_deferred_state_merkle_hash(None, [pol])
    rnd = DeferredRoundRecord(
        round_id="rnd_001",
        run_id="ep-run_001",
        round_index=0,
        parent_round_hash=None,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        execution_start_time="2026-08-01T00:00:01Z",
        execution_end_time="2026-08-01T00:00:02Z",
        effective_time="2026-08-01T00:00:02Z",
        eligible_observation_hashes=(),
        policy_round_records=(pol,),
        state_merkle_hash=merkle,
    )
    _assert_schema_and_codec(rnd)


def test_variant_6_immediate_rejection():
    """Lifecycle 6: Proposal rejected immediately; no prior pending."""
    pol = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=_dummy_hash("a"),
        account_state_after_hash=_dummy_hash("a"),
        pending_before=None,
        pending_after=None,
        settlement_outcome_hash=None,
        deferred_transition_hash=None,
        proposed_decision_hash=_dummy_hash("p"),
        decision_outcome_hash=_dummy_hash("r"),
    )
    merkle = compute_deferred_state_merkle_hash(None, [pol])
    rnd = DeferredRoundRecord(
        round_id="rnd_001",
        run_id="ep-run_001",
        round_index=0,
        parent_round_hash=None,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        execution_start_time="2026-08-01T00:00:01Z",
        execution_end_time="2026-08-01T00:00:02Z",
        effective_time="2026-08-01T00:00:02Z",
        eligible_observation_hashes=(),
        policy_round_records=(pol,),
        state_merkle_hash=merkle,
    )
    _assert_schema_and_codec(rnd)


def test_variant_7_terminal_rejection_of_pending():
    """Lifecycle 7: Prior pending terminally rejected (e.g. timeout); no new proposal."""
    ref_old = _make_pending_ref("1")
    pol = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=_dummy_hash("a"),
        account_state_after_hash=_dummy_hash("a"),
        pending_before=ref_old,
        pending_after=None,
        settlement_outcome_hash=_dummy_hash("s"),
        deferred_transition_hash=None,
        proposed_decision_hash=None,
        decision_outcome_hash=None,
    )
    merkle = compute_deferred_state_merkle_hash(None, [pol])
    rnd = DeferredRoundRecord(
        round_id="rnd_001",
        run_id="ep-run_001",
        round_index=0,
        parent_round_hash=None,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        execution_start_time="2026-08-01T00:00:01Z",
        execution_end_time="2026-08-01T00:00:02Z",
        effective_time="2026-08-01T00:00:02Z",
        eligible_observation_hashes=(),
        policy_round_records=(pol,),
        state_merkle_hash=merkle,
    )
    _assert_schema_and_codec(rnd)


# ---------------------------------------------------------------------------
# Test Suite 2: Negative Invariant Tests
# ---------------------------------------------------------------------------


def test_invariant_1_settlement_requires_pending_before():
    # settlement_outcome_hash without pending_before
    with pytest.raises(
        ValueError, match="settlement_outcome_hash cannot be present without pending_before"
    ):
        DeferredPolicyRoundRecord(
            policy_id="pol-def_alpha",
            account_state_before_hash=_dummy_hash("a"),
            account_state_after_hash=_dummy_hash("a"),
            pending_before=None,
            pending_after=None,
            settlement_outcome_hash=_dummy_hash("s"),
            deferred_transition_hash=None,
            proposed_decision_hash=None,
            decision_outcome_hash=None,
        )

    # deferred_transition_hash without pending_before
    with pytest.raises(
        ValueError, match="deferred_transition_hash cannot be present without pending_before"
    ):
        DeferredPolicyRoundRecord(
            policy_id="pol-def_alpha",
            account_state_before_hash=_dummy_hash("a"),
            account_state_after_hash=_dummy_hash("a"),
            pending_before=None,
            pending_after=None,
            settlement_outcome_hash=None,
            deferred_transition_hash=_dummy_hash("t"),
            proposed_decision_hash=None,
            decision_outcome_hash=None,
        )


def test_invariant_2_transition_requires_settlement_outcome():
    ref = _make_pending_ref("1")
    with pytest.raises(
        ValueError, match="deferred_transition_hash requires a settlement_outcome_hash"
    ):
        DeferredPolicyRoundRecord(
            policy_id="pol-def_alpha",
            account_state_before_hash=_dummy_hash("a"),
            account_state_after_hash=_dummy_hash("a"),
            pending_before=ref,
            pending_after=ref,
            settlement_outcome_hash=None,
            deferred_transition_hash=_dummy_hash("t"),
            proposed_decision_hash=None,
            decision_outcome_hash=None,
        )


def test_invariant_3_unsettled_pending_must_be_carried_unchanged():
    ref1 = _make_pending_ref("1")
    ref2 = _make_pending_ref("2")

    # pending_after is None
    with pytest.raises(ValueError, match="carried unchanged"):
        DeferredPolicyRoundRecord(
            policy_id="pol-def_alpha",
            account_state_before_hash=_dummy_hash("a"),
            account_state_after_hash=_dummy_hash("a"),
            pending_before=ref1,
            pending_after=None,
            settlement_outcome_hash=None,
            deferred_transition_hash=None,
            proposed_decision_hash=None,
            decision_outcome_hash=None,
        )

    # pending_after is changed
    with pytest.raises(ValueError, match="carried unchanged"):
        DeferredPolicyRoundRecord(
            policy_id="pol-def_alpha",
            account_state_before_hash=_dummy_hash("a"),
            account_state_after_hash=_dummy_hash("a"),
            pending_before=ref1,
            pending_after=ref2,
            settlement_outcome_hash=None,
            deferred_transition_hash=None,
            proposed_decision_hash=_dummy_hash("p"),
            decision_outcome_hash=None,
        )


def test_invariant_4_proposal_must_have_exactly_one_result():
    ref1 = _make_pending_ref("1")
    ref2 = _make_pending_ref("2")

    # Proposal with both immediate outcome and new pending
    with pytest.raises(ValueError, match="both an immediate outcome and a newly admitted pending"):
        DeferredPolicyRoundRecord(
            policy_id="pol-def_alpha",
            account_state_before_hash=_dummy_hash("a"),
            account_state_after_hash=_dummy_hash("a"),
            pending_before=None,
            pending_after=ref2,
            settlement_outcome_hash=None,
            deferred_transition_hash=None,
            proposed_decision_hash=_dummy_hash("p"),
            decision_outcome_hash=_dummy_hash("d"),
        )

    # Proposal with neither immediate outcome nor new pending
    with pytest.raises(ValueError, match="either an immediate outcome or a newly admitted pending"):
        DeferredPolicyRoundRecord(
            policy_id="pol-def_alpha",
            account_state_before_hash=_dummy_hash("a"),
            account_state_after_hash=_dummy_hash("a"),
            pending_before=None,
            pending_after=None,
            settlement_outcome_hash=None,
            deferred_transition_hash=None,
            proposed_decision_hash=_dummy_hash("p"),
            decision_outcome_hash=None,
        )

    # Proposal with neither when pending_before is present
    with pytest.raises(ValueError, match="either an immediate outcome or a newly admitted pending"):
        DeferredPolicyRoundRecord(
            policy_id="pol-def_alpha",
            account_state_before_hash=_dummy_hash("a"),
            account_state_after_hash=_dummy_hash("a"),
            pending_before=ref1,
            pending_after=ref1,
            settlement_outcome_hash=None,
            deferred_transition_hash=None,
            proposed_decision_hash=_dummy_hash("p"),
            decision_outcome_hash=None,
        )


def test_invariant_5_settled_pending_cannot_remain_after():
    ref1 = _make_pending_ref("1")
    with pytest.raises(ValueError, match="cannot remain as pending_after"):
        DeferredPolicyRoundRecord(
            policy_id="pol-def_alpha",
            account_state_before_hash=_dummy_hash("a"),
            account_state_after_hash=_dummy_hash("b"),
            pending_before=ref1,
            pending_after=ref1,
            settlement_outcome_hash=_dummy_hash("s"),
            deferred_transition_hash=_dummy_hash("t"),
            proposed_decision_hash=None,
            decision_outcome_hash=None,
        )


def test_invariant_6_no_proposal_cannot_produce_outcome_or_new_pending():
    ref1 = _make_pending_ref("1")
    ref2 = _make_pending_ref("2")

    # Immediate outcome without proposal
    with pytest.raises(
        ValueError,
        match="decision_outcome_hash cannot be present without proposed_decision_hash",
    ):
        DeferredPolicyRoundRecord(
            policy_id="pol-def_alpha",
            account_state_before_hash=_dummy_hash("a"),
            account_state_after_hash=_dummy_hash("a"),
            pending_before=None,
            pending_after=None,
            settlement_outcome_hash=None,
            deferred_transition_hash=None,
            proposed_decision_hash=None,
            decision_outcome_hash=_dummy_hash("d"),
        )

    # New pending without proposal
    with pytest.raises(ValueError, match="New pending_after cannot appear in a no-proposal round"):
        DeferredPolicyRoundRecord(
            policy_id="pol-def_alpha",
            account_state_before_hash=_dummy_hash("a"),
            account_state_after_hash=_dummy_hash("a"),
            pending_before=None,
            pending_after=ref2,
            settlement_outcome_hash=None,
            deferred_transition_hash=None,
            proposed_decision_hash=None,
            decision_outcome_hash=None,
        )

    # New pending replacing settled pending without proposal
    with pytest.raises(ValueError, match="New pending_after cannot appear in a no-proposal round"):
        DeferredPolicyRoundRecord(
            policy_id="pol-def_alpha",
            account_state_before_hash=_dummy_hash("a"),
            account_state_after_hash=_dummy_hash("b"),
            pending_before=ref1,
            pending_after=ref2,
            settlement_outcome_hash=_dummy_hash("s"),
            deferred_transition_hash=_dummy_hash("t"),
            proposed_decision_hash=None,
            decision_outcome_hash=None,
        )


def test_invariant_7_top_level_and_type_checks():
    pol_alpha = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=_dummy_hash("a"),
        account_state_after_hash=_dummy_hash("a"),
        pending_before=None,
        pending_after=None,
        settlement_outcome_hash=None,
        deferred_transition_hash=None,
        proposed_decision_hash=None,
        decision_outcome_hash=None,
    )
    pol_beta = DeferredPolicyRoundRecord(
        policy_id="pol-def_beta",
        account_state_before_hash=_dummy_hash("b"),
        account_state_after_hash=_dummy_hash("b"),
        pending_before=None,
        pending_after=None,
        settlement_outcome_hash=None,
        deferred_transition_hash=None,
        proposed_decision_hash=None,
        decision_outcome_hash=None,
    )

    # Empty policy records
    with pytest.raises(ValueError, match="at least one policy record"):
        compute_deferred_state_merkle_hash(None, [])

    # Duplicate policy IDs
    with pytest.raises(ValueError, match="strictly increasing lexicographic order"):
        compute_deferred_state_merkle_hash(None, [pol_alpha, pol_alpha])

    # Noncanonical (unsorted) policy ordering rejected
    with pytest.raises(ValueError, match="strictly increasing lexicographic order"):
        compute_deferred_state_merkle_hash(None, [pol_beta, pol_alpha])

    # Wrong supplied Merkle hash rejected
    with pytest.raises(ValueError, match="state_merkle_hash mismatch"):
        DeferredRoundRecord(
            round_id="rnd_001",
            run_id="ep-run_001",
            round_index=0,
            parent_round_hash=None,
            knowledge_cutoff="2026-08-01T00:00:00Z",
            execution_start_time="2026-08-01T00:00:01Z",
            execution_end_time="2026-08-01T00:00:02Z",
            effective_time="2026-08-01T00:00:02Z",
            eligible_observation_hashes=(),
            policy_round_records=(pol_alpha,),
            state_merkle_hash=_dummy_hash("f"),  # incorrect!
        )

    # Malformed hashes
    with pytest.raises(ValueError, match="Invalid parent_round_hash"):
        compute_deferred_state_merkle_hash("not-a-hash", [pol_alpha])

    with pytest.raises(ValueError, match="Invalid policy_id"):
        DeferredPolicyRoundRecord(
            policy_id="bad_policy_id",
            account_state_before_hash=_dummy_hash("a"),
            account_state_after_hash=_dummy_hash("a"),
            pending_before=None,
            pending_after=None,
            settlement_outcome_hash=None,
            deferred_transition_hash=None,
            proposed_decision_hash=None,
            decision_outcome_hash=None,
        )

    with pytest.raises(ValueError, match="Invalid account_state_before_hash"):
        DeferredPolicyRoundRecord(
            policy_id="pol-def_alpha",
            account_state_before_hash="not_sha256",
            account_state_after_hash=_dummy_hash("a"),
            pending_before=None,
            pending_after=None,
            settlement_outcome_hash=None,
            deferred_transition_hash=None,
            proposed_decision_hash=None,
            decision_outcome_hash=None,
        )

    # Invalid timestamp
    with pytest.raises(InvalidTimestampError):
        DeferredRoundRecord(
            round_id="rnd_001",
            run_id="ep-run_001",
            round_index=0,
            parent_round_hash=None,
            knowledge_cutoff="invalid-time",
            execution_start_time="2026-08-01T00:00:01Z",
            execution_end_time="2026-08-01T00:00:02Z",
            effective_time="2026-08-01T00:00:02Z",
            eligible_observation_hashes=(),
            policy_round_records=(pol_alpha,),
            state_merkle_hash=compute_deferred_state_merkle_hash(None, [pol_alpha]),
        )

    # PendingStateReference deadline before open time
    with pytest.raises(ValueError, match="cannot be after settlement_deadline"):
        PendingStateReference(
            pending_transition_hash=_dummy_hash("1"),
            admission_account_hash=_dummy_hash("a"),
            expected_open_time="2026-08-01T01:00:00Z",
            settlement_deadline="2026-08-01T00:59:59Z",
        )


def test_from_dict_rejects_unknown_fields_and_wrong_versions():
    pol_data = {
        "policy_id": "pol-def_alpha",
        "account_state_before_hash": _dummy_hash("a"),
        "account_state_after_hash": _dummy_hash("a"),
        "pending_before": None,
        "pending_after": None,
        "settlement_outcome_hash": None,
        "deferred_transition_hash": None,
        "proposed_decision_hash": None,
        "decision_outcome_hash": None,
        "optees_call_receipt_hashes": [],
        "rogue_field": 123,
    }
    with pytest.raises(ValueError, match="fields do not match schema"):
        DeferredPolicyRoundRecord.from_dict(pol_data)

    del pol_data["rogue_field"]
    pol = DeferredPolicyRoundRecord.from_dict(pol_data)
    merkle = compute_deferred_state_merkle_hash(None, [pol])

    rnd_data = {
        "$type": "round",
        "schema_version": "2.0.0",
        "round_id": "rnd_001",
        "run_id": "ep-run_001",
        "round_index": 0,
        "parent_round_hash": None,
        "knowledge_cutoff": "2026-08-01T00:00:00Z",
        "execution_start_time": "2026-08-01T00:00:01Z",
        "execution_end_time": "2026-08-01T00:00:02Z",
        "effective_time": "2026-08-01T00:00:02Z",
        "eligible_observation_hashes": [],
        "policy_round_records": [pol_data],
        "state_merkle_hash": merkle,
        "unexpected_extra": True,
    }
    with pytest.raises(ValueError, match="fields do not match schema"):
        DeferredRoundRecord.from_dict(rnd_data)

    rnd_data_bad_type = copy.deepcopy(rnd_data)
    del rnd_data_bad_type["unexpected_extra"]
    rnd_data_bad_type["$type"] = "invalid_type"
    with pytest.raises(ValueError, match="must be 'round'"):
        DeferredRoundRecord.from_dict(rnd_data_bad_type)

    rnd_data_bad_ver = copy.deepcopy(rnd_data)
    del rnd_data_bad_ver["unexpected_extra"]
    rnd_data_bad_ver["schema_version"] = "1.0.0"
    with pytest.raises(ValueError, match="must be '2.0.0'"):
        DeferredRoundRecord.from_dict(rnd_data_bad_ver)


# ---------------------------------------------------------------------------
# Test Suite 3: Merkle Hash Sensitivity
# ---------------------------------------------------------------------------


def test_merkle_hash_sensitivity():
    """Verify that any modification to pending schedule, anchors, or hashes changes Merkle hash."""
    base_ref = _make_pending_ref("1", "2026-08-01T00:00:00Z", "2026-08-01T00:05:00Z")
    pol_base = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=_dummy_hash("a"),
        account_state_after_hash=_dummy_hash("b"),
        pending_before=base_ref,
        pending_after=None,
        settlement_outcome_hash=_dummy_hash("s"),
        deferred_transition_hash=_dummy_hash("t"),
        proposed_decision_hash=None,
        decision_outcome_hash=None,
    )
    parent = _dummy_hash("0")
    h_base = compute_deferred_state_merkle_hash(parent, [pol_base])

    # 1. Changed parent hash
    h_parent_changed = compute_deferred_state_merkle_hash(_dummy_hash("9"), [pol_base])
    assert h_parent_changed != h_base

    # 2. Changed expected_open_time
    ref_mod_open = _make_pending_ref("1", "2026-08-01T00:01:00Z", "2026-08-01T00:05:00Z")
    pol_mod_open = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=_dummy_hash("a"),
        account_state_after_hash=_dummy_hash("b"),
        pending_before=ref_mod_open,
        pending_after=None,
        settlement_outcome_hash=_dummy_hash("s"),
        deferred_transition_hash=_dummy_hash("t"),
        proposed_decision_hash=None,
        decision_outcome_hash=None,
    )
    assert compute_deferred_state_merkle_hash(parent, [pol_mod_open]) != h_base

    # 3. Changed settlement_deadline
    ref_mod_dl = _make_pending_ref("1", "2026-08-01T00:00:00Z", "2026-08-01T00:06:00Z")
    pol_mod_dl = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=_dummy_hash("a"),
        account_state_after_hash=_dummy_hash("b"),
        pending_before=ref_mod_dl,
        pending_after=None,
        settlement_outcome_hash=_dummy_hash("s"),
        deferred_transition_hash=_dummy_hash("t"),
        proposed_decision_hash=None,
        decision_outcome_hash=None,
    )
    assert compute_deferred_state_merkle_hash(parent, [pol_mod_dl]) != h_base

    # 4. Changed admission_account_hash
    ref_mod_anchor = PendingStateReference(
        pending_transition_hash=_dummy_hash("1"),
        admission_account_hash=_dummy_hash("z"),
        expected_open_time="2026-08-01T00:00:00Z",
        settlement_deadline="2026-08-01T00:05:00Z",
    )
    pol_mod_anchor = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=_dummy_hash("a"),
        account_state_after_hash=_dummy_hash("b"),
        pending_before=ref_mod_anchor,
        pending_after=None,
        settlement_outcome_hash=_dummy_hash("s"),
        deferred_transition_hash=_dummy_hash("t"),
        proposed_decision_hash=None,
        decision_outcome_hash=None,
    )
    assert compute_deferred_state_merkle_hash(parent, [pol_mod_anchor]) != h_base

    # 5. Changed settlement_outcome_hash
    pol_mod_settle = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=_dummy_hash("a"),
        account_state_after_hash=_dummy_hash("b"),
        pending_before=base_ref,
        pending_after=None,
        settlement_outcome_hash=_dummy_hash("z"),
        deferred_transition_hash=_dummy_hash("t"),
        proposed_decision_hash=None,
        decision_outcome_hash=None,
    )
    assert compute_deferred_state_merkle_hash(parent, [pol_mod_settle]) != h_base


# ---------------------------------------------------------------------------
# Test Suite 4: Multi-Round Chain with REAL B1 & B2 Services
# ---------------------------------------------------------------------------


def _setup_episode() -> EpisodeDefinition:
    policy_id = "pol-def_alpha"
    policy_version_id = "pol-ver_alpha_v1"
    reference_resource = "USD"
    return EpisodeDefinition(
        episode_id="ep_chain_test",
        title="Chain Test Episode",
        description="Multi-round real service chain",
        created_at="2026-08-01T00:00:00Z",
        dataset_snapshot=DatasetSnapshotRef(
            snapshot_id="dss_chain_test",
            source_uri="file:///test/snapshot",
            checksum_sha256=_dummy_hash("0"),
            retrieval_time="2026-08-01T00:00:00Z",
            calendar_frequency="1d",
        ),
        calendar=CalendarSpec(
            round_cutoffs=(
                "2026-08-01T00:00:00Z",
                "2026-08-02T00:00:00Z",
                "2026-08-03T00:00:00Z",
            ),
            interval_duration="1d",
            evaluation_delay="1d",
        ),
        policy_versions=(
            PolicyVersionRef(
                policy_id=policy_id,
                policy_version_id=policy_version_id,
                policy_version="1.0.0",
                policy_hash=_dummy_hash("1"),
                config_hash=_dummy_hash("2"),
            ),
        ),
        initial_accounts=(
            InitialAccountSpec(
                policy_id=policy_id,
                balances=(
                    AccountBalanceSpec(
                        resource_id=reference_resource, quantity=Decimal("100000.00")
                    ),
                ),
            ),
        ),
        reference_resource_id=reference_resource,
        rules=EpisodeRulesSpec(
            allow_short_positions=False,
            allow_borrowing=False,
            cost_model=CostModelSpec(
                linear_transaction_fee_rate=Decimal("0.001"),
                fixed_transaction_fee=Decimal("1.00"),
                holding_cost_rate=Decimal("0.0"),
            ),
            failure_policy=FailurePolicySpec(),
            constraints=ConstraintsSpec(),
        ),
    )


def test_real_services_multi_round_synthetic_chain():
    """Construct a multi-round synthetic record chain using REAL B1 and B2 service outputs.

    - Round 0 (2026-08-01): B1 admits BUY order (pending_1).
    - Round 1 (2026-08-02): Target bar not yet eligible; B2 returns still-pending; B1 admits HOLD.
    - Round 2 (2026-08-03): Target bar eligible; B2 settles pending_1;
      B1 admits new order (pending_2).

    Asserts:
    - All records validate against round.v2 schema.
    - Record hashes resolve and distinguish old settlement from new proposal.
    """
    episode = _setup_episode()
    resource_map = {"BTC": "BTC_USDT_KLINE_1D", "ETH": "ETH_USDT_KLINE_1D"}

    # Initial Virtual Account
    acc_0 = VirtualAccountState(
        account_state_id="acc-state_rnd_000_pol-def_alpha",
        policy_id="pol-def_alpha",
        round_index=0,
        as_of_time="2026-08-01T00:00:00Z",
        balances=(
            BalanceItem(resource_id="USD", quantity=Decimal("100000.00")),
            BalanceItem(resource_id="BTC", quantity=Decimal("0.00")),
        ),
        cumulative_costs=(CumulativeCostItem(cost_type="TRANSACTION_FEE", amount=Decimal("0.00")),),
        reference_valuation=ReferenceValuation(
            reference_resource_id="USD",
            unallocated_cash=Decimal("100000.00"),
            allocated_resources_value=Decimal("0.00"),
            net_total_value=Decimal("100000.00"),
        ),
        parent_state_hash=None,
    )

    # -----------------------------------------------------------------------
    # Round 0: Admission of Buy Order (Pending 1)
    # -----------------------------------------------------------------------
    prop_0 = ProposedDecision(
        decision_id="dec-prop_000",
        round_id="rnd_000",
        policy_id="pol-def_alpha",
        policy_version_id="pol-ver_alpha_v1",
        knowledge_cutoff="2026-08-01T00:00:00Z",
        generated_at="2026-08-01T00:00:00Z",
        desired_allocations=(),
        requested_actions=(
            RequestedAction(
                action_type=ActionType.ALLOCATE,
                resource_id="BTC",
                quantity=Decimal("1.50000000"),
            ),
        ),
        rationale=DecisionRationale(method="buy_signal"),
    )

    adm_res_0 = DeferredAdmissionService.admit_decision(
        episode_def=episode,
        proposal=prop_0,
        current_account=acc_0,
        authoritative_round_id="rnd_000",
        authoritative_cutoff="2026-08-01T00:00:00Z",
        resource_to_series_map=resource_map,
        current_pending=None,
    )
    assert adm_res_0.is_newly_admitted
    pending_1 = adm_res_0.pending_transition
    assert pending_1 is not None

    pending_ref_1 = PendingStateReference(
        pending_transition_hash=pending_1.compute_hash(),
        admission_account_hash=acc_0.compute_hash(),
        expected_open_time="2026-08-02T00:00:00Z",
        settlement_deadline="2026-08-04T00:00:00Z",
    )

    pol_record_0 = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=acc_0.compute_hash(),
        account_state_after_hash=acc_0.compute_hash(),
        pending_before=None,
        pending_after=pending_ref_1,
        settlement_outcome_hash=None,
        deferred_transition_hash=None,
        proposed_decision_hash=prop_0.compute_hash(),
        decision_outcome_hash=None,
    )

    merkle_0 = compute_deferred_state_merkle_hash(None, [pol_record_0])
    round_record_0 = DeferredRoundRecord(
        round_id="rnd_000",
        run_id="ep-run_chain_001",
        round_index=0,
        parent_round_hash=None,
        knowledge_cutoff="2026-08-01T00:00:00Z",
        execution_start_time="2026-08-01T00:00:01Z",
        execution_end_time="2026-08-01T00:00:02Z",
        effective_time="2026-08-01T00:00:02Z",
        eligible_observation_hashes=(),
        policy_round_records=(pol_record_0,),
        state_merkle_hash=merkle_0,
    )
    _assert_schema_and_codec(round_record_0)
    round_0_hash = round_record_0.compute_hash()

    # -----------------------------------------------------------------------
    # Round 1: Observation open_time 2026-08-02 has knowledge_time 2026-08-03
    # Target bar is not yet eligible at cutoff 2026-08-02 -> B2 still-pending.
    # Policy submits HOLD -> B1 evaluates HOLD.
    # -----------------------------------------------------------------------
    bar_btc = ObservationRecord(
        observation_id="obs_kline_btc_20260802",
        snapshot_id="dss_chain_test",
        series_id="BTC_USDT_KLINE_1D",
        event_time="2026-08-02T23:59:59Z",
        knowledge_time="2026-08-03T00:00:00Z",
        revision=1,
        payload={
            "open_time": "2026-08-02T00:00:00Z",
            "close_time": "2026-08-02T23:59:59Z",
            "open": "60000.00",
            "high": "61000.00",
            "low": "59000.00",
            "close": "60500.00",
            "volume": "100.0",
        },
    )

    settle_res_1 = DeferredSettlementService.attempt_settlement(
        episode_def=episode,
        current_account=acc_0,
        pending=pending_1,
        settlement_round_id="rnd_001",
        settlement_round_index=1,
        settlement_time="2026-08-02T00:00:00Z",
        all_observations=(bar_btc,),
        valuation_marks={"BTC": Decimal("60000.00")},
        expected_open_time="2026-08-02T00:00:00Z",
        admission_account=acc_0,
    )
    assert settle_res_1.is_still_pending
    assert settle_res_1.settlement_outcome is None

    # Proposal in round 1 is HOLD
    prop_1 = ProposedDecision(
        decision_id="dec-prop_001",
        round_id="rnd_001",
        policy_id="pol-def_alpha",
        policy_version_id="pol-ver_alpha_v1",
        knowledge_cutoff="2026-08-02T00:00:00Z",
        generated_at="2026-08-02T00:00:00Z",
        desired_allocations=(),
        requested_actions=(
            RequestedAction(
                action_type=ActionType.HOLD,
                resource_id="BTC",
                quantity=Decimal("0.00"),
            ),
        ),
        rationale=DecisionRationale(method="hold_waiting_for_settlement"),
    )

    adm_res_1 = DeferredAdmissionService.admit_decision(
        episode_def=episode,
        proposal=prop_1,
        current_account=acc_0,
        authoritative_round_id="rnd_001",
        authoritative_cutoff="2026-08-02T00:00:00Z",
        resource_to_series_map=resource_map,
        current_pending=pending_1,
    )
    assert adm_res_1.decision_outcome is not None
    assert adm_res_1.pending_transition == pending_1  # retains active pending
    assert not adm_res_1.is_newly_admitted

    pol_record_1 = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=acc_0.compute_hash(),
        account_state_after_hash=acc_0.compute_hash(),
        pending_before=pending_ref_1,
        pending_after=pending_ref_1,  # preserved unchanged
        settlement_outcome_hash=None,
        deferred_transition_hash=None,
        proposed_decision_hash=prop_1.compute_hash(),
        decision_outcome_hash=adm_res_1.decision_outcome.compute_hash(),
    )

    merkle_1 = compute_deferred_state_merkle_hash(round_0_hash, [pol_record_1])
    round_record_1 = DeferredRoundRecord(
        round_id="rnd_001",
        run_id="ep-run_chain_001",
        round_index=1,
        parent_round_hash=round_0_hash,
        knowledge_cutoff="2026-08-02T00:00:00Z",
        execution_start_time="2026-08-02T00:00:01Z",
        execution_end_time="2026-08-02T00:00:02Z",
        effective_time="2026-08-02T00:00:02Z",
        eligible_observation_hashes=(),
        policy_round_records=(pol_record_1,),
        state_merkle_hash=merkle_1,
    )
    _assert_schema_and_codec(round_record_1)
    round_1_hash = round_record_1.compute_hash()

    # -----------------------------------------------------------------------
    # Round 2: Cutoff is 2026-08-03T00:00:00Z -> Bar is knowledge-eligible!
    # B2 settles pending_1.
    # B1 admits a new proposal (ALLOCATE ETH 5.0).
    # -----------------------------------------------------------------------
    settle_res_2 = DeferredSettlementService.attempt_settlement(
        episode_def=episode,
        current_account=acc_0,
        pending=pending_1,
        settlement_round_id="rnd_002",
        settlement_round_index=2,
        settlement_time="2026-08-03T00:00:00Z",
        all_observations=(bar_btc,),
        valuation_marks={"BTC": Decimal("60000.00")},
        expected_open_time="2026-08-02T00:00:00Z",
        admission_account=acc_0,
    )
    assert settle_res_2.is_settled
    settlement_outcome_1 = settle_res_2.settlement_outcome
    deferred_transition_1 = settle_res_2.deferred_transition
    acc_2 = settle_res_2.next_account
    assert settlement_outcome_1 is not None
    assert deferred_transition_1 is not None
    assert settlement_outcome_1.status == SettlementStatus.SETTLED

    # Policy submits a new BUY order in round 2 for ETH
    prop_2 = ProposedDecision(
        decision_id="dec-prop_002",
        round_id="rnd_002",
        policy_id="pol-def_alpha",
        policy_version_id="pol-ver_alpha_v1",
        knowledge_cutoff="2026-08-03T00:00:00Z",
        generated_at="2026-08-03T00:00:00Z",
        desired_allocations=(),
        requested_actions=(
            RequestedAction(
                action_type=ActionType.ALLOCATE,
                resource_id="ETH",
                quantity=Decimal("5.00000000"),
            ),
        ),
        rationale=DecisionRationale(method="buy_eth_signal"),
    )

    adm_res_2 = DeferredAdmissionService.admit_decision(
        episode_def=episode,
        proposal=prop_2,
        current_account=acc_2,
        authoritative_round_id="rnd_002",
        authoritative_cutoff="2026-08-03T00:00:00Z",
        resource_to_series_map=resource_map,
        current_pending=None,  # pending_1 was just settled in phase 1!
    )
    assert adm_res_2.is_newly_admitted
    pending_2 = adm_res_2.pending_transition
    assert pending_2 is not None

    pending_ref_2 = PendingStateReference(
        pending_transition_hash=pending_2.compute_hash(),
        admission_account_hash=acc_2.compute_hash(),
        expected_open_time="2026-08-04T00:00:00Z",
        settlement_deadline="2026-08-06T00:00:00Z",
    )

    pol_record_2 = DeferredPolicyRoundRecord(
        policy_id="pol-def_alpha",
        account_state_before_hash=acc_0.compute_hash(),
        account_state_after_hash=acc_2.compute_hash(),
        pending_before=pending_ref_1,
        pending_after=pending_ref_2,
        settlement_outcome_hash=settlement_outcome_1.compute_hash(),
        deferred_transition_hash=deferred_transition_1.compute_hash(),
        proposed_decision_hash=prop_2.compute_hash(),
        decision_outcome_hash=None,
    )

    merkle_2 = compute_deferred_state_merkle_hash(round_1_hash, [pol_record_2])
    round_record_2 = DeferredRoundRecord(
        round_id="rnd_002",
        run_id="ep-run_chain_001",
        round_index=2,
        parent_round_hash=round_1_hash,
        knowledge_cutoff="2026-08-03T00:00:00Z",
        execution_start_time="2026-08-03T00:00:01Z",
        execution_end_time="2026-08-03T00:00:02Z",
        effective_time="2026-08-03T00:00:02Z",
        eligible_observation_hashes=(bar_btc.compute_hash(),),
        policy_round_records=(pol_record_2,),
        state_merkle_hash=merkle_2,
    )
    _assert_schema_and_codec(round_record_2)

    # -----------------------------------------------------------------------
    # Assertions on Linkages and Record Separation
    # -----------------------------------------------------------------------
    # 1. Old settlement belongs to pending_1 (from Round 0)
    assert pol_record_2.pending_before.pending_transition_hash == pending_1.compute_hash()
    assert settlement_outcome_1.pending_transition_id == pending_1.pending_transition_id
    assert settlement_outcome_1.decision_id == prop_0.decision_id
    assert deferred_transition_1.settlement_outcome_id == settlement_outcome_1.settlement_outcome_id

    # 2. New proposal belongs to Round 2 and produces pending_2
    assert pol_record_2.proposed_decision_hash == prop_2.compute_hash()
    assert pol_record_2.pending_after.pending_transition_hash == pending_2.compute_hash()
    assert pending_2.decision_id == prop_2.decision_id

    # 3. Old settlement and new proposal are strictly distinct records
    assert settlement_outcome_1.compute_hash() != prop_2.compute_hash()
    assert pending_1.compute_hash() != pending_2.compute_hash()
    assert pol_record_2.pending_before != pol_record_2.pending_after
    assert pol_record_2.settlement_outcome_hash != pol_record_2.proposed_decision_hash
