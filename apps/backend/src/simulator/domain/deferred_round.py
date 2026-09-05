"""Deferred round records and Merkle hash computation (DS-02D2C0).

Provides immutable domain models for simulation rounds under deferred paper settlement:
- `PendingStateReference`: captures pending transition hash, admission account hash,
  frozen expected opening time, and settlement deadline.
- `DeferredPolicyRoundRecord`: represents a single policy's execution within a round,
  disentangling prior pending settlement from new proposal admission.
- `DeferredRoundRecord`: represents the top-level immutable round record with schema_version 2.0.0.
- `compute_deferred_state_merkle_hash`: pure helper computing the v2 Merkle hash over
  lexicographically sorted policy records and the parent round hash.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final

from simulator.domain.canonical import compute_record_hash, compute_state_merkle_hash
from simulator.domain.time import parse_utc_timestamp

_ROUND_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^rnd_[a-zA-Z0-9_-]+$")
_RUN_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^ep-run_[a-zA-Z0-9_-]+$")
_POLICY_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^pol-def_[a-zA-Z0-9_-]+$")
_SHA256_HASH_PATTERN: Final[re.Pattern[str]] = re.compile(r"^sha256:[a-f0-9]{64}$")


@dataclass(frozen=True)
class PendingStateReference:
    """Immutable reference to an active pending order with caller schedule and anchor."""

    pending_transition_hash: str
    admission_account_hash: str
    expected_open_time: str
    settlement_deadline: str

    def __post_init__(self) -> None:
        if not isinstance(self.pending_transition_hash, str) or not _SHA256_HASH_PATTERN.match(
            self.pending_transition_hash
        ):
            raise ValueError(f"Invalid pending_transition_hash: {self.pending_transition_hash!r}")
        if not isinstance(self.admission_account_hash, str) or not _SHA256_HASH_PATTERN.match(
            self.admission_account_hash
        ):
            raise ValueError(f"Invalid admission_account_hash: {self.admission_account_hash!r}")
        open_dt = parse_utc_timestamp(self.expected_open_time)
        deadline_dt = parse_utc_timestamp(self.settlement_deadline)
        if open_dt > deadline_dt:
            raise ValueError(
                f"expected_open_time ({self.expected_open_time}) cannot be after "
                f"settlement_deadline ({self.settlement_deadline})"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "pending_transition_hash": self.pending_transition_hash,
            "admission_account_hash": self.admission_account_hash,
            "expected_open_time": self.expected_open_time,
            "settlement_deadline": self.settlement_deadline,
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PendingStateReference:
        if not isinstance(data, dict):
            raise TypeError(f"PendingStateReference data must be a dict, got {type(data)}")
        expected_keys = {
            "pending_transition_hash",
            "admission_account_hash",
            "expected_open_time",
            "settlement_deadline",
        }
        if set(data.keys()) != expected_keys:
            raise ValueError(
                f"PendingStateReference fields do not match schema: {sorted(data.keys())}"
            )
        return cls(
            pending_transition_hash=data["pending_transition_hash"],
            admission_account_hash=data["admission_account_hash"],
            expected_open_time=data["expected_open_time"],
            settlement_deadline=data["settlement_deadline"],
        )


@dataclass(frozen=True)
class DeferredPolicyRoundRecord:
    """Immutable execution record for a single policy under deferred settlement."""

    policy_id: str
    account_state_before_hash: str
    account_state_after_hash: str
    pending_before: PendingStateReference | None
    pending_after: PendingStateReference | None
    settlement_outcome_hash: str | None
    deferred_transition_hash: str | None
    proposed_decision_hash: str | None
    decision_outcome_hash: str | None
    optees_call_receipt_hashes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, str) or not _POLICY_ID_PATTERN.match(self.policy_id):
            raise ValueError(f"Invalid policy_id: {self.policy_id!r}")
        if not isinstance(self.account_state_before_hash, str) or not _SHA256_HASH_PATTERN.match(
            self.account_state_before_hash
        ):
            raise ValueError(
                f"Invalid account_state_before_hash: {self.account_state_before_hash!r}"
            )
        if not isinstance(self.account_state_after_hash, str) or not _SHA256_HASH_PATTERN.match(
            self.account_state_after_hash
        ):
            raise ValueError(f"Invalid account_state_after_hash: {self.account_state_after_hash!r}")

        if self.pending_before is not None and not isinstance(
            self.pending_before, PendingStateReference
        ):
            raise TypeError(
                f"pending_before must be PendingStateReference or None, "
                f"got {type(self.pending_before)}"
            )
        if self.pending_after is not None and not isinstance(
            self.pending_after, PendingStateReference
        ):
            raise TypeError(
                f"pending_after must be PendingStateReference or None, "
                f"got {type(self.pending_after)}"
            )

        if self.settlement_outcome_hash is not None and (
            not isinstance(self.settlement_outcome_hash, str)
            or not _SHA256_HASH_PATTERN.match(self.settlement_outcome_hash)
        ):
            raise ValueError(f"Invalid settlement_outcome_hash: {self.settlement_outcome_hash!r}")
        if self.deferred_transition_hash is not None and (
            not isinstance(self.deferred_transition_hash, str)
            or not _SHA256_HASH_PATTERN.match(self.deferred_transition_hash)
        ):
            raise ValueError(f"Invalid deferred_transition_hash: {self.deferred_transition_hash!r}")
        if self.proposed_decision_hash is not None and (
            not isinstance(self.proposed_decision_hash, str)
            or not _SHA256_HASH_PATTERN.match(self.proposed_decision_hash)
        ):
            raise ValueError(f"Invalid proposed_decision_hash: {self.proposed_decision_hash!r}")
        if self.decision_outcome_hash is not None and (
            not isinstance(self.decision_outcome_hash, str)
            or not _SHA256_HASH_PATTERN.match(self.decision_outcome_hash)
        ):
            raise ValueError(f"Invalid decision_outcome_hash: {self.decision_outcome_hash!r}")

        if not isinstance(self.optees_call_receipt_hashes, (tuple, list)):
            raise TypeError("optees_call_receipt_hashes must be a tuple or list")
        for h in self.optees_call_receipt_hashes:
            if not isinstance(h, str) or not _SHA256_HASH_PATTERN.match(h):
                raise ValueError(f"Invalid receipt hash in optees_call_receipt_hashes: {h!r}")
        object.__setattr__(
            self, "optees_call_receipt_hashes", tuple(self.optees_call_receipt_hashes)
        )

        # Invariant 1: Without pending_before, no settlement outcome or deferred transition.
        if self.pending_before is None:
            if self.settlement_outcome_hash is not None:
                raise ValueError("settlement_outcome_hash cannot be present without pending_before")
            if self.deferred_transition_hash is not None:
                raise ValueError(
                    "deferred_transition_hash cannot be present without pending_before"
                )

        # Invariant 2: A deferred transition requires a settlement outcome.
        if self.deferred_transition_hash is not None and self.settlement_outcome_hash is None:
            raise ValueError("deferred_transition_hash requires a settlement_outcome_hash")

        # Invariant 3: Without a settlement outcome, pending_before must be carried unchanged.
        if self.pending_before is not None and self.settlement_outcome_hash is None:
            if self.pending_after != self.pending_before:
                raise ValueError(
                    "Without a settlement outcome, pending_before must be "
                    "carried unchanged into pending_after"
                )

        # Invariant 6: No-proposal rounds are permitted for waiting/finalization:
        # no immediate outcome or new pending may appear.
        if self.proposed_decision_hash is None:
            if self.decision_outcome_hash is not None:
                raise ValueError(
                    "decision_outcome_hash cannot be present without proposed_decision_hash"
                )
            if self.pending_after is not None and self.pending_after != self.pending_before:
                raise ValueError("New pending_after cannot appear in a no-proposal round")
        else:
            # Invariant 4: A proposal has exactly one result: an immediate outcome
            # OR a newly admitted pending_after.
            has_immediate_outcome = self.decision_outcome_hash is not None
            has_new_pending = (
                self.pending_after is not None and self.pending_after != self.pending_before
            )
            if has_immediate_outcome and has_new_pending:
                raise ValueError(
                    "A proposal cannot produce both an immediate outcome "
                    "and a newly admitted pending"
                )
            if not has_immediate_outcome and not has_new_pending:
                raise ValueError(
                    "A proposal must produce either an immediate outcome "
                    "or a newly admitted pending"
                )
            if (
                has_new_pending
                and self.pending_before is not None
                and self.settlement_outcome_hash is None
            ):
                raise ValueError("New admission cannot replace an unsettled pending_before")

        # Invariant 5: After settling/rejecting pending_before, it cannot remain pending_after.
        if self.pending_before is not None and self.settlement_outcome_hash is not None:
            if self.pending_after == self.pending_before:
                raise ValueError(
                    "Settled or rejected pending_before cannot remain as pending_after"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "account_state_before_hash": self.account_state_before_hash,
            "account_state_after_hash": self.account_state_after_hash,
            "pending_before": (
                self.pending_before.to_dict() if self.pending_before is not None else None
            ),
            "pending_after": (
                self.pending_after.to_dict() if self.pending_after is not None else None
            ),
            "settlement_outcome_hash": self.settlement_outcome_hash,
            "deferred_transition_hash": self.deferred_transition_hash,
            "proposed_decision_hash": self.proposed_decision_hash,
            "decision_outcome_hash": self.decision_outcome_hash,
            "optees_call_receipt_hashes": list(self.optees_call_receipt_hashes),
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeferredPolicyRoundRecord:
        if not isinstance(data, dict):
            raise TypeError(f"DeferredPolicyRoundRecord data must be a dict, got {type(data)}")
        expected_fields = {
            "policy_id",
            "account_state_before_hash",
            "account_state_after_hash",
            "pending_before",
            "pending_after",
            "settlement_outcome_hash",
            "deferred_transition_hash",
            "proposed_decision_hash",
            "decision_outcome_hash",
            "optees_call_receipt_hashes",
        }
        if set(data.keys()) != expected_fields:
            raise ValueError(
                f"DeferredPolicyRoundRecord fields do not match schema: {sorted(data.keys())}"
            )

        raw_pb = data["pending_before"]
        pending_before = PendingStateReference.from_dict(raw_pb) if raw_pb is not None else None

        raw_pa = data["pending_after"]
        pending_after = PendingStateReference.from_dict(raw_pa) if raw_pa is not None else None

        raw_receipts = data["optees_call_receipt_hashes"]
        if not isinstance(raw_receipts, (tuple, list)):
            raise TypeError("optees_call_receipt_hashes must be a list or tuple")

        return cls(
            policy_id=data["policy_id"],
            account_state_before_hash=data["account_state_before_hash"],
            account_state_after_hash=data["account_state_after_hash"],
            pending_before=pending_before,
            pending_after=pending_after,
            settlement_outcome_hash=data["settlement_outcome_hash"],
            deferred_transition_hash=data["deferred_transition_hash"],
            proposed_decision_hash=data["proposed_decision_hash"],
            decision_outcome_hash=data["decision_outcome_hash"],
            optees_call_receipt_hashes=tuple(raw_receipts),
        )


def compute_deferred_state_merkle_hash(
    parent_round_hash: str | None,
    policy_round_records: tuple[DeferredPolicyRoundRecord, ...] | list[DeferredPolicyRoundRecord],
) -> str:
    """Compute state Merkle hash for deferred round v2.

    For policies in strict lexicographic policy_id order, computes the record
    hash of each policy entry dictionary and passes them with parent_round_hash
    to compute_state_merkle_hash.
    """
    if parent_round_hash is not None and (
        not isinstance(parent_round_hash, str) or not _SHA256_HASH_PATTERN.match(parent_round_hash)
    ):
        raise ValueError(f"Invalid parent_round_hash: {parent_round_hash!r}")
    if not isinstance(policy_round_records, (tuple, list)):
        raise TypeError("policy_round_records must be a sequence of DeferredPolicyRoundRecord")
    if len(policy_round_records) == 0:
        raise ValueError("policy_round_records must contain at least one policy record")

    for p in policy_round_records:
        if not isinstance(p, DeferredPolicyRoundRecord):
            raise TypeError(
                f"policy_round_records item must be DeferredPolicyRoundRecord, got {type(p)}"
            )

    policy_ids = [p.policy_id for p in policy_round_records]
    for i in range(len(policy_ids) - 1):
        if policy_ids[i] >= policy_ids[i + 1]:
            raise ValueError(
                "policy_round_records must be in strictly increasing "
                f"lexicographic order by policy_id: '{policy_ids[i]}' >= '{policy_ids[i + 1]}'"
            )

    item_hashes = [compute_record_hash(p.to_dict()) for p in policy_round_records]
    return compute_state_merkle_hash(parent_round_hash, item_hashes)


@dataclass(frozen=True)
class DeferredRoundRecord:
    """Immutable execution record of a single simulation round under deferred settlement."""

    round_id: str
    run_id: str
    round_index: int
    parent_round_hash: str | None
    knowledge_cutoff: str
    execution_start_time: str
    execution_end_time: str
    effective_time: str
    eligible_observation_hashes: tuple[str, ...]
    policy_round_records: tuple[DeferredPolicyRoundRecord, ...]
    state_merkle_hash: str
    schema_version: str = "2.0.0"

    def __post_init__(self) -> None:
        if not isinstance(self.round_id, str) or not _ROUND_ID_PATTERN.match(self.round_id):
            raise ValueError(f"Invalid round_id: {self.round_id!r}")
        if not isinstance(self.run_id, str) or not _RUN_ID_PATTERN.match(self.run_id):
            raise ValueError(f"Invalid run_id: {self.run_id!r}")
        if (
            isinstance(self.round_index, bool)
            or not isinstance(self.round_index, int)
            or self.round_index < 0
        ):
            raise ValueError(f"round_index must be non-negative integer, got {self.round_index!r}")
        if self.parent_round_hash is not None and (
            not isinstance(self.parent_round_hash, str)
            or not _SHA256_HASH_PATTERN.match(self.parent_round_hash)
        ):
            raise ValueError(f"Invalid parent_round_hash: {self.parent_round_hash!r}")
        if self.schema_version != "2.0.0":
            raise ValueError(
                f"DeferredRoundRecord schema_version must be '2.0.0', got {self.schema_version!r}"
            )

        parse_utc_timestamp(self.knowledge_cutoff)
        parse_utc_timestamp(self.execution_start_time)
        parse_utc_timestamp(self.execution_end_time)
        parse_utc_timestamp(self.effective_time)

        if not isinstance(self.eligible_observation_hashes, (tuple, list)):
            raise TypeError("eligible_observation_hashes must be a tuple or list")
        for h in self.eligible_observation_hashes:
            if not isinstance(h, str) or not _SHA256_HASH_PATTERN.match(h):
                raise ValueError(f"Invalid observation hash: {h!r}")
        object.__setattr__(
            self, "eligible_observation_hashes", tuple(self.eligible_observation_hashes)
        )

        if not isinstance(self.policy_round_records, (tuple, list)):
            raise TypeError("policy_round_records must be a tuple or list")
        if len(self.policy_round_records) == 0:
            raise ValueError("policy_round_records must contain at least one policy record")
        for p in self.policy_round_records:
            if not isinstance(p, DeferredPolicyRoundRecord):
                raise TypeError(
                    f"policy_round_records item must be DeferredPolicyRoundRecord, got {type(p)}"
                )
        object.__setattr__(self, "policy_round_records", tuple(self.policy_round_records))

        expected_merkle = compute_deferred_state_merkle_hash(
            self.parent_round_hash, self.policy_round_records
        )
        if self.state_merkle_hash != expected_merkle:
            raise ValueError(
                f"state_merkle_hash mismatch: expected {expected_merkle}, "
                f"got {self.state_merkle_hash}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "$type": "round",
            "schema_version": self.schema_version,
            "round_id": self.round_id,
            "run_id": self.run_id,
            "round_index": self.round_index,
            "parent_round_hash": self.parent_round_hash,
            "knowledge_cutoff": self.knowledge_cutoff,
            "execution_start_time": self.execution_start_time,
            "execution_end_time": self.execution_end_time,
            "effective_time": self.effective_time,
            "eligible_observation_hashes": list(self.eligible_observation_hashes),
            "policy_round_records": [p.to_dict() for p in self.policy_round_records],
            "state_merkle_hash": self.state_merkle_hash,
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeferredRoundRecord:
        if not isinstance(data, dict):
            raise TypeError(f"DeferredRoundRecord data must be a dict, got {type(data)}")
        expected_fields = {
            "$type",
            "schema_version",
            "round_id",
            "run_id",
            "round_index",
            "parent_round_hash",
            "knowledge_cutoff",
            "execution_start_time",
            "execution_end_time",
            "effective_time",
            "eligible_observation_hashes",
            "policy_round_records",
            "state_merkle_hash",
        }
        if set(data.keys()) != expected_fields:
            raise ValueError(
                f"DeferredRoundRecord fields do not match schema: {sorted(data.keys())}"
            )
        if data["$type"] != "round":
            raise ValueError(f"DeferredRoundRecord $type must be 'round', got {data['$type']!r}")
        if data["schema_version"] != "2.0.0":
            raise ValueError(
                "DeferredRoundRecord schema_version must be '2.0.0', "
                f"got {data['schema_version']!r}"
            )

        raw_policies = data["policy_round_records"]
        if not isinstance(raw_policies, (tuple, list)):
            raise TypeError("policy_round_records must be a list or tuple")
        policy_records = tuple(DeferredPolicyRoundRecord.from_dict(p) for p in raw_policies)

        raw_obs = data["eligible_observation_hashes"]
        if not isinstance(raw_obs, (tuple, list)):
            raise TypeError("eligible_observation_hashes must be a list or tuple")

        return cls(
            round_id=data["round_id"],
            run_id=data["run_id"],
            round_index=data["round_index"],
            parent_round_hash=data["parent_round_hash"],
            knowledge_cutoff=data["knowledge_cutoff"],
            execution_start_time=data["execution_start_time"],
            execution_end_time=data["execution_end_time"],
            effective_time=data["effective_time"],
            eligible_observation_hashes=tuple(raw_obs),
            policy_round_records=policy_records,
            state_merkle_hash=data["state_merkle_hash"],
            schema_version=data["schema_version"],
        )
