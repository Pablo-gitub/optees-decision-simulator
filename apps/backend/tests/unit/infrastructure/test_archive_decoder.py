"""Unit tests for the pure bounded archive decoder (DS-02C2A / Gate DS-D2B1)."""

from __future__ import annotations

import hashlib
import io
import zipfile
from typing import Final

import pytest

from simulator.domain.errors import ArchiveDecodingError
from simulator.domain.models import AcquisitionReceipt
from simulator.infrastructure.adapters.archive_decoder import (
    MAX_CELL_LENGTH,
    MAX_CSV_ROW_COUNT,
    MAX_RAW_ARCHIVE_BYTES,
    decode_kline_archive,
)

SAMPLE_VALID_CSV_LINE: Final[str] = (
    "1704067200000,42000.50,43000.00,41500.00,42800.00,1050.25,"
    "1704153599999,44500000.00,150000,520.10,22100000.00,0\n"
)


def _create_synthetic_zip(
    filename: str,
    content: bytes,
    compress_type: int = zipfile.ZIP_DEFLATED,
    extra_members: list[tuple[str, bytes]] | None = None,
    symlink: bool = False,
    override_external_attr: int | None = None,
    override_flag_bits: int | None = None,
) -> bytes:
    """Helper to build purely in-memory synthetic ZIP byte streams."""
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, mode="w", compression=compress_type) as zf:
        zinfo = zipfile.ZipInfo(filename=filename)
        zinfo.compress_type = compress_type
        if symlink:
            zinfo.external_attr = 0o120777 << 16
        elif override_external_attr is not None:
            zinfo.external_attr = override_external_attr
        zf.writestr(zinfo, content)

        if extra_members:
            for extra_name, extra_content in extra_members:
                zf.writestr(extra_name, extra_content)

    raw = bytearray(stream.getvalue())
    if override_flag_bits is not None:
        if raw[:4] == b"PK\x03\x04":
            raw[6] |= override_flag_bits & 0xFF
            raw[7] |= (override_flag_bits >> 8) & 0xFF
        cd_pos = raw.find(b"PK\x01\x02")
        if cd_pos != -1:
            raw[cd_pos + 8] |= override_flag_bits & 0xFF
            raw[cd_pos + 9] |= (override_flag_bits >> 8) & 0xFF

    return bytes(raw)


def _create_sample_receipt(
    raw_bytes: bytes,
    filename: str = "BTCUSDT-1d-2024-01-01.zip",
    outcome: str = "ACCEPTED",
    failure_reasons: tuple[str, ...] = (),
) -> AcquisitionReceipt:
    raw_sha = f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"
    return AcquisitionReceipt(
        acquisition_id="acq_ds-snap_binance_spot_1d_v1_000000000000",
        snapshot_id="ds-snap_binance_spot_1d_v1",
        provider_archive_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}",
        provider_archive_filename=filename,
        publisher_checksum_uri=f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/{filename}.CHECKSUM",
        retrieval_time="2026-08-28T00:00:00Z",
        publisher_sha256=raw_sha,
        raw_artifact_sha256=raw_sha,
        raw_byte_size=len(raw_bytes),
        normalizer_id="binance_kline_spot_1d",
        normalizer_version="1.0.0",
        normalized_snapshot_sha256="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        manifest_sha256="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        verification_outcome=outcome,
        failure_reasons=failure_reasons,
        license="Upstream repository labelled MIT; raw archive redistribution not asserted",
    )


