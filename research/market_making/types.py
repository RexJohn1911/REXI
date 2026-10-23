"""Domain types, dataclasses, enums, and configurations for Market Making Engine."""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from research.leakage.exceptions import TemporalOrderError, TimestampSafetyError
from research.strategies.types import OrderSide, PositionState


class QuoteSuppressionReason(str, Enum):
    """Reason a market-maker quote or side is suppressed or rejected."""

    NONE = "none"
    INVALID_MARKET_DATA = "invalid_market_data"
    CROSSED_OR_LOCKED_BOOK = "crossed_or_locked_book"
    STALE_MARKET_DATA = "stale_market_data"
    EXCESSIVE_SPREAD = "excessive_spread"
    INSUFFICIENT_DEPTH = "insufficient_depth"
    EXCESSIVE_VOLATILITY = "excessive_volatility"
    MICROSTRUCTURE_IMBALANCE = "microstructure_imbalance"
    LONG_INVENTORY_LIMIT = "long_inventory_limit"
    SHORT_INVENTORY_LIMIT = "short_inventory_limit"
    MAX_NOTIONAL_EXPOSURE = "max_notional_exposure"
    INVALID_RESERVATION_PRICE = "invalid_reservation_price"
    PRICE_CROSSING_RISK = "price_crossing_risk"
    RISK_REDUCTION_ONLY = "risk_reduction_only"


@dataclass(frozen=True)
class MarketQuoteSnapshot:
    """Validated top-of-book market data snapshot for market-making decisions.

    All prices are represented in integer price units (ticks/cents) according
    to the instrument's price_scale, and mid_price / spread are in dollars.
    """

    instrument_id: int
    event_timestamp_ns: int
    available_timestamp_ns: int
    best_bid_price: int
    best_bid_quantity: int
    best_ask_price: int
    best_ask_quantity: int
    price_scale: float = 100.0
    is_valid: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, int) or isinstance(self.instrument_id, bool):
            raise TypeError("instrument_id must be an integer.")
        if not isinstance(self.event_timestamp_ns, int) or isinstance(
            self.event_timestamp_ns, bool
        ):
            raise TimestampSafetyError("event_timestamp_ns must be an integer.")
        if not isinstance(self.available_timestamp_ns, int) or isinstance(
            self.available_timestamp_ns, bool
        ):
            raise TimestampSafetyError("available_timestamp_ns must be an integer.")
        if self.event_timestamp_ns > self.available_timestamp_ns:
            raise TemporalOrderError(
                f"event_timestamp_ns ({self.event_timestamp_ns}) > "
                f"available_timestamp_ns ({self.available_timestamp_ns})"
            )
        if not isinstance(self.price_scale, int | float) or self.price_scale <= 0.0:
            raise ValueError(f"price_scale must be positive, got {self.price_scale}")

        # Integer price and quantity validations
        for name, val in [
            ("best_bid_price", self.best_bid_price),
            ("best_ask_price", self.best_ask_price),
            ("best_bid_quantity", self.best_bid_quantity),
            ("best_ask_quantity", self.best_ask_quantity),
        ]:
            if not isinstance(val, int) or isinstance(val, bool):
                raise TypeError(f"{name} must be an integer, got {type(val).__name__}")

        if self.best_bid_price <= 0 or self.best_ask_price <= 0:
            raise ValueError("Prices must be strictly positive.")
        if self.best_bid_quantity <= 0 or self.best_ask_quantity <= 0:
            raise ValueError("Quantities must be strictly positive.")

    @property
    def is_crossed_or_locked(self) -> bool:
        """True if market book is crossed or locked."""
        return self.best_bid_price >= self.best_ask_price

    @property
    def bid_dollars(self) -> float:
        """Best bid price in dollars."""
        return self.best_bid_price / self.price_scale

    @property
    def ask_dollars(self) -> float:
        """Best ask price in dollars."""
        return self.best_ask_price / self.price_scale

    @property
    def mid_dollars(self) -> float:
        """Arithmetic mid-price in dollars."""
        return (self.bid_dollars + self.ask_dollars) / 2.0

    @property
    def spread_dollars(self) -> float:
        """Top-of-book bid/ask spread in dollars."""
        return self.ask_dollars - self.bid_dollars


