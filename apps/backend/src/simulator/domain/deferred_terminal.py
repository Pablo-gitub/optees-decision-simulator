"""Deferred run terminal record and Merkle hash computation (DS-02D2C1A).

Provides immutable domain models for final run termination and cancellation
under deferred settlement:
- `PolicyTerminalRecord`: captures policy terminal account hash and optional
  unsettled pending order + terminal rejection outcome.
- `DeferredRunTerminalRecord`: represents top-level immutable terminal record.
- `compute_terminal_record_id`: deterministic terminal record ID generator.
- `compute_terminal_state_merkle_hash`: Merkle root over policy terminal leaves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Sequence

from simulator.domain.canonical import compute_record_hash, compute_state_merkle_hash
from simulator.domain.errors import DuplicateIdentityError
from simulator.domain.time import parse_utc_timestamp

_TERMINAL_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^term_[a-zA-Z0-9_-]+$")
_RUN_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^ep-run_[a-zA-Z0-9_-]+$")
_EPISODE_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^ep-def_[a-zA-Z0-9_-]+$")
_POLICY_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^pol-def_[a-zA-Z0-9_-]+$")
_SHA256_HASH_PATTERN: Final[re.Pattern[str]] = re.compile(r"^sha256:[a-f0-9]{64}$")

_VALID_STATUSES: Final[frozenset[str]] = frozenset({"COMPLETED", "CANCELLED"})
_VALID_REASONS: Final[frozenset[str]] = frozenset(
    {"CLEAN_COMPLETION", "UNSETTLED_EPISODE_TERMINATION", "EPISODE_CANCELLED"}
)


def compute_terminal_record_id(
    run_id: str, terminal_status: str, parent_round_hash: str | None
) -> str:
    """Compute the deterministic terminal record ID from canonical identity fields."""
    if not isinstance(run_id, str) or not _RUN_ID_PATTERN.match(run_id):
        raise ValueError(f"Invalid run_id for terminal ID computation: {run_id!r}")
    if terminal_status not in _VALID_STATUSES:
        raise ValueError(f"Invalid terminal_status: {terminal_status!r}")
    if parent_round_hash is not None and (
        not isinstance(parent_round_hash, str) or not _SHA256_HASH_PATTERN.match(parent_round_hash)
    ):
        raise ValueError(f"Invalid parent_round_hash: {parent_round_hash!r}")

    identity_dict = {
        "parent_round_hash": parent_round_hash,
        "run_id": run_id,
        "terminal_status": terminal_status,
    }
    raw_hash = compute_record_hash(identity_dict)
    hex_digest = raw_hash.split(":", 1)[1]
    return f"term_{hex_digest}"


def compute_terminal_state_merkle_hash(
    parent_round_hash: str | None,
    policy_terminal_records: Sequence[PolicyTerminalRecord],
) -> str:
    """Compute the state Merkle hash across policy terminal record leaves."""
    leaves = [entry.compute_hash() for entry in policy_terminal_records]
    return compute_state_merkle_hash(parent_round_hash, leaves)


@dataclass(frozen=True)
class PolicyTerminalRecord:
    """Immutable terminal record for a single policy at episode completion/cancellation."""

    policy_id: str
    account_state_hash: str
    pending_transition_hash: str | None = None
    settlement_outcome_hash: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, str) or not _POLICY_ID_PATTERN.match(self.policy_id):
            raise ValueError(f"Invalid policy_id: {self.policy_id!r}")
        if not isinstance(self.account_state_hash, str) or not _SHA256_HASH_PATTERN.match(
            self.account_state_hash
        ):
            raise ValueError(f"Invalid account_state_hash: {self.account_state_hash!r}")

        # Co-presence invariant
        if self.pending_transition_hash is None:
            if self.settlement_outcome_hash is not None:
                raise ValueError(
                    "settlement_outcome_hash must be None when pending_transition_hash is None"
                )
        else:
            if not isinstance(self.pending_transition_hash, str) or not _SHA256_HASH_PATTERN.match(
                self.pending_transition_hash
            ):
                raise ValueError(
                    f"Invalid pending_transition_hash: {self.pending_transition_hash!r}"
                )
            if (
                self.settlement_outcome_hash is None
                or not isinstance(self.settlement_outcome_hash, str)
                or not _SHA256_HASH_PATTERN.match(self.settlement_outcome_hash)
            ):
                raise ValueError(
                    "settlement_outcome_hash must be a valid SHA-256 hash when "
                    "pending_transition_hash is present"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "account_state_hash": self.account_state_hash,
            "pending_transition_hash": self.pending_transition_hash,
            "settlement_outcome_hash": self.settlement_outcome_hash,
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyTerminalRecord:
        if not isinstance(data, dict):
            raise TypeError(f"PolicyTerminalRecord data must be a dict, got {type(data)}")
        expected_keys = {
            "policy_id",
            "account_state_hash",
            "pending_transition_hash",
            "settlement_outcome_hash",
        }
        actual_keys = set(data.keys())
        if actual_keys != expected_keys:
            raise ValueError(
                f"PolicyTerminalRecord fields do not match schema: {sorted(actual_keys)}"
            )
        return cls(
            policy_id=data["policy_id"],
            account_state_hash=data["account_state_hash"],
            pending_transition_hash=data["pending_transition_hash"],
            settlement_outcome_hash=data["settlement_outcome_hash"],
        )


@dataclass(frozen=True)
class DeferredRunTerminalRecord:
    """Immutable record capturing final episode termination or cancellation."""

    terminal_record_id: str
    run_id: str
    episode_id: str
    terminal_status: str
    reason_code: str
    reason_message: str
    simulation_frontier_time: str | None
    execution_timestamp: str
    parent_round_hash: str | None
    policy_terminal_records: tuple[PolicyTerminalRecord, ...]
    terminal_state_merkle_hash: str
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError(f"Unsupported schema_version: {self.schema_version!r}")
        if not isinstance(self.terminal_record_id, str) or not _TERMINAL_ID_PATTERN.match(
            self.terminal_record_id
        ):
            raise ValueError(f"Invalid terminal_record_id: {self.terminal_record_id!r}")
        if not isinstance(self.run_id, str) or not _RUN_ID_PATTERN.match(self.run_id):
            raise ValueError(f"Invalid run_id: {self.run_id!r}")
        if not isinstance(self.episode_id, str) or not _EPISODE_ID_PATTERN.match(self.episode_id):
            raise ValueError(f"Invalid episode_id: {self.episode_id!r}")

        if self.terminal_status not in _VALID_STATUSES:
            raise ValueError(f"Invalid terminal_status: {self.terminal_status!r}")
        if self.reason_code not in _VALID_REASONS:
            raise ValueError(f"Invalid reason_code: {self.reason_code!r}")
        if not isinstance(self.reason_message, str) or not (1 <= len(self.reason_message) <= 1000):
            raise ValueError("reason_message must be a string of length 1 to 1000")

        parse_utc_timestamp(self.execution_timestamp)

        # Parent round hash and simulation frontier time invariants
        if self.parent_round_hash is None:
            if self.simulation_frontier_time is not None:
                raise ValueError(
                    "simulation_frontier_time must be None when parent_round_hash "
                    "is None (genesis cancellation)"
                )
            if self.terminal_status != "CANCELLED":
                raise ValueError("Genesis terminal record must have terminal_status='CANCELLED'")
            if self.reason_code != "EPISODE_CANCELLED":
                raise ValueError(
                    "Genesis terminal record must have reason_code='EPISODE_CANCELLED'"
                )
        else:
            if not isinstance(self.parent_round_hash, str) or not _SHA256_HASH_PATTERN.match(
                self.parent_round_hash
            ):
                raise ValueError(f"Invalid parent_round_hash: {self.parent_round_hash!r}")
            if self.simulation_frontier_time is None:
                raise ValueError(
                    "simulation_frontier_time must be provided when parent_round_hash is non-null"
                )
            parse_utc_timestamp(self.simulation_frontier_time)

        # Policy terminal records validation
        if not isinstance(self.policy_terminal_records, tuple):
            object.__setattr__(self, "policy_terminal_records", tuple(self.policy_terminal_records))

        if len(self.policy_terminal_records) < 1:
            raise ValueError("policy_terminal_records must contain at least one entry")

        policy_ids = [p.policy_id for p in self.policy_terminal_records]
        if len(policy_ids) != len(set(policy_ids)):
            raise DuplicateIdentityError("Duplicate policy_id in policy_terminal_records")
        if policy_ids != sorted(policy_ids):
            raise ValueError("policy_terminal_records must be sorted strictly by policy_id")

        has_pending = any(
            p.pending_transition_hash is not None for p in self.policy_terminal_records
        )

        # Genesis cancellation cannot have pending orders
        if self.parent_round_hash is None and has_pending:
            raise ValueError("Genesis cancellation cannot have active pending transitions")

        # Status and reason code compatibility
        if self.terminal_status == "COMPLETED":
            if has_pending:
                if self.reason_code != "UNSETTLED_EPISODE_TERMINATION":
                    raise ValueError(
                        "COMPLETED status with active pending must have "
                        "reason_code='UNSETTLED_EPISODE_TERMINATION'"
                    )
            else:
                if self.reason_code != "CLEAN_COMPLETION":
                    raise ValueError(
                        "COMPLETED status without pending must have reason_code='CLEAN_COMPLETION'"
                    )
        elif self.terminal_status == "CANCELLED":
            if self.reason_code != "EPISODE_CANCELLED":
                raise ValueError("CANCELLED status must have reason_code='EPISODE_CANCELLED'")

        # Merkle root verification
        expected_merkle = compute_terminal_state_merkle_hash(
            self.parent_round_hash, self.policy_terminal_records
        )
        if self.terminal_state_merkle_hash != expected_merkle:
            raise ValueError(
                f"terminal_state_merkle_hash mismatch: expected {expected_merkle}, "
                f"got {self.terminal_state_merkle_hash}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "$type": "deferred_run_terminal_record",
            "schema_version": self.schema_version,
            "terminal_record_id": self.terminal_record_id,
            "run_id": self.run_id,
            "episode_id": self.episode_id,
            "terminal_status": self.terminal_status,
            "reason_code": self.reason_code,
            "reason_message": self.reason_message,
            "simulation_frontier_time": self.simulation_frontier_time,
            "execution_timestamp": self.execution_timestamp,
            "parent_round_hash": self.parent_round_hash,
            "policy_terminal_records": [p.to_dict() for p in self.policy_terminal_records],
            "terminal_state_merkle_hash": self.terminal_state_merkle_hash,
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeferredRunTerminalRecord:
        if not isinstance(data, dict):
            raise TypeError(f"DeferredRunTerminalRecord data must be a dict, got {type(data)}")
        expected_keys = {
            "$type",
            "schema_version",
            "terminal_record_id",
            "run_id",
            "episode_id",
            "terminal_status",
            "reason_code",
            "reason_message",
            "simulation_frontier_time",
            "execution_timestamp",
            "parent_round_hash",
            "policy_terminal_records",
            "terminal_state_merkle_hash",
        }
        actual_keys = set(data.keys())
        if actual_keys != expected_keys:
            missing = sorted(expected_keys - actual_keys)
            extra = sorted(actual_keys - expected_keys)
            raise ValueError(
                f"DeferredRunTerminalRecord fields mismatch: missing={missing}, extra={extra}"
            )
        if data["$type"] != "deferred_run_terminal_record":
            raise ValueError(
                f"Invalid $type: expected 'deferred_run_terminal_record', got {data['$type']!r}"
            )

        policy_records = tuple(
            PolicyTerminalRecord.from_dict(p) for p in data["policy_terminal_records"]
        )

        return cls(
            terminal_record_id=data["terminal_record_id"],
            run_id=data["run_id"],
            episode_id=data["episode_id"],
            terminal_status=data["terminal_status"],
            reason_code=data["reason_code"],
            reason_message=data["reason_message"],
            simulation_frontier_time=data["simulation_frontier_time"],
            execution_timestamp=data["execution_timestamp"],
            parent_round_hash=data["parent_round_hash"],
            policy_terminal_records=policy_records,
            terminal_state_merkle_hash=data["terminal_state_merkle_hash"],
            schema_version=data["schema_version"],
        )
