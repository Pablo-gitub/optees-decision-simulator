"""Infrastructure adapter implementing MarketArchiveNormalizerPort for Binance klines."""

from __future__ import annotations

import hashlib

from simulator.application.ports.market_decoder import MarketArchiveNormalizerPort
from simulator.domain.canonical import canonicalize_json
from simulator.domain.models import AcquisitionReceipt, DatasetSnapshotManifest, ObservationRecord
from simulator.infrastructure.adapters.archive_decoder import decode_kline_archive
from simulator.infrastructure.adapters.market_normalizer import (
    build_market_snapshot_manifest,
    normalize_kline_records,
)


class BinanceKlineMarketDecoderAdapter(MarketArchiveNormalizerPort):
    """Adapter for decoding Binance kline ZIP archives into canonical observations and manifests."""

    def decode_and_normalize(
        self,
        raw_zip_bytes: bytes,
        snapshot_id: str,
        retrieval_time: str,
        archive_filename: str,
    ) -> tuple[tuple[ObservationRecord, ...], DatasetSnapshotManifest, bytes]:
        """Decode raw zip archive, normalize observations, and build canonical manifest."""
        raw_sha256 = f"sha256:{hashlib.sha256(raw_zip_bytes).hexdigest()}"
        checksum_filename = f"{archive_filename}.CHECKSUM"
        base_url = "https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d"
        archive_uri = f"{base_url}/{archive_filename}"
        checksum_uri = f"{base_url}/{checksum_filename}"

        candidate_receipt = AcquisitionReceipt(
            acquisition_id="acq_candidate",
            snapshot_id=snapshot_id,
            provider_archive_uri=archive_uri,
            provider_archive_filename=archive_filename,
            publisher_checksum_uri=checksum_uri,
            retrieval_time=retrieval_time,
            publisher_sha256=raw_sha256,
            raw_artifact_sha256=raw_sha256,
            raw_byte_size=len(raw_zip_bytes),
            normalizer_id="binance_kline_spot_1d",
            normalizer_version="1.0.0",
            normalized_snapshot_sha256="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            manifest_sha256="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            verification_outcome="ACCEPTED",
            failure_reasons=(),
        )

        decoded_pkg = decode_kline_archive(raw_zip_bytes, candidate_receipt)
        observations: tuple[ObservationRecord, ...] = normalize_kline_records(
            records=decoded_pkg.rows,
            snapshot_id=snapshot_id,
        )
        manifest: DatasetSnapshotManifest = build_market_snapshot_manifest(
            observations=observations,
            snapshot_id=snapshot_id,
            retrieval_time=retrieval_time,
        )
        canonical_lines = [canonicalize_json(obs.to_dict()) for obs in observations]
        normalized_bytes = "\n".join(canonical_lines).encode("utf-8")

        return observations, manifest, normalized_bytes
