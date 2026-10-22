"""Strict chronological splitting, walk-forward generation, and Purged K-Fold validation."""

import itertools
import math
from bisect import bisect_left, bisect_right
from collections.abc import Sequence

from research.leakage.exceptions import (
    EmptyPartitionError,
    InvalidSplitConfigError,
    TemporalOrderError,
    TimestampSafetyError,
)
from research.leakage.types import (
    LabelInformationInterval,
    PartitionRole,
    PurgeEmbargoConfig,
    SplitDefinition,
    SplitPartition,
    SplitType,
    TimeInterval,
)


def validate_monotonic_timestamps(timestamps: Sequence[int]) -> None:
    """Verify that timestamp sequence is non-empty, strictly typed, and non-decreasing.

    Raises:
    - EmptyPartitionError: if timestamps sequence is empty.
    - TimestampSafetyError: if non-integer or invalid values are encountered.
    - TemporalOrderError: if sequence is not monotonically non-decreasing.
    """
    n = len(timestamps)
    if n == 0:
        raise EmptyPartitionError("Timestamp sequence cannot be empty.")

    prev = timestamps[0]
    if not isinstance(prev, int) or isinstance(prev, bool):
        raise TimestampSafetyError(
            f"Timestamp at index 0 must be integer, got {type(prev).__name__}"
        )

    for idx in range(1, n):
        curr = timestamps[idx]
        if not isinstance(curr, int) or isinstance(curr, bool):
            raise TimestampSafetyError(
                f"Timestamp at index {idx} must be integer, got {type(curr).__name__}"
            )
        if curr < prev:
            raise TemporalOrderError(
                f"Temporal order violation at index {idx}: timestamp {curr} < previous {prev}. "
                "Time-series data must be strictly non-decreasing."
            )
        prev = curr


def find_safe_boundary_index(
    timestamps: Sequence[int],
    target_idx: int,
    total_len: int,
    min_left_size: int = 1,
    min_right_size: int = 1,
) -> int:
    """Find a split boundary that keeps identical timestamps together in the same partition.

    If target_idx falls between identical timestamps (t[target_idx - 1] == t[target_idx]),
    it evaluates both boundaries (before the duplicate block or after the duplicate block)
    to keep ties strictly intact. If neither boundary leaves enough records for adjacent
    partitions, it rejects the configuration.
    """
    if target_idx <= 0 or target_idx >= total_len:
        return target_idx

    val_left = timestamps[target_idx - 1]
    val_right = timestamps[target_idx]

    if val_left != val_right:
        # Clean boundary: different timestamps
        return target_idx

    # Tie detected: find span of identical timestamps
    dup_val = val_left
    start_idx = bisect_left(timestamps, dup_val)
    end_idx = bisect_right(timestamps, dup_val)

    if start_idx == 0 and end_idx == total_len:
        raise InvalidSplitConfigError(
            f"Cannot split dataset where all {total_len} records share identical "
            f"timestamp {dup_val}."
        )

    # Candidate 1: Place duplicate run in left partition (cut at end_idx)
    cand_after = end_idx
    cand_after_valid = (cand_after >= min_left_size) and (
        (total_len - cand_after) >= min_right_size
    )

    # Candidate 2: Place duplicate run in right partition (cut at start_idx)
    cand_before = start_idx
    cand_before_valid = (cand_before >= min_left_size) and (
        (total_len - cand_before) >= min_right_size
    )

    # Pick candidate closest to target_idx
    if cand_after_valid and cand_before_valid:
        if abs(cand_after - target_idx) <= abs(target_idx - cand_before):
            return cand_after
        return cand_before
    elif cand_after_valid:
        return cand_after
    elif cand_before_valid:
        return cand_before

    raise InvalidSplitConfigError(
        f"Split boundary near index {target_idx} falls on duplicate timestamp {dup_val} "
        f"(spanning [{start_idx}, {end_idx})), and cannot be resolved without violating "
        f"partition constraints (min_left={min_left_size}, min_right={min_right_size})."
    )


