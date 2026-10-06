#include "rexi/order_book/order_book.hpp"

#include <gtest/gtest.h>

using namespace rexi::order_book;

class OrderBookL3Test : public ::testing::Test {
protected:
    void SetUp() override { book_ = OrderBook(100); }

    OrderBook book_{100};
};

TEST_F(OrderBookL3Test, FifoOrderingAtSamePrice) {
    // Insert 3 orders at price 100 in sequence: A (id 1), B (id 2), C (id 3)
    EXPECT_EQ(book_.add_order(RestingOrder{.order_id = 1,
                                           .instrument_id = 100,
                                           .side = Side::Buy,
                                           .price = 100,
                                           .initial_quantity = 10,
                                           .remaining_quantity = 10,
                                           .priority_seq = 1}),
              OrderBookStatus::Success);
    EXPECT_EQ(book_.add_order(RestingOrder{.order_id = 2,
                                           .instrument_id = 100,
                                           .side = Side::Buy,
                                           .price = 100,
                                           .initial_quantity = 20,
                                           .remaining_quantity = 20,
                                           .priority_seq = 2}),
              OrderBookStatus::Success);
    EXPECT_EQ(book_.add_order(RestingOrder{.order_id = 3,
                                           .instrument_id = 100,
                                           .side = Side::Buy,
                                           .price = 100,
                                           .initial_quantity = 30,
                                           .remaining_quantity = 30,
                                           .priority_seq = 3}),
              OrderBookStatus::Success);

    EXPECT_EQ(book_.order_count(), 3);
    EXPECT_EQ(book_.total_bid_quantity(), 60);

    // Verify queue positions (0-indexed)
    EXPECT_EQ(book_.get_queue_position(1), 0);
    EXPECT_EQ(book_.get_queue_position(2), 1);
    EXPECT_EQ(book_.get_queue_position(3), 2);

    auto orders = book_.orders_at_level(Side::Buy, 100);
    ASSERT_EQ(orders.size(), 3);
    EXPECT_EQ(orders[0].order_id, 1);
    EXPECT_EQ(orders[1].order_id, 2);
    EXPECT_EQ(orders[2].order_id, 3);

    EXPECT_TRUE(book_.validate().is_valid);
}

TEST_F(OrderBookL3Test, CancelMiddleOrderPreservesOtherOrdersFifo) {
    // Insert orders 1, 2, 3 at price 100
    book_.add_order(RestingOrder{.order_id = 1,
                                 .instrument_id = 100,
                                 .side = Side::Buy,
                                 .price = 100,
                                 .initial_quantity = 10,
                                 .remaining_quantity = 10});
    book_.add_order(RestingOrder{.order_id = 2,
                                 .instrument_id = 100,
                                 .side = Side::Buy,
                                 .price = 100,
                                 .initial_quantity = 20,
                                 .remaining_quantity = 20});
    book_.add_order(RestingOrder{.order_id = 3,
                                 .instrument_id = 100,
                                 .side = Side::Buy,
                                 .price = 100,
                                 .initial_quantity = 30,
                                 .remaining_quantity = 30});

    // Cancel middle order (2)
    RestingOrder cancelled{};
    EXPECT_EQ(book_.cancel_order(2, &cancelled), OrderBookStatus::Success);
    EXPECT_EQ(cancelled.order_id, 2);
    EXPECT_EQ(cancelled.remaining_quantity, 20);

    EXPECT_EQ(book_.order_count(), 2);
    EXPECT_EQ(book_.total_bid_quantity(), 40);

    // Order 1 is still pos 0, Order 3 is now pos 1
    EXPECT_EQ(book_.get_queue_position(1), 0);
    EXPECT_EQ(book_.get_queue_position(2), std::nullopt);
    EXPECT_EQ(book_.get_queue_position(3), 1);

    auto orders = book_.orders_at_level(Side::Buy, 100);
    ASSERT_EQ(orders.size(), 2);
    EXPECT_EQ(orders[0].order_id, 1);
    EXPECT_EQ(orders[1].order_id, 3);

    EXPECT_TRUE(book_.validate().is_valid);
}

