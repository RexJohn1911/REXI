# REXI Research Data Lake Architecture

## 1. Executive Summary

Phase 08 establishes the canonical **Research Data Lake Subsystem** for REXI. The data lake provides local, deterministic, schema-aware, columnar storage and streaming retrieval of historical quantitative research datasets, centered on Apache Arrow and Apache Parquet.

The research data lake is a foundational storage and data engineering tier. It is strictly:
- **A local, high-throughput, schema-enforced dataset repository** for tick-level and order-book quantitative time series.
- **Causally aligned** with Phase 04 binary market-data protocol definitions and Phase 07 historical replay stream envelopes.
- **NOT a backtesting engine or no-leakage validator** (temporal causality rules, cross-validation, and lookahead detection are deferred to Phase 09).
- **NOT a feature engineering framework** (microstructure indicators, OFI, and VPIN are deferred to Phase 10).
- **NOT a cloud storage or distributed compute system** (operates on the local filesystem without external database or cloud service dependencies).

---

## 2. Core Architecture & Pipeline

```
+-------------------------------------------------------------------------+
|                  Phase 04 / Phase 07 Market Data Records                 |
|       (Trades, BBO Quotes, L3 Updates, Depth Snapshots, Replay Events)   |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                           Schema Registry                               |
|   - Versioned Arrow schemas (e.g. rexi.market_data.trade v1.0.0)        |
|   - Strict type checking: int64 prices, uint64 quantities, int64 ns      |
|   - Semantic versioning compatibility rules (major/minor/patch)         |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|              Safe DatasetWriter (Staging & Concurrency Lock)            |
|   - Non-blocking process file lock (.lock_{dataset_id}) via flock       |
|   - Path traversal prevention & safe dataset naming (validate_rel_path)  |
|   - Writes to staging directory: .staging_{dataset_id}_{uuid}            |
|   - Arrow-native stats (pc.unique) & native grouping without py-dicts   |
|   - Columnar Parquet writer with ZSTD / Snappy dictionary encoding      |
|   - Optional Hive-style partitioning (e.g., date, instrument_id)        |
|   - Bounded batch writes without accumulating full dataset in RAM       |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                      Manifest & Integrity Verification                   |
|   - Calculates SHA-256 cryptographic checksums per partition file       |
|   - Audits exact record counts, byte sizes, and column statistics       |
|   - Deep Parquet metadata inspection: verifies physical num_rows        |
|   - Rejects duplicate partitions, path escapes, and count mismatches    |
|   - Records full provenance (source files, generator, replay digest)    |
|   - Serializes canonical manifest.json (v1.0.0) with sorted keys         |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|           3-Phase Transactional Publication with Rollback               |
|   - If replacement: Phase 1: os.replace(target, backup)                 |
|                     Phase 2: os.replace(staging, target)                |
|                     Phase 3: purge backup on success; rollback on error |
|   - Guarantees previously valid datasets are never deleted on failure   |
|   - Incomplete writes are never discoverable in catalog                 |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                   DatasetCatalog & Streaming DatasetReader              |
|   - Catalog lists valid, complete datasets in data repository           |
|   - Partition filtering by metadata dimensions (date, instrument_id)    |
|   - Strict containment check: resolve_partition_path guards all reads   |
|   - Bounded streaming batch iterator (read_batch_iter) in small chunks  |
|   - Cryptographic SHA-256 + Parquet structure integrity verification    |
+-------------------------------------------------------------------------+
```

---

## 3. Schema Registry & Numerical Representations

