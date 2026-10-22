"""Integration tests for MicrostructureFeaturePipeline with Phase 08 Data Lake
and Phase 09 Safeguards.
"""

from pathlib import Path

import pyarrow as pa

from research.datasets.generator import SyntheticMarketDataGenerator
from research.datasets.reader import DatasetReader
from research.datasets.types import CompressionType, DataDomain, DatasetKind
from research.datasets.writer import DatasetWriter
from research.features.pipeline import MicrostructureFeaturePipeline
from research.features.schema import register_microstructure_schemas


def test_feature_pipeline_audit_against_lookahead(tmp_path: Path) -> None:
    # 1. Generate synthetic top of book dataset
    generator = SyntheticMarketDataGenerator(seed=42)
    tob_table = generator.generate_top_of_book(count=300, instrument_id=101)

    # 2. Extract features and audit point-in-time causality
    pipeline = MicrostructureFeaturePipeline(instrument_id=101)
    feature_table, audit_report = pipeline.extract_and_audit(tob_table, event_type="top_of_book")

    assert len(feature_table) == 300
    assert audit_report.is_valid is True
    assert audit_report.violation_count == 0
    assert len(audit_report.violations) == 0


def test_feature_pipeline_align_features_to_decisions(tmp_path: Path) -> None:
    generator = SyntheticMarketDataGenerator(seed=99)
    tob_table = generator.generate_top_of_book(count=100, instrument_id=101)

    pipeline = MicrostructureFeaturePipeline(instrument_id=101)
    feature_table = pipeline.extract_from_table(tob_table, event_type="top_of_book")

    # Sample decision timestamps interleaved with event timestamps
    ev_ts = feature_table["decision_timestamp_ns"].to_pylist()
    decision_timestamps = [ev_ts[10] + 50, ev_ts[25] + 100, ev_ts[50] + 10]

    aligned_table = pipeline.align_features_to_decisions(
        features_table=feature_table,
        decision_timestamps=decision_timestamps,
        max_staleness_ns=1_000_000_000,
    )

    assert len(aligned_table) == 3
    # Check that aligned feature event timestamp <= input decision timestamp
    for i, t_dec in enumerate(decision_timestamps):
        ev_ts = aligned_table["event_timestamp_ns"][i].as_py()
        assert ev_ts is not None
        assert ev_ts <= t_dec


def test_feature_pipeline_dataset_roundtrip(tmp_path: Path) -> None:
    # Register schema in registry
    register_microstructure_schemas()

    generator = SyntheticMarketDataGenerator(seed=777)
    tob_table = generator.generate_top_of_book(count=200, instrument_id=101)

    pipeline = MicrostructureFeaturePipeline(instrument_id=101)
    feature_table = pipeline.extract_from_table(tob_table, event_type="top_of_book")

    # Write enriched feature dataset to Data Lake
    dataset_id = "test_features_101"
    with DatasetWriter(
        dataset_id=dataset_id,
        name="Test Features 101",
        kind=DatasetKind.FEATURES,
        domain=DataDomain.FEATURES,
        schema_name="rexi.features.microstructure",
        root_dir=tmp_path,
        compression=CompressionType.ZSTD,
    ) as writer:
        writer.write_batch(feature_table)

    # Read back and verify integrity
    reader = DatasetReader(dataset_id=dataset_id, root_dir=tmp_path)
    ok, errors = reader.verify_integrity()
    assert ok is True
    assert len(errors) == 0

    read_table = reader.read_table()
    assert len(read_table) == 200
    assert read_table.column_names == feature_table.column_names
    assert read_table["mid_price"].to_pylist() == feature_table["mid_price"].to_pylist()
    assert read_table["has_spread"].to_pylist() == feature_table["has_spread"].to_pylist()


def test_feature_pipeline_causal_invariance_against_future_shocks() -> None:
    generator = SyntheticMarketDataGenerator(seed=123)
    # Generate initial 60 events
    t1 = generator.generate_top_of_book(count=60, instrument_id=101)

    pipeline1 = MicrostructureFeaturePipeline(instrument_id=101)
    f1 = pipeline1.extract_from_table(t1, event_type="top_of_book")

    # Pick decision timestamps within the first 50 events
    dec_ts = [t1["source_timestamp_ns"][10].as_py() + 1, t1["source_timestamp_ns"][30].as_py() + 1]
    aligned1 = pipeline1.align_features_to_decisions(f1, dec_ts)

    # Now simulate future events with wild price shocks (simulating future market crash)
    t_shock = generator.generate_top_of_book(count=40, instrument_id=101)
    last_src = t1["source_timestamp_ns"][-1].as_py()
    last_recv = t1["receive_timestamp_ns"][-1].as_py()
    shock_dict = t_shock.to_pydict()
    shock_dict["source_timestamp_ns"] = [last_src + 1000 * (i + 1) for i in range(40)]
    shock_dict["receive_timestamp_ns"] = [last_recv + 1000 * (i + 1) for i in range(40)]
    shock_dict["sequence_num"] = [60 + i + 1 for i in range(40)]
    shock_dict["best_bid_price"] = [500000] * 40
    shock_dict["best_ask_price"] = [500010] * 40
    t_shock_adj = pa.Table.from_pydict(shock_dict, schema=t1.schema)
    t_full = pa.concat_tables([t1, t_shock_adj])

    # Re-extract with fresh pipeline on full table
    pipeline2 = MicrostructureFeaturePipeline(instrument_id=101)
    f2 = pipeline2.extract_from_table(t_full, event_type="top_of_book")
    aligned2 = pipeline2.align_features_to_decisions(f2, dec_ts)

    # Verify that aligned past decisions are bit-for-bit identical!
    assert len(aligned1) == len(aligned2)
    for col in ["mid_price", "spread", "book_imbalance_top", "instant_ofi"]:
        assert aligned1[col].to_pylist() == aligned2[col].to_pylist()
