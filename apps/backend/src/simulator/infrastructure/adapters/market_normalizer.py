"""Pure market kline normalizer compiling raw kline records into canonical domain models."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from simulator.domain.canonical import (
    canonicalize_json,
    format_decimal,
)
from simulator.domain.errors import (
    DuplicateIdentityError,
    InvalidTimestampError,
    NonFiniteNumberError,
    SimulatorError,
)
from simulator.domain.models import (
    DatasetSnapshotManifest,
    ObservationRecord,
    SeriesCatalogItem,
)
from simulator.domain.time import parse_utc_timestamp

# Allowed Spot Market Symbols and their canonical mapping (series_id, resource_id, quote_unit)
ALLOWED_MARKET_SYMBOLS: dict[str, tuple[str, str, str]] = {
    "BTCUSDT": ("BTC_USDT_PRICE_1D", "BTC", "USDT"),
    "ETHUSDT": ("ETH_USDT_PRICE_1D", "ETH", "USDT"),
    "SOLUSDT": ("SOL_USDT_PRICE_1D", "SOL", "USDT"),
    "BNBUSDT": ("BNB_USDT_PRICE_1D", "BNB", "USDT"),
}

# Timestamp Boundary Constants:
# 2025-01-01T00:00:00.000Z in milliseconds Unix epoch: 1735689600000 (13 digits)
# 2025-01-01T00:00:00.000000Z in microseconds Unix epoch: 1735689600000000 (16 digits)
BOUNDARY_2025_MS = 1_735_689_600_000
BOUNDARY_2025_US = 1_735_689_600_000_000
ONE_DAY_MS = 86_400_000
ONE_DAY_US = 86_400_000_000


@dataclass(frozen=True)
class RawKlineRecord:
    """Narrow DTO representing a raw decoded 12-field Binance daily kline bar."""

    symbol: str
    open_time: int
    open: str
    high: str
    low: str
    close: str
    volume: str
    close_time: int
    quote_volume: str
    count: int
    taker_buy_volume: str
    taker_buy_quote_volume: str
    ignore: str = "0"
    interval: str = "1d"


def _format_subsecond_utc(dt: datetime, precision: int) -> str:
    """Format a UTC datetime preserving explicit subsecond precision without truncation."""
    utc_dt = dt.astimezone(timezone.utc)
    base = utc_dt.strftime("%Y-%m-%dT%H:%M:%S")
    if precision == 3:
        ms = utc_dt.microsecond // 1000
        return f"{base}.{ms:03d}Z"
    elif precision == 6:
        us = utc_dt.microsecond
        return f"{base}.{us:06d}Z"
    else:
        if utc_dt.microsecond > 0:
            return f"{base}.{utc_dt.microsecond:06d}Z"
        return f"{base}Z"


_PLAIN_DECIMAL = re.compile(r"^-?\d+(?:\.\d+)?$")


def _parse_decimal_field(name: str, value: Any, allow_zero: bool = False) -> Decimal:
    """Parse and validate a numeric field into a finite positive or non-negative Decimal."""
    if not isinstance(value, str):
        if isinstance(value, (bool, float, Decimal)):
            raise NonFiniteNumberError(
                f"Field {name} must preserve the upstream plain-decimal text, got {value!r}"
            )
        raise ValueError(f"Field {name} must be a decimal string, got {type(value).__name__}")
    value_str = value.strip()
    if not _PLAIN_DECIMAL.fullmatch(value_str):
        raise ValueError(
            f"Field {name} must use plain decimal notation without an exponent, got {value!r}"
        )

    try:
        dec = Decimal(value_str)
    except Exception as exc:
        raise ValueError(f"Field {name} is not a valid decimal representation: {value!r}") from exc

    if not dec.is_finite():
        raise NonFiniteNumberError(f"Field {name} resolved to non-finite Decimal: {dec}")

    if allow_zero:
        if dec < Decimal("0"):
            raise ValueError(f"Field {name} must be non-negative, got {dec}")
    else:
        if dec <= Decimal("0"):
            raise ValueError(f"Field {name} must be strictly positive (> 0), got {dec}")

    return dec


def normalize_single_kline(
    record: RawKlineRecord,
    snapshot_id: str,
    revision: int = 1,
) -> ObservationRecord:
    """Normalize a single raw kline record into an immutable ObservationRecord.

    Validates:
    - Symbol membership in allowed universe (BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT)
    - Interval is strictly '1d'
    - Timestamp millisecond vs microsecond rules and 2025-01-01 boundary
    - Positive OHLC prices and consistent high/low boundaries
    - Non-negative volumes and trade count
    - Calculation of event_time from close_time and knowledge_time to (D+2)T00:00:00Z
    """
    if record.symbol not in ALLOWED_MARKET_SYMBOLS:
        raise SimulatorError(
            f"Unsupported market symbol {record.symbol!r}. "
            f"Allowed symbols: {list(ALLOWED_MARKET_SYMBOLS.keys())}"
        )

    if record.interval != "1d":
        raise SimulatorError(
            f"Unsupported interval {record.interval!r}. Only '1d' interval is supported."
        )

    if revision < 1:
        raise ValueError(f"Observation revision must be >= 1, got {revision}")

    series_id, resource_id, _ = ALLOWED_MARKET_SYMBOLS[record.symbol]

    # Validate timestamps
    if isinstance(record.open_time, bool) or not isinstance(record.open_time, int):
        raise InvalidTimestampError(f"open_time must be an integer, got {type(record.open_time)}")
    if isinstance(record.close_time, bool) or not isinstance(record.close_time, int):
        raise InvalidTimestampError(f"close_time must be an integer, got {type(record.close_time)}")

    if record.open_time < 0 or record.close_time < 0:
        raise InvalidTimestampError("Timestamps cannot be negative")

    if record.open_time >= record.close_time:
        raise InvalidTimestampError(
            f"open_time ({record.open_time}) must be < close_time ({record.close_time})"
        )

    # Distinguish ms (< 2025-01-01) vs us (>= 2025-01-01)
    if record.open_time < BOUNDARY_2025_MS:
        # Pre-2025: millisecond precision
        duration = record.close_time - record.open_time
        if duration != ONE_DAY_MS - 1:
            raise InvalidTimestampError(
                f"1d millisecond kline duration must be exactly {ONE_DAY_MS - 1} ms, "
                f"got {duration} ms"
            )
        try:
            epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
            open_dt = epoch + timedelta(milliseconds=record.open_time)
            close_dt = epoch + timedelta(milliseconds=record.close_time)
        except (OverflowError, ValueError) as exc:
            raise InvalidTimestampError(f"Failed to parse millisecond timestamp: {exc}") from exc

        if open_dt >= datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc):
            raise InvalidTimestampError(
                "Timestamps from 2025-01-01 onwards must be in microseconds, not milliseconds"
            )
        event_time = _format_subsecond_utc(close_dt, precision=3)
        open_time = _format_subsecond_utc(open_dt, precision=3)

    elif record.open_time >= BOUNDARY_2025_US:
        # 2025+: microsecond precision
        duration = record.close_time - record.open_time
        if duration != ONE_DAY_US - 1:
            raise InvalidTimestampError(
                f"1d microsecond kline duration must be exactly {ONE_DAY_US - 1} us, "
                f"got {duration} us"
            )
        try:
            epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
            open_dt = epoch + timedelta(microseconds=record.open_time)
            close_dt = epoch + timedelta(microseconds=record.close_time)
        except (OverflowError, ValueError) as exc:
            raise InvalidTimestampError(f"Failed to parse microsecond timestamp: {exc}") from exc

        if open_dt < datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc):
            raise InvalidTimestampError(
                "Timestamps prior to 2025-01-01 must be in milliseconds, not microseconds"
            )
        event_time = _format_subsecond_utc(close_dt, precision=6)
        open_time = _format_subsecond_utc(open_dt, precision=6)

    else:
        # Ambiguous range (e.g. 2025+ date passed in milliseconds)
        raise InvalidTimestampError(
            f"Ambiguous or out-of-range timestamp {record.open_time}. "
            "Pre-2025 timestamps must be milliseconds (< 1735689600000); "
            "2025+ timestamps must be microseconds (>= 1735689600000000)."
        )

    # Assign historical knowledge_time to D+2 00:00:00Z
    event_date = open_dt.date()
    knowledge_date = event_date + timedelta(days=2)
    knowledge_time = f"{knowledge_date.isoformat()}T00:00:00Z"

    # Validate numeric fields
    open_dec = _parse_decimal_field("open", record.open, allow_zero=False)
    high_dec = _parse_decimal_field("high", record.high, allow_zero=False)
    low_dec = _parse_decimal_field("low", record.low, allow_zero=False)
    close_dec = _parse_decimal_field("close", record.close, allow_zero=False)

    # OHLC consistency
    if high_dec < open_dec or high_dec < close_dec or high_dec < low_dec:
        raise ValueError(
            f"High price ({high_dec}) must be >= open ({open_dec}), "
            f"close ({close_dec}), and low ({low_dec})"
        )
    if low_dec > open_dec or low_dec > close_dec or low_dec > high_dec:
        raise ValueError(
            f"Low price ({low_dec}) must be <= open ({open_dec}), "
            f"close ({close_dec}), and high ({high_dec})"
        )

    volume_dec = _parse_decimal_field("volume", record.volume, allow_zero=True)
    qvolume_dec = _parse_decimal_field("quote_volume", record.quote_volume, allow_zero=True)
    taker_v_dec = _parse_decimal_field("taker_buy_volume", record.taker_buy_volume, allow_zero=True)
    taker_qv_dec = _parse_decimal_field(
        "taker_buy_quote_volume", record.taker_buy_quote_volume, allow_zero=True
    )

    if isinstance(record.count, bool) or not isinstance(record.count, int):
        raise ValueError(f"count (trade count) must be an integer, got {type(record.count)}")
    if record.count < 0:
        raise ValueError(f"count (trade count) cannot be negative, got {record.count}")

    # Build observation_id: obs_{resource_id}_{YYYYMMDD}_r{revision}
    date_str = event_date.strftime("%Y%m%d")
    obs_id = f"obs_{resource_id}_{date_str}_r{revision}"

    payload: dict[str, Any] = {
        "open_time": open_time,
        "open": format_decimal(open_dec),
        "high": format_decimal(high_dec),
        "low": format_decimal(low_dec),
        "close": format_decimal(close_dec),
        "volume": format_decimal(volume_dec),
        "quote_volume": format_decimal(qvolume_dec),
        "trade_count": record.count,
        "taker_buy_base_volume": format_decimal(taker_v_dec),
        "taker_buy_quote_volume": format_decimal(taker_qv_dec),
    }

    return ObservationRecord(
        observation_id=obs_id,
        snapshot_id=snapshot_id,
        series_id=series_id,
        event_time=event_time,
        knowledge_time=knowledge_time,
        revision=revision,
        payload=payload,
    )


def normalize_kline_records(
    records: Sequence[RawKlineRecord],
    snapshot_id: str,
    revision: int = 1,
) -> tuple[ObservationRecord, ...]:
    """Normalize and deterministically sort a batch of raw kline records.

    Rules:
    - Normalizes each raw record with pure validation.
    - Enforces uniqueness: duplicate (series_id, event_time, revision) or observation_id
      raises DuplicateIdentityError.
    - Sorts the batch deterministically by (series_id, event_time, revision).
    - Preserves absent records (missing days) without hallucinating or forward-filling data.
    """
    if not snapshot_id or not snapshot_id.startswith("ds-snap_"):
        raise ValueError(f"snapshot_id must start with 'ds-snap_', got {snapshot_id!r}")

    normalized: list[ObservationRecord] = []
    seen_keys: set[tuple[str, str, int]] = set()
    seen_ids: set[str] = set()

    for idx, rec in enumerate(records):
        obs = normalize_single_kline(rec, snapshot_id=snapshot_id, revision=revision)
        key = (obs.series_id, obs.event_time, obs.revision)
        if key in seen_keys or obs.observation_id in seen_ids:
            raise DuplicateIdentityError(
                f"Duplicate observation identity detected at index {idx}: "
                f"observation_id={obs.observation_id}, key={key}"
            )
        seen_keys.add(key)
        seen_ids.add(obs.observation_id)
        normalized.append(obs)

    # Sort deterministically by (series_id, event_time, revision)
    def sort_key(item: ObservationRecord) -> tuple[str, str, int]:
        return (item.series_id, item.event_time, item.revision)

    normalized.sort(key=sort_key)
    return tuple(normalized)


def compute_normalized_snapshot_hash(observations: Sequence[ObservationRecord]) -> str:
    """Compute SHA-256 digest over the RFC 8785 canonical JSONL stream."""
    ordered = _ordered_unique_observations(observations)
    canonical_lines = [canonicalize_json(obs.to_dict()) for obs in ordered]
    stream_bytes = "\n".join(canonical_lines).encode("utf-8")
    digest = hashlib.sha256(stream_bytes).hexdigest()
    return f"sha256:{digest}"


DEFAULT_MARKET_LICENSE = "Upstream repository labelled MIT; raw archive redistribution not asserted"
DEFAULT_MARKET_CORRECTIONS = (
    "Upstream archives may be replaced; each acquisition and normalized revision "
    "is retained immutably"
)


def build_market_snapshot_manifest(
    observations: Sequence[ObservationRecord],
    snapshot_id: str,
    retrieval_time: str,
    source_uri: str = "https://data.binance.vision/data/spot/daily/klines/",
    license_str: str = DEFAULT_MARKET_LICENSE,
    correction_handling: str = DEFAULT_MARKET_CORRECTIONS,
) -> DatasetSnapshotManifest:
    """Construct an immutable DatasetSnapshotManifest from normalized observations."""
    if not observations:
        raise ValueError("Cannot build manifest from empty observation sequence")

    parse_utc_timestamp(retrieval_time)
    ordered = _ordered_unique_observations(observations)
    if any(observation.snapshot_id != snapshot_id for observation in ordered):
        raise ValueError("Every observation must reference the manifest snapshot_id")

    # Group earliest and latest event times per series
    series_catalog_map: dict[str, dict[str, str]] = {}
    for obs in ordered:
        s_id = obs.series_id
        if s_id not in series_catalog_map:
            # Look up resource_id from allowed symbols
            res_id = s_id.split("_")[0]
            series_catalog_map[s_id] = {
                "resource_id": res_id,
                "unit": "USDT",
                "frequency": "1d",
                "earliest_event_time": obs.event_time,
                "latest_event_time": obs.event_time,
            }
        else:
            cat = series_catalog_map[s_id]
            obs_dt = parse_utc_timestamp(obs.event_time)
            if obs_dt < parse_utc_timestamp(cat["earliest_event_time"]):
                cat["earliest_event_time"] = obs.event_time
            if obs_dt > parse_utc_timestamp(cat["latest_event_time"]):
                cat["latest_event_time"] = obs.event_time

    # Sort catalog by series_id
    catalog_items = tuple(
        SeriesCatalogItem(
            series_id=s_id,
            resource_id=data["resource_id"],
            unit=data["unit"],
            frequency=data["frequency"],
            earliest_event_time=data["earliest_event_time"],
            latest_event_time=data["latest_event_time"],
        )
        for s_id, data in sorted(series_catalog_map.items(), key=lambda x: x[0])
    )

    canonical_lines = [canonicalize_json(obs.to_dict()) for obs in ordered]
    stream_bytes = "\n".join(canonical_lines).encode("utf-8")
    byte_size = len(stream_bytes)
    checksum = f"sha256:{hashlib.sha256(stream_bytes).hexdigest()}"

    return DatasetSnapshotManifest(
        snapshot_id=snapshot_id,
        source_uri=source_uri,
        retrieval_time=retrieval_time,
        license=license_str,
        checksum_sha256=checksum,
        byte_size=byte_size,
        format="JSONL",
        series_catalog=catalog_items,
        correction_handling=correction_handling,
    )


def _ordered_unique_observations(
    observations: Sequence[ObservationRecord],
) -> tuple[ObservationRecord, ...]:
    ordered = tuple(
        sorted(
            observations,
            key=lambda item: (item.series_id, item.event_time, item.revision),
        )
    )
    seen: set[tuple[str, str, int]] = set()
    for observation in ordered:
        identity = (
            observation.series_id,
            observation.event_time,
            observation.revision,
        )
        if identity in seen:
            raise DuplicateIdentityError(f"Duplicate normalized observation identity: {identity}")
        seen.add(identity)
    return ordered
