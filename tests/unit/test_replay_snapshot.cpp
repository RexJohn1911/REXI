#include "rexi/replay/replay_engine.hpp"
#include "rexi/replay/synthetic_generator.hpp"

#include <gtest/gtest.h>

using namespace rexi::market_data;
using namespace rexi::replay;

TEST(ReplaySnapshotTest, SnapshotFollowedByIncrementalStream) {
    auto events = SyntheticReplayFixtureGenerator::create_snapshot_and_incremental_stream();
    ASSERT_EQ(events.size(), 3);

    InMemoryReplayReader reader(events);
    ReplayConfig config{
        .validation_policy = ValidationPolicy::Strict,
        .verify_sequence = true,
    };
    ReplayEngine engine(100, config);
    auto res = engine.run(reader);

    EXPECT_TRUE(res.is_clean);
    EXPECT_EQ(res.stats.events_processed, 3);
    EXPECT_EQ(res.stats.snapshots_applied, 1);
    EXPECT_EQ(res.stats.book_updates, 3);  // 1 snapshot + 2 adds
    EXPECT_EQ(res.stats.sequence_gaps, 0);

    // Verify final order book state
    const auto& book = engine.book();
    EXPECT_EQ(book.best_bid_price(), 103);  // Established by increment at seq 101
    EXPECT_EQ(book.best_bid_quantity(), 50);
    EXPECT_EQ(book.best_ask_price(), 104);  // Established by increment at seq 102
    EXPECT_EQ(book.best_ask_quantity(), 75);
    EXPECT_EQ(book.spread(), 1);
}

TEST(ReplaySnapshotTest, SubsequentSnapshotReplacesOrderBookState) {
    // 1. Initial snapshot with bids at 100, asks at 105
    auto hdr1 = make_md_header(MarketDataMessageType::OrderBookSnapshot, 100, 1, 1, 10, 1000, 1000);
    OrderBookSnapshotMessage snap1{};
    snap1.last_included_sequence = 10;
    snap1.bid_levels_count = 1;
    snap1.bids[0] = OrderBookSnapshotLevel{.price = 100, .quantity = 100, .order_count = 1};
    snap1.ask_levels_count = 1;
    snap1.asks[0] = OrderBookSnapshotLevel{.price = 105, .quantity = 100, .order_count = 1};

    // 2. Second snapshot at seq 50 with bids at 200, asks at 210
    auto hdr2 = make_md_header(MarketDataMessageType::OrderBookSnapshot, 100, 1, 1, 50, 5000, 5000);
    OrderBookSnapshotMessage snap2{};
    snap2.last_included_sequence = 50;
    snap2.bid_levels_count = 1;
    snap2.bids[0] = OrderBookSnapshotLevel{.price = 200, .quantity = 50, .order_count = 1};
    snap2.ask_levels_count = 1;
    snap2.asks[0] = OrderBookSnapshotLevel{.price = 210, .quantity = 50, .order_count = 1};

    // 3. Incremental add following second snapshot at seq 51
    auto hdr3 = make_md_header(MarketDataMessageType::OrderBookAdd, 100, 1, 1, 51, 6000, 6000);
    OrderBookAddMessage add_msg{
        .order_id = 999, .side = MarketSide::Buy, .price = 205, .quantity = 25};

    std::vector<ReplayEvent> events{
        make_replay_snapshot(hdr1, snap1, 0),
        make_replay_snapshot(hdr2, snap2, 1),
        make_replay_add(hdr3, add_msg, 2),
    };

    InMemoryReplayReader reader(events);
    ReplayEngine engine(100);
    auto res = engine.run(reader);

    EXPECT_TRUE(res.is_clean);
    EXPECT_EQ(res.stats.snapshots_applied, 2);
    EXPECT_EQ(engine.book().best_bid_price(), 205);
    EXPECT_EQ(engine.book().best_ask_price(), 210);
}
