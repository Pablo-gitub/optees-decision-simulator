"""Unit and contract tests for pending_transition and settlement_outcome domain records (DS-02D2A).

Verifies:
1. Real JSON Schema roundtrip against authoritative draft 2020-12 schemas.
2. Canonical valid example fixtures.
3. Stable ID prefixes and explicit linkages.
4. Illegal statuses rejection.
5. Mutual exclusivity of applied_transition_id and rejection_reasons.
6. Timestamp parsing, UTC enforcement, and causal inequalities.
7. Numerical validation: booleans, NaN, Infinity, negative values.
8. Deep immutability of nested dicts/structures.
9. Hash determinism and permutation invariance.
10. Exact open_time retention in normalizer (ms < 2025 <= us).
11. Preserved event_time semantics (close_time).
12. Legacy v1 fixture immutability.
"""

from __future__ import annotations

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest

from simulator.domain.errors import InvalidTimestampError
from simulator.domain.lifecycle import (
    ActionType,
    PendingStatus,
    SettlementStatus,
)
from simulator.domain.models import (
    PendingTransitionRecord,
    RejectionReason,
    RequestedAction,
    SettlementOutcome,
    TargetBarRule,
)
from simulator.infrastructure.adapters.market_normalizer import (
    RawKlineRecord,
    normalize_single_kline,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
SCHEMAS_DIR = REPO_ROOT / "docs" / "contracts" / "schemas"
EXAMPLES_DIR = REPO_ROOT / "docs" / "contracts" / "examples"

validator_path = REPO_ROOT / "tools" / "validate_contracts.py"
spec = importlib.util.spec_from_file_location("validate_contracts", str(validator_path))
validate_contracts = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(validate_contracts)  # type: ignore[union-attr]
validate_data = validate_contracts.validate_data


def _load_schema(filename: str) -> dict:
    with open(SCHEMAS_DIR / filename, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_example(filename: str) -> dict:
    with open(EXAMPLES_DIR / "valid" / filename, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. Authoritative Schema Roundtrip & Canonical Examples
# ---------------------------------------------------------------------------


def test_pending_transition_schema_roundtrip() -> None:
    schema = _load_schema("pending_transition.v1.json")

    record = PendingTransitionRecord(
        pending_transition_id="pnd_round0_reactive_alloc",
        decision_id="dec-prop_round0_reactive",
        round_id="rnd_round_0",
        policy_id="pol-def_reactive_baseline",
        policy_version_id="pol-ver_reactive_v1",
        knowledge_cutoff="2026-08-01T00:00:00Z",
        admitted_at="2026-08-01T00:00:00Z",
        predecessor_account_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
        requested_action=RequestedAction(
            action_type=ActionType.ALLOCATE,
            resource_id="BTC",
            quantity=Decimal("1.50"),
            parameters={"target_series": "BTC_USDT_PRICE_1D"},
        ),
        target_bar_rule=TargetBarRule(
            series_id="BTC_USDT_PRICE_1D",
            selection_rule="FIRST_OPEN_GE_CUTOFF",
            expected_open_time="2026-08-01T00:00:00.000Z",
        ),
        admission_evidence={"syntax_checked": True, "universe_checked": True},
        status=PendingStatus.ADMITTED_PENDING,
    )

    data = record.to_dict()
    errors = validate_data(data, schema)
    assert not errors, f"pending_transition schema validation errors: {errors}"

    reconstituted = PendingTransitionRecord.from_dict(data)
    assert reconstituted == record
    assert reconstituted.compute_hash() == record.compute_hash()


def test_canonical_pending_transition_fixture_is_valid() -> None:
    schema = _load_schema("pending_transition.v1.json")
    example = _load_example("pending_transition.v1.json")

    errors = validate_data(example, schema)
    assert not errors, f"Canonical pending_transition example errors: {errors}"

    record = PendingTransitionRecord.from_dict(example)
    assert record.pending_transition_id == example["pending_transition_id"]
    assert record.status == PendingStatus.ADMITTED_PENDING


def test_settlement_outcome_settled_schema_roundtrip() -> None:
    schema = _load_schema("settlement_outcome.v1.json")

    record = SettlementOutcome(
        settlement_outcome_id="set-out_round2_reactive_settled",
        pending_transition_id="pnd_round0_reactive_alloc",
        decision_id="dec-prop_round0_reactive",
        round_id="rnd_round_2",
        policy_id="pol-def_reactive_baseline",
        status=SettlementStatus.SETTLED,
        settled_at="2026-08-03T00:00:01Z",
        applied_transition_id="trn_round2_settled_transition",
        rejection_reasons=(),
        settlement_evidence={
            "observation_id": "obs_BTC_20260801_r1",
            "selected_revision": 1,
            "execution_price": "60000.00",
            "execution_fill_time": "2026-08-01T00:00:00.000Z",
            "observation_knowledge_time": "2026-08-03T00:00:00Z",
        },
    )

    data = record.to_dict()
    errors = validate_data(data, schema)
    assert not errors, f"settlement_outcome schema validation errors: {errors}"

    reconstituted = SettlementOutcome.from_dict(data)
    assert reconstituted == record
    assert reconstituted.compute_hash() == record.compute_hash()


def test_canonical_settlement_outcome_settled_fixture_is_valid() -> None:
    schema = _load_schema("settlement_outcome.v1.json")
    example = _load_example("settlement_outcome_settled.v1.json")

    errors = validate_data(example, schema)
    assert not errors, f"Canonical settlement_outcome_settled errors: {errors}"

    record = SettlementOutcome.from_dict(example)
    assert record.status == SettlementStatus.SETTLED
    assert record.applied_transition_id is not None
    assert len(record.rejection_reasons) == 0


def test_canonical_settlement_outcome_rejected_fixture_is_valid() -> None:
    schema = _load_schema("settlement_outcome.v1.json")
    example = _load_example("settlement_outcome_rejected.v1.json")

    errors = validate_data(example, schema)
    assert not errors, f"Canonical settlement_outcome_rejected errors: {errors}"

    record = SettlementOutcome.from_dict(example)
    assert record.status == SettlementStatus.REJECTED
    assert record.applied_transition_id is None
    assert len(record.rejection_reasons) >= 1


# ---------------------------------------------------------------------------
# 2. Terminal Exclusivity & Cancellation Contract
# ---------------------------------------------------------------------------


def test_settled_requires_transition_and_forbids_rejection_reasons() -> None:
    # 1. SETTLED without applied_transition_id is rejected
    with pytest.raises(ValueError, match="requires applied_transition_id"):
        SettlementOutcome(
            settlement_outcome_id="set-out_001",
            pending_transition_id="pnd_001",
            decision_id="dec-prop_001",
            round_id="rnd_001",
            policy_id="pol-def_001",
            status=SettlementStatus.SETTLED,
            settled_at="2026-08-03T00:00:00Z",
            applied_transition_id=None,
            rejection_reasons=(),
        )

    # 2. SETTLED with rejection reasons is rejected
    with pytest.raises(ValueError, match="cannot contain rejection reasons"):
        SettlementOutcome(
            settlement_outcome_id="set-out_001",
            pending_transition_id="pnd_001",
            decision_id="dec-prop_001",
            round_id="rnd_001",
            policy_id="pol-def_001",
            status=SettlementStatus.SETTLED,
            settled_at="2026-08-03T00:00:00Z",
            applied_transition_id="trn_001",
            rejection_reasons=(RejectionReason("ERR", "message"),),
        )


def test_rejected_requires_reasons_and_forbids_transition() -> None:
    # 1. REJECTED with applied_transition_id is forbidden
    with pytest.raises(ValueError, match="forbids applied_transition_id"):
        SettlementOutcome(
            settlement_outcome_id="set-out_001",
            pending_transition_id="pnd_001",
            decision_id="dec-prop_001",
            round_id="rnd_001",
            policy_id="pol-def_001",
            status=SettlementStatus.REJECTED,
            settled_at="2026-08-03T00:00:00Z",
            applied_transition_id="trn_001",
            rejection_reasons=(RejectionReason("ERR", "message"),),
        )

    # 2. REJECTED with empty rejection_reasons is forbidden
    with pytest.raises(ValueError, match="requires at least one rejection reason"):
        SettlementOutcome(
            settlement_outcome_id="set-out_001",
            pending_transition_id="pnd_001",
            decision_id="dec-prop_001",
            round_id="rnd_001",
            policy_id="pol-def_001",
            status=SettlementStatus.REJECTED,
            settled_at="2026-08-03T00:00:00Z",
            applied_transition_id=None,
            rejection_reasons=(),
        )


def test_cancellation_represented_as_rejected_with_episode_cancelled() -> None:
    outcome = SettlementOutcome(
        settlement_outcome_id="set-out_cancel_001",
        pending_transition_id="pnd_001",
        decision_id="dec-prop_001",
        round_id="rnd_001",
        policy_id="pol-def_001",
        status=SettlementStatus.REJECTED,
        settled_at="2026-08-03T00:00:00Z",
        applied_transition_id=None,
        rejection_reasons=(
            RejectionReason(
                code="EPISODE_CANCELLED",
                message="Episode execution was cancelled prior to settlement",
                violating_field=None,
            ),
        ),
    )
    assert outcome.status == SettlementStatus.REJECTED
    assert outcome.rejection_reasons[0].code == "EPISODE_CANCELLED"
    assert outcome.applied_transition_id is None


def test_illegal_status_values_are_rejected() -> None:
    # Settlement outcome allows only SETTLED or REJECTED
    for invalid_status in ("ACCEPTED", "ADMITTED_PENDING", "FALLBACK_HOLD", "CANCELLED", "PENDING"):
        with pytest.raises(ValueError):
            SettlementOutcome(
                settlement_outcome_id="set-out_001",
                pending_transition_id="pnd_001",
                decision_id="dec-prop_001",
                round_id="rnd_001",
                policy_id="pol-def_001",
                status=invalid_status,  # type: ignore[arg-type]
                settled_at="2026-08-03T00:00:00Z",
            )

    # Pending transition allows only ADMITTED_PENDING
    with pytest.raises(ValueError, match="ADMITTED_PENDING"):
        PendingTransitionRecord(
            pending_transition_id="pnd_001",
            decision_id="dec-prop_001",
            round_id="rnd_001",
            policy_id="pol-def_001",
            policy_version_id="pol-ver_001",
            knowledge_cutoff="2026-08-01T00:00:00Z",
            admitted_at="2026-08-01T00:00:00Z",
            predecessor_account_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            requested_action=RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.0")),
            target_bar_rule=TargetBarRule("BTC_USDT_PRICE_1D"),
            status="SETTLED",  # type: ignore[arg-type]
        )


def test_versions_prefixes_and_target_rule_are_frozen() -> None:
    example = _load_example("pending_transition.v1.json")
    example["schema_version"] = "1.1.0"
    with pytest.raises(ValueError, match="schema_version"):
        PendingTransitionRecord.from_dict(example)

    example = _load_example("pending_transition.v1.json")
    example["pending_transition_id"] = "trn-pend_legacy_alias"
    with pytest.raises(ValueError, match="pending_transition_id"):
        PendingTransitionRecord.from_dict(example)

    with pytest.raises(ValueError, match="FIRST_OPEN_GE_CUTOFF"):
        TargetBarRule("BTC_USDT_PRICE_1D", selection_rule="ANY_FUTURE_BAR")


def test_settled_outcome_requires_complete_causal_execution_evidence() -> None:
    base = _load_example("settlement_outcome_settled.v1.json")
    del base["settlement_evidence"]["observation_knowledge_time"]
    with pytest.raises(ValueError, match="missing execution evidence"):
        SettlementOutcome.from_dict(base)

    base = _load_example("settlement_outcome_settled.v1.json")
    base["settlement_evidence"]["observation_knowledge_time"] = "2026-07-31T00:00:00Z"
    with pytest.raises(ValueError, match="execution_fill_time"):
        SettlementOutcome.from_dict(base)


def test_from_dict_rejects_unknown_nested_fields() -> None:
    pending = _load_example("pending_transition.v1.json")
    pending["target_bar_rule"]["future_option"] = True
    with pytest.raises(ValueError, match="TargetBarRule fields"):
        PendingTransitionRecord.from_dict(pending)

    outcome = _load_example("settlement_outcome_rejected.v1.json")
    outcome["rejection_reasons"][0]["debug"] = "not contractual"
    with pytest.raises(ValueError, match="Rejection reason fields"):
        SettlementOutcome.from_dict(outcome)


# ---------------------------------------------------------------------------
# 3. ID Validation and Linkages
# ---------------------------------------------------------------------------


def test_id_prefix_validation() -> None:
    # Invalid pending_transition_id prefix
    with pytest.raises(ValueError, match="Invalid pending_transition_id"):
        PendingTransitionRecord(
            pending_transition_id="bad-prefix_001",
            decision_id="dec-prop_001",
            round_id="rnd_001",
            policy_id="pol-def_001",
            policy_version_id="pol-ver_001",
            knowledge_cutoff="2026-08-01T00:00:00Z",
            admitted_at="2026-08-01T00:00:00Z",
            predecessor_account_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            requested_action=RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.0")),
            target_bar_rule=TargetBarRule("BTC_USDT_PRICE_1D"),
        )

    # Invalid decision_id prefix
    with pytest.raises(ValueError, match="Invalid decision_id"):
        PendingTransitionRecord(
            pending_transition_id="pnd_001",
            decision_id="bad-prop_001",
            round_id="rnd_001",
            policy_id="pol-def_001",
            policy_version_id="pol-ver_001",
            knowledge_cutoff="2026-08-01T00:00:00Z",
            admitted_at="2026-08-01T00:00:00Z",
            predecessor_account_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            requested_action=RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.0")),
            target_bar_rule=TargetBarRule("BTC_USDT_PRICE_1D"),
        )

    # Invalid settlement_outcome_id prefix
    with pytest.raises(ValueError, match="Invalid settlement_outcome_id"):
        SettlementOutcome(
            settlement_outcome_id="bad-set_001",
            pending_transition_id="pnd_001",
            decision_id="dec-prop_001",
            round_id="rnd_001",
            policy_id="pol-def_001",
            status=SettlementStatus.SETTLED,
            settled_at="2026-08-03T00:00:00Z",
            applied_transition_id="trn_001",
        )


# ---------------------------------------------------------------------------
# 4. Timestamps & Causal Inequalities
# ---------------------------------------------------------------------------


def test_timestamp_causal_inequalities() -> None:
    # admitted_at must equal the policy knowledge cutoff
    with pytest.raises(ValueError, match="must equal knowledge_cutoff"):
        PendingTransitionRecord(
            pending_transition_id="pnd_001",
            decision_id="dec-prop_001",
            round_id="rnd_001",
            policy_id="pol-def_001",
            policy_version_id="pol-ver_001",
            knowledge_cutoff="2026-08-01T00:00:00Z",
            admitted_at="2026-08-01T00:00:01Z",
            predecessor_account_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            requested_action=RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.0")),
            target_bar_rule=TargetBarRule("BTC_USDT_PRICE_1D"),
        )

    # expected_open_time cannot be before knowledge_cutoff
    with pytest.raises(ValueError, match="must be >= knowledge_cutoff"):
        PendingTransitionRecord(
            pending_transition_id="pnd_001",
            decision_id="dec-prop_001",
            round_id="rnd_001",
            policy_id="pol-def_001",
            policy_version_id="pol-ver_001",
            knowledge_cutoff="2026-08-01T00:00:00Z",
            admitted_at="2026-08-01T00:00:00Z",
            predecessor_account_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            requested_action=RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.0")),
            target_bar_rule=TargetBarRule(
                "BTC_USDT_PRICE_1D",
                expected_open_time="2026-07-31T00:00:00.000Z",
            ),
        )

    # Partial execution evidence cannot establish a causal settlement.
    with pytest.raises(ValueError, match="missing execution evidence"):
        SettlementOutcome(
            settlement_outcome_id="set-out_001",
            pending_transition_id="pnd_001",
            decision_id="dec-prop_001",
            round_id="rnd_001",
            policy_id="pol-def_001",
            status=SettlementStatus.SETTLED,
            settled_at="2026-08-03T00:00:00Z",
            applied_transition_id="trn_001",
            settlement_evidence={"execution_fill_time": "2026-08-04T00:00:00Z"},
        )


def test_timestamp_utc_strictness() -> None:
    # Non-UTC / timezone offset rejected
    with pytest.raises(InvalidTimestampError):
        PendingTransitionRecord(
            pending_transition_id="pnd_001",
            decision_id="dec-prop_001",
            round_id="rnd_001",
            policy_id="pol-def_001",
            policy_version_id="pol-ver_001",
            knowledge_cutoff="2026-08-01T02:00:00+02:00",
            admitted_at="2026-08-01T02:00:00+02:00",
            predecessor_account_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            requested_action=RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.0")),
            target_bar_rule=TargetBarRule("BTC_USDT_PRICE_1D"),
        )


# ---------------------------------------------------------------------------
# 5. Quantity and Numerical Validation
# ---------------------------------------------------------------------------


def test_boolean_quantities_are_rejected() -> None:
    # Booleans in PendingTransitionRecord requested_action quantity
    with pytest.raises(TypeError, match="must be a Decimal"):
        PendingTransitionRecord(
            pending_transition_id="pnd_001",
            decision_id="dec-prop_001",
            round_id="rnd_001",
            policy_id="pol-def_001",
            policy_version_id="pol-ver_001",
            knowledge_cutoff="2026-08-01T00:00:00Z",
            admitted_at="2026-08-01T00:00:00Z",
            predecessor_account_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            requested_action=RequestedAction(ActionType.ALLOCATE, "BTC", True),  # type: ignore[arg-type]
            target_bar_rule=TargetBarRule("BTC_USDT_PRICE_1D"),
        )

    # Booleans in execution_price
    with pytest.raises(TypeError, match="cannot be a boolean"):
        SettlementOutcome(
            settlement_outcome_id="set-out_001",
            pending_transition_id="pnd_001",
            decision_id="dec-prop_001",
            round_id="rnd_001",
            policy_id="pol-def_001",
            status=SettlementStatus.SETTLED,
            settled_at="2026-08-03T00:00:00Z",
            applied_transition_id="trn_001",
            settlement_evidence={
                "observation_id": "obs_BTC_20260801_r1",
                "selected_revision": 1,
                "execution_fill_time": "2026-08-01T00:00:00Z",
                "observation_knowledge_time": "2026-08-03T00:00:00Z",
                "execution_price": True,
            },
        )


def test_non_finite_and_negative_quantities_are_rejected() -> None:
    # NaN in PendingTransitionRecord
    with pytest.raises(ValueError, match="finite"):
        PendingTransitionRecord(
            pending_transition_id="pnd_001",
            decision_id="dec-prop_001",
            round_id="rnd_001",
            policy_id="pol-def_001",
            policy_version_id="pol-ver_001",
            knowledge_cutoff="2026-08-01T00:00:00Z",
            admitted_at="2026-08-01T00:00:00Z",
            predecessor_account_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            requested_action=RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("NaN")),
            target_bar_rule=TargetBarRule("BTC_USDT_PRICE_1D"),
        )

    # Infinity in PendingTransitionRecord
    with pytest.raises(ValueError, match="finite"):
        PendingTransitionRecord(
            pending_transition_id="pnd_001",
            decision_id="dec-prop_001",
            round_id="rnd_001",
            policy_id="pol-def_001",
            policy_version_id="pol-ver_001",
            knowledge_cutoff="2026-08-01T00:00:00Z",
            admitted_at="2026-08-01T00:00:00Z",
            predecessor_account_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            requested_action=RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("Infinity")),
            target_bar_rule=TargetBarRule("BTC_USDT_PRICE_1D"),
        )

    # Negative quantity in PendingTransitionRecord
    with pytest.raises(ValueError, match="finite non-negative"):
        PendingTransitionRecord(
            pending_transition_id="pnd_001",
            decision_id="dec-prop_001",
            round_id="rnd_001",
            policy_id="pol-def_001",
            policy_version_id="pol-ver_001",
            knowledge_cutoff="2026-08-01T00:00:00Z",
            admitted_at="2026-08-01T00:00:00Z",
            predecessor_account_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            requested_action=RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("-1.0")),
            target_bar_rule=TargetBarRule("BTC_USDT_PRICE_1D"),
        )


