"""Pure bounded archive decoder for unpacking synthetic Binance-shaped ZIP/CSV archives."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import re
import zipfile
from dataclasses import dataclass
from typing import Final

from simulator.domain.errors import ArchiveDecodingError
from simulator.domain.models import AcquisitionReceipt
from simulator.infrastructure.adapters.market_normalizer import (
    ALLOWED_MARKET_SYMBOLS,
    RawKlineRecord,
)

# Explicit Conservative Limits (Frozen for Gate DS-D2B1)
MAX_RAW_ARCHIVE_BYTES: Final[int] = 10 * 1024 * 1024  # 10 MB
MAX_MEMBER_COUNT: Final[int] = 1
MAX_COMPRESSED_MEMBER_BYTES: Final[int] = 10 * 1024 * 1024  # 10 MB
MAX_UNCOMPRESSED_MEMBER_BYTES: Final[int] = 25 * 1024 * 1024  # 25 MB
MAX_COMPRESSION_RATIO: Final[float] = 50.0  # uncompressed / compressed
MAX_CSV_ROW_COUNT: Final[int] = 10_000
MIN_CSV_ROW_COUNT: Final[int] = 1
EXPECTED_CSV_COLUMN_COUNT: Final[int] = 12
MAX_CELL_LENGTH: Final[int] = 256
DECOMPRESSION_CHUNK_SIZE: Final[int] = 64 * 1024  # 64 KB buffer

# Member Name Regex: flat basename with alphanumerics, underscores, hyphens, dots
MEMBER_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-zA-Z0-9_.-]+$")


@dataclass(frozen=True)
class DecodedArchivePackage:
    """Immutable typed container representing the successfully verified and unpacked archive."""

    acquisition_id: str
    snapshot_id: str
    archive_filename: str
    member_filename: str
    raw_artifact_sha256: str
    raw_byte_size: int
    uncompressed_byte_size: int
    row_count: int
    rows: tuple[RawKlineRecord, ...]


def decode_kline_archive(
    raw_zip_bytes: bytes,
    receipt: AcquisitionReceipt,
) -> DecodedArchivePackage:
    """Verify receipt bindings and decode a single-member Binance 1d kline ZIP archive in memory.

    Strict verification and security invariants:
    - Receipt must be ACCEPTED with no failure reasons.
    - Raw byte size and SHA-256 must match receipt exactly.
    - Raw archive bytes, member counts, compressed/uncompressed sizes, and compression ratios
      must satisfy conservative frozen limits.
    - Exactly one regular CSV member matching receipt expected basename without directory nesting,
      traversal, symlinks, or encryption.
    - Content must be valid UTF-8 without NUL bytes, with headerless rows having exactly 12 columns.
    - Operates 100% in-memory with zero filesystem or network I/O.
    """
    # 1. Receipt verification precondition
    if receipt.verification_outcome != "ACCEPTED" or receipt.failure_reasons:
        raise ArchiveDecodingError(
            "Acquisition receipt is not ACCEPTED or contains active failure reasons",
            code="RECEIPT_NOT_ACCEPTED",
        )

    # 2. Raw archive size and digest checks
    raw_len = len(raw_zip_bytes)
    if raw_len != receipt.raw_byte_size:
        raise ArchiveDecodingError(
            "Raw archive byte size does not match receipt raw_byte_size",
            code="RAW_SIZE_MISMATCH",
        )

    if raw_len > MAX_RAW_ARCHIVE_BYTES:
        raise ArchiveDecodingError(
            "Raw archive byte size exceeds maximum allowed limit",
            code="EXCEEDED_MAX_RAW_ARCHIVE_BYTES",
        )

    computed_raw_sha256 = f"sha256:{hashlib.sha256(raw_zip_bytes).hexdigest()}"
    if not hmac.compare_digest(computed_raw_sha256, receipt.raw_artifact_sha256):
        raise ArchiveDecodingError(
            "Raw archive SHA-256 digest does not match receipt raw_artifact_sha256",
            code="RAW_HASH_MISMATCH",
        )

    if raw_len < 22:
        raise ArchiveDecodingError(
            "Raw archive bytes are too short to be a valid ZIP archive",
            code="INVALID_ZIP_ARCHIVE",
        )

    # 3. Open in-memory ZIP archive
    try:
        zip_file = zipfile.ZipFile(io.BytesIO(raw_zip_bytes), mode="r")
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, EOFError, KeyError) as exc:
        raise ArchiveDecodingError(
            "Failed to parse ZIP archive header",
            code="INVALID_ZIP_ARCHIVE",
        ) from exc

    with zip_file:
        infolist = zip_file.infolist()

        # 4. Check member count
        if len(infolist) == 0:
            raise ArchiveDecodingError(
                "ZIP archive contains no members",
                code="EMPTY_ARCHIVE",
            )

        if len(infolist) > MAX_MEMBER_COUNT:
            raise ArchiveDecodingError(
                "ZIP archive contains multiple or duplicate members",
                code="MULTIPLE_MEMBERS_FORBIDDEN",
            )

        info = infolist[0]

        # 5. Member type and name validation
        if info.is_dir() or info.filename.endswith("/"):
            raise ArchiveDecodingError(
                "Directory entry is forbidden as archive member",
                code="DIRECTORY_ENTRY_FORBIDDEN",
            )

        member_name = info.filename
        if (
            "\\" in member_name
            or "/" in member_name
            or ".." in member_name
            or not MEMBER_NAME_PATTERN.match(member_name)
        ):
            raise ArchiveDecodingError(
                "Member filename contains forbidden path traversal, directory, or characters",
                code="INVALID_MEMBER_NAME",
            )

        # Expected member filename: {archive_basename}.csv
        archive_fn = receipt.provider_archive_filename
        expected_csv_name = (
            archive_fn[:-4] + ".csv" if archive_fn.endswith(".zip") else archive_fn + ".csv"
        )
        if member_name != expected_csv_name:
            raise ArchiveDecodingError(
                "Archive member filename does not match expected CSV name",
                code="MEMBER_FILENAME_MISMATCH",
            )

        # Extract symbol from filename (e.g. BTCUSDT-1d-2024-01-01.csv -> BTCUSDT)
        if "-1d-" in expected_csv_name:
            symbol = expected_csv_name.split("-1d-")[0]
        else:
            symbol = expected_csv_name.split(".")[0]

        if symbol not in ALLOWED_MARKET_SYMBOLS:
            raise ArchiveDecodingError(
                "Derived symbol from archive filename is not in allowed market universe",
                code="MEMBER_FILENAME_MISMATCH",
            )

        # Special file types (symlinks, devices, pipes)
        mode_type = (info.external_attr >> 16) & 0o170000
        if mode_type != 0 and mode_type != 0o100000:
            raise ArchiveDecodingError(
                "Special entries or symlinks are forbidden in archive",
                code="SPECIAL_ENTRY_FORBIDDEN",
            )

        # Encryption check
        if info.flag_bits & 0x1 != 0:
            raise ArchiveDecodingError(
                "Encrypted ZIP members are forbidden",
                code="ENCRYPTED_MEMBER_FORBIDDEN",
            )

        # Compression method check
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ArchiveDecodingError(
                "Unsupported ZIP compression method",
                code="UNSUPPORTED_COMPRESSION_METHOD",
            )

        # Pre-decompression declared size and ratio checks
        if info.compress_size < 0 or info.compress_size > MAX_COMPRESSED_MEMBER_BYTES:
            raise ArchiveDecodingError(
                "Declared compressed size exceeds maximum allowed limit",
                code="EXCEEDED_MAX_COMPRESSED_BYTES",
            )

        if info.file_size < 0 or info.file_size > MAX_UNCOMPRESSED_MEMBER_BYTES:
            raise ArchiveDecodingError(
                "Declared uncompressed size exceeds maximum allowed limit",
                code="EXCEEDED_MAX_UNCOMPRESSED_BYTES",
            )

        effective_comp = max(info.compress_size, 1)
        if info.file_size / effective_comp > MAX_COMPRESSION_RATIO:
            raise ArchiveDecodingError(
                "Declared compression ratio exceeds maximum allowed limit",
                code="EXCEEDED_MAX_COMPRESSION_RATIO",
            )

        # 6. Bounded streaming decompression
        try:
            with zip_file.open(info, mode="r") as member_stream:
                buffer = io.BytesIO()
                total_uncompressed = 0

                while True:
                    chunk = member_stream.read(DECOMPRESSION_CHUNK_SIZE)
                    if not chunk:
                        break
                    total_uncompressed += len(chunk)
                    if total_uncompressed > MAX_UNCOMPRESSED_MEMBER_BYTES:
                        raise ArchiveDecodingError(
                            "Uncompressed member size exceeded maximum limit during decompression",
                            code="EXCEEDED_MAX_UNCOMPRESSED_BYTES",
                        )
                    if total_uncompressed / effective_comp > MAX_COMPRESSION_RATIO:
                        raise ArchiveDecodingError(
                            "Compression ratio exceeded maximum limit during decompression",
                            code="EXCEEDED_MAX_COMPRESSION_RATIO",
                        )
                    buffer.write(chunk)

                uncompressed_bytes = buffer.getvalue()
        except zipfile.BadZipFile as exc:
            raise ArchiveDecodingError(
                "ZIP archive payload is corrupted or truncated",
                code="INVALID_ZIP_ARCHIVE",
            ) from exc

    if len(uncompressed_bytes) == 0:
        raise ArchiveDecodingError(
            "Uncompressed CSV payload is empty",
            code="EMPTY_CSV_PAYLOAD",
        )

    # 7. Check for NUL bytes in payload
    if b"\x00" in uncompressed_bytes:
        raise ArchiveDecodingError(
            "NUL byte detected in CSV payload",
            code="NUL_BYTE_DETECTED",
        )

    # 8. Decode UTF-8
    try:
        csv_text = uncompressed_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArchiveDecodingError(
            "CSV payload is not valid UTF-8",
            code="INVALID_UTF8",
        ) from exc

    if not csv_text.strip():
        raise ArchiveDecodingError(
            "CSV payload contains only whitespace",
            code="EMPTY_CSV_PAYLOAD",
        )

    # 9. Parse CSV rows
    reader = csv.reader(io.StringIO(csv_text), delimiter=",")
    rows: list[RawKlineRecord] = []

    for row in reader:
        if not row or (len(row) == 1 and not row[0].strip()):
            # Skip empty lines
            continue

        if len(row) != EXPECTED_CSV_COLUMN_COUNT:
            raise ArchiveDecodingError(
                "CSV row does not contain expected column count",
                code="INVALID_COLUMN_COUNT",
            )

        for cell in row:
            if len(cell) > MAX_CELL_LENGTH:
                raise ArchiveDecodingError(
                    "CSV cell length exceeds maximum allowed limit",
                    code="EXCEEDED_MAX_CELL_LENGTH",
                )

        try:
            open_time = int(row[0].strip())
            close_time = int(row[6].strip())
            count = int(row[8].strip())
        except (ValueError, TypeError) as exc:
            raise ArchiveDecodingError(
                "Failed to parse integer timestamp or trade count in CSV row",
                code="CSV_PARSE_ERROR",
            ) from exc

        kline = RawKlineRecord(
            symbol=symbol,
            open_time=open_time,
            open=row[1].strip(),
            high=row[2].strip(),
            low=row[3].strip(),
            close=row[4].strip(),
            volume=row[5].strip(),
            close_time=close_time,
            quote_volume=row[7].strip(),
            count=count,
            taker_buy_volume=row[9].strip(),
            taker_buy_quote_volume=row[10].strip(),
            ignore=row[11].strip(),
            interval="1d",
        )
        rows.append(kline)

        if len(rows) > MAX_CSV_ROW_COUNT:
            raise ArchiveDecodingError(
                "CSV row count exceeds maximum allowed limit",
                code="EXCEEDED_MAX_ROW_COUNT",
            )

    if len(rows) < MIN_CSV_ROW_COUNT:
        raise ArchiveDecodingError(
            "CSV payload contains no valid data rows",
            code="EMPTY_CSV_PAYLOAD",
        )

    return DecodedArchivePackage(
        acquisition_id=receipt.acquisition_id,
        snapshot_id=receipt.snapshot_id,
        archive_filename=receipt.provider_archive_filename,
        member_filename=info.filename,
        raw_artifact_sha256=computed_raw_sha256,
        raw_byte_size=raw_len,
        uncompressed_byte_size=len(uncompressed_bytes),
        row_count=len(rows),
        rows=tuple(rows),
    )
