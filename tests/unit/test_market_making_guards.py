"""Unit tests for Market Making Engine adverse-selection, quality, and risk guards."""

import pytest

from research.features.types import MicrostructureFeatureRecord
from research.market_making.guards import (
    CompositeMarketGuard,
    DepthGuard,
    InventoryLimitGuard,
    MicrostructureGuard,
    SpreadGuard,
    StaleQuoteGuard,
    VolatilityGuard,
)
from research.market_making.model import build_raw_quotes
from research.market_making.types import (
    InventoryState,
    MarketMakingConfig,
    MarketQuoteSnapshot,
    QuoteSuppressionReason,
)


@pytest.fixture
def base_config() -> MarketMakingConfig:
    return MarketMakingConfig(
        instrument_id=1,
        tick_size=0.01,
        price_scale=100.0,
        quote_size=100,
        stale_quote_timeout_ns=5_000_000_000,  # 5 seconds
        max_market_spread=1.00,  # $1.00
        min_displayed_depth=100,
        max_volatility=0.20,
        max_long_inventory=500,
        max_short_inventory=500,
        max_notional_exposure=100_000.0,
    )


@pytest.fixture
def valid_quote_snapshot() -> MarketQuoteSnapshot:
    return MarketQuoteSnapshot(
        instrument_id=1,
        event_timestamp_ns=1_000_000_000,
        available_timestamp_ns=1_000_000_000,
        best_bid_price=10000,  # $100.00
        best_bid_quantity=500,
        best_ask_price=10010,  # $100.10 (spread $0.10)
        best_ask_quantity=500,
        price_scale=100.0,
        is_valid=True,
    )


@pytest.fixture
def flat_inventory() -> InventoryState:
    return InventoryState(instrument_id=1, inventory=0, cash=1_000_000.0)


class TestStaleQuoteGuard:
    """Tests for StaleQuoteGuard."""

    def test_fresh_quote_allowed(
        self,
        base_config: MarketMakingConfig,
        valid_quote_snapshot: MarketQuoteSnapshot,
        flat_inventory: InventoryState,
    ) -> None:
        guard = StaleQuoteGuard()
        # Decision 1s after quote arrival
        bid_ok, ask_ok, reasons = guard.evaluate(
            quote_snapshot=valid_quote_snapshot,
            inventory_state=flat_inventory,
            config=base_config,
            decision_timestamp_ns=2_000_000_000,
        )
        assert bid_ok is True
        assert ask_ok is True
        assert len(reasons) == 0

    def test_stale_quote_suppressed(
        self,
        base_config: MarketMakingConfig,
        valid_quote_snapshot: MarketQuoteSnapshot,
        flat_inventory: InventoryState,
    ) -> None:
        guard = StaleQuoteGuard()
        # Decision 6s after quote arrival (timeout is 5s)
        bid_ok, ask_ok, reasons = guard.evaluate(
            quote_snapshot=valid_quote_snapshot,
            inventory_state=flat_inventory,
            config=base_config,
            decision_timestamp_ns=7_000_000_001,
        )
        assert bid_ok is False
        assert ask_ok is False
        assert QuoteSuppressionReason.STALE_MARKET_DATA in reasons


