"""PyArrow schema definitions and versioned SchemaRegistry for REXI research data lake."""

from dataclasses import dataclass
from typing import Any

import pyarrow as pa

from research.datasets.exceptions import IncompatibleSchemaError, SchemaMismatchError

# -----------------------------------------------------------------------------
# Common Metadata and Headers
# -----------------------------------------------------------------------------
METADATA_COMMON = {
    b"rexi.engine": b"REXI Research Data Lake",
    b"rexi.spec_version": b"1.0.0",
    b"rexi.timestamp_unit": b"nanoseconds",
    b"rexi.price_unit": b"integer_tick_units",
    b"rexi.quantity_unit": b"integer_lots",
}

HEADER_FIELDS = [
    pa.field("version", pa.uint8(), nullable=False),
    pa.field("message_type", pa.uint8(), nullable=False),
    pa.field("flags", pa.uint16(), nullable=False),
    pa.field("venue_id", pa.uint16(), nullable=False),
    pa.field("feed_id", pa.uint16(), nullable=False),
    pa.field("instrument_id", pa.uint32(), nullable=False),
    pa.field("checksum", pa.uint16(), nullable=False),
    pa.field("sequence_num", pa.uint64(), nullable=False),
    pa.field("source_timestamp_ns", pa.int64(), nullable=False),
    pa.field("receive_timestamp_ns", pa.int64(), nullable=False),
]

LEVEL_STRUCT = pa.struct(
    [
        pa.field("price", pa.int64(), nullable=False),
        pa.field("quantity", pa.uint64(), nullable=False),
        pa.field("order_count", pa.uint32(), nullable=False),
    ]
)

# -----------------------------------------------------------------------------
# Canonical Phase 04 Trade Schema
# -----------------------------------------------------------------------------
TRADE_SCHEMA_V1 = pa.schema(
    [
        *HEADER_FIELDS,
        pa.field("trade_id", pa.uint64(), nullable=False),
        pa.field("price", pa.int64(), nullable=False),
        pa.field("quantity", pa.uint64(), nullable=False),
        pa.field("aggressor_side", pa.uint8(), nullable=False),
        pa.field("maker_order_id", pa.uint64(), nullable=False),
        pa.field("taker_order_id", pa.uint64(), nullable=False),
    ],
    metadata={
        **METADATA_COMMON,
        b"rexi.schema_name": b"rexi.market_data.trade",
        b"rexi.schema_version": b"1.0.0",
    },
)

# -----------------------------------------------------------------------------
# Canonical Phase 04 Top of Book (BBO) Schema
# -----------------------------------------------------------------------------
TOP_OF_BOOK_SCHEMA_V1 = pa.schema(
    [
        *HEADER_FIELDS,
        pa.field("best_bid_price", pa.int64(), nullable=False),
        pa.field("best_bid_quantity", pa.uint64(), nullable=False),
        pa.field("best_ask_price", pa.int64(), nullable=False),
        pa.field("best_ask_quantity", pa.uint64(), nullable=False),
    ],
    metadata={
        **METADATA_COMMON,
        b"rexi.schema_name": b"rexi.market_data.top_of_book",
        b"rexi.schema_version": b"1.0.0",
    },
)

# -----------------------------------------------------------------------------
# Canonical Phase 04 L3 Order Book Update Schema
# -----------------------------------------------------------------------------
ORDER_BOOK_UPDATE_SCHEMA_V1 = pa.schema(
    [
        *HEADER_FIELDS,
        pa.field("action", pa.uint8(), nullable=False),
        pa.field("order_id", pa.uint64(), nullable=False),
        pa.field("side", pa.uint8(), nullable=False),
        pa.field("price", pa.int64(), nullable=False),
        pa.field("quantity", pa.uint64(), nullable=False),
        pa.field("priority_rank", pa.uint32(), nullable=True),
        pa.field("delta_quantity", pa.uint64(), nullable=True),
    ],
    metadata={
        **METADATA_COMMON,
        b"rexi.schema_name": b"rexi.market_data.order_book_update",
        b"rexi.schema_version": b"1.0.0",
    },
)

