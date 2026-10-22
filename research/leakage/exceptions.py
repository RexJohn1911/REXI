"""Custom exceptions for REXI No-Leakage Research Framework."""


class LeakageError(Exception):
    """Base exception for all temporal leakage, causal violation, and split safety errors."""


class TemporalOrderError(LeakageError):
    """Raised when chronological ordering is violated (e.g., non-monotonic timestamps)."""


class TimestampSafetyError(LeakageError):
    """Raised when timestamp validation fails (e.g., naive timezones, NaN/nulls, invalid types)."""


class LookaheadBiasError(LeakageError):
    """Raised when future information is accessed before its point-in-time availability."""


class LabelOverlapError(LeakageError):
    """Raised when a label information interval overlaps an evaluation partition without purging."""


class InvalidSplitConfigError(LeakageError):
    """Raised when split configuration parameters are invalid or produce unsafe partitions."""


class EmptyPartitionError(LeakageError):
    """Raised when a split partition contains zero records or time range is exhausted."""
