"""Immutable filesystem snapshot store with atomic staging and verified reopen."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from simulator.application.ports.snapshot_store import (
    SnapshotStorePort,
    StoredAcquisitionPackage,
)
from simulator.domain.canonical import canonicalize_json
from simulator.domain.errors import SnapshotStoreError
from simulator.domain.models import AcquisitionReceipt
from simulator.infrastructure.adapters.archive_decoder import (
    MAX_RAW_ARCHIVE_BYTES,
    MAX_UNCOMPRESSED_MEMBER_BYTES,
)

SNAPSHOT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^ds-snap_[a-zA-Z0-9_-]+$")
ACQUISITION_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^acq_[a-zA-Z0-9_-]+$")


@dataclass
class SnapshotStoreFailureInjector:
    """Explicit seam for injecting controlled filesystem failures during testing."""

    fail_before_staging_write: bool = False
    fail_after_staging_write: bool = False
    fail_during_atomic_rename: bool = False
    fail_during_reopen: bool = False

    def on_before_staging_write(
        self,
        staging_dir: Path,
        package: StoredAcquisitionPackage,
    ) -> None:
        if self.fail_before_staging_write:
            raise SnapshotStoreError(
                "Injected failure before staging write",
                code="INJECTED_FAILURE",
            )

    def on_after_staging_write(self, staging_dir: Path) -> None:
        if self.fail_after_staging_write:
            raise SnapshotStoreError(
                "Injected failure after staging write",
                code="INJECTED_FAILURE",
            )

    def on_during_atomic_rename(self, staging_dir: Path, target_dir: Path) -> None:
        if self.fail_during_atomic_rename:
            raise SnapshotStoreError(
                "Injected failure during atomic rename",
                code="INJECTED_FAILURE",
            )

    def on_during_reopen(self, target_dir: Path) -> None:
        if self.fail_during_reopen:
            raise SnapshotStoreError(
                "Injected failure during reopen",
                code="INJECTED_FAILURE",
            )


class FileSystemSnapshotStore(SnapshotStorePort):
    """Production filesystem adapter for immutable dataset snapshots under a private root."""

    def __init__(
        self,
        root_dir: str | Path,
        failure_injector: SnapshotStoreFailureInjector | None = None,
        max_raw_bytes: int = MAX_RAW_ARCHIVE_BYTES,
        max_normalized_bytes: int = MAX_UNCOMPRESSED_MEMBER_BYTES,
    ) -> None:
        if max_raw_bytes < 1 or max_normalized_bytes < 1:
            raise ValueError("snapshot byte limits must be positive")
        self._root = Path(root_dir).resolve()
        self._snapshots_dir = self._root / "snapshots"
        self._staging_dir = self._root / "staging"
        self._failure_injector = failure_injector
        self._max_raw_bytes = max_raw_bytes
        self._max_normalized_bytes = max_normalized_bytes

        self._snapshots_dir.mkdir(parents=True, exist_ok=True)
        self._staging_dir.mkdir(parents=True, exist_ok=True)
        for directory in (self._snapshots_dir, self._staging_dir):
            if directory.is_symlink() or not directory.is_dir():
                raise SnapshotStoreError(
                    "Snapshot store directory must be a real directory",
                    code="SYMLINK_NOT_ALLOWED",
                )

    def _validate_identifiers(self, snapshot_id: str, acquisition_id: str) -> None:
        """Reject unsafe, absolute, traversal, or malformed identity components before I/O."""
        if not snapshot_id or not SNAPSHOT_ID_PATTERN.match(snapshot_id):
            raise SnapshotStoreError(
                f"Invalid snapshot_id format: {snapshot_id!r}",
                code="INVALID_IDENTIFIER",
            )
        if not acquisition_id or not ACQUISITION_ID_PATTERN.match(acquisition_id):
            raise SnapshotStoreError(
                f"Invalid acquisition_id format: {acquisition_id!r}",
                code="INVALID_IDENTIFIER",
            )
        for val in (snapshot_id, acquisition_id):
            if ".." in val or "/" in val or "\\" in val or "\x00" in val or ":" in val:
                raise SnapshotStoreError(
                    "Illegal path traversal or separator character in identifier",
                    code="INVALID_IDENTIFIER",
                )

    def _get_target_dir(self, snapshot_id: str, acquisition_id: str) -> Path:
        self._validate_identifiers(snapshot_id, acquisition_id)
        target = (self._snapshots_dir / snapshot_id / acquisition_id).resolve()
        if not target.is_relative_to(self._snapshots_dir.resolve()):
            raise SnapshotStoreError(
                "Resolved target path escapes snapshots root directory",
                code="INVALID_IDENTIFIER",
            )
        return target

    def store(self, package: StoredAcquisitionPackage) -> None:
        """Store an accepted acquisition package atomically under its immutable version identity.

        Decision on Identical Republishing:
        - If an acquisition package with identical hashes and receipt already exists at target,
          succeeds idempotently without modifying disk state.
        - If an acquisition already exists with conflicting content/hashes (overwrite attempt),
          raises SnapshotStoreError with code 'OVERWRITE_FORBIDDEN'.
        """
        receipt = package.receipt
        if receipt.verification_outcome != "ACCEPTED" or receipt.failure_reasons:
            raise SnapshotStoreError(
                "Cannot store acquisition package with unaccepted receipt",
                code="RECEIPT_NOT_ACCEPTED",
            )

        snapshot_id = receipt.snapshot_id
        acquisition_id = receipt.acquisition_id
        target_dir = self._get_target_dir(snapshot_id, acquisition_id)

        # 1. Pre-publication cryptographic and size checks
        raw_size = len(package.raw_bytes)
        if raw_size > self._max_raw_bytes:
            raise SnapshotStoreError(
                "Raw acquisition exceeds the configured snapshot-store limit",
                code="RAW_SIZE_LIMIT_EXCEEDED",
            )
        if len(package.normalized_bytes) > self._max_normalized_bytes:
            raise SnapshotStoreError(
                "Normalized acquisition exceeds the configured snapshot-store limit",
                code="NORMALIZED_SIZE_LIMIT_EXCEEDED",
            )
        if raw_size != receipt.raw_byte_size:
            raise SnapshotStoreError(
                "Raw bytes length does not match receipt raw_byte_size",
                code="RAW_SIZE_MISMATCH",
            )

        computed_raw_sha256 = f"sha256:{hashlib.sha256(package.raw_bytes).hexdigest()}"
        if not hmac.compare_digest(computed_raw_sha256, receipt.raw_artifact_sha256):
            raise SnapshotStoreError(
                "Raw bytes digest does not match receipt raw_artifact_sha256",
                code="RAW_HASH_MISMATCH",
            )

        computed_norm_sha256 = f"sha256:{hashlib.sha256(package.normalized_bytes).hexdigest()}"
        if not hmac.compare_digest(computed_norm_sha256, receipt.normalized_snapshot_sha256):
            raise SnapshotStoreError(
                "Normalized bytes digest does not match receipt normalized_snapshot_sha256",
                code="NORMALIZED_HASH_MISMATCH",
            )

        # 2. Check for existing target directory (Idempotence vs Collision)
        if target_dir.is_symlink():
            raise SnapshotStoreError(
                "Target snapshot path is an illegal symlink",
                code="SYMLINK_NOT_ALLOWED",
            )

        if target_dir.exists():
            # Attempt verified reopen to determine identity
            existing = self.load(acquisition_id=acquisition_id, snapshot_id=snapshot_id)
            same_receipt = existing.receipt.compute_hash() == receipt.compute_hash()
            same_raw = hmac.compare_digest(
                hashlib.sha256(existing.raw_bytes).digest(),
                hashlib.sha256(package.raw_bytes).digest(),
            )
            same_norm = hmac.compare_digest(
                hashlib.sha256(existing.normalized_bytes).digest(),
                hashlib.sha256(package.normalized_bytes).digest(),
            )
            if same_receipt and same_raw and same_norm:
                # Idempotent republishing confirmed: no-op
                return
            else:
                raise SnapshotStoreError(
                    "Acquisition already exists with different contents; overwrite is forbidden",
                    code="OVERWRITE_FORBIDDEN",
                )

        # 3. Atomic checksum-first staging
        staging_dir = self._staging_dir / f"stage_{uuid.uuid4().hex}"
        staging_dir.mkdir(parents=True, exist_ok=False)

        try:
            if self._failure_injector:
                self._failure_injector.on_before_staging_write(staging_dir, package)

            receipt_canonical = canonicalize_json(receipt.to_dict())
            (staging_dir / "receipt.json").write_bytes(receipt_canonical.encode("utf-8"))
            (staging_dir / "raw.bin").write_bytes(package.raw_bytes)
            (staging_dir / "normalized.jsonl").write_bytes(package.normalized_bytes)

            if self._failure_injector:
                self._failure_injector.on_after_staging_write(staging_dir)

            # Re-verify written files on disk before moving
            staged_receipt_bytes = (staging_dir / "receipt.json").read_bytes()
            staged_raw_bytes = (staging_dir / "raw.bin").read_bytes()
            staged_norm_bytes = (staging_dir / "normalized.jsonl").read_bytes()

            if (
                not hmac.compare_digest(
                    staged_receipt_bytes,
                    receipt_canonical.encode("utf-8"),
                )
                or not hmac.compare_digest(
                    hashlib.sha256(staged_raw_bytes).digest(),
                    hashlib.sha256(package.raw_bytes).digest(),
                )
                or not hmac.compare_digest(
                    hashlib.sha256(staged_norm_bytes).digest(),
                    hashlib.sha256(package.normalized_bytes).digest(),
                )
            ):
                raise SnapshotStoreError(
                    "Staged file byte verification failed",
                    code="STAGING_FAILURE",
                )

            target_dir.parent.mkdir(parents=True, exist_ok=True)

            if self._failure_injector:
                self._failure_injector.on_during_atomic_rename(staging_dir, target_dir)

            staging_dir.rename(target_dir)

        except Exception as exc:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            if isinstance(exc, SnapshotStoreError):
                raise
            raise SnapshotStoreError(
                "Filesystem staging or publication failure",
                code="STAGING_FAILURE",
            ) from exc
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)

    def load(self, acquisition_id: str, snapshot_id: str) -> StoredAcquisitionPackage:
        """Reopen and re-verify an existing stored acquisition package from disk."""
        target_dir = self._get_target_dir(snapshot_id, acquisition_id)

        if not target_dir.exists():
            raise SnapshotStoreError(
                f"Acquisition package not found: {acquisition_id}",
                code="ACQUISITION_NOT_FOUND",
            )

        if target_dir.is_symlink():
            raise SnapshotStoreError(
                "Target snapshot path is an illegal symlink",
                code="SYMLINK_NOT_ALLOWED",
            )

        if not target_dir.is_dir():
            raise SnapshotStoreError(
                "Target snapshot path is not a directory",
                code="TAMPERED_STORED_PACKAGE",
            )

        receipt_path = target_dir / "receipt.json"
        raw_path = target_dir / "raw.bin"
        normalized_path = target_dir / "normalized.jsonl"

        for p in (receipt_path, raw_path, normalized_path):
            if not p.exists() or not p.is_file():
                raise SnapshotStoreError(
                    "Missing expected file in snapshot package",
                    code="TAMPERED_STORED_PACKAGE",
                )
            if p.is_symlink():
                raise SnapshotStoreError(
                    "Illegal symlink detected in snapshot package file",
                    code="SYMLINK_NOT_ALLOWED",
                )

        if self._failure_injector:
            self._failure_injector.on_during_reopen(target_dir)

        receipt_bytes = receipt_path.read_bytes()
        raw_bytes = raw_path.read_bytes()
        normalized_bytes = normalized_path.read_bytes()

        # Parse and validate receipt
        try:
            receipt_dict = json.loads(receipt_bytes.decode("utf-8"))
            receipt = AcquisitionReceipt.from_dict(receipt_dict)
        except Exception as exc:
            raise SnapshotStoreError(
                "Failed to deserialize stored acquisition receipt",
                code="TAMPERED_STORED_PACKAGE",
            ) from exc

        if receipt.verification_outcome != "ACCEPTED" or receipt.failure_reasons:
            raise SnapshotStoreError(
                "Stored receipt is not ACCEPTED",
                code="RECEIPT_NOT_ACCEPTED",
            )

        if receipt.snapshot_id != snapshot_id or receipt.acquisition_id != acquisition_id:
            raise SnapshotStoreError(
                "Stored receipt identity does not match requested snapshot/acquisition",
                code="TAMPERED_STORED_PACKAGE",
            )

        # Cryptographic verification on reopen
        if len(raw_bytes) != receipt.raw_byte_size:
            raise SnapshotStoreError(
                "Stored raw bytes size mismatch on reopen",
                code="RAW_SIZE_MISMATCH",
            )

        computed_raw_sha256 = f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"
        if not hmac.compare_digest(computed_raw_sha256, receipt.raw_artifact_sha256):
            raise SnapshotStoreError(
                "Stored raw bytes digest mismatch on reopen",
                code="RAW_HASH_MISMATCH",
            )

        computed_norm_sha256 = f"sha256:{hashlib.sha256(normalized_bytes).hexdigest()}"
        if not hmac.compare_digest(computed_norm_sha256, receipt.normalized_snapshot_sha256):
            raise SnapshotStoreError(
                "Stored normalized bytes digest mismatch on reopen",
                code="NORMALIZED_HASH_MISMATCH",
            )

        return StoredAcquisitionPackage(
            receipt=receipt,
            raw_bytes=raw_bytes,
            normalized_bytes=normalized_bytes,
        )

    def exists(self, acquisition_id: str, snapshot_id: str) -> bool:
        """Return whether a complete package exists and passes verified reopen."""
        try:
            self.load(acquisition_id=acquisition_id, snapshot_id=snapshot_id)
            return True
        except SnapshotStoreError:
            return False

    def list_acquisitions(self, snapshot_id: str | None = None) -> tuple[str, ...]:
        """Return a sorted tuple of all published acquisition IDs."""
        acquisitions: list[str] = []
        if snapshot_id is not None:
            self._validate_identifiers(snapshot_id, "acq_temp")
            snap_dir = self._snapshots_dir / snapshot_id
            if snap_dir.exists() and snap_dir.is_dir() and not snap_dir.is_symlink():
                for item in snap_dir.iterdir():
                    if (
                        item.is_dir()
                        and not item.is_symlink()
                        and ACQUISITION_ID_PATTERN.match(item.name)
                    ):
                        acquisitions.append(item.name)
        else:
            if self._snapshots_dir.exists():
                for snap_item in self._snapshots_dir.iterdir():
                    if (
                        snap_item.is_dir()
                        and not snap_item.is_symlink()
                        and SNAPSHOT_ID_PATTERN.match(snap_item.name)
                    ):
                        for item in snap_item.iterdir():
                            if (
                                item.is_dir()
                                and not item.is_symlink()
                                and ACQUISITION_ID_PATTERN.match(item.name)
                            ):
                                acquisitions.append(item.name)

        return tuple(sorted(set(acquisitions)))

    def prune(
        self,
        max_retained: int,
        protected_acquisition_ids: tuple[str, ...] = (),
    ) -> int:
        """Prune oldest acquisitions exceeding max_retained, excluding protected IDs."""
        if max_retained < 1:
            raise ValueError("max_retained must be >= 1")

        # Find all stored acquisitions across all snapshots
        entries: list[tuple[str, Path, str, str]] = []  # (retrieval_time, path, snap_id, acq_id)

        if self._snapshots_dir.exists():
            for snap_dir in sorted(self._snapshots_dir.iterdir()):
                if (
                    not snap_dir.is_dir()
                    or snap_dir.is_symlink()
                    or not SNAPSHOT_ID_PATTERN.match(snap_dir.name)
                ):
                    continue
                for acq_dir in sorted(snap_dir.iterdir()):
                    if (
                        not acq_dir.is_dir()
                        or acq_dir.is_symlink()
                        or not ACQUISITION_ID_PATTERN.match(acq_dir.name)
                    ):
                        continue
                    receipt_path = acq_dir / "receipt.json"
                    retrieval_time = ""
                    if receipt_path.is_file():
                        try:
                            data = json.loads(receipt_path.read_text(encoding="utf-8"))
                            retrieval_time = data.get("retrieval_time", "")
                        except Exception:
                            retrieval_time = ""
                    entries.append((retrieval_time, acq_dir, snap_dir.name, acq_dir.name))

        # Sort chronologically by retrieval_time, then acquisition_id
        entries.sort(key=lambda x: (x[0], x[3]))

        total_count = len(entries)
        if total_count <= max_retained:
            return 0

        pruned_count = 0
        # Determine candidates for pruning starting from oldest
        for retrieval_time, acq_path, snap_id, acq_id in entries:
            if len(entries) - pruned_count <= max_retained:
                break
            if acq_id in protected_acquisition_ids:
                # Protected acquisition cannot be pruned
                continue
            # Remove directory
            try:
                shutil.rmtree(acq_path)
            except OSError as exc:
                raise SnapshotStoreError(
                    "Failed to prune immutable acquisition package",
                    code="PRUNE_FAILURE",
                ) from exc
            pruned_count += 1
            # If parent snapshot directory is empty, remove it
            snap_path = self._snapshots_dir / snap_id
            if snap_path.exists() and not any(snap_path.iterdir()):
                snap_path.rmdir()

        return pruned_count
