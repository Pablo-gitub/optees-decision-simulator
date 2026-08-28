"""Unit and contract tests for the market kline normalizer (DS-02B / Gate DS-D1)."""

from __future__ import annotations

import importlib.util
import json
import random
from decimal import Decimal
from pathlib import Path

import pytest

from simulator.application.services.eligibility import EligibilityService
from simulator.domain.errors import (
    DuplicateIdentityError,
    InvalidTimestampError,
    NonFiniteNumberError,
    SimulatorError,
)
from simulator.infrastructure.adapters.market_normalizer import (
    ALLOWED_MARKET_SYMBOLS,
    RawKlineRecord,
    build_market_snapshot_manifest,
    compute_normalized_snapshot_hash,
    normalize_kline_records,
    normalize_single_kline,
)

try:
    from tests.fixtures.synthetic_market_fixtures import (
        create_missing_day_series,
        create_reversal_series,
        create_stable_series,
        create_structural_break_series,
        create_trend_series,
        create_volatile_series,
        make_kline_ms,
        make_kline_us,
    )
except ImportError:
    from apps.backend.tests.fixtures.synthetic_market_fixtures import (
        create_missing_day_series,
        create_reversal_series,
        create_stable_series,
        create_structural_break_series,
        create_trend_series,
        create_volatile_series,
        make_kline_ms,
        make_kline_us,
    )

REPO_ROOT = Path(__file__).resolve().parents[5]
SCHEMAS_DIR = REPO_ROOT / "docs" / "contracts" / "schemas"

# Dynamically import validate_data from tools/validate_contracts.py to avoid schema duplication
validator_path = REPO_ROOT / "tools" / "validate_contracts.py"
spec = importlib.util.spec_from_file_location("validate_contracts", str(validator_path))
validate_contracts = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(validate_contracts)  # type: ignore[union-attr]
validate_data = validate_contracts.validate_data


def _load_schema(schema_filename: str) -> dict:
    schema_path = SCHEMAS_DIR / schema_filename
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_stable_fixture_normalization() -> None:
    raw_records = create_stable_series("BTCUSDT", length=5)
    observations = normalize_kline_records(raw_records, snapshot_id="ds-snap_stable_v1")

    assert len(observations) == 5
    for i, obs in enumerate(observations):
        assert obs.snapshot_id == "ds-snap_stable_v1"
        assert obs.series_id == "BTC_USDT_PRICE_1D"
        assert obs.revision == 1
        assert obs.payload["close"] == "40000.00"
        assert obs.payload["open"] == "40000.00"
        assert obs.payload["high"] == "40500.00"
        assert obs.payload["low"] == "39500.00"
        assert obs.payload["volume"] == "100.00"
        assert obs.payload["trade_count"] == 1500

        # Knowledge time must be D+2
        expected_k_day = i + 3  # Start is 2024-01-01 (day 1), D+2 is 2024-01-03
        assert obs.knowledge_time == f"2024-01-{expected_k_day:02d}T00:00:00Z"


def test_trend_fixture_normalization() -> None:
    raw_records = create_trend_series("ETHUSDT", length=4)
    observations = normalize_kline_records(raw_records, snapshot_id="ds-snap_trend_v1")

    assert len(observations) == 4
    closes = [Decimal(obs.payload["close"]) for obs in observations]
    assert closes == sorted(closes)
    assert len(set(closes)) == 4


def test_reversal_fixture_normalization() -> None:
    raw_records = create_reversal_series("BTCUSDT")
    observations = normalize_kline_records(raw_records, snapshot_id="ds-snap_reversal_v1")

    assert len(observations) == 5
    closes = [Decimal(obs.payload["close"]) for obs in observations]
    # Peak on day index 2, followed by sharp drop
    assert closes[2] > closes[0]
    assert closes[2] > closes[4]
    assert closes[4] < closes[3]


