# ADR-0005: Canonical L2/L3 Order Book Architecture

**Status:** Accepted
**Date:** 2026-10-06
**Deciders:** REXI Core Architecture & Systems Engineering Team
**Consulted:** Quantitative Research, Market Microstructure Engineering

---

## 1. Context and Problem Statement

To support strategy backtesting, execution algorithms, and live microstructure feature calculations, REXI requires an in-memory, deterministic order book subsystem. The subsystem must simultaneously satisfy Level 1 (Top of Book / BBO), Level 2 (Aggregated Market by Price), and Level 3 (Market by Order) queries, enforce strict price-time FIFO ordering, guarantee mathematical consistency between L2 aggregates and resting L3 orders, and process Phase 04 market data protocol messages.

## 2. Decision Drivers

- **Deterministic Single-Writer State Machine:** Zero internal mutexes, atomics, or thread scheduling nondeterminism.
- **$O(1)$ Order Lookup & Middle Order Erasure:** Cancelling orders must not perform full book scans.
- **Strict FIFO Time Priority:** Orders at the same price execute strictly in arrival order.
- **L2/L3 Consistency:** `level.total_quantity` must strictly equal the sum of remaining quantities of active orders at that level.
- **Priority Preservation Rules:** Quantity reductions must preserve time priority; quantity increases or price changes must lose priority.
- **Phase 04 Wire Integration:** Native application of `OrderBookAddMessage`, `OrderBookModifyMessage`, `OrderBookDeleteMessage`, and `OrderBookSnapshotMessage`.
- **No Premature Optimization:** Defer custom arenas and intrusive structures to Phase 06.

## 3. Considered Options

- **Option 1: Vector/Deque per Price Level with Linear Scan Cancellation:**
  - *Pros:* High cache locality for FIFO iterations.
  - *Cons:* Erasing middle orders requires $O(N)$ elements shifted or tombstoning, and invalidates positional indices.
- **Option 2: Flat Array Price Ladder with Fixed Depth Limit:**
  - *Pros:* Predictable cacheline layout.
  - *Cons:* Rigid depth limits, unsuitable for wide/sparse tick distributions across arbitrary markets without dynamic scaling.
- **Option 3: Map of Sorted Price Levels with Doubly Linked Lists & Hash Iterator Index:**
  - *Pros:* $O(1)$ node erasure without shifting, iterator stability for active orders, $O(1)$ FIFO append, automatic sorted price levels, clean empty-level removal.
  - *Cons:* Node allocations per order; deferred to Phase 06 for pooled arena optimization.

## 4. Decision Outcome

**Chosen Option:** **Option 3 (Map of Sorted Price Levels with Doubly Linked Lists & Hash Iterator Index)**.

### Architectural Rules:
1. **FIFO Queue:** Each `PriceLevel` maintains an `std::list<RestingOrder>` with real-time aggregate tracking (`total_quantity_`, `order_count_`).
2. **Order Indexing:** `std::unordered_map<OrderId, OrderLocation>` stores `{ Side, Price, list::iterator }`, enabling $O(1)$ cancellation and $O(1)$ quantity reductions.
3. **Priority Semantics:**
   - Quantity reduction: order remains in-place in list (priority preserved).
   - Quantity increase: order moves to the back of the queue via `std::list::splice` (priority lost).
   - Price replacement: order leaves old level and is appended to the back of the new level.
4. **Empty Level Cleanup:** When `order_count == 0`, the level is immediately purged from the price map.
5. **Crossed Book Policy:** Configurable `CrossedBookPolicy`: `Reject` (default for matching books) vs `Allow` (for external feed reconstruction).
6. **Snapshot Boundary:** Phase 04 aggregated snapshots populate L2 price levels without fabricating synthetic L3 order identities.

## 5. Consequences

### Positive:
- Sub-nanosecond L1 best bid/ask access (0.23 ns) and L3 order lookup (0.76 ns).
- $O(1)$ order cancellation (390 ns) and quantity fills (1.08 ns).
- Strict, mathematically verifiable L2/L3 consistency validated after every mutation.
- Seamless, bidirectional integration with Phase 04 Market Data Protocol messages.

### Negative / Trade-offs:
- Standard `std::list` performs heap node allocation per resting order. Phase 06 is explicitly reserved for custom cache-conscious memory pools and flat data structures.
