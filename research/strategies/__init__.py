"""REXI Statistical Strategy Laboratory.

Provides strategy contracts, temporal causality validators, forward targets,
backtest execution, and statistical hypothesis testing.
"""

from research.strategies.base import SIGNAL_SCHEMA_V1, BaseStrategy, FlatBenchmarkStrategy
from research.strategies.targets import BarrierEvent, ForwardTarget, TargetGenerator
from research.strategies.types import (
    FillRecord,
    OrderIntent,
    OrderSide,
    OrderType,
    PositionState,
    Signal,
    TimeInForce,
    validate_temporal_coordinates,
)

__all__ = [
    "SIGNAL_SCHEMA_V1",
    "BarrierEvent",
    "BaseStrategy",
    "FillRecord",
    "FlatBenchmarkStrategy",
    "ForwardTarget",
    "OrderIntent",
    "OrderSide",
    "OrderType",
    "PositionState",
    "Signal",
    "TargetGenerator",
    "TimeInForce",
    "validate_temporal_coordinates",
]
