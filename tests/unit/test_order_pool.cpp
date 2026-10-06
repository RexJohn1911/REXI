#include "rexi/order_book/order_pool.hpp"
#include "rexi/order_book/resting_order.hpp"

#include <vector>

#include <gtest/gtest.h>

using namespace rexi::order_book;

TEST(OrderPoolTest, InitialStateAndCapacity) {
    OrderPoolConfig config{
        .initial_capacity = 64,
        .max_capacity = 64,
        .allow_growth = false,
    };
    OrderPool pool(config);

    EXPECT_EQ(pool.capacity(), 64);
    EXPECT_EQ(pool.allocated_count(), 0);
    EXPECT_EQ(pool.free_count(), 64);
    EXPECT_FALSE(pool.is_full());
}

TEST(OrderPoolTest, AllocationAndDeallocationLifecycle) {
    OrderPoolConfig config{
        .initial_capacity = 4,
        .max_capacity = 4,
        .allow_growth = false,
    };
    OrderPool pool(config);

    RestingOrder ord1{.order_id = 101, .price = 1000, .remaining_quantity = 50};
    RestingOrder ord2{.order_id = 102, .price = 1000, .remaining_quantity = 75};

    OrderHandle h1 = pool.allocate(ord1);
    EXPECT_NE(h1, kInvalidOrderHandle);
    EXPECT_EQ(pool.allocated_count(), 1);
    EXPECT_TRUE(pool.is_valid_handle(h1));
    EXPECT_EQ(pool.order(h1).order_id, 101);

    OrderHandle h2 = pool.allocate(ord2);
    EXPECT_NE(h2, kInvalidOrderHandle);
    EXPECT_NE(h1, h2);
    EXPECT_EQ(pool.allocated_count(), 2);
    EXPECT_EQ(pool.order(h2).order_id, 102);

    // Deallocate h1 and verify slot reuse
    pool.deallocate(h1);
    EXPECT_EQ(pool.allocated_count(), 1);
    EXPECT_FALSE(pool.is_valid_handle(h1));

    // Next allocate should immediately reuse h1
    RestingOrder ord3{.order_id = 103, .price = 1000, .remaining_quantity = 90};
    OrderHandle h3 = pool.allocate(ord3);
    EXPECT_EQ(h3, h1);
    EXPECT_EQ(pool.allocated_count(), 2);
    EXPECT_EQ(pool.order(h3).order_id, 103);

    // Deallocate remaining
    pool.deallocate(h2);
    pool.deallocate(h3);
    EXPECT_EQ(pool.allocated_count(), 0);
    EXPECT_EQ(pool.free_count(), 4);
}

TEST(OrderPoolTest, FixedCapacityExhaustion) {
    OrderPoolConfig config{
        .initial_capacity = 2,
        .max_capacity = 2,
        .allow_growth = false,
    };
    OrderPool pool(config);

    RestingOrder o1{.order_id = 1, .price = 100, .remaining_quantity = 10};
    RestingOrder o2{.order_id = 2, .price = 100, .remaining_quantity = 20};
    RestingOrder o3{.order_id = 3, .price = 100, .remaining_quantity = 30};

    OrderHandle h1 = pool.allocate(o1);
    OrderHandle h2 = pool.allocate(o2);
    EXPECT_NE(h1, kInvalidOrderHandle);
    EXPECT_NE(h2, kInvalidOrderHandle);
    EXPECT_TRUE(pool.is_full());

    // Third allocation should fail deterministically
    OrderHandle h3 = pool.allocate(o3);
    EXPECT_EQ(h3, kInvalidOrderHandle);
    EXPECT_EQ(pool.allocated_count(), 2);

    // Release one slot and re-allocate
    pool.deallocate(h1);
    EXPECT_FALSE(pool.is_full());

    OrderHandle h4 = pool.allocate(o3);
    EXPECT_NE(h4, kInvalidOrderHandle);
    EXPECT_EQ(h4, h1);
    EXPECT_EQ(pool.order(h4).order_id, 3);
}

TEST(OrderPoolTest, ControlledGrowthUpToMaxCapacity) {
    OrderPoolConfig config{
        .initial_capacity = 2,
        .max_capacity = 4,
        .allow_growth = true,
    };
    OrderPool pool(config);

    RestingOrder o1{.order_id = 1};
    RestingOrder o2{.order_id = 2};
    RestingOrder o3{.order_id = 3};
    RestingOrder o4{.order_id = 4};
    RestingOrder o5{.order_id = 5};

    EXPECT_NE(pool.allocate(o1), kInvalidOrderHandle);
    EXPECT_NE(pool.allocate(o2), kInvalidOrderHandle);
    EXPECT_EQ(pool.capacity(), 2);

    // Triggers growth to 4
    OrderHandle h3 = pool.allocate(o3);
    EXPECT_NE(h3, kInvalidOrderHandle);
    EXPECT_EQ(pool.capacity(), 4);

    OrderHandle h4 = pool.allocate(o4);
    EXPECT_NE(h4, kInvalidOrderHandle);
    EXPECT_EQ(pool.allocated_count(), 4);
    EXPECT_TRUE(pool.is_full());

    // 5th allocation exceeds max_capacity = 4
    EXPECT_EQ(pool.allocate(o5), kInvalidOrderHandle);
}

TEST(OrderPoolTest, ClearReinitializesFreeListWithoutReallocation) {
    OrderPoolConfig config{
        .initial_capacity = 10,
        .max_capacity = 10,
        .allow_growth = false,
    };
    OrderPool pool(config);

    for (uint64_t i = 1; i <= 10; ++i) {
        RestingOrder ord{.order_id = i};
        EXPECT_NE(pool.allocate(ord), kInvalidOrderHandle);
    }
    EXPECT_TRUE(pool.is_full());

    pool.clear();
    EXPECT_EQ(pool.allocated_count(), 0);
    EXPECT_EQ(pool.free_count(), 10);
    EXPECT_FALSE(pool.is_full());

    // Should be able to re-allocate all 10 slots
    for (uint64_t i = 1; i <= 10; ++i) {
        RestingOrder ord{.order_id = i + 100};
        EXPECT_NE(pool.allocate(ord), kInvalidOrderHandle);
    }
    EXPECT_EQ(pool.allocated_count(), 10);
}
