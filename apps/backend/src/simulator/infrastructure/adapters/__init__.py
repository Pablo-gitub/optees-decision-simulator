"""Infrastructure adapters."""

from simulator.infrastructure.adapters.archive_decoder import (
    DecodedArchivePackage,
    decode_kline_archive,
)
from simulator.infrastructure.adapters.market_normalizer import (
    ALLOWED_MARKET_SYMBOLS,
    RawKlineRecord,
    build_market_snapshot_manifest,
    compute_normalized_snapshot_hash,
    normalize_kline_records,
    normalize_single_kline,
)
from simulator.infrastructure.adapters.synthetic_dataset import SyntheticDatasetAdapter

__all__ = [
    "ALLOWED_MARKET_SYMBOLS",
    "DecodedArchivePackage",
    "RawKlineRecord",
    "SyntheticDatasetAdapter",
    "build_market_snapshot_manifest",
    "compute_normalized_snapshot_hash",
    "decode_kline_archive",
    "normalize_kline_records",
    "normalize_single_kline",
]
