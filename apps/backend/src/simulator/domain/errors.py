"""Domain exceptions and stable machine-readable error codes."""

from __future__ import annotations


class SimulatorError(Exception):
    """Base exception for all simulator domain errors."""

    def __init__(self, message: str, code: str = "SIMULATOR_ERROR") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TemporalLeakageError(SimulatorError):
    """Raised when an observation or query violates the knowledge cutoff horizon."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="TEMPORAL_LEAKAGE")


class InvalidTimestampError(SimulatorError):
    """Raised when a timestamp is not strict UTC ISO 8601 / RFC 3339 with 'Z' suffix."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="AMBIGUOUS_TIMEZONE_FORMAT")


class DuplicateIdentityError(SimulatorError):
    """Raised when duplicate entity IDs are detected."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="DUPLICATE_IDENTITY_COLLISION")


class FrozenRecordMutationError(SimulatorError):
    """Raised when an attempt is made to mutate a frozen or committed record."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="MUTATION_OF_FROZEN_RECORD")


class NonFiniteNumberError(SimulatorError):
    """Raised when NaN, Infinity, or -Infinity is encountered in numbers."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="NON_FINITE_NUMBER_VALUE")


class CrossPolicyContaminationError(SimulatorError):
    """Raised when a policy attempts to reference or mutate another policy's account/state."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="CROSS_POLICY_ACCOUNT_CONTAMINATION")


class InvalidLifecycleTransitionError(SimulatorError):
    """Raised when an illegal episode lifecycle state transition is attempted."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="INVALID_LIFECYCLE_TRANSITION")


class InvariantViolationError(SimulatorError):
    """Raised when a core domain invariant is violated."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="INVARIANT_VIOLATION")


class InsufficientResourceError(SimulatorError):
    """Raised when an account lacks sufficient unallocated balance and borrowing is disabled."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="INSUFFICIENT_UNALLOCATED_RESOURCE")


class ResourceNotFoundError(SimulatorError):
    """Raised when a requested resource is not recognized."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="RESOURCE_NOT_FOUND")


class InvalidProposalError(SimulatorError):
    """Raised when a proposed decision is structurally or semantically invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="INVALID_PROPOSAL")


class ReplayDivergenceError(SimulatorError):
    """Raised when a replay run detects unexpected divergence from original records."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="REPLAY_DIVERGENCE")


class ArchiveDecodingError(SimulatorError):
    """Raised when raw archive decoding, decompression, or CSV validation fails."""

    def __init__(self, message: str, code: str = "ARCHIVE_DECODING_ERROR") -> None:
        super().__init__(message, code=code)


class SnapshotStoreError(SimulatorError):
    """Raised when snapshot storage, retrieval, or integrity verification fails."""

    def __init__(self, message: str, code: str = "SNAPSHOT_STORE_ERROR") -> None:
        super().__init__(message, code=code)
