# Phase 07 Checkpoint: Historical Market Replay

## State Overview
- **Phase**: 07 — Historical Market Replay
- **Status**: COMPLETE & VERIFIED
- **Git Commit Target**: `feat(phase-07): establish historical market replay engine` (Pending user approval)
- **Branch**: `main`
- **Working Tree**: Ready for commit upon explicit user command

---

## Architectural Deliverables

1. **`core/include/rexi/replay/replay_event.hpp`**:
   - `ReplayPayload`: Bounded `std::variant` over canonical Phase 04 message types.
   - `ReplayEvent`: Standardized 8-byte aligned, trivially copyable record envelope with `MarketDataHeader`, `SourceId`, `input_index`, and payload.
   - `ReplayEventComparator`: Canonical strict total ordering contract.
   - Factory functions for zero-allocation event creation.

2. **`core/include/rexi/replay/replay_clock.hpp`**:
   - Pure deterministic `ReplayClock` decoupled from wall-clock time.
   - Exposes `current_time_ns()`, `previous_time_ns()`, `first_time_ns()`, `event_index()`, and `elapsed_replay_time_ns()`.

3. **`core/include/rexi/replay/replay_reader.hpp`**:
   - `IReplayReader`: Abstract reader interface.
   - `InMemoryReplayReader`: High-throughput span-based reader with zero heap allocations.

4. **`core/include/rexi/replay/replay_config.hpp`**:
   - `ValidationPolicy` (`Strict`, `Permissive`).
   - `ReplayMode` (`Step`, `MaxSpeed`, `TimeScaled`).
   - `ReplayStopCondition` (`max_events`, `stop_timestamp_ns`, `stop_on_error`).
   - `ReplayConfig` container.

5. **`core/include/rexi/replay/replay_result.hpp`**:
   - `ReplayDiagnostic`: Structured anomaly records.
   - `ReplayStatistics`: Execution counters with strict historical vs. wall-clock duration separation.
   - `DeterministicStateHasher` & `compute_state_digest()`: 64-bit FNV-1a canonical state digest across price levels and FIFO resting orders.
   - `ReplayResult` summary struct.

6. **`core/include/rexi/replay/replay_checkpoint.hpp`**:
   - Lightweight `ReplayCheckpoint` struct for point-in-time recovery.

7. **`core/include/rexi/replay/replay_engine.hpp`**:
   - Canonical `ReplayEngine` integrating Phase 04 validators, multi-feed `SequenceManager` cache, `ReplayClock`, and Phase 05/06 `OrderBook`.
   - Step mode, max speed mode, stop conditions, and Phase 02 `EventDispatcher` integration.

8. **`core/include/rexi/replay/synthetic_generator.hpp`**:
   - `SyntheticReplayFixtureGenerator` and `DeterministicPrng` (SplitMix64) providing deterministic fixtures for clean L3 streams, snapshots, gaps, duplicates, out-of-order packets, corrupted payloads, and large stress runs.

9. **`benchmarks/benchmark_replay.cpp`**:
   - 9 Google Benchmark performance suites measuring latency, batch throughput, validation overhead, and scaling up to 100,000 events.

---

## Verification & Test Results

- **Debug CTest**: 128 / 128 PASSED (0.91s)
- **Release CTest**: 128 / 128 PASSED (0.53s)
- **Phase 00–06 Regression Tests**: 92 / 92 PASSED
- **Phase 07 Specialized Tests**: 36 / 36 PASSED
  - `ReplayClockTest.*` (6 tests): Initial state, baseline advancement, zero delta, relative delta, reset.
  - `ReplayOrderingTest.*` (6 tests): Sequence ordering, source timestamp, tie-breaking, sorting reconstruction.
  - `ReplayReaderTest.*` (5 tests): Empty stream, single event, sequential iteration, reset, polymorphism.
  - `ReplayValidationTest.*` (6 tests): Clean stream, gaps (strict vs permissive), duplicates, out-of-order, malformed payloads, checksum failure.
  - `ReplaySnapshotTest.*` (2 tests): Snapshot + incremental sequence baseline, subsequent snapshot book replacement.
  - `ReplayEngineTest.*` (6 tests): Step mode, step vs max-speed equivalence, stop conditions, dispatcher integration, checkpoint/restore.
  - `ReplayDeterminismTest.*` (3 tests): Independent engines bit-for-bit equivalence, run-reset-run identity, 5,000-event stress stream determinism.
  - `ReplayAllocationTest.*` (1 test): Custom allocation tracker verifying **0 dynamic heap allocations** during steady-state in-memory replay into a pre-warmed book.
  - `ReplayPipelineIntegrationTest.*` (1 test): Full end-to-end replay pipeline from synthetic stream to OrderBook, EventDispatcher, and state digest.
- **Sanitizers**: AddressSanitizer (ASan) + UndefinedBehaviorSanitizer (UBSan) passed 128 / 128 tests with 0 errors.
- **Microbenchmarks (Google Benchmark v1.8.3, Apple Silicon arm64, Release)**:
  - Single-event replay: **389 ns**
  - 1,000-event replay batch: **22.5 ns/event** (44.3M events/sec)
  - 100,000-event replay: **60.7 ns/event** (16.5M events/sec)
  - Mixed L3 market-data stream: **51.0 ns/event** (19.6M events/sec)
  - Step mode (500 events): **20.6 ns/event** (48.4M events/sec)
  - Max-speed mode (500 events): **22.9 ns/event** (43.6M events/sec)
  - Strict validation overhead: **23.1 ns/event**
  - Permissive validation overhead: **22.8 ns/event**
- **Static Analysis & Tooling**:
  - Clang-Format: Clean (0 diffs)
  - Clang-Tidy: 0 errors
  - Pytest: 2 / 2 PASSED
  - Ruff: Clean (All checks passed)
  - Mypy: Clean (0 issues across source files)
