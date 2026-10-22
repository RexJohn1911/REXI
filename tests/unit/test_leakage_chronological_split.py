"""Unit tests for strict chronological splitting and walk-forward generation."""

import pytest

from research.leakage.exceptions import (
    EmptyPartitionError,
    InvalidSplitConfigError,
    TemporalOrderError,
)
from research.leakage.split import (
    ChronologicalSplitter,
    find_safe_boundary_index,
    validate_monotonic_timestamps,
)
from research.leakage.types import PartitionRole, SplitType


def test_monotonic_timestamp_validation_success() -> None:
    """Monotonic timestamps pass validation."""
    ts = [100, 200, 200, 300, 400]
    validate_monotonic_timestamps(ts)


def test_monotonic_timestamp_validation_failure() -> None:
    """Non-monotonic or shuffled timestamps trigger TemporalOrderError."""
    shuffled = [100, 200, 150, 300]
    with pytest.raises(TemporalOrderError, match="Temporal order violation at index 2"):
        validate_monotonic_timestamps(shuffled)


def test_empty_timestamp_validation_failure() -> None:
    """Empty timestamp sequence raises EmptyPartitionError."""
    with pytest.raises(EmptyPartitionError, match="cannot be empty"):
        validate_monotonic_timestamps([])


def test_chronological_holdout_three_way_split() -> None:
    """Train -> Val -> Test split respects strict temporal ordering and zero shuffle."""
    # 100 samples from t=1000 to t=1099
    timestamps = [1000 + i * 10 for i in range(100)]
    splitter = ChronologicalSplitter()

    split_def = splitter.split_holdout(
        timestamps,
        train_ratio=0.7,
        val_ratio=0.15,
        test_ratio=0.15,
    )

    train = split_def.train_partition
    val = split_def.val_partition
    test = split_def.test_partition

    assert val is not None
    assert train.role == PartitionRole.TRAIN
    assert val.role == PartitionRole.VALIDATION
    assert test.role == PartitionRole.TEST

    # Record counts
    assert train.record_count == 70
    assert val.record_count == 15
    assert test.record_count == 15
    assert train.record_count + val.record_count + test.record_count == 100

    # Strict non-overlapping indices
    assert train.record_indices is not None
    assert val.record_indices is not None
    assert test.record_indices is not None
    assert set(train.record_indices).isdisjoint(set(val.record_indices))
    assert set(val.record_indices).isdisjoint(set(test.record_indices))
    assert set(train.record_indices).isdisjoint(set(test.record_indices))

    # Strict temporal ordering: train_end <= val_start and val_end <= test_start
    assert train.time_boundary.end_timestamp_ns <= val.time_boundary.start_timestamp_ns
    assert val.time_boundary.end_timestamp_ns <= test.time_boundary.start_timestamp_ns


def test_chronological_holdout_two_way_split() -> None:
    """Train -> Test split when val_ratio is 0.0."""
    timestamps = [1000 + i * 10 for i in range(100)]
    splitter = ChronologicalSplitter()

    split_def = splitter.split_holdout(
        timestamps,
        train_ratio=0.8,
        val_ratio=0.0,
        test_ratio=0.2,
    )

    assert split_def.val_partition is None
    assert split_def.train_partition.record_count == 80
    assert split_def.test_partition.record_count == 20
    assert (
        split_def.train_partition.time_boundary.end_timestamp_ns
        <= split_def.test_partition.time_boundary.start_timestamp_ns
    )


def test_invalid_split_ratios_rejected() -> None:
    """Invalid ratio sums or negative values are rejected."""
    timestamps = [1000 + i for i in range(50)]
    splitter = ChronologicalSplitter()

    # Ratios sum to 0.9 != 1.0
    with pytest.raises(InvalidSplitConfigError, match="must sum to 1.0"):
        splitter.split_holdout(timestamps, train_ratio=0.5, val_ratio=0.2, test_ratio=0.2)

    # Negative ratio
    with pytest.raises(InvalidSplitConfigError, match="Invalid split ratios"):
        splitter.split_holdout(timestamps, train_ratio=0.8, val_ratio=-0.1, test_ratio=0.3)


