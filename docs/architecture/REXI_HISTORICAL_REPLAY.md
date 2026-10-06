# REXI Historical Market Replay Architecture

## 1. Executive Summary

Phase 07 establishes the canonical **Historical Market Replay Subsystem** for REXI. The replay subsystem provides deterministic, reproducible playback of recorded historical market data packet streams through the canonical Phase 04 market-data protocol, maintaining exact order book state within the Phase 05/06 high-performance `OrderBook`.

The replay engine is a foundational simulation layer. It is explicitly:
- **NOT a strategy backtester** (backtesting strategy APIs are deferred to Phase 18+)
- **NOT an execution or PnL engine** (order routing and portfolio valuation are deferred to later phases)
- **NOT a research data lake** (Parquet/Arrow storage catalogs belong to Phase 08)
- **NOT a stochastic simulator** (reproduces deterministic historical sequences bit-for-bit)

---

## 2. Core Architecture & Component Pipeline

The historical replay subsystem follows a strictly causal, zero-lookahead pipeline:

```
+-------------------------------------------------------+
|             Historical Event Stream                   |
| (Contiguous ReplayEvents, In-Memory or Synthetic)     |
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|               Replay Reader (IReplayReader)           |
| (InMemoryReplayReader: zero-allocation iteration)     |
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|         Stream Validation & Ordering Check            |
|  - Phase 04 MessageValidator (Header & Payload)       |
|  - Phase 04 SequenceManager (Per-feed tracking)       |
|  - Phase 04 IntegrityChecksum (FNV-1a verification)   |
|  - Policy: Strict (halt) vs Permissive (diagnostic)   |
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|              Replay Clock (ReplayClock)               |
|  - Monotonic historical timestamp advancement         |
|  - Zero wall-clock dependency                         |
|  - Tracks event index, current, previous, elapsed     |
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|      Canonical OrderBook (Phase 05/06 Integration)    |
|  - apply_add(header, add_msg)                         |
|  - apply_modify(header, mod_msg)                      |
|  - apply_delete(header, del_msg)                      |
|  - apply_snapshot(snapshot_msg)                       |
|  - reduce_order(maker_order_id, trade_qty)            |
|  - Preserves L1, L2, L3 state & 0 steady-state allocs |
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|         Deterministic Output & Dispatch               |
|  - Optional Phase 02 EventDispatcher notification     |
|  - Canonical 64-bit FNV-1a State Digest               |
|  - ReplayResult (statistics, BBO, diagnostics)        |
+-------------------------------------------------------+
```

---

## 3. Replay Event Representation (`ReplayEvent`)

