"""PolicyPort interface and context for executing isolated decision policies."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from simulator.domain.models import (
    ObservationRecord,
    ProposedDecision,
    VirtualAccountState,
)


@dataclass(frozen=True)
class PolicyContext:
    """Immutable context provided to a policy for a single decision round."""

    policy_id: str
    policy_version_id: str
    round_id: str
    round_index: int
    knowledge_cutoff: str
    account_state: VirtualAccountState
    eligible_observations: tuple[ObservationRecord, ...]
    hyperparameters: dict[str, Any]


class PolicyPort(ABC):
    """Port for executing a decision policy given an isolated round context."""

    @property
    @abstractmethod
    def policy_id(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def policy_version_id(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def propose_decision(self, context: PolicyContext) -> ProposedDecision:
        """Generate a proposed decision for the current round."""
        raise NotImplementedError
