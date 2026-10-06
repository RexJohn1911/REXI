#include "rexi/events/event_dispatcher.hpp"
#include "rexi/market_data/events.hpp"
#include "rexi/order_book/events.hpp"
#include "rexi/replay/replay_engine.hpp"
#include "rexi/replay/synthetic_generator.hpp"

#include <vector>

#include <gtest/gtest.h>

using namespace rexi::events;
using namespace rexi::market_data;
using namespace rexi::order_book;
using namespace rexi::replay;

TEST(ReplayPipelineIntegrationTest, EndToEndReplayPipelineExecution) {
    auto events = SyntheticReplayFixtureGenerator::create_basic_l3_stream(100);
    ASSERT_FALSE(events.empty());

    EventDispatcher dispatcher;
    size_t event_bus_dispatches = 0;

    dispatcher.subscribe<OrderBookAddMessage>(
        [&](const Event<OrderBookAddMessage>&) { ++event_bus_dispatches; });
    dispatcher.subscribe<OrderBookModifyMessage>(
        [&](const Event<OrderBookModifyMessage>&) { ++event_bus_dispatches; });
    dispatcher.subscribe<OrderBookDeleteMessage>(
        [&](const Event<OrderBookDeleteMessage>&) { ++event_bus_dispatches; });
    dispatcher.subscribe<TradeMessage>([&](const Event<TradeMessage>&) { ++event_bus_dispatches; });

    ReplayConfig config{
        .validation_policy = ValidationPolicy::Strict,
        .verify_sequence = true,
        .verify_checksum = false,
        .apply_trades_to_book = false,
    };

    InMemoryReplayReader reader(events);
    ReplayEngine engine(100, config);
    engine.set_event_dispatcher(&dispatcher);

    auto result = engine.run(reader);

    // 1. Result summary checks
    EXPECT_TRUE(result.is_clean);
    EXPECT_EQ(result.stats.events_processed, events.size());
    EXPECT_EQ(result.stats.events_rejected, 0);
    EXPECT_EQ(result.stats.validation_failures, 0);
    EXPECT_EQ(result.stats.sequence_gaps, 0);
    EXPECT_EQ(event_bus_dispatches, events.size());

    // 2. Order book invariants
    const auto& book = engine.book();
    auto val = book.validate();
    EXPECT_TRUE(val.is_valid);
    EXPECT_TRUE(val.error.empty());

    // 3. Clock progression
    EXPECT_EQ(engine.clock().event_index(), events.size());
    EXPECT_EQ(engine.clock().current_time_ns(), events.back().source_timestamp_ns());
    EXPECT_EQ(engine.clock().first_time_ns(), events.front().source_timestamp_ns());
    EXPECT_GT(engine.clock().elapsed_replay_time_ns(), 0);

    // 4. State Digest reproducibility
    EXPECT_NE(result.state_digest, 0);
    EXPECT_EQ(engine.compute_digest(), result.state_digest);
}
