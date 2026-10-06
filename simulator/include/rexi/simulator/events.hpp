#pragma once

#include "rexi/events/event.hpp"
#include "rexi/events/event_types.hpp"
#include "rexi/simulator/types.hpp"

#include <cstdint>

namespace rexi::simulator {

/**
 * @brief Order accepted event payload.
 */
struct alignas(8) OrderAcceptedPayload {
    OrderId order_id{0};
    ClientId client_id{0};
    InstrumentId instrument_id{0};
    Side side{Side::Buy};
    OrderType order_type{OrderType::Limit};
    Price price{0};
    Quantity quantity{0};
    SequenceNum sequence{0};
};

/**
 * @brief Order rejected event payload.
 */
struct alignas(8) OrderRejectedPayload {
    OrderId order_id{0};
    ClientId client_id{0};
    InstrumentId instrument_id{0};
    Side side{Side::Buy};
    OrderType order_type{OrderType::Limit};
    Price price{0};
    Quantity quantity{0};
    RejectReason reason{RejectReason::None};
};

/**
 * @brief Order cancelled event payload.
 */
struct alignas(8) OrderCancelledPayload {
    OrderId order_id{0};
    ClientId client_id{0};
    InstrumentId instrument_id{0};
    Quantity cancelled_quantity{0};
    SequenceNum sequence{0};
};

/**
 * @brief Order fill / partial fill event payload.
 */
struct alignas(8) OrderFilledPayload {
    OrderId order_id{0};
    ClientId client_id{0};
    InstrumentId instrument_id{0};
    ExecutionId execution_id{0};
    Price fill_price{0};
    Quantity fill_quantity{0};
    Quantity remaining_quantity{0};
    OrderStatus status{OrderStatus::Filled};
    SequenceNum sequence{0};
};

/**
 * @brief Trade execution event payload (public execution record).
 */
struct alignas(8) TradeExecutedPayload {
    ExecutionId execution_id{0};
    InstrumentId instrument_id{0};
    Price price{0};
    Quantity quantity{0};
    Side aggressor_side{Side::Buy};
    OrderId maker_order_id{0};
    OrderId taker_order_id{0};
    SequenceNum sequence{0};
};

/**
 * @brief Top of book / BBO update event payload.
 */
struct alignas(8) TopQuoteUpdatedPayload {
    InstrumentId instrument_id{0};
    Price best_bid_price{0};
    Quantity best_bid_quantity{0};
    Price best_ask_price{0};
    Quantity best_ask_quantity{0};
    SequenceNum sequence{0};
};

}  // namespace rexi::simulator

namespace rexi::events {

template <>
struct EventTraits<rexi::simulator::OrderAcceptedPayload> {
    static constexpr EventType type = EventType::OrderAccepted;
    static constexpr std::string_view name = "OrderAccepted";
};

template <>
struct EventTraits<rexi::simulator::OrderRejectedPayload> {
    static constexpr EventType type = EventType::OrderRejected;
    static constexpr std::string_view name = "OrderRejected";
};

template <>
struct EventTraits<rexi::simulator::OrderCancelledPayload> {
    static constexpr EventType type = EventType::OrderCancelled;
    static constexpr std::string_view name = "OrderCancelled";
};

template <>
struct EventTraits<rexi::simulator::OrderFilledPayload> {
    static constexpr EventType type = EventType::OrderFilled;
    static constexpr std::string_view name = "OrderFilled";
};

template <>
struct EventTraits<rexi::simulator::TradeExecutedPayload> {
    static constexpr EventType type = EventType::TradeExecuted;
    static constexpr std::string_view name = "TradeExecuted";
};

template <>
struct EventTraits<rexi::simulator::TopQuoteUpdatedPayload> {
    static constexpr EventType type = EventType::TopQuoteUpdated;
    static constexpr std::string_view name = "TopQuoteUpdated";
};

}  // namespace rexi::events

namespace rexi::simulator {

using OrderAcceptedEvent = rexi::events::Event<OrderAcceptedPayload>;
using OrderRejectedEvent = rexi::events::Event<OrderRejectedPayload>;
using OrderCancelledEvent = rexi::events::Event<OrderCancelledPayload>;
using OrderFilledEvent = rexi::events::Event<OrderFilledPayload>;
using TradeExecutedEvent = rexi::events::Event<TradeExecutedPayload>;
using TopQuoteUpdatedEvent = rexi::events::Event<TopQuoteUpdatedPayload>;

}  // namespace rexi::simulator
