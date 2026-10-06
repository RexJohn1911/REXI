#include "rexi/order_book/price_level.hpp"
#include "rexi/order_book/resting_order.hpp"
#include "rexi/order_book/types.hpp"

#include <gtest/gtest.h>

using namespace rexi::order_book;

TEST(OrderBookTypesTest, StringConversions) {
    EXPECT_EQ(to_string(Side::Buy), "Buy");
    EXPECT_EQ(to_string(Side::Sell), "Sell");

    EXPECT_EQ(to_string(OrderBookStatus::Success), "Success");
    EXPECT_EQ(to_string(OrderBookStatus::InvalidOrderId), "InvalidOrderId");
    EXPECT_EQ(to_string(OrderBookStatus::DuplicateOrderId), "DuplicateOrderId");
    EXPECT_EQ(to_string(OrderBookStatus::OrderNotFound), "OrderNotFound");
    EXPECT_EQ(to_string(OrderBookStatus::InvalidPrice), "InvalidPrice");
    EXPECT_EQ(to_string(OrderBookStatus::InvalidQuantity), "InvalidQuantity");
    EXPECT_EQ(to_string(OrderBookStatus::QuantityExceedsRemaining), "QuantityExceedsRemaining");
    EXPECT_EQ(to_string(OrderBookStatus::CrossedMarketRejected), "CrossedMarketRejected");
    EXPECT_EQ(to_string(OrderBookStatus::InstrumentMismatch), "InstrumentMismatch");
    EXPECT_EQ(to_string(OrderBookStatus::InvalidSide), "InvalidSide");
    EXPECT_EQ(to_string(OrderBookStatus::InvalidSnapshot), "InvalidSnapshot");
    EXPECT_EQ(to_string(OrderBookStatus::LevelNotFound), "LevelNotFound");
    EXPECT_EQ(to_string(OrderBookStatus::InvalidMessageType), "InvalidMessageType");

    EXPECT_EQ(to_string(CrossedBookPolicy::Reject), "Reject");
    EXPECT_EQ(to_string(CrossedBookPolicy::Allow), "Allow");
}

TEST(OrderBookTypesTest, SideConversions) {
    EXPECT_EQ(from_market_side(rexi::market_data::MarketSide::Buy), Side::Buy);
    EXPECT_EQ(from_market_side(rexi::market_data::MarketSide::Sell), Side::Sell);
    EXPECT_EQ(from_market_side(static_cast<rexi::market_data::MarketSide>(99)), std::nullopt);

    EXPECT_EQ(to_market_side(Side::Buy), rexi::market_data::MarketSide::Buy);
    EXPECT_EQ(to_market_side(Side::Sell), rexi::market_data::MarketSide::Sell);
}

TEST(OrderBookTypesTest, RestingOrderLayoutAndMethods) {
    static_assert(std::is_standard_layout_v<RestingOrder>);
    static_assert(std::is_trivially_copyable_v<RestingOrder>);
    static_assert(sizeof(RestingOrder) % 8 == 0);

    RestingOrder order{
        .order_id = 1001,
        .instrument_id = 1,
        .side = Side::Buy,
        .price = 50000,
        .initial_quantity = 100,
        .remaining_quantity = 100,
        .priority_seq = 42,
        .timestamp_ns = 123456789,
    };

    EXPECT_TRUE(order.is_active());
    EXPECT_FALSE(order.is_filled());

    order.reduce(40);
    EXPECT_EQ(order.remaining_quantity, 60);
    EXPECT_TRUE(order.is_active());
    EXPECT_FALSE(order.is_filled());

    order.reduce(100);  // Overshoot
    EXPECT_EQ(order.remaining_quantity, 0);
    EXPECT_FALSE(order.is_active());
    EXPECT_TRUE(order.is_filled());
}

TEST(OrderBookTypesTest, PriceLevelOperations) {
    PriceLevel level(100);
    OrderPool pool(OrderPoolConfig{.initial_capacity = 10});
    EXPECT_EQ(level.price(), 100);
    EXPECT_EQ(level.total_quantity(), 0);
    EXPECT_EQ(level.order_count(), 0);
    EXPECT_TRUE(level.is_empty());

    RestingOrder order1{
        .order_id = 1,
        .instrument_id = 1,
        .side = Side::Buy,
        .price = 100,
        .initial_quantity = 50,
        .remaining_quantity = 50,
        .priority_seq = 1,
        .timestamp_ns = 1000,
    };
    RestingOrder order2{
        .order_id = 2,
        .instrument_id = 1,
        .side = Side::Buy,
        .price = 100,
        .initial_quantity = 75,
        .remaining_quantity = 75,
        .priority_seq = 2,
        .timestamp_ns = 2000,
    };

    auto h1 = pool.allocate(order1);
    level.push_back(h1, order1.remaining_quantity, pool);
    EXPECT_EQ(level.total_quantity(), 50);
    EXPECT_EQ(level.order_count(), 1);
    EXPECT_FALSE(level.is_empty());

    auto h2 = pool.allocate(order2);
    level.push_back(h2, order2.remaining_quantity, pool);
    EXPECT_EQ(level.total_quantity(), 125);
    EXPECT_EQ(level.order_count(), 2);

    // Reduce order1
    level.reduce(h1, 20, pool);
    EXPECT_EQ(pool.order(h1).remaining_quantity, 30);
    EXPECT_EQ(level.total_quantity(), 105);

    // Move order1 to back
    level.move_to_back(h1, pool);
    EXPECT_EQ(pool.order(level.head()).order_id, 2);
    EXPECT_EQ(pool.order(level.tail()).order_id, 1);

    // Erase order2
    level.erase(h2, pool);
    pool.deallocate(h2);
    EXPECT_EQ(level.order_count(), 1);
    EXPECT_EQ(level.total_quantity(), 30);

    // Erase order1
    level.erase(h1, pool);
    pool.deallocate(h1);
    EXPECT_EQ(level.order_count(), 0);
    EXPECT_EQ(level.total_quantity(), 0);
    EXPECT_TRUE(level.is_empty());
}

TEST(OrderBookTypesTest, TopQuoteAndLevelView) {
    TopQuote quote{};
    EXPECT_FALSE(quote.has_bids());
    EXPECT_FALSE(quote.has_asks());
    EXPECT_EQ(quote.spread(), std::nullopt);
    EXPECT_FALSE(quote.is_crossed());

    quote.bid_price = 100;
    quote.bid_quantity = 50;
    EXPECT_TRUE(quote.has_bids());
    EXPECT_FALSE(quote.has_asks());
    EXPECT_EQ(quote.spread(), std::nullopt);

    quote.ask_price = 105;
    quote.ask_quantity = 60;
    EXPECT_TRUE(quote.has_bids());
    EXPECT_TRUE(quote.has_asks());
    EXPECT_EQ(quote.spread(), 5);
    EXPECT_FALSE(quote.is_crossed());

    // Crossed quote
    quote.bid_price = 106;
    EXPECT_TRUE(quote.is_crossed());
    EXPECT_EQ(quote.spread(), -1);

    LevelView lv1{.price = 100, .total_quantity = 50, .order_count = 2};
    LevelView lv2{.price = 100, .total_quantity = 50, .order_count = 2};
    LevelView lv3{.price = 101, .total_quantity = 50, .order_count = 2};
    EXPECT_EQ(lv1, lv2);
    EXPECT_FALSE(lv1 == lv3);
}
