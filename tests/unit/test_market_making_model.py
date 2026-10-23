"""Unit tests for Avellaneda-Stoikov reservation price, optimal spread, and tick rounding."""

import math

import pytest

from research.market_making.model import (
    build_raw_quotes,
    compute_optimal_half_spread,
    compute_reservation_price,
    round_to_tick,
)
from research.market_making.types import MarketMakingConfig
from research.strategies.types import OrderSide


class TestReservationPriceModel:
    """Tests for the Avellaneda-Stoikov reservation price calculation."""

    def test_zero_inventory_symmetric_reservation_price(self) -> None:
        """When inventory is zero (flat), reservation price equals mid-price."""
        mid = 100.0
        r = compute_reservation_price(
            mid_price=mid,
            inventory=0,
            risk_aversion=0.1,
            volatility=0.02,
            horizon=1.0,
        )
        assert math.isclose(r, mid, rel_tol=1e-12)

    def test_positive_inventory_skews_downward(self) -> None:
        """Positive inventory (long) must lower the reservation price below mid."""
        mid = 100.0
        q = 100
        gamma = 0.1
        sigma = 0.05
        tau = 1.0

        r = compute_reservation_price(
            mid_price=mid,
            inventory=q,
            risk_aversion=gamma,
            volatility=sigma,
            horizon=tau,
        )
        expected_penalty = q * gamma * (sigma**2) * tau
        assert math.isclose(r, mid - expected_penalty, rel_tol=1e-12)
        assert r < mid

    def test_negative_inventory_skews_upward(self) -> None:
        """Negative inventory (short) must raise the reservation price above mid."""
        mid = 100.0
        q = -100
        gamma = 0.1
        sigma = 0.05
        tau = 1.0

        r = compute_reservation_price(
            mid_price=mid,
            inventory=q,
            risk_aversion=gamma,
            volatility=sigma,
            horizon=tau,
        )
        expected_penalty = q * gamma * (sigma**2) * tau  # negative penalty, so r > mid
        assert math.isclose(r, mid - expected_penalty, rel_tol=1e-12)
        assert r > mid

    def test_higher_risk_aversion_increases_inventory_skew(self) -> None:
        """Higher risk aversion gamma increases the reservation price shift."""
        mid = 100.0
        q = 50
        sigma = 0.02
        tau = 1.0

        r_low_gamma = compute_reservation_price(
            mid_price=mid, inventory=q, risk_aversion=0.05, volatility=sigma, horizon=tau
        )
        r_high_gamma = compute_reservation_price(
            mid_price=mid, inventory=q, risk_aversion=0.20, volatility=sigma, horizon=tau
        )

        assert r_high_gamma < r_low_gamma < mid
        skew_low = mid - r_low_gamma
        skew_high = mid - r_high_gamma
        assert math.isclose(skew_high / skew_low, 4.0, rel_tol=1e-9)

    def test_zero_risk_aversion_eliminates_skew(self) -> None:
        """When risk aversion is zero (risk-neutral), reservation price equals mid."""
        mid = 150.0
        for q in [-500, 0, 500]:
            r = compute_reservation_price(
                mid_price=mid,
                inventory=q,
                risk_aversion=0.0,
                volatility=0.05,
                horizon=1.0,
            )
            assert math.isclose(r, mid, rel_tol=1e-12)

    def test_volatility_and_horizon_scaling(self) -> None:
        """Reservation penalty scales quadratically with volatility and linearly with horizon."""
        mid = 50.0
        q = 200
        gamma = 0.1

        # Double volatility -> 4x penalty
        r_base = compute_reservation_price(
            mid_price=mid, inventory=q, risk_aversion=gamma, volatility=0.01, horizon=1.0
        )
        r_double_vol = compute_reservation_price(
            mid_price=mid, inventory=q, risk_aversion=gamma, volatility=0.02, horizon=1.0
        )
        pen_base = mid - r_base
        pen_double_vol = mid - r_double_vol
        assert math.isclose(pen_double_vol / pen_base, 4.0, rel_tol=1e-9)

        # Triple horizon -> 3x penalty
        r_triple_tau = compute_reservation_price(
            mid_price=mid, inventory=q, risk_aversion=gamma, volatility=0.01, horizon=3.0
        )
        pen_triple_tau = mid - r_triple_tau
        assert math.isclose(pen_triple_tau / pen_base, 3.0, rel_tol=1e-9)

    def test_invalid_parameters_raise_errors(self) -> None:
        """Negative, non-finite, and invalid types must raise ValueError or TypeError."""
        with pytest.raises(ValueError, match="mid_price must be positive"):
            compute_reservation_price(-10.0, 0, 0.1, 0.02, 1.0)

        with pytest.raises(ValueError, match="mid_price must be positive"):
            compute_reservation_price(0.0, 0, 0.1, 0.02, 1.0)

        with pytest.raises(ValueError, match="mid_price must be positive and finite"):
            compute_reservation_price(float("nan"), 0, 0.1, 0.02, 1.0)

        with pytest.raises(TypeError, match="inventory must be an integer"):
            compute_reservation_price(100.0, "10", 0.1, 0.02, 1.0)  # type: ignore

        with pytest.raises(ValueError, match="risk_aversion cannot be negative"):
            compute_reservation_price(100.0, 0, -0.1, 0.02, 1.0)

        with pytest.raises(ValueError, match="volatility cannot be negative"):
            compute_reservation_price(100.0, 0, 0.1, -0.02, 1.0)

        with pytest.raises(ValueError, match="horizon cannot be negative"):
            compute_reservation_price(100.0, 0, 0.1, 0.02, -1.0)