class TestSpreadGuard:
    """Tests for SpreadGuard."""

    def test_normal_spread_allowed(
        self,
        base_config: MarketMakingConfig,
        valid_quote_snapshot: MarketQuoteSnapshot,
        flat_inventory: InventoryState,
    ) -> None:
        guard = SpreadGuard()
        bid_ok, ask_ok, reasons = guard.evaluate(
            quote_snapshot=valid_quote_snapshot,
            inventory_state=flat_inventory,
            config=base_config,
        )
        assert bid_ok is True
        assert ask_ok is True
        assert len(reasons) == 0

    def test_crossed_or_locked_book_suppressed(
        self,
        base_config: MarketMakingConfig,
        flat_inventory: InventoryState,
    ) -> None:
        guard = SpreadGuard()

        # Locked book (bid == ask)
        locked_snapshot = MarketQuoteSnapshot(
            instrument_id=1,
            event_timestamp_ns=1_000_000_000,
            available_timestamp_ns=1_000_000_000,
            best_bid_price=10000,
            best_bid_quantity=100,
            best_ask_price=10000,
            best_ask_quantity=100,
        )
        bid_ok, ask_ok, reasons = guard.evaluate(locked_snapshot, flat_inventory, base_config)
        assert bid_ok is False
        assert ask_ok is False
        assert QuoteSuppressionReason.CROSSED_OR_LOCKED_BOOK in reasons

        # Crossed book (bid > ask)
        crossed_snapshot = MarketQuoteSnapshot(
            instrument_id=1,
            event_timestamp_ns=1_000_000_000,
            available_timestamp_ns=1_000_000_000,
            best_bid_price=10050,
            best_bid_quantity=100,
            best_ask_price=10000,
            best_ask_quantity=100,
        )
        bid_ok2, ask_ok2, reasons2 = guard.evaluate(crossed_snapshot, flat_inventory, base_config)
        assert bid_ok2 is False
        assert ask_ok2 is False
        assert QuoteSuppressionReason.CROSSED_OR_LOCKED_BOOK in reasons2

    def test_excessive_spread_suppressed(
        self,
        base_config: MarketMakingConfig,
        flat_inventory: InventoryState,
    ) -> None:
        guard = SpreadGuard()
        # Spread is $1.50 (max allowed is $1.00)
        wide_snapshot = MarketQuoteSnapshot(
            instrument_id=1,
            event_timestamp_ns=1_000_000_000,
            available_timestamp_ns=1_000_000_000,
            best_bid_price=10000,
            best_bid_quantity=200,
            best_ask_price=10150,
            best_ask_quantity=200,
        )
        bid_ok, ask_ok, reasons = guard.evaluate(wide_snapshot, flat_inventory, base_config)
        assert bid_ok is False
        assert ask_ok is False
        assert QuoteSuppressionReason.EXCESSIVE_SPREAD in reasons


class TestDepthGuard:
    """Tests for DepthGuard."""

    def test_insufficient_bid_or_ask_depth_suppressed(
        self,
        base_config: MarketMakingConfig,
        flat_inventory: InventoryState,
    ) -> None:
        guard = DepthGuard()
        # min_displayed_depth is 100

        # Insufficient bid depth
        thin_bid_snapshot = MarketQuoteSnapshot(
            instrument_id=1,
            event_timestamp_ns=1_000_000_000,
            available_timestamp_ns=1_000_000_000,
            best_bid_price=10000,
            best_bid_quantity=50,  # < 100
            best_ask_price=10010,
            best_ask_quantity=200,
        )
        bid_ok, ask_ok, reasons = guard.evaluate(thin_bid_snapshot, flat_inventory, base_config)
        assert bid_ok is False
        assert ask_ok is False
        assert QuoteSuppressionReason.INSUFFICIENT_DEPTH in reasons


