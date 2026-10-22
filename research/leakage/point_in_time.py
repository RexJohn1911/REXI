"""Point-in-time causal feature alignment engine enforcing T_available <= T_decision."""

from bisect import bisect_right
from collections.abc import Sequence
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from research.leakage.exceptions import (
    EmptyPartitionError,
    LookaheadBiasError,
    TimestampSafetyError,
)
from research.leakage.split import validate_monotonic_timestamps


class PointInTimeAligner:
    """As-of causal join aligner matching decisions with point-in-time available features."""

    def __init__(self, max_staleness_ns: int | None = None) -> None:
        """Initialize aligner.

        Args:
            max_staleness_ns: Optional maximum allowed elapsed nanoseconds between
                feature availability and decision timestamp
                (T_decision - T_available <= max_staleness).
        """
        if max_staleness_ns is not None and max_staleness_ns < 0:
            raise TimestampSafetyError(f"max_staleness_ns cannot be negative: {max_staleness_ns}")
        self.max_staleness_ns = max_staleness_ns

    @staticmethod
    def verify_causality(
        event_timestamps: Sequence[int],
        available_timestamps: Sequence[int],
    ) -> None:
        """Verify physical causality invariant: T_event <= T_available.

        Raises LookaheadBiasError if any event is reported as available before it occurred.
        """
        if len(event_timestamps) != len(available_timestamps):
            raise TimestampSafetyError(
                f"Mismatch in timestamp lengths: {len(event_timestamps)} vs "
                f"{len(available_timestamps)}"
            )

        for i, (t_ev, t_av) in enumerate(zip(event_timestamps, available_timestamps, strict=True)):
            if t_ev > t_av:
                raise LookaheadBiasError(
                    f"Physical causality violation at index {i}: "
                    f"event_timestamp ({t_ev}) > available_timestamp ({t_av}). "
                    "An event cannot be available before it physically occurred."
                )

    @staticmethod
    def verify_decision_alignment(
        decision_timestamps: Sequence[int],
        matched_available_timestamps: Sequence[int | None],
    ) -> None:
        """Verify decision causality invariant: T_available <= T_decision.

        Raises LookaheadBiasError if any feature is consumed before its availability time.
        """
        if len(decision_timestamps) != len(matched_available_timestamps):
            raise TimestampSafetyError(
                f"Mismatch in decision and feature lengths: "
                f"{len(decision_timestamps)} vs {len(matched_available_timestamps)}"
            )

        for i, (t_dec, t_av) in enumerate(
            zip(decision_timestamps, matched_available_timestamps, strict=True)
        ):
            if t_av is not None and t_av > t_dec:
                raise LookaheadBiasError(
                    f"Lookahead bias detected at decision index {i}: "
                    f"available_timestamp ({t_av}) > decision_timestamp ({t_dec}). "
                    "Features cannot be used before they are point-in-time available."
                )

    def align_as_of(
        self,
        decision_timestamps: Sequence[int],
        features_table: pa.Table,
        event_ts_col: str = "source_timestamp_ns",
        available_ts_col: str = "receive_timestamp_ns",
    ) -> pa.Table:
        """Perform point-in-time causal as-of alignment.

        For each decision timestamp T_dec, selects the most recent feature row where:
            T_available <= T_dec
        Optionally enforces (T_dec - T_available <= max_staleness_ns).

        Returns:
            PyArrow Table containing decision_timestamp_ns and aligned feature columns.
        """
        validate_monotonic_timestamps(decision_timestamps)

        if features_table.num_rows == 0:
            raise EmptyPartitionError("Features table cannot be empty for point-in-time alignment.")

        if event_ts_col not in features_table.column_names:
            raise TimestampSafetyError(
                f"Missing event timestamp column '{event_ts_col}' in features table."
            )
        if available_ts_col not in features_table.column_names:
            raise TimestampSafetyError(
                f"Missing available timestamp column '{available_ts_col}' in features table."
            )

        # Extract timestamp arrays
        ev_arr = features_table[event_ts_col].to_pylist()
        av_arr = features_table[available_ts_col].to_pylist()

        # 1. Verify physical causality for features: T_event <= T_available
        self.verify_causality(ev_arr, av_arr)

        # 2. Verify available_timestamps is sorted monotonically
        validate_monotonic_timestamps(av_arr)

        # Perform as-of lookup for each decision timestamp
        aligned_indices: list[int | None] = []
        matched_av_ts: list[int | None] = []

        for t_dec in decision_timestamps:
            # Find rightmost feature where available_ts <= t_dec
            # bisect_right returns index where element would be inserted to maintain sorted order
            idx = bisect_right(av_arr, t_dec) - 1

            if idx >= 0:
                t_match = av_arr[idx]
                # Check staleness if configured
                if self.max_staleness_ns is not None:
                    if (t_dec - t_match) > self.max_staleness_ns:
                        aligned_indices.append(None)
                        matched_av_ts.append(None)
                        continue
                aligned_indices.append(idx)
                matched_av_ts.append(t_match)
            else:
                # No feature available as of t_dec
                aligned_indices.append(None)
                matched_av_ts.append(None)

        # 3. Verify decision causality: T_available <= T_decision
        self.verify_decision_alignment(decision_timestamps, matched_av_ts)

        # Build output PyArrow table
        # Create decision_timestamp column
        cols: dict[str, Any] = {
            "decision_timestamp_ns": pa.array(decision_timestamps, type=pa.int64())
        }

        # Build mask for valid vs null matches
        valid_mask = [i is not None for i in aligned_indices]
        valid_indices = [i if i is not None else 0 for i in aligned_indices]

        # Project feature columns
        for col_name in features_table.column_names:
            src_col = features_table[col_name]
            # Take matched values
            taken = pc.take(src_col, valid_indices)
            # Nullify unmatched slots
            null_mask = pa.array([not m for m in valid_mask], type=pa.bool_())
            null_val = pa.scalar(None, type=src_col.type)
            final_col = pc.if_else(null_mask, null_val, taken)
            cols[col_name] = final_col

        return pa.table(cols)
