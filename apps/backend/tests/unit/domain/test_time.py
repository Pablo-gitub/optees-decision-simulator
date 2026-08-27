"""Unit tests for time semantics and knowledge eligibility."""

from datetime import datetime, timezone

import pytest

from simulator.domain.errors import InvalidTimestampError
from simulator.domain.time import (
    format_utc_timestamp,
    is_knowledge_eligible,
    parse_utc_timestamp,
)


def test_parse_valid_utc_timestamp() -> None:
    dt = parse_utc_timestamp("2026-08-01T00:00:00Z")
    assert dt.year == 2026
    assert dt.month == 8
    assert dt.day == 1
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0


def test_parse_valid_utc_timestamp_with_microseconds() -> None:
    dt = parse_utc_timestamp("2026-08-01T00:00:00.123456Z")
    assert dt.microsecond == 123456


def test_reject_ambiguous_and_naive_timestamps() -> None:
    with pytest.raises(InvalidTimestampError):
        parse_utc_timestamp("2026-08-01T02:00:00+02:00")
    with pytest.raises(InvalidTimestampError):
        parse_utc_timestamp("2026-08-01 00:00:00")
    with pytest.raises(InvalidTimestampError):
        parse_utc_timestamp("2026-08-01T00:00:00")
    with pytest.raises(InvalidTimestampError):
        parse_utc_timestamp("not-a-timestamp")


def test_format_utc_timestamp() -> None:
    dt = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert format_utc_timestamp(dt) == "2026-08-01T00:00:00Z"

    dt_micro = datetime(2026, 8, 1, 0, 0, 0, 500000, tzinfo=timezone.utc)
    assert format_utc_timestamp(dt_micro) == "2026-08-01T00:00:00.500000Z"


def test_is_knowledge_eligible() -> None:
    cutoff = "2026-08-01T00:00:00Z"
    assert is_knowledge_eligible("2026-07-31T12:00:00Z", cutoff) is True
    assert is_knowledge_eligible("2026-08-01T00:00:00Z", cutoff) is True
    assert is_knowledge_eligible("2026-08-01T00:00:01Z", cutoff) is False
    assert is_knowledge_eligible("2026-08-02T00:00:00Z", cutoff) is False
