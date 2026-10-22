#include "rexi/microstructure/feature_engine.hpp"
#include "rexi/microstructure/rolling_window.hpp"
#include "rexi/microstructure/types.hpp"
#include "rexi/order_book/order_book.hpp"

#include "allocation_guard.hpp"

#include <gtest/gtest.h>

#include <cmath>

using namespace rexi::microstructure;
using rexi::market_data::MarketSide;
using rexi::market_data::Price;
using rexi::market_data::Quantity;
using rexi::market_data::Timestamp;
using rexi::order_book::OrderBook;
using rexi::order_book::RestingOrder;
using rexi::order_book::Side;
using rexi::test::ScopedAllocationGuard;

class MicrostructureFeatureEngineTest : public ::testing::Test {
protected:
    void SetUp() override {
        FeatureEngineConfig cfg;
        cfg.return_lookback = 1;
        cfg.volatility_window = 5;
        cfg.ofi_window = 3;
        cfg.trade_window = 4;
        cfg.roll_window = 4;
        cfg.vpin_bucket_volume = 100;
        cfg.vpin_num_buckets = 3;
        cfg.depth_levels = 3;

        engine_ = std::make_unique<MicrostructureFeatureEngine>(101, cfg);
    }

    std::unique_ptr<MicrostructureFeatureEngine> engine_;
};

TEST_F(MicrostructureFeatureEngineTest, InitialStateIsEmptyAndUnwarmed) {
    const auto& f = engine_->features();
    EXPECT_EQ(f.instrument_id, 101);
    EXPECT_FALSE(f.has_bid);
    EXPECT_FALSE(f.has_ask);
    EXPECT_FALSE(f.has_spread);
    EXPECT_FALSE(f.has_mid);
    EXPECT_FALSE(f.has_weighted_mid);
    EXPECT_FALSE(f.has_book_imbalance);
    EXPECT_FALSE(f.has_instant_ofi);
    EXPECT_FALSE(f.has_rolling_ofi);
    EXPECT_FALSE(f.has_trade);
    EXPECT_FALSE(f.has_trade_flow);
    EXPECT_FALSE(f.has_vwap);
    EXPECT_FALSE(f.has_log_return);
    EXPECT_FALSE(f.has_realized_volatility);
    EXPECT_FALSE(f.has_roll_spread);
    EXPECT_FALSE(f.has_vpin);
    EXPECT_FALSE(f.is_crossed);
}

TEST_F(MicrostructureFeatureEngineTest, TopOfBookBasicAndGating) {
    // 1. One-sided bid only: spread and mid must NOT be marked valid
    EXPECT_TRUE(engine_->on_top_of_book(1000, 1005, 1, 10000, 50, 0, 0));
    {
        const auto& f = engine_->features();
        EXPECT_TRUE(f.has_bid);
        EXPECT_FALSE(f.has_ask);
        EXPECT_FALSE(f.has_spread);
        EXPECT_FALSE(f.has_mid);
        EXPECT_FALSE(f.has_book_imbalance);
        EXPECT_EQ(f.decision_timestamp_ns, 1005);
    }

    // 2. Both sides present and valid
    EXPECT_TRUE(engine_->on_top_of_book(2000, 2002, 2, 10000, 60, 10020, 40));
    {
        const auto& f = engine_->features();
        EXPECT_TRUE(f.has_bid);
        EXPECT_TRUE(f.has_ask);
        EXPECT_FALSE(f.is_crossed);
        EXPECT_TRUE(f.has_spread);
        EXPECT_EQ(f.spread, 20);
        EXPECT_TRUE(f.has_mid);
        EXPECT_DOUBLE_EQ(f.mid_price, 10010.0);
        EXPECT_DOUBLE_EQ(f.relative_spread, 20.0 / 10010.0);
        EXPECT_TRUE(f.has_weighted_mid);
        // Weighted mid: (10000 * 40 + 10020 * 60) / 100 = (400000 + 601200) / 100 = 10012.0
        EXPECT_DOUBLE_EQ(f.weighted_mid_price, 10012.0);
        // Imbalance: (60 - 40) / 100 = 0.20
        EXPECT_TRUE(f.has_book_imbalance);
        EXPECT_DOUBLE_EQ(f.book_imbalance_top, 0.20);
    }

    // 3. Crossed book (bid >= ask): must flag is_crossed and invalidate spread/mid
    EXPECT_TRUE(engine_->on_top_of_book(3000, 3000, 3, 10030, 50, 10020, 40));
    {
        const auto& f = engine_->features();
        EXPECT_TRUE(f.is_crossed);
        EXPECT_FALSE(f.has_spread);
        EXPECT_FALSE(f.has_mid);
        EXPECT_FALSE(f.has_weighted_mid);
        EXPECT_FALSE(f.has_book_imbalance);
    }
}

