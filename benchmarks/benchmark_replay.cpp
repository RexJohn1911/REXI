#include "rexi/replay/replay_engine.hpp"
#include "rexi/replay/synthetic_generator.hpp"

#include <benchmark/benchmark.h>

using namespace rexi::market_data;
using namespace rexi::order_book;
using namespace rexi::replay;

// 1. Single Event Replay
static void BM_Replay_SingleEvent(benchmark::State& state) {
    auto hdr = make_md_header(MarketDataMessageType::OrderBookAdd, 100, 1, 1, 1, 1000, 1000);
    OrderBookAddMessage msg{.order_id = 1, .side = MarketSide::Buy, .price = 100, .quantity = 10};
    std::vector<ReplayEvent> events{make_replay_add(hdr, msg, 0)};
    InMemoryReplayReader reader(events);

    ReplayConfig config{
        .book_config = {.initial_order_capacity = 10, .allow_pool_growth = false},
    };
    ReplayEngine engine(100, config);

    for (auto _ : state) {
        state.PauseTiming();
        reader.reset();
        engine.reset();
        state.ResumeTiming();

        bool ok = engine.step(reader);
        benchmark::DoNotOptimize(ok);
    }
    state.SetItemsProcessed(state.iterations());
}
BENCHMARK(BM_Replay_SingleEvent);

// 2. 1,000 Event Replay
static void BM_Replay_1k_Events(benchmark::State& state) {
    constexpr int64_t Count = 1000;
    auto events = SyntheticReplayFixtureGenerator::create_large_deterministic_stream(
        static_cast<size_t>(Count), 0x1111222233334444ULL);
    InMemoryReplayReader reader(events);

    ReplayConfig config{
        .book_config = {.initial_order_capacity = 2000, .allow_pool_growth = false},
    };
    ReplayEngine engine(100, config);

    for (auto _ : state) {
        state.PauseTiming();
        reader.reset();
        engine.reset();
        state.ResumeTiming();

        auto res = engine.run(reader);
        benchmark::DoNotOptimize(res);
    }
    state.SetItemsProcessed(state.iterations() * Count);
}
BENCHMARK(BM_Replay_1k_Events);

// 3. 100,000 Event Replay
static void BM_Replay_100k_Events(benchmark::State& state) {
    constexpr int64_t Count = 100'000;
    auto events = SyntheticReplayFixtureGenerator::create_large_deterministic_stream(
        static_cast<size_t>(Count), 0xABCDEF1234567890ULL);
    InMemoryReplayReader reader(events);

    ReplayConfig config{
        .book_config = {.initial_order_capacity = 150'000,
                        .max_order_capacity = 150'000,
                        .allow_pool_growth = false},
    };
    ReplayEngine engine(100, config);

    for (auto _ : state) {
        state.PauseTiming();
        reader.reset();
        engine.reset();
        state.ResumeTiming();

        auto res = engine.run(reader);
        benchmark::DoNotOptimize(res);
    }
    state.SetItemsProcessed(state.iterations() * Count);
}
BENCHMARK(BM_Replay_100k_Events)->Iterations(5);

// 4. Synthetic Mixed Market Data Stream
static void BM_Replay_SyntheticMixedStream(benchmark::State& state) {
    auto events = SyntheticReplayFixtureGenerator::create_basic_l3_stream();
    const int64_t count = static_cast<int64_t>(events.size());
    InMemoryReplayReader reader(events);
    ReplayEngine engine(100);

    for (auto _ : state) {
        state.PauseTiming();
        reader.reset();
        engine.reset();
        state.ResumeTiming();

        auto res = engine.run(reader);
        benchmark::DoNotOptimize(res);
    }
    state.SetItemsProcessed(state.iterations() * count);
}
BENCHMARK(BM_Replay_SyntheticMixedStream);

