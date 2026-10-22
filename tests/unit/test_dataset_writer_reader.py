"""Unit tests for DatasetWriter, DatasetReader, and comprehensive Parquet round-trips."""

from pathlib import Path

import pyarrow as pa
import pytest

from research.datasets.exceptions import (
    DatasetExistsError,
    DatasetNotFoundError,
    InvalidDatasetNameError,
)
from research.datasets.generator import SyntheticMarketDataGenerator
from research.datasets.reader import DatasetReader
from research.datasets.types import CompressionType, DataDomain, DatasetKind
from research.datasets.writer import DatasetWriter


def test_write_read_roundtrip_trades(tmp_path: Path) -> None:
    generator = SyntheticMarketDataGenerator(seed=123)
    table = generator.generate_trades(count=500, instrument_id=101, venue_id=1)

    with DatasetWriter(
        dataset_id="test_trades_01",
        name="Test Trades",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
        compression=CompressionType.ZSTD,
    ) as writer:
        writer.write_batch(table)

    reader = DatasetReader("test_trades_01", root_dir=tmp_path)
    assert reader.record_count == 500
    assert len(reader.partitions) == 1

    read_table = reader.read_table()
    assert read_table.num_rows == 500
    assert read_table["price"].to_pylist() == table["price"].to_pylist()
    assert read_table["quantity"].to_pylist() == table["quantity"].to_pylist()
    assert (
        read_table["source_timestamp_ns"].to_pylist() == table["source_timestamp_ns"].to_pylist()
    )


