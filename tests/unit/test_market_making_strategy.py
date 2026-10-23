"""Comprehensive tests for Market Making Strategy engine lifecycle and Phase 11 integration."""

import math

import pyarrow as pa
import pytest

from research.market_making.engine import MarketMakingStrategy
from research.market_making.types import (
    MarketMakingConfig,
    MarketQuoteSnapshot,
    QuoteSuppressionReason,
)
from research.strategies.types import (
    FillRecord,
    OrderSide,
    OrderType,
    validate_temporal_coordinates,
)


@pytest.fixture
def mm_strategy() -> MarketMakingStrategy:
    config = MarketMakingConfig(
        instrument_id=1,
        tick_size=0.01,
        price_scale=100.0,
        quote_size=100,
        risk_aversion=0.1,
        volatility=0.02,
        terminal_horizon=1.0,
        half_spread=0.05,
        max_long_inventory=500,
        max_short_inventory=500,
        max_notional_exposure=100_000.0,
        stale_quote_timeout_ns=5_000_000_000,
    )
    return MarketMakingStrategy(config)


@pytest.fixture
def standard_quote() -> MarketQuoteSnapshot:
    return MarketQuoteSnapshot(
        instrument_id=1,
        event_timestamp_ns=1_000_000_000,
        available_timestamp_ns=1_000_000_000,
        best_bid_price=10000,  # $100.00
        best_bid_quantity=1000,
        best_ask_price=10010,  # $100.10 (mid = $100.05, spread = $0.10)
        best_ask_quantity=1000,
        price_scale=100.0,
    )


