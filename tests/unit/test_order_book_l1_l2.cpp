#include "rexi/order_book/order_book.hpp"

#include <gtest/gtest.h>

using namespace rexi::order_book;

class OrderBookL1L2Test : public ::testing::Test {
protected:
    void SetUp() override { book_ = OrderBook(100); }

    OrderBook book_{100};
};

TEST_F(OrderBookL1L2Test, EmptyBook) {
    EXPECT_TRUE(book_.is_empty());
    EXPECT_FALSE(book_.has_bids());
    EXPECT_FALSE(book_.has_asks());
    EXPECT_EQ(book_.best_bid(), std::nullopt);
    EXPECT_EQ(book_.best_ask(), std::nullopt);
    EXPECT_EQ(book_.best_bid_price(), std::nullopt);
    EXPECT_EQ(book_.best_ask_price(), std::nullopt);
    EXPECT_EQ(book_.best_bid_quantity(), 0);
    EXPECT_EQ(book_.best_ask_quantity(), 0);
    EXPECT_EQ(book_.spread(), std::nullopt);
    EXPECT_EQ(book_.bid_level_count(), 0);
    EXPECT_EQ(book_.ask_level_count(), 0);
    EXPECT_EQ(book_.total_bid_quantity(), 0);
    EXPECT_EQ(book_.total_ask_quantity(), 0);
    EXPECT_TRUE(book_.bids_depth().empty());
    EXPECT_TRUE(book_.asks_depth().empty());

    auto val = book_.validate();
    EXPECT_TRUE(val.is_valid) << val.error;
}

TEST_F(OrderBookL1L2Test, SingleBidAndAsk) {
    RestingOrder bid{
        .order_id = 1,
        .instrument_id = 100,
        .side = Side::Buy,
        .price = 1000,
        .initial_quantity = 50,
        .remaining_quantity = 50,
        .priority_seq = 1,
        .timestamp_ns = 1000,
    };
    EXPECT_EQ(book_.add_order(bid), OrderBookStatus::Success);

    EXPECT_FALSE(book_.is_empty());
    EXPECT_TRUE(book_.has_bids());
    EXPECT_FALSE(book_.has_asks());
    ASSERT_TRUE(book_.best_bid().has_value());
    EXPECT_EQ(book_.best_bid()->price, 1000);
    EXPECT_EQ(book_.best_bid()->total_quantity, 50);
    EXPECT_EQ(book_.best_bid()->order_count, 1);
    EXPECT_EQ(book_.best_bid_price(), 1000);
    EXPECT_EQ(book_.best_bid_quantity(), 50);
    EXPECT_EQ(book_.spread(), std::nullopt);

    RestingOrder ask{
        .order_id = 2,
        .instrument_id = 100,
        .side = Side::Sell,
        .price = 1010,
        .initial_quantity = 30,
        .remaining_quantity = 30,
        .priority_seq = 2,
        .timestamp_ns = 2000,
    };
    EXPECT_EQ(book_.add_order(ask), OrderBookStatus::Success);

    EXPECT_TRUE(book_.has_bids());
    EXPECT_TRUE(book_.has_asks());
    ASSERT_TRUE(book_.best_ask().has_value());
    EXPECT_EQ(book_.best_ask()->price, 1010);
    EXPECT_EQ(book_.best_ask()->total_quantity, 30);
    EXPECT_EQ(book_.best_ask()->order_count, 1);
    EXPECT_EQ(book_.best_ask_price(), 1010);
    EXPECT_EQ(book_.best_ask_quantity(), 30);
    EXPECT_EQ(book_.spread(), 10);

    auto val = book_.validate();
    EXPECT_TRUE(val.is_valid) << val.error;
}