def test_volatile_fixture_normalization() -> None:
    raw_records = create_volatile_series("SOLUSDT")
    observations = normalize_kline_records(raw_records, snapshot_id="ds-snap_volatile_v1")

    assert len(observations) == 5
    for obs in observations:
        assert obs.series_id == "SOL_USDT_PRICE_1D"
        high = Decimal(obs.payload["high"])
        low = Decimal(obs.payload["low"])
        # High intraday spread >= 25 USD
        assert high - low >= Decimal("25.00")


def test_missing_day_fixture_preservation() -> None:
    raw_records = create_missing_day_series("ETHUSDT")  # Days 0, 2, 3 (day 1 missing)
    observations = normalize_kline_records(raw_records, snapshot_id="ds-snap_missing_day_v1")

    assert len(observations) == 3
    event_times = [obs.event_time for obs in observations]
    assert event_times == [
        "2024-01-01T23:59:59.999Z",
        "2024-01-03T23:59:59.999Z",
        "2024-01-04T23:59:59.999Z",
    ]
    # Day 2 is missing from output without forward-filling or hallucinating
    assert "2024-01-02T23:59:59.999Z" not in event_times


def test_structural_break_fixture_normalization() -> None:
    raw_records = create_structural_break_series("BTCUSDT")
    observations = normalize_kline_records(raw_records, snapshot_id="ds-snap_struct_break_v1")

    assert len(observations) == 4
    # Day 2 volume surge and -40% price drop
    assert Decimal(observations[2].payload["close"]) < Decimal("31000.00")
    assert Decimal(observations[2].payload["volume"]) == Decimal("1500.00")
    assert observations[2].payload["trade_count"] == 25000


def test_timestamp_ms_us_2024_2025_boundary() -> None:
    # 1. 2024-12-31 bar in milliseconds
    # 2024-12-31T00:00:00.000Z = 1735603200000 ms
    # 2024-12-31T23:59:59.999Z = 1735689599999 ms
    rec_2024 = RawKlineRecord(
        symbol="BTCUSDT",
        open_time=1_735_603_200_000,
        open="45000.00",
        high="46000.00",
        low="44500.00",
        close="45800.00",
        volume="200.00",
        close_time=1_735_689_599_999,
        quote_volume="9160000.00",
        count=3500,
        taker_buy_volume="100.00",
        taker_buy_quote_volume="4580000.00",
    )
    obs_2024 = normalize_single_kline(rec_2024, snapshot_id="ds-snap_boundary_v1", revision=1)
    assert obs_2024.event_time == "2024-12-31T23:59:59.999Z"
    assert obs_2024.knowledge_time == "2025-01-02T00:00:00Z"  # D+2

    # 2. 2025-01-01 bar in microseconds
    # 2025-01-01T00:00:00.000000Z = 1735689600000000 us
    # 2025-01-01T23:59:59.999999Z = 1735775999999999 us
    rec_2025 = RawKlineRecord(
        symbol="BTCUSDT",
        open_time=1_735_689_600_000_000,
        open="45800.00",
        high="47000.00",
        low="45500.00",
        close="46500.00",
        volume="250.00",
        close_time=1_735_775_999_999_999,
        quote_volume="11625000.00",
        count=4000,
        taker_buy_volume="130.00",
        taker_buy_quote_volume="6045000.00",
    )
    obs_2025 = normalize_single_kline(rec_2025, snapshot_id="ds-snap_boundary_v1", revision=1)
    assert obs_2025.event_time == "2025-01-01T23:59:59.999999Z"
    assert obs_2025.knowledge_time == "2025-01-03T00:00:00Z"  # D+2

    # 3. 2025 timestamp erroneously passed in milliseconds -> REJECTED
    rec_2025_invalid_ms = RawKlineRecord(
        symbol="BTCUSDT",
        open_time=1_735_689_600_000,  # 2025-01-01 in ms
        open="45800.00",
        high="47000.00",
        low="45500.00",
        close="46500.00",
        volume="250.00",
        close_time=1_735_775_999_999,
        quote_volume="11625000.00",
        count=4000,
        taker_buy_volume="130.00",
        taker_buy_quote_volume="6045000.00",
    )
    with pytest.raises(InvalidTimestampError):
        normalize_single_kline(rec_2025_invalid_ms, snapshot_id="ds-snap_boundary_v1")


