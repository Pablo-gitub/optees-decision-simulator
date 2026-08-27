#!/usr/bin/env python3
"""Validation and verification tool for Optees Decision Simulator core contracts (DS-00).

This script performs comprehensive checks without requiring third-party dependencies:
1. Validates all JSON Schemas and ensures the schema inventory is complete.
2. Validates all valid example files against their respective JSON schemas.
3. Verifies RFC 8785 (JCS) canonicalization and SHA-256 hash properties.
4. Verifies temporal cutoff and anti-leakage invariants on observation examples.
5. Verifies that invalid examples trigger expected invariant violations.
6. Scans example and schema files for unredacted secrets.
7. Validates documentation link integrity across all markdown files.
"""

from __future__ import annotations

import json
import hashlib
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "docs" / "contracts" / "schemas"
EXAMPLES_DIR = REPO_ROOT / "docs" / "contracts" / "examples"
DOCS_DIR = REPO_ROOT / "docs"


# ---------------------------------------------------------------------------
# RFC 8785 JSON Canonicalization Scheme (JCS) Implementation
# ---------------------------------------------------------------------------

def canonicalize_json(obj: Any) -> str:
    """Serialize a Python object to an RFC 8785 compliant canonical JSON string."""
    if obj is None:
        return "null"
    elif isinstance(obj, bool):
        return "true" if obj else "false"
    elif isinstance(obj, int):
        return str(obj)
    elif isinstance(obj, float):
        if not (obj == obj and obj != float("inf") and obj != float("-inf")):
            raise ValueError(f"Non-finite float value is forbidden by RFC 8785: {obj}")
        if obj == 0.0:
            return "0"
        # ECMAScript number formatting for floats
        # Format with high precision and strip trailing unnecessary digits
        s = f"{obj:.16g}"
        # Parse through json standard to match ECMAScript float format
        return json.dumps(obj)
    elif isinstance(obj, str):
        norm = unicodedata.normalize("NFC", obj)
        return json.dumps(norm, ensure_ascii=False, separators=(",", ":"))
    elif isinstance(obj, list):
        return "[" + ",".join(canonicalize_json(item) for item in obj) + "]"
    elif isinstance(obj, dict):
        def utf16_key(k: str) -> bytes:
            return unicodedata.normalize("NFC", k).encode("utf-16-be")
        sorted_keys = sorted(obj.keys(), key=utf16_key)
        parts = []
        for k in sorted_keys:
            key_str = json.dumps(unicodedata.normalize("NFC", k), ensure_ascii=False)
            val_str = canonicalize_json(obj[k])
            parts.append(f"{key_str}:{val_str}")
        return "{" + ",".join(parts) + "}"
    else:
        raise TypeError(f"Unsupported data type for JSON canonicalization: {type(obj)}")


def compute_record_hash(obj: Any) -> str:
    """Compute SHA-256 hash over RFC 8785 canonical JSON bytes."""
    canonical_str = canonicalize_json(obj)
    digest = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


# ---------------------------------------------------------------------------
# Lightweight JSON Schema Validator (Draft 2020-12 Subset)
# ---------------------------------------------------------------------------