TEST_F(OrderBookL1L2Test, MultipleBidAndAskLevelsOrdering) {
    // Add 3 bid levels out-of-order: 100, 102, 99
    book_.add_order(RestingOrder{.order_id = 1,
                                 .instrument_id = 100,
                                 .side = Side::Buy,
                                 .price = 100,
                                 .initial_quantity = 10,
                                 .remaining_quantity = 10});
    book_.add_order(RestingOrder{.order_id = 2,
                                 .instrument_id = 100,
                                 .side = Side::Buy,
                                 .price = 102,
                                 .initial_quantity = 20,
                                 .remaining_quantity = 20});
    book_.add_order(RestingOrder{.order_id = 3,
                                 .instrument_id = 100,
                                 .side = Side::Buy,
                                 .price = 99,
                                 .initial_quantity = 30,
                                 .remaining_quantity = 30});

    // Add 3 ask levels out-of-order: 108, 105, 110
    book_.add_order(RestingOrder{.order_id = 4,
                                 .instrument_id = 100,
                                 .side = Side::Sell,
                                 .price = 108,
                                 .initial_quantity = 40,
                                 .remaining_quantity = 40});
    book_.add_order(RestingOrder{.order_id = 5,
                                 .instrument_id = 100,
                                 .side = Side::Sell,
                                 .price = 105,
                                 .initial_quantity = 50,
                                 .remaining_quantity = 50});
    book_.add_order(RestingOrder{.order_id = 6,
                                 .instrument_id = 100,
                                 .side = Side::Sell,
                                 .price = 110,
                                 .initial_quantity = 60,
                                 .remaining_quantity = 60});

    EXPECT_EQ(book_.bid_level_count(), 3);
    EXPECT_EQ(book_.ask_level_count(), 3);
    EXPECT_EQ(book_.best_bid_price(), 102);
    EXPECT_EQ(book_.best_ask_price(), 105);
    EXPECT_EQ(book_.spread(), 3);

    // Verify bids descending: 102 -> 100 -> 99
    auto bids = book_.bids_depth();
    ASSERT_EQ(bids.size(), 3);
    EXPECT_EQ(bids[0].price, 102);
    EXPECT_EQ(bids[0].total_quantity, 20);
    EXPECT_EQ(bids[1].price, 100);
    EXPECT_EQ(bids[1].total_quantity, 10);
    EXPECT_EQ(bids[2].price, 99);
    EXPECT_EQ(bids[2].total_quantity, 30);

    // Verify asks ascending: 105 -> 108 -> 110
    auto asks = book_.asks_depth();
    ASSERT_EQ(asks.size(), 3);
    EXPECT_EQ(asks[0].price, 105);
    EXPECT_EQ(asks[0].total_quantity, 50);
    EXPECT_EQ(asks[1].price, 108);
    EXPECT_EQ(asks[1].total_quantity, 40);
    EXPECT_EQ(asks[2].price, 110);
    EXPECT_EQ(asks[2].total_quantity, 60);

    // Test max depth slices
    auto top2_bids = book_.bids_depth(2);
    ASSERT_EQ(top2_bids.size(), 2);
    EXPECT_EQ(top2_bids[0].price, 102);
    EXPECT_EQ(top2_bids[1].price, 100);

    EXPECT_EQ(book_.total_bid_quantity(), 60);
    EXPECT_EQ(book_.total_ask_quantity(), 150);

    auto val = book_.validate();
    EXPECT_TRUE(val.is_valid) << val.error;
}

TEST_F(OrderBookL1L2Test, EmptyLevelCleanupAndBestPriceUpdate) {
    // Two bid levels: 100 and 105
    book_.add_order(RestingOrder{.order_id = 1,
                                 .instrument_id = 100,
                                 .side = Side::Buy,
                                 .price = 100,
                                 .initial_quantity = 50,
                                 .remaining_quantity = 50});
    book_.add_order(RestingOrder{.order_id = 2,
                                 .instrument_id = 100,
                                 .side = Side::Buy,
                                 .price = 105,
                                 .initial_quantity = 25,
                                 .remaining_quantity = 25});

    EXPECT_EQ(book_.best_bid_price(), 105);
    EXPECT_EQ(book_.bid_level_count(), 2);

    // Cancel order 2 (the only order at price 105)
    EXPECT_EQ(book_.cancel_order(2), OrderBookStatus::Success);

    // Level 105 must be completely cleaned up!
    EXPECT_EQ(book_.bid_level_count(), 1);
    EXPECT_EQ(book_.best_bid_price(), 100);
    EXPECT_EQ(book_.get_level(Side::Buy, 105), std::nullopt);

    // Cancel order 1 (the only order left)
    EXPECT_EQ(book_.cancel_order(1), OrderBookStatus::Success);
    EXPECT_EQ(book_.bid_level_count(), 0);
    EXPECT_FALSE(book_.has_bids());
    EXPECT_EQ(book_.best_bid_price(), std::nullopt);

    auto val = book_.validate();
    EXPECT_TRUE(val.is_valid) << val.error;
}