def test_write_read_roundtrip_top_of_book(tmp_path: Path) -> None:
    generator = SyntheticMarketDataGenerator(seed=234)
    table = generator.generate_top_of_book(count=200, instrument_id=50)

    with DatasetWriter(
        dataset_id="test_tob_01",
        name="Test Top of Book",
        kind=DatasetKind.TOP_OF_BOOK,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.top_of_book",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(table)

    reader = DatasetReader("test_tob_01", root_dir=tmp_path)
    assert reader.record_count == 200

    read_table = reader.read_table()
    assert read_table.num_rows == 200
    assert read_table["best_bid_price"].to_pylist() == table["best_bid_price"].to_pylist()
    assert read_table["best_ask_price"].to_pylist() == table["best_ask_price"].to_pylist()
    assert read_table["best_bid_quantity"].to_pylist() == table["best_bid_quantity"].to_pylist()
    assert read_table["best_ask_quantity"].to_pylist() == table["best_ask_quantity"].to_pylist()


def test_write_read_roundtrip_order_book_updates(tmp_path: Path) -> None:
    generator = SyntheticMarketDataGenerator(seed=345)
    table = generator.generate_order_book_updates(count=300, instrument_id=77)

    with DatasetWriter(
        dataset_id="test_l3_updates_01",
        name="Test L3 Updates",
        kind=DatasetKind.ORDER_BOOK_UPDATES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.order_book_update",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(table)

    reader = DatasetReader("test_l3_updates_01", root_dir=tmp_path)
    assert reader.record_count == 300

    read_table = reader.read_table()
    assert read_table.num_rows == 300
    assert read_table["order_id"].to_pylist() == table["order_id"].to_pylist()
    assert read_table["action"].to_pylist() == table["action"].to_pylist()
    assert read_table["side"].to_pylist() == table["side"].to_pylist()
    assert read_table["price"].to_pylist() == table["price"].to_pylist()
    assert read_table["quantity"].to_pylist() == table["quantity"].to_pylist()


def test_write_read_roundtrip_order_book_snapshots(tmp_path: Path) -> None:
    generator = SyntheticMarketDataGenerator(seed=456)
    table = generator.generate_order_book_snapshots(count=50, instrument_id=88, levels=5)

    with DatasetWriter(
        dataset_id="test_ob_snapshots_01",
        name="Test Order Book Snapshots",
        kind=DatasetKind.ORDER_BOOK_SNAPSHOTS,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.order_book_snapshot",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(table)

    reader = DatasetReader("test_ob_snapshots_01", root_dir=tmp_path)
    assert reader.record_count == 50

    read_table = reader.read_table()
    assert read_table.num_rows == 50
    assert (
        read_table["last_included_sequence"].to_pylist()
        == table["last_included_sequence"].to_pylist()
    )
    assert read_table["bid_levels_count"].to_pylist() == table["bid_levels_count"].to_pylist()
    assert read_table["ask_levels_count"].to_pylist() == table["ask_levels_count"].to_pylist()
    assert read_table["bids"].to_pylist() == table["bids"].to_pylist()
    assert read_table["asks"].to_pylist() == table["asks"].to_pylist()


def test_write_read_roundtrip_market_status(tmp_path: Path) -> None:
    generator = SyntheticMarketDataGenerator(seed=567)
    table = generator.generate_market_status(count=30, venue_id=1)

    with DatasetWriter(
        dataset_id="test_market_status_01",
        name="Test Market Status",
        kind=DatasetKind.MARKET_STATUS,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.market_status",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(table)

    reader = DatasetReader("test_market_status_01", root_dir=tmp_path)
    assert reader.record_count == 30

    read_table = reader.read_table()
    assert read_table.num_rows == 30
    assert read_table["status"].to_pylist() == table["status"].to_pylist()
    assert read_table["status_flags"].to_pylist() == table["status_flags"].to_pylist()


def test_write_read_roundtrip_instrument_definitions(tmp_path: Path) -> None:
    generator = SyntheticMarketDataGenerator(seed=678)
    table = generator.generate_instrument_definitions(count=20, venue_id=1)

    with DatasetWriter(
        dataset_id="test_instrument_defs_01",
        name="Test Instrument Defs",
        kind=DatasetKind.INSTRUMENT_DEFINITIONS,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.instrument_definition",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(table)

    reader = DatasetReader("test_instrument_defs_01", root_dir=tmp_path)
    assert reader.record_count == 20

    read_table = reader.read_table()
    assert read_table.num_rows == 20
    assert read_table["tick_size"].to_pylist() == table["tick_size"].to_pylist()
    assert read_table["lot_size"].to_pylist() == table["lot_size"].to_pylist()
    assert read_table["min_quantity"].to_pylist() == table["min_quantity"].to_pylist()
    assert read_table["max_quantity"].to_pylist() == table["max_quantity"].to_pylist()


def test_write_read_roundtrip_replay_stream(tmp_path: Path) -> None:
    generator = SyntheticMarketDataGenerator(seed=789)
    table = generator.generate_replay_stream(count=150)

    with DatasetWriter(
        dataset_id="test_replay_stream_01",
        name="Test Replay Stream",
        kind=DatasetKind.REPLAY_STREAM,
        domain=DataDomain.REPLAY,
        schema_name="rexi.replay.event",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(table)

    reader = DatasetReader("test_replay_stream_01", root_dir=tmp_path)
    assert reader.record_count == 150

    read_table = reader.read_table()
    assert read_table.num_rows == 150
    assert read_table["message_type"].to_pylist() == table["message_type"].to_pylist()
    assert (
        read_table["last_included_sequence"].to_pylist()
        == table["last_included_sequence"].to_pylist()
    )
    assert read_table["bids"].to_pylist() == table["bids"].to_pylist()
    assert read_table["asks"].to_pylist() == table["asks"].to_pylist()


def test_write_read_replay_stream_v1_and_v2_datasets(tmp_path: Path) -> None:
    """Validate that legacy v1.0.0 and evolved v1.1.0 replay datasets write and read correctly."""
    generator = SyntheticMarketDataGenerator(seed=890)

    # 1. Write legacy v1.0.0 dataset
    t_v1 = generator.generate_replay_stream(count=100, schema_version="1.0.0")
    with DatasetWriter(
        dataset_id="test_replay_v1_legacy",
        name="Legacy Replay V1",
        kind=DatasetKind.REPLAY_STREAM,
        domain=DataDomain.REPLAY,
        schema_name="rexi.replay.event",
        schema_version="1.0.0",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(t_v1)

    reader_v1 = DatasetReader("test_replay_v1_legacy", root_dir=tmp_path)
    assert reader_v1.manifest.schema_version == "1.0.0"
    assert reader_v1.record_count == 100
    read_table_v1 = reader_v1.read_table()
    assert len(read_table_v1.schema) == 32
    assert "last_included_sequence" not in read_table_v1.column_names
    assert "bid_levels_count" not in read_table_v1.column_names
    assert "ask_levels_count" not in read_table_v1.column_names
    assert "bids" not in read_table_v1.column_names
    assert "asks" not in read_table_v1.column_names

    # Verify that attempting to query snapshot payload fields from V1 raises KeyError,
    # establishing that snapshot payloads were never stored and cannot be reconstructed
    with pytest.raises(KeyError):
        _ = read_table_v1["bids"]
    with pytest.raises(KeyError):
        _ = read_table_v1["asks"]

    # 2. Write evolved v1.1.0 dataset
    t_v2 = generator.generate_replay_stream(count=100, schema_version="1.1.0")
    with DatasetWriter(
        dataset_id="test_replay_v2_evolved",
        name="Evolved Replay V2",
        kind=DatasetKind.REPLAY_STREAM,
        domain=DataDomain.REPLAY,
        schema_name="rexi.replay.event",
        schema_version="1.1.0",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(t_v2)

    reader_v2 = DatasetReader("test_replay_v2_evolved", root_dir=tmp_path)
    assert reader_v2.manifest.schema_version == "1.1.0"
    assert reader_v2.record_count == 100
    read_table_v2 = reader_v2.read_table()
    assert len(read_table_v2.schema) == 37
    assert "last_included_sequence" in read_table_v2.column_names
    assert "bid_levels_count" in read_table_v2.column_names
    assert "ask_levels_count" in read_table_v2.column_names
    assert "bids" in read_table_v2.column_names
    assert "asks" in read_table_v2.column_names

    # Verify that V2 contains populated snapshot messages with exact nested levels
    snapshot_rows = [
        row for row in read_table_v2.to_pylist()
        if row["bids"] is not None and len(row["bids"]) > 0
    ]
    assert len(snapshot_rows) > 0
    first_snap = snapshot_rows[0]
    assert first_snap["bid_levels_count"] == 2
    assert first_snap["bids"][0]["price"] == 99990
    assert first_snap["bids"][0]["quantity"] == 100
    assert first_snap["bids"][0]["order_count"] == 2
    assert first_snap["asks"][0]["price"] == 100010


def test_write_read_partitioned_by_date_and_instrument(tmp_path: Path) -> None:
    generator = SyntheticMarketDataGenerator(seed=456)
    t1 = generator.generate_trades(
        count=100, instrument_id=1, start_time_ns=1_700_000_000_000_000_000
    )
    t2 = generator.generate_trades(
        count=200, instrument_id=2, start_time_ns=1_700_000_000_000_000_000
    )

    with DatasetWriter(
        dataset_id="partitioned_trades_01",
        name="Partitioned Trades",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
        partition_by=["date", "instrument_id"],
        compression=CompressionType.SNAPPY,
    ) as writer:
        writer.write_batch(t1)
        writer.write_batch(t2)

    reader = DatasetReader("partitioned_trades_01", root_dir=tmp_path)
    assert reader.record_count == 300
    assert len(reader.partitions) == 2

    # Filter by instrument_id=2
    inst2_table = reader.read_table(filter_partitions={"instrument_id": 2})
    assert inst2_table.num_rows == 200
    assert all(i == 2 for i in inst2_table["instrument_id"].to_pylist())

    # Filter by instrument_id=1
    inst1_table = reader.read_table(filter_partitions={"instrument_id": 1})
    assert inst1_table.num_rows == 100
    assert all(i == 1 for i in inst1_table["instrument_id"].to_pylist())


def test_bounded_batch_streaming_iteration(tmp_path: Path) -> None:
    generator = SyntheticMarketDataGenerator(seed=789)
    table = generator.generate_trades(count=1500, instrument_id=1)

    with DatasetWriter(
        dataset_id="streaming_trades_01",
        name="Streaming Trades",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(table)

    reader = DatasetReader("streaming_trades_01", root_dir=tmp_path)

    # Stream in bounded batches of 400
    total_iter_rows = 0
    batches = list(reader.read_batch_iter(batch_size=400))
    for b in batches:
        assert isinstance(b, pa.RecordBatch)
        assert b.num_rows <= 400
        total_iter_rows += b.num_rows

    assert total_iter_rows == 1500
    assert len(batches) == 4  # 400 + 400 + 400 + 300


def test_empty_dataset_handling(tmp_path: Path) -> None:
    with DatasetWriter(
        dataset_id="empty_dataset_01",
        name="Empty Dataset",
        kind=DatasetKind.TOP_OF_BOOK,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.top_of_book",
        root_dir=tmp_path,
    ) as _writer:
        pass  # write 0 rows

    reader = DatasetReader("empty_dataset_01", root_dir=tmp_path)
    assert reader.record_count == 0
    table = reader.read_table()
    assert table.num_rows == 0
    assert len(table.schema) > 0


def test_dataset_exists_error_and_overwrite(tmp_path: Path) -> None:
    generator = SyntheticMarketDataGenerator(seed=999)
    t = generator.generate_trades(count=50)

    # First write
    with DatasetWriter(
        dataset_id="dupe_test",
        name="Dupe Test",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(t)

    # Second write without overwrite=True must raise DatasetExistsError
    with pytest.raises(DatasetExistsError, match="already exists"):
        with DatasetWriter(
            dataset_id="dupe_test",
            name="Dupe Test",
            kind=DatasetKind.TRADES,
            domain=DataDomain.MARKET_DATA,
            schema_name="rexi.market_data.trade",
            root_dir=tmp_path,
            overwrite=False,
        ) as writer:
            writer.write_batch(t)

    # Third write with overwrite=True succeeds
    t2 = generator.generate_trades(count=75)
    with DatasetWriter(
        dataset_id="dupe_test",
        name="Dupe Test Overwritten",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
        overwrite=True,
    ) as writer:
        writer.write_batch(t2)

    reader = DatasetReader("dupe_test", root_dir=tmp_path)
    assert reader.record_count == 75


def test_path_traversal_rejection(tmp_path: Path) -> None:
    with pytest.raises(InvalidDatasetNameError, match="Path traversal"):
        DatasetWriter(
            dataset_id="../escape_path",
            name="Escape",
            kind=DatasetKind.TRADES,
            domain=DataDomain.MARKET_DATA,
            schema_name="rexi.market_data.trade",
            root_dir=tmp_path,
        )

    with pytest.raises(InvalidDatasetNameError, match="Invalid dataset ID"):
        DatasetWriter(
            dataset_id="invalid@name*with$special",
            name="Invalid Chars",
            kind=DatasetKind.TRADES,
            domain=DataDomain.MARKET_DATA,
            schema_name="rexi.market_data.trade",
            root_dir=tmp_path,
        )


def test_reader_non_existent_dataset_raises_error(tmp_path: Path) -> None:
    with pytest.raises(DatasetNotFoundError, match="not found"):
        DatasetReader("does_not_exist", root_dir=tmp_path)