// 5. Snapshot + Incremental Replay
static void BM_Replay_SnapshotAndIncremental(benchmark::State& state) {
    auto events = SyntheticReplayFixtureGenerator::create_snapshot_and_incremental_stream();
    const int64_t count = static_cast<int64_t>(events.size());
    InMemoryReplayReader reader(events);
    ReplayEngine engine(100);

    for (auto _ : state) {
        state.PauseTiming();
        reader.reset();
        engine.reset();
        state.ResumeTiming();

        auto res = engine.run(reader);
        benchmark::DoNotOptimize(res);
    }
    state.SetItemsProcessed(state.iterations() * count);
}
BENCHMARK(BM_Replay_SnapshotAndIncremental);

// 6. Step Mode vs Max Speed Mode
static void BM_Replay_StepMode(benchmark::State& state) {
    constexpr int64_t Count = 500;
    auto events = SyntheticReplayFixtureGenerator::create_large_deterministic_stream(
        static_cast<size_t>(Count), 0x5555666677778888ULL);
    InMemoryReplayReader reader(events);
    ReplayConfig config{
        .book_config = {.initial_order_capacity = 1000, .allow_pool_growth = false},
    };
    ReplayEngine engine(100, config);

    for (auto _ : state) {
        state.PauseTiming();
        reader.reset();
        engine.reset();
        state.ResumeTiming();

        while (engine.step(reader)) {
        }
        auto st = engine.statistics();
        benchmark::DoNotOptimize(st);
    }
    state.SetItemsProcessed(state.iterations() * Count);
}
BENCHMARK(BM_Replay_StepMode);

static void BM_Replay_MaxSpeedMode(benchmark::State& state) {
    constexpr int64_t Count = 500;
    auto events = SyntheticReplayFixtureGenerator::create_large_deterministic_stream(
        static_cast<size_t>(Count), 0x5555666677778888ULL);
    InMemoryReplayReader reader(events);
    ReplayConfig config{
        .book_config = {.initial_order_capacity = 1000, .allow_pool_growth = false},
    };
    ReplayEngine engine(100, config);

    for (auto _ : state) {
        state.PauseTiming();
        reader.reset();
        engine.reset();
        state.ResumeTiming();

        auto res = engine.run(reader);
        benchmark::DoNotOptimize(res);
    }
    state.SetItemsProcessed(state.iterations() * Count);
}
BENCHMARK(BM_Replay_MaxSpeedMode);

// 8. Validation Overhead: Strict vs Permissive
static void BM_Replay_ValidationOverhead_Strict(benchmark::State& state) {
    constexpr int64_t Count = 500;
    auto events = SyntheticReplayFixtureGenerator::create_large_deterministic_stream(
        static_cast<size_t>(Count), 0x9999AAAABBBBCCCCULL);
    InMemoryReplayReader reader(events);
    ReplayConfig config{
        .validation_policy = ValidationPolicy::Strict,
        .verify_sequence = true,
        .verify_checksum = false,
        .book_config = {.initial_order_capacity = 1000, .allow_pool_growth = false},
    };
    ReplayEngine engine(100, config);

    for (auto _ : state) {
        state.PauseTiming();
        reader.reset();
        engine.reset();
        state.ResumeTiming();

        auto res = engine.run(reader);
        benchmark::DoNotOptimize(res);
    }
    state.SetItemsProcessed(state.iterations() * Count);
}
BENCHMARK(BM_Replay_ValidationOverhead_Strict);

static void BM_Replay_ValidationOverhead_Permissive(benchmark::State& state) {
    constexpr int64_t Count = 500;
    auto events = SyntheticReplayFixtureGenerator::create_large_deterministic_stream(
        static_cast<size_t>(Count), 0x9999AAAABBBBCCCCULL);
    InMemoryReplayReader reader(events);
    ReplayConfig config{
        .validation_policy = ValidationPolicy::Permissive,
        .verify_sequence = true,
        .verify_checksum = false,
        .book_config = {.initial_order_capacity = 1000, .allow_pool_growth = false},
    };
    ReplayEngine engine(100, config);

    for (auto _ : state) {
        state.PauseTiming();
        reader.reset();
        engine.reset();
        state.ResumeTiming();

        auto res = engine.run(reader);
        benchmark::DoNotOptimize(res);
    }
    state.SetItemsProcessed(state.iterations() * Count);
}
BENCHMARK(BM_Replay_ValidationOverhead_Permissive);