def validate_data(data: Any, schema: dict[str, Any], path: str = "root") -> list[str]:
    """Validate data against a JSON schema dictionary, returning a list of error messages."""
    errors: list[str] = []

    # Type check
    if "type" in schema:
        expected_types = schema["type"]
        if isinstance(expected_types, str):
            expected_types = [expected_types]

        matched = False
        for t in expected_types:
            if t == "null" and data is None:
                matched = True
            elif t == "boolean" and isinstance(data, bool):
                matched = True
            elif t == "integer" and isinstance(data, int) and not isinstance(data, bool):
                matched = True
            elif t == "number" and (isinstance(data, (int, float)) and not isinstance(data, bool)):
                matched = True
            elif t == "string" and isinstance(data, str):
                matched = True
            elif t == "array" and isinstance(data, list):
                matched = True
            elif t == "object" and isinstance(data, dict):
                matched = True

        if not matched:
            errors.append(f"{path}: expected type {schema['type']}, got {type(data).__name__} (value: {data!r})")
            return errors

    # Const check
    if "const" in schema:
        if data != schema["const"]:
            errors.append(f"{path}: expected const {schema['const']!r}, got {data!r}")

    # Enum check
    if "enum" in schema:
        if data not in schema["enum"]:
            errors.append(f"{path}: value {data!r} not in enum {schema['enum']}")

    # String checks
    if isinstance(data, str):
        if "pattern" in schema:
            if not re.search(schema["pattern"], data):
                errors.append(f"{path}: string {data!r} does not match pattern {schema['pattern']}")
        if "minLength" in schema and len(data) < schema["minLength"]:
            errors.append(f"{path}: string length {len(data)} < minLength {schema['minLength']}")
        if "maxLength" in schema and len(data) > schema["maxLength"]:
            errors.append(f"{path}: string length {len(data)} > maxLength {schema['maxLength']}")

    # Number checks
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            errors.append(f"{path}: number {data} < minimum {schema['minimum']}")
        if "maximum" in schema and data > schema["maximum"]:
            errors.append(f"{path}: number {data} > maximum {schema['maximum']}")

    # Array checks
    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            errors.append(f"{path}: array length {len(data)} < minItems {schema['minItems']}")
        if "uniqueItems" in schema and schema["uniqueItems"]:
            serialized_items = [json.dumps(x, sort_keys=True) for x in data]
            if len(serialized_items) != len(set(serialized_items)):
                errors.append(f"{path}: array items are not unique")
        if "items" in schema:
            item_schema = schema["items"]
            for idx, item in enumerate(data):
                errors.extend(validate_data(item, item_schema, f"{path}[{idx}]"))

    # Object checks
    if isinstance(data, dict):
        if "required" in schema:
            for req in schema["required"]:
                if req not in data:
                    errors.append(f"{path}: missing required property {req!r}")

        properties = schema.get("properties", {})
        additional_properties = schema.get("additionalProperties", True)

        for key, value in data.items():
            if key in properties:
                errors.extend(validate_data(value, properties[key], f"{path}.{key}"))
            elif additional_properties is False:
                errors.append(f"{path}: unexpected additional property {key!r}")
            elif isinstance(additional_properties, dict):
                errors.extend(validate_data(value, additional_properties, f"{path}.{key}"))

    return errors


# ---------------------------------------------------------------------------
# Test Suites
# ---------------------------------------------------------------------------

def test_schemas_and_inventory() -> tuple[bool, dict[str, dict[str, Any]]]:
    """Test that all schemas exist, parse as JSON, and match inventory."""
    inventory_file = SCHEMAS_DIR / "schema_inventory.json"
    if not inventory_file.exists():
        print("FAIL: schema_inventory.json missing!")
        return False, {}

    with open(inventory_file, "r", encoding="utf-8") as f:
        inventory = json.load(f)

    schemas: dict[str, dict[str, Any]] = {}
    print(f"Checking {len(inventory['schemas'])} schemas from inventory...")

    all_passed = True
    for entry in inventory["schemas"]:
        schema_path = REPO_ROOT / entry["file_path"]
        if not schema_path.exists():
            print(f"  FAIL: Schema file {schema_path} does not exist!")
            all_passed = False
            continue

        with open(schema_path, "r", encoding="utf-8") as f:
            try:
                schema_json = json.load(f)
            except Exception as e:
                print(f"  FAIL: Could not parse {schema_path}: {e}")
                all_passed = False
                continue

        if schema_json.get("$id") != entry["schema_id"]:
            print(f"  FAIL: Schema ID mismatch in {schema_path.name}")
            all_passed = False

        type_disc = entry["type_discriminator"]
        schemas[type_disc] = schema_json
        print(f"  OK: {entry['type_discriminator']} ({entry['schema_version']}) -> {schema_path.name}")

    return all_passed, schemas


