#include "rexi/simulator/exchange.hpp"
#include "rexi/simulator/matching_engine.hpp"

#include <benchmark/benchmark.h>

using namespace rexi::simulator;

static void BM_Simulator_OrderSubmission(benchmark::State& state) {
    Exchange exchange;
    Instrument inst{
        .id = 1,
        .tick_size = 1,
        .min_quantity = 1,
        .max_quantity = 1'000'000,
        .lot_size = 1,
    };
    exchange.register_instrument(inst);
    exchange.open_session();

    OrderId id = 1;
    for (auto _ : state) {
        // Non-crossing limit buys with incrementing IDs and decreasing prices
        exchange.submit_order(id, 1, 1, Side::Buy, OrderType::Limit,
                              1000 - (static_cast<Price>(id % 500)), 10);
        ++id;
    }
}
BENCHMARK(BM_Simulator_OrderSubmission);

static void BM_Simulator_OrderCancellation(benchmark::State& state) {
    Exchange exchange;
    Instrument inst{
        .id = 1,
        .tick_size = 1,
        .min_quantity = 1,
        .max_quantity = 1'000'000,
        .lot_size = 1,
    };
    exchange.register_instrument(inst);
    exchange.open_session();

    OrderId id = 1;
    for (auto _ : state) {
        state.PauseTiming();
        exchange.submit_order(id, 1, 1, Side::Buy, OrderType::Limit, 1000, 10);
        state.ResumeTiming();

        exchange.cancel_order(id);
        ++id;
    }
}
BENCHMARK(BM_Simulator_OrderCancellation);

static void BM_Simulator_SingleOrderMatch(benchmark::State& state) {
    Exchange exchange;
    Instrument inst{
        .id = 1,
        .tick_size = 1,
        .min_quantity = 1,
        .max_quantity = 1'000'000,
        .lot_size = 1,
    };
    exchange.register_instrument(inst);
    exchange.open_session();

    OrderId id = 1;
    for (auto _ : state) {
        state.PauseTiming();
        // Resting sell
        exchange.submit_order(id++, 1, 1, Side::Sell, OrderType::Limit, 1000, 100);
        state.ResumeTiming();

        // Crossing buy
        exchange.submit_order(id++, 2, 1, Side::Buy, OrderType::Limit, 1000, 100);
    }
}
BENCHMARK(BM_Simulator_SingleOrderMatch);

static void BM_Simulator_MultiLevelMatch(benchmark::State& state) {
    Exchange exchange;
    Instrument inst{
        .id = 1,
        .tick_size = 1,
        .min_quantity = 1,
        .max_quantity = 1'000'000,
        .lot_size = 1,
    };
    exchange.register_instrument(inst);
    exchange.open_session();

    OrderId id = 1;
    for (auto _ : state) {
        state.PauseTiming();
        // 5 resting sell levels of 20 units each
        for (int p = 1001; p <= 1005; ++p) {
            exchange.submit_order(id++, 1, 1, Side::Sell, OrderType::Limit, p, 20);
        }
        state.ResumeTiming();

        // Aggressive buy sweeping all 5 levels (100 units @ 1005)
        exchange.submit_order(id++, 2, 1, Side::Buy, OrderType::Limit, 1005, 100);
    }
}
BENCHMARK(BM_Simulator_MultiLevelMatch);
