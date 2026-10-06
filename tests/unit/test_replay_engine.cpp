#include "rexi/events/event_dispatcher.hpp"
#include "rexi/replay/replay_engine.hpp"
#include "rexi/replay/synthetic_generator.hpp"

#include <vector>

#include <gtest/gtest.h>

using namespace rexi::events;
using namespace rexi::market_data;
using namespace rexi::order_book;
using namespace rexi::replay;

TEST(ReplayEngineTest, StepModeProcessesExactlyOneEventPerStep) {
    auto events = SyntheticReplayFixtureGenerator::create_basic_l3_stream();
    InMemoryReplayReader reader(events);
    ReplayEngine engine(100);

    for (size_t i = 0; i < events.size(); ++i) {
        EXPECT_TRUE(engine.step(reader));
        EXPECT_EQ(engine.statistics().events_read, i + 1);
        EXPECT_EQ(engine.statistics().events_processed, i + 1);
        EXPECT_EQ(engine.clock().event_index(), i + 1);
        EXPECT_EQ(engine.clock().current_time_ns(), events[i].source_timestamp_ns());
    }

    // Stream exhausted
    EXPECT_FALSE(engine.step(reader));
    EXPECT_EQ(engine.statistics().events_processed, events.size());
}

TEST(ReplayEngineTest, StepModeAndMaxSpeedModeProduceIdenticalFinalState) {
    auto events = SyntheticReplayFixtureGenerator::create_basic_l3_stream();

    // 1. Run in Step Mode
    InMemoryReplayReader reader_step(events);
    ReplayEngine engine_step(100);
    while (engine_step.step(reader_step)) {
    }
    uint64_t digest_step = engine_step.compute_digest();

    // 2. Run in Max Speed Mode
    InMemoryReplayReader reader_run(events);
    ReplayEngine engine_run(100);
    auto res_run = engine_run.run(reader_run);
    uint64_t digest_run = res_run.state_digest;

    EXPECT_EQ(digest_step, digest_run);
    EXPECT_EQ(engine_step.book().top_quote(), engine_run.book().top_quote());
    EXPECT_EQ(engine_step.book().order_count(), engine_run.book().order_count());
    EXPECT_EQ(engine_step.statistics().events_processed, engine_run.statistics().events_processed);
}

TEST(ReplayEngineTest, StopConditionMaxEvents) {
    auto events = SyntheticReplayFixtureGenerator::create_basic_l3_stream();
    InMemoryReplayReader reader(events);
    ReplayEngine engine(100);

    ReplayStopCondition stop_cond{.max_events = 5};
    auto res = engine.run_until(reader, stop_cond);

    EXPECT_EQ(res.stats.events_processed, 5);
    EXPECT_EQ(reader.current_index(), 5);
}

TEST(ReplayEngineTest, StopConditionStopTimestamp) {
    auto events = SyntheticReplayFixtureGenerator::create_basic_l3_stream();
    ASSERT_GE(events.size(), 6);
    Timestamp target_ts = events[4].source_timestamp_ns();

    InMemoryReplayReader reader(events);
    ReplayEngine engine(100);

    ReplayStopCondition stop_cond{.stop_timestamp_ns = target_ts};
    auto res = engine.run_until(reader, stop_cond);

    EXPECT_LE(engine.clock().current_time_ns(), target_ts);
    EXPECT_LE(res.stats.events_processed, 5);
}

TEST(ReplayEngineTest, Phase02EventDispatcherIntegration) {
    auto events = SyntheticReplayFixtureGenerator::create_basic_l3_stream();
    InMemoryReplayReader reader(events);

    EventDispatcher dispatcher;
    size_t adds_observed = 0;
    size_t modifies_observed = 0;
    size_t deletes_observed = 0;
    size_t trades_observed = 0;

    dispatcher.subscribe<OrderBookAddMessage>(
        [&](const Event<OrderBookAddMessage>&) { ++adds_observed; });
    dispatcher.subscribe<OrderBookModifyMessage>(
        [&](const Event<OrderBookModifyMessage>&) { ++modifies_observed; });
    dispatcher.subscribe<OrderBookDeleteMessage>(
        [&](const Event<OrderBookDeleteMessage>&) { ++deletes_observed; });
    dispatcher.subscribe<TradeMessage>([&](const Event<TradeMessage>&) { ++trades_observed; });

    ReplayEngine engine(100);
    engine.set_event_dispatcher(&dispatcher);
    auto res = engine.run(reader);

    EXPECT_TRUE(res.is_clean);
    EXPECT_EQ(adds_observed, 10);
    EXPECT_EQ(modifies_observed, 1);
    EXPECT_EQ(deletes_observed, 1);
    EXPECT_EQ(trades_observed, 1);
}

TEST(ReplayEngineTest, CheckpointCaptureAndRestore) {
    auto events = SyntheticReplayFixtureGenerator::create_basic_l3_stream();
    InMemoryReplayReader reader(events);
    ReplayEngine engine(100);

    // Step 5 events
    for (int i = 0; i < 5; ++i) {
        ASSERT_TRUE(engine.step(reader));
    }
    auto checkpoint = engine.create_checkpoint();
    uint64_t digest_at_5 = engine.compute_digest();

    // Step remaining events to completion
    while (engine.step(reader)) {
    }
    EXPECT_NE(engine.compute_digest(), digest_at_5);

    // Restore from checkpoint
    engine.restore_checkpoint(checkpoint);
    EXPECT_EQ(engine.compute_digest(), digest_at_5);
    EXPECT_EQ(engine.clock().event_index(), 5);
    EXPECT_EQ(engine.statistics().events_processed, 5);
}
