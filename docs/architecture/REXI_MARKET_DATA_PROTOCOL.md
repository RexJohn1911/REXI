# REXI Market Data Protocol Specification

**Project:** REXI — Real-time EXecution & Intelligence
**Phase:** 04 — Market Data Protocol
**Status:** Canonical / Active

---

## 1. Executive Summary & Architectural Scope

The REXI Market Data Protocol defines the strongly typed, deterministic, low-latency binary representation and processing contract for market data messages flowing through the REXI platform.

```
+-----------------------------------------------------------------------------+
|                                MARKET DATA PIPELINE                         |
|                                                                             |
|  [Source] (Simulator / Future Replay / Future Normalized Exchange Adapters) |
|      |                                                                      |
|      v                                                                      |
|  [Raw Message / Adapter Normalization] (INormalizer<Raw>)                   |
|      |                                                                      |
|      v                                                                      |
|  [MarketDataHeader + Typed Payload] (Trivially Copyable Structs)            |
|      |                                                                      |
|      +---> [Integrity Checksum] (32-bit FNV-1a Hash Verification)           |
|      |                                                                      |
|      +---> [Structural Validation] (MessageValidator: Bounds & Logic)       |
|      |                                                                      |
|      +---> [Sequence Management] (SequenceManager: Continuity / Gap / Reset)|
|      |                                                                      |
|      v                                                                      |
|  [Phase 02 Event Dispatcher] (Zero-Allocation SPSC Event Bus)               |
|      |                                                                      |
|      v                                                                      |
|  [Future Downstream Consumers: Phase 05 L2/L3 Book, Phase 07 Replay, etc.]  |
+-----------------------------------------------------------------------------+
```

### Strict Phase Boundaries
- **In Scope for Phase 04:**
  - Strongly typed market data primitives (`InstrumentId`, `VenueId`, `FeedId`, `SequenceNumber`, `Timestamp`, `Price`, `Quantity`, `OrderId`, `TradeId`).
  - Canonical 40-byte `MarketDataHeader`.
  - Fixed-size, trivially copyable message payloads (`InstrumentDefinitionMessage`, `TopOfBookMessage`, `TradeMessage`, `OrderBookAddMessage`, `OrderBookModifyMessage`, `OrderBookDeleteMessage`, `OrderBookSnapshotMessage`, `MarketStatusMessage`).
  - Deterministic 32-bit FNV-1a checksum calculation and verification (`IntegrityChecksum`).
  - Deterministic sequence validation, gap detection, duplicate filtering, and session reset handling (`SequenceManager`).
  - Structural message validation (`MessageValidator`).
  - Normalization interface (`INormalizer<Raw>`) and canonical container (`MarketDataMessage`).
  - Phase 02 event traits integration (`EventTraits` specializations for market data event IDs 20–27).
  - Exchange simulator bridge (`SimulatorMarketDataBridge`) mapping Phase 03 simulator events to canonical market data messages.
- **Strictly Out of Scope (Deferred to Future Phases):**
  - L2/L3 order book data structures and depth aggregation (Phase 05).
  - Historical market data capture and deterministic replay engine (Phase 07).
  - Real-time network sockets, WebSockets, TCP/UDP multicast feed handlers, FIX/ITCH/OUCH protocol decoders.
  - Microstructure feature generation (Phase 10), trading strategies, alpha models, ML pipelines, and order routing.

---

## 2. Strongly Typed Market Data Primitives

To eliminate type-confusion bugs and ensure compile-time type safety without runtime overhead, REXI defines explicit type aliases and enums:

| Primitive Type | Underlying Type | Semantics & Constraints |
| :--- | :--- | :--- |
| `InstrumentId` | `uint32_t` | Non-zero canonical instrument identifier. |
| `VenueId` | `uint16_t` | Identifier for the execution venue / exchange. |
| `FeedId` | `uint16_t` | Identifier for the specific feed stream within a venue. |
| `SequenceNumber` | `uint64_t` | Monotonically increasing per-feed message sequence number. |
| `Timestamp` | `uint64_t` | Nanoseconds since epoch (source, receive, or simulation clock). |
| `Price` | `int64_t` | Fixed-point integer price (scaled by tick size, no floating-point). |
| `Quantity` | `uint64_t` | Discrete order / trade quantity in lots / shares. |
| `OrderId` | `uint64_t` | Order identifier for L3 level updates. |
| `TradeId` | `uint64_t` | Unique trade identifier assigned by the venue. |

