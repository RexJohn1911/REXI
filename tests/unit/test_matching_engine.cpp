#include "rexi/simulator/instrument.hpp"
#include "rexi/simulator/matching_engine.hpp"

#include <gtest/gtest.h>

using namespace rexi::simulator;

class MatchingEngineTest : public ::testing::Test {
protected:
    void SetUp() override {
        Instrument inst{
            .id = 100,
            .tick_size = 1,
            .min_quantity = 1,
            .max_quantity = 1'000'000,
            .lot_size = 1,
        };
        engine_.register_instrument(inst);
    }

    MatchingEngine& engine() noexcept { return engine_; }

private:
    MatchingEngine engine_{};
};

TEST_F(MatchingEngineTest, BookInsertionAndBestQuote) {
    OrderBook* book = engine().get_order_book(100);
    ASSERT_NE(book, nullptr);
    EXPECT_FALSE(book->has_bids());
    EXPECT_FALSE(book->has_asks());

    Order buy1{
        .order_id = 1,
        .client_id = 1,
        .instrument_id = 100,
        .side = Side::Buy,
        .type = OrderType::Limit,
        .price = 1000,
        .initial_quantity = 50,
        .remaining_quantity = 50,
        .filled_quantity = 0,
        .priority_seq = 1,
        .status = OrderStatus::Accepted,
        .accepted_timestamp_ns = 0,
    };
    book->insert_order(buy1);

    EXPECT_TRUE(book->has_bids());
    auto bid = book->best_bid();
    ASSERT_TRUE(bid.has_value());
    EXPECT_EQ(bid->first, 1000);
    EXPECT_EQ(bid->second, 50);

    Order buy2{
        .order_id = 2,
        .client_id = 1,
        .instrument_id = 100,
        .side = Side::Buy,
        .type = OrderType::Limit,
        .price = 1005,
        .initial_quantity = 30,
        .remaining_quantity = 30,
        .filled_quantity = 0,
        .priority_seq = 2,
        .status = OrderStatus::Accepted,
        .accepted_timestamp_ns = 0,
    };
    book->insert_order(buy2);

    // Higher bid should be the new best bid (price priority)
    bid = book->best_bid();
    ASSERT_TRUE(bid.has_value());
    EXPECT_EQ(bid->first, 1005);
    EXPECT_EQ(bid->second, 30);
}

TEST_F(MatchingEngineTest, PriceTimePriorityFIFO) {
    // Insert 2 sells at same price level (1010)
    Order sell1{
        .order_id = 1,
        .client_id = 10,
        .instrument_id = 100,
        .side = Side::Sell,
        .type = OrderType::Limit,
        .price = 1010,
        .initial_quantity = 50,
        .remaining_quantity = 50,
        .filled_quantity = 0,
        .priority_seq = 1,
        .status = OrderStatus::Accepted,
        .accepted_timestamp_ns = 0,
    };
    Order sell2{
        .order_id = 2,
        .client_id = 20,
        .instrument_id = 100,
        .side = Side::Sell,
        .type = OrderType::Limit,
        .price = 1010,
        .initial_quantity = 50,
        .remaining_quantity = 50,
        .filled_quantity = 0,
        .priority_seq = 2,
        .status = OrderStatus::Accepted,
        .accepted_timestamp_ns = 0,
    };

    engine().process_order(sell1, 1, 1000);
    engine().process_order(sell2, 2, 2000);

    // Incoming buy crosses at 1010 for 60 units
    Order buy{
        .order_id = 3,
        .client_id = 30,
        .instrument_id = 100,
        .side = Side::Buy,
        .type = OrderType::Limit,
        .price = 1010,
        .initial_quantity = 60,
        .remaining_quantity = 60,
        .filled_quantity = 0,
        .priority_seq = 3,
        .status = OrderStatus::Accepted,
        .accepted_timestamp_ns = 0,
    };

    MatchResult res = engine().process_order(buy, 3, 3000);
    EXPECT_EQ(res.final_order_status, OrderStatus::Filled);
    EXPECT_EQ(res.executed_quantity, 60);
    ASSERT_EQ(res.executions.size(), 2);

    // sell1 (time priority 1) filled first (50 units)
    EXPECT_EQ(res.executions[0].maker_order_id, 1);
    EXPECT_EQ(res.executions[0].quantity, 50);
    EXPECT_EQ(res.executions[0].price, 1010);

    // sell2 (time priority 2) partially filled (10 units)
    EXPECT_EQ(res.executions[1].maker_order_id, 2);
    EXPECT_EQ(res.executions[1].quantity, 10);
    EXPECT_EQ(res.executions[1].price, 1010);

    // Verify remaining book
    OrderBook* book = engine().get_order_book(100);
    ASSERT_NE(book, nullptr);
    auto ask = book->best_ask();
    ASSERT_TRUE(ask.has_value());
    EXPECT_EQ(ask->first, 1010);
    EXPECT_EQ(ask->second, 40);
}

