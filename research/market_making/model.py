"""Quantitative reservation price and optimal spread models for Market Making Engine.

Mathematical Framework:
Implements the Avellaneda-Stoikov (2008) market-making framework for high-frequency
quote generation under inventory risk.

1. Reservation Price:
   r(s, q, tau) = s - q * gamma * sigma^2 * tau

   Dimensional Analysis & Units:
   - s: Mid-price in dollars ($)
   - q: Current inventory in shares (q > 0 for Long, q < 0 for Short, 0 for Flat)
   - gamma: Absolute risk-aversion parameter (1 / ($ * shares))
   - sigma: Price volatility ($ / sqrt(unit_time))
   - sigma^2: Price variance ($^2 / unit_time)
   - tau: Remaining investment horizon in unit_time
   - Penalty term: q * gamma * sigma^2 * tau has units of dollars ($).

   Directional Inventory Invariants:
   - Positive Inventory (q > 0, Long): r < s. The reservation price shifts downward,
     attracting buyers by posting a lower, more competitive ask, and discouraging
     further long accumulation by posting a lower bid.
   - Negative Inventory (q < 0, Short): r > s. The reservation price shifts upward,
     attracting sellers by posting a higher bid to cover short inventory, and discouraging
     further short sales by posting a higher ask.
   - Zero Inventory (q = 0, Flat): r = s. Quotations are symmetric around the mid-price.

2. Optimal Spread (Closed-Form Avellaneda-Stoikov):
   delta*(s) = (1 / gamma) * ln(1 + gamma / kappa)
   where kappa is the order arrival intensity parameter.
"""

import math

from research.market_making.types import (
    MarketMakingConfig,
    QuoteIntent,
    QuoteSuppressionReason,
)
from research.strategies.types import OrderSide


def compute_reservation_price(
    mid_price: float,
    inventory: int,
    risk_aversion: float,
    volatility: float,
    horizon: float,
    skew_factor: float = 1.0,
) -> float:
    """Compute the Avellaneda-Stoikov inventory-adjusted reservation price.

    r(s, q, tau) = s - q * gamma * sigma^2 * tau * skew_factor

    Parameters:
    - mid_price: Current market mid-price in dollars (must be positive and finite).
    - inventory: Signed position in shares (q > 0 for Long, q < 0 for Short).
    - risk_aversion: CARA risk-aversion parameter gamma >= 0.
    - volatility: Price volatility sigma >= 0.
    - horizon: Effective remaining time horizon tau >= 0.
    - skew_factor: Multiplier for inventory sensitivity >= 0.

    Returns:
    - Reservation price in dollars.
    """
    if not isinstance(mid_price, int | float) or not math.isfinite(mid_price) or mid_price <= 0.0:
        raise ValueError(f"mid_price must be positive and finite, got {mid_price}")
    if not isinstance(inventory, int) or isinstance(inventory, bool):
        raise TypeError(f"inventory must be an integer, got {type(inventory).__name__}")

    for name, val in [
        ("risk_aversion", risk_aversion),
        ("volatility", volatility),
        ("horizon", horizon),
        ("skew_factor", skew_factor),
    ]:
        if not isinstance(val, int | float) or isinstance(val, bool) or not math.isfinite(val):
            raise ValueError(f"{name} must be a finite float, got {val}")
        if val < 0.0:
            raise ValueError(f"{name} cannot be negative, got {val}")

    variance = volatility * volatility
    inventory_penalty = inventory * risk_aversion * variance * horizon * skew_factor
    reservation_price = mid_price - inventory_penalty

    if not math.isfinite(reservation_price) or reservation_price <= 0.0:
        raise ValueError(
            f"Reservation price became non-positive or non-finite: {reservation_price} "
            f"(mid={mid_price}, inv={inventory}, penalty={inventory_penalty})"
        )

    return reservation_price


def compute_optimal_half_spread(
    risk_aversion: float,
    order_arrival_intensity: float,
    min_half_spread: float,
    max_half_spread: float,
) -> float:
    """Compute optimal half-spread delta* based on order arrival intensity kappa.

    delta* = (1 / gamma) * ln(1 + gamma / kappa)
    As gamma -> 0, delta* -> 1 / kappa.

    Clamped strictly between min_half_spread and max_half_spread.
    """
    for name, val in [
        ("risk_aversion", risk_aversion),
        ("order_arrival_intensity", order_arrival_intensity),
        ("min_half_spread", min_half_spread),
        ("max_half_spread", max_half_spread),
    ]:
        if not isinstance(val, int | float) or isinstance(val, bool) or not math.isfinite(val):
            raise ValueError(f"{name} must be a finite float, got {val}")

    if risk_aversion < 0.0:
        raise ValueError("risk_aversion cannot be negative.")
    if order_arrival_intensity <= 0.0:
        raise ValueError("order_arrival_intensity must be positive.")
    if min_half_spread <= 0.0:
        raise ValueError("min_half_spread must be positive.")
    if max_half_spread < min_half_spread:
        raise ValueError("max_half_spread cannot be less than min_half_spread.")

    if risk_aversion == 0.0:
        raw_half_spread = 1.0 / order_arrival_intensity
    else:
        arg = 1.0 + (risk_aversion / order_arrival_intensity)
        raw_half_spread = (1.0 / risk_aversion) * math.log(arg)

    return max(min_half_spread, min(max_half_spread, raw_half_spread))