def extract_label_intervals(
    timestamps: Sequence[int],
    label_horizons: Sequence[int] | int | None = None,
    default_horizon_ns: int = 0,
) -> list[LabelInformationInterval]:
    """Extract or generate LabelInformationInterval for each sample in timestamps."""
    n = len(timestamps)
    effective = label_horizons if label_horizons is not None else default_horizon_ns
    if isinstance(effective, int):
        if effective < 0:
            raise InvalidSplitConfigError(f"label_horizon cannot be negative: {effective}")
        return [LabelInformationInterval(t, t + effective) for t in timestamps]
    else:
        if len(effective) != n:
            raise InvalidSplitConfigError(
                f"label_horizons length ({len(effective)}) must match timestamps ({n})"
            )
        intervals: list[LabelInformationInterval] = []
        for t, h in zip(timestamps, effective, strict=True):
            if h < 0:
                raise InvalidSplitConfigError(f"Per-sample label horizon cannot be negative: {h}")
            intervals.append(LabelInformationInterval(t, t + h))
        return intervals


def purge_and_embargo_samples(
    candidate_indices: Sequence[int],
    timestamps: Sequence[int],
    label_intervals: list[LabelInformationInterval],
    eval_partition: TimeInterval,
    is_pre_eval: bool,
    purge_config: PurgeEmbargoConfig,
) -> tuple[tuple[int, ...], int, int]:
    """Filter candidate training sample indices by applying purging and embargo.

    Rules:
    - Pre-eval training data (is_pre_eval=True):
      Purge if label interval [t_obs, t_label_end] touches eval_partition [a, b).
      Embargo does NOT apply to pre-eval data.
    - Post-eval training data (is_pre_eval=False):
      Purging checks if label interval touches eval partition.
      Embargo applies: drop if t_obs in [eval_end, eval_end + embargo_ns).

    Returns:
    - kept_indices: tuple of retained sample indices
    - purged_count: number of samples removed due to label overlap
    - embargoed_count: number of samples removed due to post-eval embargo
    """
    kept: list[int] = []
    purged_count = 0
    embargoed_count = 0

    embargo_end_ns = eval_partition.end_timestamp_ns + purge_config.embargo_ns

    for idx in candidate_indices:
        t_obs = timestamps[idx]
        lbl = label_intervals[idx]

        # Check purging: does label information touch the evaluation partition?
        if lbl.touches_partition(eval_partition):
            purged_count += 1
            continue

        # Check embargo: applies strictly to post-eval training data
        if not is_pre_eval and purge_config.embargo_ns > 0:
            if eval_partition.end_timestamp_ns <= t_obs < embargo_end_ns:
                embargoed_count += 1
                continue

        kept.append(idx)

    return tuple(kept), purged_count, embargoed_count


