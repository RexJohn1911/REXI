"""Unit tests for label information interval purging, embargo rules, and Purged K-Fold CV."""

import pytest

from research.leakage.detector import LookaheadDetector
from research.leakage.exceptions import EmptyPartitionError
from research.leakage.split import ChronologicalSplitter
from research.leakage.types import (
    LabelInformationInterval,
    PurgeEmbargoConfig,
    SplitPartition,
    TimeInterval,
)


def test_label_horizon_purging_removes_overlapping_samples() -> None:
    """Samples whose label horizons touch the test partition are purged."""
    # Timestamps every 10 ns: 0, 10, 20, ..., 990 (100 samples)
    timestamps = [i * 10 for i in range(100)]
    # Fixed forward label horizon of 50 ns (e.g., 5-tick future return)
    # Train is 70% (indices 0..69, times 0..690)
    # Test is 30% (indices 70..99, times 700..990)
    splitter = ChronologicalSplitter(
        purge_config=PurgeEmbargoConfig(purge_horizon_ns=50, embargo_ns=0)
    )

    split_def = splitter.split_holdout(
        timestamps,
        train_ratio=0.7,
        val_ratio=0.0,
        test_ratio=0.3,
        label_horizons=50,
    )

    # Test partition begins at 700 ns (index 70)
    # Samples at index 65 (t=650, horizon=50 -> end=700): touches boundary point 700!
    # Samples 65, 66, 67, 68, 69 all have end_time >= 700 -> must be purged!
    # Sample 64 (t=640, end=690 < 700) -> kept!
    train_indices = split_def.train_partition.record_indices
    assert train_indices is not None
    assert 64 in train_indices
    assert 65 not in train_indices
    assert 69 not in train_indices
    assert split_def.purged_record_count == 5
    assert len(train_indices) == 70 - 5  # 65 kept


def test_exact_boundary_purging_touch() -> None:
    """Exact boundary touch: label ending exactly at test_start is purged."""
    lbl = LabelInformationInterval(observation_timestamp_ns=450, label_end_timestamp_ns=500)
    test_partition = TimeInterval(500, 1000)
    # [450, 500] touches [500, 1000) at 500
    assert lbl.touches_partition(test_partition)

    # Label ending at 499 does not touch [500, 1000)
    lbl_clean = LabelInformationInterval(observation_timestamp_ns=450, label_end_timestamp_ns=499)
    assert not lbl_clean.touches_partition(test_partition)


def test_embargo_applies_strictly_to_post_test_training_data() -> None:
    """Embargo removes samples in [test_end, test_end + embargo_ns) only post-test."""
    # 5-fold Purged K-Fold on 100 samples (20 samples per block)
    timestamps = [i * 10 for i in range(100)]
    # Fold 1 has test block 1 (indices 20..39, times 200..390).
    # Pre-test data: block 0 (indices 0..19, times 0..190).
    # Post-test data: blocks 2, 3, 4 (indices 40..99, times 400..990).
    # Embargo of 30 ns: interval [400, 430).
    # Samples at index 40 (t=400), 41 (t=410), 42 (t=420) are inside [400, 430) -> embargoed!
    # Sample at index 43 (t=430) is >= 430 -> kept!
    # Pre-test data (indices 0..19) must NOT be embargoed!
    splitter = ChronologicalSplitter(
        purge_config=PurgeEmbargoConfig(purge_horizon_ns=0, embargo_ns=30)
    )

    kfold_splits = splitter.split_purged_k_fold(timestamps, n_splits=5)
    fold_1 = kfold_splits[1]

    train_indices = fold_1.train_partition.record_indices
    assert train_indices is not None

    # Pre-test records (0..19) are all kept
    for i in range(20):
        assert i in train_indices

    # Post-test embargoed records (40, 41, 42) are removed
    assert 40 not in train_indices
    assert 41 not in train_indices
    assert 42 not in train_indices

    # Post-test kept record (43 onwards)
    assert 43 in train_indices
    assert fold_1.embargoed_record_count == 3


def test_purged_k_fold_all_folds_valid_and_disjoint() -> None:
    """Purged K-Fold produces valid disjoint train/test splits across all folds."""
    timestamps = [i * 10 for i in range(100)]
    splitter = ChronologicalSplitter(
        purge_config=PurgeEmbargoConfig(purge_horizon_ns=20, embargo_ns=20)
    )

    kfold_splits = splitter.split_purged_k_fold(timestamps, n_splits=5)
    assert len(kfold_splits) == 5

    for fold_idx, fold in enumerate(kfold_splits):
        assert fold.split_index == fold_idx
        train_idx = fold.train_partition.record_indices
        test_idx = fold.test_partition.record_indices
        assert train_idx is not None
        assert test_idx is not None

        # Train and test are completely disjoint
        assert set(train_idx).isdisjoint(set(test_idx))

        # Test block has 20 records
        assert len(test_idx) == 20

        # Purging and embargo removed appropriate samples
        assert fold.train_partition.record_count == len(train_idx)