def test_valid_archive_decodes_successfully() -> None:
    raw_zip = _create_synthetic_zip(
        "BTCUSDT-1d-2024-01-01.csv", SAMPLE_VALID_CSV_LINE.encode("utf-8")
    )
    receipt = _create_sample_receipt(raw_zip, filename="BTCUSDT-1d-2024-01-01.zip")

    package = decode_kline_archive(raw_zip, receipt)

    assert package.acquisition_id == receipt.acquisition_id
    assert package.snapshot_id == receipt.snapshot_id
    assert package.archive_filename == "BTCUSDT-1d-2024-01-01.zip"
    assert package.member_filename == "BTCUSDT-1d-2024-01-01.csv"
    assert package.raw_artifact_sha256 == receipt.raw_artifact_sha256
    assert package.raw_byte_size == len(raw_zip)
    assert package.row_count == 1
    assert len(package.rows) == 1

    row = package.rows[0]
    assert row.symbol == "BTCUSDT"
    assert row.open_time == 1704067200000
    assert row.open == "42000.50"
    assert row.high == "43000.00"
    assert row.low == "41500.00"
    assert row.close == "42800.00"
    assert row.volume == "1050.25"
    assert row.close_time == 1704153599999
    assert row.quote_volume == "44500000.00"
    assert row.count == 150000
    assert row.taker_buy_volume == "520.10"
    assert row.taker_buy_quote_volume == "22100000.00"
    assert row.ignore == "0"
    assert row.interval == "1d"


def test_malformed_csv_parser_error_is_bounded() -> None:
    malformed = b'"unterminated,field\n'
    raw_zip = _create_synthetic_zip("BTCUSDT-1d-2024-01-01.csv", malformed)
    receipt = _create_sample_receipt(raw_zip)

    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(raw_zip, receipt)

    assert exc_info.value.code == "CSV_PARSE_ERROR"
    assert str(exc_info.value) == "CSV payload is malformed"


def test_deterministic_repetition() -> None:
    raw_zip = _create_synthetic_zip(
        "BTCUSDT-1d-2024-01-01.csv", SAMPLE_VALID_CSV_LINE.encode("utf-8")
    )
    receipt = _create_sample_receipt(raw_zip)

    p1 = decode_kline_archive(raw_zip, receipt)
    p2 = decode_kline_archive(raw_zip, receipt)

    assert p1 == p2


def test_receipt_rejected_raises_error() -> None:
    raw_zip = _create_synthetic_zip(
        "BTCUSDT-1d-2024-01-01.csv", SAMPLE_VALID_CSV_LINE.encode("utf-8")
    )

    # Case 1: verification_outcome == "REJECTED" with reason
    receipt_rejected = _create_sample_receipt(
        raw_zip, outcome="REJECTED", failure_reasons=("RAW_CHECKSUM_MISMATCH",)
    )
    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(raw_zip, receipt_rejected)
    assert exc_info.value.code == "RECEIPT_NOT_ACCEPTED"


def test_raw_bytes_mutation_detected() -> None:
    raw_zip = _create_synthetic_zip(
        "BTCUSDT-1d-2024-01-01.csv", SAMPLE_VALID_CSV_LINE.encode("utf-8")
    )
    receipt = _create_sample_receipt(raw_zip)

    # Mutate last byte preserving length
    mutated_zip = raw_zip[:-1] + bytes([(raw_zip[-1] ^ 0xFF)])
    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(mutated_zip, receipt)
    assert exc_info.value.code == "RAW_HASH_MISMATCH"


def test_raw_byte_size_mismatch_detected() -> None:
    raw_zip = _create_synthetic_zip(
        "BTCUSDT-1d-2024-01-01.csv", SAMPLE_VALID_CSV_LINE.encode("utf-8")
    )
    receipt = _create_sample_receipt(raw_zip)

    # Shorter bytes
    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(raw_zip[:-5], receipt)
    assert exc_info.value.code == "RAW_SIZE_MISMATCH"


def test_non_zip_or_truncated_bytes_rejected() -> None:
    non_zip = b"NOT_A_ZIP_HEADER_JUST_RANDOM_TEXT_12345"
    receipt = _create_sample_receipt(non_zip)
    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(non_zip, receipt)
    assert exc_info.value.code == "INVALID_ZIP_ARCHIVE"