TEST_F(MicrostructureFeatureEngineTest, OrderFlowImbalanceFormulation) {
    // Reference: Cont, Kukanov & Stoikov (2014)
    // Event 1: Initial quote: Bid: 10000 @ 50, Ask: 10020 @ 40
    EXPECT_TRUE(engine_->on_top_of_book(1000, 1000, 1, 10000, 50, 10020, 40));
    EXPECT_FALSE(engine_->features().has_instant_ofi); // First quote has no prior baseline

    // Event 2: Bid price unchanged, bid qty increases by 20. Ask unchanged.
    // delta_B = 70 - 50 = +20, delta_A = 0 => instant_ofi = +20
    EXPECT_TRUE(engine_->on_top_of_book(2000, 2000, 2, 10000, 70, 10020, 40));
    EXPECT_TRUE(engine_->features().has_instant_ofi);
    EXPECT_EQ(engine_->features().instant_ofi, 20);

    // Event 3: Bid price increases to 10005 @ 30. Ask unchanged.
    // curr_b_p > prev_b_p => delta_B = +30, delta_A = 0 => instant_ofi = +30
    EXPECT_TRUE(engine_->on_top_of_book(3000, 3000, 3, 10005, 30, 10020, 40));
    EXPECT_EQ(engine_->features().instant_ofi, 30);

    // Event 4: Ask price increases (liquidity withdrawn/ask raised): 10025 @ 45
    // delta_B = 0 (unchanged), curr_a_p > prev_a_p => delta_A = prev_a_q = +40
    // instant_ofi = +40
    EXPECT_TRUE(engine_->on_top_of_book(4000, 4000, 4, 10005, 30, 10025, 45));
    EXPECT_EQ(engine_->features().instant_ofi, 40);

    // Rolling OFI window is 3: events 2 (+20), 3 (+30), 4 (+40) => rolling_ofi = +90
    EXPECT_TRUE(engine_->features().has_rolling_ofi);
    EXPECT_EQ(engine_->features().rolling_ofi, 90);

    // Event 5: Bid price drops: 10000 @ 60
    // curr_b_p < prev_b_p => delta_B = -prev_b_q = -30
    // Ask unchanged => delta_A = 0 => instant_ofi = -30
    EXPECT_TRUE(engine_->on_top_of_book(5000, 5000, 5, 10000, 60, 10025, 45));
    EXPECT_EQ(engine_->features().instant_ofi, -30);
    // Rolling OFI over last 3: (+30) + (+40) + (-30) = +40
    EXPECT_EQ(engine_->features().rolling_ofi, 40);
}