### Core Enumerations
- **`MarketDataMessageType` (`uint8_t`):**
  - `Unknown (0)`
  - `InstrumentDefinition (1)`
  - `TopOfBook (2)`
  - `Trade (3)`
  - `OrderBookAdd (4)`
  - `OrderBookModify (5)`
  - `OrderBookDelete (6)`
  - `OrderBookSnapshot (7)`
  - `MarketStatus (8)`
- **`MarketSide` (`uint8_t`):** `Unknown (0)`, `Buy (1)`, `Sell (2)`
- **`TradingStatus` (`uint8_t`):** `Unknown (0)`, `PreOpen (1)`, `Open (2)`, `Halted (3)`, `Closed (4)`
- **`ValidationStatus` (`uint8_t`):** `Valid (0)`, `InvalidVersion (1)`, `InvalidMessageType (2)`, `InvalidInstrumentId (3)`, `InvalidVenueOrFeed (4)`, `InvalidPrice (5)`, `InvalidQuantity (6)`, `InvalidBidAskSpread (7)`, `InvalidTimestamp (8)`, `InvalidSequence (9)`, `InvalidSnapshotMetadata (10)`, `InvalidChecksum (11)`, `InvalidSide (12)`, `InvalidStatus (13)`
- **`SequenceStatus` (`uint8_t`):** `Expected (0)`, `Duplicate (1)`, `Gap (2)`, `OutOfOrder (3)`, `ResetRequired (4)`
- **`ChecksumStatus` (`uint8_t`):** `NotSupplied (0)`, `Valid (1)`, `Invalid (2)`

---

## 3. Canonical Message Header Layout

The `MarketDataHeader` is exactly 40 bytes, aligned to 8 bytes, and standard layout / trivially copyable:

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|    version    |  msg_type     |     flags     |   reserved0   |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|           venue_id            |            feed_id            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                         instrument_id                         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                           checksum                            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
+                       sequence_number                         +
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
+                       source_timestamp                        +
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
+                        recv_timestamp                         +
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### Header Metadata Fields
- `version` (`uint8_t`): Current canonical protocol version (`PROTOCOL_VERSION = 1`).
- `msg_type` (`MarketDataMessageType`): Discriminant for the payload.
- `flags` (`uint8_t`): Bitmask flags (Bit 0: `FLAG_CHECKSUM_PRESENT`, Bit 1: `FLAG_SNAPSHOT_START`, Bit 2: `FLAG_SNAPSHOT_END`, Bit 3: `FLAG_POSSIBLE_DUPLICATE`).
- `reserved0` (`uint8_t`): Padding to maintain 4-byte boundary.
- `venue_id` (`VenueId`): Originating venue identifier.
- `feed_id` (`FeedId`): Feed stream identifier.
- `instrument_id` (`InstrumentId`): Canonical instrument ID.
- `checksum` (`uint32_t`): 32-bit checksum (0 if not supplied).
- `sequence_number` (`SequenceNumber`): Feed-level monotonic sequence.
- `source_timestamp` (`Timestamp`): Exchange matching-engine event nanoseconds.
- `recv_timestamp` (`Timestamp`): Local network/adapter ingress nanoseconds.

---

## 4. Message Payloads

All message payloads are fixed-size, standard-layout structs without heap allocations or pointers:

1. **`InstrumentDefinitionMessage` (48 bytes):**
   - `tick_size` (`Price`), `lot_size` (`Quantity`), `min_price` (`Price`), `max_price` (`Price`), `symbol` (`char[16]`).
2. **`TopOfBookMessage` (32 bytes):**
   - `bid_price` (`Price`), `ask_price` (`Price`), `bid_quantity` (`Quantity`), `ask_quantity` (`Quantity`).
3. **`TradeMessage` (32 bytes):**
   - `price` (`Price`), `quantity` (`Quantity`), `trade_id` (`TradeId`), `aggressor_side` (`MarketSide`), `reserved[7]`.
4. **`OrderBookAddMessage` (32 bytes):**
   - `order_id` (`OrderId`), `price` (`Price`), `quantity` (`Quantity`), `side` (`MarketSide`), `reserved[7]`.
