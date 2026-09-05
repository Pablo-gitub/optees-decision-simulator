"""Typed deferred configuration contract and strict parser (DS-02D2C1A).

Parses and strictly validates the versioned metadata block located at:
    EpisodeDefinition.metadata["deferred_settlement"]
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from simulator.domain.errors import SimulatorError
from simulator.domain.time import parse_utc_timestamp

_SHA256_PATTERN: Final[re.Pattern[str]] = re.compile(r"^sha256:[a-f0-9]{64}$")
_REQUIRED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "settlement_mode",
        "calendar_identity",
        "calendar_sha256",
        "resource_to_series_map",
        "scheduled_openings",
        "scheduled_deadlines",
        "deadline_policy",
    }
)


class DeferredConfigurationError(SimulatorError, ValueError):
    """Raised when deferred settlement configuration is malformed or violates invariants."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="INVALID_DEFERRED_CONFIGURATION")


@dataclass(frozen=True)
class DeferredConfiguration:
    """Immutable, typed specification of an episode's deferred settlement configuration."""

    schema_version: str
    settlement_mode: str
    calendar_identity: str
    calendar_sha256: str
    resource_to_series_map: Mapping[str, str]
    scheduled_openings: Mapping[str, str]
    scheduled_deadlines: Mapping[str, str]
    deadline_policy: str

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise DeferredConfigurationError(
                f"Unsupported schema_version: expected '1.0.0', got {self.schema_version!r}"
            )
        if self.settlement_mode != "deferred":
            raise DeferredConfigurationError(
                f"Unsupported settlement_mode: expected 'deferred', got {self.settlement_mode!r}"
            )
        if not isinstance(self.calendar_identity, str) or not self.calendar_identity.strip():
            raise DeferredConfigurationError("calendar_identity must be a non-empty string")
        if not isinstance(self.calendar_sha256, str) or not _SHA256_PATTERN.match(
            self.calendar_sha256
        ):
            raise DeferredConfigurationError(
                f"Invalid calendar_sha256 format: {self.calendar_sha256!r}"
            )
        if self.deadline_policy != "inclusive":
            raise DeferredConfigurationError(
                f"Unsupported deadline_policy: expected 'inclusive', got {self.deadline_policy!r}"
            )

        object.__setattr__(
            self, "resource_to_series_map", MappingProxyType(dict(self.resource_to_series_map))
        )
        object.__setattr__(
            self, "scheduled_openings", MappingProxyType(dict(self.scheduled_openings))
        )
        object.__setattr__(
            self, "scheduled_deadlines", MappingProxyType(dict(self.scheduled_deadlines))
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to a canonical dictionary representation."""
        return {
            "schema_version": self.schema_version,
            "settlement_mode": self.settlement_mode,
            "calendar_identity": self.calendar_identity,
            "calendar_sha256": self.calendar_sha256,
            "resource_to_series_map": dict(self.resource_to_series_map),
            "scheduled_openings": dict(self.scheduled_openings),
            "scheduled_deadlines": dict(self.scheduled_deadlines),
            "deadline_policy": self.deadline_policy,
        }


def _validate_non_empty_str(val: Any, field_name: str) -> str:
    if isinstance(val, bool) or not isinstance(val, str):
        raise DeferredConfigurationError(
            f"{field_name} must be a non-empty string, got {type(val).__name__}"
        )
    if not val.strip():
        raise DeferredConfigurationError(f"{field_name} must not be empty or whitespace-only")
    return val


def parse_deferred_configuration(
    raw: Any, declared_cutoffs: Sequence[str] | None = None
) -> DeferredConfiguration:
    """Parse and strictly validate a deferred configuration mapping.

    Args:
        raw: The dictionary under EpisodeDefinition.metadata["deferred_settlement"].
        declared_cutoffs: Optional sequence of declared episode calendar cutoffs.
            When provided, schedule keys must strictly match declared cutoffs.

    Returns:
        A deeply immutable, typed DeferredConfiguration instance.

    Raises:
        DeferredConfigurationError: If the configuration structure, fields, or schedule
            invariants are violated.
    """
    if isinstance(raw, bool) or not isinstance(raw, (dict, Mapping)):
        raise DeferredConfigurationError(
            f"deferred_settlement configuration must be a mapping, got {type(raw).__name__}"
        )

    actual_keys = frozenset(raw.keys())
    if actual_keys != _REQUIRED_KEYS:
        missing = sorted(_REQUIRED_KEYS - actual_keys)
        extra = sorted(actual_keys - _REQUIRED_KEYS)
        err_parts: list[str] = []
        if missing:
            err_parts.append(f"missing keys: {missing}")
        if extra:
            err_parts.append(f"unexpected extra keys: {extra}")
        raise DeferredConfigurationError(
            f"Invalid deferred configuration keys: {'; '.join(err_parts)}"
        )

    schema_version = _validate_non_empty_str(raw["schema_version"], "schema_version")
    settlement_mode = _validate_non_empty_str(raw["settlement_mode"], "settlement_mode")
    calendar_identity = _validate_non_empty_str(raw["calendar_identity"], "calendar_identity")
    calendar_sha256 = _validate_non_empty_str(raw["calendar_sha256"], "calendar_sha256")
    deadline_policy = _validate_non_empty_str(raw["deadline_policy"], "deadline_policy")

    # Validate resource_to_series_map
    res_map_raw = raw["resource_to_series_map"]
    if isinstance(res_map_raw, bool) or not isinstance(res_map_raw, (dict, Mapping)):
        raise DeferredConfigurationError("resource_to_series_map must be a mapping")
    if not res_map_raw:
        raise DeferredConfigurationError("resource_to_series_map must not be empty")

    resource_to_series: dict[str, str] = {}
    seen_series: set[str] = set()
    for k, v in res_map_raw.items():
        res_id = _validate_non_empty_str(k, "resource_to_series_map resource key")
        ser_id = _validate_non_empty_str(
            v, f"resource_to_series_map series for resource '{res_id}'"
        )
        if ser_id in seen_series:
            raise DeferredConfigurationError(
                f"Duplicate series_id '{ser_id}' in resource_to_series_map"
            )
        seen_series.add(ser_id)
        resource_to_series[res_id] = ser_id

    # Validate scheduled_openings
    openings_raw = raw["scheduled_openings"]
    if isinstance(openings_raw, bool) or not isinstance(openings_raw, (dict, Mapping)):
        raise DeferredConfigurationError("scheduled_openings must be a mapping")
    if not openings_raw:
        raise DeferredConfigurationError("scheduled_openings must not be empty")

    # Validate scheduled_deadlines
    deadlines_raw = raw["scheduled_deadlines"]
    if isinstance(deadlines_raw, bool) or not isinstance(deadlines_raw, (dict, Mapping)):
        raise DeferredConfigurationError("scheduled_deadlines must be a mapping")
    if not deadlines_raw:
        raise DeferredConfigurationError("scheduled_deadlines must not be empty")

    openings_keys = set(openings_raw.keys())
    deadlines_keys = set(deadlines_raw.keys())
    if openings_keys != deadlines_keys:
        missing_deadlines = sorted(openings_keys - deadlines_keys)
        extra_deadlines = sorted(deadlines_keys - openings_keys)
        err_parts = []
        if missing_deadlines:
            err_parts.append(f"missing in scheduled_deadlines: {missing_deadlines}")
        if extra_deadlines:
            err_parts.append(f"extra in scheduled_deadlines: {extra_deadlines}")
        raise DeferredConfigurationError(
            f"scheduled_openings and scheduled_deadlines keys mismatch: {'; '.join(err_parts)}"
        )

    # Validate against declared cutoffs if provided
    if declared_cutoffs is not None:
        declared_set = set(declared_cutoffs)
        if openings_keys != declared_set:
            missing_cutoffs = sorted(declared_set - openings_keys)
            extra_cutoffs = sorted(openings_keys - declared_set)
            err_parts = []
            if missing_cutoffs:
                err_parts.append(f"missing cutoffs in schedule: {missing_cutoffs}")
            if extra_cutoffs:
                err_parts.append(f"extra cutoffs not in calendar: {extra_cutoffs}")
            raise DeferredConfigurationError(
                f"Schedule keys do not match declared cutoffs: {'; '.join(err_parts)}"
            )

    scheduled_openings: dict[str, str] = {}
    scheduled_deadlines: dict[str, str] = {}

    for cutoff_str in sorted(openings_keys):
        _validate_non_empty_str(cutoff_str, "scheduled cutoff key")
        cutoff_dt = parse_utc_timestamp(cutoff_str)

        open_str = _validate_non_empty_str(openings_raw[cutoff_str], f"opening for {cutoff_str}")
        open_dt = parse_utc_timestamp(open_str)
        if open_dt < cutoff_dt:
            raise DeferredConfigurationError(
                f"Scheduled opening ({open_str}) cannot precede cutoff ({cutoff_str})"
            )

        deadline_str = _validate_non_empty_str(
            deadlines_raw[cutoff_str], f"deadline for {cutoff_str}"
        )
        deadline_dt = parse_utc_timestamp(deadline_str)
        if deadline_dt < open_dt:
            raise DeferredConfigurationError(
                f"Scheduled deadline ({deadline_str}) cannot precede opening ({open_str})"
            )

        scheduled_openings[cutoff_str] = open_str
        scheduled_deadlines[cutoff_str] = deadline_str

    return DeferredConfiguration(
        schema_version=schema_version,
        settlement_mode=settlement_mode,
        calendar_identity=calendar_identity,
        calendar_sha256=calendar_sha256,
        resource_to_series_map=resource_to_series,
        scheduled_openings=scheduled_openings,
        scheduled_deadlines=scheduled_deadlines,
        deadline_policy=deadline_policy,
    )


def extract_deferred_configuration(
    episode_metadata: Mapping[str, Any] | None,
    declared_cutoffs: Sequence[str] | None = None,
) -> DeferredConfiguration | None:
    """Extract deferred configuration from episode metadata if present.

    Returns None if 'deferred_settlement' is not present in metadata (synchronous mode).
    Raises DeferredConfigurationError if 'deferred_settlement' is present but invalid.
    """
    if episode_metadata is None:
        return None
    if "deferred_settlement" not in episode_metadata:
        return None
    return parse_deferred_configuration(
        episode_metadata["deferred_settlement"], declared_cutoffs=declared_cutoffs
    )
