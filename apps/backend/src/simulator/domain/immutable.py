"""Deeply immutable JSON-like values for hashed domain records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class FrozenDict(dict):
    """A JSON-compatible mapping that rejects every in-place mutation."""

    def _immutable(self, *args: object, **kwargs: object) -> None:
        raise TypeError("frozen mapping cannot be mutated")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def freeze_json(value: Any) -> Any:
    """Copy a JSON-like tree into immutable mappings and tuples."""
    if isinstance(value, Mapping):
        return FrozenDict({str(key): freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    return value


def thaw_json(value: Any) -> Any:
    """Return ordinary dictionaries and lists for public JSON serialization."""
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw_json(item) for item in value]
    return value
