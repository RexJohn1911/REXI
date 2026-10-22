# REXI Architectural & Technical Decisions Log

This document tracks all high-level technical decisions, standards, and conventions agreed upon for the REXI platform.

---

## Index of Decisions

| ID | Date | Category | Summary | Status |
| :--- | :--- | :--- | :--- | :--- |
| **DEC-0001** | 2026-10-06 | Architecture | Two-World System: C++20/23 Execution + Python Research | Accepted |
| **DEC-0002** | 2026-10-06 | AI / Safety | AI Research Agent strictly decoupled from trading hot path | Accepted |
| **DEC-0003** | 2026-10-06 | Platform | macOS (Apple Silicon/Intel) development target with Linux production target | Accepted |
| **DEC-0004** | 2026-10-06 | Build System | CMake 3.22+ with Ninja generator for C++ toolchain | Accepted |
| **DEC-0005** | 2026-10-06 | Testing | Multi-tiered testing: GoogleTest + Google Benchmark (C++) and pytest (Python) | Accepted |
| **DEC-0006** | 2026-10-06 | Data Storage | Apache Arrow and Parquet for research and intermediate representations | Accepted |
| **DEC-0007** | 2026-10-06 | UI / Dashboard | Future dashboard uses Claymorphism (tactile, non-collapsing, quantitative density) | Accepted |
| **DEC-0008** | 2026-10-06 | Discipline | Strict single-canonical-location folder discipline | Accepted |
| **DEC-0009** | 2026-10-06 | Toolchain | Standardized CMakePresets.json with Debug and Release profiles | Accepted |
| **DEC-0010** | 2026-10-06 | Code Style | C++ namespace `rexi` with Google/C++20 clang-format standards | Accepted |
| **DEC-0011** | 2026-10-06 | Python Setup | Centralized pyproject.toml for pytest, ruff, and mypy | Accepted |
| **DEC-0012** | 2026-10-06 | Dependencies | FetchContent shallow clones for GoogleTest v1.14.0 and Benchmark v1.8.3 | Accepted |
| **DEC-0013** | 2026-10-06 | Events | 24-byte `EventHeader` layout with monotonic nanosecond timestamping | Accepted |
| **DEC-0014** | 2026-10-06 | Events | Compile-time `EventTraits` enforcing trivial copyability for zero allocations | Accepted |
| **DEC-0015** | 2026-10-06 | Concurrency | Wait-free bounded `SpscRingBuffer` with 64-byte cache line padding | Accepted |
| **DEC-0016** | 2026-10-06 | Routing | Direct-indexed non-allocating `EventDispatcher` and channel `EventBus` | Accepted |
| **DEC-0017** | 2026-10-06 | Simulator | Integer fixed-point Price (`int64_t`) and Quantity (`uint64_t`) representation | Accepted |
| **DEC-0018** | 2026-10-06 | Simulator | Price-time priority matching with resting-order trade execution pricing | Accepted |
| **DEC-0019** | 2026-10-06 | Simulator | Deterministic market order exhaustion remainder cancellation policy | Accepted |
| **DEC-0020** | 2026-10-06 | Simulator | Deterministic single-threaded matching decoupled from wall-clock time | Accepted |
| **DEC-0021** | 2026-10-07 | Market Data | Flat fixed-layout `MarketDataHeader` with zero dynamic allocation | Accepted |
| **DEC-0022** | 2026-10-07 | Market Data | Strict continuous sequence numbers with Gap / Duplicate / OutOfOrder detection | Accepted |
| **DEC-0023** | 2026-10-07 | Market Data | Static fixed-size 16-level `OrderBookSnapshotMessage` layout | Accepted |
| **DEC-0024** | 2026-10-07 | Market Data | Bitwise incremental checksum validation across network protocol boundaries | Accepted |
| **DEC-0025** | 2026-10-07 | Order Book | Two-level sparse array + dense price level order book architecture | Accepted |
| **DEC-0026** | 2026-10-07 | Order Book | Constant-time L2 BBO caching with deferred dirty-flag recomputation | Accepted |
| **DEC-0027** | 2026-10-07 | Order Book | Monotonic sequence validation with strict gap rejection inside OrderBook | Accepted |
| **DEC-0028** | 2026-10-07 | Order Book | Bounded static allocation for order book depth snapshots | Accepted |
| **DEC-0029** | 2026-10-08 | High Perf | Custom contiguous `OrderPool` with freelist recycling | Accepted |
| **DEC-0030** | 2026-10-08 | High Perf | Index handles (`OrderHandle`) replacing raw C++ pointers in OrderBook | Accepted |
| **DEC-0031** | 2026-10-08 | High Perf | Intrusive FIFO doubly-linked queues inside `PriceLevel` | Accepted |
| **DEC-0032** | 2026-10-08 | High Perf | Open-addressing `OrderIdIndex` with backward-shift deletion | Accepted |
| **DEC-0033** | 2026-10-08 | Replay | Canonical replay record composition over protocol duplication | Accepted |
| **DEC-0034** | 2026-10-08 | Replay | Strict total ordering contract with feed-sequence primacy | Accepted |
| **DEC-0035** | 2026-10-08 | Replay | Pure deterministic `ReplayClock` with zero wall-clock coupling | Accepted |
| **DEC-0036** | 2026-10-08 | Replay | Inline multi-feed sequence cache with zero steady-state allocations | Accepted |
| **DEC-0037** | 2026-10-08 | Replay | Canonical 64-bit state digest for determinism verification | Accepted |
| **DEC-0038** | 2026-10-22 | Data Lake | Python PyArrow Research Data Lake Layer | Accepted |
| **DEC-0039** | 2026-10-22 | Data Lake | Fixed-Point 64-Bit Integer Numerical Precision Invariant | Accepted |
| **DEC-0040** | 2026-10-22 | Data Lake | Centralized Semantic SchemaRegistry for Market Data and Replay | Accepted |
| **DEC-0041** | 2026-10-22 | Data Lake | 3-Phase Transactional Publication with Rollback and File Locking | Accepted |
| **DEC-0042** | 2026-10-22 | Data Lake | Cryptographic SHA-256 Manifest Verification and Replay State Digest Provenance | Accepted |
| **DEC-0043** | 2026-10-22 | Data Lake | Manifest Path Security, Containment Checks, and Deep Parquet Verification | Accepted |
| **DEC-0044** | 2026-10-22 | Data Lake | Arrow-Native Partitioning and Statistics Aggregation | Accepted |
| **DEC-0045** | 2026-10-22 | Data Lake | Coordinated Process Locking Protocol Across Writers, Readers, Recovery, and Cleanup | Accepted |
| **DEC-0046** | 2026-10-22 | Data Lake | Replay Schema Immutability (V1) and Lossless Depth Snapshot Fidelity (V2) | Accepted |
| **DEC-0047** | 2026-10-22 | Research | Strict Chronological Partitioning and Prohibition of Shuffling | Accepted |
| **DEC-0048** | 2026-10-22 | Research | Half-Open Boundaries, Closed Label Horizons, and de Prado Purging | Accepted |
| **DEC-0049** | 2026-10-22 | Research | Targeted Post-Test Embargo Applied Exclusively to Following Folds | Accepted |
| **DEC-0050** | 2026-10-22 | Research | Separation of Feature Observation vs. Availability Time (T_available <= T_decision) | Accepted |
| **DEC-0051** | 2026-10-22 | Research | Cryptographically Sealed SplitManifest with Phase 08 Dataset Binding | Accepted |
| **DEC-0052** | 2026-10-22 | Features | Two-World Microstructure Feature Engine (C++ Zero-Alloc Hot-Path + Python Research) | Accepted |
| **DEC-0053** | 2026-10-22 | Features | Explicit Feature Availability Gating and Prohibition of Silent Default Zeros | Accepted |
| **DEC-0054** | 2026-10-22 | Features | Canonical Microstructure Formulations (Cont OFI, Roll Spread, VPIN, Trade Flow) | Accepted |

