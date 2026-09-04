"""Domain lifecycle states, enums, and transition validation."""

from __future__ import annotations

from enum import Enum

from simulator.domain.errors import InvalidLifecycleTransitionError


class LifecycleStatus(str, Enum):
    CONFIGURED = "CONFIGURED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DecisionStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED"
    FALLBACK_HOLD = "FALLBACK_HOLD"


class PendingStatus(str, Enum):
    ADMITTED_PENDING = "ADMITTED_PENDING"


class SettlementStatus(str, Enum):
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


class ReplayMode(str, Enum):
    RECORD_REPLAY = "RECORD_REPLAY"
    DETERMINISTIC_RE_EXECUTION = "DETERMINISTIC_RE_EXECUTION"
    NUMERICAL_RE_EXECUTION = "NUMERICAL_RE_EXECUTION"


class ReplayStatus(str, Enum):
    MATCH = "MATCH"
    DIVERGED = "DIVERGED"
    INCOMPATIBLE = "INCOMPATIBLE"
    FAILED = "FAILED"


class DivergenceCategory(str, Enum):
    EXACT_MATCH = "EXACT_MATCH"
    NUMERICAL_EPSILON_DEVIATION = "NUMERICAL_EPSILON_DEVIATION"
    NUMERICAL_TOLERANCE_EXCEEDED = "NUMERICAL_TOLERANCE_EXCEEDED"
    DECISION_DIVERGENCE = "DECISION_DIVERGENCE"
    VALIDATION_STATUS_CHANGE = "VALIDATION_STATUS_CHANGE"
    TIMEOUT_OR_TERMINAL_FAILURE = "TIMEOUT_OR_TERMINAL_FAILURE"
    ENVIRONMENT_INCOMPATIBILITY = "ENVIRONMENT_INCOMPATIBILITY"


class PolicyType(str, Enum):
    STATIC_BASELINE = "STATIC_BASELINE"
    REACTIVE_BASELINE = "REACTIVE_BASELINE"
    OPTEES_FORECAST_LP = "OPTEES_FORECAST_LP"
    OPTEES_QP = "OPTEES_QP"
    OPTEES_ROBUST_SCENARIO = "OPTEES_ROBUST_SCENARIO"
    OPTEES_MIQP = "OPTEES_MIQP"
    CUSTOM_FORMULATION = "CUSTOM_FORMULATION"


class ActionType(str, Enum):
    TRANSFER = "TRANSFER"
    HOLD = "HOLD"
    ADJUST = "ADJUST"
    ALLOCATE = "ALLOCATE"


class CostType(str, Enum):
    TRANSACTION_FEE = "TRANSACTION_FEE"
    HOLDING_COST = "HOLDING_COST"
    PENALTY = "PENALTY"
    BORROWING_FEE = "BORROWING_FEE"


_VALID_TRANSITIONS: dict[LifecycleStatus, set[LifecycleStatus]] = {
    LifecycleStatus.CONFIGURED: {LifecycleStatus.RUNNING},
    LifecycleStatus.RUNNING: {
        LifecycleStatus.PAUSED,
        LifecycleStatus.COMPLETED,
        LifecycleStatus.FAILED,
        LifecycleStatus.CANCELLED,
    },
    LifecycleStatus.PAUSED: {
        LifecycleStatus.RUNNING,
        LifecycleStatus.CANCELLED,
    },
    LifecycleStatus.COMPLETED: set(),
    LifecycleStatus.FAILED: set(),
    LifecycleStatus.CANCELLED: set(),
}


def validate_lifecycle_transition(
    current: LifecycleStatus | str,
    target: LifecycleStatus | str,
) -> LifecycleStatus:
    """Validate that transition from current to target status is permitted.

    Raises InvalidLifecycleTransitionError if transition is illegal.
    """
    curr_enum = LifecycleStatus(current)
    target_enum = LifecycleStatus(target)

    # Idempotent same-state transitions (e.g. running -> running, paused -> paused)
    if curr_enum == target_enum:
        return curr_enum

    allowed = _VALID_TRANSITIONS.get(curr_enum, set())
    if target_enum not in allowed:
        raise InvalidLifecycleTransitionError(
            f"Illegal lifecycle transition from {curr_enum.value} to {target_enum.value}"
        )

    return target_enum
