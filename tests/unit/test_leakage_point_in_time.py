"""Unit tests for point-in-time alignment and lookahead leakage detection."""

import pyarrow as pa
import pytest

from research.leakage.detector import LookaheadDetector
from research.leakage.exceptions import LookaheadBiasError
from research.leakage.point_in_time import PointInTimeAligner
from research.leakage.split import ChronologicalSplitter
from research.leakage.types import (
    LabelInformationInterval,
    PurgeEmbargoConfig,
    SplitPartition,
)


def test_point_in_time_simultaneous_and_prior_arrival() -> None:
    """Features arriving prior to or simultaneously with decision time are causally matched."""
    # Feature published at t=100 (event=90), t=200 (event=190), t=300 (event=290)
    features_table = pa.table(
        {
            "source_timestamp_ns": [90, 190, 290],
            "receive_timestamp_ns": [100, 200, 300],
            "feature_val": [10.0, 20.0, 30.0],
        }
    )

    aligner = PointInTimeAligner()

    # Decision times:
    # 50: no feature available yet -> null
    # 100: exactly matches feature at receive_timestamp 100 (simultaneous arrival) -> 10.0
    # 250: matches most recent available feature (receive_timestamp 200) -> 20.0
    # 300: matches receive_timestamp 300 -> 30.0
    decision_ts = [50, 100, 250, 300]
    aligned = aligner.align_as_of(decision_ts, features_table)

    res_vals = aligned["feature_val"].to_pylist()
    assert res_vals[0] is None
    assert res_vals[1] == 10.0
    assert res_vals[2] == 20.0
    assert res_vals[3] == 30.0


def test_point_in_time_lookahead_detection() -> None:
    """Attempting to use a feature available in the future raises LookaheadBiasError."""
    decision_ts = [100, 200]
    # Feature 205 is available AFTER decision 200
    matched_available = [100, 205]

    with pytest.raises(LookaheadBiasError, match="Lookahead bias detected"):
        PointInTimeAligner.verify_decision_alignment(decision_ts, matched_available)


def test_point_in_time_causal_inversion_detection() -> None:
    """Event timestamp greater than available timestamp raises LookaheadBiasError."""
    event_ts = [100, 210]  # Event at 210
    avail_ts = [100, 200]  # But claimed available at 200!

    with pytest.raises(LookaheadBiasError, match="Physical causality violation"):
        PointInTimeAligner.verify_causality(event_ts, avail_ts)


def test_lookahead_detector_point_in_time_audit() -> None:
    """LookaheadDetector reports violations with detailed audit metadata."""
    decision_ts = [100, 200, 300]
    # Sample 1 has lookahead: 250 > 200
    available_ts = [90, 250, 290]

    report = LookaheadDetector.audit_point_in_time(decision_ts, available_ts)
    assert not report.is_valid
    assert report.violation_count == 1
    assert "Sample 1: Lookahead violation" in report.violations[0]


def test_lookahead_detector_split_compliance_audit() -> None:
    """LookaheadDetector verifies valid split and catches unpurged overlaps."""
    timestamps = [i * 10 for i in range(100)]
    purge_config = PurgeEmbargoConfig(purge_horizon_ns=50, embargo_ns=30)
    splitter = ChronologicalSplitter(purge_config=purge_config)

    split_def = splitter.split_holdout(
        timestamps,
        train_ratio=0.7,
        val_ratio=0.0,
        test_ratio=0.3,
        label_horizons=50,
    )

    label_intervals = [LabelInformationInterval(t, t + 50) for t in timestamps]

    # Clean split passes audit
    report_clean = LookaheadDetector.audit_split_compliance(
        split_def, timestamps, label_intervals, purge_config
    )
    assert report_clean.is_valid
    assert report_clean.violation_count == 0

    # Inject an unpurged sample (sample 69, which touches test partition [700, 1000))
    corrupted_train_indices = (*(split_def.train_partition.record_indices or ()), 69)
    corrupted_train_part = SplitPartition(
        role=split_def.train_partition.role,
        partition_index=split_def.train_partition.partition_index,
        time_boundary=split_def.train_partition.time_boundary,
        record_count=len(corrupted_train_indices),
        record_indices=corrupted_train_indices,
    )
    corrupted_split_def = split_def.__class__(
        split_index=split_def.split_index,
        train_partition=corrupted_train_part,
        test_partition=split_def.test_partition,
    )

    report_corrupted = LookaheadDetector.audit_split_compliance(
        corrupted_split_def, timestamps, label_intervals, purge_config
    )
    assert not report_corrupted.is_valid
    assert any("touches test partition" in v for v in report_corrupted.violations)


def test_correlation_heuristic_diagnostic() -> None:
    """Correlation heuristic returns exploratory metrics without raising errors."""
    f = [1.0, 2.0, 3.0, 4.0, 5.0]
    t = [2.0, 4.0, 6.0, 8.0, 10.0]

    res = LookaheadDetector.compute_feature_target_correlation_heuristic(f, t)
    assert res["correlation"] > 0.99
    assert res["is_suspicious_near_identity"]
    assert "heuristic only" in res["note"]