### A. Strict Data Typing & Precision Invariants
To eliminate precision loss and undocumented type coercion:
1. **Prices**: Encoded strictly as 64-bit signed integers (`pa.int64()`) representing fixed-point integer tick units. Converting prices to IEEE-754 floating point numbers is strictly prohibited.
2. **Quantities**: Encoded as 64-bit unsigned integers (`pa.uint64()`) representing discrete lot units.
3. **Timestamps**: Encoded as 64-bit signed integers (`pa.int64()`) representing nanoseconds since UNIX epoch (1970-01-01T00:00:00Z UTC).
4. **Sequence Numbers & IDs**: Preserved as exact integers (`uint64`, `uint32`, `uint16`).
5. **Enums**: Preserved as canonical numeric values matching C++ enums:
   - `MarketSide`: Buy = 1, Sell = 2.
   - `TradingStatus`: Unknown = 0, PreOpen = 1, Open = 2, Halted = 3, Closed = 4.
   - `MarketDataMessageType`: Matching Phase 04 discriminator values.

### B. Registered Canonical Schemas
The global `SchemaRegistry` maintains versioned definitions for:
- `rexi.market_data.trade` (v1.0.0): Executed public trade prints.
- `rexi.market_data.top_of_book` (v1.0.0): Best Bid and Offer (BBO) quotes.
- `rexi.market_data.order_book_update` (v1.0.0): L3 Add, Modify, and Delete events.
- `rexi.market_data.order_book_snapshot` (v1.0.0): L2 depth snapshot with nested price level structs.
- `rexi.market_data.market_status` (v1.0.0): Operational session state transitions.
- `rexi.market_data.instrument_definition` (v1.0.0): Reference parameters (tick size, lot size).
- `rexi.replay.event` (v1.0.0): Unified historical market replay stream envelope matching Phase 07, including full `OrderBookSnapshotMessage` payload fields (`last_included_sequence`, `bid_levels_count`, `ask_levels_count`, `bids`, `asks`).

---

## 4. Dataset Layout, Partitioning, and Manifest

### A. Repository Directory Layout
Datasets are stored within the canonical repository hierarchy:
- `data/raw/`: Preserved raw input captures (immutable source data).
- `data/processed/`: Normalized, validated research datasets stored in partitioned Parquet format.
- `data/sample/`: Small synthetic test fixtures and baseline sample datasets.
- `research/datasets/`: Data lake library code, schema registry, manifests, writer, reader, and catalog.

### B. Partitioning Convention
Partitioned datasets organize Parquet files into deterministic subdirectories:
```
{root_dir}/{dataset_id}/
├── manifest.json
├── date=2026-10-22/
│   ├── instrument_id=1/
│   │   └── part-00000.parquet
│   └── instrument_id=2/
│       └── part-00001.parquet
└── date=2026-10-23/
    └── instrument_id=1/
        └── part-00002.parquet
```
All partition dimensions are also retained as explicit columns within the Parquet files to ensure self-contained schema validity and avoid dependency on directory naming.

### C. Manifest Specification (`manifest.json` v1.0.0)
Every completed dataset contains a `manifest.json` with sorted keys and indentation:
- `manifest_version`: Version of manifest specification (`"1.0.0"`).
- `dataset_id`: Unique alphanumeric identifier (validated against `^[a-zA-Z0-9_\-]+$`).
- `schema_name` and `schema_version`: Precise schema binding.
- `created_at_utc`: ISO-8601 creation timestamp.
- `time_range`: Explicit `start_timestamp_ns` and `end_timestamp_ns`.
- `record_count` and `partition_count`: Verified summary counts.
- `total_byte_size`: Cumulative byte size of all Parquet partitions.
- `partitions`: Array of `PartitionFile` objects containing relative path, record count, byte size, SHA-256 checksum, min/max timestamps, and min/max sequence numbers.
- `provenance`: Lineage metadata tracking source files, generator version, and the Phase 07 `replay_state_digest` (64-bit FNV-1a integer).
- `is_complete`: Boolean flag set to `true` only upon successful finalization.

### D. Path Security & Traversal Guards
- All partition paths are strictly validated through `validate_relative_path` and `resolve_partition_path`.
- Paths starting with `/`, containing `..` or `.`, containing null bytes, or resolving to targets outside the dataset root directory (including malicious symlinks) are strictly rejected with `DatasetIntegrityError`.
- Manifest deserialization rejects duplicate partition paths and enforces internal count and byte-size consistency.

