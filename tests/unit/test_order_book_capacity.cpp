#include "rexi/order_book/order_book.hpp"

#include <gtest/gtest.h>

using namespace rexi::order_book;

TEST(OrderBookCapacityTest, PoolExhaustionAndDeterministicRejection) {
    OrderBookConfig config{
        .initial_order_capacity = 5,
        .max_order_capacity = 5,
        .allow_pool_growth = false,
    };
    OrderBook book(100, CrossedBookPolicy::Reject, config);

    // Add 5 orders to saturate capacity
    for (uint64_t i = 1; i <= 5; ++i) {
        RestingOrder ord{
            .order_id = i,
            .instrument_id = 100,
            .side = Side::Buy,
            .price = static_cast<Price>(1000 - i),
            .initial_quantity = 10,
            .remaining_quantity = 10,
        };
        EXPECT_EQ(book.add_order(ord), OrderBookStatus::Success);
    }

    EXPECT_EQ(book.order_count(), 5);
    EXPECT_TRUE(book.order_pool().is_full());

    // 6th order must be deterministically rejected with PoolExhausted
    RestingOrder excess_order{
        .order_id = 6,
        .instrument_id = 100,
        .side = Side::Buy,
        .price = 990,
        .initial_quantity = 10,
        .remaining_quantity = 10,
    };
    EXPECT_EQ(book.add_order(excess_order), OrderBookStatus::PoolExhausted);

    // Verify book state was not corrupted
    EXPECT_EQ(book.order_count(), 5);
    EXPECT_FALSE(book.has_order(6));
    EXPECT_TRUE(book.validate().is_valid);

    // Cancel an order and verify slot reclamation
    EXPECT_EQ(book.cancel_order(3), OrderBookStatus::Success);
    EXPECT_EQ(book.order_count(), 4);
    EXPECT_FALSE(book.order_pool().is_full());

    // Re-attempt adding order 6 now that a slot is free
    EXPECT_EQ(book.add_order(excess_order), OrderBookStatus::Success);
    EXPECT_EQ(book.order_count(), 5);
    EXPECT_TRUE(book.has_order(6));
    EXPECT_TRUE(book.validate().is_valid);
}

TEST(OrderBookCapacityTest, PriceLevelIntrusiveQueueIntegrity) {
    OrderBookConfig config{
        .initial_order_capacity = 10,
        .max_order_capacity = 10,
        .allow_pool_growth = false,
    };
    OrderBook book(100, CrossedBookPolicy::Reject, config);

    // Add 4 orders at same price level to test intrusive queue links
    for (uint64_t i = 1; i <= 4; ++i) {
        RestingOrder ord{
            .order_id = i,
            .instrument_id = 100,
            .side = Side::Buy,
            .price = 1000,
            .initial_quantity = static_cast<Quantity>(i * 10),
            .remaining_quantity = static_cast<Quantity>(i * 10),
            .priority_seq = i,
        };
        EXPECT_EQ(book.add_order(ord), OrderBookStatus::Success);
    }

    // Verify queue positions
    EXPECT_EQ(book.get_queue_position(1), 0);
    EXPECT_EQ(book.get_queue_position(2), 1);
    EXPECT_EQ(book.get_queue_position(3), 2);
    EXPECT_EQ(book.get_queue_position(4), 3);

    // Cancel middle order 2
    EXPECT_EQ(book.cancel_order(2), OrderBookStatus::Success);
    EXPECT_EQ(book.get_queue_position(1), 0);
    EXPECT_EQ(book.get_queue_position(3), 1);
    EXPECT_EQ(book.get_queue_position(4), 2);

    // Cancel head order 1
    EXPECT_EQ(book.cancel_order(1), OrderBookStatus::Success);
    EXPECT_EQ(book.get_queue_position(3), 0);
    EXPECT_EQ(book.get_queue_position(4), 1);

    // Cancel tail order 4
    EXPECT_EQ(book.cancel_order(4), OrderBookStatus::Success);
    EXPECT_EQ(book.get_queue_position(3), 0);

    // Cancel last remaining order 3
    EXPECT_EQ(book.cancel_order(3), OrderBookStatus::Success);
    EXPECT_TRUE(book.is_empty());
    EXPECT_TRUE(book.validate().is_valid);
}
