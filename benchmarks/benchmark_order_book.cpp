#include "rexi/order_book/order_book.hpp"

#include <benchmark/benchmark.h>

using namespace rexi::order_book;

// 1. Add resting order
static void BM_OrderBook_AddRestingOrder(benchmark::State& state) {
    OrderBook book(100, CrossedBookPolicy::Reject,
                   OrderBookConfig{.initial_order_capacity = 200, .allow_pool_growth = false});
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

// 2. Cancel by OrderId
static void BM_OrderBook_CancelByOrderId(benchmark::State& state) {
    OrderBook book(100, CrossedBookPolicy::Reject,
                   OrderBookConfig{.initial_order_capacity = 2000, .allow_pool_growth = false});
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

// 3. Reduce quantity
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

// 4. Modify quantity (preserves priority on reduce, loses on increase)
static void BM_OrderBook_ModifyQuantity(benchmark::State& state) {
    OrderBook book(100);
    book.add_order(RestingOrder{
        .order_id = 1,
        .instrument_id = 100,
        .side = Side::Buy,
        .price = 1000,
        .initial_quantity = 100,
        .remaining_quantity = 100,
    });

    Quantity q = 90;
    for (auto _ : state) {
        q = (q == 90) ? 95 : 90;
        benchmark::DoNotOptimize(book.modify_order(1, q));
    }
}
BENCHMARK(BM_OrderBook_ModifyQuantity);

// 5. Price change (replace_order)
static void BM_OrderBook_PriceChange(benchmark::State& state) {
    OrderBook book(100);
    book.add_order(RestingOrder{
        .order_id = 1,
        .instrument_id = 100,
        .side = Side::Buy,
        .price = 990,
        .initial_quantity = 50,
        .remaining_quantity = 50,
    });

    Price p = 990;
    for (auto _ : state) {
        p = (p == 990) ? 985 : 990;
        benchmark::DoNotOptimize(book.replace_order(1, p, 50));
    }
}
BENCHMARK(BM_OrderBook_PriceChange);

// 6. Best bid lookup
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

// 7. Best ask lookup
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

// 8. L2 depth extraction
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

// 9. L3 order lookup
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

// 10. FIFO queue position traversal
static void BM_OrderBook_FifoTraversal(benchmark::State& state) {
    OrderBook book(100);
    for (int i = 1; i <= 50; ++i) {
        book.add_order(RestingOrder{
            .order_id = static_cast<OrderId>(i),
            .instrument_id = 100,
            .side = Side::Buy,
            .price = 1000,
            .initial_quantity = 10,
            .remaining_quantity = 10,
            .priority_seq = static_cast<SequenceNumber>(i),
        });
    }

    OrderId target_id = 45;
    for (auto _ : state) {
        auto pos = book.get_queue_position(target_id);
        benchmark::DoNotOptimize(pos.has_value());
    }
}
BENCHMARK(BM_OrderBook_FifoTraversal);

// 11. Mixed HFT workload (Adds, Cancels, Reduces, Lookups)
static void BM_OrderBook_MixedWorkload(benchmark::State& state) {
    OrderBook book(100, CrossedBookPolicy::Reject,
                   OrderBookConfig{.initial_order_capacity = 5000, .allow_pool_growth = false});
    // Seed book with 200 orders across 20 levels
    for (int i = 1; i <= 200; ++i) {
        book.add_order(RestingOrder{
            .order_id = static_cast<OrderId>(i),
            .instrument_id = 100,
            .side = (i % 2 == 0) ? Side::Buy : Side::Sell,
            .price = static_cast<Price>((i % 2 == 0) ? (1000 - (i % 10)) : (1010 + (i % 10))),
            .initial_quantity = 100,
            .remaining_quantity = 100,
        });
    }

    uint64_t next_id = 300;
    for (auto _ : state) {
        // 1. Add
        book.add_order(RestingOrder{
            .order_id = next_id,
            .instrument_id = 100,
            .side = Side::Buy,
            .price = 995,
            .initial_quantity = 50,
            .remaining_quantity = 50,
        });
        // 2. Reduce
        book.reduce_order(next_id, 10);
        // 3. Lookup
        const RestingOrder* ord = book.find_order(next_id);
        benchmark::DoNotOptimize(ord);
        // 4. Cancel
        book.cancel_order(next_id);
        ++next_id;
        if (next_id > 4500) {
            next_id = 300;
        }
    }
}
BENCHMARK(BM_OrderBook_MixedWorkload);

// 12. Snapshot Application
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

// 13. Deterministic Validation
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
