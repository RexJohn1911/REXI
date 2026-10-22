"""Domain models, enums, and data structures for REXI Research Data Lake."""

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any


class DatasetKind(str, Enum):
    """Categorization of dataset content semantics."""

    RAW_MARKET_DATA = "raw_market_data"
    PROCESSED_TICKS = "processed_ticks"
    TOP_OF_BOOK = "top_of_book"
    TRADES = "trades"
    ORDER_BOOK_UPDATES = "order_book_updates"
    ORDER_BOOK_SNAPSHOTS = "order_book_snapshots"
    REPLAY_STREAM = "replay_stream"
    MARKET_STATUS = "market_status"
    INSTRUMENT_DEFINITIONS = "instrument_definitions"


class DataDomain(str, Enum):
    """Broad financial quantitative data domain."""

    MARKET_DATA = "market_data"
    ORDER_BOOK = "order_book"
    EXECUTION = "execution"
    REFERENCE = "reference"
    REPLAY = "replay"


class CompressionType(str, Enum):
    """Supported columnar file compression algorithms."""

    ZSTD = "zstd"
    SNAPPY = "snappy"
    GZIP = "gzip"
    UNCOMPRESSED = "none"


class ValidationStatus(str, Enum):
    """Dataset structural and cryptographic validation status."""

    VALID = "VALID"
    INVALID = "INVALID"
    UNVERIFIED = "UNVERIFIED"


class MarketSide(IntEnum):
    """Order and trade side direction matching C++ rexi::market_data::MarketSide."""

    BUY = 1
    SELL = 2


class TradingStatus(IntEnum):
    """Trading session status matching C++ rexi::market_data::TradingStatus."""

    UNKNOWN = 0
    PRE_OPEN = 1
    OPEN = 2
    HALTED = 3
    CLOSED = 4


class MarketDataMessageType(IntEnum):
    """Canonical message type discriminator matching C++ MarketDataMessageType."""

    UNKNOWN = 0
    INSTRUMENT_DEFINITION = 1
    TOP_OF_BOOK = 2
    TRADE = 3
    ORDER_BOOK_ADD = 4
    ORDER_BOOK_MODIFY = 5
    ORDER_BOOK_DELETE = 6
    ORDER_BOOK_SNAPSHOT = 7
    MARKET_STATUS = 8


@dataclass(frozen=True)
class TimeRange:
    """Nanosecond UNIX epoch time range bounded by dataset contents."""

    start_timestamp_ns: int = 0
    end_timestamp_ns: int = 0

    def is_valid(self) -> bool:
        """Check if time range is non-empty and logically ordered."""
        return self.start_timestamp_ns >= 0 and self.end_timestamp_ns >= self.start_timestamp_ns

    def duration_ns(self) -> int:
        """Return duration in nanoseconds."""
        return max(0, self.end_timestamp_ns - self.start_timestamp_ns)

    def duration_seconds(self) -> float:
        """Return duration in floating point seconds."""
        return self.duration_ns() / 1_000_000_000.0


@dataclass(frozen=True)
class ProvenanceInfo:
    """Lineage tracking how a dataset was generated or transformed."""

    source_files: list[str] = field(default_factory=list)
    source_dataset_id: str | None = None
    generator_name: str | None = None
    generator_version: str | None = None
    replay_state_digest: int | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert provenance metadata to serializable dictionary."""
        return {
            "source_files": list(self.source_files),
            "source_dataset_id": self.source_dataset_id,
            "generator_name": self.generator_name,
            "generator_version": self.generator_version,
            "replay_state_digest": (
                f"0x{self.replay_state_digest:016x}"
                if self.replay_state_digest is not None
                else None
            ),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProvenanceInfo":
        """Reconstruct ProvenanceInfo from dictionary."""
        digest_raw = data.get("replay_state_digest")
        digest_val: int | None = None
        if isinstance(digest_raw, str) and digest_raw.startswith("0x"):
            digest_val = int(digest_raw, 16)
        elif isinstance(digest_raw, int):
            digest_val = digest_raw

        return cls(
            source_files=list(data.get("source_files", [])),
            source_dataset_id=data.get("source_dataset_id"),
            generator_name=data.get("generator_name"),
            generator_version=data.get("generator_version"),
            replay_state_digest=digest_val,
            notes=data.get("notes"),
        )


@dataclass(frozen=True)
class DatasetIdentity:
    """Logical identity and schema binding of a research dataset."""

    dataset_id: str
    name: str
    kind: DatasetKind
    domain: DataDomain
    schema_name: str
    schema_version: str


@dataclass(frozen=True)
class DatasetMetadata:
    """Complete descriptive metadata for a dataset."""

    identity: DatasetIdentity
    time_range: TimeRange
    record_count: int
    partition_count: int
    total_byte_size: int
    instruments: list[int]
    venues: list[int]
    feeds: list[int]
    dates: list[str]
    provenance: ProvenanceInfo
    compression: CompressionType
    created_at_utc: str
