# REXI L2/L3 Order Book Architecture Specification

**Project:** REXI — Real-time EXecution & Intelligence
**Phase:** 05 — L2/L3 Order Book
**Status:** Canonical / Active

---

## 1. Executive Summary & Design Hierarchy

The REXI Order Book subsystem provides the canonical, in-memory, deterministic state machine representing limit order resting liquidity for financial instruments. It supports Level 1 (Top of Book / BBO), Level 2 (Aggregated Market by Price), and Level 3 (Market by Order / Individual Resting Orders) operations.

```
+--------------------------------------------------------------------------------+
|                             ORDER BOOK SUBSYSTEM                               |
|                                                                                |
|  [Phase 04 Messages]     [Phase 03 Simulator]       [Direct L3 Mutations]      |
|  (Add, Modify, Delete,   (Exchange Matching         (add, cancel, reduce,      |
|   Snapshot)               Fill Reductions)           replace)                  |
|           \                      |                     /                       |
|            +---------------------+--------------------+                        |
|                                  |                                             |
|                                  v                                             |
|                     +--------------------------+                               |
|                     |  rexi::order_book::      |                               |
|                     |        OrderBook         |                               |
|                     +--------------------------+                               |
|                      /            |           \                                |
|                     /             |            \                               |
|                    v              v             v                              |
|            [Level 1 (BBO)]  [Level 2 (L2)]  [Level 3 (L3)]                     |
|            - best_bid()     - bids_depth()  - has_order()                      |
|            - best_ask()     - asks_depth()  - find_order()                     |
|            - spread()       - LevelView     - get_queue_position()             |
|            - top_quote()    - total_qty     - FIFO orders per level            |
|                             - order_count   - O(1) order_index_ lookup         |
|                                                                                |
|   [Invariants & Consistency]                                                   |
|   - level.total_quantity == sum(order.remaining_quantity for order in queue)  |
|   - level.order_count == count(orders in queue)                                |
|   - Empty price levels are instantly removed from the map                      |
|   - 100% deterministic: no wall-clock, no unseeded randomness                  |
+--------------------------------------------------------------------------------+
```

---

## 2. Market Depth Tier Definitions: L1, L2, L3

1. **Level 1 (Top of Book / BBO):**
   - Exposes highest bid price, lowest ask price, respective quantities, and current spread.
   - Access is $O(1)$ amortized by inspecting the first element of the sorted price maps.
   - If a side is empty, `best_bid()` or `best_ask()` returns `std::nullopt`. No sentinel prices are used.
2. **Level 2 (Aggregated Market Depth):**
   - Aggregates resting liquidity across discrete price levels.
   - Each level contains `price`, `total_quantity`, and `order_count`.
   - Bids are ordered strictly descending (highest to lowest).
   - Asks are ordered strictly ascending (lowest to highest).
   - Configurable depth extraction via `bids_depth(max_levels)` and `asks_depth(max_levels)`.
3. **Level 3 (Market by Order / MBO):**
   - Tracks individual resting orders (`RestingOrder`) with discrete identities (`OrderId`), initial and remaining quantities, priority sequence, and timestamps.
   - Enforces strict first-in-first-out (FIFO) queue priority within each price level.
   - Fast $O(1)$ lookup and cancellation via global `order_index_` without scanning the entire book.

---

## 3. Core Architecture & Data Layout

### Price Level Representation (`PriceLevel`)
Each price level encapsulates:
- `price_` (`Price`): Scaled fixed-point price tick.
- `total_quantity_` (`Quantity`): Aggregate volume across active orders at this price.
- `order_count_` (`uint32_t`): Number of active resting orders at this price.
- `orders_` (`std::list<RestingOrder>`): Doubly linked list preserving strict FIFO order queue.
- `is_l2_aggregate_only_` (`bool`): Flag denoting whether the level was constructed from an aggregated Phase 04 snapshot without individual L3 order identities.

### Ordered Price Ladder & Order Index
- **Bids:** `std::map<Price, PriceLevel, std::greater<Price>>`
  - Root/begin element represents the Best Bid.
- **Asks:** `std::map<Price, PriceLevel, std::less<Price>>`
  - Root/begin element represents the Best Ask.
