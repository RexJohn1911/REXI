#pragma once

#include "rexi/market_data/message_header.hpp"
#include "rexi/market_data/types.hpp"

#include <array>
#include <cstdint>
#include <type_traits>

namespace rexi::market_data {

/**
 * @brief Instrument reference definition message.
 */
struct alignas(8) InstrumentDefinitionMessage {
    InstrumentId instrument_id{0};
    Price tick_size{1};
    Quantity lot_size{1};
    Quantity min_quantity{1};
    Quantity max_quantity{1'000'000'000};
};

static_assert(std::is_trivially_copyable_v<InstrumentDefinitionMessage>);
static_assert(std::is_standard_layout_v<InstrumentDefinitionMessage>);

/**
 * @brief Top of book / Best Bid & Offer (BBO) quote message.
 */
struct alignas(8) TopOfBookMessage {
    Price best_bid_price{0};
    Quantity best_bid_quantity{0};
    Price best_ask_price{0};
    Quantity best_ask_quantity{0};
};

static_assert(std::is_trivially_copyable_v<TopOfBookMessage>);
static_assert(std::is_standard_layout_v<TopOfBookMessage>);

/**
 * @brief Public executed trade message.
 */
struct alignas(8) TradeMessage {
    TradeId trade_id{0};
    Price price{0};
    Quantity quantity{0};
    MarketSide aggressor_side{MarketSide::Buy};
    OrderId maker_order_id{0};
    OrderId taker_order_id{0};
};

static_assert(std::is_trivially_copyable_v<TradeMessage>);
static_assert(std::is_standard_layout_v<TradeMessage>);

/**
 * @brief Order Book Add / New order message for future L2/L3 feeds.
 */
struct alignas(8) OrderBookAddMessage {
    OrderId order_id{0};
    MarketSide side{MarketSide::Buy};
    Price price{0};
    Quantity quantity{0};
    std::uint32_t priority_rank{0};
};

static_assert(std::is_trivially_copyable_v<OrderBookAddMessage>);
static_assert(std::is_standard_layout_v<OrderBookAddMessage>);

/**
 * @brief Order Book Modify / Quantity adjustment message.
 */
struct alignas(8) OrderBookModifyMessage {
    OrderId order_id{0};
    MarketSide side{MarketSide::Buy};
    Price price{0};
    Quantity new_quantity{0};
    Quantity delta_quantity{0};
};

static_assert(std::is_trivially_copyable_v<OrderBookModifyMessage>);
static_assert(std::is_standard_layout_v<OrderBookModifyMessage>);

/**
 * @brief Order Book Delete / Cancellation message.
 */
struct alignas(8) OrderBookDeleteMessage {
    OrderId order_id{0};
    MarketSide side{MarketSide::Buy};
    Price price{0};
    Quantity cancelled_quantity{0};
};

static_assert(std::is_trivially_copyable_v<OrderBookDeleteMessage>);
static_assert(std::is_standard_layout_v<OrderBookDeleteMessage>);

/**
 * @brief Single price level within a book snapshot.
 */
struct alignas(8) OrderBookSnapshotLevel {
    Price price{0};
    Quantity quantity{0};
    std::uint32_t order_count{0};
};

static_assert(std::is_trivially_copyable_v<OrderBookSnapshotLevel>);
static_assert(std::is_standard_layout_v<OrderBookSnapshotLevel>);

/**
 * @brief Bounded fixed-size order book depth snapshot payload for zero-allocation transport.
 */
inline constexpr size_t MaxSnapshotLevels = 10;

struct alignas(8) OrderBookSnapshotMessage {
    std::uint32_t bid_levels_count{0};
    std::uint32_t ask_levels_count{0};
    SequenceNumber last_included_sequence{0};
    std::array<OrderBookSnapshotLevel, MaxSnapshotLevels> bids;
    std::array<OrderBookSnapshotLevel, MaxSnapshotLevels> asks;
};

static_assert(std::is_trivially_copyable_v<OrderBookSnapshotMessage>);
static_assert(std::is_standard_layout_v<OrderBookSnapshotMessage>);

/**
 * @brief Market and instrument operational state transition message.
 */
struct alignas(8) MarketStatusMessage {
    TradingStatus status{TradingStatus::Unknown};
    std::uint32_t status_flags{0};
};

static_assert(std::is_trivially_copyable_v<MarketStatusMessage>);
static_assert(std::is_standard_layout_v<MarketStatusMessage>);

}  // namespace rexi::market_data