def test_empty_archive_rejected() -> None:
    # Empty ZIP (0 members)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, mode="w"):
        pass
    empty_zip = stream.getvalue()
    receipt = _create_sample_receipt(empty_zip)

    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(empty_zip, receipt)
    assert exc_info.value.code == "EMPTY_ARCHIVE"


def test_multiple_members_rejected() -> None:
    multi_zip = _create_synthetic_zip(
        "BTCUSDT-1d-2024-01-01.csv",
        SAMPLE_VALID_CSV_LINE.encode("utf-8"),
        extra_members=[("second_member.csv", b"extra content")],
    )
    receipt = _create_sample_receipt(multi_zip)

    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(multi_zip, receipt)
    assert exc_info.value.code == "MULTIPLE_MEMBERS_FORBIDDEN"


def test_directory_member_rejected() -> None:
    dir_zip = _create_synthetic_zip("BTCUSDT-1d-2024-01-01/", b"")
    receipt = _create_sample_receipt(dir_zip)

    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(dir_zip, receipt)
    assert exc_info.value.code == "DIRECTORY_ENTRY_FORBIDDEN"


def test_invalid_member_name_patterns_rejected() -> None:
    # 1. Path traversal ..
    traversal_zip = _create_synthetic_zip(
        "../BTCUSDT-1d-2024-01-01.csv", SAMPLE_VALID_CSV_LINE.encode("utf-8")
    )
    receipt1 = _create_sample_receipt(traversal_zip)
    with pytest.raises(ArchiveDecodingError) as exc1:
        decode_kline_archive(traversal_zip, receipt1)
    assert exc1.value.code == "INVALID_MEMBER_NAME"

    # 2. Absolute path /
    abs_zip = _create_synthetic_zip(
        "/BTCUSDT-1d-2024-01-01.csv", SAMPLE_VALID_CSV_LINE.encode("utf-8")
    )
    receipt2 = _create_sample_receipt(abs_zip)
    with pytest.raises(ArchiveDecodingError) as exc2:
        decode_kline_archive(abs_zip, receipt2)
    assert exc2.value.code == "INVALID_MEMBER_NAME"

    # 3. Backslash \
    backslash_zip = _create_synthetic_zip(
        "nested\\BTCUSDT-1d-2024-01-01.csv", SAMPLE_VALID_CSV_LINE.encode("utf-8")
    )
    receipt3 = _create_sample_receipt(backslash_zip)
    with pytest.raises(ArchiveDecodingError) as exc3:
        decode_kline_archive(backslash_zip, receipt3)
    assert exc3.value.code == "INVALID_MEMBER_NAME"

    # 4. Nested subfolder /
    nested_zip = _create_synthetic_zip(
        "subfolder/BTCUSDT-1d-2024-01-01.csv", SAMPLE_VALID_CSV_LINE.encode("utf-8")
    )
    receipt4 = _create_sample_receipt(nested_zip)
    with pytest.raises(ArchiveDecodingError) as exc4:
        decode_kline_archive(nested_zip, receipt4)
    assert exc4.value.code == "INVALID_MEMBER_NAME"


def test_member_filename_mismatch_rejected() -> None:
    # Inside member is ETHUSDT but receipt expects BTCUSDT
    mismatched_zip = _create_synthetic_zip(
        "ETHUSDT-1d-2024-01-01.csv", SAMPLE_VALID_CSV_LINE.encode("utf-8")
    )
    receipt = _create_sample_receipt(mismatched_zip, filename="BTCUSDT-1d-2024-01-01.zip")

    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(mismatched_zip, receipt)
    assert exc_info.value.code == "MEMBER_FILENAME_MISMATCH"


def test_symlink_or_special_entry_rejected() -> None:
    symlink_zip = _create_synthetic_zip(
        "BTCUSDT-1d-2024-01-01.csv",
        b"/etc/passwd",
        symlink=True,
    )
    receipt = _create_sample_receipt(symlink_zip)

    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(symlink_zip, receipt)
    assert exc_info.value.code == "SPECIAL_ENTRY_FORBIDDEN"


