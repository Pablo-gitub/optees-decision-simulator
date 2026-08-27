"""Synthetic dataset adapter providing deterministic time series for testing."""

from __future__ import annotations

from simulator.application.ports.dataset import DatasetPort
from simulator.domain.models import (
    DatasetSnapshotManifest,
    ObservationRecord,
    SeriesCatalogItem,
)


class SyntheticDatasetAdapter(DatasetPort):
    """Provides frozen synthetic multi-series observations with exact cutoff
    and revision scenarios.
    """

    def __init__(self) -> None:
        self._manifest = DatasetSnapshotManifest(
            snapshot_id="ds-snap_synthetic_daily_v1",
            source_uri="memory://synthetic_daily_v1",
            retrieval_time="2026-08-01T00:00:00Z",
            license="MIT",
            checksum_sha256="sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            byte_size=4096,
            format="JSONL",
            series_catalog=(
                SeriesCatalogItem(
                    series_id="RES_ALPHA_PRICE",
                    resource_id="RES_ALPHA",
                    unit="USD",
                    frequency="1d",
                    earliest_event_time="2026-07-30T00:00:00Z",
                    latest_event_time="2026-08-03T00:00:00Z",
                ),
                SeriesCatalogItem(
                    series_id="RES_BETA_PRICE",
                    resource_id="RES_BETA",
                    unit="USD",
                    frequency="1d",
                    earliest_event_time="2026-07-30T00:00:00Z",
                    latest_event_time="2026-08-03T00:00:00Z",
                ),
            ),
            correction_handling="Revision sequence with knowledge timestamps",
        )

        self._observations: tuple[ObservationRecord, ...] = (
            # 1. Prior observation for RES_ALPHA
            ObservationRecord(
                observation_id="obs_alpha_t0",
                snapshot_id="ds-snap_synthetic_daily_v1",
                series_id="RES_ALPHA_PRICE",
                event_time="2026-07-31T12:00:00Z",
                knowledge_time="2026-07-31T12:05:00Z",
                revision=1,
                payload={"price": "98.50", "volume": "10000", "status": "FINAL"},
            ),
            # 2. Exact cutoff observation for RES_ALPHA at Round 0 cutoff (2026-08-01T00:00:00Z)
            ObservationRecord(
                observation_id="obs_alpha_r0",
                snapshot_id="ds-snap_synthetic_daily_v1",
                series_id="RES_ALPHA_PRICE",
                event_time="2026-07-31T23:59:00Z",
                knowledge_time="2026-08-01T00:00:00Z",
                revision=1,
                payload={"price": "100.00", "volume": "15000", "status": "FINAL"},
            ),
            # 3. Exact cutoff observation for RES_BETA at Round 0 cutoff
            ObservationRecord(
                observation_id="obs_beta_r0",
                snapshot_id="ds-snap_synthetic_daily_v1",
                series_id="RES_BETA_PRICE",
                event_time="2026-07-31T23:59:00Z",
                knowledge_time="2026-08-01T00:00:00Z",
                revision=1,
                payload={"price": "50.00", "volume": "30000", "status": "FINAL"},
            ),
            # 4. Delayed publication for RES_ALPHA (published 1 min after Round 0 cutoff)
            ObservationRecord(
                observation_id="obs_alpha_delayed_r0",
                snapshot_id="ds-snap_synthetic_daily_v1",
                series_id="RES_ALPHA_PRICE",
                event_time="2026-07-31T23:59:00Z",
                knowledge_time="2026-08-01T00:01:00Z",
                revision=2,
                payload={"price": "100.20", "volume": "15050", "status": "REVISED"},
            ),
            # 5. Round 1 observation for RES_ALPHA (cutoff: 2026-08-02T00:00:00Z)
            ObservationRecord(
                observation_id="obs_alpha_r1",
                snapshot_id="ds-snap_synthetic_daily_v1",
                series_id="RES_ALPHA_PRICE",
                event_time="2026-08-01T23:59:00Z",
                knowledge_time="2026-08-02T00:00:00Z",
                revision=1,
                payload={"price": "105.00", "volume": "18000", "status": "FINAL"},
            ),
            # 6. Round 1 observation for RES_BETA (cutoff: 2026-08-02T00:00:00Z)
            ObservationRecord(
                observation_id="obs_beta_r1",
                snapshot_id="ds-snap_synthetic_daily_v1",
                series_id="RES_BETA_PRICE",
                event_time="2026-08-01T23:59:00Z",
                knowledge_time="2026-08-02T00:00:00Z",
                revision=1,
                payload={"price": "52.00", "volume": "25000", "status": "FINAL"},
            ),
            # 7. Round 2 observation for RES_ALPHA (cutoff: 2026-08-03T00:00:00Z)
            ObservationRecord(
                observation_id="obs_alpha_r2",
                snapshot_id="ds-snap_synthetic_daily_v1",
                series_id="RES_ALPHA_PRICE",
                event_time="2026-08-02T23:59:00Z",
                knowledge_time="2026-08-03T00:00:00Z",
                revision=1,
                payload={"price": "110.00", "volume": "20000", "status": "FINAL"},
            ),
            # 8. Round 2 observation for RES_BETA (cutoff: 2026-08-03T00:00:00Z)
            ObservationRecord(
                observation_id="obs_beta_r2",
                snapshot_id="ds-snap_synthetic_daily_v1",
                series_id="RES_BETA_PRICE",
                event_time="2026-08-02T23:59:00Z",
                knowledge_time="2026-08-03T00:00:00Z",
                revision=1,
                payload={"price": "48.00", "volume": "22000", "status": "FINAL"},
            ),
            # 9. Future observation beyond Round 2 (not visible in 3-round episode)
            ObservationRecord(
                observation_id="obs_alpha_future",
                snapshot_id="ds-snap_synthetic_daily_v1",
                series_id="RES_ALPHA_PRICE",
                event_time="2026-08-03T12:00:00Z",
                knowledge_time="2026-08-03T12:05:00Z",
                revision=1,
                payload={"price": "115.00", "volume": "25000", "status": "FINAL"},
            ),
        )

    def get_manifest(self) -> DatasetSnapshotManifest:
        return self._manifest

    def get_all_observations(self) -> tuple[ObservationRecord, ...]:
        return self._observations
