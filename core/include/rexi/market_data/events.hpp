#pragma once

#include "rexi/events/event.hpp"
#include "rexi/events/event_types.hpp"
#include "rexi/market_data/messages.hpp"

namespace rexi::events {

template <>
struct EventTraits<rexi::market_data::TopOfBookMessage> {
    static constexpr EventType type = EventType::MarketDataTopOfBook;
    static constexpr std::string_view name = "MarketDataTopOfBook";
};

template <>
struct EventTraits<rexi::market_data::TradeMessage> {
    static constexpr EventType type = EventType::MarketDataTrade;
    static constexpr std::string_view name = "MarketDataTrade";
};

template <>
struct EventTraits<rexi::market_data::MarketStatusMessage> {
    static constexpr EventType type = EventType::MarketDataStatus;
    static constexpr std::string_view name = "MarketDataStatus";
};

template <>
struct EventTraits<rexi::market_data::OrderBookSnapshotMessage> {
    static constexpr EventType type = EventType::MarketDataSnapshot;
    static constexpr std::string_view name = "MarketDataSnapshot";
};

template <>
struct EventTraits<rexi::market_data::OrderBookAddMessage> {
    static constexpr EventType type = EventType::MarketDataAdd;
    static constexpr std::string_view name = "MarketDataAdd";
};

template <>
struct EventTraits<rexi::market_data::OrderBookModifyMessage> {
    static constexpr EventType type = EventType::MarketDataModify;
    static constexpr std::string_view name = "MarketDataModify";
};

template <>
struct EventTraits<rexi::market_data::OrderBookDeleteMessage> {
    static constexpr EventType type = EventType::MarketDataDelete;
    static constexpr std::string_view name = "MarketDataDelete";
};

template <>
struct EventTraits<rexi::market_data::InstrumentDefinitionMessage> {
    static constexpr EventType type = EventType::MarketDataInstrument;
    static constexpr std::string_view name = "MarketDataInstrument";
};

}  // namespace rexi::events

namespace rexi::market_data {

using TopOfBookEvent = rexi::events::Event<TopOfBookMessage>;
using TradeEvent = rexi::events::Event<TradeMessage>;
using MarketStatusEvent = rexi::events::Event<MarketStatusMessage>;
using OrderBookSnapshotEvent = rexi::events::Event<OrderBookSnapshotMessage>;
using OrderBookAddEvent = rexi::events::Event<OrderBookAddMessage>;
using OrderBookModifyEvent = rexi::events::Event<OrderBookModifyMessage>;
using OrderBookDeleteEvent = rexi::events::Event<OrderBookDeleteMessage>;
using InstrumentDefinitionEvent = rexi::events::Event<InstrumentDefinitionMessage>;

}  // namespace rexi::market_data
