"""Unit tests for SyntheticDatasetAdapter."""

from simulator.infrastructure.adapters.synthetic_dataset import SyntheticDatasetAdapter


def test_synthetic_dataset_manifest_and_observations() -> None:
    adapter = SyntheticDatasetAdapter()
    manifest = adapter.get_manifest()
    assert manifest.snapshot_id == "ds-snap_synthetic_daily_v1"
    assert len(manifest.series_catalog) == 2

    obs = adapter.get_all_observations()
    assert len(obs) == 9
    assert all(o.snapshot_id == manifest.snapshot_id for o in obs)
