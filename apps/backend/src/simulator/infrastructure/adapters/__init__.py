"""Infrastructure adapters."""

from simulator.infrastructure.adapters.archive_decoder import (
    DecodedArchivePackage,
    decode_kline_archive,
)
from simulator.infrastructure.adapters.fs_snapshot_store import (
    FileSystemSnapshotStore,
    SnapshotStoreFailureInjector,
)
from simulator.infrastructure.adapters.https_acquisition_transport import (
    HttpsAcquisitionTransport,
    TransportTimeouts,
)
from simulator.infrastructure.adapters.market_decoder_adapter import (
    BinanceKlineMarketDecoderAdapter,
)
from simulator.infrastructure.adapters.market_normalizer import (
    ALLOWED_MARKET_SYMBOLS,
    RawKlineRecord,
    build_market_snapshot_manifest,
    compute_normalized_snapshot_hash,
    normalize_kline_records,
    normalize_single_kline,
)
from simulator.infrastructure.adapters.market_pricing import MarketKlinePricingAdapter
from simulator.infrastructure.adapters.offline_dataset import OfflineDatasetAdapter
from simulator.infrastructure.adapters.synthetic_dataset import SyntheticDatasetAdapter
from simulator.infrastructure.adapters.synthetic_pricing import SyntheticPricingAdapter

__all__ = [
    "ALLOWED_MARKET_SYMBOLS",
    "BinanceKlineMarketDecoderAdapter",
    "DecodedArchivePackage",
    "FileSystemSnapshotStore",
    "HttpsAcquisitionTransport",
    "MarketKlinePricingAdapter",
    "OfflineDatasetAdapter",
    "RawKlineRecord",
    "SnapshotStoreFailureInjector",
    "SyntheticDatasetAdapter",
    "SyntheticPricingAdapter",
    "TransportTimeouts",
    "build_market_snapshot_manifest",
    "compute_normalized_snapshot_hash",
    "decode_kline_archive",
    "normalize_kline_records",
    "normalize_single_kline",
]
