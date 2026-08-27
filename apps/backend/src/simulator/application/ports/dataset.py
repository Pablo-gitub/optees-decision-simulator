"""DatasetPort interface for accessing frozen dataset manifests and observations."""

from abc import ABC, abstractmethod

from simulator.domain.models import DatasetSnapshotManifest, ObservationRecord


class DatasetPort(ABC):
    """Port for accessing immutable dataset snapshots and cutoff-filtered observations."""

    @abstractmethod
    def get_manifest(self) -> DatasetSnapshotManifest:
        """Return the immutable manifest of the loaded dataset snapshot."""
        raise NotImplementedError

    @abstractmethod
    def get_all_observations(self) -> tuple[ObservationRecord, ...]:
        """Return all raw observations in the dataset snapshot."""
        raise NotImplementedError
