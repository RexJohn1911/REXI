"""REXI Quantitative Research Data Lake Subsystem.

Provides local, deterministic, schema-aware storage and retrieval of historical quantitative
research datasets centered on Apache Arrow and Parquet.
"""

from research.datasets.catalog import DatasetCatalog
from research.datasets.exceptions import (
    DataLakeError,
    DatasetExistsError,
    DatasetIntegrityError,
    DatasetNotFoundError,
    IncompleteDatasetError,
    InvalidDatasetNameError,
    SchemaMismatchError,
)
from research.datasets.generator import SyntheticMarketDataGenerator
from research.datasets.manifest import (
    DatasetManifest,
    PartitionFile,
    compute_file_sha256,
    verify_file_sha256,
)
from research.datasets.reader import DatasetReader
from research.datasets.schema import (
    INSTRUMENT_DEFINITION_SCHEMA_V1,
    MARKET_STATUS_SCHEMA_V1,
    ORDER_BOOK_SNAPSHOT_SCHEMA_V1,
    ORDER_BOOK_UPDATE_SCHEMA_V1,
    REPLAY_EVENT_SCHEMA_V1,
    TOP_OF_BOOK_SCHEMA_V1,
    TRADE_SCHEMA_V1,
    RegisteredSchema,
    SchemaRegistry,
    SchemaVersion,
    get_schema_registry,
)
from research.datasets.types import (
    CompressionType,
    DataDomain,
    DatasetIdentity,
    DatasetKind,
    DatasetMetadata,
    MarketDataMessageType,
    MarketSide,
    ProvenanceInfo,
    TimeRange,
    TradingStatus,
    ValidationStatus,
)
from research.datasets.writer import DatasetWriter

__all__ = [
    "INSTRUMENT_DEFINITION_SCHEMA_V1",
    "MARKET_STATUS_SCHEMA_V1",
    "ORDER_BOOK_SNAPSHOT_SCHEMA_V1",
    "ORDER_BOOK_UPDATE_SCHEMA_V1",
    "REPLAY_EVENT_SCHEMA_V1",
    "TOP_OF_BOOK_SCHEMA_V1",
    "TRADE_SCHEMA_V1",
    "CompressionType",
    "DataDomain",
    "DataLakeError",
    "DatasetCatalog",
    "DatasetExistsError",
    "DatasetIdentity",
    "DatasetIntegrityError",
    "DatasetKind",
    "DatasetManifest",
    "DatasetMetadata",
    "DatasetNotFoundError",
    "DatasetReader",
    "DatasetWriter",
    "IncompleteDatasetError",
    "InvalidDatasetNameError",
    "MarketDataMessageType",
    "MarketSide",
    "PartitionFile",
    "ProvenanceInfo",
    "RegisteredSchema",
    "SchemaMismatchError",
    "SchemaRegistry",
    "SchemaVersion",
    "SyntheticMarketDataGenerator",
    "TimeRange",
    "TradingStatus",
    "ValidationStatus",
    "compute_file_sha256",
    "get_schema_registry",
    "verify_file_sha256",
]

