"""Unit tests for Python Microstructure Feature Engine."""

import math

import pyarrow as pa
import pytest

from research.features import (
    MICROSTRUCTURE_FEATURES_SCHEMA_V1,
    AggressorSide,
    FeatureEngineConfig,
    InvalidEventDataError,
    MicrostructureFeatureEngine,
)


class TestMicrostructureFeatureEngine:
    """Test suite for MicrostructureFeatureEngine formulas and causality."""

    def test_invalid_config_raises(self) -> None:
        with pytest.raises(ValueError, match="return_lookback"):
            FeatureEngineConfig(return_lookback=0)
        with pytest.raises(ValueError, match="volatility_window"):
            FeatureEngineConfig(volatility_window=1)
        with pytest.raises(ValueError, match="vpin_bucket_volume"):
            FeatureEngineConfig(vpin_bucket_volume=0)

    def test_initial_state(self) -> None:
        engine = MicrostructureFeatureEngine(instrument_id=101)
        assert engine.current_features is None
        assert engine.out_of_order_count == 0

    def test_top_of_book_basic_and_gating(self) -> None:
        engine = MicrostructureFeatureEngine(instrument_id=101)

        # 1. Bid only: mid and spread must be gated False
        r1 = engine.on_top_of_book(
            event_time_ns=1000,
            source_time_ns=1005,
            seq=1,
            bid_price=10000,
            bid_qty=50,
            ask_price=0,
            ask_qty=0,
        )
        assert r1 is not None
        assert r1.has_bid is True
        assert r1.has_ask is False
        assert r1.has_spread is False
        assert r1.has_mid is False
        assert r1.decision_timestamp_ns == 1005

        # 2. Both sides present and valid
        r2 = engine.on_top_of_book(
            event_time_ns=2000,
            source_time_ns=2000,
            seq=2,
            bid_price=10000,
            bid_qty=60,
            ask_price=10020,
            ask_qty=40,
        )
        assert r2 is not None
        assert r2.has_bid is True
        assert r2.has_ask is True
        assert r2.is_crossed is False
        assert r2.has_spread is True
        assert r2.spread == 20
        assert r2.mid_price == 10010.0
        assert r2.relative_spread == 20.0 / 10010.0
        assert r2.has_weighted_mid is True
        # (10000 * 40 + 10020 * 60) / 100 = 10012.0
        assert r2.weighted_mid_price == 10012.0
        assert r2.has_book_imbalance is True
        # (60 - 40) / 100 = 0.20
        assert pytest.approx(r2.book_imbalance_top) == 0.20

        # 3. Crossed book
        r3 = engine.on_top_of_book(
            event_time_ns=3000,
            source_time_ns=3000,
            seq=3,
            bid_price=10030,
            bid_qty=50,
            ask_price=10020,
            ask_qty=40,
        )
        assert r3 is not None
        assert r3.is_crossed is True
        assert r3.has_spread is False
        assert r3.has_mid is False
        assert r3.has_weighted_mid is False
        assert r3.has_book_imbalance is False

    def test_ofi_cont_kukanov_stoikov_formulation(self) -> None:
        cfg = FeatureEngineConfig(ofi_window=3)
        engine = MicrostructureFeatureEngine(instrument_id=101, config=cfg)

        # Quote 1: baseline
        engine.on_top_of_book(1000, 1000, 1, 10000, 50, 10020, 40)
        assert engine.current_features is not None
        assert engine.current_features.has_instant_ofi is False

        # Quote 2: Bid qty increases by 20 at same price
        r2 = engine.on_top_of_book(2000, 2000, 2, 10000, 70, 10020, 40)
        assert r2 is not None
        assert r2.has_instant_ofi is True
        assert r2.instant_ofi == 20

        # Quote 3: Bid price increases to 10005 @ 30
        r3 = engine.on_top_of_book(3000, 3000, 3, 10005, 30, 10020, 40)
        assert r3 is not None
        assert r3.instant_ofi == 30

        # Quote 4: Ask price increases to 10025 @ 45
        r4 = engine.on_top_of_book(4000, 4000, 4, 10005, 30, 10025, 45)
        assert r4 is not None
        assert r4.instant_ofi == 40
        # Rolling OFI over last 3: 20 + 30 + 40 = 90
        assert r4.has_rolling_ofi is True
        assert r4.rolling_ofi == 90

    def test_trade_flow_and_rolling_vwap(self) -> None:
        cfg = FeatureEngineConfig(trade_window=3)
        engine = MicrostructureFeatureEngine(instrument_id=101, config=cfg)

        # Trade 1: Buy 100 @ 10000
        r1 = engine.on_trade(1000, 1000, 1, 10000, 100, AggressorSide.BUY)
        assert r1 is not None
        assert r1.last_signed_volume == 100
        assert r1.rolling_trade_volume == 100
        assert r1.rolling_buy_volume == 100
        assert r1.rolling_sell_volume == 0
        assert r1.rolling_vwap == 10000.0
        assert r1.has_trade_flow is False  # 1 < 3

        # Trade 2: Sell 50 @ 9990
        r2 = engine.on_trade(2000, 2000, 2, 9990, 50, AggressorSide.SELL)
        assert r2 is not None
        assert r2.last_signed_volume == -50
        assert r2.rolling_trade_volume == 150
        assert r2.trade_flow_imbalance == pytest.approx((100 - 50) / 150)
        # VWAP: (10000 * 100 + 9990 * 50) / 150 = 9996.6666...
        assert r2.rolling_vwap == pytest.approx((1000000 + 499500) / 150)

        # Trade 3: Buy 50 @ 10010 (completes 3-trade window)
        r3 = engine.on_trade(3000, 3000, 3, 10010, 50, AggressorSide.BUY)
        assert r3 is not None
        assert r3.has_trade_flow is True
        assert r3.rolling_trade_volume == 200
        assert r3.rolling_buy_volume == 150
        assert r3.rolling_sell_volume == 50
        assert r3.trade_flow_imbalance == pytest.approx((150 - 50) / 200)

    def test_short_horizon_returns_and_realized_volatility(self) -> None:
        cfg = FeatureEngineConfig(return_lookback=1, volatility_window=4)
        engine = MicrostructureFeatureEngine(instrument_id=101, config=cfg)

        mids = [100.0, 102.0, 101.0, 103.0, 105.0]
        for i, mid in enumerate(mids):
            p = int(mid)
            engine.on_top_of_book(1000 * (i + 1), 1000 * (i + 1), i + 1, p - 1, 10, p + 1, 10)

        f = engine.current_features
        assert f is not None
        assert f.has_log_return is True
        assert f.log_return == pytest.approx(math.log(105.0 / 103.0))
        assert f.has_realized_volatility is True
        assert f.realized_volatility is not None and f.realized_volatility > 0.0

    def test_roll_effective_spread(self) -> None:
        cfg = FeatureEngineConfig(roll_window=4)
        engine = MicrostructureFeatureEngine(instrument_id=101, config=cfg)

        # Alternating bouncing trade prices: 100, 102, 100, 102, 100
        prices = [100, 102, 100, 102, 100]
        for i, p in enumerate(prices):
            engine.on_trade(1000 * (i + 1), 1000 * (i + 1), i + 1, p, 10, AggressorSide.BUY)

        f = engine.current_features
        assert f is not None
        assert f.has_roll_spread is True
        assert f.roll_spread is not None and f.roll_spread > 0.0

    def test_vpin_calculation(self) -> None:
        cfg = FeatureEngineConfig(vpin_bucket_volume=100, vpin_num_buckets=2)
        engine = MicrostructureFeatureEngine(instrument_id=101, config=cfg)

        # Bucket 1: 100 Buy => |100 - 0| = 100
        engine.on_trade(1000, 1000, 1, 100, 100, AggressorSide.BUY)
        assert engine.current_features is not None
        assert engine.current_features.has_vpin is False

        # Bucket 2: 70 Buy + 30 Sell => |70 - 30| = 40
        engine.on_trade(2000, 2000, 2, 100, 70, AggressorSide.BUY)
        engine.on_trade(3000, 3000, 3, 100, 30, AggressorSide.SELL)

        f = engine.current_features
        assert f is not None
        assert f.has_vpin is True
        # Total imbalance = 100 + 40 = 140, Denom = 2 * 100 = 200 => VPIN = 0.70
        assert f.vpin == pytest.approx(0.70)

    def test_depth_snapshot_processing(self) -> None:
        cfg = FeatureEngineConfig(depth_levels=2)
        engine = MicrostructureFeatureEngine(instrument_id=101, config=cfg)

        bids = [{"price": 100, "quantity": 50}, {"price": 99, "quantity": 30}]
        asks = [{"price": 102, "quantity": 40}, {"price": 103, "quantity": 40}]

        f = engine.on_depth_snapshot(1000, 1000, 1, bids, asks)
        assert f is not None
        assert f.has_bid is True
        assert f.has_ask is True
        assert f.spread == 2
        assert f.bid_depth_k == 80
        assert f.ask_depth_k == 80
        assert f.has_depth_imbalance is True
        assert f.depth_imbalance_k == 0.0

    def test_out_of_order_timestamp_handling(self) -> None:
        engine = MicrostructureFeatureEngine(instrument_id=101)

        r1 = engine.on_top_of_book(1000, 1000, 1, 100, 10, 102, 10)
        assert r1 is not None
        assert engine.out_of_order_count == 0

        # Out-of-order event: timestamp 999 < 1000
        r2 = engine.on_top_of_book(999, 1000, 2, 100, 10, 102, 10)
        assert r2 is None
        assert engine.out_of_order_count == 1

        # Duplicate timestamp (1000 == 1000): accepted in same burst/tick
        r3 = engine.on_top_of_book(1000, 1005, 3, 100, 12, 102, 10)
        assert r3 is not None
        assert engine.out_of_order_count == 1

    def test_ask_only_and_bid_only_one_sided_books(self) -> None:
        engine = MicrostructureFeatureEngine(instrument_id=101)

        # Ask only
        r_ask = engine.on_top_of_book(1000, 1000, 1, 0, 0, 10020, 50)
        assert r_ask is not None
        assert r_ask.has_bid is False
        assert r_ask.has_ask is True
        assert r_ask.has_spread is False
        assert r_ask.has_mid is False
        assert r_ask.has_weighted_mid is False
        assert r_ask.has_book_imbalance is False
        assert r_ask.best_ask_price == 10020
        assert r_ask.best_bid_price is None

        # Bid only
        engine.reset()
        r_bid = engine.on_top_of_book(2000, 2000, 1, 10000, 50, 0, 0)
        assert r_bid is not None
        assert r_bid.has_bid is True
        assert r_bid.has_ask is False
        assert r_bid.has_spread is False
        assert r_bid.has_mid is False
        assert r_bid.best_bid_price == 10000
        assert r_bid.best_ask_price is None

    def test_locked_book_handling(self) -> None:
        engine = MicrostructureFeatureEngine(instrument_id=101)
        r = engine.on_top_of_book(1000, 1000, 1, 10000, 50, 10000, 50)
        assert r is not None
        assert r.is_crossed is True
        assert r.has_spread is False
        assert r.has_mid is False
        assert r.has_weighted_mid is False
        assert r.has_book_imbalance is False

    def test_invalid_trade_inputs_raise_error(self) -> None:
        engine = MicrostructureFeatureEngine(instrument_id=101)
        with pytest.raises(InvalidEventDataError, match="Invalid trade price"):
            engine.on_trade(1000, 1000, 1, 0, 100, AggressorSide.BUY)
        with pytest.raises(InvalidEventDataError, match="Invalid trade price"):
            engine.on_trade(2000, 2000, 2, -100, 100, AggressorSide.BUY)
        with pytest.raises(InvalidEventDataError, match="Invalid trade price"):
            engine.on_trade(3000, 3000, 3, 10000, 0, AggressorSide.BUY)

    def test_insufficient_history_and_gating(self) -> None:
        cfg = FeatureEngineConfig(return_lookback=2, volatility_window=4)
        engine = MicrostructureFeatureEngine(instrument_id=101, config=cfg)

        # 1 quote: no return, no vol
        r1 = engine.on_top_of_book(1000, 1000, 1, 100, 10, 102, 10)
        assert r1 is not None
        assert r1.has_log_return is False
        assert r1.has_realized_volatility is False

        # 2 quotes (lookback=2 requires > 2 quotes)
        r2 = engine.on_top_of_book(2000, 2000, 2, 101, 10, 103, 10)
        assert r2 is not None
        assert r2.has_log_return is False

        # 3 quotes: 1 return generated, but vol requires 4 returns
        r3 = engine.on_top_of_book(3000, 3000, 3, 102, 10, 104, 10)
        assert r3 is not None
        assert r3.has_log_return is True
        assert r3.has_realized_volatility is False

    def test_extract_from_table(self) -> None:
        engine = MicrostructureFeatureEngine(instrument_id=101)

        input_table = pa.Table.from_pydict(
            {
                "source_timestamp_ns": [1000, 2000, 3000],
                "receive_timestamp_ns": [1005, 2005, 3005],
                "sequence_num": [1, 2, 3],
                "best_bid_price": [100, 100, 101],
                "best_bid_quantity": [50, 60, 40],
                "best_ask_price": [102, 102, 103],
                "best_ask_quantity": [40, 40, 50],
            }
        )

        out_table = engine.extract_from_table(input_table, event_type="top_of_book")
        assert len(out_table) == 3
        assert out_table.schema.names == MICROSTRUCTURE_FEATURES_SCHEMA_V1.names
        assert out_table["spread"].to_pylist() == [2, 2, 2]
        assert out_table["has_spread"].to_pylist() == [True, True, True]
        assert out_table["instant_ofi"].to_pylist()[1] == 10  # 60 - 50 = 10
