#include "rexi/replay/replay_engine.hpp"
#include "rexi/replay/synthetic_generator.hpp"

#include <gtest/gtest.h>

using namespace rexi::replay;

TEST(ReplayDeterminismTest, TwoIndependentEnginesYieldBitForBitIdenticalState) {
    auto events = SyntheticReplayFixtureGenerator::create_basic_l3_stream();

    InMemoryReplayReader reader1(events);
    ReplayEngine engine1(100);
    auto res1 = engine1.run(reader1);

    InMemoryReplayReader reader2(events);
    ReplayEngine engine2(100);
    auto res2 = engine2.run(reader2);

    EXPECT_EQ(res1.state_digest, res2.state_digest);
    EXPECT_EQ(res1.stats.events_processed, res2.stats.events_processed);
    EXPECT_EQ(res1.stats.first_timestamp_ns, res2.stats.first_timestamp_ns);
    EXPECT_EQ(res1.stats.last_timestamp_ns, res2.stats.last_timestamp_ns);
    EXPECT_EQ(res1.best_bid_price, res2.best_bid_price);
    EXPECT_EQ(res1.best_bid_quantity, res2.best_bid_quantity);
    EXPECT_EQ(res1.best_ask_price, res2.best_ask_price);
    EXPECT_EQ(res1.best_ask_quantity, res2.best_ask_quantity);
    EXPECT_EQ(res1.total_orders, res2.total_orders);

    // Deep compare L3 snapshot order list
    auto l3_1 = engine1.book().to_l3_snapshot();
    auto l3_2 = engine2.book().to_l3_snapshot();
    ASSERT_EQ(l3_1.orders.size(), l3_2.orders.size());
    for (size_t i = 0; i < l3_1.orders.size(); ++i) {
        EXPECT_EQ(l3_1.orders[i].order_id, l3_2.orders[i].order_id);
        EXPECT_EQ(l3_1.orders[i].side, l3_2.orders[i].side);
        EXPECT_EQ(l3_1.orders[i].price, l3_2.orders[i].price);
        EXPECT_EQ(l3_1.orders[i].remaining_quantity, l3_2.orders[i].remaining_quantity);
        EXPECT_EQ(l3_1.orders[i].priority_seq, l3_2.orders[i].priority_seq);
    }
}

TEST(ReplayDeterminismTest, RunResetRunProducesIdenticalOutput) {
    auto events = SyntheticReplayFixtureGenerator::create_basic_l3_stream();
    InMemoryReplayReader reader(events);
    ReplayEngine engine(100);

    // Run 1
    auto res1 = engine.run(reader);
    EXPECT_TRUE(res1.is_clean);
    uint64_t digest1 = res1.state_digest;

    // Reset
    reader.reset();
    engine.reset();

    // Run 2
    auto res2 = engine.run(reader);
    EXPECT_TRUE(res2.is_clean);
    uint64_t digest2 = res2.state_digest;

    EXPECT_EQ(digest1, digest2);
    EXPECT_EQ(res1.stats.events_processed, res2.stats.events_processed);
    EXPECT_EQ(res1.stats.book_updates, res2.stats.book_updates);
    EXPECT_EQ(res1.total_orders, res2.total_orders);
}

TEST(ReplayDeterminismTest, FixedSeedStressStreamDeterminismAcrossEngines) {
    constexpr size_t StressEventCount = 5000;
    auto events = SyntheticReplayFixtureGenerator::create_large_deterministic_stream(
        StressEventCount, 0x123456789ABCDEF0ULL);
    ASSERT_EQ(events.size(), StressEventCount);

    InMemoryReplayReader reader1(events);
    ReplayConfig config{
        .validation_policy = ValidationPolicy::Permissive,
        .verify_sequence = true,
        .book_config =
            {
                .initial_order_capacity = 10000,
                .max_order_capacity = 10000,
                .allow_pool_growth = false,
            },
    };

    ReplayEngine engine1(100, config);
    auto res1 = engine1.run(reader1);

    InMemoryReplayReader reader2(events);
    ReplayEngine engine2(100, config);
    auto res2 = engine2.run(reader2);

    EXPECT_EQ(res1.state_digest, res2.state_digest);
    EXPECT_EQ(res1.stats.events_processed, res2.stats.events_processed);
    EXPECT_EQ(res1.stats.book_updates, res2.stats.book_updates);
    EXPECT_EQ(res1.total_orders, res2.total_orders);
    EXPECT_EQ(engine1.book().order_count(), engine2.book().order_count());

    EXPECT_TRUE(engine1.book().validate().is_valid);
    EXPECT_TRUE(engine2.book().validate().is_valid);
}