@dataclass(frozen=True)
class InventoryState:
    """Current inventory and risk exposure state of the market maker."""

    instrument_id: int
    inventory: int  # Signed position quantity (positive = Long, negative = Short, 0 = Flat)
    cash: float = 1_000_000.0
    average_entry_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    last_update_timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, int) or isinstance(self.instrument_id, bool):
            raise TypeError("instrument_id must be an integer.")
        if not isinstance(self.inventory, int) or isinstance(self.inventory, bool):
            raise TypeError("inventory must be an integer.")
        for name, val in [
            ("cash", self.cash),
            ("average_entry_price", self.average_entry_price),
            ("realized_pnl", self.realized_pnl),
            ("unrealized_pnl", self.unrealized_pnl),
        ]:
            if not isinstance(val, int | float) or isinstance(val, bool) or not math.isfinite(val):
                raise ValueError(f"{name} must be a finite float, got {val}")
        if self.average_entry_price < 0.0:
            raise ValueError("average_entry_price cannot be negative.")

    @property
    def is_flat(self) -> bool:
        """True if position is zero."""
        return self.inventory == 0

    @property
    def is_long(self) -> bool:
        """True if position is positive."""
        return self.inventory > 0

    @property
    def is_short(self) -> bool:
        """True if position is negative."""
        return self.inventory < 0

    def notional_exposure(self, mid_price: float) -> float:
        """Total absolute notional exposure in dollars."""
        if not math.isfinite(mid_price) or mid_price <= 0.0:
            raise ValueError(f"mid_price must be positive and finite, got {mid_price}")
        return abs(self.inventory) * mid_price

    @classmethod
    def from_position_state(
        cls, pos: PositionState, cash: float = 1_000_000.0
    ) -> "InventoryState":
        """Construct an InventoryState from a Phase 11 PositionState."""
        return cls(
            instrument_id=pos.instrument_id,
            inventory=pos.quantity,
            cash=cash,
            average_entry_price=pos.average_entry_price,
            realized_pnl=pos.realized_pnl,
            unrealized_pnl=pos.unrealized_pnl,
            last_update_timestamp_ns=pos.last_update_timestamp_ns,
        )


@dataclass(frozen=True)
class QuoteIntent:
    """Individual quote proposal for one side of the market (Bid or Ask)."""

    side: OrderSide
    price_ticks: int  # Integer price in price_scale ticks
    price_dollars: float  # Price in dollars
    quantity: int  # Proposed order quantity in shares
    distance_from_mid: float  # Distance from mid in dollars
    is_post_only: bool = True  # Passive quoting intent
    is_suppressed: bool = False
    suppression_reason: QuoteSuppressionReason = QuoteSuppressionReason.NONE

    def __post_init__(self) -> None:
        if not isinstance(self.side, OrderSide):
            raise TypeError(f"side must be an OrderSide enum, got {type(self.side).__name__}")
        if not isinstance(self.price_ticks, int) or isinstance(self.price_ticks, bool):
            raise TypeError("price_ticks must be an integer.")
        if not isinstance(self.quantity, int) or isinstance(self.quantity, bool):
            raise TypeError("quantity must be an integer.")
        for name, val in [
            ("price_dollars", self.price_dollars),
            ("distance_from_mid", self.distance_from_mid),
        ]:
            if not isinstance(val, int | float) or isinstance(val, bool) or not math.isfinite(val):
                raise ValueError(f"{name} must be a finite float, got {val}")

        if not self.is_suppressed:
            if self.price_ticks <= 0 or self.price_dollars <= 0.0:
                raise ValueError("Active quote price must be strictly positive.")
            if self.quantity <= 0:
                raise ValueError("Active quote quantity must be strictly positive.")


