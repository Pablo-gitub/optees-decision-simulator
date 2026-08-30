"""Application port for decoding and normalizing raw market dataset archives."""

from __future__ import annotations

from abc import ABC, abstractmethod

from simulator.domain.models import DatasetSnapshotManifest, ObservationRecord


class MarketArchiveNormalizerPort(ABC):
    """Port for decoding raw market archives, normalizing observations, and building manifests."""

    @abstractmethod
    def decode_and_normalize(
        self,
        raw_zip_bytes: bytes,
        snapshot_id: str,
        retrieval_time: str,
        archive_filename: str,
    ) -> tuple[tuple[ObservationRecord, ...], DatasetSnapshotManifest, bytes]:
        """Decode raw zip archive, normalize observations, and build canonical manifest.

        Returns:
            observations: tuple of canonical ObservationRecord items.
            manifest: reconstructed DatasetSnapshotManifest.
            normalized_bytes: canonical JSONL formatted bytes of observations.
        """
        raise NotImplementedError
