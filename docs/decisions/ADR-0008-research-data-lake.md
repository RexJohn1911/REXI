# ADR-0008: Research Data Lake Subsystem

## Status
Accepted

## Date
2026-10-22

## Context
In Phases 01–07, REXI established the core event architecture, exchange simulator, market data protocol, allocation-disciplined order book, and deterministic historical market replay engine in native C++20.

To support quantitative alpha discovery, signal evaluation, and backtesting (Phases 09+), the platform requires a structured, schema-enforced historical data lake capable of storing and streaming high-frequency tick and order book datasets.

Key architectural requirements:
1. Columnar format support (Apache Arrow / Apache Parquet) for compressed storage and high-throughput vector scanning.
2. Zero floating-point rounding errors on financial values (preserving fixed-point ticks and whole share quantities).
3. Causal integration with Phase 04 protocol types and Phase 07 replay streams.
4. Protection against partial writes, data corruption, and path traversal vulnerabilities.
5. Strict separation between C++ production execution core and Python quantitative research tooling (`CON-0004`).

## Decisions

### 1. Python-Centric Data Lake Layer via PyArrow
We implement the primary Research Data Lake under `research/datasets/` utilizing Apache Arrow (`pyarrow`). This provides native integration with scientific computing tools while keeping the native C++ execution engine free of Python runtime dependencies.

### 2. Fixed-Point Integer Precision Invariant
All financial prices are encoded strictly as 64-bit signed integers (`int64`) representing discrete tick units. Quantities are encoded as 64-bit unsigned integers (`uint64`). Timestamps are stored as 64-bit nanosecond integers. Floating-point conversions are prohibited in the data storage format.

### 3. Centralized Schema Registry with Versioning and Replay Snapshot Fidelity
We establish a global `SchemaRegistry` managing versioned `pyarrow.Schema` definitions for trades, BBO quotes, L3 book deltas, depth snapshots, market status events, and unified replay event envelopes. Schemas enforce backward compatibility rules (same major version, self.minor >= required.minor). `REPLAY_EVENT_SCHEMA_V1` faithfully preserves all `OrderBookSnapshotMessage` payload fields (`last_included_sequence`, `bid_levels_count`, `ask_levels_count`, `bids`, `asks`).

### 4. 3-Phase Transactional Staging and Publication with Rollback
Dataset creation follows a strict lifecycle:
- An exclusive non-blocking file lock (`.lock_{dataset_id}`) is acquired via `flock`.
- Data is written into a hidden staging directory (`.staging_{dataset_id}_{uuid}`) on the same filesystem root.
- Partition checksums and record counts are finalized.
- `manifest.json` is generated.
- Publication uses a 3-phase transactional swap:
  1. `Phase 1`: Move existing target to backup (`.backup_{dataset_id}_{uuid}`).
  2. `Phase 2`: Move staging to target.
  3. `Phase 3`: Purge backup on success; rollback backup to target if Phase 2 fails.
- Destructive pre-publish deletion (`rmtree`) is strictly prohibited.
- Incomplete writes and corrupt staging artifacts are never visible in the catalog.

### 5. Cryptographic SHA-256 Manifest Checksums and Deep Parquet Verification
Every partition file's SHA-256 checksum and exact byte size are recorded in `manifest.json`. `DatasetReader.verify_integrity()` computes and verifies physical hashes and performs deep inspection of Parquet internal row counts, immediately detecting file corruption or truncation.

### 6. Strict Manifest Path Security and Containment
All partition paths are validated (`validate_relative_path` and `resolve_partition_path`), strictly rejecting absolute paths, traversal components (`..`), and external symlinks. Duplicate partition entries in manifests are rejected upon deserialization.

### 7. Arrow-Native Statistics Aggregation
Dataset statistics and partitioning use native Arrow C++ compute kernels (`pc.unique` and `Table.group_by().aggregate([])`), eliminating full-batch Python dictionary allocations (`to_pylist()`).

### 8. Provenance Tracking with Replay State Digest Binding
The manifest records complete lineage, including source capture files, generator parameters, and the 64-bit FNV-1a `replay_state_digest` from Phase 07 replay runs.

## Consequences

### Positive
- **High Throughput**: Exceeds 5.1M records/s write throughput and 48.5M records/s streaming read throughput on Apple Silicon.
- **Precision Guarantee**: Exact 64-bit integer tick and quantity preservation prevents floating-point drift.
- **Fail-Safe Integrity**: Interrupted writes or failed replacements cannot corrupt existing datasets or publish partial state; rollback protects valid datasets.
- **Path Security**: Immune to directory traversal and symlink escapes.
- **Standardized Lineage**: Datasets are self-describing and audit-ready for subsequent quantitative phases.

### Negative / Limitations
- **Local Storage Only**: Phase 08 focuses strictly on local filesystem storage; cloud object storage (S3/GCS) and distributed queries are excluded.
- **POSIX Directory Replacement Limitation (`CON-0009`)**: Overwriting a non-empty directory requires a temporary backup directory move rather than a single atomic rename syscall.
- **Out of Scope**: Does not implement backtesting rules, lookahead checks, or feature engineering (deferred to Phases 09 & 10).
