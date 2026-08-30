"""Application port defining pricing value objects, evidence records, and interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from simulator.domain.models import ObservationRecord, RejectionReason
from simulator.domain.time import parse_utc_timestamp


@dataclass(frozen=True)
class PriceEvidence:
    """Immutable evidence record for a resolved valuation mark or execution price."""

    resource_id: str
    price: Decimal
    observation_id: str | None
    event_time: str | None
    knowledge_time: str | None
    revision: int | None
    staleness_seconds: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.resource_id, str) or not self.resource_id:
            raise ValueError("resource_id must be a non-empty string")
        if not isinstance(self.price, Decimal) or self.price.is_nan() or self.price.is_infinite():
            raise ValueError("price must be a finite Decimal")
        if self.price <= Decimal("0"):
            raise ValueError(f"price must be strictly positive, got {self.price}")
        if not isinstance(self.staleness_seconds, Decimal) or self.staleness_seconds < Decimal("0"):
            raise ValueError("staleness_seconds must be a non-negative Decimal")
        if self.event_time is not None:
            parse_utc_timestamp(self.event_time)
        if self.knowledge_time is not None:
            parse_utc_timestamp(self.knowledge_time)
        if self.revision is not None and self.revision < 1:
            raise ValueError("revision must be >= 1")


@dataclass(frozen=True)
class PriceResolutionResult:
    """Immutable result of price resolution containing valuation marks and execution prices."""

    valuation_marks: Mapping[str, PriceEvidence]
    execution_prices: Mapping[str, PriceEvidence]
    rejection_reasons: tuple[RejectionReason, ...] = ()

    @property
    def is_valid(self) -> bool:
        """True if pricing was resolved successfully with zero rejection reasons."""
        return len(self.rejection_reasons) == 0


class PricingPort(ABC):
    """Abstract port for resolving valuation marks and execution prices."""

    @abstractmethod
    def resolve_pricing(
        self,
        all_observations: tuple[ObservationRecord, ...],
        knowledge_cutoff: str,
        effective_time: str,
        required_resources: tuple[str, ...],
        reference_resource_id: str,
    ) -> PriceResolutionResult:
        """Resolve valuation marks at cutoff and execution prices for required resources."""
        raise NotImplementedError
