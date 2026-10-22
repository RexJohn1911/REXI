"""REXI Microstructure Feature Engine.

Provides deterministic, zero-lookahead microstructure feature generation for quantitative
research, market simulation, and point-in-time model evaluation.
"""

from research.features.engine import MicrostructureFeatureEngine
from research.features.pipeline import MicrostructureFeaturePipeline
from research.features.schema import (
    MICROSTRUCTURE_FEATURES_SCHEMA_V1,
    register_microstructure_schemas,
)
from research.features.types import (
    AggressorSide,
    FeatureEngineConfig,
    FeatureEngineError,
    InsufficientHistoryError,
    InvalidEventDataError,
    MicrostructureFeatureRecord,
    NonMonotonicTimestampError,
)

__all__ = [
    "MICROSTRUCTURE_FEATURES_SCHEMA_V1",
    "AggressorSide",
    "FeatureEngineConfig",
    "FeatureEngineError",
    "InsufficientHistoryError",
    "InvalidEventDataError",
    "MicrostructureFeatureEngine",
    "MicrostructureFeaturePipeline",
    "MicrostructureFeatureRecord",
    "NonMonotonicTimestampError",
    "register_microstructure_schemas",
]
