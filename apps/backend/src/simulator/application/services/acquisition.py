"""Provider-neutral acquisition receipt verification service linking raw bytes and manifest."""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Final

from simulator.domain.errors import InvalidTimestampError
from simulator.domain.models import AcquisitionReceipt, DatasetSnapshotManifest
from simulator.domain.time import parse_utc_timestamp

# Strict Publisher Checksum Line Pattern:
# Exactly 64 lowercase hex characters, followed by 1 or 2 spaces (or optional binary flag '*'),
# followed by the exact filename without leading/trailing garbage.
CHECKSUM_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^([a-f0-9]{64})  (?P<filename>[a-zA-Z0-9_.-]+)$"
)

# Forbidden path and secret regexes
FORBIDDEN_PATH_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(^/home/|^/tmp/|^/var/|^/usr/|^file://|^[a-zA-Z]:[/\\])"
)
FORBIDDEN_SECRET_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)(api[_-]?key\s*=|secret\s*=|token\s*=|bearer\s+|password\s*=|authorization\s*:)"
)

DEFAULT_ACQUISITION_LICENSE: Final[str] = (
    "Upstream repository labelled MIT; raw archive redistribution not asserted"
)


def parse_publisher_checksum_line(text: str, expected_filename: str) -> str:
    """Parse a single raw checksum line published by an upstream data provider.

    Strict rules:
    - Exactly one single-line checksum entry.
    - Exactly 64 lowercase hexadecimal characters for the SHA-256 hash.
    - Matches expected_filename exactly (case-sensitive).
    - Rejects uppercase hashes, missing/extra columns, comments, and invalid characters.
    - Returns formatted 'sha256:{64-hex}' string.
    """
    if not isinstance(text, str):
        raise ValueError(f"Checksum text must be a string, got {type(text).__name__}")

    stripped = text.strip()
    if not stripped or "\n" in stripped or "\r" in stripped:
        raise ValueError("Publisher checksum must be a non-empty single line")

    # Check for uppercase characters before regex matching
    hash_part = stripped.split()[0] if stripped.split() else ""
    if any(c.isupper() for c in hash_part):
        raise ValueError(f"Publisher checksum hash must be strictly lowercase hex: {hash_part}")

    match = CHECKSUM_LINE_PATTERN.match(stripped)
    if not match:
        raise ValueError(f"Publisher checksum line does not match required format: {text!r}")

    digest_hex = match.group(1)
    filename = match.group("filename")

    if filename != expected_filename:
        raise ValueError(
            f"Publisher checksum filename mismatch: expected {expected_filename!r}, "
            f"got {filename!r}"
        )

    return f"sha256:{digest_hex}"


def _check_forbidden_strings(*values: str) -> list[str]:
    """Scan strings for forbidden local filesystem paths or secret credentials."""
    reasons: list[str] = []
    for val in values:
        if FORBIDDEN_PATH_PATTERN.search(val) or FORBIDDEN_SECRET_PATTERN.search(val):
            reasons.append("SECRET_OR_PATH_EXPOSURE")
            break
    return reasons


