"""Provider acquisition service orchestrating retrieval, verification, and immutable storage."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Final

from simulator.application.ports.acquisition_transport import (
    AcquisitionArtifactRequest,
    AcquisitionTransportPort,
)
from simulator.application.ports.market_decoder import (
    MARKET_NORMALIZER_ID,
    MARKET_NORMALIZER_VERSION,
    MarketArchiveNormalizerPort,
)
from simulator.application.ports.snapshot_store import (
    SnapshotStorePort,
    StoredAcquisitionPackage,
)
from simulator.application.services.acquisition import verify_acquisition_evidence
from simulator.domain.errors import (
    SimulatorError,
    SnapshotStoreError,
)
from simulator.domain.models import AcquisitionReceipt, DatasetSnapshotManifest
from simulator.domain.time import parse_utc_timestamp

MAX_CHECKSUM_BYTES: Final[int] = 4 * 1024  # 4 KB
MAX_ARCHIVE_BYTES: Final[int] = 10 * 1024 * 1024  # 10 MB

CHECKSUM_CONTENT_TYPES: Final[tuple[str, ...]] = (
    "text/plain",
    "application/octet-stream",
    "binary/octet-stream",
)

ARCHIVE_CONTENT_TYPES: Final[tuple[str, ...]] = (
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
    "binary/octet-stream",
)


class ProviderAcquisitionService:
    """Orchestrates bounded data acquisition from external providers into the snapshot store."""

    def __init__(
        self,
        transport: AcquisitionTransportPort,
        store: SnapshotStorePort,
        normalizer: MarketArchiveNormalizerPort,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._transport = transport
        self._store = store
        self._normalizer = normalizer
        self._clock = clock

    def derive_acquisition_id(self, snapshot_id: str, raw_sha256: str) -> str:
        """Derive the immutable acquisition identifier from snapshot ID and raw digest."""
        digest_hex = raw_sha256.split(":", 1)[-1]
        return f"acq_{snapshot_id}_{digest_hex[:12]}"

    def acquire_spot_kline_snapshot(
        self,
        snapshot_id: str,
        symbol: str,
        interval: str,
        date_str: str,
        retrieval_time: str | None = None,
    ) -> tuple[AcquisitionReceipt, str]:
        """Fetch, verify, normalize, and store a spot kline archive and publisher checksum.

        Rules:
        - Uses explicit retrieval_time or injected clock.
        - Checks for existing accepted identical artifact in store (refetch idempotency).
        - Different raw bytes produce a new acquisition identity; never overwrites evidence.
        - Rejected evidence is returned without storing.
        """
        if retrieval_time is None:
            if self._clock is None:
                raise ValueError("retrieval_time must be provided or clock injected")
            retrieval_time = self._clock()

        # Validate retrieval time format
        parse_utc_timestamp(retrieval_time)

        archive_filename = f"{symbol}-{interval}-{date_str}.zip"
        checksum_filename = f"{archive_filename}.CHECKSUM"
        base_url = f"https://data.binance.vision/data/spot/daily/klines/{symbol}/{interval}"
        archive_uri = f"{base_url}/{archive_filename}"
        checksum_uri = f"{base_url}/{checksum_filename}"

        # 1. Fetch checksum artifact
        checksum_req = AcquisitionArtifactRequest(
            uri=checksum_uri,
            expected_filename=checksum_filename,
            max_bytes=MAX_CHECKSUM_BYTES,
            allowed_content_types=CHECKSUM_CONTENT_TYPES,
        )
        checksum_resp = self._transport.fetch_artifact(checksum_req)
        try:
            checksum_text = checksum_resp.content.decode("utf-8")
        except UnicodeDecodeError:
            checksum_text = ""

        # 2. Fetch archive artifact
        archive_req = AcquisitionArtifactRequest(
            uri=archive_uri,
            expected_filename=archive_filename,
            max_bytes=MAX_ARCHIVE_BYTES,
            allowed_content_types=ARCHIVE_CONTENT_TYPES,
        )
        archive_resp = self._transport.fetch_artifact(archive_req)
        raw_bytes = archive_resp.content
        raw_sha256 = f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"

        acquisition_id = self.derive_acquisition_id(snapshot_id, raw_sha256)

        # 3. Check for existing accepted artifact in store (Refetch idempotence)
        if self._store.exists(acquisition_id=acquisition_id, snapshot_id=snapshot_id):
            try:
                existing = self._store.load(acquisition_id=acquisition_id, snapshot_id=snapshot_id)
                if existing.raw_bytes == raw_bytes:
                    if (
                        existing.receipt.normalizer_id != MARKET_NORMALIZER_ID
                        or existing.receipt.normalizer_version != MARKET_NORMALIZER_VERSION
                    ):
                        raise ValueError("Normalizer version changed; use a new snapshot_id")
                    return existing.receipt, acquisition_id
            except SnapshotStoreError:
                pass

        # 4. Decode raw ZIP archive and normalize observations
        try:
            observations, manifest, normalized_bytes = self._normalizer.decode_and_normalize(
                raw_zip_bytes=raw_bytes,
                snapshot_id=snapshot_id,
                retrieval_time=retrieval_time,
                archive_filename=archive_filename,
            )
        except (SimulatorError, ValueError):
            # Normalization/decoding failed: build empty dummy manifest to record failure evidence
            manifest = DatasetSnapshotManifest(
                snapshot_id=snapshot_id,
                source_uri=archive_uri,
                retrieval_time=retrieval_time,
                license="Upstream repository labelled MIT; raw archive redistribution not asserted",
                checksum_sha256="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                byte_size=0,
                format="JSONL",
                series_catalog=(),
                correction_handling=(
                    "Immutable daily snapshot; upstream replacements require new acquisition."
                ),
            )
            normalized_bytes = b""

        # 5. Verify acquisition evidence
        receipt = verify_acquisition_evidence(
            raw_bytes=raw_bytes,
            publisher_checksum_text=checksum_text,
            manifest=manifest,
            provider_archive_uri=archive_uri,
            provider_archive_filename=archive_filename,
            publisher_checksum_uri=checksum_uri,
            retrieval_time=retrieval_time,
            normalizer_id=MARKET_NORMALIZER_ID,
            normalizer_version=MARKET_NORMALIZER_VERSION,
            normalized_snapshot_bytes=normalized_bytes if normalized_bytes else None,
            acquisition_id=acquisition_id,
            receipt_snapshot_id=snapshot_id,
        )

        # 6. Publish only ACCEPTED evidence to immutable store
        if receipt.verification_outcome == "ACCEPTED" and not receipt.failure_reasons:
            self._store.store(
                StoredAcquisitionPackage(
                    receipt=receipt,
                    raw_bytes=raw_bytes,
                    normalized_bytes=normalized_bytes,
                )
            )

        return receipt, acquisition_id