- **Order Index:** `std::unordered_map<OrderId, OrderLocation>`
  - `OrderLocation` stores `{ Side side, Price price, PriceLevel::OrderIterator order_it }`.
  - Enables $O(1)$ direct node lookup and $O(1)$ list node erase without iterator invalidation for other resting orders.

---

## 4. Mutation Semantics & Priority Invariants

### Order Addition (`add_order`)
- Validates non-zero `OrderId`, positive `Price`, non-zero `remaining_quantity`, and matching `InstrumentId`.
- Rejects duplicate active `OrderId`s with `OrderBookStatus::DuplicateOrderId`.
- If `CrossedBookPolicy::Reject` is configured, verifies that the order does not cross the opposing top of book.
- Appends the order to the back of the appropriate price level's FIFO queue ($O(1)$).
- Updates level `total_quantity` and `order_count`.
- Records iterator in `order_index_`.

### Order Cancellation / Deletion (`cancel_order`)
- Locates order via `order_index_` in $O(1)$ time.
- Erases list node from the price level in $O(1)$ time.
- Decrements level aggregate quantity and order count.
- If the price level becomes empty (`order_count == 0`), the level is immediately removed from the price map.
- Erases order from `order_index_`.

### Execution & Quantity Reduction (`reduce_order`)
- Locates order via `order_index_` in $O(1)$ time.
- Decreases `order.remaining_quantity` and `level.total_quantity` by `executed_qty`.
- Strictly preserves the order's position in the FIFO queue (time priority is preserved).
- If remaining quantity reaches 0, the order and empty levels are removed.

### Order Modification (`modify_order`)
- **Quantity Decrease at Same Price:**
  - Preserves FIFO priority. The order remains at its existing list node position.
- **Quantity Increase at Same Price:**
  - Loses FIFO priority. The order's quantity is increased, and the node is moved to the back of the level queue via `std::list::splice` ($O(1)$).
- **Price Change (`replace_order`):**
  - Order leaves the old price level (losing old priority).
  - Empty old level is cleaned up.
  - Order is inserted at the back of the new price level's FIFO queue ($O(1)$).

---

## 5. Phase 04 Market Data Protocol Integration

`OrderBook` natively applies canonical Phase 04 wire messages:
- `apply_add(header, msg)`: Inserts resting order with sequence and timestamps from the header.
- `apply_modify(header, msg)`: Modifies or replaces order in-place.
- `apply_delete(header, msg)`: Cancels resting order.
- `apply_snapshot(snapshot)`: Reconstructs L2 aggregated price levels without fabricating synthetic L3 order identities.
- `to_phase04_snapshot(seq)`: Exports aggregated snapshot truncated to the Phase 04 protocol limit (`MaxSnapshotLevels = 10` levels per side).
- `apply_l3_snapshot(snapshot)` & `to_l3_snapshot(seq, ts)`: Native full-depth L3 serialization for deterministic checkpointing and replay.

---

## 6. Internal Invariant Validation

`OrderBook::validate()` provides full structural verification:
1. Bid levels are strictly descending; ask levels are strictly ascending.
2. Every price level has `total_quantity > 0` and `order_count > 0` (no ghost levels).
3. For all L3 levels, `total_quantity == sum(order.remaining_quantity)` and `order_count == orders.size()`.
4. Every indexed order points to the exact level and side matching its fields.
5. Total active orders in `order_index_` equals the sum of order counts across all L3 levels.
6. Zero negative prices or zero remaining quantities.
7. Locked/crossed book invariants according to `CrossedBookPolicy`.

---

## 7. Performance & Latency Profile (Apple Silicon M-series)

- **Best Bid / Best Ask Lookup:** **0.23 ns**
- **L3 Order Lookup by ID:** **0.76 ns**
- **Quantity Reduction (Fill):** **1.08 ns**
- **L2 10-Level Depth Extraction:** **66.6 ns**
- **Full Invariant Validation (100 orders):** **178 ns**
- **Snapshot Application (20 levels):** **266 ns**
- **Order Cancellation by ID:** **390 ns**
- **Order Insertion (Price level create + index):** **26.3 ns / order**

---

## 8. Architectural Boundaries
- **In Scope (Phase 05):** Single-instrument deterministic in-memory L1/L2/L3 order book, FIFO queuing, L2 aggregates, Phase 04 message application, invariant validation.
- **Deferred to Phase 06:** Specialized memory arenas, flat array price ladders, SIMD search, zero-allocation circular buffer queues.
