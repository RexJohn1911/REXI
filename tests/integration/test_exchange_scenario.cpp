#include "rexi/events/event_dispatcher.hpp"
#include "rexi/simulator/events.hpp"
#include "rexi/simulator/exchange.hpp"

#include <vector>

#include <gtest/gtest.h>

using namespace rexi::simulator;
using namespace rexi::events;

TEST(ExchangeScenarioIntegrationTest, CompleteTradingScenario) {
    Exchange exchange;

    std::vector<TradeExecutedPayload> trades;
    std::vector<OrderFilledPayload> fills;

    exchange.dispatcher().subscribe<TradeExecutedPayload>(
        [&](const Event<TradeExecutedPayload>& evt) { trades.push_back(evt.payload); });

    exchange.dispatcher().subscribe<OrderFilledPayload>(
        [&](const Event<OrderFilledPayload>& evt) { fills.push_back(evt.payload); });

    // 1. Register instrument (Apple-like mock, tick = 1, lot = 1)
    Instrument inst{
        .id = 1001,
        .tick_size = 1,
        .min_quantity = 1,
        .max_quantity = 100000,
        .lot_size = 1,
    };
    ASSERT_TRUE(exchange.register_instrument(inst));

    // 2. Open session
    exchange.open_session();
    EXPECT_TRUE(exchange.is_open());

    // 3. Submit multiple resting sell orders (Client 10: 100 @ 150, Client 11: 100 @ 151, Client
    // 12: 100 @ 152)
    exchange.clock().advance_by_ns(1000);
    EXPECT_EQ(exchange.submit_order(1, 10, 1001, Side::Sell, OrderType::Limit, 150, 100),
              OrderStatus::Accepted);
    exchange.clock().advance_by_ns(1000);
    EXPECT_EQ(exchange.submit_order(2, 11, 1001, Side::Sell, OrderType::Limit, 151, 100),
              OrderStatus::Accepted);
    exchange.clock().advance_by_ns(1000);
    EXPECT_EQ(exchange.submit_order(3, 12, 1001, Side::Sell, OrderType::Limit, 152, 100),
              OrderStatus::Accepted);

    // 4. Submit multiple resting buy orders (Client 20: 50 @ 148, Client 21: 50 @ 147)
    exchange.clock().advance_by_ns(1000);
    EXPECT_EQ(exchange.submit_order(4, 20, 1001, Side::Buy, OrderType::Limit, 148, 50),
              OrderStatus::Accepted);
    exchange.clock().advance_by_ns(1000);
    EXPECT_EQ(exchange.submit_order(5, 21, 1001, Side::Buy, OrderType::Limit, 147, 50),
              OrderStatus::Accepted);

    // Verify top quote (Best Bid: 148 (qty 50), Best Ask: 150 (qty 100))
    const auto* book = exchange.matching_engine().get_order_book(1001);
    ASSERT_NE(book, nullptr);
    auto bb = book->best_bid();
    auto ba = book->best_ask();
    ASSERT_TRUE(bb.has_value());
    ASSERT_TRUE(ba.has_value());
    EXPECT_EQ(bb->first, 148);
    EXPECT_EQ(bb->second, 50);
    EXPECT_EQ(ba->first, 150);
    EXPECT_EQ(ba->second, 100);

    // 5. Submit aggressive crossing buy order (Client 30: 250 @ 151)
    // Should completely fill Order 1 (100 @ 150), Order 2 (100 @ 151), and leave remaining 50
    // resting at 151 as new best bid!
    exchange.clock().advance_by_ns(1000);
    EXPECT_EQ(exchange.submit_order(6, 30, 1001, Side::Buy, OrderType::Limit, 151, 250),
              OrderStatus::PartiallyFilled);

    // Verify executions
    ASSERT_EQ(trades.size(), 2);
    // First trade: 100 @ 150 against Order 1
    EXPECT_EQ(trades[0].price, 150);
    EXPECT_EQ(trades[0].quantity, 100);
    EXPECT_EQ(trades[0].maker_order_id, 1);
    EXPECT_EQ(trades[0].taker_order_id, 6);

    // Second trade: 100 @ 151 against Order 2
    EXPECT_EQ(trades[1].price, 151);
    EXPECT_EQ(trades[1].quantity, 100);
    EXPECT_EQ(trades[1].maker_order_id, 2);
    EXPECT_EQ(trades[1].taker_order_id, 6);

    // Verify new book state: Best Bid is now 151 (50 remaining from Order 6), Best Ask is 152 (100
    // from Order 3)
    bb = book->best_bid();
    ba = book->best_ask();
    ASSERT_TRUE(bb.has_value());
    ASSERT_TRUE(ba.has_value());
    EXPECT_EQ(bb->first, 151);
    EXPECT_EQ(bb->second, 50);
    EXPECT_EQ(ba->first, 152);
    EXPECT_EQ(ba->second, 100);

    // 6. Cancel order 3 (the resting sell at 152)
    exchange.clock().advance_by_ns(1000);
    EXPECT_TRUE(exchange.cancel_order(3));

    // Ask book is now empty
    EXPECT_FALSE(book->has_asks());

    // 7. Close session and verify further submissions are rejected
    exchange.close_session();
    EXPECT_EQ(exchange.submit_order(7, 40, 1001, Side::Buy, OrderType::Market, 0, 10),
              OrderStatus::Rejected);
}
