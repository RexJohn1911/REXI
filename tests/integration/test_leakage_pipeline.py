"""End-to-end integration test for Phase 09 No-Leakage Research Pipeline."""

from pathlib import Path

import pyarrow as pa

from research.datasets.generator import SyntheticMarketDataGenerator
from research.datasets.reader import DatasetReader
from research.datasets.types import DataDomain, DatasetKind
from research.datasets.writer import DatasetWriter
from research.leakage.dataset_split import DatasetSplitter, SplitDatasetReader
from research.leakage.detector import LookaheadDetector
from research.leakage.point_in_time import PointInTimeAligner
from research.leakage.types import (
    LabelInformationInterval,
    PartitionRole,
    PurgeEmbargoConfig,
)


def test_end_to_end_no_leakage_pipeline(tmp_path: Path) -> None:
    """Validate end-to-end workflow: Ingestion -> Causal Split -> Point-in-Time Join -> Audit."""
    lake_root = tmp_path / "lake"
    dataset_id = "pipeline_test_trades"

    # 1. Ingestion: Generate synthetic trade stream
    gen = SyntheticMarketDataGenerator(seed=1337)
    trades_table = gen.generate_trades(count=300, instrument_id=10, venue_id=1)

    with DatasetWriter(
        dataset_id=dataset_id,
        name="Pipeline Test Trades",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=lake_root,
    ) as writer:
        writer.write_batch(trades_table)

    reader = DatasetReader(dataset_id=dataset_id, root_dir=lake_root)
    assert reader.record_count == 300

    # 2. Causal Partitioning: Purged K-Fold with 10ms label horizon and 5ms post-test embargo
    purge_config = PurgeEmbargoConfig(purge_horizon_ns=10_000_000, embargo_ns=5_000_000)
    splitter = DatasetSplitter(
        reader=reader,
        timestamp_column="receive_timestamp_ns",
        purge_config=purge_config,
    )

    split_manifest = splitter.create_purged_k_fold_split(
        split_manifest_id="pipeline_kfold_split",
        n_splits=5,
        label_horizons=10_000_000,
    )
    assert split_manifest.verify_integrity()
    assert len(split_manifest.splits) == 5

    timestamps = splitter.extract_timestamps()
    label_intervals = [LabelInformationInterval(t, t + 10_000_000) for t in timestamps]

    # Audit all 5 folds for complete boundary, purge, and embargo compliance
    for fold in split_manifest.splits:
        report = LookaheadDetector.audit_split_compliance(
            fold, timestamps, label_intervals, purge_config
        )
        assert report.is_valid, f"Fold {fold.split_index} failed compliance: {report.violations}"

    # 3. Read partition tables
    split_reader = SplitDatasetReader(reader=reader, manifest=split_manifest)
    fold_0_train = split_reader.read_partition_table(split_index=0, role=PartitionRole.TRAIN)
    fold_0_test = split_reader.read_partition_table(split_index=0, role=PartitionRole.TEST)

    assert fold_0_train.num_rows > 0
    assert fold_0_test.num_rows == 60  # 300 / 5 = 60

    # 4. Feature Engineering & Point-in-Time Alignment
    # Construct an external feature signal with realistic dissemination latency (+500 microseconds)
    event_times = fold_0_test["source_timestamp_ns"].to_pylist()
    avail_times = [t + 500_000 for t in event_times]  # 500 us delay
    feature_vals = [float(p) / 100.0 for p in fold_0_test["price"].to_pylist()]

    features_table = pa.table(
        {
            "source_timestamp_ns": event_times,
            "receive_timestamp_ns": avail_times,
            "signal_val": feature_vals,
        }
    )

    # Strategy evaluates trading decisions every 2 milliseconds
    min_test_t = event_times[0]
    max_test_t = event_times[-1]
    decision_timestamps = list(range(min_test_t, max_test_t, 2_000_000))

    aligner = PointInTimeAligner()
    aligned_table = aligner.align_as_of(decision_timestamps, features_table)

    # 5. Audit Point-in-Time Feature Alignment
    dec_ts = aligned_table["decision_timestamp_ns"].to_pylist()
    matched_av = aligned_table["receive_timestamp_ns"].to_pylist()
    matched_ev = aligned_table["source_timestamp_ns"].to_pylist()

    pit_report = LookaheadDetector.audit_point_in_time(
        decision_timestamps=dec_ts,
        available_timestamps=matched_av,
        event_timestamps=matched_ev,
    )
    assert pit_report.is_valid, f"Point-in-time audit failed: {pit_report.violations}"

    # 6. Intentional Failure Injection: Ensure LookaheadDetector catches lookahead violation
    corrupted_available = [t + 10_000_000 for t in dec_ts]  # Feature arrives 10ms in future
    corrupted_report = LookaheadDetector.audit_point_in_time(
        decision_timestamps=dec_ts,
        available_timestamps=corrupted_available,
    )
    assert not corrupted_report.is_valid
    assert corrupted_report.violation_count == len(dec_ts)
    assert "Lookahead violation" in corrupted_report.violations[0]