def test_duplicate_decision_timestamps_kept_together_at_boundary() -> None:
    """Records with identical timestamps at a split boundary are not cut in half."""
    # Create 100 records, where indices 65 to 75 have identical timestamp 5000
    timestamps = [i * 10 for i in range(65)] + [5000] * 10 + [5000 + i * 10 for i in range(1, 26)]
    assert len(timestamps) == 100

    # Nominal 70% cut would land at index 70, right in the middle of the 5000 burst
    safe_cut = find_safe_boundary_index(timestamps, target_idx=70, total_len=100)
    # The duplicate run is [65, 75). Safe boundary will pick either 65 or 75
    assert safe_cut in (65, 75)
    # The elements right before and right after safe_cut must have distinct timestamps!
    assert timestamps[safe_cut - 1] != timestamps[safe_cut]


def test_all_identical_timestamps_rejected() -> None:
    """When all records have the exact same timestamp, splitting is safely rejected."""
    timestamps = [12345] * 50
    with pytest.raises(InvalidSplitConfigError, match="all 50 records share identical timestamp"):
        find_safe_boundary_index(timestamps, target_idx=25, total_len=50)


def test_walk_forward_expanding_and_rolling() -> None:
    """Walk-forward splits generate strictly advancing time windows."""
    timestamps = [1000 + i * 10 for i in range(100)]
    splitter = ChronologicalSplitter()

    # Rolling walk-forward
    rolling_splits = splitter.split_walk_forward(
        timestamps,
        n_splits=3,
        train_size=30,
        test_size=10,
        expanding=False,
    )
    assert len(rolling_splits) == 3
    for fold in rolling_splits:
        assert fold.test_partition.record_count == 10
        assert fold.train_partition.record_count <= 30
        assert fold.metadata["split_type"] == SplitType.WALK_FORWARD_ROLLING.value
        # Train strictly before test
        assert (
            fold.train_partition.time_boundary.end_timestamp_ns
            <= fold.test_partition.time_boundary.start_timestamp_ns
        )

    # Expanding walk-forward
    expanding_splits = splitter.split_walk_forward(
        timestamps,
        n_splits=3,
        train_size=30,
        test_size=10,
        expanding=True,
    )
    assert len(expanding_splits) == 3
    # Expanding: train partition size grows with each fold
    assert (
        expanding_splits[0].train_partition.record_count
        < expanding_splits[1].train_partition.record_count
    )
    assert (
        expanding_splits[1].train_partition.record_count
        < expanding_splits[2].train_partition.record_count
    )


def test_walk_forward_insufficient_data_raises() -> None:
    """Insufficient data for requested walk forward parameters raises EmptyPartitionError."""
    timestamps = [1000 + i * 10 for i in range(20)]
    splitter = ChronologicalSplitter()

    # Requires 30 + 3*10 = 60, but only 20 provided
    with pytest.raises(EmptyPartitionError, match="insufficient"):
        splitter.split_walk_forward(
            timestamps,
            n_splits=3,
            train_size=30,
            test_size=10,
        )


def test_duplicate_timestamps_cannot_cross_walk_forward_boundaries() -> None:
    """Equal decision timestamps never cross partition boundaries in walk-forward splits."""
    # 60 records total. Place runs of identical timestamps right around nominal cut points:
    # Say nominal cut occurs at index 30, and indices 28..33 all share timestamp 1500.
    timestamps = (
        [1000 + i * 10 for i in range(28)]  # 0..27 (times 1000..1270)
        + [1500] * 6  # 28..33 (all time 1500)
        + [2000 + i * 10 for i in range(26)]  # 34..59 (times 2000..2250)
    )
    assert len(timestamps) == 60

    splitter = ChronologicalSplitter()
    # 2 splits with train_size=30, test_size=15
    splits = splitter.split_walk_forward(
        timestamps,
        n_splits=2,
        train_size=30,
        test_size=15,
        expanding=False,
    )

    for split in splits:
        train_idx = split.train_partition.record_indices
        test_idx = split.test_partition.record_indices
        assert train_idx is not None
        assert test_idx is not None

        train_ts = [timestamps[i] for i in train_idx]
        test_ts = [timestamps[i] for i in test_idx]

        # Equal timestamps never cross partition boundaries
        assert max(train_ts) < min(test_ts)
        assert set(train_ts).isdisjoint(set(test_ts))
