# ADR-0002: Core Event Architecture & Concurrency Model

**Status:** Accepted
**Date:** 2026-10-06
**Deciders:** REXI Lead Architecture Team
**Consulted:** Core HFT & Microstructure Engineering

---

## 1. Context and Problem Statement

High-frequency algorithmic trading systems require an internal messaging substrate capable of moving hundreds of thousands of events per second with sub-microsecond determinism. Common general-purpose designs (such as dynamic polymorphism with heap-allocated smart pointers, or heavy unbounded MPMC mutex-locked queues) introduce non-deterministic garbage collection delays, lock contention, and cacheline invalidation.

## 2. Decision Drivers

- Zero dynamic heap allocation during runtime event processing.
- Strict deterministic ordering and strongly typed message routing.
- High cache locality with 64-byte alignment to prevent false sharing across CPU cores.
- Explicit memory-ordering semantics (`acquire`/`release`) for lock-free queues.
- Total absence of trading business logic in foundational messaging layers.

## 3. Considered Options

- **Option 1: Dynamic Polymorphic Event Bus (`std::shared_ptr<IEvent>`)**: Flexible, but incurs heap allocations, atomic ref-count contention, and virtual table indirection.
- **Option 2: Generic Multi-Producer Multi-Consumer (MPMC) Queue**: Complex, prone to high contention on concurrent head/tail modifications.
- **Option 3: Bounded Lock-Free SPSC Ring Buffer + Strongly Typed Direct EventDispatcher**: Flat, cache-aligned, wait-free ring buffer with compile-time type dispatch.

## 4. Decision Outcome

**Chosen Option:** **Option 3 (Bounded Lock-Free SPSC + Strongly Typed EventDispatcher)**.

### Architectural Rules:
1. **Event Header:** Fixed 24-byte header aligned to 8 bytes containing `EventType`, `SourceId`, `flags`, `sequence_num`, and `timestamp_ns`.
2. **Payload Contracts:** Payloads must satisfy `std::is_trivially_copyable_v<T>` and `std::is_standard_layout_v<T>`.
3. **Queue Topology:** Single-Producer Single-Consumer (`SpscRingBuffer<T, Capacity>`) with power-of-2 capacity, masked indexing, and cached index reads.
4. **Memory Ordering:** Acquire/Release synchronization on tail/head indices; relaxed ordering on private cached indices.

## 5. Consequences

### Positive:
- Zero dynamic memory allocation on event creation, queueing, and dispatch.
- Single-subscriber direct dispatch latency under 1 nanosecond.
- Total immunity from false sharing through 64-byte hardware destructive interference padding.
- ThreadSanitizer verified with 0 data races under 500,000-message stress workloads.

### Negative / Trade-offs:
- SPSC topology requires dedicated point-to-point queues when multiple producers communicate with a single consumer (will be scaled cleanly in subsequent phases).
- Payloads are bounded to fixed-size trivially copyable structures.