# -----------------------------------------------------------------------------
# Canonical Phase 04 L2 Order Book Depth Snapshot Schema
# -----------------------------------------------------------------------------
ORDER_BOOK_SNAPSHOT_SCHEMA_V1 = pa.schema(
    [
        *HEADER_FIELDS,
        pa.field("last_included_sequence", pa.uint64(), nullable=False),
        pa.field("bid_levels_count", pa.uint32(), nullable=False),
        pa.field("ask_levels_count", pa.uint32(), nullable=False),
        pa.field("bids", pa.list_(LEVEL_STRUCT), nullable=False),
        pa.field("asks", pa.list_(LEVEL_STRUCT), nullable=False),
    ],
    metadata={
        **METADATA_COMMON,
        b"rexi.schema_name": b"rexi.market_data.order_book_snapshot",
        b"rexi.schema_version": b"1.0.0",
    },
)

# -----------------------------------------------------------------------------
# Canonical Phase 04 Market Status Schema
# -----------------------------------------------------------------------------
MARKET_STATUS_SCHEMA_V1 = pa.schema(
    [
        *HEADER_FIELDS,
        pa.field("status", pa.uint8(), nullable=False),
        pa.field("status_flags", pa.uint32(), nullable=False),
    ],
    metadata={
        **METADATA_COMMON,
        b"rexi.schema_name": b"rexi.market_data.market_status",
        b"rexi.schema_version": b"1.0.0",
    },
)

# -----------------------------------------------------------------------------
# Canonical Phase 04 Instrument Definition Schema
# -----------------------------------------------------------------------------
INSTRUMENT_DEFINITION_SCHEMA_V1 = pa.schema(
    [
        *HEADER_FIELDS,
        pa.field("tick_size", pa.int64(), nullable=False),
        pa.field("lot_size", pa.uint64(), nullable=False),
        pa.field("min_quantity", pa.uint64(), nullable=False),
        pa.field("max_quantity", pa.uint64(), nullable=False),
    ],
    metadata={
        **METADATA_COMMON,
        b"rexi.schema_name": b"rexi.market_data.instrument_definition",
        b"rexi.schema_version": b"1.0.0",
    },
)

# -----------------------------------------------------------------------------
# Canonical Phase 07 Unified Replay Stream Schema V1 (Baseline, v1.0.0)
# Preserved strictly immutable for backwards compatibility.
# -----------------------------------------------------------------------------
_REPLAY_FIELDS_V1 = [
    *HEADER_FIELDS,
    pa.field("source", pa.uint8(), nullable=False),
    pa.field("input_index", pa.uint64(), nullable=False),
    pa.field("order_id", pa.uint64(), nullable=True),
    pa.field("side", pa.uint8(), nullable=True),
    pa.field("price", pa.int64(), nullable=True),
    pa.field("quantity", pa.uint64(), nullable=True),
    pa.field("trade_id", pa.uint64(), nullable=True),
    pa.field("aggressor_side", pa.uint8(), nullable=True),
    pa.field("maker_order_id", pa.uint64(), nullable=True),
    pa.field("taker_order_id", pa.uint64(), nullable=True),
    pa.field("best_bid_price", pa.int64(), nullable=True),
    pa.field("best_bid_quantity", pa.uint64(), nullable=True),
    pa.field("best_ask_price", pa.int64(), nullable=True),
    pa.field("best_ask_quantity", pa.uint64(), nullable=True),
    pa.field("priority_rank", pa.uint32(), nullable=True),
    pa.field("delta_quantity", pa.uint64(), nullable=True),
    pa.field("status", pa.uint8(), nullable=True),
    pa.field("status_flags", pa.uint32(), nullable=True),
    pa.field("tick_size", pa.int64(), nullable=True),
    pa.field("lot_size", pa.uint64(), nullable=True),
    pa.field("min_quantity", pa.uint64(), nullable=True),
    pa.field("max_quantity", pa.uint64(), nullable=True),
]

REPLAY_EVENT_SCHEMA_V1 = pa.schema(
    _REPLAY_FIELDS_V1,
    metadata={
        **METADATA_COMMON,
        b"rexi.schema_name": b"rexi.replay.event",
        b"rexi.schema_version": b"1.0.0",
    },
)

