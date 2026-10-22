"""Dataset catalog discovery, indexing, crash recovery, and staging maintenance utilities."""

import os
import re
import shutil
import time
import uuid
from pathlib import Path

from research.datasets.exceptions import DatasetNotFoundError
from research.datasets.manifest import DatasetManifest
from research.datasets.reader import DatasetReader
from research.datasets.writer import SAFE_ID_REGEX, DatasetLock

HEX_SUFFIX_REGEX = re.compile(r"^[0-9a-fA-F]{8}$")


def _extract_dataset_id_from_name(prefix: str, name: str) -> str | None:
    """Extract and validate dataset ID from prefixed directory names like .staging_<id>_<uuid8>.

    Requirements:
    - name must start with prefix.
    - suffix must be exactly '_' followed by 8 hexadecimal characters.
    - extracted dataset ID must be non-empty and conform to SAFE_ID_REGEX.
    - returns None if malformed, missing suffix, or invalid format.
    """
    if not name.startswith(prefix):
        return None
    remainder = name[len(prefix):]
    if len(remainder) <= 9 or remainder[-9] != "_":
        return None
    suffix = remainder[-8:]
    if not HEX_SUFFIX_REGEX.match(suffix):
        return None
    cand = remainder[:-9]
    return cand if (cand and SAFE_ID_REGEX.match(cand)) else None