TEST_F(OrderBookL3Test, CancelFirstAndLastOrder) {
    book_.add_order(RestingOrder{.order_id = 1,
                                 .instrument_id = 100,
                                 .side = Side::Sell,
                                 .price = 200,
                                 .initial_quantity = 10,
                                 .remaining_quantity = 10});
    book_.add_order(RestingOrder{.order_id = 2,
                                 .instrument_id = 100,
                                 .side = Side::Sell,
                                 .price = 200,
                                 .initial_quantity = 20,
                                 .remaining_quantity = 20});
    book_.add_order(RestingOrder{.order_id = 3,
                                 .instrument_id = 100,
                                 .side = Side::Sell,
                                 .price = 200,
                                 .initial_quantity = 30,
                                 .remaining_quantity = 30});

    // Cancel first order (1)
    EXPECT_EQ(book_.cancel_order(1), OrderBookStatus::Success);
    EXPECT_EQ(book_.get_queue_position(2), 0);
    EXPECT_EQ(book_.get_queue_position(3), 1);

    // Cancel last order (3)
    EXPECT_EQ(book_.cancel_order(3), OrderBookStatus::Success);
    EXPECT_EQ(book_.get_queue_position(2), 0);
    EXPECT_EQ(book_.order_count(), 1);

    EXPECT_TRUE(book_.validate().is_valid);
}

TEST_F(OrderBookL3Test, QuantityReductionPreservesPriority) {
    // Orders 1, 2, 3 at price 100
    book_.add_order(RestingOrder{.order_id = 1,
                                 .instrument_id = 100,
                                 .side = Side::Buy,
                                 .price = 100,
                                 .initial_quantity = 50,
                                 .remaining_quantity = 50});
    book_.add_order(RestingOrder{.order_id = 2,
                                 .instrument_id = 100,
                                 .side = Side::Buy,
                                 .price = 100,
                                 .initial_quantity = 50,
                                 .remaining_quantity = 50});

    // Reduce order 1 from 50 to 30 (reduce_order by 20)
    RestingOrder out{};
    EXPECT_EQ(book_.reduce_order(1, 20, &out), OrderBookStatus::Success);
    EXPECT_EQ(out.remaining_quantity, 30);
    EXPECT_EQ(book_.total_bid_quantity(), 80);

    // Order 1 MUST still be at queue position 0 (preserved priority)
    EXPECT_EQ(book_.get_queue_position(1), 0);
    EXPECT_EQ(book_.get_queue_position(2), 1);

    // Modify order 1 from 30 down to 15 (modify_order)
    EXPECT_EQ(book_.modify_order(1, 15), OrderBookStatus::Success);
    EXPECT_EQ(book_.total_bid_quantity(), 65);
    EXPECT_EQ(book_.get_queue_position(1), 0);
    EXPECT_EQ(book_.get_queue_position(2), 1);

    EXPECT_TRUE(book_.validate().is_valid);
}

TEST_F(OrderBookL3Test, FullExecutionRemovesOrderAndLevel) {
    book_.add_order(RestingOrder{.order_id = 1,
                                 .instrument_id = 100,
                                 .side = Side::Buy,
                                 .price = 100,
                                 .initial_quantity = 50,
                                 .remaining_quantity = 50});

    RestingOrder out{};
    EXPECT_EQ(book_.reduce_order(1, 50, &out), OrderBookStatus::Success);
    EXPECT_EQ(out.remaining_quantity, 0);

    EXPECT_EQ(book_.order_count(), 0);
    EXPECT_FALSE(book_.has_order(1));
    EXPECT_EQ(book_.find_order(1), nullptr);
    EXPECT_FALSE(book_.has_bids());
    EXPECT_EQ(book_.bid_level_count(), 0);

    EXPECT_TRUE(book_.validate().is_valid);
}

TEST_F(OrderBookL3Test, QuantityIncreaseLosesPriority) {
    // Orders 1, 2 at price 100
    book_.add_order(RestingOrder{.order_id = 1,
                                 .instrument_id = 100,
                                 .side = Side::Buy,
                                 .price = 100,
                                 .initial_quantity = 50,
                                 .remaining_quantity = 50});
    book_.add_order(RestingOrder{.order_id = 2,
                                 .instrument_id = 100,
                                 .side = Side::Buy,
                                 .price = 100,
                                 .initial_quantity = 50,
                                 .remaining_quantity = 50});

    EXPECT_EQ(book_.get_queue_position(1), 0);
    EXPECT_EQ(book_.get_queue_position(2), 1);

    // Increase order 1 quantity from 50 to 100: MUST lose priority and move to back!
    EXPECT_EQ(book_.modify_order(1, 100), OrderBookStatus::Success);
    EXPECT_EQ(book_.total_bid_quantity(), 150);

    EXPECT_EQ(book_.get_queue_position(2), 0);
    EXPECT_EQ(book_.get_queue_position(1), 1);

    auto orders = book_.orders_at_level(Side::Buy, 100);
    ASSERT_EQ(orders.size(), 2);
    EXPECT_EQ(orders[0].order_id, 2);
    EXPECT_EQ(orders[1].order_id, 1);
    EXPECT_EQ(orders[1].remaining_quantity, 100);

    EXPECT_TRUE(book_.validate().is_valid);
}

