#include "rexi/events/event_dispatcher.hpp"
#include "rexi/market_data/checksum.hpp"
#include "rexi/market_data/events.hpp"
#include "rexi/market_data/message_header.hpp"
#include "rexi/market_data/messages.hpp"
#include "rexi/market_data/normalizer.hpp"
#include "rexi/market_data/sequence_manager.hpp"
#include "rexi/market_data/validator.hpp"

#include <benchmark/benchmark.h>

using namespace rexi::market_data;
using namespace rexi::events;

static void BM_MarketData_HeaderConstruction(benchmark::State& state) {
    SequenceNumber seq = 1;
    for (auto _ : state) {
        MarketDataHeader header =
            make_md_header(MarketDataMessageType::TopOfBook, 1001, 1, 1, seq++, 1000, 1000);
        benchmark::DoNotOptimize(header);
    }
}
BENCHMARK(BM_MarketData_HeaderConstruction);

static void BM_MarketData_ChecksumCalculation(benchmark::State& state) {
    TradeMessage trade{
        .trade_id = 12345,
        .price = 15025,
        .quantity = 100,
        .aggressor_side = MarketSide::Buy,
        .maker_order_id = 1,
        .taker_order_id = 2,
    };
    for (auto _ : state) {
        std::uint32_t chk = IntegrityChecksum::calculate_for_payload(trade);
        benchmark::DoNotOptimize(chk);
    }
}
BENCHMARK(BM_MarketData_ChecksumCalculation);

static void BM_MarketData_ChecksumVerification(benchmark::State& state) {
    TradeMessage trade{
        .trade_id = 12345,
        .price = 15025,
        .quantity = 100,
        .aggressor_side = MarketSide::Buy,
        .maker_order_id = 1,
        .taker_order_id = 2,
    };
    std::uint32_t chk = IntegrityChecksum::calculate_for_payload(trade);
    MarketDataHeader header =
        make_md_header(MarketDataMessageType::Trade, 1001, 1, 1, 1, 1000, 1000, 0, chk);

    for (auto _ : state) {
        ChecksumStatus status = IntegrityChecksum::verify(header, trade);
        benchmark::DoNotOptimize(status);
    }
}
BENCHMARK(BM_MarketData_ChecksumVerification);

static void BM_MarketData_MessageValidation(benchmark::State& state) {
    MarketDataHeader header =
        make_md_header(MarketDataMessageType::TopOfBook, 1001, 1, 1, 1, 1000, 1000);
    TopOfBookMessage tob{
        .best_bid_price = 1000,
        .best_bid_quantity = 50,
        .best_ask_price = 1005,
        .best_ask_quantity = 50,
    };

    for (auto _ : state) {
        ValidationStatus status = MessageValidator::validate(header, tob);
        benchmark::DoNotOptimize(status);
    }
}
BENCHMARK(BM_MarketData_MessageValidation);

static void BM_MarketData_SequenceValidation(benchmark::State& state) {
    SequenceManager seq_mgr(1);
    SequenceNumber seq = 1;

    for (auto _ : state) {
        SequenceStatus status = seq_mgr.validate_and_advance(seq++);
        benchmark::DoNotOptimize(status);
    }
}
BENCHMARK(BM_MarketData_SequenceValidation);

static void BM_MarketData_EventDispatch(benchmark::State& state) {
    EventDispatcher dispatcher;
    uint64_t received_count = 0;
    dispatcher.subscribe<TopOfBookMessage>(
        [&received_count](const Event<TopOfBookMessage>&) { ++received_count; });

    TopOfBookMessage tob{
        .best_bid_price = 1000,
        .best_bid_quantity = 50,
        .best_ask_price = 1005,
        .best_ask_quantity = 50,
    };
    auto evt = make_event(tob, SourceId::Simulator, 1, 0, 1000);

    for (auto _ : state) {
        size_t count = dispatcher.dispatch(evt);
        benchmark::DoNotOptimize(count);
    }
    benchmark::DoNotOptimize(received_count);
}
BENCHMARK(BM_MarketData_EventDispatch);
