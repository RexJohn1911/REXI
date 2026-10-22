"""Phase 08 Research Data Lake integration for reproducible chronological splitting."""

from bisect import bisect_left
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pyarrow as pa

from research.datasets.manifest import compute_file_sha256
from research.datasets.reader import DatasetReader
from research.leakage.exceptions import EmptyPartitionError, InvalidSplitConfigError
from research.leakage.split import ChronologicalSplitter
from research.leakage.types import (
    PartitionRole,
    PurgeEmbargoConfig,
    SplitManifest,
    SplitType,
    TimeInterval,
)


class DatasetSplitter:
    """Partitioner for Phase 08 Data Lake datasets producing verifiable SplitManifests."""

    def __init__(
        self,
        reader: DatasetReader,
        timestamp_column: str = "receive_timestamp_ns",
        purge_config: PurgeEmbargoConfig | None = None,
    ) -> None:
        self.reader = reader
        self.timestamp_column = timestamp_column
        self.purge_config = purge_config or PurgeEmbargoConfig()
        self.splitter = ChronologicalSplitter(purge_config=self.purge_config)

    def extract_timestamps(self) -> list[int]:
        """Extract monotonic integer timestamps for the dataset.

        Projects only the timestamp column from Parquet partitions to minimize memory usage.
        """
        timestamps: list[int] = []
        for batch in self.reader.read_batch_iter(
            batch_size=65536,
            columns=[self.timestamp_column],
        ):
            col = batch[self.timestamp_column]
            timestamps.extend(col.to_pylist())

        if len(timestamps) == 0:
            raise EmptyPartitionError(
                f"Dataset '{self.reader.dataset_id}' contains zero records "
                f"in '{self.timestamp_column}'."
            )
        return timestamps

    def create_holdout_split(
        self,
        split_manifest_id: str,
        train_ratio: float = 0.7,
        val_ratio: float = 0.15,
        test_ratio: float = 0.15,
        label_horizons: list[int] | int | None = None,
    ) -> SplitManifest:
        """Create a verifiable holdout split manifest for the Phase 08 dataset."""
        timestamps = self.extract_timestamps()
        split_def = self.splitter.split_holdout(
            timestamps=timestamps,
            train_ratio=train_ratio,
            val_ratio=val_ratio,
            test_ratio=test_ratio,
            label_horizons=label_horizons,
        )

        manifest_path = self.reader.dataset_dir / "manifest.json"
        dataset_sha = compute_file_sha256(manifest_path) if manifest_path.is_file() else None

        min_ts = timestamps[0]
        max_ts = timestamps[-1]
        time_boundary = TimeInterval(min_ts, max_ts + 1)

        cfg: dict[str, Any] = {
            "train_ratio": train_ratio,
            "val_ratio": val_ratio,
            "test_ratio": test_ratio,
            "timestamp_column": self.timestamp_column,
            "purge_embargo": self.purge_config.to_dict(),
        }

        created_at = datetime.now(UTC).isoformat()
        manifest = SplitManifest(
            split_manifest_id=split_manifest_id,
            split_type=SplitType.CHRONOLOGICAL_HOLD_OUT,
            dataset_id=self.reader.dataset_id,
            dataset_manifest_sha256=dataset_sha,
            total_samples=len(timestamps),
            time_boundary=time_boundary,
            config=cfg,
            splits=[split_def],
            created_at_utc=created_at,
        )

        # Seal manifest with cryptographic checksum
        signed_manifest = SplitManifest(
            split_manifest_id=manifest.split_manifest_id,
            split_type=manifest.split_type,
            dataset_id=manifest.dataset_id,
            dataset_manifest_sha256=manifest.dataset_manifest_sha256,
            total_samples=manifest.total_samples,
            time_boundary=manifest.time_boundary,
            config=manifest.config,
            splits=manifest.splits,
            created_at_utc=manifest.created_at_utc,
            manifest_sha256=manifest.compute_sha256(),
        )
        return signed_manifest

    def create_purged_k_fold_split(
        self,
        split_manifest_id: str,
        n_splits: int = 5,
        label_horizons: list[int] | int | None = None,
    ) -> SplitManifest:
        """Create a verifiable Purged K-Fold split manifest for the Phase 08 dataset."""
        timestamps = self.extract_timestamps()
        splits = self.splitter.split_purged_k_fold(
            timestamps=timestamps,
            n_splits=n_splits,
            label_horizons=label_horizons,
        )

        manifest_path = self.reader.dataset_dir / "manifest.json"
        dataset_sha = compute_file_sha256(manifest_path) if manifest_path.is_file() else None

        min_ts = timestamps[0]
        max_ts = timestamps[-1]
        time_boundary = TimeInterval(min_ts, max_ts + 1)

        cfg: dict[str, Any] = {
            "n_splits": n_splits,
            "timestamp_column": self.timestamp_column,
            "purge_embargo": self.purge_config.to_dict(),
        }

        created_at = datetime.now(UTC).isoformat()
        manifest = SplitManifest(
            split_manifest_id=split_manifest_id,
            split_type=SplitType.PURGED_K_FOLD,
            dataset_id=self.reader.dataset_id,
            dataset_manifest_sha256=dataset_sha,
            total_samples=len(timestamps),
            time_boundary=time_boundary,
            config=cfg,
            splits=splits,
            created_at_utc=created_at,
        )

        signed_manifest = SplitManifest(
            split_manifest_id=manifest.split_manifest_id,
            split_type=manifest.split_type,
            dataset_id=manifest.dataset_id,
            dataset_manifest_sha256=manifest.dataset_manifest_sha256,
            total_samples=manifest.total_samples,
            time_boundary=manifest.time_boundary,
            config=manifest.config,
            splits=manifest.splits,
            created_at_utc=manifest.created_at_utc,
            manifest_sha256=manifest.compute_sha256(),
        )
        return signed_manifest