5. **`OrderBookModifyMessage` (24 bytes):**
   - `order_id` (`OrderId`), `new_price` (`Price`), `new_quantity` (`Quantity`).
6. **`OrderBookDeleteMessage` (8 bytes):**
   - `order_id` (`OrderId`).
7. **`OrderBookSnapshotMessage` (680 bytes):**
   - Up to `MAX_SNAPSHOT_LEVELS = 16` depth levels for bids and asks.
   - `bid_levels_count` (`uint32_t`), `ask_levels_count` (`uint32_t`), `last_included_sequence` (`SequenceNumber`).
   - `bids` (`OrderBookSnapshotLevel[16]`), `asks` (`OrderBookSnapshotLevel[16]`).
8. **`MarketStatusMessage` (16 bytes):**
   - `status` (`TradingStatus`), `reserved[7]`, `halt_reason_code` (`uint64_t`).

---

## 5. Integrity Checksum Algorithm

The protocol provides deterministic packet integrity validation using the 32-bit FNV-1a (Fowler-Noll-Vo) hash algorithm:
- **Constants:** `OffsetBasis = 0x811C9DC5`, `Prime = 0x01000193`.
- **Properties:** Non-cryptographic, zero-allocation, deterministic across all platforms, low instruction count (<15 ns).
- **Semantics:**
  - When `FLAG_CHECKSUM_PRESENT` is set, `IntegrityChecksum::verify(header, payload_bytes)` checks the payload hash against `header.checksum`.
  - Returns `ChecksumStatus::Valid`, `ChecksumStatus::Invalid`, or `ChecksumStatus::NotSupplied`.

---

## 6. Sequence Validation & Gap Semantics

Market data feed continuity is enforced by `SequenceManager`:
- Tracks `expected_sequence` and `last_processed_sequence`.
- Supports configurable gap tolerance (`max_tolerated_gap`).
- **Validation Results:**
  - `Expected`: Incoming sequence == `expected_sequence`.
  - `Duplicate`: Incoming sequence < `expected_sequence`.
  - `Gap`: Incoming sequence > `expected_sequence` (records gap count and bounds).
  - `OutOfOrder`: Incompatible ordering in strict modes.
  - `ResetRequired`: Incoming sequence > `expected_sequence + max_tolerated_gap` or explicit session reset.

---

## 7. Structural Message Validation

`MessageValidator::validate(header, payload)` ensures all incoming messages adhere to protocol invariants:
- Checks protocol version (`version == PROTOCOL_VERSION`).
- Checks message type alignment and non-zero instrument identifiers.
- Checks prices (`Price >= 0` where applicable) and quantities (`Quantity > 0`).
- Checks top-of-book crossed market invariants (`ask_price > bid_price` when both sides exist).
- Checks snapshot level bounds (`levels_count <= 16`) and price ordering (bids strictly descending, asks strictly ascending).

---

## 8. Adapter Normalization Interface

Future exchange adapters (e.g., ITCH, FIX, Binance, CME) implement the clean contract:
```cpp
template <typename RawMessage>
class INormalizer {
public:
    virtual ~INormalizer() = default;
    [[nodiscard]] virtual bool normalize(const RawMessage& raw, MarketDataMessage& out_msg) = 0;
};
```
The canonical `MarketDataMessage` contains a `MarketDataHeader` and a `std::variant` of all payload types.

---

## 9. Phase 02 Event System Integration

Market data events seamlessly integrate with the Phase 02 zero-allocation event bus via `EventTraits`:
- `EventId::MarketDataTopOfBook (20)`
- `EventId::MarketDataTrade (21)`
- `EventId::MarketDataStatus (22)`
- `EventId::MarketDataSnapshot (23)`
- `EventId::MarketDataAdd (24)`
- `EventId::MarketDataModify (25)`
- `EventId::MarketDataDelete (26)`
- `EventId::MarketDataInstrument (27)`

---

## 10. Simulator Bridge

The `SimulatorMarketDataBridge` bridges Phase 03 `Exchange` simulation events to canonical market data messages:
- Dispatches `TradeExecutedPayload` $\rightarrow$ canonical `TradeMessage`.
- Dispatches `TopQuoteUpdatedPayload` $\rightarrow$ canonical `TopOfBookMessage`.
- Assigns monotonic feed sequence numbers and propagates simulation timestamps.
