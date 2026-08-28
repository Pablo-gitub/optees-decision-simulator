"""Unit and contract tests for AcquisitionReceipt verification (DS-02C1 / Gate DS-D2A)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from simulator.application.services.acquisition import (
    parse_publisher_checksum_line,
    verify_acquisition_evidence,
)
from simulator.domain.models import (
    DatasetSnapshotManifest,
    SeriesCatalogItem,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
SCHEMAS_DIR = REPO_ROOT / "docs" / "contracts" / "schemas"
NORMALIZED_SNAPSHOT_BYTES = b'{"observation_id":"synthetic-normalized"}\n'

# Dynamically import validate_data from tools/validate_contracts.py to avoid schema duplication
validator_path = REPO_ROOT / "tools" / "validate_contracts.py"
spec = importlib.util.spec_from_file_location("validate_contracts", str(validator_path))
validate_contracts = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(validate_contracts)  # type: ignore[union-attr]
validate_data = validate_contracts.validate_data


def _load_schema(schema_filename: str) -> dict:
    schema_path = SCHEMAS_DIR / schema_filename
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def sample_manifest() -> DatasetSnapshotManifest:
    return DatasetSnapshotManifest(
        snapshot_id="ds-snap_binance_spot_1d_v1",
        source_uri="https://data.binance.vision/data/spot/daily/klines/",
        retrieval_time="2026-08-28T00:00:00Z",
        license="Upstream repository labelled MIT; raw archive redistribution not asserted",
        checksum_sha256=f"sha256:{hashlib.sha256(NORMALIZED_SNAPSHOT_BYTES).hexdigest()}",
        byte_size=1048576,
        format="JSONL",
        series_catalog=(
            SeriesCatalogItem(
                series_id="BTC_USDT_PRICE_1D",
                resource_id="BTC",
                unit="USDT",
                frequency="1d",
                earliest_event_time="2024-01-01T23:59:59Z",
                latest_event_time="2025-12-31T23:59:59Z",
            ),
        ),
        correction_handling=(
            "Upstream archives may be replaced; each acquisition and normalized revision "
            "is retained immutably"
        ),
    )


def test_valid_acquisition_receipt_verification(sample_manifest: DatasetSnapshotManifest) -> None:
    raw_bytes = b"sample raw binance kline zip bytes for BTCUSDT 2024-01-01"
    raw_hash_hex = hashlib.sha256(raw_bytes).hexdigest()
    filename = "BTCUSDT-1d-2024-01-01.zip"
    checksum_text = f"{raw_hash_hex}  {filename}\n"

    receipt = verify_acquisition_evidence(
        raw_bytes=raw_bytes,
        publisher_checksum_text=checksum_text,
        manifest=sample_manifest,
        provider_archive_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}",
        provider_archive_filename=filename,
        publisher_checksum_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}.CHECKSUM",
        retrieval_time="2026-08-28T00:00:00Z",
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_bytes=NORMALIZED_SNAPSHOT_BYTES,
    )

    assert receipt.verification_outcome == "ACCEPTED"
    assert receipt.failure_reasons == ()
    assert receipt.raw_artifact_sha256 == f"sha256:{raw_hash_hex}"
    assert receipt.publisher_sha256 == f"sha256:{raw_hash_hex}"
    assert receipt.raw_byte_size == len(raw_bytes)
    assert receipt.normalized_snapshot_sha256 == sample_manifest.checksum_sha256
    assert receipt.manifest_sha256 == sample_manifest.compute_hash()
    assert receipt.snapshot_id == sample_manifest.snapshot_id


def test_acquisition_receipt_schema_roundtrip(sample_manifest: DatasetSnapshotManifest) -> None:
    schema = _load_schema("acquisition_receipt.v1.json")
    raw_bytes = b"zip payload bytes"
    raw_hash_hex = hashlib.sha256(raw_bytes).hexdigest()
    filename = "BTCUSDT-1d-2024-01-01.zip"
    checksum_text = f"{raw_hash_hex}  {filename}"

    receipt = verify_acquisition_evidence(
        raw_bytes=raw_bytes,
        publisher_checksum_text=checksum_text,
        manifest=sample_manifest,
        provider_archive_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}",
        provider_archive_filename=filename,
        publisher_checksum_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}.CHECKSUM",
        retrieval_time="2026-08-28T00:00:00Z",
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_bytes=NORMALIZED_SNAPSHOT_BYTES,
    )

    receipt_dict = receipt.to_dict()
    errs = validate_data(receipt_dict, schema, path="test_receipt")
    assert not errs, f"Acquisition receipt schema errors: {errs}"


def test_publisher_checksum_parser_valid() -> None:
    h = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    fn = "BTCUSDT-1d-2024-01-01.zip"

    # Standard two spaces
    assert parse_publisher_checksum_line(f"{h}  {fn}", fn) == f"sha256:{h}"
    with pytest.raises(ValueError, match="required format"):
        parse_publisher_checksum_line(f"{h} {fn}", fn)
    with pytest.raises(ValueError, match="required format"):
        parse_publisher_checksum_line(f"{h} *{fn}\n", fn)


def test_snapshot_id_mismatch_is_detected(sample_manifest: DatasetSnapshotManifest) -> None:
    raw_bytes = b"snapshot-bound bytes"
    digest = hashlib.sha256(raw_bytes).hexdigest()
    filename = "BTCUSDT-1d-2024-01-01.zip"
    receipt = verify_acquisition_evidence(
        raw_bytes=raw_bytes,
        publisher_checksum_text=f"{digest}  {filename}",
        manifest=sample_manifest,
        provider_archive_uri=f"https://data.binance.vision/{filename}",
        provider_archive_filename=filename,
        publisher_checksum_uri=f"https://data.binance.vision/{filename}.CHECKSUM",
        retrieval_time="2026-08-28T00:00:00Z",
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_bytes=NORMALIZED_SNAPSHOT_BYTES,
        receipt_snapshot_id="ds-snap_other",
    )

    assert receipt.snapshot_id == "ds-snap_other"
    assert "SNAPSHOT_ID_MISMATCH" in receipt.failure_reasons


def test_publisher_checksum_parser_wrong_filename() -> None:
    h = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    with pytest.raises(ValueError, match="filename mismatch"):
        parse_publisher_checksum_line(f"{h}  WRONG-1d-2024-01-01.zip", "BTCUSDT-1d-2024-01-01.zip")


def test_publisher_checksum_parser_uppercase_rejected() -> None:
    h = "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855"
    fn = "BTCUSDT-1d-2024-01-01.zip"
    with pytest.raises(ValueError, match="lowercase hex"):
        parse_publisher_checksum_line(f"{h}  {fn}", fn)


def test_publisher_checksum_parser_short_hash_rejected() -> None:
    h = "e3b0c442"
    fn = "BTCUSDT-1d-2024-01-01.zip"
    with pytest.raises(ValueError, match="required format"):
        parse_publisher_checksum_line(f"{h}  {fn}", fn)


def test_publisher_checksum_parser_non_hex_rejected() -> None:
    h = "g3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    fn = "BTCUSDT-1d-2024-01-01.zip"
    with pytest.raises(ValueError, match="required format"):
        parse_publisher_checksum_line(f"{h}  {fn}", fn)


def test_publisher_checksum_parser_multiline_or_extra_content_rejected() -> None:
    h = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    fn = "BTCUSDT-1d-2024-01-01.zip"
    with pytest.raises(ValueError, match="single line"):
        parse_publisher_checksum_line(f"{h}  {fn}\nsecond line", fn)


def test_raw_byte_mutation_detected(sample_manifest: DatasetSnapshotManifest) -> None:
    raw_bytes = b"valid original bytes"
    raw_hash_hex = hashlib.sha256(raw_bytes).hexdigest()
    filename = "BTCUSDT-1d-2024-01-01.zip"
    checksum_text = f"{raw_hash_hex}  {filename}"

    mutated_bytes = b"mutated corrupted bytes"

    receipt = verify_acquisition_evidence(
        raw_bytes=mutated_bytes,
        publisher_checksum_text=checksum_text,
        manifest=sample_manifest,
        provider_archive_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}",
        provider_archive_filename=filename,
        publisher_checksum_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}.CHECKSUM",
        retrieval_time="2026-08-28T00:00:00Z",
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_bytes=NORMALIZED_SNAPSHOT_BYTES,
    )

    assert receipt.verification_outcome == "REJECTED"
    assert "RAW_CHECKSUM_MISMATCH" in receipt.failure_reasons


def test_raw_byte_size_mismatch_detected(sample_manifest: DatasetSnapshotManifest) -> None:
    raw_bytes = b"short byte string"
    raw_hash_hex = hashlib.sha256(raw_bytes).hexdigest()
    filename = "BTCUSDT-1d-2024-01-01.zip"
    checksum_text = f"{raw_hash_hex}  {filename}"

    receipt = verify_acquisition_evidence(
        raw_bytes=raw_bytes,
        publisher_checksum_text=checksum_text,
        manifest=sample_manifest,
        provider_archive_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}",
        provider_archive_filename=filename,
        publisher_checksum_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}.CHECKSUM",
        retrieval_time="2026-08-28T00:00:00Z",
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_bytes=NORMALIZED_SNAPSHOT_BYTES,
        expected_raw_byte_size=99999,  # Mismatch
    )

    assert receipt.verification_outcome == "REJECTED"
    assert "RAW_BYTE_SIZE_MISMATCH" in receipt.failure_reasons


def test_publisher_hash_differs_from_computed_raw_hash(
    sample_manifest: DatasetSnapshotManifest,
) -> None:
    raw_bytes = b"some raw archive content"
    different_hash_hex = "1111111111111111111111111111111111111111111111111111111111111111"
    filename = "BTCUSDT-1d-2024-01-01.zip"
    checksum_text = f"{different_hash_hex}  {filename}"

    receipt = verify_acquisition_evidence(
        raw_bytes=raw_bytes,
        publisher_checksum_text=checksum_text,
        manifest=sample_manifest,
        provider_archive_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}",
        provider_archive_filename=filename,
        publisher_checksum_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}.CHECKSUM",
        retrieval_time="2026-08-28T00:00:00Z",
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_bytes=NORMALIZED_SNAPSHOT_BYTES,
    )

    assert receipt.verification_outcome == "REJECTED"
    assert "RAW_CHECKSUM_MISMATCH" in receipt.failure_reasons


def test_normalized_hash_mismatch_detected(sample_manifest: DatasetSnapshotManifest) -> None:
    raw_bytes = b"raw archive content"
    raw_hash_hex = hashlib.sha256(raw_bytes).hexdigest()
    filename = "BTCUSDT-1d-2024-01-01.zip"
    checksum_text = f"{raw_hash_hex}  {filename}"

    receipt = verify_acquisition_evidence(
        raw_bytes=raw_bytes,
        publisher_checksum_text=checksum_text,
        manifest=sample_manifest,
        provider_archive_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}",
        provider_archive_filename=filename,
        publisher_checksum_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}.CHECKSUM",
        retrieval_time="2026-08-28T00:00:00Z",
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_bytes=NORMALIZED_SNAPSHOT_BYTES,
        expected_normalized_hash="sha256:9999999999999999999999999999999999999999999999999999999999999999",
    )

    assert receipt.verification_outcome == "REJECTED"
    assert "NORMALIZED_SNAPSHOT_HASH_MISMATCH" in receipt.failure_reasons
    assert receipt.normalized_snapshot_sha256 == sample_manifest.checksum_sha256


def test_missing_normalized_snapshot_evidence_is_rejected(
    sample_manifest: DatasetSnapshotManifest,
) -> None:
    raw_bytes = b"raw archive content"
    digest = hashlib.sha256(raw_bytes).hexdigest()
    filename = "BTCUSDT-1d-2024-01-01.zip"

    receipt = verify_acquisition_evidence(
        raw_bytes=raw_bytes,
        publisher_checksum_text=f"{digest}  {filename}",
        manifest=sample_manifest,
        provider_archive_uri=f"https://data.binance.vision/{filename}",
        provider_archive_filename=filename,
        publisher_checksum_uri=f"https://data.binance.vision/{filename}.CHECKSUM",
        retrieval_time="2026-08-28T00:00:00Z",
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
    )

    assert receipt.verification_outcome == "REJECTED"
    assert "NORMALIZED_SNAPSHOT_HASH_MISMATCH" in receipt.failure_reasons
    assert receipt.normalized_snapshot_sha256 is None
    assert not validate_data(
        receipt.to_dict(), _load_schema("acquisition_receipt.v1.json"), path="rejected_receipt"
    )


def test_manifest_hash_mismatch_detected(sample_manifest: DatasetSnapshotManifest) -> None:
    raw_bytes = b"raw archive content"
    raw_hash_hex = hashlib.sha256(raw_bytes).hexdigest()
    filename = "BTCUSDT-1d-2024-01-01.zip"
    checksum_text = f"{raw_hash_hex}  {filename}"

    receipt = verify_acquisition_evidence(
        raw_bytes=raw_bytes,
        publisher_checksum_text=checksum_text,
        manifest=sample_manifest,
        provider_archive_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}",
        provider_archive_filename=filename,
        publisher_checksum_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}.CHECKSUM",
        retrieval_time="2026-08-28T00:00:00Z",
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_bytes=NORMALIZED_SNAPSHOT_BYTES,
        expected_manifest_hash="sha256:9999999999999999999999999999999999999999999999999999999999999999",
    )

    assert receipt.verification_outcome == "REJECTED"
    assert "CANONICAL_MANIFEST_HASH_MISMATCH" in receipt.failure_reasons


def test_retrieval_time_formats_and_rejections(sample_manifest: DatasetSnapshotManifest) -> None:
    raw_bytes = b"data"
    raw_hash_hex = hashlib.sha256(raw_bytes).hexdigest()
    filename = "BTCUSDT-1d-2024-01-01.zip"
    checksum_text = f"{raw_hash_hex}  {filename}"

    # Missing Z
    receipt_no_z = verify_acquisition_evidence(
        raw_bytes=raw_bytes,
        publisher_checksum_text=checksum_text,
        manifest=sample_manifest,
        provider_archive_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}",
        provider_archive_filename=filename,
        publisher_checksum_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}.CHECKSUM",
        retrieval_time="2026-08-28T00:00:00",
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_bytes=NORMALIZED_SNAPSHOT_BYTES,
    )
    assert receipt_no_z.verification_outcome == "REJECTED"
    assert "INVALID_RETRIEVAL_TIME" in receipt_no_z.failure_reasons

    # Non-UTC timezone offset
    receipt_offset = verify_acquisition_evidence(
        raw_bytes=raw_bytes,
        publisher_checksum_text=checksum_text,
        manifest=sample_manifest,
        provider_archive_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}",
        provider_archive_filename=filename,
        publisher_checksum_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}.CHECKSUM",
        retrieval_time="2026-08-28T02:00:00+02:00",
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_bytes=NORMALIZED_SNAPSHOT_BYTES,
    )
    assert receipt_offset.verification_outcome == "REJECTED"
    assert "INVALID_RETRIEVAL_TIME" in receipt_offset.failure_reasons


def test_absolute_path_or_secret_rejected(sample_manifest: DatasetSnapshotManifest) -> None:
    raw_bytes = b"data"
    raw_hash_hex = hashlib.sha256(raw_bytes).hexdigest()
    filename = "BTCUSDT-1d-2024-01-01.zip"
    checksum_text = f"{raw_hash_hex}  {filename}"

    # Local file path
    receipt_path = verify_acquisition_evidence(
        raw_bytes=raw_bytes,
        publisher_checksum_text=checksum_text,
        manifest=sample_manifest,
        provider_archive_uri="/home/paolo/Projects/local.zip",
        provider_archive_filename=filename,
        publisher_checksum_uri="https://data.binance.vision/checksum",
        retrieval_time="2026-08-28T00:00:00Z",
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_bytes=NORMALIZED_SNAPSHOT_BYTES,
    )
    assert receipt_path.verification_outcome == "REJECTED"
    assert "SECRET_OR_PATH_EXPOSURE" in receipt_path.failure_reasons

    # Secret in URI
    receipt_secret = verify_acquisition_evidence(
        raw_bytes=raw_bytes,
        publisher_checksum_text=checksum_text,
        manifest=sample_manifest,
        provider_archive_uri="https://api.binance.com/archive.zip?api_key=SECRET_TOKEN_123",
        provider_archive_filename=filename,
        publisher_checksum_uri="https://data.binance.vision/checksum",
        retrieval_time="2026-08-28T00:00:00Z",
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_bytes=NORMALIZED_SNAPSHOT_BYTES,
    )
    assert receipt_secret.verification_outcome == "REJECTED"
    assert "SECRET_OR_PATH_EXPOSURE" in receipt_secret.failure_reasons


def test_identical_inputs_produce_identical_receipt_and_hash(
    sample_manifest: DatasetSnapshotManifest,
) -> None:
    raw_bytes = b"deterministic test content"
    raw_hash_hex = hashlib.sha256(raw_bytes).hexdigest()
    filename = "BTCUSDT-1d-2024-01-01.zip"
    checksum_text = f"{raw_hash_hex}  {filename}"

    r1 = verify_acquisition_evidence(
        raw_bytes=raw_bytes,
        publisher_checksum_text=checksum_text,
        manifest=sample_manifest,
        provider_archive_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}",
        provider_archive_filename=filename,
        publisher_checksum_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}.CHECKSUM",
        retrieval_time="2026-08-28T00:00:00Z",
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_bytes=NORMALIZED_SNAPSHOT_BYTES,
    )

    r2 = verify_acquisition_evidence(
        raw_bytes=raw_bytes,
        publisher_checksum_text=checksum_text,
        manifest=sample_manifest,
        provider_archive_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}",
        provider_archive_filename=filename,
        publisher_checksum_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}.CHECKSUM",
        retrieval_time="2026-08-28T00:00:00Z",
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_bytes=NORMALIZED_SNAPSHOT_BYTES,
    )

    assert r1 == r2
    assert r1.compute_hash() == r2.compute_hash()


def test_single_semantic_mutation_changes_receipt_hash(
    sample_manifest: DatasetSnapshotManifest,
) -> None:
    raw_bytes = b"content"
    raw_hash_hex = hashlib.sha256(raw_bytes).hexdigest()
    filename = "BTCUSDT-1d-2024-01-01.zip"
    checksum_text = f"{raw_hash_hex}  {filename}"

    r_base = verify_acquisition_evidence(
        raw_bytes=raw_bytes,
        publisher_checksum_text=checksum_text,
        manifest=sample_manifest,
        provider_archive_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}",
        provider_archive_filename=filename,
        publisher_checksum_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}.CHECKSUM",
        retrieval_time="2026-08-28T00:00:00Z",
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_bytes=NORMALIZED_SNAPSHOT_BYTES,
    )

    # Mutate retrieval time by 1 second
    r_mutated = verify_acquisition_evidence(
        raw_bytes=raw_bytes,
        publisher_checksum_text=checksum_text,
        manifest=sample_manifest,
        provider_archive_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}",
        provider_archive_filename=filename,
        publisher_checksum_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}.CHECKSUM",
        retrieval_time="2026-08-28T00:00:01Z",
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_bytes=NORMALIZED_SNAPSHOT_BYTES,
    )

    assert r_base.compute_hash() != r_mutated.compute_hash()
