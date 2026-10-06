#include "rexi/events/clock.hpp"
#include "rexi/events/event.hpp"
#include "rexi/events/event_bus.hpp"
#include "rexi/events/event_dispatcher.hpp"
#include "rexi/events/event_header.hpp"
#include "rexi/events/event_types.hpp"
#include "rexi/events/foundation_events.hpp"
#include "rexi/events/source_id.hpp"

#include <gtest/gtest.h>

namespace rexi::events::tests {

TEST(EventArchitectureTest, HeaderLayoutAndSize) {
    EXPECT_EQ(sizeof(EventHeader), 24U);
    EXPECT_TRUE(std::is_trivially_copyable_v<EventHeader>);
    EXPECT_TRUE(std::is_standard_layout_v<EventHeader>);

    const auto header =
        make_header(EventType::TimerTick, SourceId::Internal, 42U, 0x01U, 123456789ULL);
    EXPECT_EQ(header.type, EventType::TimerTick);
    EXPECT_EQ(header.source, SourceId::Internal);
    EXPECT_EQ(header.sequence_num, 42U);
    EXPECT_EQ(header.flags, 0x01U);
    EXPECT_EQ(header.timestamp_ns, 123456789ULL);
}

TEST(EventArchitectureTest, MonotonicClockProducesIncreasingTimestamps) {
    const auto ts1 = MonotonicClock::now_ns();
    const auto ts2 = MonotonicClock::now_ns();
    EXPECT_GE(ts2, ts1);
}

TEST(EventArchitectureTest, SourceIdToStringConversion) {
    EXPECT_EQ(to_string(SourceId::Unknown), "Unknown");
    EXPECT_EQ(to_string(SourceId::Internal), "Internal");
    EXPECT_EQ(to_string(SourceId::Simulator), "Simulator");
    EXPECT_EQ(to_string(SourceId::Engine), "Engine");
    EXPECT_EQ(to_string(SourceId::Test), "Test");
}

TEST(EventArchitectureTest, EventTypeToStringConversion) {
    EXPECT_EQ(to_string(EventType::Unknown), "Unknown");
    EXPECT_EQ(to_string(EventType::TimerTick), "TimerTick");
    EXPECT_EQ(to_string(EventType::Heartbeat), "Heartbeat");
    EXPECT_EQ(to_string(EventType::SystemStatus), "SystemStatus");
    EXPECT_EQ(to_string(EventType::TestEvent), "TestEvent");
}

TEST(EventArchitectureTest, StronglyTypedEventConstruction) {
    const TimerTickPayload payload{.tick_id = 101U, .interval_ns = 1'000'000U};
    const auto event = make_event(payload, SourceId::Engine, 1U);

    EXPECT_EQ(event.header.type, EventType::TimerTick);
    EXPECT_EQ(event.header.source, SourceId::Engine);
    EXPECT_EQ(event.header.sequence_num, 1U);
    EXPECT_GT(event.header.timestamp_ns, 0U);
    EXPECT_EQ(event.payload.tick_id, 101U);
    EXPECT_EQ(event.payload.interval_ns, 1'000'000U);
}

TEST(EventArchitectureTest, DispatcherZeroSubscribers) {
    EventDispatcher dispatcher;
    EXPECT_EQ(dispatcher.subscriber_count(EventType::TimerTick), 0U);

    const TimerTickPayload payload{.tick_id = 1U, .interval_ns = 1000U};
    const auto event = make_event(payload);

    const size_t invoked = dispatcher.dispatch(event);
    EXPECT_EQ(invoked, 0U);
}

TEST(EventArchitectureTest, DispatcherSingleAndMultipleSubscribers) {
    EventDispatcher dispatcher;
    uint32_t call_count_1 = 0;
    uint32_t call_count_2 = 0;
    uint64_t received_val = 0;

    dispatcher.subscribe<TestEventPayload>([&](const TestEvent& ev) {
        ++call_count_1;
        received_val += ev.payload.value_a;
    });

    dispatcher.subscribe<TestEventPayload>([&](const TestEvent& ev) {
        ++call_count_2;
        received_val += ev.payload.value_b;
    });

    EXPECT_EQ(dispatcher.subscriber_count(EventType::TestEvent), 2U);

    const TestEventPayload payload{.value_a = 10U, .value_b = 20U, .value_c = 30U};
    const auto event = make_event(payload);

    const size_t invoked = dispatcher.dispatch(event);
    EXPECT_EQ(invoked, 2U);
    EXPECT_EQ(call_count_1, 1U);
    EXPECT_EQ(call_count_2, 1U);
    EXPECT_EQ(received_val, 30U);
}

TEST(EventArchitectureTest, DispatcherClearHandlers) {
    EventDispatcher dispatcher;
    dispatcher.subscribe<TimerTickPayload>([](const TimerTickEvent&) {});
    EXPECT_EQ(dispatcher.subscriber_count(EventType::TimerTick), 1U);

    dispatcher.clear();
    EXPECT_EQ(dispatcher.subscriber_count(EventType::TimerTick), 0U);
}

TEST(EventArchitectureTest, EventBusSynchronousAndAsynchronousDispatch) {
    EventBus<TestEvent, 64> bus;
    uint32_t sync_count = 0;
    uint32_t async_count = 0;

    bus.dispatcher().subscribe<TestEventPayload>([&](const TestEvent& ev) {
        if (ev.header.flags == 1U) {
            ++sync_count;
        } else {
            ++async_count;
        }
    });

    // Synchronous dispatch
    const auto sync_event = make_event(
        TestEventPayload{.value_a = 1U, .value_b = 2U, .value_c = 3U}, SourceId::Internal, 1U, 1U);
    bus.publish_sync(sync_event);
    EXPECT_EQ(sync_count, 1U);
    EXPECT_EQ(async_count, 0U);

    // Asynchronous queued dispatch
    const auto async_event = make_event(
        TestEventPayload{.value_a = 4U, .value_b = 5U, .value_c = 6U}, SourceId::Internal, 2U, 0U);
    EXPECT_TRUE(bus.publish_async(async_event));
    EXPECT_FALSE(bus.is_queue_empty());
    EXPECT_EQ(bus.pending_count(), 1U);

    const bool polled = bus.poll_one();
    EXPECT_TRUE(polled);
    EXPECT_TRUE(bus.is_queue_empty());
    EXPECT_EQ(async_count, 1U);
}

}  // namespace rexi::events::tests