@dataclass(frozen=True)
class QuoteDecision:
    """Comprehensive, deterministic quoting decision emitted by the Market Making Engine."""

    decision_timestamp_ns: int
    instrument_id: int
    mid_price: float
    reservation_price: float
    target_half_spread: float
    inventory: int
    bid_quote: QuoteIntent
    ask_quote: QuoteIntent
    is_valid: bool = True
    suppression_reasons: list[QuoteSuppressionReason] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.decision_timestamp_ns, int) or isinstance(
            self.decision_timestamp_ns, bool
        ):
            raise TimestampSafetyError("decision_timestamp_ns must be an integer.")
        if not isinstance(self.instrument_id, int) or isinstance(self.instrument_id, bool):
            raise TypeError("instrument_id must be an integer.")
        for name, val in [
            ("mid_price", self.mid_price),
            ("reservation_price", self.reservation_price),
            ("target_half_spread", self.target_half_spread),
        ]:
            if not isinstance(val, int | float) or isinstance(val, bool) or not math.isfinite(val):
                raise ValueError(f"{name} must be a finite float, got {val}")

        if not isinstance(self.inventory, int) or isinstance(self.inventory, bool):
            raise TypeError("inventory must be an integer.")

        # Invariant: If both sides are active, bid price must be strictly less than ask price
        if not self.bid_quote.is_suppressed and not self.ask_quote.is_suppressed:
            if self.bid_quote.price_ticks >= self.ask_quote.price_ticks:
                raise ValueError(
                    f"Crossed/locked quote generated: bid {self.bid_quote.price_ticks} >= "
                    f"ask {self.ask_quote.price_ticks}"
                )

    @property
    def has_active_bid(self) -> bool:
        """True if the bid quote is active and unsuppressed."""
        return not self.bid_quote.is_suppressed and self.is_valid

    @property
    def has_active_ask(self) -> bool:
        """True if the ask quote is active and unsuppressed."""
        return not self.ask_quote.is_suppressed and self.is_valid

    @property
    def is_two_sided(self) -> bool:
        """True if both bid and ask quotes are active and unsuppressed."""
        return self.has_active_bid and self.has_active_ask


