#pragma once

#include <cstdint>
#include <string_view>

namespace rexi::events {

/**
 * @brief Strongly typed event identifier for deterministic dispatching.
 *
 * Underlying uint16_t enables high-performance direct table indexing without
 * string parsing or runtime reflection.
 */
enum class EventType : uint16_t {
    Unknown = 0,
    TimerTick = 1,
    Heartbeat = 2,
    SystemStatus = 3,
    TestEvent = 4,

    // Exchange Simulator Events (Phase 03)
    OrderAccepted = 10,
    OrderRejected = 11,
    OrderCancelled = 12,
    OrderFilled = 13,
    TradeExecuted = 14,
    TopQuoteUpdated = 15,

    // Market Data Protocol Events (Phase 04)
    MarketDataTopOfBook = 20,
    MarketDataTrade = 21,
    MarketDataStatus = 22,
    MarketDataSnapshot = 23,
    MarketDataAdd = 24,
    MarketDataModify = 25,
    MarketDataDelete = 26,
    MarketDataInstrument = 27,

    // Order Book Events (Phase 05)
    OrderBookOrderAdded = 30,
    OrderBookOrderModified = 31,
    OrderBookOrderDeleted = 32,
    OrderBookOrderReduced = 33,
    OrderBookBboChanged = 34,

    CustomBase = 100
};

/**
 * @brief Convert EventType to string representation for logging and diagnostics.
 */
[[nodiscard]] constexpr std::string_view to_string(EventType type) noexcept {
    switch (type) {
        case EventType::Unknown:
            return "Unknown";
        case EventType::TimerTick:
            return "TimerTick";
        case EventType::Heartbeat:
            return "Heartbeat";
        case EventType::SystemStatus:
            return "SystemStatus";
        case EventType::TestEvent:
            return "TestEvent";
        case EventType::OrderAccepted:
            return "OrderAccepted";
        case EventType::OrderRejected:
            return "OrderRejected";
        case EventType::OrderCancelled:
            return "OrderCancelled";
        case EventType::OrderFilled:
            return "OrderFilled";
        case EventType::TradeExecuted:
            return "TradeExecuted";
        case EventType::TopQuoteUpdated:
            return "TopQuoteUpdated";
        case EventType::MarketDataTopOfBook:
            return "MarketDataTopOfBook";
        case EventType::MarketDataTrade:
            return "MarketDataTrade";
        case EventType::MarketDataStatus:
            return "MarketDataStatus";
        case EventType::MarketDataSnapshot:
            return "MarketDataSnapshot";
        case EventType::MarketDataAdd:
            return "MarketDataAdd";
        case EventType::MarketDataModify:
            return "MarketDataModify";
        case EventType::MarketDataDelete:
            return "MarketDataDelete";
        case EventType::MarketDataInstrument:
            return "MarketDataInstrument";
        case EventType::OrderBookOrderAdded:
            return "OrderBookOrderAdded";
        case EventType::OrderBookOrderModified:
            return "OrderBookOrderModified";
        case EventType::OrderBookOrderDeleted:
            return "OrderBookOrderDeleted";
        case EventType::OrderBookOrderReduced:
            return "OrderBookOrderReduced";
        case EventType::OrderBookBboChanged:
            return "OrderBookBboChanged";
        case EventType::CustomBase:
            return "CustomBase";
    }
    return "InvalidEventType";
}

}  // namespace rexi::events