def test_subsecond_precision_preservation() -> None:
    kline_ms = make_kline_ms("BNBUSDT", 0, "300.00", "310.00", "295.00", "305.00")
    obs_ms = normalize_single_kline(kline_ms, snapshot_id="ds-snap_subsecond_v1")
    assert obs_ms.event_time.endswith(".999Z")

    kline_us = make_kline_us("BNBUSDT", 0, "300.00", "310.00", "295.00", "305.00")
    obs_us = normalize_single_kline(kline_us, snapshot_id="ds-snap_subsecond_v1")
    assert obs_us.event_time.endswith(".999999Z")


def test_eligibility_d_plus_1_ineligible_and_d_plus_2_eligible() -> None:
    # 2024-01-01 bar
    kline = make_kline_ms("BTCUSDT", 0, "40000.00", "41000.00", "39000.00", "40500.00")
    obs = normalize_single_kline(kline, snapshot_id="ds-snap_eligibility_v1")

    assert obs.event_time == "2024-01-01T23:59:59.999Z"
    assert obs.knowledge_time == "2024-01-03T00:00:00Z"  # D+2

    # At Round 1 (Cutoff D+1 = 2024-01-02T00:00:00Z): NOT eligible
    cutoff_d1 = "2024-01-02T00:00:00Z"
    eligible_d1 = EligibilityService.get_eligible_observations((obs,), cutoff_d1)
    assert len(eligible_d1) == 0

    # At Round 2 (Cutoff D+2 = 2024-01-03T00:00:00Z): IS eligible
    cutoff_d2 = "2024-01-03T00:00:00Z"
    eligible_d2 = EligibilityService.get_eligible_observations((obs,), cutoff_d2)
    assert len(eligible_d2) == 1
    assert eligible_d2[0].observation_id == obs.observation_id


def test_zero_volume_valid_zero_and_negative_price_invalid() -> None:
    # Zero volume is valid
    valid_zero_vol = make_kline_ms(
        "BTCUSDT",
        0,
        "40000.00",
        "40000.00",
        "40000.00",
        "40000.00",
        volume="0.00",
        quote_volume="0.00",
        count=0,
        taker_v="0.00",
        taker_qv="0.00",
    )
    obs = normalize_single_kline(valid_zero_vol, snapshot_id="ds-snap_zero_v1")
    assert obs.payload["volume"] == "0" or obs.payload["volume"] == "0.00"
    assert obs.payload["trade_count"] == 0

    # Zero price is invalid
    invalid_zero_price = make_kline_ms(
        "BTCUSDT",
        0,
        "0.00",
        "40000.00",
        "0.00",
        "40000.00",
    )
    with pytest.raises(ValueError, match="strictly positive"):
        normalize_single_kline(invalid_zero_price, snapshot_id="ds-snap_zero_v1")

    # Negative price is invalid
    invalid_neg_price = make_kline_ms(
        "BTCUSDT",
        0,
        "-40000.00",
        "40000.00",
        "-40000.00",
        "40000.00",
    )
    with pytest.raises(ValueError, match="strictly positive"):
        normalize_single_kline(invalid_neg_price, snapshot_id="ds-snap_zero_v1")

    # Negative volume is invalid
    invalid_neg_vol = make_kline_ms(
        "BTCUSDT",
        0,
        "40000.00",
        "41000.00",
        "39000.00",
        "40500.00",
        volume="-10.00",
    )
    with pytest.raises(ValueError, match="non-negative"):
        normalize_single_kline(invalid_neg_vol, snapshot_id="ds-snap_zero_v1")


