#pragma once

#include <cstdint>
#include <string_view>

namespace rexi::simulator {

/**
 * @brief Fixed-point integer price representation in ticks / minimum price increments.
 *
 * Example: A price of 10025 represents $100.25 on a 0.01 tick size instrument.
 * Strictly integer-based arithmetic guarantees 100% deterministic matching comparisons.
 */
using Price = std::int64_t;

/**
 * @brief Integer quantity representation in whole share/contract lots.
 */
using Quantity = std::uint64_t;

/**
 * @brief Strongly typed unique identifier for individual orders.
 */
using OrderId = std::uint64_t;

/**
 * @brief Strongly typed identifier for tradable financial instruments.
 */
using InstrumentId = std::uint32_t;

/**
 * @brief Strongly typed identifier for client / participant sessions.
 */
using ClientId = std::uint32_t;

/**
 * @brief Strongly typed identifier for executed trades / fill matches.
 */
using ExecutionId = std::uint64_t;

/**
 * @brief Monotonic sequence counter assigned by exchange for deterministic priority.
 */
using SequenceNum = std::uint64_t;

/**
 * @brief Order side direction.
 */
enum class Side : std::uint8_t { Buy = 1, Sell = 2 };

/**
 * @brief Supported order execution types in Phase 03.
 */
enum class OrderType : std::uint8_t { Limit = 1, Market = 2 };

/**
 * @brief Deterministic order lifecycle states.
 */
enum class OrderStatus : std::uint8_t {
    New = 0,
    Accepted = 1,
    PartiallyFilled = 2,
    Filled = 3,
    Cancelled = 4,
    Rejected = 5
};

/**
 * @brief Structural exchange rejection reasons.
 */
enum class RejectReason : std::uint8_t {
    None = 0,
    SessionClosed = 1,
    UnknownInstrument = 2,
    InvalidQuantity = 3,
    InvalidPrice = 4,
    DuplicateOrderId = 5,
    OrderNotFound = 6,
    OrderNotActive = 7,
    UnsupportedOrderType = 8
};

[[nodiscard]] constexpr std::string_view to_string(Side side) noexcept {
    switch (side) {
        case Side::Buy:
            return "Buy";
        case Side::Sell:
            return "Sell";
    }
    return "InvalidSide";
}

[[nodiscard]] constexpr std::string_view to_string(OrderType type) noexcept {
    switch (type) {
        case OrderType::Limit:
            return "Limit";
        case OrderType::Market:
            return "Market";
    }
    return "InvalidOrderType";
}

[[nodiscard]] constexpr std::string_view to_string(OrderStatus status) noexcept {
    switch (status) {
        case OrderStatus::New:
            return "New";
        case OrderStatus::Accepted:
            return "Accepted";
        case OrderStatus::PartiallyFilled:
            return "PartiallyFilled";
        case OrderStatus::Filled:
            return "Filled";
        case OrderStatus::Cancelled:
            return "Cancelled";
        case OrderStatus::Rejected:
            return "Rejected";
    }
    return "InvalidOrderStatus";
}

[[nodiscard]] constexpr std::string_view to_string(RejectReason reason) noexcept {
    switch (reason) {
        case RejectReason::None:
            return "None";
        case RejectReason::SessionClosed:
            return "SessionClosed";
        case RejectReason::UnknownInstrument:
            return "UnknownInstrument";
        case RejectReason::InvalidQuantity:
            return "InvalidQuantity";
        case RejectReason::InvalidPrice:
            return "InvalidPrice";
        case RejectReason::DuplicateOrderId:
            return "DuplicateOrderId";
        case RejectReason::OrderNotFound:
            return "OrderNotFound";
        case RejectReason::OrderNotActive:
            return "OrderNotActive";
        case RejectReason::UnsupportedOrderType:
            return "UnsupportedOrderType";
    }
    return "InvalidRejectReason";
}

}  // namespace rexi::simulator
