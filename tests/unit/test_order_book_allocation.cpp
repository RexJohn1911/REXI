#include "rexi/order_book/order_book.hpp"

#include "allocation_guard.hpp"

#include <gtest/gtest.h>

using namespace rexi::order_book;
using rexi::test::ScopedAllocationGuard;

TEST(OrderBookAllocationTest, ZeroHeapAllocationsDuringSteadyStateOperations) {
    OrderBookConfig config{
        .initial_order_capacity = 500,
        .max_order_capacity = 500,
        .allow_pool_growth = false,
    };
    OrderBook book(100, CrossedBookPolicy::Reject, config);

    // Warm up the price level to establish the std::map node
    RestingOrder warmup{
        .order_id = 1,
        .instrument_id = 100,
        .side = Side::Buy,
        .price = 1000,
        .initial_quantity = 50,
        .remaining_quantity = 50,
        .priority_seq = 1,
    };
    EXPECT_EQ(book.add_order(warmup), OrderBookStatus::Success);

    // Activate allocation tracking for steady-state operations
    {
        ScopedAllocationGuard guard;

        // 1. Add orders at existing level
        for (uint64_t i = 2; i <= 20; ++i) {
            RestingOrder ord{
                .order_id = i,
                .instrument_id = 100,
                .side = Side::Buy,
                .price = 1000,
                .initial_quantity = 25,
                .remaining_quantity = 25,
                .priority_seq = i,
            };
            EXPECT_EQ(book.add_order(ord), OrderBookStatus::Success);
        }
        EXPECT_EQ(guard.allocations(), 0);

        // 2. Lookup order
        const RestingOrder* found = book.find_order(5);
        ASSERT_NE(found, nullptr);
        EXPECT_EQ(found->order_id, 5);
        EXPECT_EQ(guard.allocations(), 0);

        // 3. FIFO queue position query
        auto pos = book.get_queue_position(5);
        EXPECT_TRUE(pos.has_value());
        EXPECT_EQ(guard.allocations(), 0);

        // 4. Quantity reduction
        EXPECT_EQ(book.reduce_order(5, 10), OrderBookStatus::Success);
        EXPECT_EQ(guard.allocations(), 0);

        // 5. Quantity modification (increase - moves to back)
        EXPECT_EQ(book.modify_order(6, 40), OrderBookStatus::Success);
        EXPECT_EQ(guard.allocations(), 0);

        // 6. Cancellation
        EXPECT_EQ(book.cancel_order(7), OrderBookStatus::Success);
        EXPECT_EQ(guard.allocations(), 0);

        // 7. Level 1 top-of-book queries
        auto best = book.best_bid();
        EXPECT_TRUE(best.has_value());
        auto quote = book.top_quote();
        EXPECT_TRUE(quote.has_bids());
        EXPECT_EQ(guard.allocations(), 0);

        // 8. Internal invariant validation
        auto val = book.validate();
        EXPECT_TRUE(val.is_valid);
        EXPECT_EQ(guard.allocations(), 0);
    }
}