TEST_F(OrderBookL1L2Test, CrossedBookPolicyRejectVsAllow) {
    book_.set_policy(CrossedBookPolicy::Reject);

    // Best Ask = 100
    book_.add_order(RestingOrder{.order_id = 1,
                                 .instrument_id = 100,
                                 .side = Side::Sell,
                                 .price = 100,
                                 .initial_quantity = 50,
                                 .remaining_quantity = 50});

    // Attempting to place Buy at 100 (locks) or 101 (crosses) must be rejected
    RestingOrder locking_buy{.order_id = 2,
                             .instrument_id = 100,
                             .side = Side::Buy,
                             .price = 100,
                             .initial_quantity = 10,
                             .remaining_quantity = 10};
    EXPECT_EQ(book_.add_order(locking_buy), OrderBookStatus::CrossedMarketRejected);

    RestingOrder crossing_buy{.order_id = 3,
                              .instrument_id = 100,
                              .side = Side::Buy,
                              .price = 101,
                              .initial_quantity = 10,
                              .remaining_quantity = 10};
    EXPECT_EQ(book_.add_order(crossing_buy), OrderBookStatus::CrossedMarketRejected);
    EXPECT_FALSE(book_.has_bids());

    // Switch policy to Allow
    book_.set_policy(CrossedBookPolicy::Allow);
    EXPECT_EQ(book_.add_order(crossing_buy), OrderBookStatus::Success);
    EXPECT_TRUE(book_.has_bids());
    EXPECT_EQ(book_.best_bid_price(), 101);
    EXPECT_EQ(book_.best_ask_price(), 100);
    EXPECT_EQ(book_.spread(), -1);
    EXPECT_TRUE(book_.top_quote().is_crossed());

    auto val = book_.validate();
    EXPECT_TRUE(val.is_valid) << val.error;
}

TEST_F(OrderBookL1L2Test, DeepCopyPreservesIndexAndConsistency) {
    book_.add_order(RestingOrder{.order_id = 1,
                                 .instrument_id = 100,
                                 .side = Side::Buy,
                                 .price = 100,
                                 .initial_quantity = 50,
                                 .remaining_quantity = 50});
    book_.add_order(RestingOrder{.order_id = 2,
                                 .instrument_id = 100,
                                 .side = Side::Sell,
                                 .price = 105,
                                 .initial_quantity = 30,
                                 .remaining_quantity = 30});

    OrderBook copy_book = book_;
    EXPECT_EQ(copy_book.order_count(), 2);
    EXPECT_EQ(copy_book.best_bid_price(), 100);
    EXPECT_EQ(copy_book.best_ask_price(), 105);

    // Cancel order 1 in copy_book; original book should be unaffected
    EXPECT_EQ(copy_book.cancel_order(1), OrderBookStatus::Success);
    EXPECT_EQ(copy_book.order_count(), 1);
    EXPECT_FALSE(copy_book.has_bids());

    EXPECT_EQ(book_.order_count(), 2);
    EXPECT_TRUE(book_.has_bids());
    EXPECT_EQ(book_.best_bid_price(), 100);

    EXPECT_TRUE(book_.validate().is_valid);
    EXPECT_TRUE(copy_book.validate().is_valid);
}
