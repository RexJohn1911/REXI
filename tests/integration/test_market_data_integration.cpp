#include "rexi/events/event_dispatcher.hpp"
#include "rexi/market_data/checksum.hpp"
#include "rexi/market_data/events.hpp"
#include "rexi/market_data/messages.hpp"
#include "rexi/market_data/simulator_bridge.hpp"
#include "rexi/simulator/exchange.hpp"

#include <vector>

#include <gtest/gtest.h>

using namespace rexi::simulator;
using namespace rexi::market_data;
using namespace rexi::events;

TEST(MarketDataIntegrationTest, SimulatorToMarketDataEventPipeline) {
    Exchange exchange;
    EventDispatcher md_dispatcher;

    SimulatorMarketDataBridge bridge(exchange.dispatcher(), md_dispatcher, 10, 100);

    std::vector<TopOfBookMessage> received_quotes;
    std::vector<TradeMessage> received_trades;

    md_dispatcher.subscribe<TopOfBookMessage>(
        [&](const Event<TopOfBookMessage>& evt) { received_quotes.push_back(evt.payload); });

    md_dispatcher.subscribe<TradeMessage>(
        [&](const Event<TradeMessage>& evt) { received_trades.push_back(evt.payload); });

    // Register instrument in simulator
    Instrument inst{
        .id = 501,
        .tick_size = 1,
        .min_quantity = 1,
        .max_quantity = 100000,
        .lot_size = 1,
    };
    ASSERT_TRUE(exchange.register_instrument(inst));
    exchange.open_session();

    // 1. Submit resting sell order (Client 10: 100 @ 200)
    exchange.clock().advance_by_ns(1000);
    EXPECT_EQ(exchange.submit_order(1, 10, 501, Side::Sell, OrderType::Limit, 200, 100),
              OrderStatus::Accepted);

    // 2. Submit resting buy order (Client 20: 50 @ 198)
    exchange.clock().advance_by_ns(1000);
    EXPECT_EQ(exchange.submit_order(2, 20, 501, Side::Buy, OrderType::Limit, 198, 50),
              OrderStatus::Accepted);

    // Verify quote update arrived in market data stream
    ASSERT_GE(received_quotes.size(), 2U);
    EXPECT_EQ(received_quotes.back().best_bid_price, 198);
    EXPECT_EQ(received_quotes.back().best_bid_quantity, 50U);
    EXPECT_EQ(received_quotes.back().best_ask_price, 200);
    EXPECT_EQ(received_quotes.back().best_ask_quantity, 100U);

    // 3. Submit crossing buy order (Client 30: 100 @ 200)
    exchange.clock().advance_by_ns(1000);
    EXPECT_EQ(exchange.submit_order(3, 30, 501, Side::Buy, OrderType::Limit, 200, 100),
              OrderStatus::Filled);

    // Verify Trade event arrived in market data stream
    ASSERT_EQ(received_trades.size(), 1U);
    EXPECT_EQ(received_trades[0].price, 200);
    EXPECT_EQ(received_trades[0].quantity, 100U);
    EXPECT_EQ(received_trades[0].aggressor_side, MarketSide::Buy);
    EXPECT_EQ(received_trades[0].maker_order_id, 1U);
    EXPECT_EQ(received_trades[0].taker_order_id, 3U);

    // Verify sequence manager progression
    EXPECT_GT(bridge.sequence_manager().expected_sequence(), 3U);
    EXPECT_EQ(bridge.sequence_manager().gap_count(), 0U);
    EXPECT_EQ(bridge.sequence_manager().duplicate_count(), 0U);
}