class SplitDatasetReader:
    """Reader interface allowing streaming or table reads of specific split partitions."""

    def __init__(
        self,
        reader: DatasetReader,
        manifest: SplitManifest,
    ) -> None:
        if manifest.dataset_id != reader.dataset_id:
            raise InvalidSplitConfigError(
                f"SplitManifest dataset_id '{manifest.dataset_id}' does not match "
                f"reader dataset_id '{reader.dataset_id}'"
            )
        self.reader = reader
        self.manifest = manifest

    def read_partition_batch_iter(
        self,
        split_index: int,
        role: PartitionRole,
        batch_size: int = 10000,
        columns: list[str] | None = None,
    ) -> Iterator[pa.RecordBatch]:
        """Stream record batches for a specific split partition across multi-file datasets.

        Translates recorded global row indices to partition-local batch offsets dynamically,
        guaranteeing bounded memory streaming without materializing the full dataset in RAM.
        """
        if split_index < 0 or split_index >= len(self.manifest.splits):
            raise InvalidSplitConfigError(
                f"Invalid split_index {split_index}. "
                f"Manifest contains {len(self.manifest.splits)} splits."
            )

        split_def = self.manifest.splits[split_index]
        if role == PartitionRole.TRAIN:
            partition = split_def.train_partition
        elif role == PartitionRole.TEST:
            partition = split_def.test_partition
        elif role == PartitionRole.VALIDATION:
            if split_def.val_partition is None:
                raise InvalidSplitConfigError(f"Split {split_index} has no validation partition.")
            partition = split_def.val_partition
        else:
            raise InvalidSplitConfigError(f"Unsupported partition role for batch read: {role}")

        indices = partition.record_indices
        if indices is None or len(indices) == 0:
            return

        current_global_offset = 0

        for batch in self.reader.read_batch_iter(batch_size=batch_size, columns=columns):
            batch_len = batch.num_rows
            if batch_len == 0:
                continue

            batch_end_offset = current_global_offset + batch_len

            # Find range of global indices falling inside this batch
            start_pos = bisect_left(indices, current_global_offset)
            end_pos = bisect_left(indices, batch_end_offset)

            if end_pos > start_pos:
                # Convert global indices to batch-local indices
                local_indices = [idx - current_global_offset for idx in indices[start_pos:end_pos]]
                pa_local_indices = pa.array(local_indices, type=pa.int64())
                sliced_batch = batch.take(pa_local_indices)
                yield sliced_batch

            current_global_offset = batch_end_offset

    def read_partition_table(
        self,
        split_index: int,
        role: PartitionRole,
        columns: list[str] | None = None,
    ) -> pa.Table:
        """Read all records belonging to a specified split partition into an Arrow Table."""
        batches = list(
            self.read_partition_batch_iter(
                split_index=split_index,
                role=role,
                columns=columns,
            )
        )
        if not batches:
            return self.reader.schema.empty_table()
        return pa.Table.from_batches(batches)
