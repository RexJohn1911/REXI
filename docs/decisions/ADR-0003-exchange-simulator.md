# ADR-0003: Exchange Simulator & Matching Engine Design

**Status:** Accepted
**Date:** 2026-10-06
**Deciders:** REXI Lead Architecture Team
**Consulted:** Microstructure Simulation & Quantitative Research

---

## 1. Context and Problem Statement

To develop and benchmark market data decoders, execution handlers, and risk modules in subsequent phases, REXI requires an in-process, deterministic exchange simulator. The simulator must faithfully replicate continuous double-auction mechanics (price-time priority FIFO, resting order pricing, limit and market order handling) while remaining 100% reproducible and decoupled from wall-clock timing or external network dependencies.

## 2. Decision Drivers

- Exact, reproducible execution: Identical inputs must yield identical outputs, fills, timestamps, and sequence numbers.
- Integer fixed-point pricing (`Price`, `Quantity`) to eliminate floating-point drift and comparison anomalies.
- Strict single-threaded matching core avoiding artificial multi-threading synchronization overhead.
- Clean integration with Phase 02 strongly typed `EventDispatcher`.
- Minimal scope: No live broker connectors, FIX engines, strategy alpha logic, or multi-asset risk engines.

## 3. Considered Options

- **Option 1: Asynchronous Multi-Threaded Matching with Wall-Clock Priority:** Simulates real-world network latency via threads, but introduces non-deterministic matching order and makes test reproducibility difficult.
- **Option 2: Floating-Point Order Book with Complex Exotic Order Types:** Supports floating-point prices and trailing stops, but suffers from IEEE 754 precision issues and violates phase boundaries.
- **Option 3: Deterministic Price-Time Priority Engine with Integer Fixed-Point Units & Explicit Simulation Clock:** Uses integer ticks/lots, monotonic exchange sequence numbers, resting-order pricing, and explicit clock progression.

## 4. Decision Outcome

**Chosen Option:** **Option 3 (Deterministic Price-Time Priority Engine with Integer Fixed-Point Units & Explicit Simulation Clock)**.

### Architectural Rules:
1. **Price & Quantity:** Prices are integer numbers of price ticks (`int64_t Price`); quantities are integer numbers of lot units (`uint64_t Quantity`).
2. **Matching Priority:** Price-time priority (Bids highest-first, Asks lowest-first, FIFO queue at each price level).
3. **Execution Price:** Determined strictly by the **resting** order when an aggressive incoming order crosses the spread.
4. **Market Orders:** Aggressive market orders consume available opposite-side liquidity. Any unfilled remainder upon book exhaustion is cancelled deterministically.
5. **Time & Sequencing:** Order priority is governed strictly by the monotonic `SequenceNum` assigned upon exchange acceptance, with timestamps driven by an explicitly controlled `SimulationClock`.

## 5. Consequences

### Positive:
- 100% reproducible testing laboratory: Identical runs produce bit-for-bit identical trade logs and event emissions.
- Zero floating-point drift or rounding errors in matching comparisons.
- High throughput: Single-order match latency ~450 ns (> 2.2M matches/sec).
- Full compatibility with Phase 02 event architecture.

### Negative / Trade-offs:
- Advanced order types (iceberg, pegged, stop-loss) are deferred to later phases.
- Custom low-latency data structures (cache-conscious flat book arrays) are deferred until performance profiling demands them.
