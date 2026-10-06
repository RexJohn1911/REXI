# ADR-0004: Market Data Protocol Architecture

**Status:** Accepted
**Date:** 2026-10-06
**Deciders:** REXI Core Architecture & Systems Engineering Team
**Consulted:** Microstructure Engineering, Quantitative Research

---

## 1. Context and Problem Statement

Downstream components (Phase 05 L2/L3 Order Book, Phase 07 Historical Replay, Phase 10 Microstructure Features, Strategy & Execution Engines) require a normalized, strongly typed, low-latency, and deterministic market data protocol. The protocol must cleanly decouple feed-specific encoding formats (e.g., ITCH, FIX, JSON, proprietary binary) from internal processing, support deterministic sequence gap detection and checksum validation, and avoid premature serialization overheads or dynamic heap allocations.

## 2. Decision Drivers

- **Zero Heap Allocations:** Fixed-size, trivially copyable message payloads suitable for SPSC ring buffers and cache-friendly transport.
- **Strict Determinism:** Sequence numbers, integer fixed-point prices, and explicit timestamps dictate ordering; no wall-clock or non-deterministic ordering.
- **Explicit Protocol Versioning & Integrity:** 40-byte aligned header with explicit protocol version, message type discriminant, and 32-bit FNV-1a checksum support.
- **Non-Existent Heap / Variant Simplicity:** Native C++ representation without bulky external serialization frameworks (no Protobuf/FlatBuffers/Cap'n Proto).
- **Clean Phase Boundaries:** Zero order book data structures, zero live network sockets, zero WebSockets or FIX network connections in this phase.

## 3. Considered Options

- **Option 1: Dynamic Serialization Framework (Protobuf / FlatBuffers / Cap'n Proto):**
  - *Pros:* Cross-language serialization out-of-the-box, schema reflection.
  - *Cons:* Schema compilation overhead, runtime overhead, external dependency baggage, non-trivial memory layout in hot paths.
- **Option 2: Polymorphic OOP Message Hierarchy (`std::shared_ptr<IMarketDataMessage>`):**
  - *Pros:* Easy subclassing for new exchange message types.
  - *Cons:* Dynamic heap allocation per message, cache misses, pointer chasing, vtable overhead in low-latency paths.
- **Option 3: Flat, Trivially Copyable C++ Value Structs with Standard Header & SPSC Event Dispatch:**
  - *Pros:* 40-byte compact header, zero-allocation SPSC ring buffer compatibility, trivially copyable payloads, deterministic FNV-1a hash verification, standard layout.
  - *Cons:* Snapshot payloads are bounded to a fixed maximum depth (e.g., 16 levels) for flat structs.

## 4. Decision Outcome

**Chosen Option:** **Option 3 (Flat, Trivially Copyable C++ Value Structs with Standard Header & SPSC Event Dispatch)**.

### Architectural Invariants:
1. **Header Layout:** Exactly 40 bytes, aligned to 8 bytes, containing protocol version, message type, flags, venue/feed/instrument IDs, checksum, sequence number, source timestamp, and receive timestamp.
2. **Fixed-Point Primitives:** Prices are `int64_t Price`; quantities are `uint64_t Quantity`.
3. **Integrity Validation:** 32-bit FNV-1a non-cryptographic checksum algorithm for fast deterministic packet hashing.
4. **Sequence & Gap Handling:** `SequenceManager` evaluates every incoming message against expected sequence numbers and provides typed statuses (`Expected`, `Duplicate`, `Gap`, `OutOfOrder`, `ResetRequired`).
5. **Phase 02 Integration:** All market data message types specialize `EventTraits` with unique `EventId`s (20–27) for zero-allocation dispatch.

## 5. Consequences

### Positive:
- Sub-nanosecond construction (<1 ns) and ultra-low validation latency (<0.3 ns).
- Direct compatibility with Phase 02 lock-free SPSC queues.
- 100% deterministic test reproducibility across multiple pipelines.
- Clean bridge for Phase 03 Exchange Simulator trade and quote events.

### Negative / Trade-offs:
- OrderBookSnapshot is limited to 16 bid/ask levels in the flat message format; deeper historical dumps will require multi-packet chunking or dedicated snapshot channels in Phase 05/07.