# -----------------------------------------------------------------------------
# Canonical Phase 07 Unified Replay Stream Schema V2 (v1.1.0)
# Extends v1.0.0 with full OrderBookSnapshotMessage payload fidelity.
# -----------------------------------------------------------------------------
REPLAY_EVENT_SCHEMA_V2 = pa.schema(
    [
        *_REPLAY_FIELDS_V1,
        pa.field("last_included_sequence", pa.uint64(), nullable=True),
        pa.field("bid_levels_count", pa.uint32(), nullable=True),
        pa.field("ask_levels_count", pa.uint32(), nullable=True),
        pa.field("bids", pa.list_(LEVEL_STRUCT), nullable=True),
        pa.field("asks", pa.list_(LEVEL_STRUCT), nullable=True),
    ],
    metadata={
        **METADATA_COMMON,
        b"rexi.schema_name": b"rexi.replay.event",
        b"rexi.schema_version": b"1.1.0",
    },
)


@dataclass(frozen=True)
class RegisteredSchema:
    """Record of a schema registered in the catalog."""

    name: str
    version: "SchemaVersion"
    schema: pa.Schema
    description: str


class SchemaVersion:
    """Semantic version for research dataset schemas."""

    def __init__(self, major: int, minor: int, patch: int = 0) -> None:
        self.major = int(major)
        self.minor = int(minor)
        self.patch = int(patch)

    @classmethod
    def from_str(cls, ver_str: str) -> "SchemaVersion":
        parts = ver_str.strip().split(".")
        if len(parts) == 2:
            return cls(int(parts[0]), int(parts[1]), 0)
        if len(parts) == 3:
            return cls(int(parts[0]), int(parts[1]), int(parts[2]))
        raise ValueError(f"Invalid schema version string: '{ver_str}'")

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __repr__(self) -> str:
        return f"SchemaVersion({self.major}, {self.minor}, {self.patch})"

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, SchemaVersion):
            return False
        return (
            self.major == other.major
            and self.minor == other.minor
            and self.patch == other.patch
        )

    def __hash__(self) -> int:
        return hash((self.major, self.minor, self.patch))

    def is_backward_compatible_with(self, other: "SchemaVersion") -> bool:
        """True if self is backward compatible with required version other."""
        if self.major != other.major:
            return False
        return self.minor >= other.minor

    is_compatible_with = is_backward_compatible_with


