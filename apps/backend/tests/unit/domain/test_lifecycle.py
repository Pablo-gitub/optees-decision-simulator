"""Unit tests for episode lifecycle transitions."""

import pytest

from simulator.domain.errors import InvalidLifecycleTransitionError
from simulator.domain.lifecycle import (
    LifecycleStatus,
    validate_lifecycle_transition,
)


def test_valid_lifecycle_transitions() -> None:
    assert (
        validate_lifecycle_transition(LifecycleStatus.CONFIGURED, LifecycleStatus.RUNNING)
        == LifecycleStatus.RUNNING
    )
    assert (
        validate_lifecycle_transition(LifecycleStatus.RUNNING, LifecycleStatus.PAUSED)
        == LifecycleStatus.PAUSED
    )
    assert (
        validate_lifecycle_transition(LifecycleStatus.PAUSED, LifecycleStatus.RUNNING)
        == LifecycleStatus.RUNNING
    )
    assert (
        validate_lifecycle_transition(LifecycleStatus.RUNNING, LifecycleStatus.COMPLETED)
        == LifecycleStatus.COMPLETED
    )
    assert (
        validate_lifecycle_transition(LifecycleStatus.RUNNING, LifecycleStatus.FAILED)
        == LifecycleStatus.FAILED
    )
    assert (
        validate_lifecycle_transition(LifecycleStatus.RUNNING, LifecycleStatus.CANCELLED)
        == LifecycleStatus.CANCELLED
    )
    assert (
        validate_lifecycle_transition(LifecycleStatus.PAUSED, LifecycleStatus.CANCELLED)
        == LifecycleStatus.CANCELLED
    )


def test_idempotent_lifecycle_transitions() -> None:
    assert (
        validate_lifecycle_transition(LifecycleStatus.RUNNING, LifecycleStatus.RUNNING)
        == LifecycleStatus.RUNNING
    )
    assert (
        validate_lifecycle_transition(LifecycleStatus.PAUSED, LifecycleStatus.PAUSED)
        == LifecycleStatus.PAUSED
    )


def test_invalid_lifecycle_transitions() -> None:
    with pytest.raises(InvalidLifecycleTransitionError):
        validate_lifecycle_transition(LifecycleStatus.CONFIGURED, LifecycleStatus.PAUSED)
    with pytest.raises(InvalidLifecycleTransitionError):
        validate_lifecycle_transition(LifecycleStatus.CONFIGURED, LifecycleStatus.COMPLETED)
    with pytest.raises(InvalidLifecycleTransitionError):
        validate_lifecycle_transition(LifecycleStatus.COMPLETED, LifecycleStatus.RUNNING)
    with pytest.raises(InvalidLifecycleTransitionError):
        validate_lifecycle_transition(LifecycleStatus.FAILED, LifecycleStatus.RUNNING)
    with pytest.raises(InvalidLifecycleTransitionError):
        validate_lifecycle_transition(LifecycleStatus.CANCELLED, LifecycleStatus.RUNNING)
    with pytest.raises(InvalidLifecycleTransitionError):
        validate_lifecycle_transition(LifecycleStatus.PAUSED, LifecycleStatus.CONFIGURED)
