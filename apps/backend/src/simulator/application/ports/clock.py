"""ClockPort interface for deterministic simulation time and wall-clock progression."""

from abc import ABC, abstractmethod


class ClockPort(ABC):
    """Port for wall-clock execution time and deterministic time progression."""

    @abstractmethod
    def now_utc(self) -> str:
        """Return current execution timestamp in strict UTC RFC 3339 format."""
        raise NotImplementedError

    @abstractmethod
    def advance_to(self, timestamp: str) -> None:
        """Advance the simulated clock to a target UTC timestamp."""
        raise NotImplementedError