class TestOptimalSpread:
    """Tests for optimal spread calculation."""

    def test_optimal_half_spread_formula(self) -> None:
        """Verify delta* = (1 / gamma) * ln(1 + gamma / kappa)."""
        gamma = 0.1
        kappa = 1.5
        min_s = 0.01
        max_s = 1.0

        expected = (1.0 / gamma) * math.log(1.0 + gamma / kappa)
        result = compute_optimal_half_spread(gamma, kappa, min_s, max_s)
        assert math.isclose(result, expected, rel_tol=1e-12)

    def test_optimal_spread_clamping(self) -> None:
        """Optimal spread is clamped between min and max bounds."""
        # Extreme high gamma
        result_max = compute_optimal_half_spread(
            risk_aversion=0.0001,
            order_arrival_intensity=0.0001,
            min_half_spread=0.01,
            max_half_spread=0.50,
        )
        assert result_max == 0.50

        # High kappa
        result_min = compute_optimal_half_spread(
            risk_aversion=0.1,
            order_arrival_intensity=1000.0,
            min_half_spread=0.02,
            max_half_spread=0.50,
        )
        assert result_min == 0.02

    def test_optimal_spread_zero_risk_aversion(self) -> None:
        """As gamma -> 0, delta* -> 1 / kappa."""
        kappa = 2.0
        result = compute_optimal_half_spread(0.0, kappa, 0.01, 1.0)
        assert math.isclose(result, 1.0 / kappa, rel_tol=1e-12)


class TestTickRoundingAndQuoteConstruction:
    """Tests for tick rounding and quote invariants."""

    def test_round_to_tick_bids_round_down_asks_round_up(self) -> None:
        """Bids round downward and Asks round upward to preserve queue passivity."""
        tick_size = 0.01
        price_scale = 100.0

        # Raw price 100.054
        bid_ticks, bid_dlrs = round_to_tick(100.054, OrderSide.BUY, tick_size, price_scale)
        assert bid_ticks == 10005
        assert math.isclose(bid_dlrs, 100.05, rel_tol=1e-9)

        ask_ticks, ask_dlrs = round_to_tick(100.054, OrderSide.SELL, tick_size, price_scale)
        assert ask_ticks == 10006
        assert math.isclose(ask_dlrs, 100.06, rel_tol=1e-9)

    def test_exact_tick_boundary(self) -> None:
        """Exact tick boundaries remain unchanged."""
        tick_size = 0.05
        price_scale = 100.0

        bid_ticks, bid_dlrs = round_to_tick(25.50, OrderSide.BUY, tick_size, price_scale)
        ask_ticks, ask_dlrs = round_to_tick(25.50, OrderSide.SELL, tick_size, price_scale)

        assert bid_ticks == 2550
        assert ask_ticks == 2550
        assert math.isclose(bid_dlrs, 25.50, rel_tol=1e-9)
        assert math.isclose(ask_dlrs, 25.50, rel_tol=1e-9)

    def test_build_raw_quotes_enforces_bid_less_than_ask(self) -> None:
        """build_raw_quotes guarantees bid price < ask price strictly."""
        config = MarketMakingConfig(
            instrument_id=1,
            tick_size=0.01,
            price_scale=100.0,
            half_spread=0.001,  # Sub-tick half spread
            quote_size=100,
        )

        bid_quote, ask_quote = build_raw_quotes(
            mid_price=10.0,
            reservation_price=10.0,
            half_spread=0.001,
            config=config,
        )

        assert bid_quote.price_ticks < ask_quote.price_ticks
        assert bid_quote.price_dollars < ask_quote.price_dollars
        assert ask_quote.price_ticks - bid_quote.price_ticks >= 1

    def test_inventory_skewed_quotes(self) -> None:
        """Quotes constructed under long inventory shift downward relative to mid."""
        config = MarketMakingConfig(
            instrument_id=1,
            tick_size=0.01,
            price_scale=100.0,
            half_spread=0.05,
            quote_size=100,
            risk_aversion=0.1,
            volatility=0.05,
            terminal_horizon=1.0,
        )

        mid = 100.0
        # Long inventory
        r_long = compute_reservation_price(mid, 200, config.risk_aversion, config.volatility, 1.0)
        bid_long, ask_long = build_raw_quotes(mid, r_long, 0.05, config)

        # Flat inventory
        r_flat = compute_reservation_price(mid, 0, config.risk_aversion, config.volatility, 1.0)
        bid_flat, ask_flat = build_raw_quotes(mid, r_flat, 0.05, config)

        # Under long inventory, both bid and ask are lower than under flat
        assert bid_long.price_ticks < bid_flat.price_ticks
        assert ask_long.price_ticks < ask_flat.price_ticks
        # Ask is closer to mid (more competitive to sell)
        assert ask_long.distance_from_mid < ask_flat.distance_from_mid
        # Bid is further from mid (less aggressive to buy)
        assert bid_long.distance_from_mid > bid_flat.distance_from_mid
