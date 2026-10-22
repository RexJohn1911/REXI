"""PyArrow schema definitions for microstructure feature datasets."""

from typing import Any

import pyarrow as pa

from research.datasets.schema import METADATA_COMMON

MICROSTRUCTURE_FEATURES_SCHEMA_V1 = pa.schema(
    [
        # Identifiers & Timestamps
        pa.field("instrument_id", pa.uint32(), nullable=False),
        pa.field("sequence_num", pa.uint64(), nullable=False),
        pa.field("event_timestamp_ns", pa.int64(), nullable=False),
        pa.field("source_timestamp_ns", pa.int64(), nullable=False),
        pa.field("decision_timestamp_ns", pa.int64(), nullable=False),
        # Level 1 BBO
        pa.field("best_bid_price", pa.int64(), nullable=True),
        pa.field("best_bid_quantity", pa.uint64(), nullable=True),
        pa.field("best_ask_price", pa.int64(), nullable=True),
        pa.field("best_ask_quantity", pa.uint64(), nullable=True),
        pa.field("spread", pa.int64(), nullable=True),
        pa.field("relative_spread", pa.float64(), nullable=True),
        pa.field("mid_price", pa.float64(), nullable=True),
        pa.field("weighted_mid_price", pa.float64(), nullable=True),
        pa.field("book_imbalance_top", pa.float64(), nullable=True),
        # Level 2 Depth & Imbalance
        pa.field("bid_depth_k", pa.uint64(), nullable=True),
        pa.field("ask_depth_k", pa.uint64(), nullable=True),
        pa.field("depth_imbalance_k", pa.float64(), nullable=True),
        # Order Flow Imbalance
        pa.field("instant_ofi", pa.int64(), nullable=True),
        pa.field("rolling_ofi", pa.int64(), nullable=True),
        # Trade Flow
        pa.field("last_signed_volume", pa.int64(), nullable=True),
        pa.field("rolling_trade_volume", pa.uint64(), nullable=True),
        pa.field("rolling_buy_volume", pa.uint64(), nullable=True),
        pa.field("rolling_sell_volume", pa.uint64(), nullable=True),
        pa.field("trade_flow_imbalance", pa.float64(), nullable=True),
        pa.field("rolling_vwap", pa.float64(), nullable=True),
        # Short-Horizon Returns & Volatility
        pa.field("log_return", pa.float64(), nullable=True),
        pa.field("realized_volatility", pa.float64(), nullable=True),
        # Advanced Microstructure Models
        pa.field("roll_spread", pa.float64(), nullable=True),
        pa.field("vpin", pa.float64(), nullable=True),
        # Explicit Feature Validity Booleans
        pa.field("has_bid", pa.bool_(), nullable=False),
        pa.field("has_ask", pa.bool_(), nullable=False),
        pa.field("is_crossed", pa.bool_(), nullable=False),
        pa.field("has_spread", pa.bool_(), nullable=False),
        pa.field("has_mid", pa.bool_(), nullable=False),
        pa.field("has_weighted_mid", pa.bool_(), nullable=False),
        pa.field("has_book_imbalance", pa.bool_(), nullable=False),
        pa.field("has_depth_imbalance", pa.bool_(), nullable=False),
        pa.field("has_instant_ofi", pa.bool_(), nullable=False),
        pa.field("has_rolling_ofi", pa.bool_(), nullable=False),
        pa.field("has_trade", pa.bool_(), nullable=False),
        pa.field("has_trade_flow", pa.bool_(), nullable=False),
        pa.field("has_vwap", pa.bool_(), nullable=False),
        pa.field("has_log_return", pa.bool_(), nullable=False),
        pa.field("has_realized_volatility", pa.bool_(), nullable=False),
        pa.field("has_roll_spread", pa.bool_(), nullable=False),
        pa.field("has_vpin", pa.bool_(), nullable=False),
    ],
    metadata={
        **METADATA_COMMON,
        b"rexi.schema_name": b"rexi.features.microstructure",
        b"rexi.schema_version": b"1.0.0",
    },
)


def register_microstructure_schemas(registry: Any = None) -> Any:
    """Register MICROSTRUCTURE_FEATURES_SCHEMA_V1 in the SchemaRegistry."""
    from research.datasets.exceptions import SchemaMismatchError
    from research.datasets.schema import SchemaVersion, get_schema_registry

    reg = registry or get_schema_registry()
    v1 = SchemaVersion(1, 0, 0)
    try:
        reg.get("rexi.features.microstructure", v1)
    except (SchemaMismatchError, KeyError):
        reg.register(
            "rexi.features.microstructure",
            v1,
            MICROSTRUCTURE_FEATURES_SCHEMA_V1,
            "Canonical microstructure feature engine output (Phase 10 v1.0.0)",
        )
    return reg
