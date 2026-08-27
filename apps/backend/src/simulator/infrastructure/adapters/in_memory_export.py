"""In-memory export and bundle verification adapter."""

from __future__ import annotations

from typing import Any

from simulator.application.ports.export import ExportPort
from simulator.application.ports.persistence import PersistencePort
from simulator.domain.canonical import compute_record_hash


class InMemoryExportAdapter(ExportPort):
    """Generates canonical export bundles from in-memory persistence."""

    def __init__(self, persistence: PersistencePort) -> None:
        self._persistence = persistence

    def export_episode_bundle(self, run_id: str) -> dict[str, Any]:
        run = self._persistence.get_episode_run(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")

        episode = self._persistence.get_episode_definition(run.episode_id)
        if episode is None:
            raise ValueError(f"Episode {run.episode_id} not found")

        rounds = self._persistence.get_rounds(run_id)
        metrics = self._persistence.get_metric_records(run_id)

        all_states: dict[str, list[dict[str, Any]]] = {}
        for p_ver in episode.policy_versions:
            states = self._persistence.get_account_states(run_id, p_ver.policy_id)
            all_states[p_ver.policy_id] = [s.to_dict() for s in states]

        bundle: dict[str, Any] = {
            "$type": "episode_export_bundle",
            "schema_version": "1.0.0",
            "episode_definition": episode.to_dict(),
            "episode_run": run.to_dict(),
            "rounds": [r.to_dict() for r in rounds],
            "account_trajectories": all_states,
            "metrics": [m.to_dict() for m in metrics],
        }
        bundle["bundle_hash"] = compute_record_hash(
            {k: v for k, v in bundle.items() if k != "bundle_hash"}
        )
        return bundle

    def verify_episode_bundle(self, bundle: dict[str, Any]) -> bool:
        if "bundle_hash" not in bundle:
            return False
        expected_hash = bundle["bundle_hash"]
        unhashed = {k: v for k, v in bundle.items() if k != "bundle_hash"}
        return compute_record_hash(unhashed) == expected_hash