class TestVolatilityGuard:
    """Tests for VolatilityGuard."""

    def test_excessive_volatility_suppressed(
        self,
        base_config: MarketMakingConfig,
        valid_quote_snapshot: MarketQuoteSnapshot,
        flat_inventory: InventoryState,
    ) -> None:
        guard = VolatilityGuard()
        # max_volatility is 0.20

        # Low volatility feature
        low_vol_feat = MicrostructureFeatureRecord(
            instrument_id=1,
            sequence_num=1,
            event_timestamp_ns=1_000_000_000,
            source_timestamp_ns=1_000_000_000,
            decision_timestamp_ns=1_000_000_000,
            best_bid_price=10000,
            best_bid_quantity=500,
            best_ask_price=10010,
            best_ask_quantity=500,
            spread=10,
            relative_spread=0.001,
            mid_price=100.05,
            weighted_mid_price=100.05,
            book_imbalance_top=0.0,
            bid_depth_k=500,
            ask_depth_k=500,
            depth_imbalance_k=0.0,
            instant_ofi=0,
            rolling_ofi=0,
            last_signed_volume=0,
            rolling_trade_volume=0,
            rolling_buy_volume=0,
            rolling_sell_volume=0,
            trade_flow_imbalance=0.0,
            rolling_vwap=100.05,
            log_return=0.0,
            realized_volatility=0.10,
            roll_spread=None,
            vpin=None,
            has_bid=True,
            has_ask=True,
            is_crossed=False,
            has_spread=True,
            has_mid=True,
            has_weighted_mid=True,
            has_book_imbalance=True,
            has_depth_imbalance=True,
            has_instant_ofi=False,
            has_rolling_ofi=False,
            has_trade=False,
            has_trade_flow=False,
            has_vwap=True,
            has_log_return=True,
            has_realized_volatility=True,
            has_roll_spread=False,
            has_vpin=False,
        )
        bid_ok, ask_ok, reasons = guard.evaluate(
            valid_quote_snapshot, flat_inventory, base_config, low_vol_feat
        )
        assert bid_ok is True
        assert ask_ok is True
        assert len(reasons) == 0

        # High volatility feature (0.35 > 0.20)
        high_vol_feat = MicrostructureFeatureRecord(
            instrument_id=1,
            sequence_num=2,
            event_timestamp_ns=1_000_000_000,
            source_timestamp_ns=1_000_000_000,
            decision_timestamp_ns=1_000_000_000,
            best_bid_price=10000,
            best_bid_quantity=500,
            best_ask_price=10010,
            best_ask_quantity=500,
            spread=10,
            relative_spread=0.001,
            mid_price=100.05,
            weighted_mid_price=100.05,
            book_imbalance_top=0.0,
            bid_depth_k=500,
            ask_depth_k=500,
            depth_imbalance_k=0.0,
            instant_ofi=0,
            rolling_ofi=0,
            last_signed_volume=0,
            rolling_trade_volume=0,
            rolling_buy_volume=0,
            rolling_sell_volume=0,
            trade_flow_imbalance=0.0,
            rolling_vwap=100.05,
            log_return=0.0,
            realized_volatility=0.35,
            roll_spread=None,
            vpin=None,
            has_bid=True,
            has_ask=True,
            is_crossed=False,
            has_spread=True,
            has_mid=True,
            has_weighted_mid=True,
            has_book_imbalance=True,
            has_depth_imbalance=True,
            has_instant_ofi=False,
            has_rolling_ofi=False,
            has_trade=False,
            has_trade_flow=False,
            has_vwap=True,
            has_log_return=True,
            has_realized_volatility=True,
            has_roll_spread=False,
            has_vpin=False,
        )
        b_ok, a_ok, r_list = guard.evaluate(
            valid_quote_snapshot, flat_inventory, base_config, high_vol_feat
        )
        assert b_ok is False
        assert a_ok is False
        assert QuoteSuppressionReason.EXCESSIVE_VOLATILITY in r_list