TEST_F(MicrostructureFeatureEngineTest, TradeFlowAndRollingVWAP) {
    // Window capacity set to 4 in SetUp
    // Trade 1: Buy 100 @ 10000
    EXPECT_TRUE(engine_->on_trade(1000, 1000, 1, 10000, 100, MarketSide::Buy));
    {
        const auto& f = engine_->features();
        EXPECT_TRUE(f.has_trade);
        EXPECT_EQ(f.last_signed_volume, 100);
        EXPECT_EQ(f.rolling_trade_volume, 100);
        EXPECT_EQ(f.rolling_buy_volume, 100);
        EXPECT_EQ(f.rolling_sell_volume, 0);
        EXPECT_DOUBLE_EQ(f.trade_flow_imbalance, 1.0);
        EXPECT_TRUE(f.has_vwap);
        EXPECT_DOUBLE_EQ(f.rolling_vwap, 10000.0);
        EXPECT_FALSE(f.has_trade_flow); // Requires full window of 4 trades to be considered warmed
    }

    // Trade 2: Sell 50 @ 9995
    EXPECT_TRUE(engine_->on_trade(2000, 2000, 2, 9995, 50, MarketSide::Sell));
    {
        const auto& f = engine_->features();
        EXPECT_EQ(f.last_signed_volume, -50);
        EXPECT_EQ(f.rolling_trade_volume, 150);
        EXPECT_EQ(f.rolling_buy_volume, 100);
        EXPECT_EQ(f.rolling_sell_volume, 50);
        // Imbalance: (100 - 50) / 150 = 50 / 150 = 0.3333333333333333
        EXPECT_NEAR(f.trade_flow_imbalance, 1.0 / 3.0, 1e-9);
        // VWAP: (10000 * 100 + 9995 * 50) / 150 = (1000000 + 499750) / 150 = 9998.33333333
        EXPECT_NEAR(f.rolling_vwap, 1499750.0 / 150.0, 1e-9);
    }

    // Trade 3: Sell 50 @ 9990
    EXPECT_TRUE(engine_->on_trade(3000, 3000, 3, 9990, 50, MarketSide::Sell));
    // Trade 4: Buy 200 @ 10010 (completes 4-trade window)
    EXPECT_TRUE(engine_->on_trade(4000, 4000, 4, 10010, 200, MarketSide::Buy));
    {
        const auto& f = engine_->features();
        EXPECT_TRUE(f.has_trade_flow);
        EXPECT_EQ(f.rolling_trade_volume, 400); // 100 + 50 + 50 + 200
        EXPECT_EQ(f.rolling_buy_volume, 300);
        EXPECT_EQ(f.rolling_sell_volume, 100);
        EXPECT_DOUBLE_EQ(f.trade_flow_imbalance, 200.0 / 400.0);
    }
}

TEST_F(MicrostructureFeatureEngineTest, ShortHorizonReturnsAndVolatility) {
    // Config: return_lookback = 1, volatility_window = 5
    // Feed 6 consecutive quotes to generate 5 returns
    const double mids[] = {100.0, 102.0, 101.0, 103.0, 104.0, 106.0};
    for (size_t i = 0; i < 6; ++i) {
        Price p = static_cast<Price>(mids[i]);
        Timestamp ts = static_cast<Timestamp>(1000 * (i + 1));
        EXPECT_TRUE(engine_->on_top_of_book(ts, ts, i + 1, p - 1, 10, p + 1, 10));
    }

    const auto& f = engine_->features();
    EXPECT_TRUE(f.has_log_return);
    // Last return is ln(106 / 104)
    EXPECT_NEAR(f.log_return, std::log(106.0 / 104.0), 1e-9);
    EXPECT_TRUE(f.has_realized_volatility);
    EXPECT_GT(f.realized_volatility, 0.0);
}

TEST_F(MicrostructureFeatureEngineTest, RollEffectiveSpread) {
    // Roll (1984) model: S = 2 * sqrt(-Cov(Delta P_t, Delta P_{t-1}))
    // Alternate price bouncing: 100, 102, 100, 102, 100, 102
    // Price diffs: +2, -2, +2, -2, +2
    const Price prices[] = {100, 102, 100, 102, 100, 102};
    for (size_t i = 0; i < 6; ++i) {
        Timestamp ts = static_cast<Timestamp>(1000 * (i + 1));
        EXPECT_TRUE(engine_->on_trade(ts, ts, i + 1, prices[i], 10, MarketSide::Buy));
    }

    const auto& f = engine_->features();
    EXPECT_TRUE(f.has_roll_spread);
    EXPECT_GT(f.roll_spread, 0.0);
}

