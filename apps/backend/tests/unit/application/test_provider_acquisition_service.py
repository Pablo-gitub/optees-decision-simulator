"""Unit tests for ProviderAcquisitionService (DS-02C3 / Gate DS-D2C)."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Final

import pytest

from simulator.application.ports.acquisition_transport import (
    AcquisitionArtifactRequest,
    AcquisitionArtifactResponse,
    AcquisitionTransportPort,
)
from simulator.application.services.provider_acquisition import ProviderAcquisitionService
from simulator.domain.errors import AcquisitionTransportError, SnapshotStoreError
from simulator.infrastructure.adapters.fs_snapshot_store import (
    FileSystemSnapshotStore,
    SnapshotStoreFailureInjector,
)
from simulator.infrastructure.adapters.market_decoder_adapter import (
    BinanceKlineMarketDecoderAdapter,
)
from simulator.infrastructure.adapters.offline_dataset import OfflineDatasetAdapter

SAMPLE_KLINE_CSV: Final[str] = (
    "1704067200000,42000.50,43000.00,41500.00,42800.00,1050.25,"
    "1704153599999,44500000.00,150000,520.10,22100000.00,0\n"
)


def _create_zip(filename: str, content: bytes) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(filename, content)
    return stream.getvalue()


class ScriptedFakeTransport(AcquisitionTransportPort):
    """Deterministic in-memory transport recording calls and returning scripted responses."""

    def __init__(self, responses: dict[str, AcquisitionArtifactResponse | Exception]) -> None:
        self._responses = responses
        self.call_history: list[AcquisitionArtifactRequest] = []

    def fetch_artifact(self, request: AcquisitionArtifactRequest) -> AcquisitionArtifactResponse:
        self.call_history.append(request)
        if request.uri not in self._responses:
            raise AcquisitionTransportError(
                f"No scripted response for URI: {request.uri}",
                code="HTTP_STATUS_ERROR",
            )
        resp = self._responses[request.uri]
        if isinstance(resp, Exception):
            raise resp
        return resp


def _build_fixture_responses(
    symbol: str = "BTCUSDT",
    interval: str = "1d",
    date_str: str = "2024-01-01",
    csv_content: str = SAMPLE_KLINE_CSV,
) -> tuple[dict[str, AcquisitionArtifactResponse], bytes, str]:
    archive_filename = f"{symbol}-{interval}-{date_str}.zip"
    csv_filename = f"{symbol}-{interval}-{date_str}.csv"
    checksum_filename = f"{archive_filename}.CHECKSUM"

    base_url = f"https://data.binance.vision/data/spot/daily/klines/{symbol}/{interval}"
    archive_uri = f"{base_url}/{archive_filename}"
    checksum_uri = f"{base_url}/{checksum_filename}"

    zip_bytes = _create_zip(csv_filename, csv_content.encode("utf-8"))
    zip_sha = hashlib.sha256(zip_bytes).hexdigest()
    checksum_text = f"{zip_sha}  {archive_filename}\n".encode("utf-8")

    responses: dict[str, AcquisitionArtifactResponse] = {
        checksum_uri: AcquisitionArtifactResponse(
            content=checksum_text,
            content_type="text/plain",
            byte_size=len(checksum_text),
            sha256_digest=f"sha256:{hashlib.sha256(checksum_text).hexdigest()}",
        ),
        archive_uri: AcquisitionArtifactResponse(
            content=zip_bytes,
            content_type="application/zip",
            byte_size=len(zip_bytes),
            sha256_digest=f"sha256:{zip_sha}",
        ),
    }

    return responses, zip_bytes, f"sha256:{zip_sha}"


def test_successful_acquisition_and_publication(tmp_path: Path) -> None:
    responses, zip_bytes, raw_sha = _build_fixture_responses()
    transport = ScriptedFakeTransport(responses)
    store = FileSystemSnapshotStore(tmp_path)
    service = ProviderAcquisitionService(
        transport=transport,
        store=store,
        normalizer=BinanceKlineMarketDecoderAdapter(),
    )

    snapshot_id = "ds-snap_btc_20240101"
    receipt, acq_id = service.acquire_spot_kline_snapshot(
        snapshot_id=snapshot_id,
        symbol="BTCUSDT",
        interval="1d",
        date_str="2024-01-01",
        retrieval_time="2026-08-30T00:00:00Z",
    )

    assert receipt.verification_outcome == "ACCEPTED"
    assert receipt.failure_reasons == ()
    assert receipt.raw_artifact_sha256 == raw_sha
    assert receipt.snapshot_id == snapshot_id
    assert receipt.acquisition_id == acq_id

    # Verify presence in store and reopen via OfflineDatasetAdapter
    assert store.exists(acquisition_id=acq_id, snapshot_id=snapshot_id)

    adapter = OfflineDatasetAdapter(store=store, acquisition_id=acq_id, snapshot_id=snapshot_id)
    assert adapter.receipt == receipt
    assert len(adapter.get_all_observations()) == 1
    assert adapter.get_manifest().snapshot_id == snapshot_id


def test_refetch_idempotency_returns_first_receipt(tmp_path: Path) -> None:
    responses, _, _ = _build_fixture_responses()
    transport = ScriptedFakeTransport(responses)
    store = FileSystemSnapshotStore(tmp_path)
    service = ProviderAcquisitionService(
        transport=transport,
        store=store,
        normalizer=BinanceKlineMarketDecoderAdapter(),
    )

    snapshot_id = "ds-snap_btc_20240101"
    receipt1, acq_id1 = service.acquire_spot_kline_snapshot(
        snapshot_id=snapshot_id,
        symbol="BTCUSDT",
        interval="1d",
        date_str="2024-01-01",
        retrieval_time="2026-08-30T00:00:00Z",
    )

    # Second acquisition with DIFFERENT retrieval_time
    receipt2, acq_id2 = service.acquire_spot_kline_snapshot(
        snapshot_id=snapshot_id,
        symbol="BTCUSDT",
        interval="1d",
        date_str="2024-01-01",
        retrieval_time="2026-08-30T12:00:00Z",
    )

    # Identical acquisition ID returned
    assert acq_id1 == acq_id2
    # First receipt retained with original retrieval_time
    assert receipt2.retrieval_time == "2026-08-30T00:00:00Z"
    assert receipt1 == receipt2


def test_changed_upstream_artifact_creates_new_acquisition(tmp_path: Path) -> None:
    # 1. First version of upstream data
    responses1, _, sha1 = _build_fixture_responses(csv_content=SAMPLE_KLINE_CSV)
    transport1 = ScriptedFakeTransport(responses1)
    store = FileSystemSnapshotStore(tmp_path)
    service1 = ProviderAcquisitionService(
        transport=transport1,
        store=store,
        normalizer=BinanceKlineMarketDecoderAdapter(),
    )

    snapshot_id = "ds-snap_btc_20240101"
    receipt1, acq_id1 = service1.acquire_spot_kline_snapshot(
        snapshot_id=snapshot_id,
        symbol="BTCUSDT",
        interval="1d",
        date_str="2024-01-01",
        retrieval_time="2026-08-30T00:00:00Z",
    )

    # 2. Upstream modified artifact (e.g. revision with different price)
    modified_csv = (
        "1704067200000,42500.00,43500.00,42000.00,43100.00,2000.00,"
        "1704153599999,86000000.00,300000,1000.00,43000000.00,0\n"
    )
    responses2, _, sha2 = _build_fixture_responses(csv_content=modified_csv)
    transport2 = ScriptedFakeTransport(responses2)
    service2 = ProviderAcquisitionService(
        transport=transport2,
        store=store,
        normalizer=BinanceKlineMarketDecoderAdapter(),
    )

    receipt2, acq_id2 = service2.acquire_spot_kline_snapshot(
        snapshot_id=snapshot_id,
        symbol="BTCUSDT",
        interval="1d",
        date_str="2024-01-01",
        retrieval_time="2026-08-30T01:00:00Z",
    )

    assert acq_id1 != acq_id2
    assert sha1 != sha2
    assert receipt1.raw_artifact_sha256 == sha1
    assert receipt2.raw_artifact_sha256 == sha2

    # Both acquisitions exist in store simultaneously without overwriting
    assert store.exists(acq_id1, snapshot_id)
    assert store.exists(acq_id2, snapshot_id)


def test_publisher_checksum_mismatch_rejects_and_publishes_nothing(tmp_path: Path) -> None:
    responses, _, _ = _build_fixture_responses()
    # Tamper checksum file with a different hash
    checksum_uri = "https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip.CHECKSUM"
    wrong_text = (
        b"0000000000000000000000000000000000000000000000000000000000000000  "
        b"BTCUSDT-1d-2024-01-01.zip\n"
    )
    responses[checksum_uri] = AcquisitionArtifactResponse(
        content=wrong_text,
        content_type="text/plain",
        byte_size=len(wrong_text),
        sha256_digest=f"sha256:{hashlib.sha256(wrong_text).hexdigest()}",
    )

    transport = ScriptedFakeTransport(responses)
    store = FileSystemSnapshotStore(tmp_path)
    service = ProviderAcquisitionService(
        transport=transport,
        store=store,
        normalizer=BinanceKlineMarketDecoderAdapter(),
    )

    snapshot_id = "ds-snap_btc_20240101"
    receipt, acq_id = service.acquire_spot_kline_snapshot(
        snapshot_id=snapshot_id,
        symbol="BTCUSDT",
        interval="1d",
        date_str="2024-01-01",
        retrieval_time="2026-08-30T00:00:00Z",
    )

    assert receipt.verification_outcome == "REJECTED"
    assert "RAW_CHECKSUM_MISMATCH" in receipt.failure_reasons
    assert not store.exists(acq_id, snapshot_id)


def test_malformed_checksum_line_rejects_and_publishes_nothing(tmp_path: Path) -> None:
    responses, _, _ = _build_fixture_responses()
    checksum_uri = "https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip.CHECKSUM"
    invalid_text = b"INVALID_CHECKSUM_LINE_FORMAT\n"
    responses[checksum_uri] = AcquisitionArtifactResponse(
        content=invalid_text,
        content_type="text/plain",
        byte_size=len(invalid_text),
        sha256_digest=f"sha256:{hashlib.sha256(invalid_text).hexdigest()}",
    )

    transport = ScriptedFakeTransport(responses)
    store = FileSystemSnapshotStore(tmp_path)
    service = ProviderAcquisitionService(
        transport=transport,
        store=store,
        normalizer=BinanceKlineMarketDecoderAdapter(),
    )

    snapshot_id = "ds-snap_btc_20240101"
    receipt, acq_id = service.acquire_spot_kline_snapshot(
        snapshot_id=snapshot_id,
        symbol="BTCUSDT",
        interval="1d",
        date_str="2024-01-01",
        retrieval_time="2026-08-30T00:00:00Z",
    )

    assert receipt.verification_outcome == "REJECTED"
    assert not store.exists(acq_id, snapshot_id)


def test_malformed_zip_rejects_and_publishes_nothing(tmp_path: Path) -> None:
    archive_uri = (
        "https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip"
    )
    checksum_uri = f"{archive_uri}.CHECKSUM"
    non_zip_bytes = b"CORRUPTED_NON_ZIP_BYTES"
    sha = hashlib.sha256(non_zip_bytes).hexdigest()
    checksum_text = f"{sha}  BTCUSDT-1d-2024-01-01.zip\n".encode("utf-8")

    responses = {
        checksum_uri: AcquisitionArtifactResponse(
            content=checksum_text,
            content_type="text/plain",
            byte_size=len(checksum_text),
            sha256_digest=f"sha256:{hashlib.sha256(checksum_text).hexdigest()}",
        ),
        archive_uri: AcquisitionArtifactResponse(
            content=non_zip_bytes,
            content_type="application/zip",
            byte_size=len(non_zip_bytes),
            sha256_digest=f"sha256:{sha}",
        ),
    }

    transport = ScriptedFakeTransport(responses)
    store = FileSystemSnapshotStore(tmp_path)
    service = ProviderAcquisitionService(
        transport=transport,
        store=store,
        normalizer=BinanceKlineMarketDecoderAdapter(),
    )

    snapshot_id = "ds-snap_btc_20240101"
    receipt, acq_id = service.acquire_spot_kline_snapshot(
        snapshot_id=snapshot_id,
        symbol="BTCUSDT",
        interval="1d",
        date_str="2024-01-01",
        retrieval_time="2026-08-30T00:00:00Z",
    )

    assert receipt.verification_outcome == "REJECTED"
    assert not store.exists(acq_id, snapshot_id)


def test_store_failure_cleans_up_and_does_not_publish(tmp_path: Path) -> None:
    responses, _, _ = _build_fixture_responses()
    transport = ScriptedFakeTransport(responses)
    injector = SnapshotStoreFailureInjector(fail_before_staging_write=True)
    store = FileSystemSnapshotStore(tmp_path, failure_injector=injector)
    service = ProviderAcquisitionService(
        transport=transport,
        store=store,
        normalizer=BinanceKlineMarketDecoderAdapter(),
    )

    snapshot_id = "ds-snap_btc_20240101"
    with pytest.raises(SnapshotStoreError):
        service.acquire_spot_kline_snapshot(
            snapshot_id=snapshot_id,
            symbol="BTCUSDT",
            interval="1d",
            date_str="2024-01-01",
            retrieval_time="2026-08-30T00:00:00Z",
        )

    # Assert nothing was published
    assert len(store.list_acquisitions(snapshot_id)) == 0


def test_call_order_and_transport_error_propagation(tmp_path: Path) -> None:
    # Script transport to fail on archive fetch
    checksum_uri = "https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip.CHECKSUM"
    archive_uri = (
        "https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip"
    )
    checksum_text = (
        b"1111111111111111111111111111111111111111111111111111111111111111  "
        b"BTCUSDT-1d-2024-01-01.zip\n"
    )

    responses = {
        checksum_uri: AcquisitionArtifactResponse(
            content=checksum_text,
            content_type="text/plain",
            byte_size=len(checksum_text),
            sha256_digest=f"sha256:{hashlib.sha256(checksum_text).hexdigest()}",
        ),
        archive_uri: AcquisitionTransportError("Network timeout", code="TIMEOUT"),
    }

    transport = ScriptedFakeTransport(responses)
    store = FileSystemSnapshotStore(tmp_path)
    service = ProviderAcquisitionService(
        transport=transport,
        store=store,
        normalizer=BinanceKlineMarketDecoderAdapter(),
    )

    snapshot_id = "ds-snap_btc_20240101"
    with pytest.raises(AcquisitionTransportError) as exc_info:
        service.acquire_spot_kline_snapshot(
            snapshot_id=snapshot_id,
            symbol="BTCUSDT",
            interval="1d",
            date_str="2024-01-01",
            retrieval_time="2026-08-30T00:00:00Z",
        )

    assert exc_info.value.code == "TIMEOUT"
    # Verify call order: checksum was requested first, then archive
    assert len(transport.call_history) == 2
    assert transport.call_history[0].uri == checksum_uri
    assert transport.call_history[1].uri == archive_uri
