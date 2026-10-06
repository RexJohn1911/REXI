#include "rexi/order_book/order_id_index.hpp"

#include <gtest/gtest.h>

using namespace rexi::order_book;

TEST(OrderIdIndexTest, BasicInsertFindContains) {
    OrderIdIndex index(16, false);
    EXPECT_EQ(index.size(), 0);
    EXPECT_TRUE(index.empty());

    EXPECT_TRUE(index.insert(1001, 10, Side::Buy, 500));
    EXPECT_TRUE(index.insert(1002, 11, Side::Sell, 505));
    EXPECT_EQ(index.size(), 2);

    EXPECT_TRUE(index.contains(1001));
    EXPECT_TRUE(index.contains(1002));
    EXPECT_FALSE(index.contains(9999));

    const auto* e1 = index.find(1001);
    ASSERT_NE(e1, nullptr);
    EXPECT_EQ(e1->order_id, 1001);
    EXPECT_EQ(e1->handle, 10);
    EXPECT_EQ(e1->side, Side::Buy);
    EXPECT_EQ(e1->price, 500);

    const auto* e2 = index.find(1002);
    ASSERT_NE(e2, nullptr);
    EXPECT_EQ(e2->order_id, 1002);
    EXPECT_EQ(e2->handle, 11);
    EXPECT_EQ(e2->side, Side::Sell);
    EXPECT_EQ(e2->price, 505);
}

TEST(OrderIdIndexTest, UpdateExistingKey) {
    OrderIdIndex index(16, false);
    EXPECT_TRUE(index.insert(100, 5, Side::Buy, 1000));
    EXPECT_EQ(index.size(), 1);

    // Update with new price/handle
    EXPECT_TRUE(index.insert(100, 8, Side::Buy, 1010));
    EXPECT_EQ(index.size(), 1);

    const auto* e = index.find(100);
    ASSERT_NE(e, nullptr);
    EXPECT_EQ(e->handle, 8);
    EXPECT_EQ(e->price, 1010);
}

TEST(OrderIdIndexTest, BackwardShiftDeletionMaintainsReachability) {
    OrderIdIndex index(32, false);

    // Insert keys that map to same or adjacent buckets to form probe chains
    for (uint64_t id = 1; id <= 15; ++id) {
        EXPECT_TRUE(index.insert(id, static_cast<OrderHandle>(id), Side::Buy, 100));
    }
    EXPECT_EQ(index.size(), 15);

    // Erase an element from the middle of the chain
    EXPECT_TRUE(index.erase(7));
    EXPECT_EQ(index.size(), 14);
    EXPECT_FALSE(index.contains(7));

    // Verify all remaining elements are still fully reachable
    for (uint64_t id = 1; id <= 15; ++id) {
        if (id == 7) {
            EXPECT_FALSE(index.contains(id));
        } else {
            EXPECT_TRUE(index.contains(id));
            const auto* entry = index.find(id);
            ASSERT_NE(entry, nullptr);
            EXPECT_EQ(entry->handle, static_cast<OrderHandle>(id));
        }
    }

    // Erase head and tail of remaining keys
    EXPECT_TRUE(index.erase(1));
    EXPECT_TRUE(index.erase(15));
    EXPECT_EQ(index.size(), 12);

    for (uint64_t id = 2; id <= 14; ++id) {
        if (id == 7) {
            EXPECT_FALSE(index.contains(id));
        } else {
            EXPECT_TRUE(index.contains(id));
        }
    }
}

TEST(OrderIdIndexTest, ClearAndReuse) {
    OrderIdIndex index(16, false);
    for (uint64_t id = 1; id <= 5; ++id) {
        EXPECT_TRUE(index.insert(id, static_cast<OrderHandle>(id), Side::Buy, 100));
    }
    EXPECT_EQ(index.size(), 5);

    index.clear();
    EXPECT_EQ(index.size(), 0);
    EXPECT_TRUE(index.empty());
    for (uint64_t id = 1; id <= 5; ++id) {
        EXPECT_FALSE(index.contains(id));
    }

    // Insert new elements after clear
    EXPECT_TRUE(index.insert(999, 42, Side::Sell, 200));
    EXPECT_EQ(index.size(), 1);
    EXPECT_TRUE(index.contains(999));
}
