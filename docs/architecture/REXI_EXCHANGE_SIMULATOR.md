# REXI Exchange Simulator Architecture Specification

**Project:** REXI — Real-time EXecution & Intelligence
**Phase:** 03 — Exchange Simulator
**Status:** Active

---

## 1. Executive Summary & Design Philosophy

The REXI Exchange Simulator is a deterministic, event-driven laboratory designed to test and validate future market data, strategy, execution, risk, and research components under strict, reproducible conditions.

```
+-----------------------------------------------------------------------------+
|                                 Exchange                                    |
|  +---------------------+  +---------------------+  +---------------------+  |
|  |   ExchangeSession   |  |   SimulationClock   |  |     SequenceNum     |  |
|  |  (Created/Open/Clsd)|  | (Explicit Monotonic)|  | (Monotonic Priority)|  |
|  +---------------------+  +---------------------+  +---------------------+  |
|                                    |                                        |
|                                    v                                        |
|  +-----------------------------------------------------------------------+  |
|  |                             MatchingEngine                            |  |
|  |  +-----------------------------------------------------------------+  |  |
|  |  |                 OrderBook (Per Registered Instrument)           |  |  |
|  |  |  - Bids: map<Price, deque<Order>, greater<>> (Price-Time FIFO)  |  |  |
|  |  |  - Asks: map<Price, deque<Order>, less<>>    (Price-Time FIFO)  |  |  |
|  |  |  - Order Index: unordered_map<OrderId, OrderLocation>           |  |  |
|  |  +-----------------------------------------------------------------+  |  |
|  +-----------------------------------------------------------------------+  |
|                                    |                                        |
|                                    v                                        |
|  +-----------------------------------------------------------------------+  |
|  |                    EventDispatcher (Phase 02 Integration)             |  |
|  |  - OrderAcceptedPayload    - OrderRejectedPayload                     |  |
|  |  - OrderCancelledPayload   - OrderFilledPayload                       |  |
|  |  - TradeExecutedPayload    - TopQuoteUpdatedPayload                   |  |
|  +-----------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------+
```

### Core Design Principles
1. **100% Determinism:** The simulator contains zero wall-clock timing dependencies and zero unseeded randomness. Given the exact same sequence of input commands, it produces the exact same execution events, fills, sequence numbers, and book state.
2. **Fixed-Point Price/Quantity:** Prices (`int64_t Price`) and quantities (`uint64_t Quantity`) are strictly integer multiples of minimum increments (ticks and lots), eliminating floating-point rounding drift and nondeterminism.
3. **Price-Time Priority (FIFO):** Bids are prioritized from highest price to lowest price; Asks are prioritized from lowest price to highest price. Orders at the exact same price level are executed in strict first-in-first-out order according to their exchange sequence timestamp.
4. **Resting-Order Execution Price Rule:** When an aggressive incoming order matches against a resting limit order, the execution price is determined strictly by the resting order's price.
5. **Deterministic Market Order Exhaustion:** If an aggressive market order exhausts all available opposite-side liquidity, the unfilled remainder is immediately cancelled deterministically.
6. **Zero External I/O:** The simulator does not connect to any network sockets or live broker APIs.

---

## 2. Order Lifecycle & State Machine

```
      +-----------+
      | Submitted |
      +-----------+
            |
    [Validation / Session Check]
     /                     \
    v (Invalid/Closed)      v (Valid & Open)
+----------+          +----------+
| Rejected |          | Accepted |
+----------+          +----------+
                           |
                     [MatchingEngine]
                     /      |       \
                    /       |        \
                   v        v         v
             +--------+ +----------+ +--------+
             | Filled | | PartFill | | Cancel |
             +--------+ +----------+ +--------+
```

- **`New` / `Submitted`:** Order submitted to `Exchange::submit_order()`.
- **`Rejected`:** Order rejected due to closed session, unknown instrument, duplicate Order ID, or invalid price/quantity constraints. Generates `OrderRejectedPayload`.
- **`Accepted`:** Order passed all validation rules and was assigned a monotonic sequence number (`SequenceNum`). Generates `OrderAcceptedPayload`.
- **`PartiallyFilled`:** Order matched against resting liquidity for part of its initial quantity. Generates `OrderFilledPayload`.
- **`Filled`:** Order fully satisfied (`remaining_quantity == 0`). Generates `OrderFilledPayload`.
- **`Cancelled`:** Active resting quantity successfully cancelled by client request or market order liquidity exhaustion. Generates `OrderCancelledPayload`.

---

## 3. Order Book & Matching Engine Data Structures

Each registered `Instrument` maintains an isolated `OrderBook` with:
- **Bids:** `std::map<Price, std::deque<Order>, std::greater<>>` (highest bid at `begin()`).
- **Asks:** `std::map<Price, std::deque<Order>, std::less<>>` (lowest ask at `begin()`).
- **Order Location Index:** `std::unordered_map<OrderId, OrderLocation>` for fast lookup and cancellation.

### Complexity Characteristics:
- **Best Bid / Best Ask Lookup:** $O(1)$ amortized.
- **Top Quote Inspection:** $O(1)$.
- **Order Insertion:** $O(\log L)$ where $L$ is the number of distinct price levels.
- **Order Cancellation:** $O(\log L + Q)$ where $Q$ is the queue depth at the target price level.
- **Match Execution:** $O(M)$ where $M$ is the number of matched resting orders.

---

## 4. Benchmark Performance Baseline (Apple M-Series Silicon)

| Operation | Measured Latency | Throughput |
| :--- | :--- | :--- |
| **Order Submission (Resting)** | `~508 ns` | ~1.97M orders/sec |
| **Order Cancellation** | `~417 ns` | ~2.40M cancellations/sec |
| **Single-Order Match (Crossing)** | `~454 ns` | ~2.20M matches/sec |
| **Multi-Level Sweep (5 Levels)** | `~696 ns` | ~1.44M sweeps/sec |

*Note: Benchmarks measure single-threaded in-memory simulator execution on development workstations.*

---

## 5. Scope Boundary & What Phase 03 Does NOT Implement

Phase 03 strictly implements the **deterministic exchange simulator laboratory**. It intentionally excludes:
- Real exchange network sockets, FIX engine, ITCH/OUCH protocols (Phase 04/05/06).
- Strategy logic, alpha generation, signal models (Phase 11+).
- Portfolio management and multi-asset risk engine (Phase 09/10).
- Market impact models, machine learning, or AI execution agents.
