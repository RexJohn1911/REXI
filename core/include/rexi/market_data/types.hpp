#pragma once

#include <cstdint>
#include <string_view>

namespace rexi::market_data {

/**
 * @brief Current protocol version for wire and in-memory representation.
 */
inline constexpr std::uint16_t CurrentProtocolVersion = 1;

/**
 * @brief Fixed-point price representation in integer tick units.
 */
using Price = std::int64_t;

/**
 * @brief Integer quantity representation in whole share/contract lots.
 */
using Quantity = std::uint64_t;

/**
 * @brief Strongly typed identifier for tradable financial instruments.
 */
using InstrumentId = std::uint32_t;

/**
 * @brief Strongly typed identifier for exchange execution venues (e.g. 1=SIM, 2=NASDAQ, 3=CME).
 */
using VenueId = std::uint16_t;

/**
 * @brief Strongly typed identifier for market data channels / feeds.
 */
using FeedId = std::uint16_t;

/**
 * @brief Authoritative monotonically increasing sequence number per feed.
 */
using SequenceNumber = std::uint64_t;

/**
 * @brief Nanosecond timestamp since UNIX epoch.
 */
using Timestamp = std::uint64_t;

/**
 * @brief Strongly typed order identifier for book delta messages.
 */
using OrderId = std::uint64_t;

/**
 * @brief Strongly typed trade execution identifier.
 */
using TradeId = std::uint64_t;

/**
 * @brief Order and trade side direction.
 */
enum class MarketSide : std::uint8_t { Buy = 1, Sell = 2 };

/**
 * @brief Canonical market data message discriminator.
 */
enum class MarketDataMessageType : std::uint8_t {
    Unknown = 0,
    InstrumentDefinition = 1,
    TopOfBook = 2,
    Trade = 3,
    OrderBookAdd = 4,
    OrderBookModify = 5,
    OrderBookDelete = 6,
    OrderBookSnapshot = 7,
    MarketStatus = 8
};

/**
 * @brief Exchange and instrument trading operational status.
 */
enum class TradingStatus : std::uint8_t {
    Unknown = 0,
    PreOpen = 1,
    Open = 2,
    Halted = 3,
    Closed = 4
};

/**
 * @brief Structural message validation results.
 */
enum class ValidationStatus : std::uint8_t {
    Valid = 0,
    InvalidInstrument = 1,
    InvalidVenue = 2,
    InvalidPrice = 3,
    InvalidQuantity = 4,
    InvalidTimestamp = 5,
    InvalidSequence = 6,
    InvalidVersion = 7,
    MalformedPayload = 8,
    InvalidChecksum = 9
};

/**
 * @brief Sequence number tracking and gap detection status.
 */
enum class SequenceStatus : std::uint8_t {
    Expected = 0,
    Duplicate = 1,
    Gap = 2,
    OutOfOrder = 3,
    ResetRequired = 4
};

/**
 * @brief Message integrity verification status.
 */
enum class ChecksumStatus : std::uint8_t { NotSupplied = 0, Valid = 1, Invalid = 2 };

[[nodiscard]] constexpr std::string_view to_string(MarketSide side) noexcept {
    switch (side) {
        case MarketSide::Buy:
            return "Buy";
        case MarketSide::Sell:
            return "Sell";
    }
    return "InvalidMarketSide";
}

[[nodiscard]] constexpr std::string_view to_string(MarketDataMessageType type) noexcept {
    switch (type) {
        case MarketDataMessageType::Unknown:
            return "Unknown";
        case MarketDataMessageType::InstrumentDefinition:
            return "InstrumentDefinition";
        case MarketDataMessageType::TopOfBook:
            return "TopOfBook";
        case MarketDataMessageType::Trade:
            return "Trade";
        case MarketDataMessageType::OrderBookAdd:
            return "OrderBookAdd";
        case MarketDataMessageType::OrderBookModify:
            return "OrderBookModify";
        case MarketDataMessageType::OrderBookDelete:
            return "OrderBookDelete";
        case MarketDataMessageType::OrderBookSnapshot:
            return "OrderBookSnapshot";
        case MarketDataMessageType::MarketStatus:
            return "MarketStatus";
    }
    return "InvalidMarketDataMessageType";
}

[[nodiscard]] constexpr std::string_view to_string(TradingStatus status) noexcept {
    switch (status) {
        case TradingStatus::Unknown:
            return "Unknown";
        case TradingStatus::PreOpen:
            return "PreOpen";
        case TradingStatus::Open:
            return "Open";
        case TradingStatus::Halted:
            return "Halted";
        case TradingStatus::Closed:
            return "Closed";
    }
    return "InvalidTradingStatus";
}

[[nodiscard]] constexpr std::string_view to_string(ValidationStatus status) noexcept {
    switch (status) {
        case ValidationStatus::Valid:
            return "Valid";
        case ValidationStatus::InvalidInstrument:
            return "InvalidInstrument";
        case ValidationStatus::InvalidVenue:
            return "InvalidVenue";
        case ValidationStatus::InvalidPrice:
            return "InvalidPrice";
        case ValidationStatus::InvalidQuantity:
            return "InvalidQuantity";
        case ValidationStatus::InvalidTimestamp:
            return "InvalidTimestamp";
        case ValidationStatus::InvalidSequence:
            return "InvalidSequence";
        case ValidationStatus::InvalidVersion:
            return "InvalidVersion";
        case ValidationStatus::MalformedPayload:
            return "MalformedPayload";
        case ValidationStatus::InvalidChecksum:
            return "InvalidChecksum";
    }
    return "InvalidValidationStatus";
}

[[nodiscard]] constexpr std::string_view to_string(SequenceStatus status) noexcept {
    switch (status) {
        case SequenceStatus::Expected:
            return "Expected";
        case SequenceStatus::Duplicate:
            return "Duplicate";
        case SequenceStatus::Gap:
            return "Gap";
        case SequenceStatus::OutOfOrder:
            return "OutOfOrder";
        case SequenceStatus::ResetRequired:
            return "ResetRequired";
    }
    return "InvalidSequenceStatus";
}

[[nodiscard]] constexpr std::string_view to_string(ChecksumStatus status) noexcept {
    switch (status) {
        case ChecksumStatus::NotSupplied:
            return "NotSupplied";
        case ChecksumStatus::Valid:
            return "Valid";
        case ChecksumStatus::Invalid:
            return "Invalid";
    }
    return "InvalidChecksumStatus";
}

}  // namespace rexi::market_data
