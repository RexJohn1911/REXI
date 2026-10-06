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

---

## Detailed Records

### DEC-0001: Two-World Architecture
- **Decision:** Separate production execution (`core/`, `simulator/`) in modern C++ (C++20/23) from quantitative research (`research/`, `ml/`) in Python.
- **Rationale:** Delivers microsecond-level deterministic low-allocation execution while preserving rapid ML/data-science research velocity.
- **Reference:** [ADR-0001](file:///Users/rexjohnabraham/Documents/REXI/docs/decisions/ADR-0001-project-architecture.md)

### DEC-0002: AI Research Layer Safety Boundary
- **Decision:** AI agents and LLMs will never sit inside the live trading hot path. AI operates solely in the research and hypothesis generation loop:
  `AI Agent -> Hypothesis -> Experiment -> Quantitative Validation -> Promoted Model -> Risk Engine -> Execution -> Exchange`.
- **Rationale:** Unconstrained generative models introduce non-deterministic latencies, hallucinations, and catastrophic tail-risk when placed directly in execution loops.

### DEC-0003: Cross-Platform Development (macOS to Linux)
- **Decision:** All core C++ code must compile, run, and pass tests on macOS (Apple Silicon ARM64 and x86_64) using portable C++ standard features. Platform-specific optimizations (e.g., Linux `io_uring`, epoll, CPU core pinning) will reside behind infrastructure abstraction layers.
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
- **Decision:** Root namespace is `rexi`, with subsystem namespaces such as `rexi::core`, `rexi::events`, `rexi::tests`, `rexi::benchmarks`. Formatting strictly enforced via `.clang-format` (Google baseline with C++20 standard).
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
- **Reference:** [ADR-0002](file:///Users/rexjohnabraham/Documents/REXI/docs/decisions/ADR-0002-core-event-architecture.md)

### DEC-0014: Compile-Time Event Traits & Trivial Copyability
- **Decision:** Event payloads must implement `EventTraits<T>` and satisfy `std::is_trivially_copyable_v<T>` and `std::is_standard_layout_v<T>`.
- **Rationale:** Eliminates virtual dispatch and heap allocation overhead in high-frequency event handling.

### DEC-0015: Wait-Free Bounded SPSC Ring Buffer
- **Decision:** Use an SPSC ring buffer with power-of-2 capacity, 64-byte cache line padding between producer and consumer state, and Acquire/Release atomic index synchronization.
- **Rationale:** Prevents CPU cacheline bouncing, provides deterministic bounded buffering, and eliminates thread contention.

### DEC-0016: Direct Lookup Event Dispatcher
- **Decision:** `EventDispatcher` uses direct table indexing over `EventType` without runtime string lookups or dynamic reflection.
- **Rationale:** Sub-nanosecond dispatch latency per subscriber and zero dynamic heap allocation on the hot path.

### DEC-0017: Integer Fixed-Point Price and Quantity Representation
- **Decision:** Represent prices as integer multiples of ticks (`int64_t Price`) and quantities as integer lots (`uint64_t Quantity`). Floating-point types are strictly forbidden in matching engine comparisons.
- **Rationale:** Guarantees 100% exact comparisons, eliminates IEEE 754 precision drift, and ensures deterministic order book crossing outcomes.
- **Reference:** [ADR-0003](file:///Users/rexjohnabraham/Documents/REXI/docs/decisions/ADR-0003-exchange-simulator.md)

### DEC-0018: Price-Time Priority Matching with Resting-Order Pricing
- **Decision:** Matching engine strictly executes highest Bids and lowest Asks first, with FIFO ordering at each price level. Executions across the spread take the resting order's price.
- **Rationale:** Conforms to standard continuous double auction market microstructure principles while maintaining exact determinism.

### DEC-0019: Deterministic Market Order Liquidity Exhaustion Policy
- **Decision:** Market orders consume all available opposite-side liquidity. If the opposing book is exhausted before the order is fully filled, the unfilled remainder is cancelled immediately.
- **Rationale:** Avoids fabricating synthetic liquidity while guaranteeing unambiguous deterministic state progression.

### DEC-0020: Deterministic Single-Threaded Matching Core
- **Decision:** The core matching engine executes deterministically in a single thread, advancing time strictly through an explicit `SimulationClock` and monotonic sequence numbering (`SequenceNum`).
- **Rationale:** Eliminates race conditions, thread scheduling jitter, and non-reproducible test failures, ensuring that identical input sequences produce identical output streams.

### DEC-0021: 40-Byte Standard Aligned Market Data Header
- **Decision:** Standardize canonical market data message headers at 40 bytes (8-byte aligned) containing protocol version, message type discriminant, flags, venue/feed/instrument IDs, 32-bit checksum, sequence number, source timestamp, and receive timestamp.
- **Rationale:** Minimizes cache-line footprints, eliminates padding overhead, and guarantees standard binary layout across platforms.
- **Reference:** [ADR-0004](file:///Users/rexjohnabraham/Documents/REXI/docs/decisions/ADR-0004-market-data-protocol.md)

### DEC-0022: Flat Trivially Copyable Message Payloads with Zero Heap Allocation
- **Decision:** All market data message payloads (TopOfBook, Trade, OrderBookAdd/Modify/Delete, OrderBookSnapshot, MarketStatus) are flat, standard-layout structs without heap allocations, pointers, or dynamic arrays.
- **Rationale:** Guarantees zero-allocation compatibility with lock-free SPSC ring buffers and sub-nanosecond copy semantics.

### DEC-0023: Deterministic 32-bit FNV-1a Checksum Integrity Protocol
- **Decision:** Provide optional packet integrity verification using 32-bit FNV-1a hash algorithm (`OffsetBasis = 0x811C9DC5`, `Prime = 0x01000193`).
- **Rationale:** Fast, zero-allocation non-cryptographic checksum verification (<16 ns) with known test vectors for validating packet integrity across network boundaries.

### DEC-0024: Monotonic Sequence Manager with Explicit Gap & Reset Semantics
- **Decision:** Track message streams per feed using `SequenceManager` with explicit typed outcomes (`Expected`, `Duplicate`, `Gap`, `OutOfOrder`, `ResetRequired`), refusing silent repair of sequence gaps.
- **Rationale:** Guarantees that feed discontinuities and session resets are transparently observable to downstream order book and replay consumers.

### DEC-0025: Price Level Map with Doubly Linked List FIFO Queue & Hash Node Index
- **Decision:** Implement canonical order book using sorted price level maps (`std::map<Price, PriceLevel>`) with doubly linked list order queues (`std::list<RestingOrder>`) and hash index storing list iterators (`std::unordered_map<OrderId, OrderLocation>`).
- **Rationale:** Guarantees $O(1)$ order cancellation and $O(1)$ quantity reductions without shifting elements or invalidating other orders' positions, while maintaining strict FIFO queue ordering.
- **Reference:** [ADR-0005](file:///Users/rexjohnabraham/Documents/REXI/docs/decisions/ADR-0005-order-book.md)

### DEC-0026: Explicit Priority Rules on Order Modification
- **Decision:** Quantity reductions at the same price preserve FIFO priority in-place; quantity increases lose priority and move the order to the back of the queue; price changes leave the old price level and join the back of the new level.
- **Rationale:** Mirrors canonical exchange matching engine rules, prevents priority gaming, and provides unambiguous deterministic state transitions.

### DEC-0027: Dual Snapshot Model (L2 Aggregated vs Native L3)
- **Decision:** Distinguish between Phase 04 aggregated L2 snapshots (which reconstruct price levels without fabricating synthetic OrderIds) and native L3 snapshots (which capture explicit resting order identities and queue positions).
- **Rationale:** Prevents polluting the order book state machine with fake identities while supporting full-depth state checkpointing.

### DEC-0028: Configurable Locked/Crossed Market Policy
- **Decision:** Support explicit `CrossedBookPolicy`: `Reject` (default for matching engine books, rejecting updates crossing the spread) vs `Allow` (for reconstructing external market data feeds where crossed markets temporarily occur).
- **Rationale:** Keeps matching engine invariant enforcement strict while allowing flexible adaptation to noisy real-world feed streams.

### DEC-0029: Preallocated Contiguous OrderPool with Intrusive Free-List
- **Decision:** Replace per-order heap allocations in `PriceLevel` with a contiguous, preallocated `OrderPool` of 80-byte `OrderSlot` objects, managed by an intrusive free-list embedded directly in the slot structures.
- **Rationale:** Eliminates dynamic memory allocation and deallocation during steady-state order insertions and cancellations, resolving CON-0007.
- **Reference:** [ADR-0006](file:///Users/rexjohnabraham/Documents/REXI/docs/decisions/ADR-0006-high-performance-data-structures.md)

### DEC-0030: Compact 32-Bit Integer Handles (`OrderHandle`) Over Pointers
- **Decision:** Use 32-bit unsigned integers (`uint32_t`) as slot handles rather than 64-bit raw pointers or container iterators, with sentinel `kInvalidOrderHandle = 0xFFFFFFFF`.
- **Rationale:** Reduces handle footprint by 50%, enhances memory density, and ensures handles remain valid across whole-book copy operations without requiring iterator re-pointing.

### DEC-0031: Intrusive FIFO Doubly-Linked Queues Inside PriceLevel
- **Decision:** Each `PriceLevel` maintains 32-bit `head_` and `tail_` handles, using intrusive `prev` and `next` links embedded directly within the pool slots to maintain strict price-time queue priority.
- **Rationale:** Reduces `PriceLevel` footprint to 32 bytes and delivers $O(1)$ append, arbitrary erasure, and tail relocation without dynamic node allocation.

### DEC-0032: Open-Addressing OrderIdIndex with Backward-Shift Deletion
- **Decision:** Replace `std::unordered_map` with an open-addressing linear-probing hash table utilizing SplitMix64 hashing and backward-shift deletion upon erasure.
- **Rationale:** Eliminates hash bucket node allocations on insertion and completely prevents performance degradation from tombstone accumulation over millions of cancellations.
