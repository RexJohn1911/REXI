"""REXI Backtesting and Execution Simulation Package."""

from research.backtesting.costs import (
    US_EASTERN_TZ,
    US_SETTLEMENT_HOLIDAYS_2024_2029,
    US_SETTLEMENT_HOLIDAYS_2024_2032,
    CostModelConfig,
    DatedFeeSchedule,
    SecChargeDateRule,
    TradeDateResolution,
    TransactionCostCalculator,
    calculate_settlement_timestamp_ns,
    create_standard_us_equities_schedules,
    get_us_settlement_holidays_for_year,
    parse_iso_date_to_eastern_ns,
    parse_iso_date_to_utc_ns,
    resolve_trade_and_settlement_dates,
    timestamp_ns_to_eastern_date,
)
from research.backtesting.engine import (
    BacktestEngineConfig,
    BacktestResult,
    BacktestSnapshot,
    DeterministicBacktestEngine,
)
from research.backtesting.exceptions import (
    BacktestConfigurationError,
    BacktestError,
    InsufficientLiquidityError,
    StaleQuoteError,
    UnsupportedOrderTypeError,
)

__all__ = [
    "US_EASTERN_TZ",
    "US_SETTLEMENT_HOLIDAYS_2024_2029",
    "US_SETTLEMENT_HOLIDAYS_2024_2032",
    "BacktestConfigurationError",
    "BacktestEngineConfig",
    "BacktestError",
    "BacktestResult",
    "BacktestSnapshot",
    "CostModelConfig",
    "DatedFeeSchedule",
    "DeterministicBacktestEngine",
    "InsufficientLiquidityError",
    "SecChargeDateRule",
    "StaleQuoteError",
    "TradeDateResolution",
    "TransactionCostCalculator",
    "UnsupportedOrderTypeError",
    "calculate_settlement_timestamp_ns",
    "create_standard_us_equities_schedules",
    "get_us_settlement_holidays_for_year",
    "parse_iso_date_to_eastern_ns",
    "parse_iso_date_to_utc_ns",
    "resolve_trade_and_settlement_dates",
    "timestamp_ns_to_eastern_date",
]