# ---------------------------------------------------------------------------
# 6. Deep Immutability & Unknown Properties
# ---------------------------------------------------------------------------


def test_deep_immutability_of_evidence() -> None:
    mutable_evidence = {"flag": True, "nested": {"key": "val"}}
    record = PendingTransitionRecord(
        pending_transition_id="pnd_001",
        decision_id="dec-prop_001",
        round_id="rnd_001",
        policy_id="pol-def_001",
        policy_version_id="pol-ver_001",
        knowledge_cutoff="2026-08-01T00:00:00Z",
        admitted_at="2026-08-01T00:00:00Z",
        predecessor_account_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
        requested_action=RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.0")),
        target_bar_rule=TargetBarRule("BTC_USDT_PRICE_1D"),
        admission_evidence=mutable_evidence,
    )

    # Mutating original dict must not affect record
    mutable_evidence["flag"] = False
    assert record.admission_evidence["flag"] is True

    # Attempting to mutate record.admission_evidence must raise TypeError (mappingproxy)
    with pytest.raises(TypeError):
        record.admission_evidence["new_key"] = "bad"  # type: ignore[index]


def test_unknown_properties_rejected_by_schemas() -> None:
    pending_schema = _load_schema("pending_transition.v1.json")
    example_pending = _load_example("pending_transition.v1.json")
    example_pending["rogue_field"] = "malicious"
    errs = validate_data(example_pending, pending_schema)
    assert any("unexpected additional property" in e for e in errs)

    settle_schema = _load_schema("settlement_outcome.v1.json")
    example_settle = _load_example("settlement_outcome_settled.v1.json")
    example_settle["rogue_field"] = "malicious"
    errs = validate_data(example_settle, settle_schema)
    assert any("unexpected additional property" in e for e in errs)


