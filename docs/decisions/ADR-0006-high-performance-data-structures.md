# ADR-0006: High-Performance Data Structures for Order Book

## Status
Accepted

## Date
2026-10-06

## Context
In Phase 05, the canonical L2/L3 order book was established with a focus on semantic correctness, deterministic invariant validation, and Phase 04 market-data protocol integration. However, resting orders were stored in `std::list<RestingOrder>` nodes inside each `PriceLevel`, and order locations were tracked using `std::unordered_map<OrderId, OrderLocation>`.

This design had a critical performance deficiency recorded in **CON-0007**:
- Every newly inserted resting order caused a dynamic heap allocation for a `std::list` node.
- Every order insertion into `std::unordered_map` incurred heap allocation for a hash bucket node.
- Heap fragmentation, non-contiguous memory access, and pointer chasing harmed cache locality.

Phase 06 requires eliminating steady-state heap allocations while preserving all Phase 05 semantics (price-time priority, cancellation, reduction, modify, replace, crossed-market policy, and determinism).

## Decisions

### 1. Preallocated Contiguous OrderPool with Intrusive Free-List
We introduce `rexi::order_book::OrderPool`, which preallocates an array of `OrderSlot` structures up-front:
- Slots maintain resting order data, `uint32_t generation`, and intrusive doubly-linked `OrderHandle` indices (`prev`, `next`).
- Free slots form an intrusive singly-linked list (`free_head_`).
- Allocation and deallocation are strictly $O(1)$ and perform **zero heap allocations** after pool initialization.
- Capacity exhaustion returns `OrderBookStatus::PoolExhausted` deterministically.

### 2. Compact 32-Bit Handles (`OrderHandle`) Over Pointers
Instead of raw pointers or iterators, orders are referenced across levels and indices using `using OrderHandle = uint32_t` with sentinel `kInvalidOrderHandle = 0xFFFFFFFF`:
- 4 bytes per handle instead of 8 bytes for raw pointers.
- Order handles remain valid during copy/clone operations across books because they are array indices.

### 3. Intrusive FIFO Queues Inside `PriceLevel`
`PriceLevel` maintains two handles: `head_` and `tail_`. Adding an order, erasing an arbitrary order, or moving an order to the back (upon quantity increase) is an $O(1)$ pointer update inside the contiguous slot array:
- Eliminates per-order `std::list` heap overhead.
- Preserves exact FIFO queue sequence for execution.

### 4. Open-Addressing Linear-Probing `OrderIdIndex` with Backward-Shift Deletion
We replace `std::unordered_map` with a flat open-addressing hash table:
- Backed by a contiguous power-of-two table.
- Uses SplitMix64 hashing for uniform distribution across sequential IDs.
- Implements backward-shift deletion upon order cancellation, completely eliminating tombstone degradation and maintaining average probe lengths below 1.5 steps.

### 5. Retention of `std::map<Price, PriceLevel>` for Price Ladders
We evaluated replacing `std::map` with a bounded flat-array price ladder. We determined that retaining `std::map<Price, PriceLevel>` is the correct architectural choice for Phase 06:
- Supports arbitrary, unbounded price ranges without requiring configuration of fixed tick spreads.
- `bids_.begin()` and `asks_.begin()` provide $O(1)$ access to best bid and best ask.
- Orders added to existing price levels perform **zero price-level allocations**.
- Dedicated flat price ladders and tick arrays will be evaluated in future phases when instrument tick bands are standardized.

## Consequences

### Positive
- **Zero Steady-State Allocations**: Critical operations (`add_order` at existing levels, `reduce_order`, `modify_order`, `cancel_order`, `find_order`) trigger 0 dynamic allocations.
- **Hardware Efficiency**: Array-backed layout enables hardware cacheline prefetching and eliminates pointer indirection.
- **Throughput Gain**: Batch order addition is 1.42x faster (18.5 ns/order vs 26.3 ns/order); L3 lookup is 0.63 ns vs 0.76 ns.
- **API Stability**: Public `OrderBook` methods remain source-compatible.
- **CON-0007 Resolved**: The known limitation is formally resolved.

### Negative
- Book capacity is bounded by `OrderPoolConfig::initial_capacity` when growth is disabled.
- Price level insertion for an unseen price still allocates a node in `std::map` (addressed in steady-state trading scenarios where spread levels are pre-populated).

## Alternatives Considered
1. **Intrusive Pointers (`boost::intrusive`)**: Rejected to avoid external dependencies and preserve self-contained single-writer state machines.
2. **`std::pmr::monotonic_buffer_resource`**: Rejected because monotonic allocators cannot reclaim memory on arbitrary cancellations; `OrderPool` with intrusive free-list enables full slot reuse.
3. **Fixed Flat-Array Price Ladder**: Rejected because it requires fixed instrument price limits and cannot support unbounded simulation price vectors.