---

## 5. Safe, Atomic Write Lifecycle & Recovery

1. **Validation & Locking**: Dataset identity and partition columns are validated before touching disk. An exclusive non-blocking process file lock (`.lock_{dataset_id}`) is acquired via `fcntl.flock`.
2. **Staging**: An isolated staging directory `.staging_{dataset_id}_{uuid}` is created inside `root_dir` (guaranteeing the same filesystem as the target).
3. **Bounded Streaming & Arrow-Native Aggregation**: Batches are written through `pq.ParquetWriter` with dictionary encoding and ZSTD compression. Statistics and partitioning are computed natively via Arrow C++ compute kernels (`pc.unique` and `Table.group_by().aggregate([])`), avoiding full-batch Python dictionary allocations.
4. **Finalization**: Writers are closed, and SHA-256 checksums, byte sizes, and row counts are audited.
5. **Manifest Generation**: `manifest.json` is generated directly in the staging directory.
6. **3-Phase Transactional Publication**:
   - If target does not exist: `os.replace(staging_dir, target_dir)` atomically publishes the dataset.
   - If target exists and `overwrite=True`:
     1. `Phase 1 (Backup)`: `os.replace(target_dir, backup_dir)` moves the existing valid dataset to a temporary backup directory.
     2. `Phase 2 (Promote)`: `os.replace(staging_dir, target_dir)` moves the new staging dataset into place.
     3. `Phase 3 (Cleanup / Rollback)`: If promote succeeds, `backup_dir` is purged. If promote fails, `backup_dir` is rolled back to `target_dir`, preserving the original valid dataset intact.
7. **Reader Isolation**: POSIX file descriptors already opened by active readers remain valid and readable across directory renames and unlinks.
8. **Stale Cleanup**: `DatasetCatalog.clean_stale_staging(max_age_seconds)` automatically purges orphaned `.staging_*` and `.backup_*` artifacts.

---

## 6. Language & Integration Boundary

- **Production C++ Engine (Phases 01–07)**: Remains zero-allocation, native C++ with 0 runtime Python dependencies (`CON-0004`).
- **Research Data Lake (Phase 08)**: Implemented in Python using Apache Arrow (`pyarrow`), providing native interoperability with quantitative research ecosystems.
- **Bridge to Historical Replay (Phase 07)**: `SyntheticMarketDataGenerator` and `DatasetReader` support the unified `rexi.replay.event` schema. Replay stream outputs can be serialized to Parquet with Phase 07 `replay_state_digest` in the manifest provenance, guaranteeing bit-for-bit reproducibility.

---

## 7. Performance Benchmarks

Measured on Apple Silicon (macOS arm64, Python 3.13.9, PyArrow 21.0.0):

| Benchmark Operation | Dataset Size / Batch Size | Elapsed Time | Throughput | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Write Parquet (ZSTD)** | 10,000 records | 3.22 ms | **3,102,418 rec/s** (62.4 MB/s) | Compressed size: 0.20 MB |
| **Write Parquet (ZSTD)** | 100,000 records | 19.42 ms | **5,149,563 rec/s** (147.0 MB/s) | Arrow-native stats, no py-dicts |
| **Streaming Read (Iter)** | 100,000 records (batch=1k) | 7.16 ms | **13,972,661 rec/s** | Bounded streaming iterator |
| **Streaming Read (Iter)** | 100,000 records (batch=10k) | 2.15 ms | **46,550,428 rec/s** | Bounded streaming iterator |
| **Streaming Read (Iter)** | 100,000 records (batch=50k) | 2.06 ms | **48,503,450 rec/s** | Bounded streaming iterator |
| **Cryptographic Integrity Audit** | 100,000 records (SHA-256 + Parquet) | 1.127 ms | **887 audits/s** | Full physical SHA-256 + row scan |
| **Catalog Metadata Discovery** | 14 datasets | 475.6 µs | **2,102 scans/s** | Manifest file inspection |
