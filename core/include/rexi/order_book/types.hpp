#pragma once

#include "rexi/market_data/types.hpp"

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

namespace rexi::order_book {

// Reuse canonical primitive types from market_data
using InstrumentId = rexi::market_data::InstrumentId;
using OrderId = rexi::market_data::OrderId;
using Price = rexi::market_data::Price;
using Quantity = rexi::market_data::Quantity;
using SequenceNumber = rexi::market_data::SequenceNumber;
using Timestamp = rexi::market_data::Timestamp;

/**
 * @brief Order side representation for order book.
 */
enum class Side : uint8_t {
    Buy = 1,
    Sell = 2,
};

[[nodiscard]] constexpr std::string_view to_string(Side side) noexcept {
    switch (side) {
        case Side::Buy:
            return "Buy";
        case Side::Sell:
            return "Sell";
    }
    return "Unknown";
}

[[nodiscard]] constexpr std::optional<Side> from_market_side(
    rexi::market_data::MarketSide side) noexcept {
    switch (side) {
        case rexi::market_data::MarketSide::Buy:
            return Side::Buy;
        case rexi::market_data::MarketSide::Sell:
            return Side::Sell;
        default:
            return std::nullopt;
    }
}

[[nodiscard]] constexpr rexi::market_data::MarketSide to_market_side(Side side) noexcept {
    switch (side) {
        case Side::Buy:
            return rexi::market_data::MarketSide::Buy;
        case Side::Sell:
            return rexi::market_data::MarketSide::Sell;
    }
    return rexi::market_data::MarketSide::Buy;
}

/**
 * @brief Status returned by order book operations.
 */
enum class OrderBookStatus : uint8_t {
    Success = 0,
    InvalidOrderId = 1,
    DuplicateOrderId = 2,
    OrderNotFound = 3,
    InvalidPrice = 4,
    InvalidQuantity = 5,
    QuantityExceedsRemaining = 6,
    CrossedMarketRejected = 7,
    InstrumentMismatch = 8,
    InvalidSide = 9,
    InvalidSnapshot = 10,
    LevelNotFound = 11,
    InvalidMessageType = 12,
    PoolExhausted = 13,
};

[[nodiscard]] constexpr std::string_view to_string(OrderBookStatus status) noexcept {
    switch (status) {
        case OrderBookStatus::Success:
            return "Success";
        case OrderBookStatus::InvalidOrderId:
            return "InvalidOrderId";
        case OrderBookStatus::DuplicateOrderId:
            return "DuplicateOrderId";
        case OrderBookStatus::OrderNotFound:
            return "OrderNotFound";
        case OrderBookStatus::InvalidPrice:
            return "InvalidPrice";
        case OrderBookStatus::InvalidQuantity:
            return "InvalidQuantity";
        case OrderBookStatus::QuantityExceedsRemaining:
            return "QuantityExceedsRemaining";
        case OrderBookStatus::CrossedMarketRejected:
            return "CrossedMarketRejected";
        case OrderBookStatus::InstrumentMismatch:
            return "InstrumentMismatch";
        case OrderBookStatus::InvalidSide:
            return "InvalidSide";
        case OrderBookStatus::InvalidSnapshot:
            return "InvalidSnapshot";
        case OrderBookStatus::LevelNotFound:
            return "LevelNotFound";
        case OrderBookStatus::InvalidMessageType:
            return "InvalidMessageType";
        case OrderBookStatus::PoolExhausted:
            return "PoolExhausted";
    }
    return "Unknown";
}

/**
 * @brief Configuration parameters for OrderBook capacity and pool sizing.
 */
struct OrderBookConfig {
    size_t initial_order_capacity{1024};
    size_t max_order_capacity{1024};
    bool allow_pool_growth{false};
};

/**
 * @brief Policy determining behavior when an incoming order or update crosses the book.
 */
enum class CrossedBookPolicy : uint8_t {
    Reject = 0,  ///< Reject updates that cross or lock the market (standard matching engine)
    Allow = 1,   ///< Allow crossed states (external market data feed reconstruction mode)
};

[[nodiscard]] constexpr std::string_view to_string(CrossedBookPolicy policy) noexcept {
    switch (policy) {
        case CrossedBookPolicy::Reject:
            return "Reject";
        case CrossedBookPolicy::Allow:
            return "Allow";
    }
    return "Unknown";
}

/**
 * @brief Aggregated Level 2 price level view.
 */
struct LevelView {
    Price price{0};
    Quantity total_quantity{0};
    uint32_t order_count{0};

    [[nodiscard]] constexpr bool operator==(const LevelView& other) const noexcept {
        return price == other.price && total_quantity == other.total_quantity &&
               order_count == other.order_count;
    }
};

/**
 * @brief Level 1 Top of Book (BBO) representation.
 */
struct TopQuote {
    std::optional<Price> bid_price{std::nullopt};
    Quantity bid_quantity{0};
    std::optional<Price> ask_price{std::nullopt};
    Quantity ask_quantity{0};

    [[nodiscard]] constexpr bool has_bids() const noexcept { return bid_price.has_value(); }
    [[nodiscard]] constexpr bool has_asks() const noexcept { return ask_price.has_value(); }

    [[nodiscard]] constexpr std::optional<Price> spread() const noexcept {
        if (bid_price.has_value() && ask_price.has_value()) {
            return *ask_price - *bid_price;
        }
        return std::nullopt;
    }

    [[nodiscard]] constexpr bool is_crossed() const noexcept {
        if (bid_price.has_value() && ask_price.has_value()) {
            return *bid_price >= *ask_price;
        }
        return false;
    }

    [[nodiscard]] constexpr bool operator==(const TopQuote& other) const noexcept {
        return bid_price == other.bid_price && bid_quantity == other.bid_quantity &&
               ask_price == other.ask_price && ask_quantity == other.ask_quantity;
    }
};

/**
 * @brief Result struct for order book internal validation.
 */
struct ValidationResult {
    bool is_valid{true};
    std::string error;

    [[nodiscard]] constexpr explicit operator bool() const noexcept { return is_valid; }
};

}  // namespace rexi::order_book