class TestMicrostructureGuard:
    """Tests for MicrostructureGuard evaluating OFI, depth imbalance, and VPIN."""

    def test_ofi_imbalance_asymmetric_suppression(
        self,
        base_config: MarketMakingConfig,
        valid_quote_snapshot: MarketQuoteSnapshot,
        flat_inventory: InventoryState,
    ) -> None:
        """Heavy positive OFI suppresses Ask; heavy negative OFI suppresses Bid."""
        guard = MicrostructureGuard()
        cfg = MarketMakingConfig(
            instrument_id=1,
            max_ofi_magnitude=500.0,
        )

        # 1. Heavy buying OFI (+1000 > +500)
        buy_ofi_feat = MicrostructureFeatureRecord(
            instrument_id=1,
            sequence_num=1,
            event_timestamp_ns=1_000_000_000,
            source_timestamp_ns=1_000_000_000,
            decision_timestamp_ns=1_000_000_000,
            best_bid_price=10000,
            best_bid_quantity=500,
            best_ask_price=10010,
            best_ask_quantity=500,
            spread=10,
            relative_spread=0.001,
            mid_price=100.05,
            weighted_mid_price=100.05,
            book_imbalance_top=0.0,
            bid_depth_k=500,
            ask_depth_k=500,
            depth_imbalance_k=0.0,
            instant_ofi=1000,
            rolling_ofi=1000,
            last_signed_volume=0,
            rolling_trade_volume=0,
            rolling_buy_volume=0,
            rolling_sell_volume=0,
            trade_flow_imbalance=0.0,
            rolling_vwap=100.05,
            log_return=0.0,
            realized_volatility=0.01,
            roll_spread=None,
            vpin=None,
            has_bid=True,
            has_ask=True,
            is_crossed=False,
            has_spread=True,
            has_mid=True,
            has_weighted_mid=True,
            has_book_imbalance=True,
            has_depth_imbalance=True,
            has_instant_ofi=True,
            has_rolling_ofi=True,
            has_trade=False,
            has_trade_flow=False,
            has_vwap=True,
            has_log_return=True,
            has_realized_volatility=True,
            has_roll_spread=False,
            has_vpin=False,
        )
        b_ok, a_ok, r = guard.evaluate(valid_quote_snapshot, flat_inventory, cfg, buy_ofi_feat)
        # Buying OFI means toxic buying pressure; ask is suppressed, bid allowed
        assert b_ok is True
        assert a_ok is False
        assert QuoteSuppressionReason.MICROSTRUCTURE_IMBALANCE in r

    def test_vpin_toxicity_suppression(
        self,
        base_config: MarketMakingConfig,
        valid_quote_snapshot: MarketQuoteSnapshot,
        flat_inventory: InventoryState,
    ) -> None:
        """VPIN exceeding threshold suppresses both quotes."""
        guard = MicrostructureGuard()
        cfg = MarketMakingConfig(
            instrument_id=1,
            max_vpin=0.75,
        )

        toxic_feat = MicrostructureFeatureRecord(
            instrument_id=1,
            sequence_num=2,
            event_timestamp_ns=1_000_000_000,
            source_timestamp_ns=1_000_000_000,
            decision_timestamp_ns=1_000_000_000,
            best_bid_price=10000,
            best_bid_quantity=500,
            best_ask_price=10010,
            best_ask_quantity=500,
            spread=10,
            relative_spread=0.001,
            mid_price=100.05,
            weighted_mid_price=100.05,
            book_imbalance_top=0.0,
            bid_depth_k=500,
            ask_depth_k=500,
            depth_imbalance_k=0.0,
            instant_ofi=0,
            rolling_ofi=0,
            last_signed_volume=0,
            rolling_trade_volume=0,
            rolling_buy_volume=0,
            rolling_sell_volume=0,
            trade_flow_imbalance=0.0,
            rolling_vwap=100.05,
            log_return=0.0,
            realized_volatility=0.01,
            roll_spread=None,
            vpin=0.85,
            has_bid=True,
            has_ask=True,
            is_crossed=False,
            has_spread=True,
            has_mid=True,
            has_weighted_mid=True,
            has_book_imbalance=True,
            has_depth_imbalance=True,
            has_instant_ofi=False,
            has_rolling_ofi=False,
            has_trade=False,
            has_trade_flow=False,
            has_vwap=True,
            has_log_return=True,
            has_realized_volatility=True,
            has_roll_spread=False,
            has_vpin=True,
        )
        b_ok, a_ok, r = guard.evaluate(valid_quote_snapshot, flat_inventory, cfg, toxic_feat)
        assert b_ok is False
        assert a_ok is False
        assert QuoteSuppressionReason.MICROSTRUCTURE_IMBALANCE in r

    def test_missing_features_with_strict_validity(
        self,
        base_config: MarketMakingConfig,
        valid_quote_snapshot: MarketQuoteSnapshot,
        flat_inventory: InventoryState,
    ) -> None:
        """When require_microstructure_validity=True, missing features trigger suppression."""
        guard = MicrostructureGuard()
        cfg = MarketMakingConfig(
            instrument_id=1,
            max_vpin=0.75,
            require_microstructure_validity=True,
        )

        missing_vpin_feat = MicrostructureFeatureRecord(
            instrument_id=1,
            sequence_num=3,
            event_timestamp_ns=1_000_000_000,
            source_timestamp_ns=1_000_000_000,
            decision_timestamp_ns=1_000_000_000,
            best_bid_price=10000,
            best_bid_quantity=500,
            best_ask_price=10010,
            best_ask_quantity=500,
            spread=10,
            relative_spread=0.001,
            mid_price=100.05,
            weighted_mid_price=100.05,
            book_imbalance_top=0.0,
            bid_depth_k=500,
            ask_depth_k=500,
            depth_imbalance_k=0.0,
            instant_ofi=0,
            rolling_ofi=0,
            last_signed_volume=0,
            rolling_trade_volume=0,
            rolling_buy_volume=0,
            rolling_sell_volume=0,
            trade_flow_imbalance=0.0,
            rolling_vwap=100.05,
            log_return=0.0,
            realized_volatility=0.01,
            roll_spread=None,
            vpin=None,
            has_bid=True,
            has_ask=True,
            is_crossed=False,
            has_spread=True,
            has_mid=True,
            has_weighted_mid=True,
            has_book_imbalance=True,
            has_depth_imbalance=True,
            has_instant_ofi=False,
            has_rolling_ofi=False,
            has_trade=False,
            has_trade_flow=False,
            has_vwap=True,
            has_log_return=True,
            has_realized_volatility=True,
            has_roll_spread=False,
            has_vpin=False,  # Missing!
        )
        b_ok, a_ok, r = guard.evaluate(
            valid_quote_snapshot, flat_inventory, cfg, missing_vpin_feat
        )
        assert b_ok is False
        assert a_ok is False
        assert QuoteSuppressionReason.MICROSTRUCTURE_IMBALANCE in r