def test_invalid_numbers_and_inconsistent_ohlc_rejection() -> None:
    # High < Open
    rec_high_low = make_kline_ms("BTCUSDT", 0, "42000.00", "41000.00", "39000.00", "40000.00")
    with pytest.raises(ValueError, match="High price"):
        normalize_single_kline(rec_high_low, snapshot_id="ds-snap_inv_v1")

    # Low > Close
    rec_low_close = make_kline_ms("BTCUSDT", 0, "42000.00", "43000.00", "41000.00", "40000.00")
    with pytest.raises(ValueError, match="Low price"):
        normalize_single_kline(rec_low_close, snapshot_id="ds-snap_inv_v1")

    # Boolean passed for price
    rec_bool = make_kline_ms("BTCUSDT", 0, True, "43000.00", "39000.00", "40000.00")  # type: ignore
    with pytest.raises(NonFiniteNumberError):
        normalize_single_kline(rec_bool, snapshot_id="ds-snap_inv_v1")

    # NaN float passed for price
    rec_nan = make_kline_ms("BTCUSDT", 0, float("nan"), "43000.00", "39000.00", "40000.00")
    with pytest.raises(NonFiniteNumberError):
        normalize_single_kline(rec_nan, snapshot_id="ds-snap_inv_v1")

    rec_exponent = make_kline_ms("BTCUSDT", 0, "4e4", "43000.00", "39000.00", "40000.00")
    with pytest.raises(ValueError, match="without an exponent"):
        normalize_single_kline(rec_exponent, snapshot_id="ds-snap_inv_v1")


def test_unsupported_symbol_or_interval_rejection() -> None:
    # Unsupported symbol
    rec_sym = make_kline_ms("XRPUSDT", 0, "0.50", "0.60", "0.45", "0.55")
    with pytest.raises(SimulatorError, match="Unsupported market symbol"):
        normalize_single_kline(rec_sym, snapshot_id="ds-snap_sym_v1")

    # Unsupported interval
    rec_int = RawKlineRecord(
        symbol="BTCUSDT",
        open_time=1_704_067_200_000,
        open="40000.00",
        high="41000.00",
        low="39000.00",
        close="40500.00",
        volume="100.00",
        close_time=1_704_070_799_999,
        quote_volume="4050000.00",
        count=1000,
        taker_buy_volume="50.00",
        taker_buy_quote_volume="2025000.00",
        interval="1h",
    )
    with pytest.raises(SimulatorError, match="Unsupported interval"):
        normalize_single_kline(rec_int, snapshot_id="ds-snap_sym_v1")


def test_duplicate_identity_rejection() -> None:
    rec1 = make_kline_ms("BTCUSDT", 0, "40000.00", "41000.00", "39000.00", "40500.00")
    rec2 = make_kline_ms("BTCUSDT", 0, "40000.00", "41000.00", "39000.00", "40500.00")

    with pytest.raises(DuplicateIdentityError):
        normalize_kline_records([rec1, rec2], snapshot_id="ds-snap_dup_v1", revision=1)


def test_two_acquisitions_with_ordered_revisions() -> None:
    # Initial revision 1
    rec1 = make_kline_ms("BTCUSDT", 0, "40000.00", "41000.00", "39000.00", "40500.00")
    obs1 = normalize_single_kline(rec1, snapshot_id="ds-snap_rev_v1", revision=1)

    # Restated revision 2
    rec2 = make_kline_ms("BTCUSDT", 0, "40000.00", "41000.00", "39000.00", "40600.00")
    obs2 = normalize_single_kline(rec2, snapshot_id="ds-snap_rev_v1", revision=2)

    assert obs1.event_time == obs2.event_time
    assert obs1.revision == 1
    assert obs2.revision == 2
    assert obs1.observation_id != obs2.observation_id

    # Passing both to EligibilityService resolves to revision 2
    eligible = EligibilityService.get_eligible_observations((obs1, obs2), "2024-01-05T00:00:00Z")
    assert len(eligible) == 1
    assert eligible[0].revision == 2
    assert eligible[0].payload["close"] == "40600.00"


