#include "rexi/order_book/order_book.hpp"

#include <random>
#include <vector>

#include <gtest/gtest.h>

using namespace rexi::order_book;

TEST(OrderBookDeterminismTest, IdenticalOperationSequenceProducesBitForBitIdenticalState) {
    OrderBook book1(100);
    OrderBook book2(100);

    // Sequence of 50 operations
    for (uint64_t i = 1; i <= 20; ++i) {
        RestingOrder bid{
            .order_id = i,
            .instrument_id = 100,
            .side = Side::Buy,
            .price = static_cast<Price>(1000 + (i % 5)),
            .initial_quantity = i * 10,
            .remaining_quantity = i * 10,
            .priority_seq = i,
            .timestamp_ns = i * 1000,
        };
        EXPECT_EQ(book1.add_order(bid), book2.add_order(bid));
    }

    for (uint64_t i = 21; i <= 40; ++i) {
        RestingOrder ask{
            .order_id = i,
            .instrument_id = 100,
            .side = Side::Sell,
            .price = static_cast<Price>(2000 + (i % 5)),
            .initial_quantity = i * 5,
            .remaining_quantity = i * 5,
            .priority_seq = i,
            .timestamp_ns = i * 1000,
        };
        EXPECT_EQ(book1.add_order(ask), book2.add_order(ask));
    }

    // Cancel some
    for (uint64_t i = 5; i <= 15; i += 2) {
        EXPECT_EQ(book1.cancel_order(i), book2.cancel_order(i));
    }

    // Reduce some
    for (uint64_t i = 22; i <= 30; i += 2) {
        EXPECT_EQ(book1.reduce_order(i, 10), book2.reduce_order(i, 10));
    }

    // Replace some
    for (uint64_t i = 32; i <= 36; ++i) {
        EXPECT_EQ(book1.replace_order(i, 2050, 45), book2.replace_order(i, 2050, 45));
    }

    // Validate identical state
    EXPECT_EQ(book1.order_count(), book2.order_count());
    EXPECT_EQ(book1.best_bid_price(), book2.best_bid_price());
    EXPECT_EQ(book1.best_ask_price(), book2.best_ask_price());
    EXPECT_EQ(book1.best_bid_quantity(), book2.best_bid_quantity());
    EXPECT_EQ(book1.best_ask_quantity(), book2.best_ask_quantity());
    EXPECT_EQ(book1.total_bid_quantity(), book2.total_bid_quantity());
    EXPECT_EQ(book1.total_ask_quantity(), book2.total_ask_quantity());

    auto b1_depth = book1.bids_depth();
    auto b2_depth = book2.bids_depth();
    ASSERT_EQ(b1_depth.size(), b2_depth.size());
    for (size_t i = 0; i < b1_depth.size(); ++i) {
        EXPECT_EQ(b1_depth[i], b2_depth[i]);
    }

    auto a1_depth = book1.asks_depth();
    auto a2_depth = book2.asks_depth();
    ASSERT_EQ(a1_depth.size(), a2_depth.size());
    for (size_t i = 0; i < a1_depth.size(); ++i) {
        EXPECT_EQ(a1_depth[i], a2_depth[i]);
    }

    auto val1 = book1.validate();
    auto val2 = book2.validate();
    EXPECT_TRUE(val1.is_valid) << val1.error;
    EXPECT_TRUE(val2.is_valid) << val2.error;
}

TEST(OrderBookDeterminismTest, FixedSeedRandomizedStressAndInvariantVerification) {
    OrderBook book(100, CrossedBookPolicy::Reject);
    std::mt19937_64 rng(0x1911DECAFC001);

    std::uniform_int_distribution<int> op_dist(0, 3);  // 0: Add, 1: Reduce, 2: Cancel, 3: Replace
    std::uniform_int_distribution<Price> bid_price_dist(100, 149);
    std::uniform_int_distribution<Price> ask_price_dist(151, 200);
    std::uniform_int_distribution<Quantity> qty_dist(10, 100);

    OrderId next_order_id = 1;
    std::vector<OrderId> active_order_ids;

    constexpr int NUM_OPERATIONS = 1000;
    for (int op = 0; op < NUM_OPERATIONS; ++op) {
        int action = op_dist(rng);

        if (action == 0 || active_order_ids.empty()) {
            // Add Order
            bool is_buy = (rng() % 2 == 0);
            OrderId oid = next_order_id++;
            Price p = is_buy ? bid_price_dist(rng) : ask_price_dist(rng);
            Quantity q = qty_dist(rng);

            RestingOrder ord{
                .order_id = oid,
                .instrument_id = 100,
                .side = is_buy ? Side::Buy : Side::Sell,
                .price = p,
                .initial_quantity = q,
                .remaining_quantity = q,
                .priority_seq = static_cast<SequenceNumber>(op),
                .timestamp_ns = static_cast<Timestamp>(op * 100),
            };

            auto st = book.add_order(ord);
            if (st == OrderBookStatus::Success) {
                active_order_ids.push_back(oid);
            }
        } else if (action == 1) {
            // Reduce Order
            size_t idx = rng() % active_order_ids.size();
            OrderId target_id = active_order_ids[idx];
            const RestingOrder* ord = book.find_order(target_id);
            if (ord != nullptr) {
                Quantity red = (rng() % ord->remaining_quantity) + 1;
                auto st = book.reduce_order(target_id, red);
                EXPECT_EQ(st, OrderBookStatus::Success);
                if (ord->remaining_quantity == 0) {
                    active_order_ids.erase(active_order_ids.begin() + static_cast<long>(idx));
                }
            }
        } else if (action == 2) {
            // Cancel Order
            size_t idx = rng() % active_order_ids.size();
            OrderId target_id = active_order_ids[idx];
            auto st = book.cancel_order(target_id);
            EXPECT_EQ(st, OrderBookStatus::Success);
            active_order_ids.erase(active_order_ids.begin() + static_cast<long>(idx));
        } else {
            // Replace Order
            size_t idx = rng() % active_order_ids.size();
            OrderId target_id = active_order_ids[idx];
            const RestingOrder* ord = book.find_order(target_id);
            if (ord != nullptr) {
                bool is_buy = (ord->side == Side::Buy);
                Price new_p = is_buy ? bid_price_dist(rng) : ask_price_dist(rng);
                Quantity new_q = qty_dist(rng);
                book.replace_order(target_id, new_p, new_q);
            }
        }

        // Verify invariants periodically
        if (op % 50 == 0) {
            auto val = book.validate();
            ASSERT_TRUE(val.is_valid) << "Invariant failed at op " << op << ": " << val.error;
        }
    }

    auto final_val = book.validate();
    EXPECT_TRUE(final_val.is_valid) << final_val.error;
}