class TestMarketMakingStrategyLifecycle:
    """Tests for the MarketMakingStrategy class lifecycle."""

    def test_initial_state_is_flat(self, mm_strategy: MarketMakingStrategy) -> None:
        """New strategy starts flat with initial cash and fitted=True."""
        assert mm_strategy.is_fitted is True
        inv = mm_strategy.inventory_state
        assert inv.is_flat is True
        assert inv.inventory == 0
        assert inv.cash == 1_000_000.0
        assert inv.realized_pnl == 0.0

    def test_compute_quotes_zero_inventory_symmetric(
        self,
        mm_strategy: MarketMakingStrategy,
        standard_quote: MarketQuoteSnapshot,
    ) -> None:
        """Under flat inventory, reservation price equals mid and quotes are symmetric."""
        decision = mm_strategy.compute_quotes(standard_quote)

        assert decision.is_valid is True
        assert decision.is_two_sided is True
        assert math.isclose(decision.reservation_price, standard_quote.mid_dollars, rel_tol=1e-9)

        # Invariant: Bid < Ask
        assert decision.bid_quote.price_ticks < decision.ask_quote.price_ticks
        assert decision.bid_quote.quantity == 100
        assert decision.ask_quote.quantity == 100
        assert decision.bid_quote.is_post_only is True
        assert decision.ask_quote.is_post_only is True

    def test_compute_quotes_inventory_skewing(
        self,
        mm_strategy: MarketMakingStrategy,
        standard_quote: MarketQuoteSnapshot,
    ) -> None:
        """Positive inventory lowers reservation price; negative inventory raises it."""
        mid = standard_quote.mid_dollars

        # 1. Long Inventory (+200 shares)
        mm_strategy.set_inventory_direct(200)
        long_dec = mm_strategy.compute_quotes(standard_quote)
        assert long_dec.reservation_price < mid
        # Under long inventory, ask is more competitive (closer to mid)
        assert long_dec.ask_quote.price_ticks <= 10010

        # 2. Short Inventory (-200 shares)
        mm_strategy.set_inventory_direct(-200)
        short_dec = mm_strategy.compute_quotes(standard_quote)
        assert short_dec.reservation_price > mid
        # Under short inventory, bid is more aggressive (closer to mid)
        assert short_dec.bid_quote.price_ticks >= 10000

    def test_inventory_limits_suppression(
        self,
        mm_strategy: MarketMakingStrategy,
        standard_quote: MarketQuoteSnapshot,
    ) -> None:
        """Quotes breaching inventory limits are suppressed, but risk-reducing quotes stay."""
        # Set inventory to max long (500)
        mm_strategy.set_inventory_direct(500)
        dec_long = mm_strategy.compute_quotes(standard_quote)

        # Buying is suppressed
        assert dec_long.bid_quote.is_suppressed is True
        assert dec_long.bid_quote.suppression_reason == QuoteSuppressionReason.LONG_INVENTORY_LIMIT
        assert dec_long.bid_quote.quantity == 0

        # Selling (offloading) remains active!
        assert dec_long.ask_quote.is_suppressed is False
        assert dec_long.ask_quote.quantity == 100
        assert dec_long.has_active_ask is True

        # Set inventory to max short (-500)
        mm_strategy.set_inventory_direct(-500)
        dec_short = mm_strategy.compute_quotes(standard_quote)

        # Selling is suppressed
        assert dec_short.ask_quote.is_suppressed is True
        assert (
            dec_short.ask_quote.suppression_reason == QuoteSuppressionReason.SHORT_INVENTORY_LIMIT
        )
        assert dec_short.ask_quote.quantity == 0

        # Buying (covering) remains active!
        assert dec_short.bid_quote.is_suppressed is False
        assert dec_short.bid_quote.quantity == 100
        assert dec_short.has_active_bid is True

    def test_fill_record_inventory_and_cash_accounting(
        self,
        mm_strategy: MarketMakingStrategy,
    ) -> None:
        """Fill events update inventory, cash ledger, average entry price, and realized PnL."""
        # 1. Buy Fill: 100 shares @ $100.00 (price_ticks = 10000), friction = $0.05
        buy_fill = FillRecord(
            fill_id="FILL-001",
            order_id="ORD-001",
            fill_timestamp_ns=1_000_000_100,
            instrument_id=1,
            side=OrderSide.BUY,
            quantity=100,
            price=10000,
            spread_cost=0.02,
            slippage_cost=0.01,
            exchange_fee=0.01,
            regulatory_fee=0.01,
        )
        mm_strategy.on_fill(buy_fill)

        inv = mm_strategy.inventory_state
        assert inv.inventory == 100
        assert math.isclose(inv.average_entry_price, 100.0, rel_tol=1e-9)
        # Cash: 1,000,000 - 10,000 - 0.05 = 989,999.95
        assert math.isclose(inv.cash, 989_999.95, rel_tol=1e-9)
        assert inv.realized_pnl == 0.0

        # 2. Sell Fill: 100 shares @ $100.10 (price_ticks = 10010), friction = $0.05
        # Realized gross PnL: 100 * (100.10 - 100.00) = $10.00
        sell_fill = FillRecord(
            fill_id="FILL-002",
            order_id="ORD-002",
            fill_timestamp_ns=1_000_000_200,
            instrument_id=1,
            side=OrderSide.SELL,
            quantity=100,
            price=10010,
            spread_cost=0.02,
            slippage_cost=0.01,
            exchange_fee=0.01,
            regulatory_fee=0.01,
        )
        mm_strategy.on_fill(sell_fill)

        inv2 = mm_strategy.inventory_state
        assert inv2.inventory == 0
        assert inv2.is_flat is True
        assert math.isclose(inv2.realized_pnl, 10.0, rel_tol=1e-9)
        # Cash: 989,999.95 + 10,010.00 - 0.05 = 1,000,009.90
        assert math.isclose(inv2.cash, 1_000_009.90, rel_tol=1e-9)

    def test_create_order_intents_emits_valid_passive_limit_orders(
        self,
        mm_strategy: MarketMakingStrategy,
        standard_quote: MarketQuoteSnapshot,
    ) -> None:
        """Strategy converts active QuoteDecision into passive OrderIntents."""
        decision = mm_strategy.compute_quotes(standard_quote, decision_timestamp_ns=1_000_000_000)
        intents = mm_strategy.create_order_intents(decision, latency_ns=500)

        assert len(intents) == 2
        bid_intent, ask_intent = intents[0], intents[1]

        # Bid Order
        assert bid_intent.side == OrderSide.BUY
        assert bid_intent.order_type == OrderType.LIMIT
        assert bid_intent.limit_price == decision.bid_quote.price_ticks
        assert bid_intent.quantity == 100
        assert bid_intent.actionable_timestamp_ns == 1_000_000_500
        assert bid_intent.decision_timestamp_ns == 1_000_000_000

        # Ask Order
        assert ask_intent.side == OrderSide.SELL
        assert ask_intent.order_type == OrderType.LIMIT
        assert ask_intent.limit_price == decision.ask_quote.price_ticks
        assert ask_intent.quantity == 100
        assert ask_intent.actionable_timestamp_ns == 1_000_000_500

        # Validate 5-point temporal coordinate chain
        validate_temporal_coordinates(
            event_timestamp_ns=standard_quote.event_timestamp_ns,
            available_timestamp_ns=standard_quote.available_timestamp_ns,
            decision_timestamp_ns=bid_intent.decision_timestamp_ns,
            actionable_timestamp_ns=bid_intent.actionable_timestamp_ns,
            fill_timestamp_ns=bid_intent.actionable_timestamp_ns + 1000,
        )

    def test_strategy_determinism(
        self,
        mm_strategy: MarketMakingStrategy,
        standard_quote: MarketQuoteSnapshot,
    ) -> None:
        """Two identical runs on the same input sequence produce identical results."""
        mm_strategy.reset()
        mm_strategy.set_inventory_direct(150)
        dec1 = mm_strategy.compute_quotes(standard_quote)

        mm_strategy.reset()
        mm_strategy.set_inventory_direct(150)
        dec2 = mm_strategy.compute_quotes(standard_quote)

        assert dec1.reservation_price == dec2.reservation_price
        assert dec1.bid_quote.price_ticks == dec2.bid_quote.price_ticks
        assert dec1.ask_quote.price_ticks == dec2.ask_quote.price_ticks
        assert dec1.suppression_reasons == dec2.suppression_reasons

    def test_generate_signals_table_conforms_to_schema(
        self,
        mm_strategy: MarketMakingStrategy,
    ) -> None:
        """generate_signals produces a PyArrow table conforming to SIGNAL_SCHEMA_V1."""
        n_rows = 5
        market_table = pa.Table.from_pydict(
            {
                "event_timestamp_ns": [1_000_000_000 + i * 1_000 for i in range(n_rows)],
                "decision_timestamp_ns": [1_000_000_000 + i * 1_000 for i in range(n_rows)],
                "best_bid_price": [10000 + i for i in range(n_rows)],
                "best_bid_quantity": [500] * n_rows,
                "best_ask_price": [10010 + i for i in range(n_rows)],
                "best_ask_quantity": [500] * n_rows,
                "mid_price": [100.05 + i * 0.01 for i in range(n_rows)],
                "is_crossed": [False] * n_rows,
            }
        )

        signals_table = mm_strategy.generate_signals(market_table)
        assert len(signals_table) == n_rows
        assert "decision_timestamp_ns" in signals_table.column_names
        assert "target_weight" in signals_table.column_names
        assert "direction" in signals_table.column_names
        assert "is_valid" in signals_table.column_names

        # Flat inventory -> direction = 0, target_weight = 0.0
        dirs = signals_table["direction"].to_pylist()
        weights = signals_table["target_weight"].to_pylist()
        assert all(d == 0 for d in dirs)
        assert all(w == 0.0 for w in weights)