@dataclass(frozen=True)
class MarketMakingConfig:
    """Configuration parameters and risk thresholds for Market Making Engine."""

    instrument_id: int
    tick_size: float = 0.01  # Minimum price increment in dollars ($0.01 for U.S. equities)
    price_scale: float = 100.0  # Ticks per dollar (e.g. 100.0 for cents)
    quote_size: int = 100  # Default quote quantity in shares
    min_quote_size: int = 1
    max_quote_size: int = 10_000

    # Avellaneda-Stoikov parameters
    risk_aversion: float = 0.1  # gamma > 0 (CARA risk aversion parameter)
    volatility: float = 0.02  # sigma >= 0 (annualized, daily, or scaled price volatility)
    terminal_horizon: float = 1.0  # tau > 0 (remaining horizon time unit)
    half_spread: float = 0.05  # delta_0 (target baseline half-spread in dollars)
    min_half_spread: float = 0.01  # Minimum allowable half-spread
    max_half_spread: float = 1.0  # Maximum allowable half-spread
    order_arrival_intensity: float = 1.5  # kappa (Poisson order arrival intensity parameter)
    use_optimal_spread: bool = False  # If True, use Avellaneda-Stoikov closed-form spread

    # Inventory limits and skew
    max_long_inventory: int = 1000  # Maximum long position in shares
    max_short_inventory: int = 1000  # Maximum short position in shares
    max_notional_exposure: float = 100_000.0  # Maximum portfolio notional in dollars
    skew_factor: float = 1.0  # Scaling multiplier for inventory penalty
    inventory_limit_soft_threshold: float = 0.9  # Fraction of limit triggering cautious quoting
    risk_reduction_only: bool = False  # When True, only allow quotes that reduce inventory

    # Adverse-selection & market-quality guards
    stale_quote_timeout_ns: int = 5_000_000_000  # 5.0 seconds (0 disables staleness guard)
    max_market_spread: float = 2.0  # Maximum prevailing market spread in dollars
    min_displayed_depth: int = 100  # Minimum prevailing displayed depth in shares (0 disables)
    max_volatility: float = 0.50  # Maximum allowable volatility (0 disables)
    max_ofi_magnitude: float = 10_000.0  # Maximum Order Flow Imbalance magnitude (0 disables)
    max_depth_imbalance: float = 0.90  # Maximum Depth Imbalance magnitude (0 disables)
    max_vpin: float = 0.80  # Maximum VPIN toxicity (0 disables)
    require_microstructure_validity: bool = False  # Require feature flags when guards enabled

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, int) or isinstance(self.instrument_id, bool):
            raise TypeError("instrument_id must be an integer.")

        float_fields = [
            ("tick_size", self.tick_size),
            ("price_scale", self.price_scale),
            ("risk_aversion", self.risk_aversion),
            ("volatility", self.volatility),
            ("terminal_horizon", self.terminal_horizon),
            ("half_spread", self.half_spread),
            ("min_half_spread", self.min_half_spread),
            ("max_half_spread", self.max_half_spread),
            ("order_arrival_intensity", self.order_arrival_intensity),
            ("max_notional_exposure", self.max_notional_exposure),
            ("skew_factor", self.skew_factor),
            ("inventory_limit_soft_threshold", self.inventory_limit_soft_threshold),
            ("max_market_spread", self.max_market_spread),
            ("max_volatility", self.max_volatility),
            ("max_ofi_magnitude", self.max_ofi_magnitude),
            ("max_depth_imbalance", self.max_depth_imbalance),
            ("max_vpin", self.max_vpin),
        ]
        for name, val in float_fields:
            if not isinstance(val, int | float) or isinstance(val, bool) or not math.isfinite(val):
                raise ValueError(f"{name} must be a finite float, got {val}")

        int_fields = [
            ("quote_size", self.quote_size),
            ("min_quote_size", self.min_quote_size),
            ("max_quote_size", self.max_quote_size),
            ("max_long_inventory", self.max_long_inventory),
            ("max_short_inventory", self.max_short_inventory),
            ("stale_quote_timeout_ns", self.stale_quote_timeout_ns),
            ("min_displayed_depth", self.min_displayed_depth),
        ]
        for name, ival in int_fields:
            if not isinstance(ival, int) or isinstance(ival, bool):
                raise TypeError(f"{name} must be an integer, got {type(ival).__name__}")

        if self.tick_size <= 0.0:
            raise ValueError("tick_size must be positive.")
        if self.price_scale <= 0.0:
            raise ValueError("price_scale must be positive.")
        if self.quote_size <= 0:
            raise ValueError("quote_size must be positive.")
        if self.min_quote_size <= 0:
            raise ValueError("min_quote_size must be positive.")
        if self.max_quote_size < self.min_quote_size:
            raise ValueError("max_quote_size cannot be less than min_quote_size.")
        if not (self.min_quote_size <= self.quote_size <= self.max_quote_size):
            raise ValueError("quote_size must be between min_quote_size and max_quote_size.")
        if self.risk_aversion < 0.0:
            raise ValueError("risk_aversion cannot be negative.")
        if self.volatility < 0.0:
            raise ValueError("volatility cannot be negative.")
        if self.terminal_horizon < 0.0:
            raise ValueError("terminal_horizon cannot be negative.")
        if self.half_spread <= 0.0:
            raise ValueError("half_spread must be positive.")
        if self.min_half_spread <= 0.0:
            raise ValueError("min_half_spread must be positive.")
        if self.max_half_spread < self.min_half_spread:
            raise ValueError("max_half_spread cannot be less than min_half_spread.")
        if self.order_arrival_intensity <= 0.0:
            raise ValueError("order_arrival_intensity must be positive.")
        if self.max_long_inventory < 0 or self.max_short_inventory < 0:
            raise ValueError("Inventory limits cannot be negative.")
        if self.max_notional_exposure <= 0.0:
            raise ValueError("max_notional_exposure must be positive.")
        if not (0.0 < self.inventory_limit_soft_threshold <= 1.0):
            raise ValueError("inventory_limit_soft_threshold must be in (0.0, 1.0].")
        if self.skew_factor < 0.0:
            raise ValueError("skew_factor cannot be negative.")
        if self.max_market_spread <= 0.0:
            raise ValueError("max_market_spread must be positive.")
        if self.stale_quote_timeout_ns < 0:
            raise ValueError("stale_quote_timeout_ns cannot be negative.")