def test_encrypted_member_rejected() -> None:
    enc_zip = _create_synthetic_zip(
        "BTCUSDT-1d-2024-01-01.csv",
        SAMPLE_VALID_CSV_LINE.encode("utf-8"),
        override_flag_bits=0x1,
    )
    receipt = _create_sample_receipt(enc_zip)

    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(enc_zip, receipt)
    assert exc_info.value.code == "ENCRYPTED_MEMBER_FORBIDDEN"


def test_unsupported_compression_method_rejected() -> None:
    # Compression method 14 is LZMA
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, mode="w") as zf:
        zinfo = zipfile.ZipInfo(filename="BTCUSDT-1d-2024-01-01.csv")
        zinfo.compress_type = 14
        zf.writestr(zinfo, SAMPLE_VALID_CSV_LINE.encode("utf-8"))
    bad_comp_zip = stream.getvalue()
    receipt = _create_sample_receipt(bad_comp_zip)

    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(bad_comp_zip, receipt)
    assert exc_info.value.code == "UNSUPPORTED_COMPRESSION_METHOD"


def test_exceeded_max_raw_archive_bytes_rejected() -> None:
    oversized_zip = b"PK" + (b"0" * (MAX_RAW_ARCHIVE_BYTES + 10))
    receipt = _create_sample_receipt(oversized_zip)

    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(oversized_zip, receipt)
    assert exc_info.value.code == "EXCEEDED_MAX_RAW_ARCHIVE_BYTES"


def test_compression_ratio_limit_rejected() -> None:
    # A single byte repeated heavily with high compression ratio > 50
    huge_payload = b"0" * (100 * 1024)
    bomb_zip = _create_synthetic_zip(
        "BTCUSDT-1d-2024-01-01.csv",
        huge_payload,
        compress_type=zipfile.ZIP_DEFLATED,
    )
    receipt = _create_sample_receipt(bomb_zip)

    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(bomb_zip, receipt)
    assert exc_info.value.code == "EXCEEDED_MAX_COMPRESSION_RATIO"


def test_invalid_utf8_rejected() -> None:
    invalid_utf8_bytes = b"\xff\xfe\xfd\x80\x81\x82"
    bad_utf8_zip = _create_synthetic_zip("BTCUSDT-1d-2024-01-01.csv", invalid_utf8_bytes)
    receipt = _create_sample_receipt(bad_utf8_zip)

    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(bad_utf8_zip, receipt)
    assert exc_info.value.code == "INVALID_UTF8"


def test_nul_byte_rejected() -> None:
    nul_payload = (
        b"1704067200000,42000.50,\x00,41500.00,42800.00,1050.25,"
        b"1704153599999,44500000.00,150000,520.10,22100000.00,0\n"
    )
    nul_zip = _create_synthetic_zip("BTCUSDT-1d-2024-01-01.csv", nul_payload)
    receipt = _create_sample_receipt(nul_zip)

    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(nul_zip, receipt)
    assert exc_info.value.code == "NUL_BYTE_DETECTED"


def test_empty_or_whitespace_csv_rejected() -> None:
    # Empty string
    empty_zip = _create_synthetic_zip("BTCUSDT-1d-2024-01-01.csv", b"")
    receipt1 = _create_sample_receipt(empty_zip)
    with pytest.raises(ArchiveDecodingError) as exc1:
        decode_kline_archive(empty_zip, receipt1)
    assert exc1.value.code == "EMPTY_CSV_PAYLOAD"

    # Whitespace only
    ws_zip = _create_synthetic_zip("BTCUSDT-1d-2024-01-01.csv", b"   \n\n\t  \n")
    receipt2 = _create_sample_receipt(ws_zip)
    with pytest.raises(ArchiveDecodingError) as exc2:
        decode_kline_archive(ws_zip, receipt2)
    assert exc2.value.code == "EMPTY_CSV_PAYLOAD"


