# REXI Core Event Architecture Specification

**Project:** REXI — Real-time EXecution & Intelligence
**Phase:** 02 — Core Event Architecture
**Status:** Active

---

## 1. Executive Summary & Design Tenets

The REXI Core Event Architecture provides the strongly typed, deterministic, and allocation-conscious communication backbone connecting internal components of the high-frequency trading platform.

```
+-------------------------------------------------------------------------+
|                              Event Envelope                             |
|  +-------------------------------------------------------------------+  |
|  | EventHeader (24 Bytes, 8-Byte Aligned)                            |  |
|  | [EventType: uint16] [SourceId: uint16] [Flags: uint32]            |  |
|  | [SequenceNum: uint64] [TimestampNs: uint64]                       |  |
|  +-------------------------------------------------------------------+  |
|  | Typed Payload (Trivially Copyable Struct)                         |  |
|  +-------------------------------------------------------------------+  |
+-------------------------------------------------------------------------+
                                   |
         +-------------------------+-------------------------+
         |                                                   |
         v                                                   v
+-----------------------------+             +-----------------------------+
|    Synchronous Dispatch     |             |  Asynchronous SPSC Queue    |
|   (Direct EventDispatcher)  |             |  (Wait-Free Ring Buffer)    |
|  - Zero Allocation          |             |  - 64-Byte Cache Padding    |
|  - < 1.0 ns per subscriber  |             |  - Acquire / Release Sync   |
+-----------------------------+             +-----------------------------+
```

### Core Design Rules
1. **Zero Heap Allocation:** Event creation, queueing, and dispatching perform zero dynamic memory allocation on the active path.
2. **Explicit Lifetime & Ownership:** Events are value-typed and trivially copyable. `std::shared_ptr` is strictly forbidden in event transport.
3. **Deterministic Dispatch:** Subscribers are invoked strictly in registration order. Zero string parsing or runtime reflection in dispatch loops.
4. **Hardware-Conscious Concurrency:** Producer and consumer indices reside on separate 64-byte cache lines to eliminate cacheline bouncing and false sharing.

---

## 2. Event Structure & Layout

### Standardized `EventHeader` (24 Bytes)

```cpp
struct alignas(8) EventHeader {
    EventType type{EventType::Unknown};   // 2 Bytes
    SourceId source{SourceId::Unknown};   // 2 Bytes
    uint32_t flags{0};                    // 4 Bytes
    uint64_t sequence_num{0};             // 8 Bytes
    TimestampNs timestamp_ns{0};          // 8 Bytes
};
```

- **`type`:** Strongly typed 16-bit identifier mapped directly to dispatch lookup tables.
- **`source`:** Strongly typed attribution identifier (`Internal`, `Simulator`, `Engine`, etc.).
- **`flags`:** Bitmask reserved for event routing (e.g., synchronous, replayed, priority).
- **`sequence_num`:** Strictly monotonic sequence counter.
- **`timestamp_ns`:** Nanoseconds since epoch from monotonic clock (`MonotonicClock::now_ns()`).

### Strongly Typed `Event<Payload>`
```cpp
template <typename Payload>
struct alignas(8) Event {
    static_assert(std::is_trivially_copyable_v<Payload>,
                  "Payload must be trivially copyable for zero-allocation transport");
    EventHeader header;
    Payload payload;
};
```

---

## 3. Concurrency Model: Bounded SPSC Ring Buffer

For asynchronous inter-thread event handoff, REXI utilizes a bounded, wait-free Single-Producer Single-Consumer (`SpscRingBuffer<T, Capacity>`) ring buffer.

### Synchronization Rationale:
- **Producer:**
  1. Reads `write_index_` with `memory_order_relaxed`.
  2. Compares against local cached `cached_read_index_`. If capacity is exceeded, refreshes `read_index_` with `memory_order_acquire`.
  3. Writes item directly to `buffer_[write_index & Mask]`.
  4. Stores updated `write_index_` with `memory_order_release` to ensure payload bytes are committed to memory before the consumer observes the new index.
- **Consumer:**
  1. Reads `read_index_` with `memory_order_relaxed`.
  2. Compares against local cached `cached_write_index_`. If empty, refreshes `write_index_` with `memory_order_acquire`.
  3. Copies payload from `buffer_[read_index & Mask]`.
  4. Stores updated `read_index_` with `memory_order_release`.

### Cacheline Isolation:
Producer write indices and Consumer read indices are partitioned using `alignas(64)` padding, preventing false sharing across CPU cores.

---

## 4. Benchmark Performance Baseline (Apple M-Series Silicon)

| Operation | Measured Latency | Throughput |
| :--- | :--- | :--- |
| **Event Construction** | `~12.5 ns` | ~80M events/sec |
| **Single-Subscriber Dispatch** | `~0.92 ns` | > 1.0B events/sec |
| **4-Subscriber Dispatch** | `~2.99 ns` | ~330M events/sec |
| **SPSC Queue Push/Pop** | `~2.24 ns` | ~440M operations/sec |
| **EventBus Sync Publish** | `~1.16 ns` | ~860M events/sec |

*Note: Benchmarks measure local in-memory harness throughput on development workstations and are configuration-dependent.*

---

## 5. Scope Boundaries & What Phase 02 Does NOT Implement

Phase 02 intentionally implements **only the event/messaging foundation**. It does not implement:
- Market data decoders or book feeds (Phase 04/05).
- Exchange simulation logic or order matching (Phase 03).
- Trading strategies, alphas, risk engines, or portfolio logic (Phase 11+).
