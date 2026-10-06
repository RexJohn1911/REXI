#include "rexi/events/event_dispatcher.hpp"
#include "rexi/market_data/events.hpp"
#include "rexi/market_data/message_header.hpp"
#include "rexi/market_data/messages.hpp"
#include "rexi/market_data/simulator_bridge.hpp"
#include "rexi/order_book/events.hpp"
#include "rexi/order_book/order_book.hpp"
#include "rexi/simulator/exchange.hpp"

#include <vector>

#include <gtest/gtest.h>

using namespace rexi::events;
using namespace rexi::market_data;
using namespace rexi::order_book;
using namespace rexi::simulator;

TEST(OrderBookPipelineIntegrationTest, EndToEndSimulatorBridgeToOrderBookPipeline) {
    Exchange exchange;
    EventDispatcher md_dispatcher;
    rexi::order_book::OrderBook client_book(100);

    // Wire Simulator -> Bridge -> Market Data Dispatcher
    SimulatorMarketDataBridge bridge(exchange.dispatcher(), md_dispatcher, 1, 100);

    std::vector<TopOfBookMessage> received_quotes;
    std::vector<TradeMessage> received_trades;

    md_dispatcher.subscribe<TopOfBookMessage>(
        [&](const Event<TopOfBookMessage>& evt) { received_quotes.push_back(evt.payload); });

    md_dispatcher.subscribe<TradeMessage>(
        [&](const Event<TradeMessage>& evt) { received_trades.push_back(evt.payload); });

    Instrument inst{
        .id = 100,
        .tick_size = 1,
        .min_quantity = 1,
        .max_quantity = 10000,
        .lot_size = 1,
    };
    ASSERT_TRUE(exchange.register_instrument(inst));
    exchange.open_session();

    // 1. Submit resting limit sell order on exchange (105 @ 40)
    exchange.clock().advance_by_ns(1000);
    EXPECT_EQ(
        exchange.submit_order(1, 10, 100, rexi::simulator::Side::Sell, OrderType::Limit, 105, 40),
        OrderStatus::Accepted);

    // Verify quote message received
    ASSERT_FALSE(received_quotes.empty());
    EXPECT_EQ(received_quotes.back().best_ask_price, 105);
    EXPECT_EQ(received_quotes.back().best_ask_quantity, 40);

    // Apply incremental L3 add to client book
    MarketDataHeader md_hdr =
        make_md_header(MarketDataMessageType::OrderBookAdd, 100, 1, 1, 1, 1000, 1000);
    OrderBookAddMessage add_msg{
        .order_id = 1,
        .side = MarketSide::Sell,
        .price = 105,
        .quantity = 40,
    };
    EXPECT_EQ(client_book.apply_add(md_hdr, add_msg), OrderBookStatus::Success);

    EXPECT_EQ(client_book.best_ask_price(), 105);
    EXPECT_EQ(client_book.best_ask_quantity(), 40);

    // 2. Submit matching buy order on exchange (105 @ 40)
    exchange.clock().advance_by_ns(1000);
    EXPECT_EQ(
        exchange.submit_order(2, 20, 100, rexi::simulator::Side::Buy, OrderType::Limit, 105, 40),
        OrderStatus::Filled);

    // Verify trade received
    ASSERT_FALSE(received_trades.empty());
    EXPECT_EQ(received_trades.back().price, 105);
    EXPECT_EQ(received_trades.back().quantity, 40);

    // Apply execution reduction to client order book
    EXPECT_EQ(client_book.reduce_order(1, 40), OrderBookStatus::Success);
    EXPECT_TRUE(client_book.is_empty());
    EXPECT_EQ(client_book.best_ask_price(), std::nullopt);

    EXPECT_TRUE(client_book.validate().is_valid);
}
