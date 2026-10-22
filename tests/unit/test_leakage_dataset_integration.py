"""Unit tests for Phase 08 Data Lake integration with No-Leakage Framework."""

from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pytest

from research.datasets.generator import SyntheticMarketDataGenerator
from research.datasets.reader import DatasetReader
from research.datasets.types import DataDomain, DatasetKind
from research.datasets.writer import DatasetWriter
from research.leakage.dataset_split import DatasetSplitter, SplitDatasetReader
from research.leakage.types import PartitionRole, PurgeEmbargoConfig, SplitType


@pytest.fixture
def sample_dataset(tmp_path: Path) -> tuple[Path, str]:
    """Generate a clean Phase 08 dataset with synthetic trades for testing."""
    root_dir = tmp_path / "lake"
    dataset_id = "test_lake_trades_001"

    gen = SyntheticMarketDataGenerator(seed=42)
    # Generate 200 trade records
    trades_table = gen.generate_trades(count=200, instrument_id=1, venue_id=1)

    with DatasetWriter(
        dataset_id=dataset_id,
        name="Test Trades",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=root_dir,
    ) as writer:
        writer.write_batch(trades_table)

    return root_dir, dataset_id


def test_dataset_splitter_holdout_creation(sample_dataset: tuple[Path, str]) -> None:
    """DatasetSplitter reads Phase 08 dataset and generates verifiable SplitManifest."""
    root_dir, dataset_id = sample_dataset
    reader = DatasetReader(dataset_id=dataset_id, root_dir=root_dir)

    purge_config = PurgeEmbargoConfig(purge_horizon_ns=100_000, embargo_ns=50_000)
    splitter = DatasetSplitter(
        reader=reader,
        timestamp_column="receive_timestamp_ns",
        purge_config=purge_config,
    )

    manifest = splitter.create_holdout_split(
        split_manifest_id="split_manifest_001",
        train_ratio=0.7,
        val_ratio=0.15,
        test_ratio=0.15,
    )

    assert manifest.split_manifest_id == "split_manifest_001"
    assert manifest.split_type == SplitType.CHRONOLOGICAL_HOLD_OUT
    assert manifest.dataset_id == dataset_id
    assert manifest.dataset_manifest_sha256 is not None
    assert len(manifest.dataset_manifest_sha256) == 64
    assert manifest.total_samples == 200
    assert manifest.verify_integrity()

    # Verify split partitions
    split_def = manifest.splits[0]
    train_part = split_def.train_partition
    val_part = split_def.val_partition
    test_part = split_def.test_partition

    assert val_part is not None
    assert train_part.record_count > 0
    assert val_part.record_count > 0
    assert test_part.record_count > 0


def test_dataset_splitter_purged_k_fold(sample_dataset: tuple[Path, str]) -> None:
    """DatasetSplitter generates valid Purged K-Fold manifest."""
    root_dir, dataset_id = sample_dataset
    reader = DatasetReader(dataset_id=dataset_id, root_dir=root_dir)

    purge_config = PurgeEmbargoConfig(purge_horizon_ns=50_000, embargo_ns=20_000)
    splitter = DatasetSplitter(
        reader=reader,
        timestamp_column="receive_timestamp_ns",
        purge_config=purge_config,
    )

    manifest = splitter.create_purged_k_fold_split(
        split_manifest_id="kfold_manifest_001",
        n_splits=5,
    )

    assert manifest.split_type == SplitType.PURGED_K_FOLD
    assert len(manifest.splits) == 5
    assert manifest.verify_integrity()


def test_split_dataset_reader_projections(sample_dataset: tuple[Path, str]) -> None:
    """SplitDatasetReader reads exact partition records into an Arrow Table."""
    root_dir, dataset_id = sample_dataset
    reader = DatasetReader(dataset_id=dataset_id, root_dir=root_dir)

    splitter = DatasetSplitter(reader=reader)
    manifest = splitter.create_holdout_split(
        split_manifest_id="split_reader_test",
        train_ratio=0.8,
        val_ratio=0.0,
        test_ratio=0.2,
    )

    split_reader = SplitDatasetReader(reader=reader, manifest=manifest)

    # Read train table
    train_table = split_reader.read_partition_table(split_index=0, role=PartitionRole.TRAIN)
    # Read test table
    test_table = split_reader.read_partition_table(split_index=0, role=PartitionRole.TEST)

    assert train_table.num_rows == manifest.splits[0].train_partition.record_count
    assert test_table.num_rows == manifest.splits[0].test_partition.record_count

    # Max train timestamp < min test timestamp
    max_train_ts = pc.max(train_table["receive_timestamp_ns"]).as_py()
    min_test_ts = pc.min(test_table["receive_timestamp_ns"]).as_py()
    assert max_train_ts <= min_test_ts