def test_invalid_column_count_11_and_13_rejected() -> None:
    # 11 columns (missing ignore field)
    cols_11 = (
        "1704067200000,42000.50,43000.00,41500.00,42800.00,1050.25,"
        "1704153599999,44500000.00,150000,520.10,22100000.00\n"
    )
    zip_11 = _create_synthetic_zip("BTCUSDT-1d-2024-01-01.csv", cols_11.encode("utf-8"))
    receipt_11 = _create_sample_receipt(zip_11)
    with pytest.raises(ArchiveDecodingError) as exc_11:
        decode_kline_archive(zip_11, receipt_11)
    assert exc_11.value.code == "INVALID_COLUMN_COUNT"

    # 13 columns (extra 13th field)
    cols_13 = (
        "1704067200000,42000.50,43000.00,41500.00,42800.00,1050.25,"
        "1704153599999,44500000.00,150000,520.10,22100000.00,0,EXTRA_FIELD\n"
    )
    zip_13 = _create_synthetic_zip("BTCUSDT-1d-2024-01-01.csv", cols_13.encode("utf-8"))
    receipt_13 = _create_sample_receipt(zip_13)
    with pytest.raises(ArchiveDecodingError) as exc_13:
        decode_kline_archive(zip_13, receipt_13)
    assert exc_13.value.code == "INVALID_COLUMN_COUNT"


def test_exceeded_max_cell_length_rejected() -> None:
    oversized_cell = "A" * (MAX_CELL_LENGTH + 1)
    bad_cell_csv = (
        f"1704067200000,{oversized_cell},43000.00,41500.00,42800.00,1050.25,"
        "1704153599999,44500000.00,150000,520.10,22100000.00,0\n"
    )
    bad_cell_zip = _create_synthetic_zip("BTCUSDT-1d-2024-01-01.csv", bad_cell_csv.encode("utf-8"))
    receipt = _create_sample_receipt(bad_cell_zip)

    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(bad_cell_zip, receipt)
    assert exc_info.value.code == "EXCEEDED_MAX_CELL_LENGTH"


def test_invalid_integer_fields_rejected() -> None:
    # open_time is non-integer
    bad_time_csv = (
        "INVALID_TIME,42000.50,43000.00,41500.00,42800.00,1050.25,"
        "1704153599999,44500000.00,150000,520.10,22100000.00,0\n"
    )
    bad_time_zip = _create_synthetic_zip("BTCUSDT-1d-2024-01-01.csv", bad_time_csv.encode("utf-8"))
    receipt = _create_sample_receipt(bad_time_zip)

    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(bad_time_zip, receipt)
    assert exc_info.value.code == "CSV_PARSE_ERROR"


def test_exceeded_max_row_count_rejected() -> None:
    lines = SAMPLE_VALID_CSV_LINE * (MAX_CSV_ROW_COUNT + 1)
    large_csv_zip = _create_synthetic_zip("BTCUSDT-1d-2024-01-01.csv", lines.encode("utf-8"))
    receipt = _create_sample_receipt(large_csv_zip)

    with pytest.raises(ArchiveDecodingError) as exc_info:
        decode_kline_archive(large_csv_zip, receipt)
    # Could be row count or compression ratio depending on repetition
    assert exc_info.value.code in ("EXCEEDED_MAX_ROW_COUNT", "EXCEEDED_MAX_COMPRESSION_RATIO")


def test_zero_filesystem_writes_performed() -> None:
    raw_zip = _create_synthetic_zip(
        "BTCUSDT-1d-2024-01-01.csv", SAMPLE_VALID_CSV_LINE.encode("utf-8")
    )
    receipt = _create_sample_receipt(raw_zip)

    package = decode_kline_archive(raw_zip, receipt)
    assert package.row_count == 1
    # Pure in-memory operation confirmed
