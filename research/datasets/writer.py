"""Atomic, partitioned dataset writer for research datasets using Apache Arrow and Parquet."""

import fcntl
import os
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from research.datasets.exceptions import (
    DatasetExistsError,
    DatasetIntegrityError,
    DatasetLockError,
    InvalidDatasetNameError,
    SchemaMismatchError,
)
from research.datasets.manifest import DatasetManifest, PartitionFile, compute_file_sha256
from research.datasets.schema import SchemaRegistry, SchemaVersion, get_schema_registry
from research.datasets.types import (
    CompressionType,
    DataDomain,
    DatasetKind,
    ProvenanceInfo,
    ValidationStatus,
)

SAFE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")


class DatasetLock:
    """Process-level exclusive file lock coordinating writers, recovery, and cleanup.

    Protocol:
    - Lock file path: {lake_root}/.lock_{dataset_id}
    - Uses non-blocking exclusive POSIX flock (fcntl.LOCK_EX | fcntl.LOCK_NB).
    - When acquired, the open file descriptor is held until release() is called.
    - If the lock is held by another process or thread, acquire() returns False or raises
      DatasetLockError.
    - On release, fcntl.LOCK_UN is issued and the file descriptor is closed.
    - Lock file persistence: The .lock_{dataset_id} file persists on disk as an empty file
      to prevent unlinking races between processes. Persistent existence of the file does NOT
      mean a transaction is active; active status is determined strictly by whether an advisory
      exclusive flock is currently held.
    """

    def __init__(self, root_dir: Path | str, dataset_id: str) -> None:
        self.root_dir = Path(root_dir).resolve()
        DatasetWriter._validate_id(dataset_id)
        self.dataset_id = dataset_id
        self.lock_path = (self.root_dir / f".lock_{self.dataset_id}").resolve()
        if not self.lock_path.is_relative_to(self.root_dir):
            raise InvalidDatasetNameError(f"Dataset lock path escapes root: {self.lock_path}")
        self._file: Any = None
        self._is_locked = False

    def acquire(self, raise_on_conflict: bool = True) -> bool:
        """Attempt to acquire exclusive, non-blocking lock.

        Returns True if acquired.
        If held by another process:
          - If raise_on_conflict is True: raises DatasetLockError.
          - If raise_on_conflict is False: returns False.
        """
        if self._is_locked:
            return True

        self.root_dir.mkdir(parents=True, exist_ok=True)
        try:
            fd = open(self.lock_path, "a+")
        except OSError as e:
            if raise_on_conflict:
                raise DatasetLockError(f"Could not open lock file {self.lock_path}: {e}") from e
            return False

        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._file = fd
            self._is_locked = True
            return True
        except (BlockingIOError, OSError) as e:
            try:
                fd.close()
            except Exception:
                pass
            if raise_on_conflict:
                raise DatasetLockError(
                    f"Dataset '{self.dataset_id}' is currently locked by another active writer."
                ) from e
            return False

    def release(self) -> None:
        """Release the advisory lock and close the descriptor."""
        if self._file is not None:
            try:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None
            self._is_locked = False

    def __enter__(self) -> "DatasetLock":
        self.acquire(raise_on_conflict=True)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self.release()

    @property
    def is_locked(self) -> bool:
        return self._is_locked

    @classmethod
    def is_active(cls, root_dir: Path | str, dataset_id: str) -> bool:
        """Check whether dataset_id is actively locked by any process."""
        try:
            lock = cls(root_dir, dataset_id)
        except Exception:
            return False
        if not lock.lock_path.is_file():
            return False
        acquired = lock.acquire(raise_on_conflict=False)
        if acquired:
            lock.release()
            return False
        return True