class DatasetCatalog:
    """Catalog manager for discovering, verifying, recovering, and maintaining datasets."""

    def __init__(self, root_dir: Path | str = "data/processed") -> None:
        self.root_dir = Path(root_dir).resolve()

    def list_datasets(self) -> list[DatasetManifest]:
        """Discover and return manifests for all valid, completed datasets in the root directory."""
        if not self.root_dir.is_dir():
            return []

        manifests: list[DatasetManifest] = []
        for entry in sorted(self.root_dir.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                manifest_file = entry / "manifest.json"
                if manifest_file.is_file():
                    try:
                        manifest = DatasetManifest.from_file(manifest_file)
                        if manifest.is_complete:
                            manifests.append(manifest)
                    except Exception:
                        # Skip malformed or incompatible manifests during catalog scan
                        pass
        return manifests

    def get_dataset(self, dataset_id: str) -> DatasetManifest:
        """Retrieve manifest for a specific dataset ID."""
        if not SAFE_ID_REGEX.match(dataset_id):
            raise DatasetNotFoundError(f"Invalid dataset ID format: '{dataset_id}'")

        dataset_path = self.root_dir / dataset_id
        manifest_file = dataset_path / "manifest.json"
        if not manifest_file.is_file():
            raise DatasetNotFoundError(
                f"Dataset '{dataset_id}' not found in catalog at '{dataset_path}'"
            )

        return DatasetManifest.from_file(manifest_file)

    def verify_dataset(self, dataset_id: str) -> tuple[bool, list[str]]:
        """Run full cryptographic integrity verification on a dataset."""
        reader = DatasetReader(dataset_id, root_dir=self.root_dir)
        return reader.verify_integrity()

    def recover_datasets(self) -> dict[str, list[str]]:
        """Execute deterministic crash recovery protocol over leftover .backup_* directories.

        Protocol rules:
        1. Discover all .backup_* directories in root_dir.
        2. Coordinate with DatasetLock: if a dataset write lock is held by another process,
           skip it to prevent racing with an active writer.
        3. If manifest.json is missing or unparseable, quarantine the backup; never delete.
        4. If target_dir is missing:
           - Validate backup integrity (SHA-256 and Parquet metadata).
           - If valid, promote backup to target_dir via atomic rename (os.replace).
           - If invalid, preserve backup in quarantine (.corrupt_backup_*); never delete.
        5. If target_dir already exists:
           - Validate target_dir integrity.
           - If target_dir is corrupt but backup is valid, preserve corrupt target
             and restore backup.
           - If both are invalid, preserve both in quarantine; never delete.

        Returns:
            Dictionary summarizing actions taken:
            {"recovered": [...], "quarantined": [...], "redundant": [...]}
        """
        if not self.root_dir.is_dir():
            return {"recovered": [], "quarantined": [], "redundant": []}

        recovered: list[str] = []
        quarantined: list[str] = []
        redundant: list[str] = []

        # Sort backups by modification time (most recent first)
        backup_entries = [
            e for e in self.root_dir.iterdir()
            if e.is_dir() and e.name.startswith(".backup_")
        ]
        backup_entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        for backup_dir in backup_entries:
            manifest_file = backup_dir / "manifest.json"
            backup_manifest: DatasetManifest | None = None
            dataset_id: str | None = None

            if manifest_file.is_file():
                try:
                    backup_manifest = DatasetManifest.from_file(manifest_file)
                    dataset_id = backup_manifest.dataset_id
                except Exception:
                    pass

            if dataset_id is None:
                dataset_id = _extract_dataset_id_from_name(".backup_", backup_dir.name)

            if dataset_id is None or not SAFE_ID_REGEX.match(dataset_id):
                quarantine_name = f".corrupt_backup_unknown_{uuid.uuid4().hex[:6]}"
                try:
                    os.replace(backup_dir, self.root_dir / quarantine_name)
                    quarantined.append(quarantine_name)
                except Exception:
                    quarantined.append(backup_dir.name)
                continue

            # COORDINATED LOCKING PROTOCOL:
            lock = DatasetLock(self.root_dir, dataset_id)
            if not lock.acquire(raise_on_conflict=False):
                # An active writer or transaction holds the lock; do not race
                continue

            try:
                if backup_manifest is None:
                    quarantine_name = f".corrupt_backup_{dataset_id}_invalid_{uuid.uuid4().hex[:6]}"
                    try:
                        os.replace(backup_dir, self.root_dir / quarantine_name)
                        quarantined.append(quarantine_name)
                    except Exception:
                        quarantined.append(backup_dir.name)
                    continue

                target_dir = self.root_dir / dataset_id

                if not target_dir.exists():
                    # Case A: Target is missing! Backup contains the only potential valid copy
                    backup_ok, _ = backup_manifest.verify_integrity(backup_dir)
                    if backup_ok:
                        try:
                            os.replace(backup_dir, target_dir)
                            recovered.append(dataset_id)
                        except Exception:
                            quarantined.append(backup_dir.name)
                    else:
                        # Backup is corrupt; preserve in quarantine
                        quarantine_name = f".corrupt_backup_{dataset_id}_{uuid.uuid4().hex[:6]}"
                        try:
                            os.replace(backup_dir, self.root_dir / quarantine_name)
                            quarantined.append(quarantine_name)
                        except Exception:
                            quarantined.append(backup_dir.name)
                else:
                    # Case B: Both target and backup exist
                    target_manifest_file = target_dir / "manifest.json"
                    target_valid = False
                    if target_manifest_file.is_file():
                        try:
                            target_manifest = DatasetManifest.from_file(target_manifest_file)
                            ok, _ = target_manifest.verify_integrity(target_dir)
                            target_valid = ok
                        except Exception:
                            target_valid = False

                    if target_valid:
                        # Target is verified complete; backup is confirmed redundant
                        redundant.append(backup_dir.name)
                    else:
                        # Target is invalid or corrupt! Check backup
                        backup_ok, _ = backup_manifest.verify_integrity(backup_dir)
                        if backup_ok:
                            # Move corrupt target to quarantine and promote backup to target
                            hex_suffix = uuid.uuid4().hex[:6]
                            quarantine_target = f".corrupt_target_{dataset_id}_{hex_suffix}"
                            try:
                                os.replace(target_dir, self.root_dir / quarantine_target)
                                os.replace(backup_dir, target_dir)
                                quarantined.append(quarantine_target)
                                recovered.append(dataset_id)
                            except Exception:
                                quarantined.append(backup_dir.name)
                        else:
                            # Both are invalid; preserve both
                            quarantine_name = f".corrupt_backup_{dataset_id}_{uuid.uuid4().hex[:6]}"
                            try:
                                os.replace(backup_dir, self.root_dir / quarantine_name)
                                quarantined.append(quarantine_name)
                            except Exception:
                                quarantined.append(backup_dir.name)
            finally:
                lock.release()

        return {"recovered": recovered, "quarantined": quarantined, "redundant": redundant}

    def clean_stale_staging(self, max_age_seconds: float = 3600.0) -> int:
        """Remove leftover disposable .staging_* and verified redundant .backup_* directories.

        Guarantees:
        - Automatically runs recover_datasets() before any cleanup.
        - Coordinates with DatasetLock: active writers are never interfered with.
        - Never deletes a .backup_* directory if the target dataset is missing or unverified.
        - Only deletes .backup_* if target_dir exists and passes full cryptographic verification.
        """
        if not self.root_dir.is_dir():
            return 0

        # Step 1: Execute recovery protocol to restore any recoverable backups
        self.recover_datasets()

        now = time.time()
        cleaned = 0

        for entry in self.root_dir.iterdir():
            if not entry.is_dir():
                continue

            # Disposable staging directories older than max_age_seconds
            if entry.name.startswith(".staging_"):
                candidate_id = _extract_dataset_id_from_name(".staging_", entry.name)
                if candidate_id is not None:
                    lock = DatasetLock(self.root_dir, candidate_id)
                    if not lock.acquire(raise_on_conflict=False):
                        # Active writer holds the lock; do not delete staging
                        continue
                    try:
                        mtime = entry.stat().st_mtime
                        if (now - mtime) > max_age_seconds:
                            shutil.rmtree(entry, ignore_errors=True)
                            cleaned += 1
                    except (OSError, FileNotFoundError):
                        pass
                    finally:
                        lock.release()

            # Redundant backup directories: ONLY purge if target exists and is verified valid
            elif entry.name.startswith(".backup_"):
                manifest_path = entry / "manifest.json"
                if manifest_path.is_file():
                    try:
                        m = DatasetManifest.from_file(manifest_path)
                        dataset_id = m.dataset_id
                        lock = DatasetLock(self.root_dir, dataset_id)
                        if not lock.acquire(raise_on_conflict=False):
                            # Active writer holds lock; do not touch backup
                            continue
                        try:
                            target = self.root_dir / dataset_id
                            tgt_manifest = target / "manifest.json"
                            if target.is_dir() and tgt_manifest.is_file():
                                target_manifest = DatasetManifest.from_file(tgt_manifest)
                                target_ok, _ = target_manifest.verify_integrity(target)
                                if target_ok:
                                    mtime = entry.stat().st_mtime
                                    if (now - mtime) > max_age_seconds:
                                        shutil.rmtree(entry, ignore_errors=True)
                                        cleaned += 1
                        finally:
                            lock.release()
                    except Exception:
                        # Preserve whenever validation fails or encounters errors
                        pass

        return cleaned