class TestInventoryLimitGuard:
    """Tests for InventoryLimitGuard and asymmetric quote filtering."""

    def test_long_limit_suppresses_bid_allows_ask(
        self,
        base_config: MarketMakingConfig,
        valid_quote_snapshot: MarketQuoteSnapshot,
    ) -> None:
        """At max long inventory, buying is suppressed, but selling to offload is permitted."""
        guard = InventoryLimitGuard()
        long_inv = InventoryState(
            instrument_id=1,
            inventory=500,  # Max long limit is 500
            cash=950_000.0,
        )

        bid_ok, ask_ok, reasons = guard.evaluate(
            quote_snapshot=valid_quote_snapshot,
            inventory_state=long_inv,
            config=base_config,
        )
        assert bid_ok is False
        assert ask_ok is True
        assert QuoteSuppressionReason.LONG_INVENTORY_LIMIT in reasons

    def test_short_limit_suppresses_ask_allows_bid(
        self,
        base_config: MarketMakingConfig,
        valid_quote_snapshot: MarketQuoteSnapshot,
    ) -> None:
        """At max short inventory, selling is suppressed, but buying to cover is permitted."""
        guard = InventoryLimitGuard()
        short_inv = InventoryState(
            instrument_id=1,
            inventory=-500,  # Max short limit is 500
            cash=1_050_000.0,
        )

        bid_ok, ask_ok, reasons = guard.evaluate(
            quote_snapshot=valid_quote_snapshot,
            inventory_state=short_inv,
            config=base_config,
        )
        assert bid_ok is True
        assert ask_ok is False
        assert QuoteSuppressionReason.SHORT_INVENTORY_LIMIT in reasons

    def test_risk_reduction_only_mode(
        self,
        valid_quote_snapshot: MarketQuoteSnapshot,
    ) -> None:
        """When risk_reduction_only=True, only trades reducing existing inventory are permitted."""
        config_risk_reduce = MarketMakingConfig(
            instrument_id=1,
            risk_reduction_only=True,
            quote_size=100,
        )
        guard = InventoryLimitGuard()

        # Long position: only allow asks
        long_inv = InventoryState(instrument_id=1, inventory=200)
        b_ok, a_ok, r = guard.evaluate(valid_quote_snapshot, long_inv, config_risk_reduce)
        assert b_ok is False
        assert a_ok is True
        assert QuoteSuppressionReason.RISK_REDUCTION_ONLY in r

        # Short position: only allow bids
        short_inv = InventoryState(instrument_id=1, inventory=-200)
        b_ok2, a_ok2, r2 = guard.evaluate(valid_quote_snapshot, short_inv, config_risk_reduce)
        assert b_ok2 is True
        assert a_ok2 is False
        assert QuoteSuppressionReason.RISK_REDUCTION_ONLY in r2

        # Flat position: both suppressed
        flat_inv = InventoryState(instrument_id=1, inventory=0)
        b_ok3, a_ok3, r3 = guard.evaluate(valid_quote_snapshot, flat_inv, config_risk_reduce)
        assert b_ok3 is False
        assert a_ok3 is False
        assert QuoteSuppressionReason.RISK_REDUCTION_ONLY in r3