class SchemaRegistry:
    """Thread-safe registry for validated dataset schemas and version compatibility."""

    def __init__(self) -> None:
        self._schemas: dict[tuple[str, str], RegisteredSchema] = {}
        self._latest: dict[str, SchemaVersion] = {}

    def register(
        self,
        name: str,
        version: SchemaVersion | str,
        schema: pa.Schema,
        description: str = "",
    ) -> None:
        """Register a schema with a specific version string."""
        ver = SchemaVersion.from_str(str(version)) if isinstance(version, str) else version
        key = (name, str(ver))

        curr_latest = self._latest.get(name)
        if curr_latest is not None:
            if ver.major < curr_latest.major or (
                ver.major == curr_latest.major and ver.minor < curr_latest.minor
            ):
                pass
            else:
                self._latest[name] = ver
        else:
            self._latest[name] = ver

        self._schemas[key] = RegisteredSchema(
            name=name,
            version=ver,
            schema=schema,
            description=description,
        )

    def get(
        self, name: str, version: SchemaVersion | str | None = None
    ) -> pa.Schema:
        """Retrieve registered schema by name and optional version."""
        if version is None:
            latest_ver = self._latest.get(name)
            if latest_ver is None:
                raise SchemaMismatchError(f"No schema registered with name '{name}'")
            return self._schemas[(name, str(latest_ver))].schema

        ver_obj = SchemaVersion.from_str(str(version)) if isinstance(version, str) else version
        key = (name, str(ver_obj))
        if key in self._schemas:
            return self._schemas[key].schema

        # Check compatibility with latest
        latest_ver = self._latest.get(name)
        if latest_ver and latest_ver.is_backward_compatible_with(ver_obj):
            return self._schemas[(name, str(latest_ver))].schema

        raise IncompatibleSchemaError(
            f"Schema '{name}' version '{ver_obj}' is not compatible with registered "
            f"versions for '{name}'."
        )

    def get_registered(
        self, name: str, version: SchemaVersion | str | None = None
    ) -> RegisteredSchema:
        """Retrieve RegisteredSchema object."""
        if version is None:
            latest_ver = self._latest.get(name)
            if latest_ver is None:
                raise SchemaMismatchError(f"No schema registered with name '{name}'")
            return self._schemas[(name, str(latest_ver))]

        ver_obj = SchemaVersion.from_str(str(version)) if isinstance(version, str) else version
        key = (name, str(ver_obj))
        if key not in self._schemas:
            raise SchemaMismatchError(f"Schema '{name}' version '{ver_obj}' not found in registry.")
        return self._schemas[key]

    def list_schemas(self) -> list[RegisteredSchema]:
        """List all currently registered schemas."""
        return list(self._schemas.values())

    def validate_batch(
        self,
        name: str,
        batch: pa.RecordBatch | pa.Table,
        version: SchemaVersion | str | None = None,
    ) -> None:
        """Validate that a record batch or table strictly conforms to the registered schema."""
        expected_schema = self.get(name, version)
        batch_schema = batch.schema

        if len(batch_schema) != len(expected_schema):
            raise SchemaMismatchError(
                f"Field count mismatch for '{name}': expected {len(expected_schema)} fields, "
                f"got {len(batch_schema)}"
            )

        for i, expected_field in enumerate(expected_schema):
            actual_field = batch_schema[i]
            if actual_field.name != expected_field.name:
                raise SchemaMismatchError(
                    f"Field name mismatch at index {i} in '{name}': "
                    f"expected '{expected_field.name}', got '{actual_field.name}'"
                )
            if actual_field.type != expected_field.type:
                raise SchemaMismatchError(
                    f"Field type mismatch for '{actual_field.name}' in '{name}': expected "
                    f"{expected_field.type}, got {actual_field.type}"
                )


_GLOBAL_REGISTRY: SchemaRegistry | None = None


def get_schema_registry() -> SchemaRegistry:
    """Retrieve global populated SchemaRegistry instance."""
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        registry = SchemaRegistry()
        v1 = SchemaVersion(1, 0, 0)
        v1_1 = SchemaVersion(1, 1, 0)

        registry.register(
            "rexi.market_data.trade",
            v1,
            TRADE_SCHEMA_V1,
            "Canonical public executed trade messages (Phase 04)",
        )
        registry.register(
            "rexi.market_data.top_of_book",
            v1,
            TOP_OF_BOOK_SCHEMA_V1,
            "Canonical Best Bid and Offer (BBO) quotes (Phase 04)",
        )
        registry.register(
            "rexi.market_data.order_book_update",
            v1,
            ORDER_BOOK_UPDATE_SCHEMA_V1,
            "Canonical L3 order book additions, modifications, cancellations (Phase 04)",
        )
        registry.register(
            "rexi.market_data.order_book_snapshot",
            v1,
            ORDER_BOOK_SNAPSHOT_SCHEMA_V1,
            "Canonical L2 multi-level depth snapshots (Phase 04)",
        )
        registry.register(
            "rexi.market_data.market_status",
            v1,
            MARKET_STATUS_SCHEMA_V1,
            "Canonical trading session status events (Phase 04)",
        )
        registry.register(
            "rexi.market_data.instrument_definition",
            v1,
            INSTRUMENT_DEFINITION_SCHEMA_V1,
            "Canonical instrument reference tick & lot parameters (Phase 04)",
        )
        registry.register(
            "rexi.replay.event",
            v1,
            REPLAY_EVENT_SCHEMA_V1,
            "Canonical unified historical market replay stream baseline (Phase 07 v1.0.0)",
        )
        registry.register(
            "rexi.replay.event",
            v1_1,
            REPLAY_EVENT_SCHEMA_V2,
            "Canonical unified replay stream with OrderBookSnapshotMessage (Phase 07 v1.1.0)",
        )
        _GLOBAL_REGISTRY = registry
    return _GLOBAL_REGISTRY