---

## Detailed Records

### DEC-0001: Two-World Architecture
- **Decision:** Separate production execution (`core/`, `simulator/`) in modern C++ (C++20/23) from quantitative research (`research/`, `ml/`) in Python.
- **Rationale:** Delivers microsecond-level deterministic low-allocation execution while preserving rapid ML/data-science research velocity.
- **Reference:** [ADR-0001](file:///Users/rexjohnabraham/Documents/REXI/docs/decisions/ADR-0001-project-architecture.md)

### DEC-0002: AI Research Layer Safety Boundary
- **Decision:** AI agents and LLMs will never sit inside the live trading hot path. AI operates solely in the research and hypothesis generation loop.
- **Rationale:** Unconstrained generative models introduce non-deterministic latencies, hallucinations, and catastrophic tail-risk when placed directly in execution loops.

### DEC-0003: Cross-Platform Development (macOS to Linux)
- **Decision:** All core C++ code must compile, run, and pass tests on macOS (Apple Silicon ARM64 and x86_64) using portable C++ standard features. Platform-specific optimizations will reside behind infrastructure abstraction layers.
- **Rationale:** Maximizes developer productivity on macOS workstations while preserving a clean transition to production Linux servers.

### DEC-0004: Build System Toolchain
- **Decision:** Standardize on CMake (>= 3.22) paired with the Ninja build generator.
- **Rationale:** Industry standard for high-performance C++ builds, enabling fast incremental compilation and cross-IDE support via `compile_commands.json`.

### DEC-0005: Testing Frameworks
- **Decision:** Use GoogleTest (`gtest`) and Google Benchmark (`benchmark`) for C++ components; use `pytest` with hypothesis/coverage for Python modules.
- **Rationale:** Provides rigorous unit, regression, integration, and nanosecond microbenchmarking capabilities across both technology stacks.

### DEC-0006: Data Formats
- **Decision:** Use Apache Arrow (in-memory columnar data) and Apache Parquet (compressed on-disk storage) for tick datasets, feature caches, and model training matrices.
- **Rationale:** High throughput, zero-copy capabilities, cross-language interoperability between C++ and Python.

### DEC-0007: Claymorphism UI Design System (Future State)
- **Decision:** The eventual `apps/dashboard/` will implement a professional, tactile Claymorphism design system with fixed/persistent navigation and non-collapsing core panels.
- **Rationale:** Provides modern, premium aesthetics without sacrificing numerical legibility, chart clarity, or quantitative density.

### DEC-0008: Folder Discipline
- **Decision:** Every file has exactly one canonical location. No random folders, no duplicate source files, and no ad-hoc folder creation.
- **Rationale:** Ensures clean scalability across all 32 development phases.

### DEC-0009: CMake Presets Specification
- **Decision:** Maintain `CMakePresets.json` with standardized `debug` and `release` configure, build, and test presets using `build/debug` and `build/release` out-of-source directories.
- **Rationale:** Provides identical, one-command builds across developer workstations and CI runners.

### DEC-0010: C++ Namespace and Style Conventions
- **Decision:** Root namespace is `rexi`, with subsystem namespaces such as `rexi::core`, `rexi::events`, `rexi::tests`, `rexi::benchmarks`. Formatting strictly enforced via `.clang-format`.
- **Rationale:** Avoids namespace collisions and ensures code formatting consistency across all contributors.

### DEC-0011: Centralized Python Packaging
- **Decision:** Centralize all Python tooling configuration (`pytest`, `ruff`, `mypy`) within `pyproject.toml` in the repository root.
- **Rationale:** Eliminates scattered configuration files and guarantees uniform linting and type-checking rules.

### DEC-0012: Reproducible C++ Test/Benchmark Dependencies
- **Decision:** Fetch GoogleTest (v1.14.0) and Google Benchmark (v1.8.3) via CMake `FetchContent` using shallow git tags.
- **Rationale:** Ensures hermetic, zero-dependency builds without requiring global system package installations or committing third-party code.

### DEC-0013: Standardized 24-Byte Event Header
- **Decision:** All internal messages encapsulate an 8-byte aligned `EventHeader` containing `EventType`, `SourceId`, flags, monotonic sequence number, and nanosecond monotonic timestamp.
- **Rationale:** Provides consistent message provenance, chronological ordering, and cache alignment without dynamic allocation.

### DEC-0014: Compile-Time Event Traits & Trivial Copyability
- **Decision:** Event payloads must implement `EventTraits<T>` and satisfy `std::is_trivially_copyable_v<T>` and `std::is_standard_layout_v<T>`.
- **Rationale:** Eliminates virtual dispatch and heap allocation overhead in high-frequency event handling.

### DEC-0015: Wait-Free Bounded SPSC Ring Buffer
- **Decision:** Use an SPSC ring buffer with power-of-2 capacity, 64-byte cache line padding between producer and consumer state, and Acquire/Release atomic index synchronization.
- **Rationale:** Prevents CPU cacheline bouncing, provides deterministic bounded buffering, and eliminates thread contention.

### DEC-0016: Direct Lookup Event Dispatcher
- **Decision:** `EventDispatcher` uses direct table indexing over `EventType` without runtime string lookups or dynamic reflection.
- **Rationale:** Dispatches events with $O(1)$ determinism and minimal cache pollution.

### DEC-0017: Price and Quantity Integer Fixed-Point Units
- **Decision:** Internal engine represents prices as `int64_t` fixed-point ticks and quantities as `uint64_t` integral units. Floating point (`double`, `float`) is strictly prohibited in matching logic.
- **Rationale:** Guarantees zero rounding errors, associative arithmetic, and bit-exact reproducibility across platforms.

### DEC-0018: Strict Price-Time Priority Matching Engine
- **Decision:** Resting limit orders match on pure price-time priority. Executions price at the resting limit order's price.
- **Rationale:** Follows universal exchange microstructure standards and eliminates non-deterministic execution pricing.

### DEC-0019: Market Order Unmatched Remainder Cancellation Policy
- **Decision:** Market orders that cannot be immediately filled against resting liquidity are immediately canceled (IOC-like exhaustion) rather than resting on the book.
- **Rationale:** Prevents infinite-price resting states and complies with standard financial exchange order handling semantics.

### DEC-0020: Discrete Event Decoupled Matching Engine
- **Decision:** Simulator state transitions occur strictly per discrete event via incoming `source_timestamp` and sequential `OrderCommand`. Wall-clock timers do not drive execution.
- **Rationale:** Ensures 100% deterministic backtesting, reproducible debugging, and zero dependency on host system load.

### DEC-0021: Flat Fixed-Layout MarketDataHeader
- **Decision:** All external market data messages share an 8-byte aligned `MarketDataHeader` containing schema version, message type, flags, venue ID, feed ID, instrument ID, checksum, sequence number, and timestamps.
- **Rationale:** Supports wire-level binary validation, feed identification, and chronological replay sorting without heap allocation.

### DEC-0022: Continuous Sequence Numbers and Gap Detection
- **Decision:** Every market data channel mandates strictly monotonically increasing sequence numbers, validated by a dedicated `SequenceManager`.
- **Rationale:** Detects network packet drops, duplicate feeds, and out-of-order deliveries instantly before feeding downstream matching engines.

### DEC-0023: Static Fixed-Size 16-Level OrderBookSnapshotMessage
- **Decision:** Market data snapshots are fixed at 16 depth levels (`MAX_SNAPSHOT_LEVELS = 16`) using contiguous inline structs.
- **Rationale:** Completely eliminates dynamic array allocations on snapshot publishing and parsing, preserving ultra-low latency guarantees.

### DEC-0024: Fast Incremental Checksum Validation
- **Decision:** Use a 16-bit additive folding checksum algorithm over serialized network payloads with bitwise inversion.
- **Rationale:** Detects bit-flips and corrupted packets with sub-microsecond overhead before dispatching to trading engines.

### DEC-0025: Two-Level Sparse Array + Dense Price Level Order Book Architecture
- **Decision:** Model the order book using flat price levels with contiguous sparse-to-dense indexing rather than complex pointer trees (`std::map`).
- **Rationale:** Minimizes pointer chasing and cache misses during frequent best bid/ask lookups and level iterations.

### DEC-0026: Constant-Time L2 BBO Caching with Deferred Recomputation
- **Decision:** Cache top-of-book best bid and best ask levels directly. Mark dirty on order execution/cancellation and recompute only when queried or when best level is exhausted.
- **Rationale:** Eliminates repeated scans across empty price levels for high-frequency quote readers.

### DEC-0027: Monotonic Sequence Validation Inside OrderBook
- **Decision:** `OrderBook` embeds internal sequence checking that halts or rejects updates if sequence gaps occur.
- **Rationale:** Prevents state corruption caused by missed exchange deltas or packet loss.

### DEC-0028: Bounded Static Allocation for Order Book Snapshots
- **Decision:** Snapshot generation populates fixed-capacity preallocated buffers without dynamic vector reallocation.
- **Rationale:** Ensures zero heap allocations during market data snapshot capture.

### DEC-0029: Custom Contiguous OrderPool with Freelist Recycling
- **Decision:** Implement a custom pool allocator (`OrderPool`) that preallocates a contiguous block of memory for order records and manages unused slots via an intrusive singly-linked freelist.
- **Rationale:** Eliminates operating system heap allocation jitter (`malloc`/`free`) on order insertions and cancellations, achieving deterministic $O(1)$ allocation times and cache locality.

### DEC-0030: Index Handles Replacing Raw C++ Pointers
- **Decision:** Internal order book indices reference order records via 32-bit `OrderHandle` indices rather than raw 64-bit pointers.
- **Rationale:** Halves pointer memory footprint, eliminates 64-bit pointer overhead in cache lines, improves cache capacity, and ensures handles remain valid across whole-book copy operations without requiring iterator re-pointing.

### DEC-0031: Intrusive FIFO Doubly-Linked Queues Inside PriceLevel
- **Decision:** Each `PriceLevel` maintains 32-bit `head_` and `tail_` handles, using intrusive `prev` and `next` links embedded directly within the pool slots to maintain strict price-time queue priority.
- **Rationale:** Reduces `PriceLevel` footprint to 32 bytes and delivers $O(1)$ append, arbitrary erasure, and tail relocation without dynamic node allocation.

### DEC-0032: Open-Addressing OrderIdIndex with Backward-Shift Deletion
- **Decision:** Replace `std::unordered_map` with an open-addressing linear-probing hash table utilizing SplitMix64 hashing and backward-shift deletion upon erasure.
- **Rationale:** Eliminates hash bucket node allocations on insertion and completely prevents performance degradation from tombstone accumulation over millions of cancellations.

### DEC-0033: Canonical Replay Record Composition Over Protocol Duplication
- **Decision:** Encapsulate historical events in `ReplayEvent` using canonical Phase 04 `MarketDataHeader` and typed `std::variant` payloads rather than creating a separate replay-specific protocol hierarchy.
- **Rationale:** Eliminates protocol divergence, ensures wire/replay parity, and maintains a single canonical event path into the order book.

### DEC-0034: Strict Total Ordering Contract with Feed-Sequence Primacy
- **Decision:** Implement `ReplayEventComparator` enforcing total ordering: authoritative feed sequence number first, followed by source timestamp, receive timestamp, feed identifiers, and stable input index.
- **Rationale:** Prevents arbitrary reordering across simultaneous events while preserving original exchange sequence continuity and eliminating platform-dependent sorting ties.

### DEC-0035: Pure Deterministic ReplayClock with Zero Wall-Clock Coupling
- **Decision:** Drive historical simulation time entirely through incoming historical timestamps via `ReplayClock`, strictly decoupled from system and steady wall-clock timers.
- **Rationale:** Guarantees 100% reproducible execution and timing metrics regardless of host CPU speed, execution pauses, or debug stepping.

### DEC-0036: Inline Multi-Feed Sequence Cache with Zero Steady-State Allocations
- **Decision:** Track sequence managers per feed within `ReplayEngine` via an inline fixed array of 16 entries before falling back to heap structures.
- **Rationale:** Preserves the Phase 06 zero-allocation guarantee for multi-feed streams during hot-path replay.

### DEC-0037: Canonical 64-Bit State Digest for Determinism Verification
- **Decision:** Implement `compute_state_digest()` combining 64-bit FNV-1a hashing over sorted price levels, resting order FIFO queues, clock states, and counters without hashing pointers or container layouts.
- **Rationale:** Enables automated bit-for-bit regression testing across compiler toolchains, optimization levels, and runs.

### DEC-0038: Python PyArrow Research Data Lake Layer
- **Decision:** Implement the primary quantitative Research Data Lake under `research/datasets/` using Apache Arrow / Parquet (`pyarrow`) while keeping the native C++ execution engine free of Python runtime dependencies.
- **Rationale:** Leverages the rich columnar ecosystem for research without compromising C++ zero-allocation low-latency production execution (`CON-0004`).
- **Reference:** [ADR-0008](file:///Users/rexjohnabraham/Documents/REXI/docs/decisions/ADR-0008-research-data-lake.md)

### DEC-0039: Fixed-Point 64-Bit Integer Numerical Precision Invariant
- **Decision:** Financial prices are strictly encoded as 64-bit signed integers (`pa.int64()`) representing discrete tick units; quantities are encoded as 64-bit unsigned integers (`pa.uint64()`) representing lot units; timestamps are 64-bit nanosecond integers. Floating-point conversions are prohibited.
- **Rationale:** Prevents IEEE-754 rounding drift and guarantees 100% precision parity with native C++ fixed-point order book calculations.

### DEC-0040: Centralized Semantic SchemaRegistry for Market Data and Replay
- **Decision:** Establish a thread-safe `SchemaRegistry` managing versioned PyArrow schemas for trades, quotes, L3 book deltas, depth snapshots, market status, instrument definitions, and unified replay event envelopes with backward compatibility validation rules.
- **Rationale:** Prevents schema divergence, guarantees strict type enforcement, and rejects incompatible schemas before writing or reading.

### DEC-0041: 3-Phase Transactional Publication with Rollback and File Locking
- **Decision:** Overwrite publication executes a 3-phase transactional backup swap (`target -> backup`, `staging -> target`, purge backup on success, rollback on failure) protected by a non-blocking process file lock (`.lock_{dataset_id}`). Destructive pre-publish deletions (`rmtree`) are strictly prohibited.
- **Rationale:** Solves POSIX non-empty directory rename restrictions (`CON-0009`) while ensuring previously valid datasets are never deleted or corrupted if replacement publication encounters a disk or system failure. Active readers with open file descriptors continue uninterrupted.

### DEC-0042: Cryptographic SHA-256 Manifest Verification and Replay State Digest Provenance
- **Decision:** Every completed dataset manifest records chunked SHA-256 checksums per partition file and tracks full lineage including Phase 07 64-bit `replay_state_digest`.
- **Rationale:** Delivers tamper-evident integrity audits (`verify_integrity()`) and bit-for-bit reproducible provenance linking research datasets directly to simulator/replay states.

### DEC-0043: Manifest Path Security, Containment Checks, and Deep Parquet Verification
- **Decision:** Deserialization and reading strictly sanitize partition paths (`validate_relative_path` and `resolve_partition_path`), rejecting absolute paths, traversal components (`..`), and external symlinks. Manifest deserialization rejects duplicate partition entries and count/size inconsistencies. `verify_integrity()` performs deep Parquet file inspection against internal row-count metadata.
- **Rationale:** Prevents arbitrary file reads/writes outside dataset boundaries and guarantees manifest truthfulness beyond physical file checksums.

### DEC-0044: Arrow-Native Partitioning and Statistics Aggregation
- **Decision:** Dataset statistics aggregation and row-wise partitioning are implemented directly via Arrow C++ compute kernels (`pc.unique`, `Table.group_by().aggregate([])`, `Table.filter(mask)`), eliminating full-batch Python dictionary allocations (`to_pylist()`).
- **Rationale:** Binds memory allocations strictly to partition cardinalities rather than dataset batch row counts, delivering write throughput exceeding 5.1M records/s (147 MB/s).

### DEC-0045: Coordinated Process Locking Protocol Across Writers, Readers, Recovery, and Cleanup
- **Decision:** All write, recovery, and cleanup mutations require acquiring an advisory non-blocking process file lock (`DatasetLock`, `fcntl.LOCK_EX | fcntl.LOCK_NB`) on `.lock_{dataset_id}`. Empty lock files intentionally persist on disk to eliminate inode deletion races; active status is evaluated strictly via non-blocking lock acquisition tests (`DatasetLock.is_active`). Recovery and stale staging cleanup skip datasets with actively held locks, completely preventing races with concurrent publishing writers.
- **Rationale:** Ensures crash recovery and automated maintenance never race with or destroy active publication transactions, prevents reader false-positives on stale lock files, and provides idempotent recovery without deleting valid backups.

### DEC-0046: Replay Schema Immutability (V1) and Lossless Depth Snapshot Fidelity (V2)
- **Decision:** `REPLAY_EVENT_SCHEMA_V1` (`v1.0.0`, 32 columns) is preserved strictly immutable for backward compatibility. `REPLAY_EVENT_SCHEMA_V2` (`v1.1.0`, 37 columns) introduces full `OrderBookSnapshotMessage` payload fidelity (`last_included_sequence`, `bid_levels_count`, `ask_levels_count`, and nested struct lists `bids` and `asks` with `price`, `quantity`, `order_count`). Readers transparently detect schema versions from `manifest.json`.
- **Rationale:** Honors schema versioning immutability: snapshot payloads were never recorded in V1 datasets and cannot be losslessly reconstructed from V1 data. V2 provides 100% bit-for-bit replay book reconstruction.

### DEC-0047: Strict Chronological Partitioning and Prohibition of Shuffling
- **Decision:** All research partitions (Train, Validation, Test, Walk-Forward, and CV blocks) are partitioned strictly in temporal order. Random shuffling of time-series observations is strictly prohibited throughout REXI. Duplicate decision timestamps at boundaries are deterministically kept together in the same partition.
- **Rationale:** Random shuffling leaks future regime and autocorrelation information into training sets, rendering backtest statistics fundamentally invalid.

### DEC-0048: Half-Open Boundaries, Closed Label Horizons, and de Prado Purging
- **Decision:** Partition time boundaries are defined as half-open $[t_{\text{start}}, t_{\text{end}})$, while label information intervals are defined as closed $[t_{\text{obs}}, t_{\text{label\_end}}]$. Training samples whose label intervals touch evaluation partitions ($t_{\text{obs}} < t_{\text{test, end}}$ and $t_{\text{label\_end}} \ge t_{\text{test, start}}$) are purged.
- **Rationale:** Eliminates boundary ambiguities and prevents future return information from leaking across partition boundaries into training weights.

### DEC-0049: Targeted Post-Test Embargo Applied Exclusively to Following Folds
- **Decision:** Embargo buffers ($[t_{\text{test, end}}, t_{\text{test, end}} + \Delta_{\text{embargo}})$) are applied strictly to post-test training data in cross-validation (e.g. Purged K-Fold). Embargo is never applied to pre-test training samples or standard chronological holdout where training precedes testing.
- **Rationale:** Eliminates autoregressive and serial correlation leakage from test periods into immediately following training samples without needlessly discarding valid pre-test training data.

### DEC-0050: Separation of Feature Observation vs. Availability Time
- **Decision:** Feature schemas and alignment engines explicitly differentiate between `event_timestamp_ns` (when physical market event occurred) and `available_timestamp_ns` (when feature was realistically received and computed). Decisions at $T_{\text{decision}}$ may only observe features satisfying $T_{\text{available}} \le T_{\text{decision}}$.
- **Rationale:** Models actual execution realities (feed latency, network jitter, computation delay), eliminating lookahead bias in signal generation.

### DEC-0051: Cryptographically Sealed SplitManifest with Phase 08 Dataset Binding
- **Decision:** Split configurations and partition boundaries are serialized into a standardized `SplitManifest` (`manifest.json` v1.0.0) recording source `dataset_id`, source `dataset_manifest_sha256`, exact row index spans, and a self-sealing SHA-256 hash.
- **Rationale:** Ensures 100% bit-for-bit reproducible train/val/test splits across research environments without copying or duplicating underlying Parquet partition files.

### DEC-0052: Two-World Microstructure Feature Engine Architecture
- **Decision:** Microstructure feature calculations are dual-architected:
  1. Low-latency C++ hot-path (`core/include/rexi/microstructure/`): zero steady-state heap allocations, contiguous fixed ring buffers (`FixedRingBuffer<T, N>`), sub-50ns update latency for live trading pipelines.
  2. Quantitative research Python engine (`research/features/`): vectorized/streaming PyArrow table extraction, Phase 08 Data Lake integration (`MICROSTRUCTURE_FEATURES_SCHEMA_V1`), and Phase 09 lookahead audit.
- **Rationale:** Enforces clean separation between ultra-low-latency production execution and flexible, point-in-time quantitative research without duplicating business logic formulas.

### DEC-0053: Explicit Feature Availability Gating and Prohibition of Silent Default Zeros
- **Decision:** Every computed microstructure feature is strictly paired with a boolean validity flag (`has_bid`, `has_ask`, `is_crossed`, `has_spread`, `has_mid`, `has_weighted_mid`, `has_book_imbalance`, `has_depth_imbalance`, `has_instant_ofi`, `has_rolling_ofi`, `has_trade`, `has_trade_flow`, `has_vwap`, `has_log_return`, `has_realized_volatility`, `has_roll_spread`, `has_vpin`). Missing quotes, crossed/locked books, insufficient history, and non-negative Roll autocovariances are never substituted with silent zeros.
- **Rationale:** Prevents models and signals from confusing missing or invalid data with genuine market conditions (such as zero spread or zero price change), eliminating spurious trading signals.

### DEC-0054: Canonical Microstructure Formulations
- **Decision:** Formulations follow established quantitative microstructure literature: Cont, Kukanov & Stoikov (2014) for Order Flow Imbalance (OFI); Roll (1984) for effective spread via serial covariance; Easley, Lopez de Prado & O'Hara (2012) for Volume-Synchronized Probability of Toxicity (VPIN); and continuous rolling VWAP/trade flow imbalance.
- **Rationale:** Ensures mathematical rigor, verifiable correctness, and deterministic equivalence between streaming and batched research evaluations.
