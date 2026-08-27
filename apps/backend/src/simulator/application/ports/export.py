"""ExportPort interface for exporting reproducible experiment packages."""

from abc import ABC, abstractmethod
from typing import Any


class ExportPort(ABC):
    """Port for canonical export and checksum verification of completed episodes."""

    @abstractmethod
    def export_episode_bundle(self, run_id: str) -> dict[str, Any]:
        """Export complete immutable history for an episode run as a canonical bundle."""
        raise NotImplementedError

    @abstractmethod
    def verify_episode_bundle(self, bundle: dict[str, Any]) -> bool:
        """Verify the cryptographic integrity and hashes of an exported bundle."""
        raise NotImplementedError