class TestCompositeMarketGuard:
    """Tests for CompositeMarketGuard quote filtering."""

    def test_composite_filters_raw_quotes(
        self,
        base_config: MarketMakingConfig,
        valid_quote_snapshot: MarketQuoteSnapshot,
        flat_inventory: InventoryState,
    ) -> None:
        comp = CompositeMarketGuard()
        raw_bid, raw_ask = build_raw_quotes(
            mid_price=valid_quote_snapshot.mid_dollars,
            reservation_price=valid_quote_snapshot.mid_dollars,
            half_spread=0.05,
            config=base_config,
        )

        filtered_bid, filtered_ask, reasons, diags = comp.filter_quotes(
            bid_quote=raw_bid,
            ask_quote=raw_ask,
            quote_snapshot=valid_quote_snapshot,
            inventory_state=flat_inventory,
            config=base_config,
        )

        assert filtered_bid.is_suppressed is False
        assert filtered_ask.is_suppressed is False
        assert filtered_bid.quantity == base_config.quote_size
        assert filtered_ask.quantity == base_config.quote_size
        assert len(reasons) == 0

    def test_composite_suppression_marks_quote_suppressed(
        self,
        base_config: MarketMakingConfig,
        valid_quote_snapshot: MarketQuoteSnapshot,
    ) -> None:
        comp = CompositeMarketGuard()
        long_inv = InventoryState(instrument_id=1, inventory=500)

        raw_bid, raw_ask = build_raw_quotes(
            mid_price=valid_quote_snapshot.mid_dollars,
            reservation_price=valid_quote_snapshot.mid_dollars - 0.05,
            half_spread=0.05,
            config=base_config,
        )

        f_bid, f_ask, reasons, _ = comp.filter_quotes(
            bid_quote=raw_bid,
            ask_quote=raw_ask,
            quote_snapshot=valid_quote_snapshot,
            inventory_state=long_inv,
            config=base_config,
        )

        assert f_bid.is_suppressed is True
        assert f_bid.quantity == 0
        assert f_bid.suppression_reason == QuoteSuppressionReason.LONG_INVENTORY_LIMIT
        assert f_ask.is_suppressed is False
        assert f_ask.quantity == base_config.quote_size


class TestConfigValidation:
    """Tests for MarketMakingConfig parameter validation and bounds."""

    def test_invalid_tick_size(self) -> None:
        with pytest.raises(ValueError, match="tick_size must be positive"):
            MarketMakingConfig(instrument_id=1, tick_size=-0.01)

    def test_invalid_quote_size(self) -> None:
        with pytest.raises(ValueError, match="quote_size must be positive"):
            MarketMakingConfig(instrument_id=1, quote_size=0)

    def test_max_quote_size_less_than_min(self) -> None:
        with pytest.raises(ValueError, match="max_quote_size cannot be less than min_quote_size"):
            MarketMakingConfig(instrument_id=1, min_quote_size=100, max_quote_size=50)

    def test_invalid_risk_aversion(self) -> None:
        with pytest.raises(ValueError, match="risk_aversion cannot be negative"):
            MarketMakingConfig(instrument_id=1, risk_aversion=-0.1)

    def test_invalid_spread_bounds(self) -> None:
        with pytest.raises(ValueError, match="max_half_spread cannot be less than min_half_spread"):
            MarketMakingConfig(instrument_id=1, min_half_spread=0.10, max_half_spread=0.05)

    def test_nan_values_rejected(self) -> None:
        with pytest.raises(ValueError, match="volatility must be a finite float"):
            MarketMakingConfig(instrument_id=1, volatility=float("nan"))