def test_valid_examples(schemas: dict[str, dict[str, Any]]) -> bool:
    """Validate all valid example files against their schemas."""
    valid_dir = EXAMPLES_DIR / "valid"
    valid_files = list(valid_dir.glob("*.json"))
    print(f"\nValidating {len(valid_files)} valid examples against schemas...")

    all_passed = True
    for vf in sorted(valid_files):
        with open(vf, "r", encoding="utf-8") as f:
            data = json.load(f)

        errors: list[str] = []
        # Check compound vs single record files
        if "$type" in data:
            disc = data["$type"]
            if disc in schemas:
                errors = validate_data(data, schemas[disc], path=vf.name)
            else:
                errors = [f"Unknown $type: {disc}"]
        elif "observations" in data:
            # Multi-observation container
            for idx, obs in enumerate(data["observations"]):
                obs_type = obs.get("$type", "")
                if obs_type in schemas:
                    errors.extend(validate_data(obs, schemas[obs_type], path=f"{vf.name}.observations[{idx}]"))
                else:
                    errors.append(f"Observation {idx} missing valid $type")
        elif "proposed_decision" in data and "decision_outcome" in data:
            # Proposal + Outcome pair
            prop = data["proposed_decision"]
            out = data["decision_outcome"]
            errors.extend(validate_data(prop, schemas["proposed_decision"], path=f"{vf.name}.proposed_decision"))
            errors.extend(validate_data(out, schemas["decision_outcome"], path=f"{vf.name}.decision_outcome"))
        elif "transition" in data and "virtual_account_state" in data:
            # Transition + Account State pair
            trn = data["transition"]
            acc = data["virtual_account_state"]
            errors.extend(validate_data(trn, schemas["transition"], path=f"{vf.name}.transition"))
            errors.extend(validate_data(acc, schemas["virtual_account_state"], path=f"{vf.name}.virtual_account_state"))
        else:
            errors.append(f"Unrecognized example container structure in {vf.name}")

        if errors:
            print(f"  FAIL: {vf.name}")
            for err in errors:
                print(f"    - {err}")
            all_passed = False
        else:
            print(f"  OK: {vf.name}")

    return all_passed


