# REXI Known Issues & Technical Debt Tracker

This document tracks known issues, risks, technical debt, and architectural constraints identified during the project lifecycle.

---

## Active Issues

*No active code defects currently recorded.*

---

## Architectural Constraints & Watch Items

| ID | Area | Severity | Description | Mitigation Plan |
| :--- | :--- | :--- | :--- | :--- |
| **CON-0001** | Platform | Medium | macOS Darwin kernel lacks Linux `epoll`, `io_uring`, and explicit thread-to-core hard affinity APIs (`pthread_setaffinity_np`). | Implement clean platform abstraction layers under `infrastructure/networking/` and `infrastructure/execution/` that use `kqueue` / standard C++ threads on macOS and native high-perf APIs on Linux. |
| **CON-0004** | Latency | High | Cross-language IPC (Python to C++) introduces latency overhead if not properly structured. | Maintain complete separation: production execution runs entirely inside native C++ without runtime Python dependencies. |
| **CON-0005** | Simulator | Low | Exotic order types (iceberg, pegged, stop-loss) and stochastic network jitter models are excluded from Phase 03 baseline. | Keep simulator core minimal, deterministic, and modular so specialized order types can be added cleanly in later execution phases (Phase 22). |
| **CON-0006** | Market Data | Low | Canonical flat `OrderBookSnapshotMessage` is bounded to 16 bid/ask levels for zero heap allocation. | Deeper L2 full-depth snapshots or full-book recovery in Phase 05/07 will use multi-packet chunking or out-of-band snapshot channels. |
| **CON-0008** | Replay | Low | Phase 07 replay operates strictly sequentially over in-memory event streams without disk-backed indexing or arbitrary random seeks. | Implement Parquet / Arrow chunked streaming adapters and checkpoint-assisted random seek indices in Phase 08+. |
| **CON-0009** | Storage | Medium | POSIX `rename(2)` / `os.replace` cannot atomically overwrite a non-empty directory over another non-empty directory on macOS/Linux. | `DatasetWriter` implements a 3-phase transactional backup swap (`target -> backup`, `staging -> target`, purge backup on success, rollback on failure) paired with non-blocking process file locks (`.lock_{dataset_id}`). Active readers with open file descriptors remain undisturbed. |
| **CON-0010** | Features | Low | Roll (1984) spread requires negative lag-1 autocovariance ($\gamma_1 < 0$). In trending or momentum markets, positive autocovariance makes the Roll spread mathematically undefined. | `MicrostructureFeatureEngine` explicitly gates `has_roll_spread = false` without defaulting to silent zeros, ensuring downstream strategies never mistake missing models for zero spread. |
| **CON-0011** | Backtest | Low | Phase 11 backtest engine executes Market Orders against top-of-book displayed depth with configurable partial fills. Resting limit orders, iceberg orders, and multi-level book sweeps are deferred to Phase 22. | Phase 22 (Execution Engine) will introduce full L2/L3 order book traversal and algorithm execution (TWAP, VWAP, aggressive sweeps). |

---

## Resolved Issues

| ID | Area | Resolution | Phase | Verification Evidence |
| :--- | :--- | :--- | :--- | :--- |
| **CON-0003** | AI Safety | Implemented strict chronological splitting, point-in-time as-of feature joins ($T_{\text{avail}} \le T_{\text{decision}}$), de Prado label horizon purging, targeted post-test embargo, and verifiable causal LookaheadDetector in `research.leakage`. | Phase 09 | Verified via 41 Phase 09 unit & integration tests (101 total) covering chronological ordering, point-in-time causality, label purging, embargo boundaries, and Phase 08 integration. |
| **CON-0007** | Order Book | Replaced `std::list` nodes and `std::unordered_map` with preallocated `OrderPool` and open-addressing `OrderIdIndex` with backward-shift deletion. | Phase 06 | Verified zero heap allocations in steady-state operations via `ScopedAllocationGuard` in `test_order_book_allocation.cpp`. Batch add latency improved to 18.5 ns/order. |
| **CON-0002** | Data | Implemented bounded chunked streaming `DatasetReader.read_batch_iter()` and partitioned Parquet storage in `research.datasets`. | Phase 08 | Verified streaming iteration across 100k-record partitions in bounded memory batches; read throughput reached 46.7M - 53.8M rec/s. |
| **CRIT-001** | Data Lake | Replaced destructive `shutil.rmtree()` before publish with 3-phase transactional backup and rollback swap. | Phase 08 | Verified via `test_failed_replacement_preserves_original_valid_dataset`: original valid dataset remains intact if replacement fails. |
| **CRIT-002** | Schema | Restored missing `OrderBookSnapshotMessage` fields (`last_included_sequence`, `bid_levels_count`, `ask_levels_count`, `bids`, `asks`) in `REPLAY_EVENT_SCHEMA_V1`. | Phase 08 | Verified via `test_write_read_roundtrip_replay_stream` and `test_order_book_snapshot_nested_struct_levels`. |
| **CRIT-003** | Security | Enforced strict `validate_relative_path` and `resolve_partition_path` root containment checks against traversal and symlink escapes. | Phase 08 | Verified via `test_manifest_path_security_traversal_rejected`: absolute paths, traversal components, and external symlinks rejected. |
| **CRIT-004** | Integrity | Added duplicate partition rejection, internal manifest consistency checking, and deep Parquet metadata row-count audits. | Phase 08 | Verified via `test_manifest_rejects_duplicate_partitions`, `test_manifest_internal_consistency_validation`, `test_deep_parquet_integrity_and_row_count_mismatch`. |
| **CRIT-005** | Performance | Replaced full-batch `to_pylist()` with Arrow-native `pc.unique` and `Table.group_by().aggregate([])`. | Phase 08 | Verified zero full-batch Python dictionary allocations; write throughput reached 5.15M rec/s (147 MB/s). |