class DatasetWriter:
    """Safe, atomic, transactional writer for partitioned Apache Parquet research datasets."""

    def __init__(
        self,
        dataset_id: str,
        name: str,
        kind: DatasetKind,
        domain: DataDomain,
        schema_name: str,
        root_dir: Path | str = "data/processed",
        schema_version: SchemaVersion | str | None = None,
        partition_by: list[str] | None = None,
        compression: CompressionType = CompressionType.ZSTD,
        provenance: ProvenanceInfo | None = None,
        overwrite: bool = False,
        registry: SchemaRegistry | None = None,
    ) -> None:
        self._validate_id(dataset_id)
        self.dataset_id = dataset_id
        self.name = name
        self.kind = kind
        self.domain = domain
        self.schema_name = schema_name
        self.registry = registry or get_schema_registry()

        if schema_version is None:
            registered = self.registry.get_registered(self.schema_name)
            self.schema_version = registered.version
            self.arrow_schema = registered.schema
        else:
            self.schema_version = (
                SchemaVersion.from_str(str(schema_version))
                if isinstance(schema_version, str)
                else schema_version
            )
            self.arrow_schema = self.registry.get(self.schema_name, self.schema_version)

        self.root_dir = Path(root_dir).resolve()
        self.partition_by = list(partition_by) if partition_by else []
        self.compression = compression
        self.provenance = provenance or ProvenanceInfo()
        self.overwrite = overwrite

        # Target and staging paths (guaranteed on same filesystem root)
        self.target_dir = self.root_dir / self.dataset_id
        self.staging_id = f".staging_{self.dataset_id}_{uuid.uuid4().hex[:8]}"
        self.staging_dir = self.root_dir / self.staging_id

        # Coordinated process lock
        self._lock = DatasetLock(self.root_dir, self.dataset_id)

        # Verify target existence before proceeding
        if self.target_dir.exists() and not self.overwrite:
            raise DatasetExistsError(
                f"Dataset directory '{self.target_dir}' already exists and overwrite=False."
            )

        # Active state tracking
        self._is_open = False
        self._writers: dict[str, pq.ParquetWriter] = {}
        self._partition_counts: dict[str, int] = {}
        self._partition_values: dict[str, dict[str, Any]] = {}
        self._min_timestamps: dict[str, int] = {}
        self._max_timestamps: dict[str, int] = {}
        self._min_sequences: dict[str, int] = {}
        self._max_sequences: dict[str, int] = {}

        self._all_instruments: set[int] = set()
        self._all_venues: set[int] = set()
        self._all_feeds: set[int] = set()
        self._all_dates: set[str] = set()

        self._total_records = 0
        self._global_min_ts: int | None = None
        self._global_max_ts: int | None = None

        self._part_counter = 0

    @staticmethod
    def _validate_id(ident: str) -> None:
        if ".." in ident or "/" in ident or "\\" in ident:
            raise InvalidDatasetNameError(f"Path traversal detected in dataset ID: '{ident}'")
        if not ident or not SAFE_ID_REGEX.match(ident):
            raise InvalidDatasetNameError(
                f"Invalid dataset ID: '{ident}'. "
                "Must contain only alphanumeric, underscore, or hyphen."
            )

    def __enter__(self) -> "DatasetWriter":
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if exc_type is not None:
            self.abort()
        else:
            self.close()

    def open(self) -> None:
        """Initialize staging directory and acquire exclusive dataset write lock."""
        if self._is_open:
            return
        self.root_dir.mkdir(parents=True, exist_ok=True)

        # Acquire non-blocking exclusive process lock on dataset_id
        self._lock.acquire(raise_on_conflict=True)

        self.staging_dir.mkdir(parents=True, exist_ok=False)
        self._is_open = True

    def _release_lock(self) -> None:
        self._lock.release()

    def write_batch(self, batch: pa.RecordBatch | pa.Table) -> None:
        """Write a bounded batch of records into the dataset."""
        if not self._is_open:
            raise DatasetIntegrityError("DatasetWriter is not open.")

        table = pa.Table.from_batches([batch]) if isinstance(batch, pa.RecordBatch) else batch

        # Validate schema conformance
        self.registry.validate_batch(self.schema_name, table, self.schema_version)

        if table.num_rows == 0:
            return

        self._record_global_stats(table)

        if not self.partition_by:
            # Single default partition
            part_key = "default"
            rel_path = f"part-{self._part_counter:05d}.parquet"
            writer = self._get_or_create_writer(part_key, rel_path, {})
            writer.write_table(table)
            self._update_part_stats(part_key, table)
        else:
            # Partition by specified columns using Arrow-native grouping
            self._write_partitioned_table(table)

    def _write_partitioned_table(self, table: pa.Table) -> None:
        """Partition table by specified partition columns natively in Arrow."""
        working_table = table

        # If date is a partition column and not physically in schema, derive it in Arrow
        date_added = False
        if "date" in self.partition_by and "date" not in working_table.column_names:
            if "source_timestamp_ns" in working_table.column_names:
                date_col = pc.strftime(
                    pc.cast(working_table["source_timestamp_ns"], pa.timestamp("ns")),
                    "%Y-%m-%d",
                )
                working_table = working_table.append_column("date", date_col)
                date_added = True
            else:
                raise SchemaMismatchError(
                    "Partition column 'date' requires 'source_timestamp_ns' in table schema."
                )

        for col in self.partition_by:
            if col not in working_table.column_names:
                raise SchemaMismatchError(
                    f"Partition column '{col}' is not present in schema fields."
                )

        # Arrow-native aggregation to find distinct partition combinations in C++
        grouped = working_table.group_by(self.partition_by).aggregate([])
        combos = grouped.to_pylist()

        for combo in combos:
            # Build boolean filter mask natively in Arrow
            mask = None
            path_segments: list[str] = []
            part_values: dict[str, Any] = {}

            for col in self.partition_by:
                val = combo[col]
                part_values[col] = val
                path_segments.append(f"{col}={val}")
                cond = pc.equal(working_table[col], val)
                mask = cond if mask is None else pc.and_(mask, cond)

            if mask is None:
                continue

            sub_table = working_table.filter(mask)
            if date_added and "date" not in self.arrow_schema.names:
                sub_table = sub_table.drop(["date"])

            part_dir_rel = "/".join(path_segments)
            part_key = part_dir_rel
            rel_path = f"{part_dir_rel}/part-{self._part_counter:05d}.parquet"

            writer = self._get_or_create_writer(part_key, rel_path, part_values)
            writer.write_table(sub_table)
            self._update_part_stats(part_key, sub_table)

    def _get_or_create_writer(
        self,
        part_key: str,
        rel_path: str,
        part_values: dict[str, Any],
    ) -> pq.ParquetWriter:
        if part_key in self._writers:
            return self._writers[part_key]

        full_part_path = self.staging_dir / rel_path
        full_part_path.parent.mkdir(parents=True, exist_ok=True)

        compression_val = (
            None if self.compression == CompressionType.UNCOMPRESSED else self.compression.value
        )

        writer = pq.ParquetWriter(
            str(full_part_path),
            schema=self.arrow_schema,
            compression=compression_val,
            use_dictionary=True,
            write_statistics=True,
        )

        self._writers[part_key] = writer
        self._partition_counts[part_key] = 0
        self._partition_values[part_key] = part_values
        self._part_counter += 1
        return writer

    def _record_global_stats(self, table: pa.Table) -> None:
        """Record dataset-wide statistics using Arrow-native kernel operations."""
        num_rows = table.num_rows
        self._total_records += num_rows

        if "instrument_id" in table.column_names:
            for inst in pc.unique(table["instrument_id"]):
                val = inst.as_py()
                if val is not None:
                    self._all_instruments.add(int(val))

        if "venue_id" in table.column_names:
            for v in pc.unique(table["venue_id"]):
                val = v.as_py()
                if val is not None:
                    self._all_venues.add(int(val))

        if "feed_id" in table.column_names:
            for f in pc.unique(table["feed_id"]):
                val = f.as_py()
                if val is not None:
                    self._all_feeds.add(int(val))

        if "source_timestamp_ns" in table.column_names:
            ts_col = table["source_timestamp_ns"]
            min_ts = pc.min(ts_col).as_py()
            max_ts = pc.max(ts_col).as_py()
            if min_ts is not None:
                if self._global_min_ts is None or min_ts < self._global_min_ts:
                    self._global_min_ts = int(min_ts)
                dt_str = datetime.fromtimestamp(min_ts / 1e9, tz=UTC).strftime("%Y-%m-%d")
                self._all_dates.add(dt_str)
            if max_ts is not None:
                if self._global_max_ts is None or max_ts > self._global_max_ts:
                    self._global_max_ts = int(max_ts)
                dt_str = datetime.fromtimestamp(max_ts / 1e9, tz=UTC).strftime("%Y-%m-%d")
                self._all_dates.add(dt_str)

    def _update_part_stats(self, part_key: str, table: pa.Table) -> None:
        """Update partition-level statistics using Arrow-native compute kernels."""
        self._partition_counts[part_key] = self._partition_counts.get(part_key, 0) + table.num_rows

        if "source_timestamp_ns" in table.column_names:
            ts_col = table["source_timestamp_ns"]
            min_ts = pc.min(ts_col).as_py()
            max_ts = pc.max(ts_col).as_py()
            if min_ts is not None:
                curr_min = self._min_timestamps.get(part_key)
                self._min_timestamps[part_key] = (
                    min_ts if curr_min is None else min(curr_min, min_ts)
                )
            if max_ts is not None:
                curr_max = self._max_timestamps.get(part_key)
                self._max_timestamps[part_key] = (
                    max_ts if curr_max is None else max(curr_max, max_ts)
                )

        if "sequence_num" in table.column_names:
            seq_col = table["sequence_num"]
            min_seq = pc.min(seq_col).as_py()
            max_seq = pc.max(seq_col).as_py()
            if min_seq is not None:
                curr_min = self._min_sequences.get(part_key)
                self._min_sequences[part_key] = (
                    min_seq if curr_min is None else min(curr_min, min_seq)
                )
            if max_seq is not None:
                curr_max = self._max_sequences.get(part_key)
                self._max_sequences[part_key] = (
                    max_seq if curr_max is None else max(curr_max, max_seq)
                )

    def close(self) -> DatasetManifest:
        """Finalize Parquet files, construct manifest, and atomically publish dataset.

        Publication semantics:
        - If dataset does not exist: atomically renames staging to target on the same filesystem.
        - If dataset exists and overwrite=True: executes a 3-phase transactional swap:
          1. Atomically renames existing target to a temporary backup directory.
          2. Atomically renames staging to target.
          3. If rename succeeds, purges backup. If rename fails, rolls back backup to target,
             preserving the original valid dataset intact.
        - Readers with open file descriptors continue uninterrupted across directory moves.
        """
        if not self._is_open:
            raise DatasetIntegrityError("DatasetWriter is not open.")
        try:
            return self._close_internal()
        except Exception:
            self.abort()
            raise

    def _close_internal(self) -> DatasetManifest:
        # Close all active writers
        for writer in self._writers.values():
            writer.close()
        self._writers.clear()

        # Handle empty dataset case
        if self._total_records == 0:
            rel_path = "part-00000.parquet"
            full_part_path = self.staging_dir / rel_path
            empty_table = self.arrow_schema.empty_table()
            pq.write_table(empty_table, str(full_part_path), compression=None)
            self._partition_counts["default"] = 0
            self._partition_values["default"] = {}

        # Compute checksums and build partition descriptors
        partition_descriptors: list[PartitionFile] = []
        total_bytes = 0

        # Scan all .parquet files inside staging_dir
        for pfile in sorted(self.staging_dir.rglob("*.parquet")):
            rel_path = str(pfile.relative_to(self.staging_dir))
            size = pfile.stat().st_size
            sha = compute_file_sha256(pfile)
            total_bytes += size

            # Locate key matching this file
            part_key = str(pfile.parent.relative_to(self.staging_dir))
            if part_key == ".":
                part_key = "default"

            row_count = self._partition_counts.get(part_key, 0)
            part_vals = self._partition_values.get(part_key, {})

            partition_descriptors.append(
                PartitionFile(
                    relative_path=rel_path,
                    record_count=row_count,
                    byte_size=size,
                    sha256_checksum=sha,
                    min_timestamp_ns=self._min_timestamps.get(part_key),
                    max_timestamp_ns=self._max_timestamps.get(part_key),
                    min_sequence=self._min_sequences.get(part_key),
                    max_sequence=self._max_sequences.get(part_key),
                    partition_values=part_vals,
                )
            )

        now_utc = datetime.now(UTC).isoformat()
        manifest = DatasetManifest(
            manifest_version="1.0.0",
            dataset_id=self.dataset_id,
            name=self.name,
            kind=self.kind.value,
            domain=self.domain.value,
            schema_name=self.schema_name,
            schema_version=str(self.schema_version),
            created_at_utc=now_utc,
            time_range={
                "start_timestamp_ns": self._global_min_ts or 0,
                "end_timestamp_ns": self._global_max_ts or 0,
            },
            record_count=self._total_records,
            partition_count=len(partition_descriptors),
            total_byte_size=total_bytes,
            instruments=sorted(self._all_instruments),
            venues=sorted(self._all_venues),
            feeds=sorted(self._all_feeds),
            dates=sorted(self._all_dates),
            partition_keys=self.partition_by,
            partitions=partition_descriptors,
            provenance=self.provenance.to_dict(),
            compression=self.compression.value,
            validation_status=ValidationStatus.VALID.value,
            validation_rules_version="1.0.0",
            is_complete=True,
        )

        # Write manifest to staging directory
        manifest.to_file(self.staging_dir / "manifest.json")

        # Atomic publication transaction
        if self.target_dir.exists():
            if not self.overwrite:
                self.abort()
                raise DatasetExistsError(
                    f"Dataset directory '{self.target_dir}' already exists and overwrite=False."
                )

            backup_id = f".backup_{self.dataset_id}_{uuid.uuid4().hex[:8]}"
            backup_dir = self.root_dir / backup_id

            # Phase 1: Atomically swap current target to backup
            try:
                os.replace(self.target_dir, backup_dir)
            except Exception as e:
                self.abort()
                raise DatasetIntegrityError(
                    f"Failed to move active dataset to backup before replacement: {e}"
                ) from e

            # Phase 2: Atomically move staging to target
            try:
                os.replace(self.staging_dir, self.target_dir)
            except Exception as e:
                # Rollback: restore backup to target
                rollback_succeeded = False
                try:
                    os.replace(backup_dir, self.target_dir)
                    rollback_succeeded = True
                except Exception:
                    pass
                self.abort()
                if rollback_succeeded:
                    raise DatasetIntegrityError(
                        f"Failed to publish dataset replacement; original dataset restored: {e}"
                    ) from e
                raise DatasetIntegrityError(
                    f"Failed to publish dataset replacement AND rollback failed: {e}. "
                    f"Original dataset preserved in backup at '{backup_dir}'"
                ) from e

            # Phase 3: Purge backup now that replacement is verified in place
            shutil.rmtree(backup_dir, ignore_errors=True)
        else:
            try:
                os.replace(self.staging_dir, self.target_dir)
            except Exception as e:
                self.abort()
                raise DatasetIntegrityError(f"Failed to publish dataset atomically: {e}") from e

        self._release_lock()
        self._is_open = False
        return manifest

    def abort(self) -> None:
        """Abort writing, safely remove staging artifacts, and release dataset write lock."""
        for writer in self._writers.values():
            try:
                writer.close()
            except Exception:
                pass
        self._writers.clear()

        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir, ignore_errors=True)

        self._release_lock()
        self._is_open = False