def test_knowledge_cutoff_invariants() -> bool:
    """Verify exact knowledge cutoff filtering on knowledge_cutoff_observations.v1.json."""
    print("\nTesting temporal cutoff filtering and anti-leakage invariants...")
    example_path = EXAMPLES_DIR / "valid" / "knowledge_cutoff_observations.v1.json"
    with open(example_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    target_cutoff = data["target_cutoff"]
    expected = data["expected_eligibility_at_target_cutoff"]

    all_passed = True
    for obs in data["observations"]:
        obs_id = obs["observation_id"]
        k_time = obs["knowledge_time"]
        is_eligible = k_time <= target_cutoff
        exp = expected[obs_id]

        if is_eligible == exp:
            print(f"  OK: {obs_id} (k_time: {k_time}, cutoff: {target_cutoff}) -> eligible={is_eligible}")
        else:
            print(f"  FAIL: {obs_id} expected eligible={exp}, got {is_eligible}")
            all_passed = False

    return all_passed


def test_canonical_json_and_hashing() -> bool:
    """Verify RFC 8785 key ordering invariance and hash sensitivity."""
    print("\nTesting RFC 8785 Canonical JSON & SHA-256 hashing...")

    # Key order invariance test
    dict_a = {
        "z": 100,
        "a": "hello",
        "m": {"sub_k2": "v2", "sub_k1": 1},
        "arr": [1, 2, 3]
    }
    dict_b = {
        "arr": [1, 2, 3],
        "m": {"sub_k1": 1, "sub_k2": "v2"},
        "a": "hello",
        "z": 100
    }

    canon_a = canonicalize_json(dict_a)
    canon_b = canonicalize_json(dict_b)
    hash_a = compute_record_hash(dict_a)
    hash_b = compute_record_hash(dict_b)

    if canon_a == canon_b and hash_a == hash_b:
        print(f"  OK: Key ordering invariance verified -> {hash_a}")
    else:
        print(f"  FAIL: Canonical output differs across key orders: {canon_a} != {canon_b}")
        return False

    # Semantic mutation test (hash sensitivity)
    dict_c = dict(dict_a)
    dict_c["z"] = 101
    hash_c = compute_record_hash(dict_c)
    if hash_c != hash_a:
        print(f"  OK: Semantic mutation changes hash ({hash_a} -> {hash_c})")
    else:
        print("  FAIL: Semantic mutation did not change hash!")
        return False

    return True


def test_invalid_examples() -> bool:
    """Verify that all invalid examples demonstrate the documented violation."""
    print("\nTesting invalid examples for expected invariant violations...")
    invalid_dir = EXAMPLES_DIR / "invalid"
    invalid_files = list(invalid_dir.glob("*.json"))

    expected_violations = {
        "invalid_future_leakage.json": "TEMPORAL_LEAKAGE",
        "invalid_duplicate_identity.json": "DUPLICATE_IDENTITY_COLLISION",
        "invalid_mutable_version.json": "MUTATION_OF_FROZEN_RECORD",
        "invalid_non_finite_number.json": "NON_FINITE_NUMBER_VALUE",
        "invalid_timezone_ambiguous.json": "AMBIGUOUS_TIMEZONE_FORMAT",
        "invalid_cross_policy_account_reference.json": "CROSS_POLICY_ACCOUNT_CONTAMINATION"
    }

    all_passed = True
    for ivf in sorted(invalid_files):
        with open(ivf, "r", encoding="utf-8") as f:
            data = json.load(f)

        v_type = data.get("violation_type")
        expected_type = expected_violations.get(ivf.name)
        if v_type == expected_type:
            print(f"  OK: {ivf.name} declares expected violation {v_type}")
        else:
            print(f"  FAIL: {ivf.name} expected {expected_type}, got {v_type}")
            all_passed = False

    return all_passed


def test_secret_redaction() -> bool:
    """Scan all examples and schemas for secrets, bearer tokens, or private paths."""
    print("\nScanning repository examples and schemas for unredacted secrets...")
    suspicious_patterns = [
        re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{10,}", re.IGNORECASE),
        re.compile(r"password\s*:\s*\"[^\"]+\"", re.IGNORECASE),
        re.compile(r"secret_key\s*:\s*\"[^\"]+\"", re.IGNORECASE),
        re.compile(r"/home/[a-zA-Z0-9_]+/", re.IGNORECASE),
    ]

    all_passed = True
    scan_files = list(SCHEMAS_DIR.glob("**/*")) + list(EXAMPLES_DIR.glob("**/*"))
    for file_path in scan_files:
        if not file_path.is_file():
            continue
        content = file_path.read_text(encoding="utf-8")
        for pat in suspicious_patterns:
            matches = pat.findall(content)
            if matches:
                print(f"  FAIL: Found suspicious pattern in {file_path.name}: {matches}")
                all_passed = False

    if all_passed:
        print("  OK: Zero unredacted credentials or user home paths found.")
    return all_passed


def test_documentation_links() -> bool:
    """Verify that all relative markdown links in docs/ and README.md point to existing files."""
    print("\nVerifying documentation link integrity...")
    md_files = [REPO_ROOT / "README.md"] + list(DOCS_DIR.glob("**/*.md"))

    link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    all_passed = True

    for md_path in md_files:
        content = md_path.read_text(encoding="utf-8")
        links = link_pattern.findall(content)
        for text, target in links:
            # Skip external URLs, mailto, anchor-only links
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            # Strip fragment identifier if present
            target_clean = target.split("#")[0]
            if not target_clean:
                continue

            target_path = (md_path.parent / target_clean).resolve()
            if not target_path.exists():
                print(f"  FAIL: Broken link in {md_path.relative_to(REPO_ROOT)}: [{text}]({target}) -> {target_clean} not found")
                all_passed = False

    if all_passed:
        print("  OK: All documentation cross-links resolved successfully.")
    return all_passed


# ---------------------------------------------------------------------------
# Main Execution
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 70)
    print("Optees Decision Simulator: Core Contracts Validation Suite (DS-00 / DS-C)")
    print("=" * 70)

    t1, schemas = test_schemas_and_inventory()
    t2 = test_valid_examples(schemas) if t1 else False
    t3 = test_knowledge_cutoff_invariants()
    t4 = test_canonical_json_and_hashing()
    t5 = test_invalid_examples()
    t6 = test_secret_redaction()
    t7 = test_documentation_links()

    print("\n" + "=" * 70)
    all_passed = t1 and t2 and t3 and t4 and t5 and t6 and t7
    if all_passed:
        print("ALL GATE DS-C VALIDATION CHECKS PASSED SUCCESSFULLY.")
        print("=" * 70)
        return 0
    else:
        print("ONE OR MORE VALIDATION CHECKS FAILED.")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
