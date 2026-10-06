#include "rexi/events/event_dispatcher.hpp"
#include "rexi/market_data/events.hpp"

#include <gtest/gtest.h>

using namespace rexi::market_data;
using namespace rexi::events;

TEST(MarketDataEventsTest, DispatchAndReceiveMarketDataEvents) {
    EventDispatcher dispatcher;

    std::uint32_t tob_count = 0;
    std::uint32_t trade_count = 0;
    std::uint32_t status_count = 0;

    dispatcher.subscribe<TopOfBookMessage>([&](const Event<TopOfBookMessage>& evt) {
        ++tob_count;
        EXPECT_EQ(evt.header.type, EventType::MarketDataTopOfBook);
        EXPECT_EQ(evt.payload.best_bid_price, 100);
    });

    dispatcher.subscribe<TradeMessage>([&](const Event<TradeMessage>& evt) {
        ++trade_count;
        EXPECT_EQ(evt.header.type, EventType::MarketDataTrade);
        EXPECT_EQ(evt.payload.price, 105);
    });

    dispatcher.subscribe<MarketStatusMessage>([&](const Event<MarketStatusMessage>& evt) {
        ++status_count;
        EXPECT_EQ(evt.header.type, EventType::MarketDataStatus);
        EXPECT_EQ(evt.payload.status, TradingStatus::Open);
    });

    TopOfBookMessage tob{.best_bid_price = 100,
                         .best_bid_quantity = 50,
                         .best_ask_price = 105,
                         .best_ask_quantity = 50};
    auto tob_evt = make_event(tob, SourceId::Simulator, 1, 0, 1000);
    dispatcher.dispatch(tob_evt);

    TradeMessage trade{.trade_id = 1,
                       .price = 105,
                       .quantity = 25,
                       .aggressor_side = MarketSide::Buy,
                       .maker_order_id = 10,
                       .taker_order_id = 20};
    auto trade_evt = make_event(trade, SourceId::Simulator, 2, 0, 2000);
    dispatcher.dispatch(trade_evt);

    MarketStatusMessage status{.status = TradingStatus::Open, .status_flags = 0};
    auto status_evt = make_event(status, SourceId::Simulator, 3, 0, 3000);
    dispatcher.dispatch(status_evt);

    EXPECT_EQ(tob_count, 1U);
    EXPECT_EQ(trade_count, 1U);
    EXPECT_EQ(status_count, 1U);
}