TEST_F(MicrostructureFeatureEngineTest, VPINCalculation) {
    // Config: vpin_bucket_volume = 100, vpin_num_buckets = 3
    // Bucket 1: 100 Buy => |100 - 0| = 100
    EXPECT_TRUE(engine_->on_trade(1000, 1000, 1, 100, 100, MarketSide::Buy));
    EXPECT_FALSE(engine_->features().has_vpin); // 1 bucket < 3

    // Bucket 2: 60 Buy + 40 Sell = 100 => |60 - 40| = 20
    EXPECT_TRUE(engine_->on_trade(2000, 2000, 2, 100, 60, MarketSide::Buy));
    EXPECT_TRUE(engine_->on_trade(3000, 3000, 3, 100, 40, MarketSide::Sell));
    EXPECT_FALSE(engine_->features().has_vpin); // 2 buckets < 3

    // Bucket 3: 50 Buy + 50 Sell = 100 => |50 - 50| = 0
    EXPECT_TRUE(engine_->on_trade(4000, 4000, 4, 100, 50, MarketSide::Buy));
    EXPECT_TRUE(engine_->on_trade(5000, 5000, 5, 100, 50, MarketSide::Sell));

    // Now 3 buckets completed: imbalances = 100, 20, 0
    // Total imbalance = 120
    // Denominator = 3 * 100 = 300
    // VPIN = 120 / 300 = 0.40
    {
        const auto& f = engine_->features();
        EXPECT_TRUE(f.has_vpin);
        EXPECT_NEAR(f.vpin, 0.40, 1e-9);
    }
}

TEST_F(MicrostructureFeatureEngineTest, MultiLevelDepthFromOrderBook) {
    OrderBook book(101);

    // Add 3 bid levels
    RestingOrder b1{.order_id = 1, .instrument_id = 101, .side = Side::Buy, .price = 100, .initial_quantity = 50, .remaining_quantity = 50};
    RestingOrder b2{.order_id = 2, .instrument_id = 101, .side = Side::Buy, .price = 99,  .initial_quantity = 30, .remaining_quantity = 30};
    RestingOrder b3{.order_id = 3, .instrument_id = 101, .side = Side::Buy, .price = 98,  .initial_quantity = 20, .remaining_quantity = 20};
    book.add_order(b1);
    book.add_order(b2);
    book.add_order(b3);

    // Add 3 ask levels
    RestingOrder a1{.order_id = 4, .instrument_id = 101, .side = Side::Sell, .price = 102, .initial_quantity = 40, .remaining_quantity = 40};
    RestingOrder a2{.order_id = 5, .instrument_id = 101, .side = Side::Sell, .price = 103, .initial_quantity = 30, .remaining_quantity = 30};
    RestingOrder a3{.order_id = 6, .instrument_id = 101, .side = Side::Sell, .price = 104, .initial_quantity = 30, .remaining_quantity = 30};
    book.add_order(a1);
    book.add_order(a2);
    book.add_order(a3);

    EXPECT_TRUE(engine_->on_order_book_update(book, 1000, 1000, 1));
    {
        const auto& f = engine_->features();
        EXPECT_TRUE(f.has_bid);
        EXPECT_TRUE(f.has_ask);
        EXPECT_EQ(f.best_bid_price, 100);
        EXPECT_EQ(f.best_ask_price, 102);
        EXPECT_EQ(f.spread, 2);
        // Bid depth top 3: 50 + 30 + 20 = 100
        EXPECT_EQ(f.bid_depth_k, 100);
        // Ask depth top 3: 40 + 30 + 30 = 100
        EXPECT_EQ(f.ask_depth_k, 100);
        EXPECT_TRUE(f.has_depth_imbalance);
        EXPECT_DOUBLE_EQ(f.depth_imbalance_k, 0.0);
    }
}

TEST_F(MicrostructureFeatureEngineTest, TemporalCausalityAndOutOfOrderDrops) {
    EXPECT_TRUE(engine_->on_top_of_book(1000, 1010, 1, 100, 10, 102, 10));
    EXPECT_EQ(engine_->features().decision_timestamp_ns, 1010);
    EXPECT_EQ(engine_->out_of_order_drops(), 0);

    // Event with earlier timestamp than current last_event_time_ (999 < 1000)
    EXPECT_FALSE(engine_->on_top_of_book(999, 1000, 2, 100, 10, 102, 10));
    EXPECT_EQ(engine_->out_of_order_drops(), 1);

    // Duplicate timestamp (1000 == 1000): accepted in same burst/tick
    EXPECT_TRUE(engine_->on_top_of_book(1001, 1005, 3, 100, 10, 102, 10));
    EXPECT_TRUE(engine_->on_top_of_book(1001, 1006, 4, 100, 15, 102, 10));
    EXPECT_EQ(engine_->out_of_order_drops(), 1);
}

