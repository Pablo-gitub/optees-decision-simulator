"""RFC 8785 JSON Canonicalization Scheme (JCS) and cryptographic hashing."""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any

from simulator.domain.errors import NonFiniteNumberError


def canonicalize_json(obj: Any) -> str:
    """Serialize a Python object to an RFC 8785 compliant canonical JSON string."""
    if obj is None:
        return "null"
    elif isinstance(obj, bool):
        return "true" if obj else "false"
    elif isinstance(obj, int):
        if abs(obj) > 9_007_199_254_740_992:
            raise ValueError("JCS numbers must be exactly representable as IEEE 754 doubles")
        return str(obj)
    elif isinstance(obj, float):
        if not math.isfinite(obj):
            raise NonFiniteNumberError(f"Non-finite float value is forbidden by RFC 8785: {obj}")
        return _serialize_ecmascript_number(obj)
    elif isinstance(obj, Decimal):
        # Decimal objects in domain models are exact; serialize as decimal string
        return json.dumps(format_decimal(obj), ensure_ascii=False, separators=(",", ":"))
    elif isinstance(obj, str):
        _reject_lone_surrogates(obj)
        # Note: RFC 8785 preserves Unicode strings as-is without re-normalization,
        # but rejects lone surrogates.
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    elif isinstance(obj, (list, tuple)):
        return "[" + ",".join(canonicalize_json(item) for item in obj) + "]"
    elif isinstance(obj, dict):

        def utf16_key(k: str) -> bytes:
            if not isinstance(k, str):
                raise TypeError(f"JCS object keys must be strings, got {type(k).__name__}")
            _reject_lone_surrogates(k)
            return k.encode("utf-16-be")

        sorted_keys = sorted(obj.keys(), key=utf16_key)
        parts = []
        for k in sorted_keys:
            key_str = json.dumps(k, ensure_ascii=False)
            val_str = canonicalize_json(obj[k])
            parts.append(f"{key_str}:{val_str}")
        return "{" + ",".join(parts) + "}"
    elif hasattr(obj, "to_dict") and callable(obj.to_dict):
        return canonicalize_json(obj.to_dict())
    else:
        raise TypeError(f"Unsupported data type for JSON canonicalization: {type(obj).__name__}")


def _reject_lone_surrogates(value: str) -> None:
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError("JCS forbids lone Unicode surrogate code points")


def _serialize_ecmascript_number(value: float) -> str:
    """Render a finite binary64 using ECMAScript/JCS exponent thresholds."""
    if value == 0.0:
        return "0"

    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    rendered = repr(magnitude).lower()
    if "e" in rendered:
        mantissa, exponent_text = rendered.split("e", 1)
        exponent = int(exponent_text)
        digits = mantissa.replace(".", "")
        decimal_position = 1 + exponent
    else:
        digits = rendered.replace(".", "")
        decimal_position = rendered.find(".") if "." in rendered else len(rendered)

    if 1e-6 <= magnitude < 1e21:
        if decimal_position <= 0:
            body = "0." + ("0" * -decimal_position) + digits
        elif decimal_position >= len(digits):
            body = digits + ("0" * (decimal_position - len(digits)))
        else:
            body = digits[:decimal_position] + "." + digits[decimal_position:]
        return sign + body

    exponent = decimal_position - 1
    mantissa = digits[0] + (("." + digits[1:]) if len(digits) > 1 else "")
    exponent_sign = "+" if exponent >= 0 else "-"
    return f"{sign}{mantissa}e{exponent_sign}{abs(exponent)}"


def compute_record_hash(obj: Any) -> str:
    """Compute SHA-256 hash over RFC 8785 canonical JSON UTF-8 bytes."""
    canonical_str = canonicalize_json(obj)
    digest = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def compute_state_merkle_hash(
    parent_hash: str | None,
    item_hashes: list[str],
) -> str:
    """Compute Merkle state hash linking a parent hash with round item hashes."""
    combined = {
        "$type": "state_merkle_node",
        "parent_hash": parent_hash,
        "item_hashes": sorted(item_hashes),
    }
    return compute_record_hash(combined)


def format_decimal(d: Decimal) -> str:
    """Format Decimal into canonical string matching regex ^-?\\d+(\\.\\d+)?$."""
    # Normalize string format: avoid scientific notation and trailing unneeded decimal points
    if d.is_nan() or d.is_infinite():
        raise NonFiniteNumberError(f"Cannot format non-finite Decimal: {d}")
    sign, digits, exponent = d.as_tuple()
    if exponent == 0:
        s = "".join(str(digit) for digit in digits)
        if not s:
            s = "0"
        return ("-" if sign else "") + s
    elif exponent > 0:
        s = "".join(str(digit) for digit in digits) + ("0" * exponent)
        return ("-" if sign else "") + (s if s else "0")
    else:
        # exponent < 0
        s_digits = "".join(str(digit) for digit in digits)
        needed_zeros = (-exponent) - len(s_digits)
        if needed_zeros >= 0:
            s = "0." + ("0" * needed_zeros) + s_digits
        else:
            split_pos = len(s_digits) + exponent
            s = s_digits[:split_pos] + "." + s_digits[split_pos:]
        return ("-" if sign else "") + s