TEST_F(MatchingEngineTest, RestingOrderDeterminesExecutionPrice) {
    // Resting sell at 100
    Order sell{
        .order_id = 1,
        .client_id = 10,
        .instrument_id = 100,
        .side = Side::Sell,
        .type = OrderType::Limit,
        .price = 100,
        .initial_quantity = 50,
        .remaining_quantity = 50,
        .filled_quantity = 0,
        .priority_seq = 1,
        .status = OrderStatus::Accepted,
        .accepted_timestamp_ns = 0,
    };
    engine().process_order(sell, 1, 1000);

    // Incoming aggressive buy at 105
    Order buy{
        .order_id = 2,
        .client_id = 20,
        .instrument_id = 100,
        .side = Side::Buy,
        .type = OrderType::Limit,
        .price = 105,
        .initial_quantity = 50,
        .remaining_quantity = 50,
        .filled_quantity = 0,
        .priority_seq = 2,
        .status = OrderStatus::Accepted,
        .accepted_timestamp_ns = 0,
    };

    MatchResult res = engine().process_order(buy, 2, 2000);
    EXPECT_EQ(res.final_order_status, OrderStatus::Filled);
    ASSERT_EQ(res.executions.size(), 1);
    // Execution price MUST be resting order price (100), not 105
    EXPECT_EQ(res.executions[0].price, 100);
    EXPECT_EQ(res.executions[0].quantity, 50);
}

TEST_F(MatchingEngineTest, MultiLevelMatchingSweep) {
    // Resting sells at 101, 102, 103
    Order sell1{.order_id = 1,
                .client_id = 1,
                .instrument_id = 100,
                .side = Side::Sell,
                .type = OrderType::Limit,
                .price = 101,
                .initial_quantity = 100,
                .remaining_quantity = 100,
                .filled_quantity = 0,
                .priority_seq = 1,
                .status = OrderStatus::Accepted,
                .accepted_timestamp_ns = 0};
    Order sell2{.order_id = 2,
                .client_id = 2,
                .instrument_id = 100,
                .side = Side::Sell,
                .type = OrderType::Limit,
                .price = 102,
                .initial_quantity = 100,
                .remaining_quantity = 100,
                .filled_quantity = 0,
                .priority_seq = 2,
                .status = OrderStatus::Accepted,
                .accepted_timestamp_ns = 0};
    Order sell3{.order_id = 3,
                .client_id = 3,
                .instrument_id = 100,
                .side = Side::Sell,
                .type = OrderType::Limit,
                .price = 103,
                .initial_quantity = 100,
                .remaining_quantity = 100,
                .filled_quantity = 0,
                .priority_seq = 3,
                .status = OrderStatus::Accepted,
                .accepted_timestamp_ns = 0};

    engine().process_order(sell1, 1, 1000);
    engine().process_order(sell2, 2, 2000);
    engine().process_order(sell3, 3, 3000);

    // Aggressive buy for 250 units at 103
    Order buy{.order_id = 4,
              .client_id = 4,
              .instrument_id = 100,
              .side = Side::Buy,
              .type = OrderType::Limit,
              .price = 103,
              .initial_quantity = 250,
              .remaining_quantity = 250,
              .filled_quantity = 0,
              .priority_seq = 4,
              .status = OrderStatus::Accepted,
              .accepted_timestamp_ns = 0};

    MatchResult res = engine().process_order(buy, 4, 4000);
    EXPECT_EQ(res.final_order_status, OrderStatus::Filled);
    EXPECT_EQ(res.executed_quantity, 250);
    ASSERT_EQ(res.executions.size(), 3);

    // 100 @ 101
    EXPECT_EQ(res.executions[0].price, 101);
    EXPECT_EQ(res.executions[0].quantity, 100);
    // 100 @ 102
    EXPECT_EQ(res.executions[1].price, 102);
    EXPECT_EQ(res.executions[1].quantity, 100);
    // 50 @ 103
    EXPECT_EQ(res.executions[2].price, 103);
    EXPECT_EQ(res.executions[2].quantity, 50);

    // Remaining in book: 50 @ 103
    OrderBook* book = engine().get_order_book(100);
    ASSERT_NE(book, nullptr);
    auto ask = book->best_ask();
    ASSERT_TRUE(ask.has_value());
    EXPECT_EQ(ask->first, 103);
    EXPECT_EQ(ask->second, 50);
}