def test_combinatorial_purged_cross_validation_combinations() -> None:
    """CPCV generates all (N choose k) combinations with full purging and embargo."""
    timestamps = [i * 10 for i in range(100)]
    splitter = ChronologicalSplitter(
        purge_config=PurgeEmbargoConfig(purge_horizon_ns=10, embargo_ns=10)
    )

    # 5 choose 2 = 10 combinations
    cpcv_splits = splitter.split_combinatorial_purged(
        timestamps,
        n_splits=5,
        n_test_splits=2,
    )
    assert len(cpcv_splits) == 10

    for split in cpcv_splits:
        train_idx = split.train_partition.record_indices
        test_idx = split.test_partition.record_indices
        assert train_idx is not None
        assert test_idx is not None
        assert set(train_idx).isdisjoint(set(test_idx))
        # Each test combination has 2 blocks of 20 = 40 records
        assert len(test_idx) == 40
        assert split.train_partition.record_count > 0


def test_extreme_purge_exhausting_partition_raises_error() -> None:
    """When purge horizon exceeds entire partition duration, EmptyPartitionError is raised."""
    timestamps = [i * 10 for i in range(20)]
    # Purge horizon of 1000 ns exceeds the entire 200 ns dataset
    splitter = ChronologicalSplitter(
        purge_config=PurgeEmbargoConfig(purge_horizon_ns=1000, embargo_ns=0)
    )
    with pytest.raises(EmptyPartitionError, match="exhausted after label horizon purging"):
        splitter.split_holdout(timestamps, train_ratio=0.5, val_ratio=0.0, test_ratio=0.5)


def test_cpcv_non_contiguous_blocks_and_full_audit_compliance() -> None:
    """Verify CPCV with non-contiguous test blocks, pre/post test samples, and embargo boundaries.

    Ensures every generated fold excludes all prohibited samples and passes LookaheadDetector
    split compliance audit without false violations from intermediate training blocks.
    """
    timestamps = [i * 10 for i in range(100)]  # 5 blocks of 20 samples (times 0..990)
    purge_config = PurgeEmbargoConfig(purge_horizon_ns=15, embargo_ns=20)
    splitter = ChronologicalSplitter(purge_config=purge_config)

    cpcv_splits = splitter.split_combinatorial_purged(
        timestamps,
        n_splits=5,
        n_test_splits=2,
        label_horizons=15,
    )
    assert len(cpcv_splits) == 10

    labels = [LabelInformationInterval(t, t + 15) for t in timestamps]

    # Every single fold must pass the LookaheadDetector audit
    for split in cpcv_splits:
        report = LookaheadDetector.audit_split_compliance(
            split,
            timestamps,
            labels,
            purge_config,
        )
        assert report.is_valid, f"Fold {split.split_index} failed audit: {report.violations}"
        assert report.violation_count == 0

    # Specifically test non-contiguous test block combinations: e.g. [0, 2]
    fold_0_2 = next(s for s in cpcv_splits if s.metadata["test_block_indices"] == [0, 2])
    train_indices = set(fold_0_2.train_partition.record_indices or ())
    test_indices = set(fold_0_2.test_partition.record_indices or ())

    # Test blocks are 0 (indices 0..19, times 0..190) and 2 (indices 40..59, times 400..590)
    for i in range(0, 20):
        assert i in test_indices
    for i in range(40, 60):
        assert i in test_indices

    # Intermediate Block 1 (indices 20..39, times 200..390):
    # - Block 0 ends at 190. With embargo_ns=20, embargo window is [191, 211).
    #   Samples at index 20 (t=200) and index 21 (t=210) must be embargoed!
    assert 20 not in train_indices
    assert 21 not in train_indices
    #   Sample at index 22 (t=220) is >= 211 -> kept!
    assert 22 in train_indices

    # - Block 2 begins at 400. With purge_horizon_ns=15:
    #   Sample at index 38 (t=380, label_end=395 < 400) -> kept!
    #   Sample at index 39 (t=390, label_end=405 >= 400) -> touches Block 2 -> purged!
    assert 38 in train_indices
    assert 39 not in train_indices

    # Now verify that injecting an unpurged overlapping sample into Block 1 is detected
    corrupted_indices = tuple(sorted((*train_indices, 39)))
    corrupted_part = SplitPartition(
        role=fold_0_2.train_partition.role,
        partition_index=fold_0_2.train_partition.partition_index,
        time_boundary=fold_0_2.train_partition.time_boundary,
        record_count=len(corrupted_indices),
        record_indices=corrupted_indices,
    )
    corrupted_split = fold_0_2.__class__(
        split_index=fold_0_2.split_index,
        train_partition=corrupted_part,
        test_partition=fold_0_2.test_partition,
        metadata=fold_0_2.metadata,
    )
    corrupted_report = LookaheadDetector.audit_split_compliance(
        corrupted_split,
        timestamps,
        labels,
        purge_config,
    )
    assert not corrupted_report.is_valid
    assert any("touches test partition" in v for v in corrupted_report.violations)
