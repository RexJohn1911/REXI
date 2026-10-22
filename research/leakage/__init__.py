"""REXI No-Leakage Research Framework.

Provides reliable, reproducible, point-in-time causal partitioning, label horizon purging,
targeted post-test embargo, and lookahead detection for quantitative research.
"""

from research.leakage.dataset_split import DatasetSplitter, SplitDatasetReader
from research.leakage.detector import LookaheadDetector
from research.leakage.exceptions import (
    EmptyPartitionError,
    InvalidSplitConfigError,
    LabelOverlapError,
    LeakageError,
    LookaheadBiasError,
    TemporalOrderError,
    TimestampSafetyError,
)
from research.leakage.point_in_time import PointInTimeAligner
from research.leakage.split import (
    ChronologicalSplitter,
    extract_label_intervals,
    find_safe_boundary_index,
    purge_and_embargo_samples,
    validate_monotonic_timestamps,
)
from research.leakage.types import (
    FeatureAvailabilityRecord,
    LabelInformationInterval,
    LeakageAuditReport,
    PartitionRole,
    PurgeEmbargoConfig,
    SplitDefinition,
    SplitManifest,
    SplitPartition,
    SplitType,
    TimeInterval,
    normalize_timestamp_ns,
)

__all__ = [
    "ChronologicalSplitter",
    "DatasetSplitter",
    "EmptyPartitionError",
    "FeatureAvailabilityRecord",
    "InvalidSplitConfigError",
    "LabelInformationInterval",
    "LabelOverlapError",
    "LeakageAuditReport",
    "LeakageError",
    "LookaheadBiasError",
    "LookaheadDetector",
    "PartitionRole",
    "PointInTimeAligner",
    "PurgeEmbargoConfig",
    "SplitDatasetReader",
    "SplitDefinition",
    "SplitManifest",
    "SplitPartition",
    "SplitType",
    "TemporalOrderError",
    "TimeInterval",
    "TimestampSafetyError",
    "extract_label_intervals",
    "find_safe_boundary_index",
    "normalize_timestamp_ns",
    "purge_and_embargo_samples",
    "validate_monotonic_timestamps",
]