def test_split_manifest_determinism(sample_dataset: tuple[Path, str]) -> None:
    """Identical dataset and configurations produce bit-for-bit identical partition boundaries."""
    root_dir, dataset_id = sample_dataset
    reader = DatasetReader(dataset_id=dataset_id, root_dir=root_dir)

    purge_config = PurgeEmbargoConfig(purge_horizon_ns=100_000, embargo_ns=50_000)
    splitter = DatasetSplitter(
        reader=reader,
        timestamp_column="receive_timestamp_ns",
        purge_config=purge_config,
    )

    m1 = splitter.create_holdout_split("det_split", 0.7, 0.15, 0.15)
    m2 = splitter.create_holdout_split("det_split", 0.7, 0.15, 0.15)

    # Partition counts and boundaries are strictly identical
    s1 = m1.splits[0]
    s2 = m2.splits[0]
    assert s1.train_partition.record_count == s2.train_partition.record_count
    assert s1.train_partition.time_boundary == s2.train_partition.time_boundary
    assert s1.train_partition.record_indices == s2.train_partition.record_indices
    assert s1.purged_record_count == s2.purged_record_count
    assert s1.embargoed_record_count == s2.embargoed_record_count


def test_split_dataset_reader_multi_file_multi_batch_row_mapping(tmp_path: Path) -> None:
    """Verify global row index resolution across multi-file partitioned datasets and small batches.

    Ensures that partition-local indices are strictly computed relative to current batch offsets
    and not confused with global indices, resolving the exact original records across files.
    """
    root_dir = tmp_path / "multi_part_lake"
    dataset_id = "test_multi_file_dataset"

    # Write a multi-file partitioned dataset with 3 distinct partition files
    gen = SyntheticMarketDataGenerator(seed=123)
    t1 = gen.generate_trades(
        count=100,
        instrument_id=10,
        venue_id=1,
        start_time_ns=1_700_000_000_000_000_000,
    )
    t2 = gen.generate_trades(
        count=100,
        instrument_id=20,
        venue_id=1,
        start_time_ns=1_700_000_000_100_000_000,
    )
    t3 = gen.generate_trades(
        count=100,
        instrument_id=30,
        venue_id=1,
        start_time_ns=1_700_000_000_200_000_000,
    )

    with DatasetWriter(
        dataset_id=dataset_id,
        name="Multi Part Trades",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        partition_by=["instrument_id"],
        root_dir=root_dir,
    ) as writer:
        writer.write_batch(t1)
        writer.write_batch(t2)
        writer.write_batch(t3)

    reader = DatasetReader(dataset_id=dataset_id, root_dir=root_dir)
    assert len(reader.partitions) == 3
    assert reader.record_count == 300

    # Combine source tables to get full ground-truth records by global index
    full_table = reader.read_table()
    assert full_table.num_rows == 300

    # Create holdout split: 60% train (180 rows, spanning file 0 and part of file 1),
    # 20% val (60 rows, spanning file 1 and part of file 2), 20% test (60 rows)
    splitter = DatasetSplitter(
        reader=reader,
        timestamp_column="receive_timestamp_ns",
        purge_config=PurgeEmbargoConfig(purge_horizon_ns=0, embargo_ns=0),
    )
    manifest = splitter.create_holdout_split(
        split_manifest_id="multi_file_split",
        train_ratio=0.6,
        val_ratio=0.2,
        test_ratio=0.2,
    )

    split_def = manifest.splits[0]
    train_indices = split_def.train_partition.record_indices
    val_indices = split_def.val_partition.record_indices if split_def.val_partition else None
    test_indices = split_def.test_partition.record_indices

    assert train_indices is not None
    assert val_indices is not None
    assert test_indices is not None

    assert len(train_indices) == 180
    assert len(val_indices) == 60
    assert len(test_indices) == 60

    split_reader = SplitDatasetReader(reader=reader, manifest=manifest)

    # Test reading via read_partition_table
    train_table = split_reader.read_partition_table(0, PartitionRole.TRAIN)
    assert train_table.num_rows == 180

    # Verify train_table rows match ground-truth records at train_indices exactly
    expected_train_seq = [full_table["trade_id"][i].as_py() for i in train_indices]
    actual_train_seq = train_table["trade_id"].to_pylist()
    assert actual_train_seq == expected_train_seq

    # Test streaming via read_partition_batch_iter with an odd prime batch size (17)
    # This forces batch boundaries to fall inside files and across file boundaries
    train_batches = list(
        split_reader.read_partition_batch_iter(
            0, PartitionRole.TRAIN, batch_size=17
        )
    )
    assert len(train_batches) > 1
    streamed_train_table = pa.Table.from_batches(train_batches)
    assert streamed_train_table.num_rows == 180
    assert streamed_train_table["trade_id"].to_pylist() == expected_train_seq

    # Verify validation partition across files
    expected_val_seq = [full_table["trade_id"][i].as_py() for i in val_indices]
    val_table = split_reader.read_partition_table(0, PartitionRole.VALIDATION)
    assert val_table["trade_id"].to_pylist() == expected_val_seq

    val_batches = list(
        split_reader.read_partition_batch_iter(
            0, PartitionRole.VALIDATION, batch_size=13
        )
    )
    streamed_val_table = pa.Table.from_batches(val_batches)
    assert streamed_val_table["trade_id"].to_pylist() == expected_val_seq

    # Verify test partition
    expected_test_seq = [full_table["trade_id"][i].as_py() for i in test_indices]
    test_table = split_reader.read_partition_table(0, PartitionRole.TEST)
    assert test_table["trade_id"].to_pylist() == expected_test_seq
