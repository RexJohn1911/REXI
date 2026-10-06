#include "rexi/events/event.hpp"
#include "rexi/events/event_bus.hpp"
#include "rexi/events/event_dispatcher.hpp"
#include "rexi/events/foundation_events.hpp"
#include "rexi/events/spsc_ring_buffer.hpp"

#include <benchmark/benchmark.h>

namespace rexi::events::benchmarks {

// 1. Event Construction Benchmark
static void BM_EventConstruction(benchmark::State& state) {
    uint64_t seq = 0;
    for (auto state_iter : state) {
        benchmark::DoNotOptimize(state_iter);
        const uint64_t current_seq = seq;
        ++seq;
        auto event = make_event(
            TestEventPayload{
                .value_a = current_seq, .value_b = current_seq * 2, .value_c = current_seq * 3},
            SourceId::Simulator, current_seq);
        benchmark::DoNotOptimize(event);
    }
}
BENCHMARK(BM_EventConstruction);

// 2. Direct Event Dispatch Benchmark (1 Subscriber)
static void BM_EventDispatchSingleSubscriber(benchmark::State& state) {
    EventDispatcher dispatcher;
    uint64_t sum = 0;
    dispatcher.subscribe<TestEventPayload>(
        [&sum](const TestEvent& ev) { sum += ev.payload.value_a; });

    const auto event =
        make_event(TestEventPayload{.value_a = 42U, .value_b = 84U, .value_c = 126U});

    for (auto state_iter : state) {
        benchmark::DoNotOptimize(state_iter);
        dispatcher.dispatch(event);
        benchmark::DoNotOptimize(sum);
    }
}
BENCHMARK(BM_EventDispatchSingleSubscriber);

// 3. Direct Event Dispatch Benchmark (4 Subscribers)
static void BM_EventDispatchFourSubscribers(benchmark::State& state) {
    EventDispatcher dispatcher;
    uint64_t sum = 0;
    for (int i = 0; i < 4; ++i) {
        dispatcher.subscribe<TestEventPayload>(
            [&sum](const TestEvent& ev) { sum += ev.payload.value_a; });
    }

    const auto event =
        make_event(TestEventPayload{.value_a = 42U, .value_b = 84U, .value_c = 126U});

    for (auto state_iter : state) {
        benchmark::DoNotOptimize(state_iter);
        dispatcher.dispatch(event);
        benchmark::DoNotOptimize(sum);
    }
}
BENCHMARK(BM_EventDispatchFourSubscribers);

// 4. SPSC Ring Buffer Push / Pop Single-Threaded Throughput
static void BM_SpscRingBufferPushPop(benchmark::State& state) {
    SpscRingBuffer<TestEvent, 1024> buffer;
    const auto event = make_event(TestEventPayload{.value_a = 1U, .value_b = 2U, .value_c = 3U});
    TestEvent popped{};

    for (auto state_iter : state) {
        benchmark::DoNotOptimize(state_iter);
        buffer.try_push(event);
        buffer.try_pop(popped);
        benchmark::DoNotOptimize(popped);
    }
}
BENCHMARK(BM_SpscRingBufferPushPop);

// 5. EventBus Synchronous Publish
static void BM_EventBusSyncPublish(benchmark::State& state) {
    EventBus<TestEvent, 1024> bus;
    uint64_t sink = 0;
    bus.dispatcher().subscribe<TestEventPayload>(
        [&sink](const TestEvent& ev) { sink += ev.payload.value_a; });

    const auto event = make_event(TestEventPayload{.value_a = 10U, .value_b = 20U, .value_c = 30U});

    for (auto state_iter : state) {
        benchmark::DoNotOptimize(state_iter);
        bus.publish_sync(event);
        benchmark::DoNotOptimize(sink);
    }
}
BENCHMARK(BM_EventBusSyncPublish);

}  // namespace rexi::events::benchmarks
