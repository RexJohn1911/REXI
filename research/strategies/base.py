"""Base strategy interface and flat/no-trade benchmark for Strategy Laboratory."""

from abc import ABC, abstractmethod
from typing import Any

import pyarrow as pa

from research.features.types import MicrostructureFeatureRecord
from research.strategies.types import Signal

# Canonical PyArrow Schema for Strategy Signals
SIGNAL_SCHEMA_V1 = pa.schema(
    [
        pa.field("decision_timestamp_ns", pa.int64(), nullable=False),
        pa.field("instrument_id", pa.int64(), nullable=False),
        pa.field("direction", pa.int8(), nullable=False),
        pa.field("target_weight", pa.float64(), nullable=False),
        pa.field("strength", pa.float64(), nullable=False),
        pa.field("confidence", pa.float64(), nullable=False),
        pa.field("is_valid", pa.bool_(), nullable=False),
    ]
)


class BaseStrategy(ABC):
    """Abstract base class for all REXI quantitative and statistical strategies."""

    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        self.name = name
        self.config = config or {}
        self._is_fitted: bool = False

    @property
    def is_fitted(self) -> bool:
        """True if the strategy has been calibrated on in-sample data."""
        return self._is_fitted

    @abstractmethod
    def fit(self, train_table: pa.Table) -> None:
        """Calibrate strategy parameters strictly on in-sample training data.

        Must NEVER access validation or out-of-sample test data.
        """
        ...

    @abstractmethod
    def generate_signals(self, features_table: pa.Table) -> pa.Table:
        """Generate a causal table of signals from a microstructure features table.

        Temporal Integrity Invariant:
        Signal at row i (decision_timestamp_ns) may ONLY observe features where
        available_timestamp_ns <= decision_timestamp_ns.
        """
        ...

    @abstractmethod
    def on_features(self, record: MicrostructureFeatureRecord) -> Signal | None:
        """Streaming feature event handler for step-by-step causal evaluation.

        Returns a Signal if a new decision is made, or None if no update is required.
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """Reset internal streaming state (for clean replay across evaluation folds)."""
        ...


class FlatBenchmarkStrategy(BaseStrategy):
    """Zero-trade / Flat baseline benchmark strategy.

    Provides a clean null baseline for backtesting pipelines, ensuring that all
    infrastructure (cost accounting, mark-to-market equity curve, Sharpe ratios)
    properly reports zero turnover, zero net PnL, and zero trading activity.
    """

    def __init__(self, instrument_id: int) -> None:
        super().__init__(name="FlatBenchmark", config={"instrument_id": instrument_id})
        self.instrument_id = instrument_id
        self._is_fitted = True

    def fit(self, train_table: pa.Table) -> None:
        """No calibration required for flat benchmark."""
        self._is_fitted = True

    def reset(self) -> None:
        """No internal state to reset for flat benchmark."""
        pass

    def generate_signals(self, features_table: pa.Table) -> pa.Table:
        """Generate flat (0.0 weight, 0 direction) signals for every decision timestamp."""
        if len(features_table) == 0:
            return pa.Table.from_batches([], schema=SIGNAL_SCHEMA_V1)

        decision_ts = features_table["decision_timestamp_ns"]
        n_rows = len(features_table)

        arrays = [
            decision_ts,
            pa.array([self.instrument_id] * n_rows, type=pa.int64()),
            pa.array([0] * n_rows, type=pa.int8()),
            pa.array([0.0] * n_rows, type=pa.float64()),
            pa.array([0.0] * n_rows, type=pa.float64()),
            pa.array([1.0] * n_rows, type=pa.float64()),
            pa.array([True] * n_rows, type=pa.bool_()),
        ]
        return pa.Table.from_arrays(arrays, schema=SIGNAL_SCHEMA_V1)

    def on_features(self, record: MicrostructureFeatureRecord) -> Signal | None:
        """Return a flat signal on every valid feature record."""
        return Signal(
            decision_timestamp_ns=record.decision_timestamp_ns,
            instrument_id=self.instrument_id,
            direction=0,
            target_weight=0.0,
            strength=0.0,
            confidence=1.0,
            is_valid=True,
            metadata={"strategy": self.name},
        )
