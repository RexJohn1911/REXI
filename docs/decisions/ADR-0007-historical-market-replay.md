# ADR-0007: Historical Market Replay Subsystem

## Status
Accepted

## Date
2026-10-06

## Context
In Phases 01–06, REXI established the core event architecture (Phase 02), deterministic exchange simulator (Phase 03), binary market-data protocol (Phase 04), and high-performance allocation-disciplined order book (Phase 05 & 06).

To enable quantitative backtesting, feature engineering, and market microstructure research (Phases 08+), the platform requires a canonical historical replay engine capable of taking recorded market data streams and deterministically reconstructing book state.

Key constraints:
1. Replay must NOT reinvent a second event architecture or duplicate the order book.
2. Replay must preserve source event ordering, feed sequence numbers, and exchange timestamps without depending on host wall-clock time.
3. Replay must enforce zero look-ahead bias (events at index $i$ must only observe state up to $i$).
4. Replay must maintain Phase 06 allocation discipline (zero steady-state heap allocations).

## Decisions

### 1. Reuse Canonical Phase 04 Protocol and Phase 05/06 OrderBook
Instead of inventing a specialized replay format or a "ReplayOrderBook", the replay engine directly consumes `ReplayEvent` records containing Phase 04 `MarketDataHeader` and typed payloads (`OrderBookAddMessage`, `OrderBookModifyMessage`, `OrderBookDeleteMessage`, `OrderBookSnapshotMessage`, `TradeMessage`), feeding them into the canonical `rexi::order_book::OrderBook`.

### 2. Strict Total Event Ordering Contract
We formalize a total ordering contract implemented by `ReplayEventComparator`:
- Primary: Feed sequence number (`sequence_num`) when venues and feeds match.
- Secondary: Source timestamp (`source_timestamp_ns`).
- Tertiary: Gateway receive timestamp (`receive_timestamp_ns`).
- Quaternary: Venue ID and Feed ID.
- Fallback: Stable input index (`input_index`) as a tie-breaker.

### 3. Pure Deterministic ReplayClock
We implement `ReplayClock` with no dependency on wall-clock time or `std::chrono::steady_clock`. Replay time advances strictly according to incoming event timestamps. Replay semantics are invariant to host CPU speed or execution pauses.

### 4. Explicit Validation Policies: Strict vs. Permissive
We provide two explicit validation modes:
- `ValidationPolicy::Strict`: Halts replay immediately on any sequence gap, duplicate, out-of-order event, malformed message, or checksum failure.
- `ValidationPolicy::Permissive`: Records structured `ReplayDiagnostic`, rejects the corrupted event, fast-forwards sequence trackers, and continues execution without silent data loss.

### 5. Multi-Feed Sequence Tracking with Inline Cache
To preserve zero steady-state heap allocations during replay across multiple feeds, `ReplayEngine` maintains an inline fixed-capacity array of 16 `SequenceManager` instances. This eliminates dynamic allocations while tracking feed-specific sequence gaps and duplicates.

### 6. Canonical 64-Bit State Digest
To guarantee reproducible verification across test runs and independent replay engines, we implement `compute_state_digest()` utilizing 64-bit FNV-1a hashing across price levels, resting orders in FIFO order, clock state, and execution counters.

## Consequences

### Positive
- **Single Canonical Implementation**: Exactly one order book implementation exists in REXI.
- **Bit-for-Bit Determinism**: Two fresh replay runs on identical streams produce identical state digests.
- **High Throughput**: 100,000-event streams replay in ~6.07 ms (60.7 ns/event; 16.5M events/sec) on Apple Silicon Release builds.
- **Zero Steady-State Allocations**: 0 heap allocations during steady-state in-memory replay into a pre-warmed book.
- **Causal Integrity**: Zero look-ahead leakage.

### Negative / Limitations
- **In-Memory Streaming Only**: Phase 07 does not implement disk-backed storage or Parquet reading (deferred to Phase 08 Data Lake).
- **Sequential Replay**: Arbitrary non-checkpointed random-access seeking is not supported; replay is strictly forward-sequential.