TEST_F(MatchingEngineTest, MarketOrderExecutionAndLiquidityExhaustion) {
    Order sell1{.order_id = 1,
                .client_id = 1,
                .instrument_id = 100,
                .side = Side::Sell,
                .type = OrderType::Limit,
                .price = 100,
                .initial_quantity = 40,
                .remaining_quantity = 40,
                .filled_quantity = 0,
                .priority_seq = 1,
                .status = OrderStatus::Accepted,
                .accepted_timestamp_ns = 0};
    engine().process_order(sell1, 1, 1000);

    // Market Buy for 100 (only 40 available)
    Order market_buy{.order_id = 2,
                     .client_id = 2,
                     .instrument_id = 100,
                     .side = Side::Buy,
                     .type = OrderType::Market,
                     .price = 0,
                     .initial_quantity = 100,
                     .remaining_quantity = 100,
                     .filled_quantity = 0,
                     .priority_seq = 2,
                     .status = OrderStatus::Accepted,
                     .accepted_timestamp_ns = 0};

    MatchResult res = engine().process_order(market_buy, 2, 2000);
    EXPECT_EQ(res.executed_quantity, 40);
    EXPECT_EQ(res.cancelled_remainder_quantity, 60);
    EXPECT_EQ(res.final_order_status, OrderStatus::PartiallyFilled);
    ASSERT_EQ(res.executions.size(), 1);

    // Book is now completely empty
    OrderBook* book = engine().get_order_book(100);
    ASSERT_NE(book, nullptr);
    EXPECT_FALSE(book->has_asks());
}

TEST_F(MatchingEngineTest, OrderCancellationOperations) {
    Order sell1{.order_id = 1,
                .client_id = 1,
                .instrument_id = 100,
                .side = Side::Sell,
                .type = OrderType::Limit,
                .price = 100,
                .initial_quantity = 50,
                .remaining_quantity = 50,
                .filled_quantity = 0,
                .priority_seq = 1,
                .status = OrderStatus::Accepted,
                .accepted_timestamp_ns = 0};
    engine().process_order(sell1, 1, 1000);

    Order cancelled{};
    // Active order cancels successfully
    EXPECT_TRUE(engine().cancel_order(1, cancelled));
    EXPECT_EQ(cancelled.status, OrderStatus::Cancelled);
    EXPECT_EQ(cancelled.remaining_quantity, 50);

    // Double cancel should fail
    EXPECT_FALSE(engine().cancel_order(1, cancelled));

    // Non-existent order cancellation should fail
    EXPECT_FALSE(engine().cancel_order(999, cancelled));
}
