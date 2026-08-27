"""Deterministic in-memory ClockPort adapter."""

from simulator.application.ports.clock import ClockPort
from simulator.domain.time import parse_utc_timestamp


class InMemoryClock(ClockPort):
    """Clock with manual UTC timestamp progression for deterministic testing."""

    def __init__(
        self,
        initial_time: str = "2026-08-01T00:00:00Z",
        monotonic_time: float = 0.0,
    ) -> None:
        parse_utc_timestamp(initial_time)
        self._current_time = initial_time
        self._monotonic_time = float(monotonic_time)

    def now_utc(self) -> str:
        return self._current_time

    def monotonic_seconds(self) -> float:
        return self._monotonic_time

    def advance_to(self, timestamp: str) -> None:
        parse_utc_timestamp(timestamp)
        self._current_time = timestamp

    def advance_monotonic(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("monotonic clock cannot move backwards")
        self._monotonic_time += float(seconds)
