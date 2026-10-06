#include "rexi/replay/replay_engine.hpp"

#include <vector>

#include <gtest/gtest.h>

#include "allocation_guard.hpp"

using namespace rexi::market_data;
using namespace rexi::order_book;
using namespace rexi::replay;
using rexi::test::ScopedAllocationGuard;

TEST(ReplayAllocationTest, ZeroHeapAllocationsDuringSteadyStateReplay) {
    ReplayConfig config{
        .validation_policy = ValidationPolicy::Strict,
        .verify_sequence = true,
        .verify_checksum = false,
        .book_config =
            {
                .initial_order_capacity = 1000,
                .max_order_capacity = 1000,
                .allow_pool_growth = false,
            },
    };
    ReplayEngine engine(100, config);

    // Warm up the price levels in OrderBook so std::map nodes are already allocated
    {
        RestingOrder warm_buy{
            .order_id = 10000,
            .instrument_id = 100,
            .side = Side::Buy,
            .price = 100,
            .initial_quantity = 1,
            .remaining_quantity = 1,
            .priority_seq = 10000,
        };
        RestingOrder warm_sell{
            .order_id = 10001,
            .instrument_id = 100,
            .side = Side::Sell,
            .price = 105,
            .initial_quantity = 1,
            .remaining_quantity = 1,
            .priority_seq = 10001,
        };
        EXPECT_EQ(engine.book().add_order(warm_buy), OrderBookStatus::Success);
        EXPECT_EQ(engine.book().add_order(warm_sell), OrderBookStatus::Success);
    }

    // Pre-create replay events at the existing price levels
    std::vector<ReplayEvent> events;
    events.reserve(20);

    Timestamp ts = 1'000'000ULL;
    SequenceNumber seq = 1;
    uint64_t idx = 0;

    // 1. Adds at existing levels (100 and 105)
    for (uint64_t id = 1; id <= 5; ++id) {
        auto hdr = make_md_header(MarketDataMessageType::OrderBookAdd, 100, 1, 1, seq++, ts, ts);
        OrderBookAddMessage msg{
            .order_id = id, .side = MarketSide::Buy, .price = 100, .quantity = 10};
        events.push_back(make_replay_add(hdr, msg, idx++));
        ts += 1000;
    }
    for (uint64_t id = 6; id <= 10; ++id) {
        auto hdr = make_md_header(MarketDataMessageType::OrderBookAdd, 100, 1, 1, seq++, ts, ts);
        OrderBookAddMessage msg{
            .order_id = id, .side = MarketSide::Sell, .price = 105, .quantity = 10};
        events.push_back(make_replay_add(hdr, msg, idx++));
        ts += 1000;
    }

    // 2. Modifies (quantity reduce)
    {
        auto hdr = make_md_header(MarketDataMessageType::OrderBookModify, 100, 1, 1, seq++, ts, ts);
        OrderBookModifyMessage msg{
            .order_id = 1,
            .side = MarketSide::Buy,
            .price = 100,
            .new_quantity = 5,
            .delta_quantity = 5,
        };
        events.push_back(make_replay_modify(hdr, msg, idx++));
        ts += 1000;
    }

    // 3. Deletes
    {
        auto hdr = make_md_header(MarketDataMessageType::OrderBookDelete, 100, 1, 1, seq++, ts, ts);
        OrderBookDeleteMessage msg{
            .order_id = 2, .side = MarketSide::Buy, .price = 100, .cancelled_quantity = 10};
        events.push_back(make_replay_delete(hdr, msg, idx++));
        ts += 1000;
    }

    InMemoryReplayReader reader(events);

    // Verify steady-state replay introduces ZERO heap allocations
    {
        ScopedAllocationGuard guard;

        while (reader.has_next()) {
            EXPECT_TRUE(engine.step(reader));
        }

        EXPECT_EQ(guard.allocations(), 0);
    }

    EXPECT_EQ(engine.statistics().events_processed, events.size());
}