def round_to_tick(
    price_dollars: float,
    side: OrderSide,
    tick_size: float,
    price_scale: float,
) -> tuple[int, float]:
    """Round a raw quote price to the instrument's tick size according to quoting side.

    To maintain passive queue priority and prevent accidental crossing:
    - Buy (Bid) quotes round downward: floor(p / tick_size) * tick_size
    - Sell (Ask) quotes round upward: ceil(p / tick_size) * tick_size

    Parameters:
    - price_dollars: Raw unrounded price in dollars.
    - side: OrderSide.BUY or OrderSide.SELL.
    - tick_size: Minimum price increment in dollars (e.g. 0.01).
    - price_scale: Fixed-point scaling factor (e.g. 100.0 for cents).

    Returns:
    - (price_ticks, price_dollars)
    """
    if (
        not isinstance(price_dollars, int | float)
        or not math.isfinite(price_dollars)
        or price_dollars <= 0.0
    ):
        raise ValueError(f"price_dollars must be positive and finite, got {price_dollars}")
    if tick_size <= 0.0 or not math.isfinite(tick_size):
        raise ValueError(f"tick_size must be positive and finite, got {tick_size}")
    if price_scale <= 0.0 or not math.isfinite(price_scale):
        raise ValueError(f"price_scale must be positive and finite, got {price_scale}")

    # Calculate tick unit in price_scale (e.g. 0.01 * 100 = 1 tick unit)
    tick_units_in_scale = round(tick_size * price_scale)
    if tick_units_in_scale < 1:
        tick_units_in_scale = 1

    # Raw ticks
    raw_ticks = price_dollars * price_scale

    if side == OrderSide.BUY:
        # Round down for bids
        num_ticks = math.floor(raw_ticks / tick_units_in_scale)
        ticks = int(num_ticks * tick_units_in_scale)
        # Ensure price is at least 1 tick
        if ticks < tick_units_in_scale:
            ticks = tick_units_in_scale
    elif side == OrderSide.SELL:
        # Round up for asks
        num_ticks = math.ceil(raw_ticks / tick_units_in_scale)
        ticks = int(num_ticks * tick_units_in_scale)
        if ticks < tick_units_in_scale:
            ticks = tick_units_in_scale
    else:
        raise ValueError(f"Unsupported OrderSide: {side}")

    rounded_dollars = ticks / price_scale
    return ticks, rounded_dollars


def build_raw_quotes(
    mid_price: float,
    reservation_price: float,
    half_spread: float,
    config: MarketMakingConfig,
    bid_quantity: int | None = None,
    ask_quantity: int | None = None,
) -> tuple[QuoteIntent, QuoteIntent]:
    """Construct rounded, sanity-checked bid and ask QuoteIntent objects.

    Ensures the fundamental invariant:
    p_bid_ticks < p_ask_ticks

    If tick rounding causes bid_ticks >= ask_ticks:
    The ask is widened by at least one tick increment to prevent locking or crossing.
    """
    qty_bid = bid_quantity if bid_quantity is not None else config.quote_size
    qty_ask = ask_quantity if ask_quantity is not None else config.quote_size

    # Raw prices around reservation price
    raw_bid_dollars = reservation_price - half_spread
    raw_ask_dollars = reservation_price + half_spread

    # If raw bid is non-positive, clamp to minimum tick
    if raw_bid_dollars <= 0.0:
        raw_bid_dollars = config.tick_size

    # Round to tick size
    bid_ticks, bid_dollars = round_to_tick(
        price_dollars=raw_bid_dollars,
        side=OrderSide.BUY,
        tick_size=config.tick_size,
        price_scale=config.price_scale,
    )
    ask_ticks, ask_dollars = round_to_tick(
        price_dollars=raw_ask_dollars,
        side=OrderSide.SELL,
        tick_size=config.tick_size,
        price_scale=config.price_scale,
    )

    # Invariant: Bid must be strictly lower than Ask
    tick_in_scale = max(1, round(config.tick_size * config.price_scale))
    if bid_ticks >= ask_ticks:
        # Widen ask to prevent crossed/locked quotes
        ask_ticks = bid_ticks + tick_in_scale
        ask_dollars = ask_ticks / config.price_scale

    bid_dist = mid_price - bid_dollars
    ask_dist = ask_dollars - mid_price

    bid_quote = QuoteIntent(
        side=OrderSide.BUY,
        price_ticks=bid_ticks,
        price_dollars=bid_dollars,
        quantity=qty_bid,
        distance_from_mid=bid_dist,
        is_post_only=True,
        is_suppressed=False,
        suppression_reason=QuoteSuppressionReason.NONE,
    )

    ask_quote = QuoteIntent(
        side=OrderSide.SELL,
        price_ticks=ask_ticks,
        price_dollars=ask_dollars,
        quantity=qty_ask,
        distance_from_mid=ask_dist,
        is_post_only=True,
        is_suppressed=False,
        suppression_reason=QuoteSuppressionReason.NONE,
    )

    return bid_quote, ask_quote
