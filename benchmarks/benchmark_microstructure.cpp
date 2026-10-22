#include "rexi/microstructure/feature_engine.hpp"

#include <benchmark/benchmark.h>

using namespace rexi::microstructure;
using rexi::market_data::MarketSide;
using rexi::market_data::Price;
using rexi::market_data::Quantity;
using rexi::market_data::Timestamp;
using rexi::order_book::OrderBook;
using rexi::order_book::RestingOrder;
using rexi::order_book::Side;

static void BM_Microstructure_TopOfBookUpdate(benchmark::State& state) {
    MicrostructureFeatureEngine engine(100);
    Timestamp ts = 1000;
    Price bid = 1000;
    Price ask = 1005;
    Quantity qty = 50;

    for (auto _ : state) {
        ts += 100;
        bid += (ts % 2 == 0) ? 1 : -1;
        ask = bid + 5;
        bool ok = engine.on_top_of_book(ts, ts, 1, bid, qty, ask, qty);
        benchmark::DoNotOptimize(ok);
        const auto& feats = engine.features();
        benchmark::DoNotOptimize(feats.mid_price);
    }
}
BENCHMARK(BM_Microstructure_TopOfBookUpdate);

static void BM_Microstructure_TradeUpdate(benchmark::State& state) {
    MicrostructureFeatureEngine engine(100);
    Timestamp ts = 1000;
    Price price = 1002;
    Quantity qty = 100;

    for (auto _ : state) {
        ts += 100;
        price += (ts % 2 == 0) ? 1 : -1;
        MarketSide side = (ts % 2 == 0) ? MarketSide::Buy : MarketSide::Sell;
        bool ok = engine.on_trade(ts, ts, 1, price, qty, side);
        benchmark::DoNotOptimize(ok);
        const auto& feats = engine.features();
        benchmark::DoNotOptimize(feats.rolling_vwap);
    }
}
BENCHMARK(BM_Microstructure_TradeUpdate);

static void BM_Microstructure_OrderBookUpdate(benchmark::State& state) {
    MicrostructureFeatureEngine engine(100);
    OrderBook book(100);
    RestingOrder b1{.order_id = 1, .instrument_id = 100, .side = Side::Buy, .price = 1000, .initial_quantity = 50, .remaining_quantity = 50};
    RestingOrder a1{.order_id = 2, .instrument_id = 100, .side = Side::Sell, .price = 1005, .initial_quantity = 50, .remaining_quantity = 50};
    book.add_order(b1);
    book.add_order(a1);

    Timestamp ts = 1000;
    for (auto _ : state) {
        ts += 100;
        bool ok = engine.on_order_book_update(book, ts, ts, 1);
        benchmark::DoNotOptimize(ok);
        const auto& feats = engine.features();
        benchmark::DoNotOptimize(feats.depth_imbalance_k);
    }
}
BENCHMARK(BM_Microstructure_OrderBookUpdate);
