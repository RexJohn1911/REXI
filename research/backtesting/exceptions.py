"""Exceptions for REXI Backtesting and Execution Simulation."""


class BacktestError(Exception):
    """Base exception for backtesting domain."""


class UnsupportedOrderTypeError(BacktestError):
    """Raised when an order type is not supported by the backtester (e.g. LIMIT in Stage 2)."""


class StaleQuoteError(BacktestError):
    """Raised when an execution is attempted against a stale or unavailable quote."""


class InsufficientLiquidityError(BacktestError):
    """Raised when displayed depth is insufficient to satisfy an order without partial fill."""


class BacktestConfigurationError(BacktestError):
    """Raised when backtest engine or cost configuration is invalid."""
