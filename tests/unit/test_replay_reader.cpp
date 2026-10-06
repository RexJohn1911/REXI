#include "rexi/replay/replay_reader.hpp"
#include "rexi/replay/synthetic_generator.hpp"

#include <vector>

#include <gtest/gtest.h>

using namespace rexi::market_data;
using namespace rexi::replay;

TEST(ReplayReaderTest, EmptyStreamBehavior) {
    InMemoryReplayReader reader;
    EXPECT_FALSE(reader.has_next());
    EXPECT_EQ(reader.next(), nullptr);
    EXPECT_EQ(reader.total_events(), 0);
    EXPECT_EQ(reader.current_index(), 0);
    EXPECT_EQ(reader.remaining(), 0);
}

TEST(ReplayReaderTest, SingleEventLifecycle) {
    auto hdr = make_md_header(MarketDataMessageType::OrderBookAdd, 100, 1, 1, 1, 1000, 1000);
    OrderBookAddMessage msg{.order_id = 1, .side = MarketSide::Buy, .price = 100, .quantity = 10};
    std::vector<ReplayEvent> events{make_replay_add(hdr, msg, 0)};

    InMemoryReplayReader reader(events);
    EXPECT_TRUE(reader.has_next());
    EXPECT_EQ(reader.total_events(), 1);
    EXPECT_EQ(reader.remaining(), 1);

    const auto* evt = reader.next();
    ASSERT_NE(evt, nullptr);
    EXPECT_EQ(evt->sequence_num(), 1);
    EXPECT_EQ(evt->source_timestamp_ns(), 1000);

    EXPECT_FALSE(reader.has_next());
    EXPECT_EQ(reader.next(), nullptr);
    EXPECT_EQ(reader.remaining(), 0);
    EXPECT_EQ(reader.current_index(), 1);
}

TEST(ReplayReaderTest, MultipleEventsSequentialIteration) {
    auto events = SyntheticReplayFixtureGenerator::create_basic_l3_stream();
    ASSERT_FALSE(events.empty());

    InMemoryReplayReader reader(events);
    EXPECT_EQ(reader.total_events(), events.size());
    EXPECT_EQ(reader.remaining(), events.size());

    size_t count = 0;
    while (reader.has_next()) {
        const auto* evt = reader.next();
        ASSERT_NE(evt, nullptr);
        EXPECT_EQ(evt->sequence_num(), count + 1);
        ++count;
    }

    EXPECT_EQ(count, events.size());
    EXPECT_EQ(reader.current_index(), events.size());
    EXPECT_EQ(reader.remaining(), 0);
    EXPECT_EQ(reader.next(), nullptr);
}

TEST(ReplayReaderTest, ResetRestoresCursorToBeginning) {
    auto events = SyntheticReplayFixtureGenerator::create_basic_l3_stream();
    InMemoryReplayReader reader(events);

    // Read first 3 events
    ASSERT_NE(reader.next(), nullptr);
    ASSERT_NE(reader.next(), nullptr);
    ASSERT_NE(reader.next(), nullptr);
    EXPECT_EQ(reader.current_index(), 3);

    reader.reset();
    EXPECT_EQ(reader.current_index(), 0);
    EXPECT_EQ(reader.remaining(), events.size());
    EXPECT_TRUE(reader.has_next());

    const auto* first = reader.next();
    ASSERT_NE(first, nullptr);
    EXPECT_EQ(first->sequence_num(), 1);
}

TEST(ReplayReaderTest, PolymorphicInterfaceUsage) {
    auto events = SyntheticReplayFixtureGenerator::create_basic_l3_stream();
    InMemoryReplayReader concrete_reader(events);
    IReplayReader* reader = &concrete_reader;

    EXPECT_TRUE(reader->has_next());
    EXPECT_EQ(reader->total_events(), events.size());

    const auto* evt = reader->next();
    ASSERT_NE(evt, nullptr);
    EXPECT_EQ(evt->sequence_num(), 1);
    EXPECT_EQ(reader->current_index(), 1);

    reader->reset();
    EXPECT_EQ(reader->current_index(), 0);
}