# ---------------------------------------------------------------------------
# 7. Hash Determinism & Permutation Invariance
# ---------------------------------------------------------------------------


def test_hash_determinism_and_permutation_invariance() -> None:
    rec1 = PendingTransitionRecord(
        pending_transition_id="pnd_001",
        decision_id="dec-prop_001",
        round_id="rnd_001",
        policy_id="pol-def_001",
        policy_version_id="pol-ver_001",
        knowledge_cutoff="2026-08-01T00:00:00Z",
        admitted_at="2026-08-01T00:00:00Z",
        predecessor_account_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
        requested_action=RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.0")),
        target_bar_rule=TargetBarRule("BTC_USDT_PRICE_1D"),
        admission_evidence={"b": 2, "a": 1},
    )

    rec2 = PendingTransitionRecord(
        pending_transition_id="pnd_001",
        decision_id="dec-prop_001",
        round_id="rnd_001",
        policy_id="pol-def_001",
        policy_version_id="pol-ver_001",
        knowledge_cutoff="2026-08-01T00:00:00Z",
        admitted_at="2026-08-01T00:00:00Z",
        predecessor_account_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
        requested_action=RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.0")),
        target_bar_rule=TargetBarRule("BTC_USDT_PRICE_1D"),
        admission_evidence={"a": 1, "b": 2},
    )

    assert rec1.compute_hash() == rec2.compute_hash()

    # Mutation sensitivity
    rec3 = PendingTransitionRecord(
        pending_transition_id="pnd_001",
        decision_id="dec-prop_001",
        round_id="rnd_001",
        policy_id="pol-def_001",
        policy_version_id="pol-ver_001",
        knowledge_cutoff="2026-08-01T00:00:00Z",
        admitted_at="2026-08-01T00:00:00Z",
        predecessor_account_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
        requested_action=RequestedAction(ActionType.ALLOCATE, "BTC", Decimal("1.00000001")),
        target_bar_rule=TargetBarRule("BTC_USDT_PRICE_1D"),
        admission_evidence={"a": 1, "b": 2},
    )
    assert rec1.compute_hash() != rec3.compute_hash()


