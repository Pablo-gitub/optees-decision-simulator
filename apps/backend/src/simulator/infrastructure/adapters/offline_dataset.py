"""Offline DatasetPort adapter reopening accepted acquisitions from SnapshotStorePort."""

from __future__ import annotations

from simulator.application.ports.dataset import DatasetPort
from simulator.application.ports.snapshot_store import SnapshotStorePort
from simulator.domain.errors import InvariantViolationError
from simulator.domain.models import (
    AcquisitionReceipt,
    DatasetSnapshotManifest,
    ObservationRecord,
)
from simulator.infrastructure.adapters.archive_decoder import decode_kline_archive
from simulator.infrastructure.adapters.market_normalizer import (
    build_market_snapshot_manifest,
    compute_normalized_snapshot_hash,
    normalize_kline_records,
)


class OfflineDatasetAdapter(DatasetPort):
    """Offline dataset adapter consuming verified acquisition packages from a SnapshotStorePort.

    Reconstructs exact canonical ObservationRecord tuples and DatasetSnapshotManifest without
    introducing a second dataset schema or modifying core contracts.
    """

    def __init__(
        self,
        store: SnapshotStorePort,
        acquisition_id: str,
        snapshot_id: str,
    ) -> None:
        self._store = store
        self._acquisition_id = acquisition_id
        self._snapshot_id = snapshot_id

        # 1. Load and re-verify package from snapshot store
        package = self._store.load(
            acquisition_id=self._acquisition_id,
            snapshot_id=self._snapshot_id,
        )
        self._receipt: AcquisitionReceipt = package.receipt

        # 2. Decode raw ZIP archive into parsed rows
        decoded_pkg = decode_kline_archive(package.raw_bytes, self._receipt)

        # 3. Normalize parsed rows into canonical ObservationRecords
        self._observations: tuple[ObservationRecord, ...] = normalize_kline_records(
            records=decoded_pkg.rows,
            snapshot_id=self._snapshot_id,
        )

        # 4. Construct canonical dataset manifest
        self._manifest: DatasetSnapshotManifest = build_market_snapshot_manifest(
            observations=self._observations,
            snapshot_id=self._snapshot_id,
            retrieval_time=self._receipt.retrieval_time,
            license_str=self._receipt.license,
        )

        # 5. Assert strict cryptographic parity between decoded observations and receipt evidence
        computed_norm_hash = compute_normalized_snapshot_hash(self._observations)
        if computed_norm_hash != self._receipt.normalized_snapshot_sha256:
            raise InvariantViolationError(
                "Normalized snapshot hash parity violation: computed digest does not match receipt"
            )

        if self._manifest.checksum_sha256 != self._receipt.normalized_snapshot_sha256:
            raise InvariantViolationError(
                "Manifest checksum parity violation: manifest checksum does not match receipt"
            )

        if self._manifest.compute_hash() != self._receipt.manifest_sha256:
            raise InvariantViolationError(
                "Canonical manifest hash parity violation: "
                "computed manifest hash does not match receipt"
            )

    @property
    def receipt(self) -> AcquisitionReceipt:
        """Return the immutable verified acquisition receipt."""
        return self._receipt

    def get_manifest(self) -> DatasetSnapshotManifest:
        """Return the reconstructed immutable manifest of the offline dataset snapshot."""
        return self._manifest

    def get_all_observations(self) -> tuple[ObservationRecord, ...]:
        """Return all canonical observations in the offline dataset snapshot."""
        return self._observations
