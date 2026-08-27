"""Unit tests for RFC 8785 canonicalization and hashing."""

from decimal import Decimal

import pytest

from simulator.domain.canonical import (
    canonicalize_json,
    compute_record_hash,
    compute_state_merkle_hash,
    format_decimal,
)
from simulator.domain.errors import NonFiniteNumberError


def test_canonical_json_primitives() -> None:
    assert canonicalize_json(None) == "null"
    assert canonicalize_json(True) == "true"
    assert canonicalize_json(False) == "false"
    assert canonicalize_json(123) == "123"
    assert canonicalize_json(0) == "0"
    assert canonicalize_json(-100) == "-100"


def test_canonical_json_rfc8785_number_vectors() -> None:
    vectors = [
        (0.0, "0"),
        (-0.0, "0"),
        (5e-324, "5e-324"),
        (-5e-324, "-5e-324"),
        (1.7976931348623157e308, "1.7976931348623157e+308"),
        (333333333.33333329, "333333333.3333333"),
        (1e30, "1e+30"),
        (4.5, "4.5"),
        (0.002, "0.002"),
        (1e-27, "1e-27"),
        (1e-6, "0.000001"),
        (1e20, "100000000000000000000"),
        (295147905179352825856.0, "295147905179352830000"),
    ]
    for val, expected in vectors:
        assert canonicalize_json(val) == expected


def test_canonical_json_rejects_non_finite() -> None:
    with pytest.raises(NonFiniteNumberError):
        canonicalize_json(float("nan"))
    with pytest.raises(NonFiniteNumberError):
        canonicalize_json(float("inf"))
    with pytest.raises(NonFiniteNumberError):
        canonicalize_json(float("-inf"))


def test_canonical_json_decimal_formatting() -> None:
    assert format_decimal(Decimal("100.50")) == "100.50"
    assert format_decimal(Decimal("-2003.00")) == "-2003.00"
    assert format_decimal(Decimal("0.00000123")) == "0.00000123"
    assert format_decimal(Decimal("0")) == "0"
    assert format_decimal(Decimal("12345")) == "12345"


def test_canonical_json_key_order_invariance() -> None:
    obj1 = {"z": 1, "a": 2, "m": {"k2": 3, "k1": 4}, "arr": [1, 2]}
    obj2 = {"arr": [1, 2], "a": 2, "m": {"k1": 4, "k2": 3}, "z": 1}
    assert canonicalize_json(obj1) == canonicalize_json(obj2)
    assert compute_record_hash(obj1) == compute_record_hash(obj2)


def test_canonical_json_hash_sensitivity() -> None:
    obj1 = {"a": "test", "b": 100}
    obj2 = {"a": "test", "b": 101}
    assert compute_record_hash(obj1) != compute_record_hash(obj2)


def test_canonical_json_unicode_preservation() -> None:
    # RFC 8785 preserves Unicode strings as-is without re-normalization
    s1 = "e\u0301"  # decomposed e + combining acute
    s2 = "é"  # precomposed é
    assert canonicalize_json(s1) != canonicalize_json(s2)


def test_state_merkle_hash() -> None:
    h1 = compute_state_merkle_hash("sha256:0000", ["sha256:1111", "sha256:2222"])
    h2 = compute_state_merkle_hash("sha256:0000", ["sha256:2222", "sha256:1111"])
    assert h1 == h2
    assert h1.startswith("sha256:")