def test_corrected_content_produces_different_hash() -> None:
    rec_a = make_kline_ms("BTCUSDT", 0, "40000.00", "41000.00", "39000.00", "40500.00")
    rec_b = make_kline_ms("BTCUSDT", 0, "40000.00", "41000.00", "39000.00", "40500.01")

    obs_a = normalize_single_kline(rec_a, snapshot_id="ds-snap_hash_v1", revision=1)
    obs_b = normalize_single_kline(rec_b, snapshot_id="ds-snap_hash_v1", revision=1)

    assert obs_a.compute_hash() != obs_b.compute_hash()

    hash_a = compute_normalized_snapshot_hash([obs_a])
    hash_b = compute_normalized_snapshot_hash([obs_b])
    assert hash_a != hash_b


def test_input_permutations_yield_deterministic_ordering_and_hash() -> None:
    # 3 symbols over 3 days
    raw_list: list[RawKlineRecord] = []
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        for day in range(3):
            raw_list.append(make_kline_ms(sym, day, "100.00", "110.00", "90.00", "105.00"))

    # Normalize canonical baseline
    obs_base = normalize_kline_records(raw_list, snapshot_id="ds-snap_perm_v1")
    hash_base = compute_normalized_snapshot_hash(obs_base)

    # Test 5 randomized shuffles
    rng = random.Random(42)
    for _ in range(5):
        shuffled = list(raw_list)
        rng.shuffle(shuffled)
        obs_shuffled = normalize_kline_records(shuffled, snapshot_id="ds-snap_perm_v1")
        hash_shuffled = compute_normalized_snapshot_hash(obs_shuffled)

        assert obs_shuffled == obs_base
        assert hash_shuffled == hash_base

    assert compute_normalized_snapshot_hash(tuple(reversed(obs_base))) == hash_base


def test_repeated_executions_byte_for_byte_deterministic() -> None:
    raw_records = create_trend_series("BNBUSDT", length=5)
    first_obs = normalize_kline_records(raw_records, snapshot_id="ds-snap_repeat_v1")
    first_hash = compute_normalized_snapshot_hash(first_obs)

    for _ in range(5):
        obs = normalize_kline_records(raw_records, snapshot_id="ds-snap_repeat_v1")
        h = compute_normalized_snapshot_hash(obs)
        assert obs == first_obs
        assert h == first_hash


def test_manifest_builder_and_schema_roundtrip() -> None:
    schema_obs = _load_schema("observation.v1.json")
    schema_snap = _load_schema("dataset_snapshot.v1.json")

    # Generate records for all 4 allowed symbols
    all_raw: list[RawKlineRecord] = []
    for sym in ALLOWED_MARKET_SYMBOLS:
        all_raw.extend(create_stable_series(sym, length=3))

    observations = normalize_kline_records(all_raw, snapshot_id="ds-snap_binance_market_v1")

    # Validate each observation against observation.v1.json
    for obs in observations:
        errs = validate_data(obs.to_dict(), schema_obs, path=obs.observation_id)
        assert not errs, f"Observation {obs.observation_id} schema errors: {errs}"

    # Build and validate manifest
    manifest = build_market_snapshot_manifest(
        observations,
        snapshot_id="ds-snap_binance_market_v1",
        source_uri="https://data.binance.vision/data/spot/daily/klines/",
        retrieval_time="2026-08-28T00:00:00Z",
    )

    manifest_dict = manifest.to_dict()
    snap_errs = validate_data(manifest_dict, schema_snap, path=manifest.snapshot_id)
    assert not snap_errs, f"Manifest schema errors: {snap_errs}"

    assert manifest.byte_size > 0
    assert manifest.checksum_sha256.startswith("sha256:")
    assert len(manifest.series_catalog) == 4

    reversed_manifest = build_market_snapshot_manifest(
        tuple(reversed(observations)),
        snapshot_id="ds-snap_binance_market_v1",
        source_uri="https://data.binance.vision/data/spot/daily/klines/",
        retrieval_time="2026-08-28T00:00:00Z",
    )
    assert reversed_manifest.checksum_sha256 == manifest.checksum_sha256

    with pytest.raises(ValueError, match="manifest snapshot_id"):
        build_market_snapshot_manifest(
            observations,
            snapshot_id="ds-snap_different_v1",
            retrieval_time="2026-08-28T00:00:00Z",
        )
