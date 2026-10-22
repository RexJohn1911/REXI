"""Integration tests for the end-to-end Research Data Lake ingestion and retrieval pipeline."""

from pathlib import Path

import pyarrow as pa

from research.datasets import (
    CompressionType,
    DataDomain,
    DatasetCatalog,
    DatasetKind,
    DatasetReader,
    DatasetWriter,
    ProvenanceInfo,
    SyntheticMarketDataGenerator,
)


def test_end_to_end_multi_dataset_ingestion_and_catalog_pipeline(tmp_path: Path) -> None:
    catalog = DatasetCatalog(root_dir=tmp_path)
    gen = SyntheticMarketDataGenerator(seed=1337)

    # 1. Ingest Trades Dataset (Partitioned by date & instrument_id)
    trades_day1_inst1 = gen.generate_trades(
        count=500,
        instrument_id=1,
        venue_id=1,
        start_time_ns=1_700_000_000_000_000_000,
    )
    trades_day1_inst2 = gen.generate_trades(
        count=600,
        instrument_id=2,
        venue_id=1,
        start_time_ns=1_700_000_000_000_000_000,
    )
    # Day 2 trades (+86400s)
    trades_day2_inst1 = gen.generate_trades(
        count=400,
        instrument_id=1,
        venue_id=1,
        start_time_ns=1_700_086_400_000_000_000,
    )

    trades_provenance = ProvenanceInfo(
        source_files=["raw_capture_feed_a.bin", "raw_capture_feed_b.bin"],
        source_dataset_id="raw_market_capture_2026",
        generator_name="SyntheticMarketDataGenerator",
        generator_version="1.0.0",
        replay_state_digest=0xDEADBEEF01234567,
        notes="Phase 08 Integration Pipeline Test",
    )

    with DatasetWriter(
        dataset_id="equities_l2_trades_v1",
        name="Equities L2 Executed Trades",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
        partition_by=["date", "instrument_id"],
        compression=CompressionType.ZSTD,
        provenance=trades_provenance,
    ) as writer:
        writer.write_batch(trades_day1_inst1)
        writer.write_batch(trades_day1_inst2)
        writer.write_batch(trades_day2_inst1)

    # 2. Ingest TopOfBook Quotes Dataset (Flat unpartitioned)
    quotes = gen.generate_top_of_book(count=1000, instrument_id=1, venue_id=1)
    with DatasetWriter(
        dataset_id="equities_bbo_quotes_v1",
        name="Equities BBO Top of Book",
        kind=DatasetKind.TOP_OF_BOOK,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.top_of_book",
        root_dir=tmp_path,
        compression=CompressionType.ZSTD,
    ) as writer:
        writer.write_batch(quotes)

    # 3. Ingest Replay Stream Dataset (Phase 07 Unified Replay Stream)
    replay_stream = gen.generate_replay_stream(count=800, instrument_id=1)
    with DatasetWriter(
        dataset_id="historical_replay_stream_v1",
        name="Historical Market Replay Stream",
        kind=DatasetKind.REPLAY_STREAM,
        domain=DataDomain.REPLAY,
        schema_name="rexi.replay.event",
        root_dir=tmp_path,
        compression=CompressionType.ZSTD,
    ) as writer:
        writer.write_batch(replay_stream)

    # 4. Discover via DatasetCatalog
    manifests = catalog.list_datasets()
    assert len(manifests) == 3
    dataset_ids = {m.dataset_id for m in manifests}
    assert dataset_ids == {
        "equities_l2_trades_v1",
        "equities_bbo_quotes_v1",
        "historical_replay_stream_v1",
    }

    # 5. Cryptographic Integrity Verification across all datasets
    for ds_id in dataset_ids:
        ok, errors = catalog.verify_dataset(ds_id)
        assert ok is True, f"Integrity check failed for {ds_id}: {errors}"
        assert len(errors) == 0

    # 6. Verify Trades Dataset Partition Discovery and Filtering
    trades_reader = DatasetReader("equities_l2_trades_v1", root_dir=tmp_path)
    assert trades_reader.record_count == 1500  # 500 + 600 + 400
    assert len(trades_reader.partitions) == 3

    # Filter by date only
    day1_table = trades_reader.read_table(filter_partitions={"date": "2023-11-14"})
    assert day1_table.num_rows == 1100  # 500 + 600

    # Filter by instrument_id only
    inst2_table = trades_reader.read_table(filter_partitions={"instrument_id": 2})
    assert inst2_table.num_rows == 600
    assert all(i == 2 for i in inst2_table["instrument_id"].to_pylist())

    # 7. Verify Column Selection & Bounded Streaming Iteration
    batch_rows = 0
    for batch in trades_reader.read_batch_iter(
        batch_size=250, columns=["trade_id", "price", "quantity"]
    ):
        assert isinstance(batch, pa.RecordBatch)
        assert batch.column_names == ["trade_id", "price", "quantity"]
        assert batch.num_rows <= 250
        batch_rows += batch.num_rows
    assert batch_rows == 1500

    # 8. Verify Provenance and Lineage Integrity
    prov_loaded = ProvenanceInfo.from_dict(trades_reader.manifest.provenance)
    assert prov_loaded.replay_state_digest == 0xDEADBEEF01234567
    assert prov_loaded.source_dataset_id == "raw_market_capture_2026"
    assert len(prov_loaded.source_files) == 2

    # 9. Verify Replay Stream Reader
    replay_reader = DatasetReader("historical_replay_stream_v1", root_dir=tmp_path)
    assert replay_reader.record_count == 800
    replay_table = replay_reader.read_table()
    assert replay_table.num_rows == 800
    assert "source" in replay_table.column_names
    assert "input_index" in replay_table.column_names
