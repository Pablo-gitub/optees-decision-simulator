"""Unit tests for DeferredTransitionRecord and transition.v2 contract invariants."""

from __future__ import annotations

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest

from simulator.domain.errors import InvalidTimestampError
from simulator.domain.lifecycle import CostType
from simulator.domain.models import (
    CostItem,
    DeferredTransitionRecord,
    ResourceDelta,
    TransitionRecord,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
SCHEMA_V2_PATH = REPO_ROOT / "docs" / "contracts" / "schemas" / "transition.v2.json"
SCHEMA_V1_PATH = REPO_ROOT / "docs" / "contracts" / "schemas" / "transition.v1.json"
EXAMPLE_V2_PATH = (
    REPO_ROOT / "docs" / "contracts" / "examples" / "valid" / "deferred_transition.v2.json"
)
EXAMPLE_V1_PATH = (
    REPO_ROOT / "docs" / "contracts" / "examples" / "valid" / "transition_and_account_state.v1.json"
)


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_contracts", REPO_ROOT / "tools" / "validate_contracts.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_data


def _make_valid_record() -> DeferredTransitionRecord:
    return DeferredTransitionRecord(
        transition_id="trn_round2_reactive_transition",
        round_id="rnd_round_2",
        policy_id="pol-def_reactive_baseline",
        settlement_outcome_id="set-out_round2_reactive_settled",
        economic_fill_time="2026-08-01T00:00:00.000Z",
        effective_time="2026-08-03T00:00:01Z",
        resource_deltas=(
            ResourceDelta(
                resource_id="USDT",
                delta_quantity=Decimal("-60060.00"),
                valuation_price=Decimal("1.00"),
            ),
            ResourceDelta(
                resource_id="BTC",
                delta_quantity=Decimal("1.00000000"),
                valuation_price=Decimal("60000.00"),
            ),
        ),
        costs=(
            CostItem(
                cost_type=CostType.TRANSACTION_FEE,
                resource_id="USDT",
                amount=Decimal("60.00"),
            ),
        ),
        total_cost_reference_unit=Decimal("60.00"),
        account_state_before_hash=(
            "sha256:0000000000000000000000000000000000000000000000000000000000000000"
        ),
        account_state_after_hash=(
            "sha256:1111111111111111111111111111111111111111111111111111111111111111"
        ),
    )


def test_deferred_transition_v2_roundtrip_and_schema_validation():
    validate_data = _load_validator()
    with open(SCHEMA_V2_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)

    record = _make_valid_record()
    data = record.to_dict()

    errs = validate_data(data, schema)
    assert not errs, f"Validation errors: {errs}"

    reconstituted = DeferredTransitionRecord.from_dict(data)
    assert reconstituted == record
    assert reconstituted.compute_hash() == record.compute_hash()


def test_canonical_example_matches_deferred_transition_record():
    validate_data = _load_validator()
    with open(SCHEMA_V2_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)
    with open(EXAMPLE_V2_PATH, "r", encoding="utf-8") as f:
        example = json.load(f)

    errs = validate_data(example, schema)
    assert not errs, f"Canonical example errors: {errs}"

    record = DeferredTransitionRecord.from_dict(example)
    assert record.to_dict() == example


def test_settlement_outcome_id_missing_or_bad_prefix():
    validate_data = _load_validator()
    with open(SCHEMA_V2_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)

    base = _make_valid_record().to_dict()

    # Missing in schema
    bad_missing = dict(base)
    del bad_missing["settlement_outcome_id"]
    errs = validate_data(bad_missing, schema)
    assert any("settlement_outcome_id" in e for e in errs)

    # Bad prefixes
    for bad_id in [
        "dec-out_001",
        "trn_001",
        "pnd_001",
        "invalid-prefix",
        "",
    ]:
        with pytest.raises(ValueError):
            DeferredTransitionRecord(
                transition_id="trn_test",
                round_id="rnd_test",
                policy_id="pol-def_test",
                settlement_outcome_id=bad_id,
                economic_fill_time="2026-08-01T00:00:00Z",
                effective_time="2026-08-01T00:00:00Z",
                resource_deltas=(ResourceDelta("BTC", Decimal("1"), Decimal("100")),),
                costs=(),
                total_cost_reference_unit=Decimal("0"),
                account_state_before_hash="sha256:" + "0" * 64,
                account_state_after_hash="sha256:" + "1" * 64,
            )


def test_illegal_presence_of_outcome_id():
    validate_data = _load_validator()
    with open(SCHEMA_V2_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)

    base = _make_valid_record().to_dict()
    base["outcome_id"] = "dec-out_round2_reactive_accepted"

    # Schema must reject additional property
    errs = validate_data(base, schema)
    assert any("outcome_id" in e for e in errs)

    # from_dict must reject outcome_id
    with pytest.raises(ValueError, match="DeferredTransitionRecord forbids outcome_id"):
        DeferredTransitionRecord.from_dict(base)


def test_schema_version_and_type_errors():
    validate_data = _load_validator()
    with open(SCHEMA_V2_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)

    base = _make_valid_record().to_dict()

    # Wrong schema_version
    bad_ver = dict(base, schema_version="1.0.0")
    assert any("schema_version" in e for e in validate_data(bad_ver, schema))
    with pytest.raises(ValueError, match="schema_version must be 2.0.0"):
        DeferredTransitionRecord.from_dict(bad_ver)

    # Wrong $type
    bad_type = dict(base, **{"$type": "pending_transition"})
    assert any("$type" in e for e in validate_data(bad_type, schema))
    with pytest.raises(ValueError, match="\\$type must be transition"):
        DeferredTransitionRecord.from_dict(bad_type)


def test_economic_fill_time_causality():
    # economic_fill_time after effective_time must fail
    with pytest.raises(ValueError, match="cannot be after effective_time"):
        DeferredTransitionRecord(
            transition_id="trn_test",
            round_id="rnd_test",
            policy_id="pol-def_test",
            settlement_outcome_id="set-out_test",
            economic_fill_time="2026-08-05T00:00:00Z",
            effective_time="2026-08-04T00:00:00Z",
            resource_deltas=(ResourceDelta("BTC", Decimal("1"), Decimal("100")),),
            costs=(),
            total_cost_reference_unit=Decimal("0"),
            account_state_before_hash="sha256:" + "0" * 64,
            account_state_after_hash="sha256:" + "1" * 64,
        )


def test_timestamp_non_utc_or_ambiguous():
    for bad_ts in [
        "2026-08-01 00:00:00",
        "2026-08-01T00:00:00+02:00",
        "2026-08-01T00:00:00",
        "not-a-timestamp",
    ]:
        with pytest.raises(InvalidTimestampError):
            DeferredTransitionRecord(
                transition_id="trn_test",
                round_id="rnd_test",
                policy_id="pol-def_test",
                settlement_outcome_id="set-out_test",
                economic_fill_time=bad_ts,
                effective_time="2026-08-01T00:00:00Z",
                resource_deltas=(ResourceDelta("BTC", Decimal("1"), Decimal("100")),),
                costs=(),
                total_cost_reference_unit=Decimal("0"),
                account_state_before_hash="sha256:" + "0" * 64,
                account_state_after_hash="sha256:" + "1" * 64,
            )


def test_numeric_validation_booleans_nan_infinity_negatives():
    base = _make_valid_record()

    # Boolean as quantity
    with pytest.raises(TypeError):
        DeferredTransitionRecord(
            transition_id=base.transition_id,
            round_id=base.round_id,
            policy_id=base.policy_id,
            settlement_outcome_id=base.settlement_outcome_id,
            economic_fill_time=base.economic_fill_time,
            effective_time=base.effective_time,
            resource_deltas=(
                ResourceDelta("BTC", True, Decimal("100")),  # type: ignore
            ),
            costs=base.costs,
            total_cost_reference_unit=base.total_cost_reference_unit,
            account_state_before_hash=base.account_state_before_hash,
            account_state_after_hash=base.account_state_after_hash,
        )

    # Boolean as valuation_price
    with pytest.raises(TypeError):
        DeferredTransitionRecord(
            transition_id=base.transition_id,
            round_id=base.round_id,
            policy_id=base.policy_id,
            settlement_outcome_id=base.settlement_outcome_id,
            economic_fill_time=base.economic_fill_time,
            effective_time=base.effective_time,
            resource_deltas=(
                ResourceDelta("BTC", Decimal("1"), True),  # type: ignore
            ),
            costs=base.costs,
            total_cost_reference_unit=base.total_cost_reference_unit,
            account_state_before_hash=base.account_state_before_hash,
            account_state_after_hash=base.account_state_after_hash,
        )

    # NaN in delta_quantity
    with pytest.raises(ValueError):
        DeferredTransitionRecord(
            transition_id=base.transition_id,
            round_id=base.round_id,
            policy_id=base.policy_id,
            settlement_outcome_id=base.settlement_outcome_id,
            economic_fill_time=base.economic_fill_time,
            effective_time=base.effective_time,
            resource_deltas=(ResourceDelta("BTC", Decimal("NaN"), Decimal("100")),),
            costs=base.costs,
            total_cost_reference_unit=base.total_cost_reference_unit,
            account_state_before_hash=base.account_state_before_hash,
            account_state_after_hash=base.account_state_after_hash,
        )

    # Zero valuation_price
    with pytest.raises(ValueError, match="positive finite Decimal"):
        DeferredTransitionRecord(
            transition_id=base.transition_id,
            round_id=base.round_id,
            policy_id=base.policy_id,
            settlement_outcome_id=base.settlement_outcome_id,
            economic_fill_time=base.economic_fill_time,
            effective_time=base.effective_time,
            resource_deltas=(ResourceDelta("BTC", Decimal("1"), Decimal("0")),),
            costs=base.costs,
            total_cost_reference_unit=base.total_cost_reference_unit,
            account_state_before_hash=base.account_state_before_hash,
            account_state_after_hash=base.account_state_after_hash,
        )

    # Negative valuation_price
    with pytest.raises(ValueError, match="positive finite Decimal"):
        DeferredTransitionRecord(
            transition_id=base.transition_id,
            round_id=base.round_id,
            policy_id=base.policy_id,
            settlement_outcome_id=base.settlement_outcome_id,
            economic_fill_time=base.economic_fill_time,
            effective_time=base.effective_time,
            resource_deltas=(ResourceDelta("BTC", Decimal("1"), Decimal("-10.0")),),
            costs=base.costs,
            total_cost_reference_unit=base.total_cost_reference_unit,
            account_state_before_hash=base.account_state_before_hash,
            account_state_after_hash=base.account_state_after_hash,
        )

    # Negative cost
    with pytest.raises(ValueError, match="non-negative finite Decimal"):
        DeferredTransitionRecord(
            transition_id=base.transition_id,
            round_id=base.round_id,
            policy_id=base.policy_id,
            settlement_outcome_id=base.settlement_outcome_id,
            economic_fill_time=base.economic_fill_time,
            effective_time=base.effective_time,
            resource_deltas=base.resource_deltas,
            costs=(CostItem(CostType.TRANSACTION_FEE, "USDT", Decimal("-1.00")),),
            total_cost_reference_unit=base.total_cost_reference_unit,
            account_state_before_hash=base.account_state_before_hash,
            account_state_after_hash=base.account_state_after_hash,
        )

    # Negative total cost
    with pytest.raises(ValueError, match="non-negative finite Decimal"):
        DeferredTransitionRecord(
            transition_id=base.transition_id,
            round_id=base.round_id,
            policy_id=base.policy_id,
            settlement_outcome_id=base.settlement_outcome_id,
            economic_fill_time=base.economic_fill_time,
            effective_time=base.effective_time,
            resource_deltas=base.resource_deltas,
            costs=base.costs,
            total_cost_reference_unit=Decimal("-5.00"),
            account_state_before_hash=base.account_state_before_hash,
            account_state_after_hash=base.account_state_after_hash,
        )


def test_resource_deltas_non_empty():
    base = _make_valid_record()
    with pytest.raises(ValueError, match="at least one item"):
        DeferredTransitionRecord(
            transition_id=base.transition_id,
            round_id=base.round_id,
            policy_id=base.policy_id,
            settlement_outcome_id=base.settlement_outcome_id,
            economic_fill_time=base.economic_fill_time,
            effective_time=base.effective_time,
            resource_deltas=(),
            costs=base.costs,
            total_cost_reference_unit=base.total_cost_reference_unit,
            account_state_before_hash=base.account_state_before_hash,
            account_state_after_hash=base.account_state_after_hash,
        )


def test_account_hashes_validation():
    base = _make_valid_record()
    for bad_hash in ["invalid_hash", "md5:abcdef", "sha256:1234"]:
        with pytest.raises(ValueError):
            DeferredTransitionRecord(
                transition_id=base.transition_id,
                round_id=base.round_id,
                policy_id=base.policy_id,
                settlement_outcome_id=base.settlement_outcome_id,
                economic_fill_time=base.economic_fill_time,
                effective_time=base.effective_time,
                resource_deltas=base.resource_deltas,
                costs=base.costs,
                total_cost_reference_unit=base.total_cost_reference_unit,
                account_state_before_hash=bad_hash,
                account_state_after_hash=base.account_state_after_hash,
            )


def test_unknown_fields_rejected():
    base = _make_valid_record().to_dict()
    base["extra_field"] = "unknown"
    with pytest.raises(ValueError, match="do not match schema v2"):
        DeferredTransitionRecord.from_dict(base)


def test_deep_immutability():
    record = _make_valid_record()
    with pytest.raises((AttributeError, TypeError)):
        record.resource_deltas = ()  # type: ignore
    with pytest.raises((AttributeError, TypeError)):
        record.costs = ()  # type: ignore
    with pytest.raises((AttributeError, TypeError)):
        record.settlement_outcome_id = "set-out_other"  # type: ignore


def test_hash_determinism_and_semantic_sensitivity():
    record = _make_valid_record()
    h1 = record.compute_hash()
    h2 = record.compute_hash()
    assert h1 == h2

    # Semantic mutation: slight change in quantity changes hash
    mutated = DeferredTransitionRecord(
        transition_id=record.transition_id,
        round_id=record.round_id,
        policy_id=record.policy_id,
        settlement_outcome_id=record.settlement_outcome_id,
        economic_fill_time=record.economic_fill_time,
        effective_time=record.effective_time,
        resource_deltas=(
            ResourceDelta("USDT", Decimal("-60060.00"), Decimal("1.00")),
            ResourceDelta("BTC", Decimal("1.00000001"), Decimal("60000.00")),
        ),
        costs=record.costs,
        total_cost_reference_unit=record.total_cost_reference_unit,
        account_state_before_hash=record.account_state_before_hash,
        account_state_after_hash=record.account_state_after_hash,
    )
    assert mutated.compute_hash() != h1


def test_v1_transition_compatibility_and_immutability():
    validate_data = _load_validator()
    with open(SCHEMA_V1_PATH, "r", encoding="utf-8") as f:
        schema_v1 = json.load(f)
    with open(EXAMPLE_V1_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Assert legacy example transition validates under schema v1
    v1_trn = data["transition"]
    errs = validate_data(v1_trn, schema_v1)
    assert not errs, f"Legacy v1 transition failed schema v1: {errs}"

    # Assert v1 TransitionRecord produces exact match
    rec_v1 = TransitionRecord(
        transition_id=v1_trn["transition_id"],
        round_id=v1_trn["round_id"],
        policy_id=v1_trn["policy_id"],
        outcome_id=v1_trn["outcome_id"],
        effective_time=v1_trn["effective_time"],
        resource_deltas=tuple(
            ResourceDelta(
                d["resource_id"],
                Decimal(d["delta_quantity"]),
                Decimal(d["valuation_price"]),
            )
            for d in v1_trn["resource_deltas"]
        ),
        costs=tuple(
            CostItem(
                CostType(c["cost_type"]),
                c["resource_id"],
                Decimal(c["amount"]),
            )
            for c in v1_trn["costs"]
        ),
        total_cost_reference_unit=Decimal(v1_trn["total_cost_reference_unit"]),
        account_state_before_hash=v1_trn["account_state_before_hash"],
        account_state_after_hash=v1_trn["account_state_after_hash"],
    )
    assert rec_v1.to_dict() == v1_trn
    assert rec_v1.outcome_id == "dec-out_round0_reactive_accepted"
