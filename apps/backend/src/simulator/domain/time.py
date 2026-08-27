"""Strict UTC time semantics, interval checks, and deterministic tie-breaking."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from simulator.domain.errors import InvalidTimestampError

UTC_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def parse_utc_timestamp(value: str) -> datetime:
    """Parse a strict RFC 3339 / ISO 8601 UTC timestamp ending in 'Z'.

    Rejects naive datetimes, non-UTC offsets (e.g. +02:00), and invalid calendar dates.
    """
    if not isinstance(value, str) or not UTC_TIMESTAMP_PATTERN.match(value):
        raise InvalidTimestampError(
            f"Timestamp {value!r} must be strict RFC 3339 UTC format with uppercase 'Z'"
        )

    # Convert trailing 'Z' to '+00:00' for Python fromisoformat
    iso_str = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(iso_str)
    except ValueError as exc:
        raise InvalidTimestampError(f"Invalid date-time value {value!r}: {exc}") from exc

    if dt.utcoffset() is None or dt.utcoffset().total_seconds() != 0:
        raise InvalidTimestampError(f"Timestamp {value!r} is not normalized to UTC")

    return dt


def format_utc_timestamp(dt: datetime) -> str:
    """Format a datetime as a strict UTC string with 'Z' suffix."""
    if dt.tzinfo is None:
        raise InvalidTimestampError(f"Cannot format naive datetime {dt!r}")

    utc_dt = dt.astimezone(timezone.utc)
    if utc_dt.microsecond > 0:
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    else:
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def is_knowledge_eligible(
    observation_knowledge_time: str | datetime,
    cutoff_time: str | datetime,
) -> bool:
    """Check if observation knowledge time is <= round knowledge cutoff."""
    k_dt = (
        parse_utc_timestamp(observation_knowledge_time)
        if isinstance(observation_knowledge_time, str)
        else observation_knowledge_time
    )
    c_dt = parse_utc_timestamp(cutoff_time) if isinstance(cutoff_time, str) else cutoff_time
    return k_dt <= c_dt
