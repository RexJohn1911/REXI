#pragma once

#include "rexi/events/event.hpp"
#include "rexi/events/event_types.hpp"
#include "rexi/order_book/types.hpp"

#include <cstdint>

namespace rexi::order_book {

/**
 * @brief Event emitted when an order is added to the book.
 */
struct alignas(8) OrderBookOrderAddedPayload {
    InstrumentId instrument_id{0};
    OrderId order_id{0};
    Side side{Side::Buy};
    uint8_t reserved[3]{0};
    Price price{0};
    Quantity quantity{0};
    SequenceNumber sequence_number{0};
    Timestamp timestamp_ns{0};
};

/**
 * @brief Event emitted when an order's quantity or price is modified.
 */
struct alignas(8) OrderBookOrderModifiedPayload {
    InstrumentId instrument_id{0};
    OrderId order_id{0};
    Side side{Side::Buy};
    bool priority_preserved{true};
    uint8_t reserved[2]{0};
    Price price{0};
    Quantity old_quantity{0};
    Quantity new_quantity{0};
    SequenceNumber sequence_number{0};
    Timestamp timestamp_ns{0};
};

/**
 * @brief Event emitted when an order is cancelled/deleted from the book.
 */
struct alignas(8) OrderBookOrderDeletedPayload {
    InstrumentId instrument_id{0};
    OrderId order_id{0};
    Side side{Side::Buy};
    uint8_t reserved[3]{0};
    Price price{0};
    Quantity remaining_quantity{0};
    SequenceNumber sequence_number{0};
    Timestamp timestamp_ns{0};
};

/**
 * @brief Event emitted when an order's quantity is reduced (e.g. fill).
 */
struct alignas(8) OrderBookOrderReducedPayload {
    InstrumentId instrument_id{0};
    OrderId order_id{0};
    Side side{Side::Buy};
    uint8_t reserved[3]{0};
    Price price{0};
    Quantity executed_quantity{0};
    Quantity remaining_quantity{0};
    SequenceNumber sequence_number{0};
    Timestamp timestamp_ns{0};
};

/**
 * @brief Event emitted when the Best Bid and Offer (BBO) changes.
 */
struct alignas(8) OrderBookBboChangedPayload {
    InstrumentId instrument_id{0};
    Price bid_price{0};
    Quantity bid_quantity{0};
    Price ask_price{0};
    Quantity ask_quantity{0};
    Timestamp timestamp_ns{0};
};

}  // namespace rexi::order_book

namespace rexi::events {

template <>
struct EventTraits<rexi::order_book::OrderBookOrderAddedPayload> {
    static constexpr EventType type = EventType::OrderBookOrderAdded;
    static constexpr std::string_view name = "OrderBookOrderAdded";
};

template <>
struct EventTraits<rexi::order_book::OrderBookOrderModifiedPayload> {
    static constexpr EventType type = EventType::OrderBookOrderModified;
    static constexpr std::string_view name = "OrderBookOrderModified";
};

template <>
struct EventTraits<rexi::order_book::OrderBookOrderDeletedPayload> {
    static constexpr EventType type = EventType::OrderBookOrderDeleted;
    static constexpr std::string_view name = "OrderBookOrderDeleted";
};

template <>
struct EventTraits<rexi::order_book::OrderBookOrderReducedPayload> {
    static constexpr EventType type = EventType::OrderBookOrderReduced;
    static constexpr std::string_view name = "OrderBookOrderReduced";
};

template <>
struct EventTraits<rexi::order_book::OrderBookBboChangedPayload> {
    static constexpr EventType type = EventType::OrderBookBboChanged;
    static constexpr std::string_view name = "OrderBookBboChanged";
};

}  // namespace rexi::events
