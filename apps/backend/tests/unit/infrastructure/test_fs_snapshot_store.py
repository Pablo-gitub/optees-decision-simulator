"""Unit tests for the immutable filesystem snapshot store (DS-02C2B / Gate DS-D2B)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from simulator.application.ports.snapshot_store import StoredAcquisitionPackage
from simulator.domain.errors import SnapshotStoreError
from simulator.domain.models import AcquisitionReceipt
from simulator.infrastructure.adapters.fs_snapshot_store import (
    FileSystemSnapshotStore,
    SnapshotStoreFailureInjector,
)


def _create_test_package(
    raw_bytes: bytes = b"RAW_ZIP_PAYLOAD_12345",
    normalized_bytes: bytes = b'{"obs":"1"}\n{"obs":"2"}',
    snapshot_id: str = "ds-snap_test_v1",
    acquisition_id: str = "acq_test_v1_0001",
    outcome: str = "ACCEPTED",
    failure_reasons: tuple[str, ...] = (),
) -> StoredAcquisitionPackage:
    raw_sha = f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"
    norm_sha = f"sha256:{hashlib.sha256(normalized_bytes).hexdigest()}"
    receipt = AcquisitionReceipt(
        acquisition_id=acquisition_id,
        snapshot_id=snapshot_id,
        provider_archive_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{acquisition_id}.zip",
        provider_archive_filename=f"{acquisition_id}.zip",
        publisher_checksum_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{acquisition_id}.zip.CHECKSUM",
        retrieval_time="2026-08-28T00:00:00Z",
        publisher_sha256=raw_sha,
        raw_artifact_sha256=raw_sha,
        raw_byte_size=len(raw_bytes),
        normalizer_id="generic_test_normalizer",
        normalizer_version="1.0.0",
        normalized_snapshot_sha256=norm_sha,
        manifest_sha256="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        verification_outcome=outcome,
        failure_reasons=failure_reasons,
        license="Upstream repository labelled MIT; raw archive redistribution not asserted",
    )
    return StoredAcquisitionPackage(
        receipt=receipt,
        raw_bytes=raw_bytes,
        normalized_bytes=normalized_bytes,
    )


def test_publish_and_verified_reopen(tmp_path: Path) -> None:
    store = FileSystemSnapshotStore(tmp_path)
    pkg = _create_test_package()

    assert not store.exists(pkg.receipt.acquisition_id, pkg.receipt.snapshot_id)
    store.store(pkg)
    assert store.exists(pkg.receipt.acquisition_id, pkg.receipt.snapshot_id)

    loaded = store.load(pkg.receipt.acquisition_id, pkg.receipt.snapshot_id)
    assert loaded.receipt == pkg.receipt
    assert loaded.raw_bytes == pkg.raw_bytes
    assert loaded.normalized_bytes == pkg.normalized_bytes


def test_repeated_reopen_determinism(tmp_path: Path) -> None:
    store = FileSystemSnapshotStore(tmp_path)
    pkg = _create_test_package()
    store.store(pkg)

    l1 = store.load(pkg.receipt.acquisition_id, pkg.receipt.snapshot_id)
    l2 = store.load(pkg.receipt.acquisition_id, pkg.receipt.snapshot_id)
    assert l1 == l2


def test_idempotent_republish_identical_content(tmp_path: Path) -> None:
    store = FileSystemSnapshotStore(tmp_path)
    pkg = _create_test_package()

    store.store(pkg)
    # Storing identical package a second time succeeds idempotently
    store.store(pkg)

    loaded = store.load(pkg.receipt.acquisition_id, pkg.receipt.snapshot_id)
    assert loaded.raw_bytes == pkg.raw_bytes


def test_collision_and_overwrite_forbidden(tmp_path: Path) -> None:
    store = FileSystemSnapshotStore(tmp_path)
    pkg1 = _create_test_package(raw_bytes=b"ORIGINAL_BYTES_111")
    store.store(pkg1)

    # Attempt to overwrite with different raw bytes under same IDs
    pkg2 = _create_test_package(raw_bytes=b"DIFFERENT_BYTES_222")
    with pytest.raises(SnapshotStoreError) as exc_info:
        store.store(pkg2)
    assert exc_info.value.code == "OVERWRITE_FORBIDDEN"


def test_unaccepted_receipt_rejected(tmp_path: Path) -> None:
    store = FileSystemSnapshotStore(tmp_path)
    pkg = _create_test_package(
        outcome="REJECTED",
        failure_reasons=("RAW_CHECKSUM_MISMATCH",),
    )

    with pytest.raises(SnapshotStoreError) as exc_info:
        store.store(pkg)
    assert exc_info.value.code == "RECEIPT_NOT_ACCEPTED"


def test_raw_hash_mismatch_rejected(tmp_path: Path) -> None:
    store = FileSystemSnapshotStore(tmp_path)
    valid_pkg = _create_test_package()
    # Mutate raw bytes in package while keeping receipt untouched
    tampered_pkg = StoredAcquisitionPackage(
        receipt=valid_pkg.receipt,
        raw_bytes=b"TAMPERED_RAW_BYTES_DIFFERENT",
        normalized_bytes=valid_pkg.normalized_bytes,
    )

    with pytest.raises(SnapshotStoreError) as exc_info:
        store.store(tampered_pkg)
    assert exc_info.value.code in ("RAW_HASH_MISMATCH", "RAW_SIZE_MISMATCH")


def test_malicious_identifiers_rejected(tmp_path: Path) -> None:
    store = FileSystemSnapshotStore(tmp_path)

    # Traversal in snapshot_id
    with pytest.raises(SnapshotStoreError) as exc1:
        store.load(acquisition_id="acq_valid_1", snapshot_id="../ds-snap_escape")
    assert exc1.value.code == "INVALID_IDENTIFIER"

    # Traversal in acquisition_id
    with pytest.raises(SnapshotStoreError) as exc2:
        store.load(acquisition_id="../acq_escape", snapshot_id="ds-snap_valid_1")
    assert exc2.value.code == "INVALID_IDENTIFIER"

    # Backslash
    with pytest.raises(SnapshotStoreError) as exc3:
        store.load(acquisition_id="acq_test\\sub", snapshot_id="ds-snap_valid_1")
    assert exc3.value.code == "INVALID_IDENTIFIER"


def test_symlink_substitution_rejected(tmp_path: Path) -> None:
    store = FileSystemSnapshotStore(tmp_path)
    pkg = _create_test_package()
    store.store(pkg)

    target_dir = tmp_path / "snapshots" / pkg.receipt.snapshot_id / pkg.receipt.acquisition_id
    # Replace raw.bin with symlink
    raw_file = target_dir / "raw.bin"
    raw_file.unlink()
    raw_file.symlink_to(target_dir / "receipt.json")

    with pytest.raises(SnapshotStoreError) as exc_info:
        store.load(pkg.receipt.acquisition_id, pkg.receipt.snapshot_id)
    assert exc_info.value.code == "SYMLINK_NOT_ALLOWED"


def test_tampered_stored_content_detected_on_reopen(tmp_path: Path) -> None:
    store = FileSystemSnapshotStore(tmp_path)
    pkg = _create_test_package()
    store.store(pkg)

    target_dir = tmp_path / "snapshots" / pkg.receipt.snapshot_id / pkg.receipt.acquisition_id
    raw_file = target_dir / "raw.bin"

    # Corrupt raw file on disk
    raw_file.write_bytes(b"CORRUPTED_DISK_BYTES")

    with pytest.raises(SnapshotStoreError) as exc_info:
        store.load(pkg.receipt.acquisition_id, pkg.receipt.snapshot_id)
    assert exc_info.value.code in ("RAW_HASH_MISMATCH", "RAW_SIZE_MISMATCH")


def test_failure_injection_before_staging_write(tmp_path: Path) -> None:
    injector = SnapshotStoreFailureInjector(fail_before_staging_write=True)
    store = FileSystemSnapshotStore(tmp_path, failure_injector=injector)
    pkg = _create_test_package()

    with pytest.raises(SnapshotStoreError) as exc_info:
        store.store(pkg)
    assert exc_info.value.code == "INJECTED_FAILURE"

    # Verify nothing was published
    assert not store.exists(pkg.receipt.acquisition_id, pkg.receipt.snapshot_id)
    # Verify staging cleanup
    staging_dir = tmp_path / "staging"
    assert not any(staging_dir.iterdir())


def test_failure_injection_during_atomic_rename(tmp_path: Path) -> None:
    injector = SnapshotStoreFailureInjector(fail_during_atomic_rename=True)
    store = FileSystemSnapshotStore(tmp_path, failure_injector=injector)
    pkg = _create_test_package()

    with pytest.raises(SnapshotStoreError) as exc_info:
        store.store(pkg)
    assert exc_info.value.code == "INJECTED_FAILURE"

    # Verify nothing published
    assert not store.exists(pkg.receipt.acquisition_id, pkg.receipt.snapshot_id)
    # Verify staging directory was cleaned up
    staging_dir = tmp_path / "staging"
    assert not any(staging_dir.iterdir())


def test_list_acquisitions_and_pruning(tmp_path: Path) -> None:
    store = FileSystemSnapshotStore(tmp_path)
    pkg1 = _create_test_package(acquisition_id="acq_test_v1_0001", raw_bytes=b"PKG_1")
    pkg2 = _create_test_package(acquisition_id="acq_test_v1_0002", raw_bytes=b"PKG_2")
    pkg3 = _create_test_package(acquisition_id="acq_test_v1_0003", raw_bytes=b"PKG_3")

    store.store(pkg1)
    store.store(pkg2)
    store.store(pkg3)

    acqs = store.list_acquisitions(pkg1.receipt.snapshot_id)
    assert acqs == ("acq_test_v1_0001", "acq_test_v1_0002", "acq_test_v1_0003")

    # Prune retaining max 2, protecting pkg1
    pruned = store.prune(max_retained=2, protected_acquisition_ids=("acq_test_v1_0001",))
    assert pruned == 1
    # pkg1 protected, pkg3 newest, so pkg2 was pruned
    remaining = store.list_acquisitions(pkg1.receipt.snapshot_id)
    assert "acq_test_v1_0001" in remaining
    assert "acq_test_v1_0003" in remaining
    assert "acq_test_v1_0002" not in remaining
