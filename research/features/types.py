"""Types, configurations, and exceptions for the microstructure feature engine."""

from dataclasses import dataclass
from enum import Enum


class FeatureEngineError(Exception):
    """Base exception for all microstructure feature engine errors."""


class NonMonotonicTimestampError(FeatureEngineError):
    """Raised when an event timestamp is older than the previous event timestamp."""


class InvalidEventDataError(FeatureEngineError):
    """Raised when event attributes violate schema or domain constraints."""


class InsufficientHistoryError(FeatureEngineError):
    """Raised when feature generation is requested before required warm-up is satisfied."""


class AggressorSide(int, Enum):
    """Aggressor side enum matching protocol wire types."""

    BUY = 1
    SELL = 2


@dataclass(frozen=True)
class FeatureEngineConfig:
    """Configuration parameters for microstructure feature calculations."""

    return_lookback: int = 1
    volatility_window: int = 20
    ofi_window: int = 20
    trade_window: int = 20
    roll_window: int = 30
    vpin_bucket_volume: int = 1000
    vpin_num_buckets: int = 20
    depth_levels: int = 5

    def __post_init__(self) -> None:
        if self.return_lookback < 1:
            raise ValueError("return_lookback must be at least 1")
        if self.volatility_window < 2:
            raise ValueError("volatility_window must be at least 2")
        if self.ofi_window < 1:
            raise ValueError("ofi_window must be at least 1")
        if self.trade_window < 1:
            raise ValueError("trade_window must be at least 1")
        if self.roll_window < 3:
            raise ValueError("roll_window must be at least 3")
        if self.vpin_bucket_volume < 1:
            raise ValueError("vpin_bucket_volume must be at least 1")
        if self.vpin_num_buckets < 1:
            raise ValueError("vpin_num_buckets must be at least 1")
        if self.depth_levels < 1:
            raise ValueError("depth_levels must be at least 1")


@dataclass(frozen=True)
class MicrostructureFeatureRecord:
    """Immutable Python record representing a complete microstructure feature state."""

    instrument_id: int
    sequence_num: int
    event_timestamp_ns: int
    source_timestamp_ns: int
    decision_timestamp_ns: int

    # Level 1
    best_bid_price: int | None
    best_bid_quantity: int | None
    best_ask_price: int | None
    best_ask_quantity: int | None
    spread: int | None
    relative_spread: float | None
    mid_price: float | None
    weighted_mid_price: float | None
    book_imbalance_top: float | None

    # Level 2
    bid_depth_k: int | None
    ask_depth_k: int | None
    depth_imbalance_k: float | None

    # OFI
    instant_ofi: int | None
    rolling_ofi: int | None

    # Trade Flow
    last_signed_volume: int | None
    rolling_trade_volume: int | None
    rolling_buy_volume: int | None
    rolling_sell_volume: int | None
    trade_flow_imbalance: float | None
    rolling_vwap: float | None

    # Returns & Volatility
    log_return: float | None
    realized_volatility: float | None

    # Advanced Microstructure
    roll_spread: float | None
    vpin: float | None

    # Validity Flags
    has_bid: bool
    has_ask: bool
    is_crossed: bool
    has_spread: bool
    has_mid: bool
    has_weighted_mid: bool
    has_book_imbalance: bool
    has_depth_imbalance: bool
    has_instant_ofi: bool
    has_rolling_ofi: bool
    has_trade: bool
    has_trade_flow: bool
    has_vwap: bool
    has_log_return: bool
    has_realized_volatility: bool
    has_roll_spread: bool
    has_vpin: bool
