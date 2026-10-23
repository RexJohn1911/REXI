"""Data models, enums, dataclasses, and temporal validation for REXI Strategy Laboratory."""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from research.leakage.exceptions import TemporalOrderError, TimestampSafetyError


class OrderSide(str, Enum):
    """Side of the order."""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Execution type of the order.

    Scope Note:
    Stage 2 backtester strictly simulates MARKET orders (crossing prevailing BBO).
    LIMIT is defined here for interface completeness and will be supported when
    passive execution modeling is added in later phases.
    """

    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(str, Enum):
    """Time in force policy for order execution."""

    IOC = "ioc"  # Immediate or Cancel
    GTC = "gtc"  # Good 'til Canceled
    DAY = "day"  # Valid for current trading day session


def validate_temporal_coordinates(
    event_timestamp_ns: int,
    available_timestamp_ns: int,
    decision_timestamp_ns: int,
    actionable_timestamp_ns: int,
    fill_timestamp_ns: int,
) -> None:
    """Validate strict causal ordering of the 5-point execution temporal chain.

    Enforces:
    T_event <= T_available <= T_decision <= T_actionable <= T_fill

    Permitted Boundary Conditions:
    - Zero local processing latency: T_event == T_available.
    - Zero decision latency: T_available == T_decision.
    - Zero network transport latency: T_decision == T_actionable.
    - Immediate matching fill: T_actionable == T_fill.

    Prohibited Inversions:
    - T_event > T_available: physical causality violation (event seen before it occurred).
    - T_available > T_decision: lookahead violation (decision made before features ready).
    - T_decision > T_actionable: order arrival violation (order at exchange before decision).
    - T_actionable > T_fill: fill violation (fill occurred before order was actionable).

    Raises:
    - TimestampSafetyError: if any timestamp is not a 64-bit signed integer.
    - TemporalOrderError: if any chronological inequality is violated.
    """
    coords = [
        ("event_timestamp_ns", event_timestamp_ns),
        ("available_timestamp_ns", available_timestamp_ns),
        ("decision_timestamp_ns", decision_timestamp_ns),
        ("actionable_timestamp_ns", actionable_timestamp_ns),
        ("fill_timestamp_ns", fill_timestamp_ns),
    ]

    for name, ts in coords:
        if not isinstance(ts, int) or isinstance(ts, bool):
            raise TimestampSafetyError(
                f"{name} must be a 64-bit integer, got {type(ts).__name__}"
            )
        if ts < -9_223_372_036_854_775_808 or ts > 9_223_372_036_854_775_807:
            raise TimestampSafetyError(f"{name} out of 64-bit signed integer range: {ts}")

    if event_timestamp_ns > available_timestamp_ns:
        raise TemporalOrderError(
            f"Physical causality violation: event_timestamp_ns ({event_timestamp_ns}) > "
            f"available_timestamp_ns ({available_timestamp_ns}). "
            "Feature cannot be available before the physical event occurred."
        )

    if available_timestamp_ns > decision_timestamp_ns:
        raise TemporalOrderError(
            f"Point-in-time lookahead violation: available_timestamp_ns "
            f"({available_timestamp_ns}) > decision_timestamp_ns ({decision_timestamp_ns}). "
            "Strategy cannot make a decision before features are available in RAM."
        )

    if decision_timestamp_ns > actionable_timestamp_ns:
        raise TemporalOrderError(
            f"Execution causality violation: decision_timestamp_ns ({decision_timestamp_ns}) > "
            f"actionable_timestamp_ns ({actionable_timestamp_ns}). "
            "Order cannot arrive at exchange before the decision was generated."
        )

    if actionable_timestamp_ns > fill_timestamp_ns:
        raise TemporalOrderError(
            f"Fill causality violation: actionable_timestamp_ns ({actionable_timestamp_ns}) > "
            f"fill_timestamp_ns ({fill_timestamp_ns}). "
            "Order cannot execute before it became actionable at the exchange."
        )


@dataclass(frozen=True)
class Signal:
    """Strongly-typed, point-in-time signal emitted by a strategy.

    Semantics:
    - decision_timestamp_ns: Exact nanosecond when the signal was generated.
    - instrument_id: Canonical 64-bit instrument ID.
    - direction: Target direction (-1 = Short, 0 = Flat, +1 = Long).
    - target_weight: Desired portfolio allocation in [-1.0, 1.0].
    - strength: Raw continuous signal strength in [0.0, 1.0].
    - confidence: Statistical confidence or probability in [0.0, 1.0].
    - is_valid: Boolean validity gate. When False, direction must be 0 and target_weight 0.0.
    """

    decision_timestamp_ns: int
    instrument_id: int
    direction: int
    target_weight: float = 0.0
    strength: float = 0.0
    confidence: float = 0.0
    is_valid: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.decision_timestamp_ns, int) or isinstance(
            self.decision_timestamp_ns, bool
        ):
            raise TimestampSafetyError("decision_timestamp_ns must be an integer.")
        if not isinstance(self.instrument_id, int) or isinstance(self.instrument_id, bool):
            raise TypeError("instrument_id must be an integer.")
        if self.direction not in (-1, 0, 1):
            raise ValueError(f"direction must be -1, 0, or 1, got {self.direction}")

        # Finite numeric checks
        for name, val in [
            ("target_weight", self.target_weight),
            ("strength", self.strength),
            ("confidence", self.confidence),
        ]:
            if not isinstance(val, int | float) or isinstance(val, bool) or not math.isfinite(val):
                raise ValueError(f"{name} must be a finite float, got {val}")

        if not (-1.0 <= self.target_weight <= 1.0):
            raise ValueError(f"target_weight must be in [-1.0, 1.0], got {self.target_weight}")
        if not (0.0 <= self.strength <= 1.0):
            raise ValueError(f"strength must be in [0.0, 1.0], got {self.strength}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")

        # Invariant: Invalid signal cannot request non-zero exposure
        if not self.is_valid:
            if self.direction != 0 or self.target_weight != 0.0:
                raise ValueError(
                    f"Invalid signal (is_valid=False) must be Flat: direction=0, target_weight=0.0 "
                    f"(got direction={self.direction}, target_weight={self.target_weight})"
                )

        # Invariant: Direction and target_weight must be mutually consistent
        if self.direction == 0 and self.target_weight != 0.0:
            raise ValueError(
                f"direction=0 (Flat) requires target_weight=0.0, got {self.target_weight}"
            )
        elif self.direction == 1 and self.target_weight <= 0.0:
            raise ValueError(
                f"direction=1 (Long) requires target_weight > 0.0, got {self.target_weight}"
            )
        elif self.direction == -1 and self.target_weight >= 0.0:
            raise ValueError(
                f"direction=-1 (Short) requires target_weight < 0.0, got {self.target_weight}"
            )


@dataclass(frozen=True)
class OrderIntent:
    """Order instructions emitted from a strategy signal to the backtest execution engine."""

    order_id: str
    decision_timestamp_ns: int
    actionable_timestamp_ns: int
    instrument_id: int
    side: OrderSide
    order_type: OrderType
    quantity: int
    limit_price: int | None = None
    time_in_force: TimeInForce = TimeInForce.IOC
    signal_event_timestamp_ns: int | None = None
    signal_available_timestamp_ns: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.order_id, str) or not self.order_id.strip():
            raise ValueError("order_id must be a non-empty string.")
        if not isinstance(self.decision_timestamp_ns, int) or not isinstance(
            self.actionable_timestamp_ns, int
        ):
            raise TimestampSafetyError("Timestamps must be integers.")
        if self.actionable_timestamp_ns < self.decision_timestamp_ns:
            raise TemporalOrderError(
                f"actionable_timestamp_ns ({self.actionable_timestamp_ns}) < "
                f"decision_timestamp_ns ({self.decision_timestamp_ns})"
            )
        if self.signal_event_timestamp_ns is not None:
            if not isinstance(self.signal_event_timestamp_ns, int) or isinstance(
                self.signal_event_timestamp_ns, bool
            ):
                raise TimestampSafetyError("signal_event_timestamp_ns must be an integer.")
            if self.signal_event_timestamp_ns > self.decision_timestamp_ns:
                raise TemporalOrderError("signal_event_timestamp_ns > decision_timestamp_ns")
        if self.signal_available_timestamp_ns is not None:
            if not isinstance(self.signal_available_timestamp_ns, int) or isinstance(
                self.signal_available_timestamp_ns, bool
            ):
                raise TimestampSafetyError("signal_available_timestamp_ns must be an integer.")
            if self.signal_available_timestamp_ns > self.decision_timestamp_ns:
                raise TemporalOrderError("signal_available_timestamp_ns > decision_timestamp_ns")
        if (
            not isinstance(self.quantity, int)
            or isinstance(self.quantity, bool)
            or self.quantity <= 0
        ):
            raise ValueError(f"Order quantity must be a positive integer, got {self.quantity}")

        if self.order_type == OrderType.LIMIT:
            if (
                self.limit_price is None
                or not isinstance(self.limit_price, int)
                or isinstance(self.limit_price, bool)
                or self.limit_price <= 0
            ):
                raise ValueError(
                    f"Limit order requires a positive integer limit_price, got {self.limit_price}"
                )
        elif self.order_type == OrderType.MARKET:
            if self.limit_price is not None:
                raise ValueError(
                    f"Market orders cannot specify limit_price, got {self.limit_price}"
                )


@dataclass(frozen=True)
class FillRecord:
    """Immutable record of an executed trade fill."""

    fill_id: str
    order_id: str
    fill_timestamp_ns: int
    instrument_id: int
    side: OrderSide
    quantity: int
    price: int  # Fixed-point integer price (e.g. cents or 10^-4)
    spread_cost: float = 0.0
    slippage_cost: float = 0.0
    exchange_fee: float = 0.0
    regulatory_fee: float = 0.0
    is_passive: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.fill_id, str) or not self.fill_id.strip():
            raise ValueError("fill_id must be a non-empty string.")
        if not isinstance(self.order_id, str) or not self.order_id.strip():
            raise ValueError("order_id must be a non-empty string.")
        if not isinstance(self.fill_timestamp_ns, int) or isinstance(
            self.fill_timestamp_ns, bool
        ):
            raise TimestampSafetyError("fill_timestamp_ns must be an integer.")
        if (
            not isinstance(self.quantity, int)
            or isinstance(self.quantity, bool)
            or self.quantity <= 0
        ):
            raise ValueError(f"Fill quantity must be a positive integer, got {self.quantity}")
        if not isinstance(self.price, int) or isinstance(self.price, bool) or self.price <= 0:
            raise ValueError(f"Fill price must be a positive integer, got {self.price}")

        # Cost sanity checks
        costs = [
            ("spread_cost", self.spread_cost),
            ("slippage_cost", self.slippage_cost),
            ("exchange_fee", self.exchange_fee),
            ("regulatory_fee", self.regulatory_fee),
        ]
        for name, val in costs:
            if not isinstance(val, int | float) or isinstance(val, bool) or not math.isfinite(val):
                raise ValueError(f"{name} must be a finite float, got {val}")

        if self.spread_cost < 0.0:
            raise ValueError(f"spread_cost cannot be negative, got {self.spread_cost}")
        if self.slippage_cost < 0.0:
            raise ValueError(f"slippage_cost cannot be negative, got {self.slippage_cost}")
        if self.regulatory_fee < 0.0:
            raise ValueError(f"regulatory_fee cannot be negative, got {self.regulatory_fee}")

    @property
    def total_transaction_cost(self) -> float:
        """Total transaction friction (spread + slippage + exchange fees + regulatory fees)."""
        return self.spread_cost + self.slippage_cost + self.exchange_fee + self.regulatory_fee


@dataclass
class PositionState:
    """Mutable portfolio position state tracked by the backtest engine."""

    instrument_id: int
    quantity: int = 0
    average_entry_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_fees_paid: float = 0.0
    last_update_timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, int) or isinstance(self.instrument_id, bool):
            raise TypeError("instrument_id must be an integer.")
        if not isinstance(self.quantity, int) or isinstance(self.quantity, bool):
            raise TypeError("quantity must be an integer.")
        for name, val in [
            ("average_entry_price", self.average_entry_price),
            ("realized_pnl", self.realized_pnl),
            ("unrealized_pnl", self.unrealized_pnl),
            ("total_fees_paid", self.total_fees_paid),
        ]:
            if not isinstance(val, int | float) or isinstance(val, bool) or not math.isfinite(val):
                raise ValueError(f"{name} must be a finite float, got {val}")
        if self.average_entry_price < 0.0:
            raise ValueError(
                f"average_entry_price cannot be negative, got {self.average_entry_price}"
            )

    @property
    def is_flat(self) -> bool:
        """True if position is zero."""
        return self.quantity == 0

    @property
    def is_long(self) -> bool:
        """True if position is positive."""
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        """True if position is negative."""
        return self.quantity < 0