# ---------------------------------------------------------------------------
# 8. Normalizer open_time Retention & event_time Preservation
# ---------------------------------------------------------------------------


def test_normalizer_retains_open_time_ms_pre_2025() -> None:
    # 2024-01-01 1d kline in ms
    raw_kline = RawKlineRecord(
        symbol="BTCUSDT",
        open_time=1704067200000,  # 2024-01-01T00:00:00.000Z
        open="42000.00",
        high="43000.00",
        low="41500.00",
        close="42500.00",
        volume="100.00",
        close_time=1704153599999,  # 2024-01-01T23:59:59.999Z
        quote_volume="4250000.00",
        count=5000,
        taker_buy_volume="40.00",
        taker_buy_quote_volume="1700000.00",
    )

    obs = normalize_single_kline(raw_kline, snapshot_id="ds-snap_btc_2024")
    # 1. open_time is exact ISO-8601 UTC with ms precision
    assert obs.payload["open_time"] == "2024-01-01T00:00:00.000Z"
    # 2. event_time continues to be close_time
    assert obs.event_time == "2024-01-01T23:59:59.999Z"
    # 3. knowledge_time remains D+2
    assert obs.knowledge_time == "2024-01-03T00:00:00Z"


def test_normalizer_retains_open_time_us_2025_plus() -> None:
    # 2025-01-01 1d kline in us
    raw_kline = RawKlineRecord(
        symbol="ETHUSDT",
        open_time=1735689600000000,  # 2025-01-01T00:00:00.000000Z
        open="3000.00",
        high="3100.00",
        low="2950.00",
        close="3050.00",
        volume="500.00",
        close_time=1735775999999999,  # 2025-01-01T23:59:59.999999Z
        quote_volume="1525000.00",
        count=12000,
        taker_buy_volume="250.00",
        taker_buy_quote_volume="762500.00",
    )

    obs = normalize_single_kline(raw_kline, snapshot_id="ds-snap_eth_2025")
    # 1. open_time is exact ISO-8601 UTC with us precision
    assert obs.payload["open_time"] == "2025-01-01T00:00:00.000000Z"
    # 2. event_time continues to be close_time
    assert obs.event_time == "2025-01-01T23:59:59.999999Z"
    # 3. knowledge_time remains D+2
    assert obs.knowledge_time == "2025-01-03T00:00:00Z"


# ---------------------------------------------------------------------------
# 9. Legacy V1 Fixture Immutability
# ---------------------------------------------------------------------------


def test_legacy_fixtures_remain_immutable() -> None:
    # Verify existing manifest fixture checksum is preserved
    manifest_ex = _load_example("market_dataset_manifest.v1.json")
    assert manifest_ex["checksum_sha256"] == (
        "sha256:5b0c1896110c8e38e2b79299ba27fe40fe5e6989f05f7291a08385627cc93286"
    )

    # Verify existing knowledge cutoff observations fixture is preserved
    cutoff_obs_ex = _load_example("knowledge_cutoff_observations.v1.json")
    assert len(cutoff_obs_ex["observations"]) == 4
    for obs in cutoff_obs_ex["observations"]:
        assert "price" in obs["payload"]
        assert "open_time" not in obs["payload"]  # legacy fixture has no open_time
