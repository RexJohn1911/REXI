"""Streaming bounded reader and iterator for partitioned Arrow/Parquet research datasets."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from research.datasets.exceptions import (
    DatasetNotFoundError,
    IncompleteDatasetError,
    InvalidDatasetNameError,
)
from research.datasets.manifest import DatasetManifest, PartitionFile, resolve_partition_path
from research.datasets.schema import SchemaRegistry, SchemaVersion, get_schema_registry
from research.datasets.writer import SAFE_ID_REGEX, DatasetLock


class DatasetReader:
    """Bounded, streaming reader for partitioned Apache Parquet research datasets."""

    def __init__(
        self,
        dataset_id: str,
        root_dir: Path | str = "data/processed",
        registry: SchemaRegistry | None = None,
    ) -> None:
        self._validate_id(dataset_id)
        self.dataset_id = dataset_id
        self.root_dir = Path(root_dir).resolve()
        self.dataset_dir = self.root_dir / self.dataset_id
        self.registry = registry or get_schema_registry()

        if not self.dataset_dir.is_dir():
            if DatasetLock.is_active(self.root_dir, self.dataset_id):
                raise DatasetNotFoundError(
                    f"Dataset '{self.dataset_id}' not found at '{self.dataset_dir}' "
                    "(dataset is currently undergoing an active "
                    "publication/replacement transaction)."
                )
            raise DatasetNotFoundError(
                f"Dataset '{self.dataset_id}' not found at '{self.dataset_dir}'"
            )

        manifest_path = self.dataset_dir / "manifest.json"
        if not manifest_path.is_file():
            raise IncompleteDatasetError(
                f"Dataset '{self.dataset_id}' missing manifest.json at '{manifest_path}'"
            )

        self.manifest = DatasetManifest.from_file(manifest_path)
        self.schema = self.registry.get(
            self.manifest.schema_name,
            SchemaVersion.from_str(self.manifest.schema_version),
        )

    @staticmethod
    def _validate_id(ident: str) -> None:
        if ".." in ident or "/" in ident or "\\" in ident:
            raise InvalidDatasetNameError(f"Path traversal detected in dataset ID: '{ident}'")
        if not ident or not SAFE_ID_REGEX.match(ident):
            raise InvalidDatasetNameError(
                f"Invalid dataset ID: '{ident}'. "
                "Must contain only alphanumeric, underscore, or hyphen."
            )

    @property
    def partitions(self) -> list[PartitionFile]:
        """List all partition metadata records."""
        return self.manifest.partitions

    @property
    def record_count(self) -> int:
        """Total number of records across all partitions."""
        return self.manifest.record_count

    def verify_integrity(self) -> tuple[bool, list[str]]:
        """Verify the cryptographic SHA-256 and byte sizes of all partitions."""
        return self.manifest.verify_integrity(self.dataset_dir)

    def _matches_filter(
        self,
        partition: PartitionFile,
        filter_partitions: dict[str, Any] | None,
    ) -> bool:
        if not filter_partitions:
            return True
        for key, val in filter_partitions.items():
            if key in partition.partition_values:
                part_val = partition.partition_values[key]
                if str(part_val) != str(val):
                    return False
        return True

    def get_selected_partitions(
        self, filter_partitions: dict[str, Any] | None = None
    ) -> list[PartitionFile]:
        """Return partitions matching optional partition key filters."""
        return [p for p in self.partitions if self._matches_filter(p, filter_partitions)]

    def read_batch_iter(
        self,
        batch_size: int = 10000,
        columns: list[str] | None = None,
        filter_partitions: dict[str, Any] | None = None,
    ) -> Iterator[pa.RecordBatch]:
        """Stream record batches from disk in bounded memory chunks.

        Iterates sequentially across matched partition files without loading the full
        dataset into memory. Partition paths are strictly validated against root directory
        containment before opening.
        """
        selected_parts = self.get_selected_partitions(filter_partitions)

        for part in selected_parts:
            part_path = resolve_partition_path(self.dataset_dir, part.relative_path)
            if not part_path.is_file():
                continue

            parquet_file = pq.ParquetFile(str(part_path))
            for batch in parquet_file.iter_batches(batch_size=batch_size, columns=columns):
                if batch.num_rows > 0:
                    yield batch

    def read_table(
        self,
        columns: list[str] | None = None,
        filter_partitions: dict[str, Any] | None = None,
    ) -> pa.Table:
        """Read all matching partitions into a single in-memory Arrow Table.

        Partition paths are strictly validated against root directory containment before opening.
        """
        selected_parts = self.get_selected_partitions(filter_partitions)
        if not selected_parts:
            return self.schema.empty_table()

        tables: list[pa.Table] = []
        for part in selected_parts:
            part_path = resolve_partition_path(self.dataset_dir, part.relative_path)
            if part_path.is_file():
                t = pq.ParquetFile(str(part_path)).read(columns=columns)
                tables.append(t)

        if not tables:
            return self.schema.empty_table()
        if len(tables) == 1:
            return tables[0]
        return pa.concat_tables(tables)
