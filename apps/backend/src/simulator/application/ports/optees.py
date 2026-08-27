"""OpteesClientPort interface placeholder for external solver invocation."""

from abc import ABC, abstractmethod
from typing import Any

from simulator.domain.models import OpteesCallReceipt


class OpteesClientPort(ABC):
    """Port for communicating with Optees solvers and validators.

    Not invoked during Phase DS-01 (deterministic kernel).
    """

    @abstractmethod
    def execute_capability(
        self,
        capability_id: str,
        problem_payload: dict[str, Any],
        round_id: str,
        policy_id: str,
    ) -> OpteesCallReceipt:
        raise NotImplementedError
