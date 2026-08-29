"""Integration tests for OfflineDatasetAdapter (DS-02C2B / Gate DS-D2B)."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Final

import pytest

from simulator.application.ports.snapshot_store import StoredAcquisitionPackage
from simulator.application.services.acquisition import verify_acquisition_evidence
from simulator.application.services.eligibility import EligibilityService
from simulator.domain.errors import SnapshotStoreError
from simulator.domain.models import AcquisitionReceipt
from simulator.infrastructure.adapters.archive_decoder import decode_kline_archive
from simulator.infrastructure.adapters.fs_snapshot_store import FileSystemSnapshotStore
from simulator.infrastructure.adapters.market_normalizer import (
    build_market_snapshot_manifest,
    compute_normalized_snapshot_hash,
    normalize_kline_records,
)
from simulator.infrastructure.adapters.offline_dataset import OfflineDatasetAdapter

SAMPLE_KLINE_CSV_3DAYS: Final[str] = (
    "1704067200000,42000.50,43000.00,41500.00,42800.00,1050.25,"
    "1704153599999,44500000.00,150000,520.10,22100000.00,0\n"
    "1704153600000,42800.00,44200.00,42500.00,43900.00,1200.50,"
    "1704239999999,52000000.00,180000,600.25,26000000.00,0\n"
    "1704240000000,43900.00,44500.00,43200.00,44100.00,980.10,"
    "1704326399999,43000000.00,140000,450.00,19700000.00,0\n"
)


def _create_synthetic_zip(filename: str, content: bytes) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(filename, content)
    return stream.getvalue()


def _build_verified_test_package(
    snapshot_id: str = "ds-snap_btc_spot_1d_v1",
    filename: str = "BTCUSDT-1d-2024-01.zip",
) -> StoredAcquisitionPackage:
    csv_bytes = SAMPLE_KLINE_CSV_3DAYS.encode("utf-8")
    raw_zip = _create_synthetic_zip("BTCUSDT-1d-2024-01.csv", csv_bytes)
    raw_hash_hex = hashlib.sha256(raw_zip).hexdigest()
    checksum_text = f"{raw_hash_hex}  {filename}\n"

    # 1. Normalization to build canonical manifest
    decoded_pkg = decode_kline_archive(
        raw_zip_bytes=raw_zip,
        receipt=_create_bootstrap_receipt(snapshot_id, filename, raw_zip),
    )
    observations = normalize_kline_records(decoded_pkg.rows, snapshot_id=snapshot_id)
    manifest = build_market_snapshot_manifest(
        observations=observations,
        snapshot_id=snapshot_id,
        retrieval_time="2026-08-28T00:00:00Z",
    )

    # 2. Canonical JSONL bytes for normalized snapshot
    norm_hash = compute_normalized_snapshot_hash(observations)
    assert norm_hash == manifest.checksum_sha256
    # Build exact canonical JSONL stream bytes
    from simulator.domain.canonical import canonicalize_json

    canonical_lines = [canonicalize_json(obs.to_dict()) for obs in observations]
    normalized_bytes = "\n".join(canonical_lines).encode("utf-8")

    # 3. Verify acquisition evidence
    receipt = verify_acquisition_evidence(
        raw_bytes=raw_zip,
        publisher_checksum_text=checksum_text,
        manifest=manifest,
        provider_archive_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}",
        provider_archive_filename=filename,
        publisher_checksum_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}.CHECKSUM",
        retrieval_time="2026-08-28T00:00:00Z",
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_bytes=normalized_bytes,
    )

    assert receipt.verification_outcome == "ACCEPTED"

    return StoredAcquisitionPackage(
        receipt=receipt,
        raw_bytes=raw_zip,
        normalized_bytes=normalized_bytes,
    )


def _create_bootstrap_receipt(
    snapshot_id: str,
    filename: str,
    raw_bytes: bytes,
) -> AcquisitionReceipt:
    raw_sha = f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"
    return AcquisitionReceipt(
        acquisition_id="acq_bootstrap",
        snapshot_id=snapshot_id,
        provider_archive_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}",
        provider_archive_filename=filename,
        publisher_checksum_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}.CHECKSUM",
        retrieval_time="2026-08-28T00:00:00Z",
        publisher_sha256=raw_sha,
        raw_artifact_sha256=raw_sha,
        raw_byte_size=len(raw_bytes),
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_sha256="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        manifest_sha256="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        verification_outcome="ACCEPTED",
        failure_reasons=(),
        license="Upstream repository labelled MIT; raw archive redistribution not asserted",
    )


def test_end_to_end_offline_dataset_adapter_reproduction(tmp_path: Path) -> None:
    store = FileSystemSnapshotStore(tmp_path)
    pkg = _build_verified_test_package()
    store.store(pkg)

    adapter = OfflineDatasetAdapter(
        store=store,
        acquisition_id=pkg.receipt.acquisition_id,
        snapshot_id=pkg.receipt.snapshot_id,
    )

    # 1. Parity of observations and manifest
    observations = adapter.get_all_observations()
    assert len(observations) == 3
    assert observations[0].series_id == "BTC_USDT_PRICE_1D"
    assert observations[0].payload["open"] == "42000.50"

    manifest = adapter.get_manifest()
    assert manifest.snapshot_id == pkg.receipt.snapshot_id
    assert manifest.checksum_sha256 == pkg.receipt.normalized_snapshot_sha256
    assert manifest.compute_hash() == pkg.receipt.manifest_sha256
    assert len(manifest.series_catalog) == 1
    assert manifest.series_catalog[0].series_id == "BTC_USDT_PRICE_1D"

    # 2. Receipt parity
    assert adapter.receipt == pkg.receipt


def test_eligibility_service_filtering_on_offline_dataset(tmp_path: Path) -> None:
    store = FileSystemSnapshotStore(tmp_path)
    pkg = _build_verified_test_package()
    store.store(pkg)

    adapter = OfflineDatasetAdapter(
        store=store,
        acquisition_id=pkg.receipt.acquisition_id,
        snapshot_id=pkg.receipt.snapshot_id,
    )

    all_obs = adapter.get_all_observations()

    # Day 1: event_time 2024-01-01 -> knowledge_time 2024-01-03T00:00:00Z
    # Cutoff at 2024-01-02T00:00:00Z -> 0 eligible
    obs_t1 = EligibilityService.get_eligible_observations(all_obs, "2024-01-02T00:00:00Z")
    assert len(obs_t1) == 0

    # Cutoff at 2024-01-03T00:00:00Z -> Day 1 observation eligible
    obs_t2 = EligibilityService.get_eligible_observations(all_obs, "2024-01-03T00:00:00Z")
    assert len(obs_t2) == 1
    assert obs_t2[0].event_time == "2024-01-01T23:59:59.999Z"

    # Cutoff at 2024-01-05T00:00:00Z -> All 3 observations eligible
    obs_t3 = EligibilityService.get_eligible_observations(all_obs, "2024-01-05T00:00:00Z")
    assert len(obs_t3) == 3


def test_adapter_fails_on_missing_or_corrupted_store(tmp_path: Path) -> None:
    store = FileSystemSnapshotStore(tmp_path)

    # Missing acquisition
    with pytest.raises(SnapshotStoreError) as exc_info:
        OfflineDatasetAdapter(
            store=store,
            acquisition_id="acq_missing",
            snapshot_id="ds-snap_missing",
        )
    assert exc_info.value.code == "ACQUISITION_NOT_FOUND"
