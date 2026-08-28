"""Immutable domain entities and value objects matching frozen v1 core contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from simulator.domain.canonical import (
    compute_record_hash,
    format_decimal,
)
from simulator.domain.errors import (
    DuplicateIdentityError,
)
from simulator.domain.immutable import freeze_json, thaw_json
from simulator.domain.lifecycle import (
    ActionType,
    CostType,
    DecisionStatus,
    DivergenceCategory,
    LifecycleStatus,
    PolicyType,
    ReplayMode,
    ReplayStatus,
)
from simulator.domain.time import parse_utc_timestamp

# ---------------------------------------------------------------------------
# Supporting Value Objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DatasetSnapshotRef:
    snapshot_id: str
    source_uri: str
    checksum_sha256: str
    retrieval_time: str
    calendar_frequency: str

    def __post_init__(self) -> None:
        parse_utc_timestamp(self.retrieval_time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "source_uri": self.source_uri,
            "checksum_sha256": self.checksum_sha256,
            "retrieval_time": self.retrieval_time,
            "calendar_frequency": self.calendar_frequency,
        }


@dataclass(frozen=True)
class CalendarSpec:
    round_cutoffs: tuple[str, ...]
    interval_duration: str
    evaluation_delay: str

    def __post_init__(self) -> None:
        if not self.round_cutoffs:
            raise ValueError("CalendarSpec must define at least one round cutoff")
        prev_dt = None
        for cutoff in self.round_cutoffs:
            curr_dt = parse_utc_timestamp(cutoff)
            if prev_dt is not None and curr_dt <= prev_dt:
                raise ValueError("Round cutoffs must be strictly monotonically increasing")
            prev_dt = curr_dt

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_cutoffs": list(self.round_cutoffs),
            "interval_duration": self.interval_duration,
            "evaluation_delay": self.evaluation_delay,
        }


@dataclass(frozen=True)
class PolicyVersionRef:
    policy_id: str
    policy_version_id: str
    policy_version: str
    policy_hash: str
    config_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "policy_version_id": self.policy_version_id,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "config_hash": self.config_hash,
        }


@dataclass(frozen=True)
class AccountBalanceSpec:
    resource_id: str
    quantity: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "quantity": format_decimal(self.quantity),
        }


@dataclass(frozen=True)
class InitialAccountSpec:
    policy_id: str
    balances: tuple[AccountBalanceSpec, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "balances": [b.to_dict() for b in self.balances],
        }


@dataclass(frozen=True)
class CostModelSpec:
    linear_transaction_fee_rate: Decimal
    fixed_transaction_fee: Decimal
    holding_cost_rate: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "linear_transaction_fee_rate": format_decimal(self.linear_transaction_fee_rate),
            "fixed_transaction_fee": format_decimal(self.fixed_transaction_fee),
            "holding_cost_rate": format_decimal(self.holding_cost_rate),
        }


@dataclass(frozen=True)
class ConstraintsSpec:
    max_transition_count_per_round: int | None = None
    max_allocation_per_resource: Decimal | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.max_transition_count_per_round is not None:
            d["max_transition_count_per_round"] = self.max_transition_count_per_round
        if self.max_allocation_per_resource is not None:
            d["max_allocation_per_resource"] = format_decimal(self.max_allocation_per_resource)
        return d


@dataclass(frozen=True)
class FailurePolicySpec:
    on_policy_error: str = "REJECT_AND_HOLD"
    on_solver_timeout: str = "FALLBACK_TO_HOLD"
    on_invalid_decision: str = "REJECT_AND_HOLD"

    def to_dict(self) -> dict[str, Any]:
        return {
            "on_policy_error": self.on_policy_error,
            "on_solver_timeout": self.on_solver_timeout,
            "on_invalid_decision": self.on_invalid_decision,
        }


@dataclass(frozen=True)
class EpisodeRulesSpec:
    allow_short_positions: bool
    allow_borrowing: bool
    cost_model: CostModelSpec
    failure_policy: FailurePolicySpec
    constraints: ConstraintsSpec = field(default_factory=ConstraintsSpec)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_short_positions": self.allow_short_positions,
            "allow_borrowing": self.allow_borrowing,
            "cost_model": self.cost_model.to_dict(),
            "constraints": self.constraints.to_dict(),
            "failure_policy": self.failure_policy.to_dict(),
        }


# ---------------------------------------------------------------------------
# Core Entities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EpisodeDefinition:
    episode_id: str
    title: str
    description: str
    created_at: str
    dataset_snapshot: DatasetSnapshotRef
    calendar: CalendarSpec
    policy_versions: tuple[PolicyVersionRef, ...]
    initial_accounts: tuple[InitialAccountSpec, ...]
    reference_resource_id: str
    rules: EpisodeRulesSpec
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        parse_utc_timestamp(self.created_at)
        object.__setattr__(self, "metadata", freeze_json(self.metadata))
        policy_ids = [p.policy_id for p in self.policy_versions]
        if len(policy_ids) != len(set(policy_ids)):
            raise DuplicateIdentityError("Duplicate policy_id in policy_versions")
        account_policy_ids = [a.policy_id for a in self.initial_accounts]
        if len(account_policy_ids) != len(set(account_policy_ids)):
            raise DuplicateIdentityError("Duplicate policy_id in initial_accounts")

    def to_dict(self) -> dict[str, Any]:
        return {
            "$type": "episode_definition",
            "schema_version": self.schema_version,
            "episode_id": self.episode_id,
            "title": self.title,
            "description": self.description,
            "created_at": self.created_at,
            "dataset_snapshot": self.dataset_snapshot.to_dict(),
            "calendar": self.calendar.to_dict(),
            "policy_versions": [p.to_dict() for p in self.policy_versions],
            "initial_accounts": [a.to_dict() for a in self.initial_accounts],
            "reference_resource_id": self.reference_resource_id,
            "rules": self.rules.to_dict(),
            "metadata": thaw_json(self.metadata),
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())


@dataclass(frozen=True)
class EpisodeRun:
    run_id: str
    episode_id: str
    episode_definition_hash: str
    lifecycle_status: LifecycleStatus
    started_at: str
    ended_at: str | None
    current_round_index: int
    total_rounds: int
    final_state_hash: str | None
    failure_reason: str | None = None
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        parse_utc_timestamp(self.started_at)
        if self.ended_at is not None:
            parse_utc_timestamp(self.ended_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "$type": "episode_run",
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "episode_id": self.episode_id,
            "episode_definition_hash": self.episode_definition_hash,
            "lifecycle_status": self.lifecycle_status.value,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "current_round_index": self.current_round_index,
            "total_rounds": self.total_rounds,
            "final_state_hash": self.final_state_hash,
            "failure_reason": self.failure_reason,
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())


@dataclass(frozen=True)
class PolicyDefinition:
    policy_id: str
    name: str
    description: str
    author: str
    created_at: str
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        parse_utc_timestamp(self.created_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "$type": "policy_definition",
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "created_at": self.created_at,
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())


@dataclass(frozen=True)
class PolicyVersion:
    policy_version_id: str
    policy_id: str
    version: str
    policy_type: PolicyType
    required_capabilities: tuple[dict[str, str], ...]
    required_observations: tuple[dict[str, Any], ...]
    hyperparameters: dict[str, Any]
    code_provenance: dict[str, str]
    declared_tolerances: dict[str, float]
    created_at: str
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        parse_utc_timestamp(self.created_at)
        object.__setattr__(
            self, "required_capabilities", tuple(freeze_json(v) for v in self.required_capabilities)
        )
        object.__setattr__(
            self, "required_observations", tuple(freeze_json(v) for v in self.required_observations)
        )
        object.__setattr__(self, "hyperparameters", freeze_json(self.hyperparameters))
        object.__setattr__(self, "code_provenance", freeze_json(self.code_provenance))
        object.__setattr__(self, "declared_tolerances", freeze_json(self.declared_tolerances))

    def to_dict(self) -> dict[str, Any]:
        return {
            "$type": "policy_version",
            "schema_version": self.schema_version,
            "policy_version_id": self.policy_version_id,
            "policy_id": self.policy_id,
            "version": self.version,
            "policy_type": self.policy_type.value,
            "required_capabilities": thaw_json(self.required_capabilities),
            "required_observations": thaw_json(self.required_observations),
            "hyperparameters": thaw_json(self.hyperparameters),
            "code_provenance": thaw_json(self.code_provenance),
            "declared_tolerances": thaw_json(self.declared_tolerances),
            "created_at": self.created_at,
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())


@dataclass(frozen=True)
class SeriesCatalogItem:
    series_id: str
    resource_id: str
    unit: str
    frequency: str
    earliest_event_time: str
    latest_event_time: str

    def __post_init__(self) -> None:
        parse_utc_timestamp(self.earliest_event_time)
        parse_utc_timestamp(self.latest_event_time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "series_id": self.series_id,
            "resource_id": self.resource_id,
            "unit": self.unit,
            "frequency": self.frequency,
            "earliest_event_time": self.earliest_event_time,
            "latest_event_time": self.latest_event_time,
        }


@dataclass(frozen=True)
class DatasetSnapshotManifest:
    snapshot_id: str
    source_uri: str
    retrieval_time: str
    license: str
    checksum_sha256: str
    byte_size: int
    format: str
    series_catalog: tuple[SeriesCatalogItem, ...]
    correction_handling: str
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        parse_utc_timestamp(self.retrieval_time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "$type": "dataset_snapshot",
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "source_uri": self.source_uri,
            "retrieval_time": self.retrieval_time,
            "license": self.license,
            "checksum_sha256": self.checksum_sha256,
            "byte_size": self.byte_size,
            "format": self.format,
            "series_catalog": [s.to_dict() for s in self.series_catalog],
            "correction_handling": self.correction_handling,
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())


@dataclass(frozen=True)
class AcquisitionReceipt:
    acquisition_id: str
    snapshot_id: str
    provider_archive_uri: str
    provider_archive_filename: str
    publisher_checksum_uri: str
    retrieval_time: str
    publisher_sha256: str | None
    raw_artifact_sha256: str
    raw_byte_size: int
    normalizer_id: str
    normalizer_version: str
    normalized_snapshot_sha256: str | None
    manifest_sha256: str
    verification_outcome: str
    failure_reasons: tuple[str, ...] = ()
    license: str = "Upstream repository labelled MIT; raw archive redistribution not asserted"
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if self.raw_byte_size < 0:
            raise ValueError(f"raw_byte_size must be >= 0, got {self.raw_byte_size}")
        if self.verification_outcome not in ("ACCEPTED", "REJECTED"):
            raise ValueError(f"Invalid verification_outcome: {self.verification_outcome}")
        if self.verification_outcome == "ACCEPTED":
            parse_utc_timestamp(self.retrieval_time)
            if self.raw_byte_size < 1:
                raise ValueError("accepted evidence must contain non-empty raw bytes")
            if self.publisher_sha256 is None:
                raise ValueError("accepted evidence must contain the parsed publisher digest")
            if self.normalized_snapshot_sha256 is None:
                raise ValueError("accepted evidence must contain the computed normalized digest")
            if self.failure_reasons:
                raise ValueError("accepted evidence cannot contain failure reasons")
        elif not self.failure_reasons:
            raise ValueError("rejected evidence must contain at least one failure reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "$type": "acquisition_receipt",
            "schema_version": self.schema_version,
            "acquisition_id": self.acquisition_id,
            "snapshot_id": self.snapshot_id,
            "provider_archive_uri": self.provider_archive_uri,
            "provider_archive_filename": self.provider_archive_filename,
            "publisher_checksum_uri": self.publisher_checksum_uri,
            "retrieval_time": self.retrieval_time,
            "publisher_sha256": self.publisher_sha256,
            "raw_artifact_sha256": self.raw_artifact_sha256,
            "raw_byte_size": self.raw_byte_size,
            "normalizer_id": self.normalizer_id,
            "normalizer_version": self.normalizer_version,
            "normalized_snapshot_sha256": self.normalized_snapshot_sha256,
            "manifest_sha256": self.manifest_sha256,
            "verification_outcome": self.verification_outcome,
            "failure_reasons": list(self.failure_reasons),
            "license": self.license,
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())


@dataclass(frozen=True)
class ObservationRecord:
    observation_id: str
    snapshot_id: str
    series_id: str
    event_time: str
    knowledge_time: str
    revision: int
    payload: dict[str, Any]
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        parse_utc_timestamp(self.event_time)
        parse_utc_timestamp(self.knowledge_time)
        object.__setattr__(self, "payload", freeze_json(self.payload))
        if self.revision < 1:
            raise ValueError("Observation revision must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "$type": "observation",
            "schema_version": self.schema_version,
            "observation_id": self.observation_id,
            "snapshot_id": self.snapshot_id,
            "series_id": self.series_id,
            "event_time": self.event_time,
            "knowledge_time": self.knowledge_time,
            "revision": self.revision,
            "payload": thaw_json(self.payload),
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())


@dataclass(frozen=True)
class DesiredAllocation:
    resource_id: str
    target_quantity: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "target_quantity": format_decimal(self.target_quantity),
        }


@dataclass(frozen=True)
class RequestedAction:
    action_type: ActionType
    resource_id: str
    quantity: Decimal
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", freeze_json(self.parameters))

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type.value,
            "resource_id": self.resource_id,
            "quantity": format_decimal(self.quantity),
            "parameters": thaw_json(self.parameters),
        }


@dataclass(frozen=True)
class DecisionRationale:
    method: str
    objective_value: float | None = None
    solver_status: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra", freeze_json(self.extra))

    def to_dict(self) -> dict[str, Any]:
        d = {
            "method": self.method,
            "objective_value": self.objective_value,
            "solver_status": self.solver_status,
        }
        d.update(thaw_json(self.extra))
        return d


@dataclass(frozen=True)
class ProposedDecision:
    decision_id: str
    round_id: str
    policy_id: str
    policy_version_id: str
    knowledge_cutoff: str
    generated_at: str
    desired_allocations: tuple[DesiredAllocation, ...]
    requested_actions: tuple[RequestedAction, ...]
    rationale: DecisionRationale
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        parse_utc_timestamp(self.knowledge_cutoff)
        parse_utc_timestamp(self.generated_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "$type": "proposed_decision",
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "round_id": self.round_id,
            "policy_id": self.policy_id,
            "policy_version_id": self.policy_version_id,
            "knowledge_cutoff": self.knowledge_cutoff,
            "generated_at": self.generated_at,
            "desired_allocations": [a.to_dict() for a in self.desired_allocations],
            "requested_actions": [a.to_dict() for a in self.requested_actions],
            "rationale": self.rationale.to_dict(),
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())


@dataclass(frozen=True)
class RejectionReason:
    code: str
    message: str
    violating_field: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "violating_field": self.violating_field,
        }


@dataclass(frozen=True)
class DecisionOutcome:
    outcome_id: str
    decision_id: str
    round_id: str
    policy_id: str
    status: DecisionStatus
    rejection_reasons: tuple[RejectionReason, ...]
    evaluated_at: str
    applied_transition_id: str | None = None
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        parse_utc_timestamp(self.evaluated_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "$type": "decision_outcome",
            "schema_version": self.schema_version,
            "outcome_id": self.outcome_id,
            "decision_id": self.decision_id,
            "round_id": self.round_id,
            "policy_id": self.policy_id,
            "status": self.status.value,
            "rejection_reasons": [r.to_dict() for r in self.rejection_reasons],
            "evaluated_at": self.evaluated_at,
            "applied_transition_id": self.applied_transition_id,
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())


@dataclass(frozen=True)
class ResourceDelta:
    resource_id: str
    delta_quantity: Decimal
    valuation_price: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "delta_quantity": format_decimal(self.delta_quantity),
            "valuation_price": format_decimal(self.valuation_price),
        }


@dataclass(frozen=True)
class CostItem:
    cost_type: CostType
    resource_id: str
    amount: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_type": self.cost_type.value,
            "resource_id": self.resource_id,
            "amount": format_decimal(self.amount),
        }


@dataclass(frozen=True)
class TransitionRecord:
    transition_id: str
    round_id: str
    policy_id: str
    outcome_id: str
    effective_time: str
    resource_deltas: tuple[ResourceDelta, ...]
    costs: tuple[CostItem, ...]
    total_cost_reference_unit: Decimal
    account_state_before_hash: str
    account_state_after_hash: str
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        parse_utc_timestamp(self.effective_time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "$type": "transition",
            "schema_version": self.schema_version,
            "transition_id": self.transition_id,
            "round_id": self.round_id,
            "policy_id": self.policy_id,
            "outcome_id": self.outcome_id,
            "effective_time": self.effective_time,
            "resource_deltas": [d.to_dict() for d in self.resource_deltas],
            "costs": [c.to_dict() for c in self.costs],
            "total_cost_reference_unit": format_decimal(self.total_cost_reference_unit),
            "account_state_before_hash": self.account_state_before_hash,
            "account_state_after_hash": self.account_state_after_hash,
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())


@dataclass(frozen=True)
class BalanceItem:
    resource_id: str
    quantity: Decimal
    reserved_quantity: Decimal = field(default_factory=lambda: Decimal("0.00"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "quantity": format_decimal(self.quantity),
            "reserved_quantity": format_decimal(self.reserved_quantity),
        }


@dataclass(frozen=True)
class CumulativeCostItem:
    cost_type: str
    amount: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_type": self.cost_type,
            "amount": format_decimal(self.amount),
        }


@dataclass(frozen=True)
class ReferenceValuation:
    reference_resource_id: str
    unallocated_cash: Decimal
    allocated_resources_value: Decimal
    net_total_value: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_resource_id": self.reference_resource_id,
            "unallocated_cash": format_decimal(self.unallocated_cash),
            "allocated_resources_value": format_decimal(self.allocated_resources_value),
            "net_total_value": format_decimal(self.net_total_value),
        }


@dataclass(frozen=True)
class VirtualAccountState:
    account_state_id: str
    policy_id: str
    round_index: int
    as_of_time: str
    balances: tuple[BalanceItem, ...]
    cumulative_costs: tuple[CumulativeCostItem, ...]
    reference_valuation: ReferenceValuation
    parent_state_hash: str | None
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        parse_utc_timestamp(self.as_of_time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "$type": "virtual_account_state",
            "schema_version": self.schema_version,
            "account_state_id": self.account_state_id,
            "policy_id": self.policy_id,
            "round_index": self.round_index,
            "as_of_time": self.as_of_time,
            "balances": [b.to_dict() for b in self.balances],
            "cumulative_costs": [c.to_dict() for c in self.cumulative_costs],
            "reference_valuation": self.reference_valuation.to_dict(),
            "parent_state_hash": self.parent_state_hash,
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())


@dataclass(frozen=True)
class MetricsData:
    final_net_value: Decimal
    total_return: float
    max_drawdown: float
    volatility: float
    turnover: float
    total_transaction_costs: Decimal
    rejected_decision_count: int
    solver_call_count: int
    validation_failure_count: int
    execution_wall_time_seconds: float
    sharpe_ratio: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra", freeze_json(self.extra))

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "final_net_value": format_decimal(self.final_net_value),
            "total_return": self.total_return,
            "max_drawdown": self.max_drawdown,
            "volatility": self.volatility,
            "turnover": self.turnover,
            "total_transaction_costs": format_decimal(self.total_transaction_costs),
            "rejected_decision_count": self.rejected_decision_count,
            "solver_call_count": self.solver_call_count,
            "validation_failure_count": self.validation_failure_count,
            "execution_wall_time_seconds": self.execution_wall_time_seconds,
            "sharpe_ratio": self.sharpe_ratio,
        }
        d.update(thaw_json(self.extra))
        return d


@dataclass(frozen=True)
class MetricRecord:
    metric_record_id: str
    run_id: str
    policy_id: str
    round_index: int | None
    calculated_at: str
    metrics: MetricsData
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        parse_utc_timestamp(self.calculated_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "$type": "metric_record",
            "schema_version": self.schema_version,
            "metric_record_id": self.metric_record_id,
            "run_id": self.run_id,
            "policy_id": self.policy_id,
            "round_index": self.round_index,
            "calculated_at": self.calculated_at,
            "metrics": self.metrics.to_dict(),
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())


@dataclass(frozen=True)
class PolicyRoundRecord:
    policy_id: str
    proposed_decision_hash: str
    decision_outcome_hash: str
    transition_hash: str | None
    account_state_after_hash: str
    optees_call_receipt_hashes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "proposed_decision_hash": self.proposed_decision_hash,
            "decision_outcome_hash": self.decision_outcome_hash,
            "transition_hash": self.transition_hash,
            "account_state_after_hash": self.account_state_after_hash,
            "optees_call_receipt_hashes": list(self.optees_call_receipt_hashes),
        }


@dataclass(frozen=True)
class RoundRecord:
    round_id: str
    run_id: str
    round_index: int
    parent_round_hash: str | None
    knowledge_cutoff: str
    execution_start_time: str
    execution_end_time: str
    effective_time: str
    eligible_observation_hashes: tuple[str, ...]
    policy_round_records: tuple[PolicyRoundRecord, ...]
    state_merkle_hash: str
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        parse_utc_timestamp(self.knowledge_cutoff)
        parse_utc_timestamp(self.execution_start_time)
        parse_utc_timestamp(self.execution_end_time)
        parse_utc_timestamp(self.effective_time)

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


@dataclass(frozen=True)
class ValidationReceipt:
    status: str
    validator_version: str
    diagnostics: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "validator_version": self.validator_version,
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True)
class TimingSpec:
    submitted_at: str
    completed_at: str
    duration_ms: float

    def __post_init__(self) -> None:
        parse_utc_timestamp(self.submitted_at)
        parse_utc_timestamp(self.completed_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "submitted_at": self.submitted_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class OpteesCallReceipt:
    receipt_id: str
    round_id: str
    policy_id: str
    capability_id: str
    contract_versions: dict[str, str]
    transport: str
    request_hash: str
    response_hash: str
    validation_receipt: ValidationReceipt
    solver_status: str
    timing: TimingSpec
    redacted_transport_metadata: dict[str, Any]
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_versions", freeze_json(self.contract_versions))
        object.__setattr__(
            self, "redacted_transport_metadata", freeze_json(self.redacted_transport_metadata)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "$type": "optees_call_receipt",
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "round_id": self.round_id,
            "policy_id": self.policy_id,
            "capability_id": self.capability_id,
            "contract_versions": thaw_json(self.contract_versions),
            "transport": self.transport,
            "request_hash": self.request_hash,
            "response_hash": self.response_hash,
            "validation_receipt": self.validation_receipt.to_dict(),
            "solver_status": self.solver_status,
            "timing": self.timing.to_dict(),
            "redacted_transport_metadata": thaw_json(self.redacted_transport_metadata),
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())


@dataclass(frozen=True)
class ReplayReport:
    report_id: str
    original_run_id: str
    replay_mode: ReplayMode
    executed_at: str
    overall_status: ReplayStatus
    rounds_evaluated: int
    matched_round_count: int
    diverged_round_count: int
    initial_state_hash_match: bool
    final_state_hash_match: bool
    divergence_report_ids: tuple[str, ...]
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        parse_utc_timestamp(self.executed_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "$type": "replay_report",
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "original_run_id": self.original_run_id,
            "replay_mode": self.replay_mode.value,
            "executed_at": self.executed_at,
            "overall_status": self.overall_status.value,
            "rounds_evaluated": self.rounds_evaluated,
            "matched_round_count": self.matched_round_count,
            "diverged_round_count": self.diverged_round_count,
            "initial_state_hash_match": self.initial_state_hash_match,
            "final_state_hash_match": self.final_state_hash_match,
            "divergence_report_ids": list(self.divergence_report_ids),
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())


@dataclass(frozen=True)
class DivergenceReport:
    divergence_id: str
    replay_report_id: str
    round_index: int
    policy_id: str
    category: DivergenceCategory
    declared_epsilon: float | None
    observed_max_delta: float | None
    field_path: str | None
    original_value_hash: str
    replayed_value_hash: str
    details: dict[str, Any]
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", freeze_json(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "$type": "divergence_report",
            "schema_version": self.schema_version,
            "divergence_id": self.divergence_id,
            "replay_report_id": self.replay_report_id,
            "round_index": self.round_index,
            "policy_id": self.policy_id,
            "category": self.category.value,
            "declared_epsilon": self.declared_epsilon,
            "observed_max_delta": self.observed_max_delta,
            "field_path": self.field_path,
            "original_value_hash": self.original_value_hash,
            "replayed_value_hash": self.replayed_value_hash,
            "details": thaw_json(self.details),
        }

    def compute_hash(self) -> str:
        return compute_record_hash(self.to_dict())