Located in [replay_event.hpp](file:///Users/rexjohnabraham/Documents/REXI/core/include/rexi/replay/replay_event.hpp), `ReplayEvent` is an 8-byte aligned, trivially copyable record envelope:

- **Canonical Header**: Phase 04 `MarketDataHeader` (40 bytes: protocol version, message type, venue, feed, instrument, checksum, sequence number, source/receive timestamps).
- **Source Identity**: Phase 02 `SourceId`.
- **Input Index**: Monotonically assigned 64-bit input index for deterministic tie-breaking.
- **Typed Payload Variant**: `ReplayPayload` (`std::variant` over all canonical Phase 04 messages: `OrderBookAddMessage`, `OrderBookModifyMessage`, `OrderBookDeleteMessage`, `OrderBookSnapshotMessage`, `TradeMessage`, `TopOfBookMessage`, `MarketStatusMessage`, `InstrumentDefinitionMessage`).
- **Memory Footprint**: Fixed bounded size (~528 bytes for up to 10-level snapshots), zero heap allocations.

---

## 4. Total Event Ordering Contract

Historical market data often contains multiple streams, retransmissions, and out-of-order packets. The replay engine establishes an explicit total ordering via `ReplayEventComparator`:

1. **Authoritative Feed Sequence Number**: For matching venues and feeds (`lhs.venue_id == rhs.venue_id && lhs.feed_id == rhs.feed_id`), sequence continuity is primary when `sequence_num > 0`.
2. **Historical Source Timestamp**: Nanosecond timestamp assigned at exchange matching engine.
3. **Receive Timestamp**: Gateway/recorder arrival timestamp.
4. **Feed Identifiers**: `VenueId` followed by `FeedId`.
5. **Sequence Number Tie-Breaker**: For events across different feeds with identical timestamps.
6. **Stable Input Index Fallback**: Monotonically assigned `input_index` ensuring bit-for-bit reproducible tie-breaking across compilers, platforms, and runs.

---

## 5. Replay Clock (`ReplayClock`)

Located in [replay_clock.hpp](file:///Users/rexjohnabraham/Documents/REXI/core/include/rexi/replay/replay_clock.hpp):
- **Zero Wall-Clock Dependency**: Replay semantics do not consult `std::chrono::steady_clock` or `std::chrono::system_clock`.
- **State Exposed**:
  - `current_time_ns()` / `now_ns()`: Current event timestamp.
  - `previous_time_ns()`: Preceding event timestamp.
  - `first_time_ns()`: Stream baseline timestamp.
  - `event_index()`: Processed event counter.
  - `elapsed_replay_time_ns()`: Historical nanoseconds elapsed since stream start.
- **Modes Supported**:
  - **Step Mode**: Exactly one event advanced per `step()` invocation.
  - **Max Speed Mode**: Events processed back-to-back at hardware maximum throughput.
  - **Time Scaled Mode**: Optional configuration pacing (rate limiting) for dashboard/inspection without altering ordering or state.

---

## 6. Stream Validation & Sequence Policy

Replay reuses the Phase 04 validation components:
- `rexi::market_data::MessageValidator`: Validates header version, sequence > 0, instrument ID, crossed prices, and payload bounds.
- `rexi::market_data::SequenceManager`: Tracks sequence numbers independently per feed (`venue_id`, `feed_id`). An inline fixed cache of 16 feeds guarantees zero heap allocations for multi-feed streams.
- `rexi::market_data::IntegrityChecksum`: Verifies FNV-1a checksums if enabled.

### Validation Policies:
- **`ValidationPolicy::Strict`**: Halts replay immediately on any malformed message, sequence gap, duplicate, or out-of-order packet.
- **`ValidationPolicy::Permissive`**: Records structured `ReplayDiagnostic`, rejects the malformed packet, fast-forwards sequence manager if gap detected, and continues stream processing.

---

## 7. Initial State & Snapshot Handling

The replay engine supports:
1. **Initial Snapshot**: Applies an `OrderBookSnapshotMessage` (or L3 snapshot) atomically, resetting resting orders and establishing the sequence baseline (`seq_mgr.fast_forward(last_included_sequence + 1)`).
2. **Incremental Stream**: Subsequent L3/L2 delta events continue from the snapshot baseline.
3. **Pre-Initialized Book**: A pre-populated `OrderBook` can be supplied to `ReplayEngine` constructor.

---

## 8. Deterministic State Digest

To verify reproducible replay across runs, platforms, and engines, [replay_result.hpp](file:///Users/rexjohnabraham/Documents/REXI/core/include/rexi/replay/replay_result.hpp) computes a canonical 64-bit FNV-1a digest (`DeterministicStateHasher`):
- Instrument ID
- Clock event index, current timestamp, processed count
- Best bid/ask prices and quantities
- Total resting order count
- Canonical traversal of all bids (highest price to lowest) and asks (lowest price to highest)
- Canonical FIFO order iteration for every resting order (`order_id`, `side`, `price`, `remaining_quantity`, `priority_seq`)

Two independent replay runs with identical inputs produce identical state digests.

---

## 9. Performance & Allocation Profile

- **Steady-State Allocations**: **0 dynamic heap allocations** verified during in-memory stream replay into a pre-warmed book (`ScopedAllocationGuard`).
- **Throughput**: ~44.3M events/sec in 1,000-event batches (22.5 ns/event) and ~16.5M events/sec in 100,000-event runs (60.7 ns/event) on Apple Silicon Release builds.
- **Concurrency**: Sequential, single-threaded, cache-coherent design ensuring 100% determinism.