TEST_F(OrderBookL3Test, PriceReplacementLosesPriorityAndMovesLevel) {
    // Order 1 at 100, Order 2 at 99
    book_.add_order(RestingOrder{.order_id = 1,
                                 .instrument_id = 100,
                                 .side = Side::Buy,
                                 .price = 100,
                                 .initial_quantity = 50,
                                 .remaining_quantity = 50});
    book_.add_order(RestingOrder{.order_id = 2,
                                 .instrument_id = 100,
                                 .side = Side::Buy,
                                 .price = 99,
                                 .initial_quantity = 40,
                                 .remaining_quantity = 40});

    // Replace order 1 to price 99 with quantity 60: joins back of level 99!
    EXPECT_EQ(book_.replace_order(1, 99, 60), OrderBookStatus::Success);

    EXPECT_EQ(book_.bid_level_count(), 1);
    EXPECT_EQ(book_.best_bid_price(), 99);
    EXPECT_EQ(book_.total_bid_quantity(), 100);

    // Order 2 joined 99 first, so Order 2 is pos 0, Order 1 is pos 1
    EXPECT_EQ(book_.get_queue_position(2), 0);
    EXPECT_EQ(book_.get_queue_position(1), 1);

    EXPECT_TRUE(book_.validate().is_valid);
}

TEST_F(OrderBookL3Test, ErrorHandlingAndInputValidation) {
    // 1. Invalid OrderId
    EXPECT_EQ(book_.add_order(RestingOrder{.order_id = 0,
                                           .instrument_id = 100,
                                           .side = Side::Buy,
                                           .price = 100,
                                           .initial_quantity = 10,
                                           .remaining_quantity = 10}),
              OrderBookStatus::InvalidOrderId);

    // 2. Duplicate OrderId
    book_.add_order(RestingOrder{.order_id = 10,
                                 .instrument_id = 100,
                                 .side = Side::Buy,
                                 .price = 100,
                                 .initial_quantity = 10,
                                 .remaining_quantity = 10});
    EXPECT_EQ(book_.add_order(RestingOrder{.order_id = 10,
                                           .instrument_id = 100,
                                           .side = Side::Buy,
                                           .price = 101,
                                           .initial_quantity = 10,
                                           .remaining_quantity = 10}),
              OrderBookStatus::DuplicateOrderId);

    // 3. Unknown OrderId for cancel/reduce/modify
    EXPECT_EQ(book_.cancel_order(999), OrderBookStatus::OrderNotFound);
    EXPECT_EQ(book_.reduce_order(999, 5), OrderBookStatus::OrderNotFound);
    EXPECT_EQ(book_.modify_order(999, 20), OrderBookStatus::OrderNotFound);
    EXPECT_EQ(book_.replace_order(999, 100, 20), OrderBookStatus::OrderNotFound);

    // 4. Invalid Quantity
    EXPECT_EQ(book_.add_order(RestingOrder{.order_id = 11,
                                           .instrument_id = 100,
                                           .side = Side::Buy,
                                           .price = 100,
                                           .initial_quantity = 0,
                                           .remaining_quantity = 0}),
              OrderBookStatus::InvalidQuantity);
    EXPECT_EQ(book_.reduce_order(10, 0), OrderBookStatus::InvalidQuantity);
    EXPECT_EQ(book_.reduce_order(10, 50), OrderBookStatus::QuantityExceedsRemaining);
    EXPECT_EQ(book_.modify_order(10, 0), OrderBookStatus::InvalidQuantity);
    EXPECT_EQ(book_.replace_order(10, 100, 0), OrderBookStatus::InvalidQuantity);

    // 5. Invalid Price
    EXPECT_EQ(book_.add_order(RestingOrder{.order_id = 12,
                                           .instrument_id = 100,
                                           .side = Side::Buy,
                                           .price = 0,
                                           .initial_quantity = 10,
                                           .remaining_quantity = 10}),
              OrderBookStatus::InvalidPrice);
    EXPECT_EQ(book_.replace_order(10, 0, 10), OrderBookStatus::InvalidPrice);

    // 6. Instrument Mismatch
    EXPECT_EQ(book_.add_order(RestingOrder{.order_id = 13,
                                           .instrument_id = 200,  // Configured is 100
                                           .side = Side::Buy,
                                           .price = 100,
                                           .initial_quantity = 10,
                                           .remaining_quantity = 10}),
              OrderBookStatus::InstrumentMismatch);

    EXPECT_TRUE(book_.validate().is_valid);
}
