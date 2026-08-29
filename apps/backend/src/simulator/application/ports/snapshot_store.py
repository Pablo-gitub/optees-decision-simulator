"""Application port defining immutable snapshot store operations and packages."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from simulator.domain.models import AcquisitionReceipt


@dataclass(frozen=True)
class StoredAcquisitionPackage:
    """Domain-neutral immutable package holding verified evidence and raw/normalized bytes.

    Contains zero filesystem or local path representations.
    """

    receipt: AcquisitionReceipt
    raw_bytes: bytes
    normalized_bytes: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, AcquisitionReceipt):
            raise TypeError("receipt must be an instance of AcquisitionReceipt")
        if not isinstance(self.raw_bytes, (bytes, bytearray)):
            raise TypeError("raw_bytes must be bytes")
        if not isinstance(self.normalized_bytes, (bytes, bytearray)):
            raise TypeError("normalized_bytes must be bytes")
        if len(self.raw_bytes) == 0:
            raise ValueError("raw_bytes cannot be empty")
        if len(self.normalized_bytes) == 0:
            raise ValueError("normalized_bytes cannot be empty")


class SnapshotStorePort(ABC):
    """Port for storing, verifying, and reopening immutable dataset acquisition packages."""

    @abstractmethod
    def store(self, package: StoredAcquisitionPackage) -> None:
        """Store an accepted acquisition package atomically under its immutable version identity.

        If an acquisition package with identical identity and content already exists,
        the operation succeeds idempotently without overwriting existing files.
        If an acquisition already exists with different content/hashes, raises SnapshotStoreError.
        """
        raise NotImplementedError

    @abstractmethod
    def load(self, acquisition_id: str, snapshot_id: str) -> StoredAcquisitionPackage:
        """Reopen and re-verify an existing stored acquisition package.

        Verifies all checksums and receipt bindings before returning the immutable package.
        """
        raise NotImplementedError

    @abstractmethod
    def exists(self, acquisition_id: str, snapshot_id: str) -> bool:
        """Check if a verified acquisition package is published and present."""
        raise NotImplementedError

    @abstractmethod
    def list_acquisitions(self, snapshot_id: str | None = None) -> tuple[str, ...]:
        """Return a sorted tuple of all published acquisition IDs, optionally by snapshot_id."""
        raise NotImplementedError

    @abstractmethod
    def prune(
        self,
        max_retained: int,
        protected_acquisition_ids: tuple[str, ...] = (),
    ) -> int:
        """Deterministically prune oldest acquisitions beyond max_retained, excluding protected IDs.

        Returns the number of pruned acquisitions.
        """
        raise NotImplementedError