TEST_F(MicrostructureFeatureEngineTest, AskOnlyOneSidedBook) {
    // Only ask present (bid = 0, ask = 10020 @ 40)
    EXPECT_TRUE(engine_->on_top_of_book(1000, 1000, 1, 0, 0, 10020, 40));
    const auto& f = engine_->features();
    EXPECT_FALSE(f.has_bid);
    EXPECT_TRUE(f.has_ask);
    EXPECT_FALSE(f.has_spread);
    EXPECT_FALSE(f.has_mid);
    EXPECT_FALSE(f.has_weighted_mid);
    EXPECT_FALSE(f.has_book_imbalance);
    EXPECT_EQ(f.best_ask_price, 10020);
    EXPECT_EQ(f.best_ask_quantity, 40);
    EXPECT_EQ(f.best_bid_price, 0);
}

TEST_F(MicrostructureFeatureEngineTest, LockedBookHandling) {
    // Locked book: bid_price == ask_price (10000 == 10000)
    EXPECT_TRUE(engine_->on_top_of_book(1000, 1000, 1, 10000, 50, 10000, 50));
    const auto& f = engine_->features();
    EXPECT_TRUE(f.is_crossed);
    EXPECT_FALSE(f.has_spread);
    EXPECT_FALSE(f.has_mid);
    EXPECT_FALSE(f.has_weighted_mid);
    EXPECT_FALSE(f.has_book_imbalance);
    EXPECT_EQ(f.spread, 0);
}

TEST_F(MicrostructureFeatureEngineTest, InvalidTradeInputsRejected) {
    // Trade with price <= 0 or quantity == 0 must be rejected
    EXPECT_FALSE(engine_->on_trade(1000, 1000, 1, 0, 100, MarketSide::Buy));
    EXPECT_FALSE(engine_->on_trade(2000, 2000, 2, -100, 100, MarketSide::Buy));
    EXPECT_FALSE(engine_->on_trade(3000, 3000, 3, 10000, 0, MarketSide::Buy));
    EXPECT_FALSE(engine_->features().has_trade);
}

TEST_F(MicrostructureFeatureEngineTest, InsufficientHistoryTransitions) {
    // Volatility requires volatility_window = 5 returns
    // Feed only 3 quotes (2 returns)
    engine_->on_top_of_book(1000, 1000, 1, 100, 10, 102, 10);
    engine_->on_top_of_book(2000, 2000, 2, 102, 10, 104, 10);
    engine_->on_top_of_book(3000, 3000, 3, 101, 10, 103, 10);

    const auto& f = engine_->features();
    EXPECT_TRUE(f.has_log_return);
    EXPECT_FALSE(f.has_realized_volatility);
    EXPECT_DOUBLE_EQ(f.realized_volatility, 0.0);
}

TEST_F(MicrostructureFeatureEngineTest, SteadyStateZeroHeapAllocations) {
    OrderBook book(101);
    RestingOrder b1{.order_id = 1, .instrument_id = 101, .side = Side::Buy, .price = 100, .initial_quantity = 50, .remaining_quantity = 50};
    RestingOrder a1{.order_id = 2, .instrument_id = 101, .side = Side::Sell, .price = 102, .initial_quantity = 40, .remaining_quantity = 40};
    book.add_order(b1);
    book.add_order(a1);

    // Warm up engine state across all 3 handlers
    engine_->on_top_of_book(1000, 1000, 1, 100, 10, 102, 10);
    engine_->on_trade(1000, 1000, 1, 101, 50, MarketSide::Buy);
    engine_->on_order_book_update(book, 1000, 1000, 1);

    ScopedAllocationGuard guard;

    for (size_t i = 2; i <= 50; ++i) {
        Timestamp ts = static_cast<Timestamp>(1000 * i);
        Price p = static_cast<Price>(100 + (i % 5));
        engine_->on_top_of_book(ts, ts, i, p, 20, p + 2, 20);
        engine_->on_trade(ts, ts, i, p + 1, 10, (i % 2 == 0) ? MarketSide::Buy : MarketSide::Sell);
        engine_->on_order_book_update(book, ts, ts, i);
    }

    EXPECT_EQ(guard.allocations(), 0) << "Expected zero heap allocations during steady-state processing!";
}