def verify_acquisition_evidence(
    raw_bytes: bytes,
    publisher_checksum_text: str,
    manifest: DatasetSnapshotManifest,
    provider_archive_uri: str,
    provider_archive_filename: str,
    publisher_checksum_uri: str,
    retrieval_time: str,
    normalizer_id: str,
    normalizer_version: str,
    expected_raw_byte_size: int | None = None,
    expected_manifest_hash: str | None = None,
    expected_normalized_hash: str | None = None,
    acquisition_id: str | None = None,
    license_str: str = DEFAULT_ACQUISITION_LICENSE,
    receipt_snapshot_id: str | None = None,
) -> AcquisitionReceipt:
    """Verify raw bytes, publisher checksum, and manifest linkage deterministically.

    This pure function performs no network or filesystem operations.
    Validates:
    - Strict UTC format for retrieval_time.
    - Prevention of local paths or secrets.
    - Constant-time comparison between locally computed raw SHA-256 and publisher SHA-256.
    - Exact linkage between receipt snapshot_id and manifest snapshot_id.
    - Exact linkage between normalized snapshot hash and manifest checksum_sha256.
    - Canonical manifest hash calculation.
    """
    failure_reasons: list[str] = []

    # 1. Validate retrieval time
    try:
        parse_utc_timestamp(retrieval_time)
    except (InvalidTimestampError, ValueError):
        failure_reasons.append("INVALID_RETRIEVAL_TIME")

    # 2. Check for secret / local path exposure
    exposure_reasons = _check_forbidden_strings(
        provider_archive_uri,
        provider_archive_filename,
        publisher_checksum_uri,
    )
    failure_reasons.extend(exposure_reasons)

    # 3. Validate archive filename format
    if not re.match(r"^[a-zA-Z0-9_.-]+$", provider_archive_filename):
        failure_reasons.append("INVALID_FILENAME")

    # 4. Compute raw artifact SHA-256 and byte size
    raw_byte_size = len(raw_bytes)
    if raw_byte_size < 1:
        failure_reasons.append("RAW_BYTE_SIZE_MISMATCH")
    elif expected_raw_byte_size is not None and raw_byte_size != expected_raw_byte_size:
        failure_reasons.append("RAW_BYTE_SIZE_MISMATCH")

    raw_artifact_sha256 = f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"

    # 5. Parse publisher checksum line
    try:
        publisher_sha256 = parse_publisher_checksum_line(
            publisher_checksum_text, provider_archive_filename
        )
    except ValueError:
        publisher_sha256 = None
        failure_reasons.append("PUBLISHER_CHECKSUM_PARSE_ERROR")

    # 6. Constant-time comparison of raw hashes
    if "PUBLISHER_CHECKSUM_PARSE_ERROR" not in failure_reasons:
        if not hmac.compare_digest(publisher_sha256, raw_artifact_sha256):
            failure_reasons.append("RAW_CHECKSUM_MISMATCH")

    # 7. Validate manifest linkage and snapshot ID
    snapshot_id = receipt_snapshot_id or manifest.snapshot_id
    if snapshot_id != manifest.snapshot_id:
        failure_reasons.append("SNAPSHOT_ID_MISMATCH")

    normalized_snapshot_sha256 = manifest.checksum_sha256
    if expected_normalized_hash is not None and not hmac.compare_digest(
        normalized_snapshot_sha256, expected_normalized_hash
    ):
        failure_reasons.append("NORMALIZED_SNAPSHOT_HASH_MISMATCH")

    # 8. Compute canonical manifest hash
    computed_manifest_sha256 = manifest.compute_hash()
    if expected_manifest_hash is not None and not hmac.compare_digest(
        computed_manifest_sha256, expected_manifest_hash
    ):
        failure_reasons.append("CANONICAL_MANIFEST_HASH_MISMATCH")

    # 9. Determine verification outcome
    outcome = "ACCEPTED" if not failure_reasons else "REJECTED"

    # 10. Generate deterministic acquisition ID if not supplied
    if not acquisition_id:
        digest_suffix = raw_artifact_sha256[7:19]
        acq_id = f"acq_{snapshot_id}_{digest_suffix}"
    else:
        acq_id = acquisition_id

    # Deduplicate failure reasons preserving order
    unique_reasons = tuple(dict.fromkeys(failure_reasons))

    return AcquisitionReceipt(
        acquisition_id=acq_id,
        snapshot_id=snapshot_id,
        provider_archive_uri=provider_archive_uri,
        provider_archive_filename=provider_archive_filename,
        publisher_checksum_uri=publisher_checksum_uri,
        retrieval_time=retrieval_time,
        publisher_sha256=publisher_sha256,
        raw_artifact_sha256=raw_artifact_sha256,
        raw_byte_size=raw_byte_size,
        normalizer_id=normalizer_id,
        normalizer_version=normalizer_version,
        normalized_snapshot_sha256=normalized_snapshot_sha256,
        manifest_sha256=computed_manifest_sha256,
        verification_outcome=outcome,
        failure_reasons=unique_reasons,
        license=license_str,
    )
