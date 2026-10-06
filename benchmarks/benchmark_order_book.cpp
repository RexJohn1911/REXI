#include "rexi/order_book/order_book.hpp"

#include <benchmark/benchmark.h>

using namespace rexi::order_book;

static void BM_OrderBook_AddRestingOrder(benchmark::State& state) {
    OrderBook book(100);
    uint64_t seq = 1;
    for (auto _ : state) {
        state.PauseTiming();
        book.clear();
        state.ResumeTiming();

        for (int i = 0; i < 100; ++i) {
            RestingOrder ord{
                .order_id = static_cast<OrderId>(i + 1),
                .instrument_id = 100,
                .side = (i % 2 == 0) ? Side::Buy : Side::Sell,
                .price = static_cast<Price>((i % 2 == 0) ? (1000 - i) : (2000 + i)),
                .initial_quantity = 50,
                .remaining_quantity = 50,
                .priority_seq = seq++,
                .timestamp_ns = 1000,
            };
            benchmark::DoNotOptimize(book.add_order(ord));
        }
    }
}
BENCHMARK(BM_OrderBook_AddRestingOrder);

static void BM_OrderBook_CancelByOrderId(benchmark::State& state) {
    OrderBook book(100);
    for (int i = 1; i <= 1000; ++i) {
        book.add_order(RestingOrder{
            .order_id = static_cast<OrderId>(i),
            .instrument_id = 100,
            .side = (i % 2 == 0) ? Side::Buy : Side::Sell,
            .price = static_cast<Price>((i % 2 == 0) ? (1000 - (i % 50)) : (2000 + (i % 50))),
            .initial_quantity = 50,
            .remaining_quantity = 50,
        });
    }

    OrderId target_id = 500;
    for (auto _ : state) {
        state.PauseTiming();
        // Re-insert order 500 if cancelled
        if (!book.has_order(target_id)) {
            book.add_order(RestingOrder{
                .order_id = target_id,
                .instrument_id = 100,
                .side = Side::Buy,
                .price = 990,
                .initial_quantity = 50,
                .remaining_quantity = 50,
            });
        }
        state.ResumeTiming();

        benchmark::DoNotOptimize(book.cancel_order(target_id));
    }
}
BENCHMARK(BM_OrderBook_CancelByOrderId);

static void BM_OrderBook_ReduceQuantity(benchmark::State& state) {
    OrderBook book(100);
    book.add_order(RestingOrder{
        .order_id = 1,
        .instrument_id = 100,
        .side = Side::Buy,
        .price = 1000,
        .initial_quantity = 100000000,
        .remaining_quantity = 100000000,
    });

    for (auto _ : state) {
        benchmark::DoNotOptimize(book.reduce_order(1, 1));
    }
}
BENCHMARK(BM_OrderBook_ReduceQuantity);

static void BM_OrderBook_BestBidLookup(benchmark::State& state) {
    OrderBook book(100);
    for (int i = 1; i <= 50; ++i) {
        book.add_order(RestingOrder{
            .order_id = static_cast<OrderId>(i),
            .instrument_id = 100,
            .side = Side::Buy,
            .price = static_cast<Price>(1000 - i),
            .initial_quantity = 10,
            .remaining_quantity = 10,
        });
    }

    for (auto _ : state) {
        auto best = book.best_bid();
        benchmark::DoNotOptimize(best.has_value());
    }
}
BENCHMARK(BM_OrderBook_BestBidLookup);

static void BM_OrderBook_BestAskLookup(benchmark::State& state) {
    OrderBook book(100);
    for (int i = 1; i <= 50; ++i) {
        book.add_order(RestingOrder{
            .order_id = static_cast<OrderId>(i),
            .instrument_id = 100,
            .side = Side::Sell,
            .price = static_cast<Price>(2000 + i),
            .initial_quantity = 10,
            .remaining_quantity = 10,
        });
    }

    for (auto _ : state) {
        auto best = book.best_ask();
        benchmark::DoNotOptimize(best.has_value());
    }
}
BENCHMARK(BM_OrderBook_BestAskLookup);

static void BM_OrderBook_L2DepthExtraction(benchmark::State& state) {
    OrderBook book(100);
    for (int i = 1; i <= 20; ++i) {
        book.add_order(RestingOrder{
            .order_id = static_cast<OrderId>(i),
            .instrument_id = 100,
            .side = Side::Buy,
            .price = static_cast<Price>(1000 - i),
            .initial_quantity = 10,
            .remaining_quantity = 10,
        });
    }

    for (auto _ : state) {
        auto depth = book.bids_depth(10);
        benchmark::DoNotOptimize(depth.size());
    }
}
BENCHMARK(BM_OrderBook_L2DepthExtraction);

static void BM_OrderBook_L3OrderLookup(benchmark::State& state) {
    OrderBook book(100);
    for (int i = 1; i <= 100; ++i) {
        book.add_order(RestingOrder{
            .order_id = static_cast<OrderId>(i),
            .instrument_id = 100,
            .side = Side::Buy,
            .price = static_cast<Price>(1000 - (i % 20)),
            .initial_quantity = 10,
            .remaining_quantity = 10,
        });
    }

    OrderId target_id = 42;
    for (auto _ : state) {
        const RestingOrder* ord = book.find_order(target_id);
        benchmark::DoNotOptimize(ord);
    }
}
BENCHMARK(BM_OrderBook_L3OrderLookup);

static void BM_OrderBook_SnapshotApplication(benchmark::State& state) {
    OrderBook book(100);
    rexi::market_data::OrderBookSnapshotMessage snap{};
    snap.bid_levels_count = 10;
    snap.ask_levels_count = 10;
    for (uint32_t i = 0; i < 10; ++i) {
        snap.bids[i] = rexi::market_data::OrderBookSnapshotLevel{
            .price = static_cast<Price>(1000 - i),
            .quantity = 100,
            .order_count = 5,
        };
        snap.asks[i] = rexi::market_data::OrderBookSnapshotLevel{
            .price = static_cast<Price>(1100 + i),
            .quantity = 100,
            .order_count = 5,
        };
    }

    for (auto _ : state) {
        benchmark::DoNotOptimize(book.apply_snapshot(snap));
    }
}
BENCHMARK(BM_OrderBook_SnapshotApplication);

static void BM_OrderBook_DeterministicValidation(benchmark::State& state) {
    OrderBook book(100);
    for (int i = 1; i <= 50; ++i) {
        book.add_order(RestingOrder{
            .order_id = static_cast<OrderId>(i),
            .instrument_id = 100,
            .side = Side::Buy,
            .price = static_cast<Price>(1000 - (i % 10)),
            .initial_quantity = 10,
            .remaining_quantity = 10,
        });
        book.add_order(RestingOrder{
            .order_id = static_cast<OrderId>(100 + i),
            .instrument_id = 100,
            .side = Side::Sell,
            .price = static_cast<Price>(2000 + (i % 10)),
            .initial_quantity = 10,
            .remaining_quantity = 10,
        });
    }

    for (auto _ : state) {
        auto val = book.validate();
        benchmark::DoNotOptimize(val.is_valid);
    }
}
BENCHMARK(BM_OrderBook_DeterministicValidation);