class ChronologicalSplitter:
    """Strict chronological time-series partitioner enforcing zero random shuffling."""

    def __init__(
        self,
        purge_config: PurgeEmbargoConfig | None = None,
    ) -> None:
        self.purge_config = purge_config or PurgeEmbargoConfig()

    def split_holdout(
        self,
        timestamps: Sequence[int],
        train_ratio: float = 0.7,
        val_ratio: float = 0.15,
        test_ratio: float = 0.15,
        label_horizons: Sequence[int] | int | None = None,
    ) -> SplitDefinition:
        """Create a strict chronological Train -> [Validation] -> Test holdout partition.

        Timestamps are never randomly shuffled.
        Identical timestamps at split boundaries are kept intact in the same partition.
        Purging is applied to training samples whose labels touch validation or test intervals.
        """
        validate_monotonic_timestamps(timestamps)
        total_len = len(timestamps)

        if train_ratio <= 0.0 or test_ratio <= 0.0 or val_ratio < 0.0:
            raise InvalidSplitConfigError(
                f"Invalid split ratios: train={train_ratio}, val={val_ratio}, test={test_ratio}. "
                "train_ratio and test_ratio must be > 0, val_ratio >= 0."
            )

        ratio_sum = train_ratio + val_ratio + test_ratio
        if not math.isclose(ratio_sum, 1.0, abs_tol=1e-5):
            raise InvalidSplitConfigError(f"Split ratios must sum to 1.0 (got {ratio_sum:.6f})")

        label_intervals = extract_label_intervals(
            timestamps, label_horizons, default_horizon_ns=self.purge_config.purge_horizon_ns
        )

        has_val = val_ratio > 0.0
        # Calculate nominal cut points
        nominal_train_end = int(total_len * train_ratio)
        min_train = 1
        min_test = 1
        min_val = 1 if has_val else 0

        # Find safe cut between train and val/test
        train_end_idx = find_safe_boundary_index(
            timestamps,
            nominal_train_end,
            total_len,
            min_left_size=min_train,
            min_right_size=min_test + min_val,
        )

        if has_val:
            nominal_val_end = int(total_len * (train_ratio + val_ratio))
            val_end_idx = find_safe_boundary_index(
                timestamps,
                nominal_val_end,
                total_len,
                min_left_size=train_end_idx + min_val,
                min_right_size=min_test,
            )
        else:
            val_end_idx = train_end_idx

        # Define partitions
        train_indices_raw = list(range(0, train_end_idx))
        val_indices_raw = list(range(train_end_idx, val_end_idx)) if has_val else []
        test_indices_raw = list(range(val_end_idx, total_len))

        if len(train_indices_raw) == 0 or len(test_indices_raw) == 0:
            raise EmptyPartitionError("Resulting train or test partition is empty.")
        if has_val and len(val_indices_raw) == 0:
            raise EmptyPartitionError("Resulting validation partition is empty.")

        # Boundaries
        # For half-open boundaries:
        # train: [timestamps[0], timestamps[train_end_idx])
        # val: [timestamps[train_end_idx], timestamps[val_end_idx])
        # test: [timestamps[val_end_idx], timestamps[-1] + 1)
        train_interval = TimeInterval(timestamps[0], timestamps[train_end_idx])
        if has_val:
            val_interval = TimeInterval(timestamps[train_end_idx], timestamps[val_end_idx])
        else:
            val_interval = None
        test_interval = TimeInterval(timestamps[val_end_idx], timestamps[-1] + 1)

        # Apply purging to train against val and test
        purged_records = 0
        embargoed_records = 0

        # Purge train against val if val exists
        train_candidates = train_indices_raw
        if val_interval is not None:
            train_candidates_kept, purged_val, _ = purge_and_embargo_samples(
                train_candidates,
                timestamps,
                label_intervals,
                val_interval,
                is_pre_eval=True,
                purge_config=self.purge_config,
            )
            purged_records += purged_val
            train_candidates = list(train_candidates_kept)

        # Purge train against test
        train_kept, purged_test, _ = purge_and_embargo_samples(
            train_candidates,
            timestamps,
            label_intervals,
            test_interval,
            is_pre_eval=True,
            purge_config=self.purge_config,
        )
        purged_records += purged_test

        # Purge val against test if val exists
        if val_interval is not None:
            val_kept, purged_val_test, _ = purge_and_embargo_samples(
                val_indices_raw,
                timestamps,
                label_intervals,
                test_interval,
                is_pre_eval=True,
                purge_config=self.purge_config,
            )
            purged_records += purged_val_test
        else:
            val_kept = ()

        if len(train_kept) == 0:
            raise EmptyPartitionError(
                "Training partition was completely exhausted after label horizon purging."
            )

        train_part = SplitPartition(
            role=PartitionRole.TRAIN,
            partition_index=0,
            time_boundary=train_interval,
            record_count=len(train_kept),
            record_indices=train_kept,
        )

        test_part = SplitPartition(
            role=PartitionRole.TEST,
            partition_index=2 if has_val else 1,
            time_boundary=test_interval,
            record_count=len(test_indices_raw),
            record_indices=tuple(test_indices_raw),
        )

        val_part = None
        if val_interval is not None:
            val_part = SplitPartition(
                role=PartitionRole.VALIDATION,
                partition_index=1,
                time_boundary=val_interval,
                record_count=len(val_kept),
                record_indices=val_kept,
            )

        return SplitDefinition(
            split_index=0,
            train_partition=train_part,
            test_partition=test_part,
            val_partition=val_part,
            purged_record_count=purged_records,
            embargoed_record_count=embargoed_records,
            metadata={
                "split_type": SplitType.CHRONOLOGICAL_HOLD_OUT.value,
                "train_ratio": train_ratio,
                "val_ratio": val_ratio,
                "test_ratio": test_ratio,
                "test_intervals": [test_interval.to_dict()],
            },
        )

    def split_walk_forward(
        self,
        timestamps: Sequence[int],
        n_splits: int,
        train_size: int,
        test_size: int,
        expanding: bool = False,
        label_horizons: Sequence[int] | int | None = None,
    ) -> list[SplitDefinition]:
        """Generate rolling or expanding walk-forward chronological splits.

        In each fold:
        - Train window precedes test window.
        - Purging removes training samples whose label intervals touch the test window.
        """
        validate_monotonic_timestamps(timestamps)
        total_len = len(timestamps)

        if n_splits < 1:
            raise InvalidSplitConfigError(f"n_splits must be >= 1, got {n_splits}")
        if train_size < 1 or test_size < 1:
            raise InvalidSplitConfigError(
                f"train_size and test_size must be >= 1 (got {train_size}, {test_size})"
            )

        label_intervals = extract_label_intervals(
            timestamps, label_horizons, default_horizon_ns=self.purge_config.purge_horizon_ns
        )
        splits: list[SplitDefinition] = []

        # Calculate stride
        min_required = train_size + n_splits * test_size
        if total_len < min_required:
            raise EmptyPartitionError(
                f"Dataset length ({total_len}) is insufficient for {n_splits} splits "
                f"with train_size={train_size}, test_size={test_size} (requires >= {min_required})."
            )

        stride = test_size

        for i in range(n_splits):
            test_end_nom = total_len - (n_splits - 1 - i) * stride
            test_start_nom = test_end_nom - test_size

            if expanding:
                train_start_idx = 0
            else:
                train_start_idx = max(0, test_start_nom - train_size)

            # Adjust boundaries for ties
            test_start_idx = find_safe_boundary_index(
                timestamps,
                test_start_nom,
                total_len,
                min_left_size=train_start_idx + 1,
                min_right_size=1,
            )
            test_end_idx = (
                find_safe_boundary_index(
                    timestamps,
                    test_end_nom,
                    total_len,
                    min_left_size=test_start_idx + 1,
                    min_right_size=0,
                )
                if test_end_nom < total_len
                else total_len
            )

            train_candidates = list(range(train_start_idx, test_start_idx))
            test_candidates = list(range(test_start_idx, test_end_idx))

            if len(train_candidates) == 0 or len(test_candidates) == 0:
                raise EmptyPartitionError(f"Walk-forward fold {i} produced an empty partition.")

            train_interval = TimeInterval(timestamps[train_start_idx], timestamps[test_start_idx])
            test_interval = TimeInterval(
                timestamps[test_start_idx], timestamps[test_end_idx - 1] + 1
            )

            # Purge train against test
            train_kept, purged_count, _ = purge_and_embargo_samples(
                train_candidates,
                timestamps,
                label_intervals,
                test_interval,
                is_pre_eval=True,
                purge_config=self.purge_config,
            )

            if len(train_kept) == 0:
                raise EmptyPartitionError(
                    f"Walk-forward fold {i} training partition exhausted after purging."
                )

            train_part = SplitPartition(
                role=PartitionRole.TRAIN,
                partition_index=0,
                time_boundary=train_interval,
                record_count=len(train_kept),
                record_indices=train_kept,
            )
            test_part = SplitPartition(
                role=PartitionRole.TEST,
                partition_index=1,
                time_boundary=test_interval,
                record_count=len(test_candidates),
                record_indices=tuple(test_candidates),
            )

            splits.append(
                SplitDefinition(
                    split_index=i,
                    train_partition=train_part,
                    test_partition=test_part,
                    purged_record_count=purged_count,
                    embargoed_record_count=0,
                    metadata={
                        "split_type": (
                            SplitType.WALK_FORWARD_EXPANDING.value
                            if expanding
                            else SplitType.WALK_FORWARD_ROLLING.value
                        ),
                        "fold_index": i,
                        "test_intervals": [test_interval.to_dict()],
                    },
                )
            )

        return splits

    def split_purged_k_fold(
        self,
        timestamps: Sequence[int],
        n_splits: int = 5,
        label_horizons: Sequence[int] | int | None = None,
    ) -> list[SplitDefinition]:
        """Marcos Lopez de Prado's Purged K-Fold Cross-Validation.

        Divides timestamps into n_splits contiguous temporal blocks.
        For fold i, block i is the test partition.
        For training blocks:
        - Blocks before test (pre-test): purged if label horizon touches test block.
        - Blocks after test (post-test): embargoed if within [test_end, test_end + embargo_ns).
        """
        validate_monotonic_timestamps(timestamps)
        total_len = len(timestamps)

        if n_splits < 2:
            raise InvalidSplitConfigError(f"Purged K-Fold requires n_splits >= 2, got {n_splits}")
        if total_len < n_splits:
            raise EmptyPartitionError(
                f"Dataset length ({total_len}) is smaller than n_splits ({n_splits})"
            )

        label_intervals = extract_label_intervals(
            timestamps, label_horizons, default_horizon_ns=self.purge_config.purge_horizon_ns
        )

        # Compute block boundary cut indices
        block_cuts = [0]
        for k in range(1, n_splits):
            nominal_cut = int(k * (total_len / n_splits))
            safe_cut = find_safe_boundary_index(
                timestamps,
                nominal_cut,
                total_len,
                min_left_size=k,
                min_right_size=n_splits - k,
            )
            block_cuts.append(safe_cut)
        block_cuts.append(total_len)

        # Build contiguous blocks
        blocks: list[tuple[int, int]] = []
        for k in range(n_splits):
            start = block_cuts[k]
            end = block_cuts[k + 1]
            if start >= end:
                raise EmptyPartitionError(
                    f"Purged K-Fold block {k} is empty due to duplicate timestamp boundaries."
                )
            blocks.append((start, end))

        splits: list[SplitDefinition] = []

        for fold_idx in range(n_splits):
            test_start_idx, test_end_idx = blocks[fold_idx]
            test_indices = tuple(range(test_start_idx, test_end_idx))
            test_interval = TimeInterval(
                timestamps[test_start_idx],
                timestamps[test_end_idx - 1] + 1,
            )

            train_kept: list[int] = []
            total_purged = 0
            total_embargoed = 0

            # Pre-test blocks (blocks before fold_idx)
            for b_idx in range(0, fold_idx):
                b_start, b_end = blocks[b_idx]
                candidates = list(range(b_start, b_end))
                kept, p_count, _ = purge_and_embargo_samples(
                    candidates,
                    timestamps,
                    label_intervals,
                    test_interval,
                    is_pre_eval=True,
                    purge_config=self.purge_config,
                )
                train_kept.extend(kept)
                total_purged += p_count

            # Post-test blocks (blocks after fold_idx)
            for b_idx in range(fold_idx + 1, n_splits):
                b_start, b_end = blocks[b_idx]
                candidates = list(range(b_start, b_end))
                kept, p_count, e_count = purge_and_embargo_samples(
                    candidates,
                    timestamps,
                    label_intervals,
                    test_interval,
                    is_pre_eval=False,
                    purge_config=self.purge_config,
                )
                train_kept.extend(kept)
                total_purged += p_count
                total_embargoed += e_count

            if len(train_kept) == 0:
                raise EmptyPartitionError(
                    f"Purged K-Fold fold {fold_idx} training partition exhausted after purging."
                )

            # Composite train interval bounding kept training records
            train_min_ts = min(timestamps[i] for i in train_kept)
            train_max_ts = max(timestamps[i] for i in train_kept)
            train_interval = TimeInterval(train_min_ts, train_max_ts + 1)

            train_part = SplitPartition(
                role=PartitionRole.TRAIN,
                partition_index=0,
                time_boundary=train_interval,
                record_count=len(train_kept),
                record_indices=tuple(train_kept),
            )
            test_part = SplitPartition(
                role=PartitionRole.TEST,
                partition_index=1,
                time_boundary=test_interval,
                record_count=len(test_indices),
                record_indices=test_indices,
            )

            splits.append(
                SplitDefinition(
                    split_index=fold_idx,
                    train_partition=train_part,
                    test_partition=test_part,
                    purged_record_count=total_purged,
                    embargoed_record_count=total_embargoed,
                    metadata={
                        "split_type": SplitType.PURGED_K_FOLD.value,
                        "fold_index": fold_idx,
                        "test_block_index": fold_idx,
                        "test_intervals": [test_interval.to_dict()],
                    },
                )
            )

        return splits

    def split_combinatorial_purged(
        self,
        timestamps: Sequence[int],
        n_splits: int = 5,
        n_test_splits: int = 2,
        label_horizons: Sequence[int] | int | None = None,
    ) -> list[SplitDefinition]:
        """Combinatorial Purged Cross-Validation (CPCV).

        Generates all (n_splits choose n_test_splits) combinations of test blocks.
        For each combination, purging and embargo are applied across all test blocks.
        """
        validate_monotonic_timestamps(timestamps)
        total_len = len(timestamps)

        if n_test_splits >= n_splits or n_test_splits < 1:
            raise InvalidSplitConfigError(
                f"n_test_splits must be between 1 and n_splits-1 (got {n_test_splits}, {n_splits})"
            )

        label_intervals = extract_label_intervals(
            timestamps, label_horizons, default_horizon_ns=self.purge_config.purge_horizon_ns
        )

        # Compute block cuts
        block_cuts = [0]
        for k in range(1, n_splits):
            nominal_cut = int(k * (total_len / n_splits))
            safe_cut = find_safe_boundary_index(
                timestamps,
                nominal_cut,
                total_len,
                min_left_size=k,
                min_right_size=n_splits - k,
            )
            block_cuts.append(safe_cut)
        block_cuts.append(total_len)

        blocks: list[tuple[int, int]] = []
        for k in range(n_splits):
            start = block_cuts[k]
            end = block_cuts[k + 1]
            if start >= end:
                raise EmptyPartitionError(
                    f"CPCV block {k} is empty due to duplicate timestamp boundaries."
                )
            blocks.append((start, end))

        comb_splits: list[SplitDefinition] = []
        comb_idx = 0

        for test_block_indices in itertools.combinations(range(n_splits), n_test_splits):
            # Test indices are union of all test blocks
            test_indices_list: list[int] = []
            test_intervals: list[TimeInterval] = []

            for b_idx in test_block_indices:
                b_start, b_end = blocks[b_idx]
                test_indices_list.extend(range(b_start, b_end))
                test_intervals.append(TimeInterval(timestamps[b_start], timestamps[b_end - 1] + 1))

            # Training blocks are the complement
            train_block_indices = [i for i in range(n_splits) if i not in test_block_indices]
            train_kept_set: set[int] = set()

            total_purged = 0
            total_embargoed = 0

            for tb_idx in train_block_indices:
                b_start, b_end = blocks[tb_idx]
                block_candidates = list(range(b_start, b_end))

                # Determine if this block is pre-eval or post-eval relative to each test block
                # A training sample must be validated against EVERY test block
                kept_candidates = block_candidates
                for test_b_idx, t_interval in zip(test_block_indices, test_intervals, strict=True):
                    is_pre = tb_idx < test_b_idx
                    kept_candidates_t, p_count, e_count = purge_and_embargo_samples(
                        kept_candidates,
                        timestamps,
                        label_intervals,
                        t_interval,
                        is_pre_eval=is_pre,
                        purge_config=self.purge_config,
                    )
                    total_purged += p_count
                    total_embargoed += e_count
                    kept_candidates = list(kept_candidates_t)

                train_kept_set.update(kept_candidates)

            train_kept_sorted = sorted(train_kept_set)
            if len(train_kept_sorted) == 0:
                raise EmptyPartitionError(
                    f"CPCV combination {comb_idx} training partition exhausted after purging."
                )

            train_min_ts = min(timestamps[i] for i in train_kept_sorted)
            train_max_ts = max(timestamps[i] for i in train_kept_sorted)
            train_interval = TimeInterval(train_min_ts, train_max_ts + 1)

            test_min_ts = min(timestamps[i] for i in test_indices_list)
            test_max_ts = max(timestamps[i] for i in test_indices_list)
            composite_test_interval = TimeInterval(test_min_ts, test_max_ts + 1)

            train_part = SplitPartition(
                role=PartitionRole.TRAIN,
                partition_index=0,
                time_boundary=train_interval,
                record_count=len(train_kept_sorted),
                record_indices=tuple(train_kept_sorted),
            )
            test_part = SplitPartition(
                role=PartitionRole.TEST,
                partition_index=1,
                time_boundary=composite_test_interval,
                record_count=len(test_indices_list),
                record_indices=tuple(test_indices_list),
            )

            comb_splits.append(
                SplitDefinition(
                    split_index=comb_idx,
                    train_partition=train_part,
                    test_partition=test_part,
                    purged_record_count=total_purged,
                    embargoed_record_count=total_embargoed,
                    metadata={
                        "split_type": SplitType.COMBINATORIAL_PURGED.value,
                        "test_block_indices": list(test_block_indices),
                        "test_intervals": [t.to_dict() for t in test_intervals],
                    },
                )
            )
            comb_idx += 1

        return comb_splits
