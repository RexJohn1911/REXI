"""Unit tests for Schema Registry, SchemaVersion, and canonical Arrow schemas."""

import pyarrow as pa
import pytest

from research.datasets.exceptions import SchemaMismatchError
from research.datasets.schema import (
    HEADER_FIELDS,
    ORDER_BOOK_SNAPSHOT_SCHEMA_V1,
    TOP_OF_BOOK_SCHEMA_V1,
    TRADE_SCHEMA_V1,
    SchemaVersion,
    get_schema_registry,
)


def test_schema_version_parsing_and_equality() -> None:
    v1 = SchemaVersion.from_str("1.2.3")
    assert v1.major == 1
    assert v1.minor == 2
    assert v1.patch == 3
    assert str(v1) == "1.2.3"

    v2 = SchemaVersion(1, 2, 3)
    assert v1 == v2

    with pytest.raises(ValueError, match="Invalid schema version string"):
        SchemaVersion.from_str("invalid_version")


def test_schema_version_compatibility_policy() -> None:
    base = SchemaVersion(1, 0, 0)
    minor_update = SchemaVersion(1, 1, 0)
    patch_update = SchemaVersion(1, 0, 1)
    major_bump = SchemaVersion(2, 0, 0)

    # Minor/patch updates within same major are backward compatible with base
    assert minor_update.is_compatible_with(base)
    assert patch_update.is_compatible_with(base)
    assert base.is_compatible_with(base)

    # Base is not compatible with higher minor requirements
    assert not base.is_compatible_with(minor_update)

    # Different major version breaks compatibility
    assert not major_bump.is_compatible_with(base)
    assert not base.is_compatible_with(major_bump)


def test_canonical_schemas_registration_in_global_registry() -> None:
    registry = get_schema_registry()
    schemas = registry.list_schemas()
    assert len(schemas) >= 7

    names = {s.name for s in schemas}
    assert "rexi.market_data.trade" in names
    assert "rexi.market_data.top_of_book" in names
    assert "rexi.market_data.order_book_update" in names
    assert "rexi.market_data.order_book_snapshot" in names
    assert "rexi.market_data.market_status" in names
    assert "rexi.market_data.instrument_definition" in names
    assert "rexi.replay.event" in names


def test_trade_schema_field_types_and_units() -> None:
    schema = TRADE_SCHEMA_V1
    assert schema.field("source_timestamp_ns").type == pa.int64()
    assert schema.field("receive_timestamp_ns").type == pa.int64()
    assert schema.field("sequence_num").type == pa.uint64()
    assert schema.field("venue_id").type == pa.uint16()
    assert schema.field("feed_id").type == pa.uint16()
    assert schema.field("instrument_id").type == pa.uint32()
    assert schema.field("trade_id").type == pa.uint64()
    # Ensure fixed-point price is int64, NOT float
    assert schema.field("price").type == pa.int64()
    assert schema.field("quantity").type == pa.uint64()
    assert schema.field("aggressor_side").type == pa.uint8()

    metadata = schema.metadata
    assert metadata[b"rexi.timestamp_unit"] == b"nanoseconds"
    assert metadata[b"rexi.price_unit"] == b"integer_tick_units"
    assert metadata[b"rexi.quantity_unit"] == b"integer_lots"


def test_top_of_book_schema_types() -> None:
    schema = TOP_OF_BOOK_SCHEMA_V1
    assert schema.field("best_bid_price").type == pa.int64()
    assert schema.field("best_bid_quantity").type == pa.uint64()
    assert schema.field("best_ask_price").type == pa.int64()
    assert schema.field("best_ask_quantity").type == pa.uint64()


def test_order_book_snapshot_nested_struct_levels() -> None:
    schema = ORDER_BOOK_SNAPSHOT_SCHEMA_V1
    bids_field = schema.field("bids")
    assert pa.types.is_list(bids_field.type)
    element_type = bids_field.type.value_type
    assert pa.types.is_struct(element_type)
    assert element_type.field("price").type == pa.int64()
    assert element_type.field("quantity").type == pa.uint64()
    assert element_type.field("order_count").type == pa.uint32()


def test_schema_registry_batch_validation_success() -> None:
    registry = get_schema_registry()
    data = {
        "version": [1],
        "message_type": [3],
        "flags": [0],
        "venue_id": [1],
        "feed_id": [1],
        "instrument_id": [100],
        "checksum": [12345],
        "sequence_num": [1],
        "source_timestamp_ns": [1_700_000_000_000_000_000],
        "receive_timestamp_ns": [1_700_000_000_000_500_000],
        "trade_id": [5000],
        "price": [105000],
        "quantity": [100],
        "aggressor_side": [1],
        "maker_order_id": [10],
        "taker_order_id": [20],
    }
    table = pa.Table.from_pydict(data, schema=TRADE_SCHEMA_V1)
    # Must succeed without throwing
    registry.validate_batch("rexi.market_data.trade", table)


def test_schema_registry_batch_validation_detects_mismatch() -> None:
    registry = get_schema_registry()
    # Missing required field 'trade_id'
    bad_schema = pa.schema(
        [
            *HEADER_FIELDS,
            pa.field("price", pa.int64(), nullable=False),
        ]
    )
    bad_table = pa.Table.from_pydict(
        {
            "version": [1],
            "message_type": [3],
            "flags": [0],
            "venue_id": [1],
            "feed_id": [1],
            "instrument_id": [100],
            "checksum": [0],
            "sequence_num": [1],
            "source_timestamp_ns": [1000],
            "receive_timestamp_ns": [2000],
            "price": [100],
        },
        schema=bad_schema,
    )
    with pytest.raises(SchemaMismatchError, match="Field count mismatch"):
        registry.validate_batch("rexi.market_data.trade", bad_table)


def test_unknown_schema_raises_error() -> None:
    registry = get_schema_registry()
    with pytest.raises(SchemaMismatchError, match="No schema registered"):
        registry.get("non_existent_schema")


def test_replay_schema_v1_and_v2_compatibility() -> None:
    registry = get_schema_registry()
    schema_v1 = registry.get("rexi.replay.event", "1.0.0")
    schema_v2 = registry.get("rexi.replay.event", "1.1.0")
    schema_default = registry.get("rexi.replay.event")

    # Default is the latest v1.1.0
    assert schema_default == schema_v2
    assert len(schema_v1) < len(schema_v2)

    # V1 does NOT contain snapshot fields
    v1_names = set(schema_v1.names)
    assert "last_included_sequence" not in v1_names
    assert "bids" not in v1_names
    assert "asks" not in v1_names

    # V2 strictly preserves snapshot fields
    v2_names = set(schema_v2.names)
    assert "last_included_sequence" in v2_names
    assert "bid_levels_count" in v2_names
    assert "ask_levels_count" in v2_names
    assert "bids" in v2_names
    assert "asks" in v2_names

    # Minor version 1.1.0 is backward-compatible with 1.0.0
    v1_ver = SchemaVersion(1, 0, 0)
    v2_ver = SchemaVersion(1, 1, 0)
    assert v2_ver.is_backward_compatible_with(v1_ver)

