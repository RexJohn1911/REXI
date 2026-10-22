"""Domain models, enums, dataclasses, and timestamp utilities for REXI Leakage Framework."""

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from research.datasets.types import TimeRange
from research.leakage.exceptions import InvalidSplitConfigError, TimestampSafetyError


class SplitType(str, Enum):
    """Supported temporal data partition strategies."""

    CHRONOLOGICAL_HOLD_OUT = "chronological_hold_out"
    WALK_FORWARD_EXPANDING = "walk_forward_expanding"
    WALK_FORWARD_ROLLING = "walk_forward_rolling"
    PURGED_K_FOLD = "purged_k_fold"
    COMBINATORIAL_PURGED = "combinatorial_purged"


class PartitionRole(str, Enum):
    """Designation of a partition's role within an evaluation fold."""

    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"
    EMBARGO = "embargo"
    PURGED = "purged"


# ISO-8601 regex with mandatory timezone offset or Z
ISO8601_TZ_REGEX = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})$",
    re.IGNORECASE,
)


def normalize_timestamp_ns(val: Any, default_tz: timezone | None = None) -> int:
    """Validate and normalize a timestamp to 64-bit signed integer nanoseconds since UNIX epoch.

    Accepts:
    - int: signed 64-bit nanosecond integer.
    - datetime: must be timezone-aware or default_tz must be explicitly provided.
    - str: ISO-8601 formatted string with explicit timezone indicator (e.g. 'Z', '+00:00').

    Rejects:
    - Naive datetimes (without default_tz)
    - Strings without timezone indicators
    - Floats (to avoid precision loss/NaNs)
    - None / NaN / infinite values
    """
    if val is None:
        raise TimestampSafetyError("Timestamp value cannot be None.")

    if isinstance(val, bool):
        raise TimestampSafetyError("Boolean value cannot be used as timestamp.")

    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            raise TimestampSafetyError(f"Float NaN or Inf cannot be used as timestamp: {val}")
        raise TimestampSafetyError(
            f"Floating-point timestamp '{val}' rejected to prevent numerical precision loss. "
            "Use integer nanoseconds or timezone-aware datetime."
        )

    if isinstance(val, int):
        # 64-bit signed integer check
        if val < -9_223_372_036_854_775_808 or val > 9_223_372_036_854_775_807:
            raise TimestampSafetyError(f"Timestamp integer out of 64-bit signed range: {val}")
        return val

    if isinstance(val, datetime):
        if val.tzinfo is None:
            if default_tz is None:
                raise TimestampSafetyError(
                    f"Naive datetime '{val}' rejected. Explicit timezone awareness required."
                )
            dt = val.replace(tzinfo=default_tz)
        else:
            dt = val
        dt_utc = dt.astimezone(UTC)
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        delta = dt_utc - epoch
        total_seconds = delta.days * 86400 + delta.seconds
        return total_seconds * 1_000_000_000 + delta.microseconds * 1000

    if isinstance(val, str):
        clean_str = val.strip()
        if not ISO8601_TZ_REGEX.match(clean_str):
            if default_tz is None:
                raise TimestampSafetyError(
                    f"Timestamp string '{clean_str}' lacks explicit timezone offset or 'Z'. "
                    "Silent local timezone assumptions are prohibited."
                )
            # Try parsing with default_tz if explicitly configured
            try:
                dt_parsed = datetime.fromisoformat(clean_str)
                if dt_parsed.tzinfo is None:
                    dt_parsed = dt_parsed.replace(tzinfo=default_tz)
                return normalize_timestamp_ns(dt_parsed)
            except Exception as e:
                raise TimestampSafetyError(
                    f"Failed to parse timestamp string '{clean_str}': {e}"
                ) from e

        # Normalize 'Z' to '+00:00' for fromisoformat compatibility
        iso_str = clean_str.replace("Z", "+00:00").replace("z", "+00:00")
        try:
            dt_aware = datetime.fromisoformat(iso_str)
            return normalize_timestamp_ns(dt_aware)
        except Exception as e:
            raise TimestampSafetyError(f"Invalid ISO-8601 timestamp string '{val}': {e}") from e

    raise TimestampSafetyError(
        f"Unsupported timestamp type '{type(val).__name__}': {val!r}. "
        "Must be int (nanoseconds), timezone-aware datetime, or ISO-8601 string."
    )


@dataclass(frozen=True)
class TimeInterval:
    """Half-open temporal boundary [start_timestamp_ns, end_timestamp_ns).

    Semantics:
    - Includes start_timestamp_ns.
    - Excludes end_timestamp_ns.
    - An empty interval satisfies start_timestamp_ns == end_timestamp_ns.
    """

    start_timestamp_ns: int
    end_timestamp_ns: int

    def __post_init__(self) -> None:
        if not isinstance(self.start_timestamp_ns, int) or not isinstance(
            self.end_timestamp_ns, int
        ):
            raise TimestampSafetyError("TimeInterval boundaries must be integers.")
        if self.start_timestamp_ns > self.end_timestamp_ns:
            raise InvalidSplitConfigError(
                f"Inverted interval: start_timestamp_ns ({self.start_timestamp_ns}) > "
                f"end_timestamp_ns ({self.end_timestamp_ns})"
            )

    def duration_ns(self) -> int:
        """Return duration in nanoseconds."""
        return self.end_timestamp_ns - self.start_timestamp_ns

    def duration_seconds(self) -> float:
        """Return duration in floating-point seconds."""
        return self.duration_ns() / 1_000_000_000.0

    def is_empty(self) -> bool:
        """Return True if duration is zero."""
        return self.start_timestamp_ns == self.end_timestamp_ns

    def contains(self, timestamp_ns: int) -> bool:
        """Check if timestamp lies within half-open interval [start, end)."""
        return self.start_timestamp_ns <= timestamp_ns < self.end_timestamp_ns

    def contains_inclusive(self, timestamp_ns: int) -> bool:
        """Check if timestamp lies within closed interval [start, end]."""
        return self.start_timestamp_ns <= timestamp_ns <= self.end_timestamp_ns

    def overlaps_half_open(self, other: "TimeInterval") -> bool:
        """Check if two half-open intervals [a1, b1) and [a2, b2) overlap."""
        return max(self.start_timestamp_ns, other.start_timestamp_ns) < min(
            self.end_timestamp_ns, other.end_timestamp_ns
        )

    def overlaps_closed(self, closed_start: int, closed_end: int) -> bool:
        """Check if a closed interval [a1, b1] overlaps this half-open interval [a2, b2).

        Overlap occurs iff: a1 < b2 and b1 >= a2.
        """
        if closed_start > closed_end:
            raise InvalidSplitConfigError(
                f"Invalid closed interval: start ({closed_start}) > end ({closed_end})"
            )
        return (closed_start < self.end_timestamp_ns) and (closed_end >= self.start_timestamp_ns)

    def to_time_range(self) -> TimeRange:
        """Convert to Phase 08 TimeRange object."""
        return TimeRange(
            start_timestamp_ns=self.start_timestamp_ns,
            end_timestamp_ns=self.end_timestamp_ns,
        )

    @classmethod
    def from_time_range(cls, tr: TimeRange) -> "TimeInterval":
        """Construct from Phase 08 TimeRange."""
        return cls(
            start_timestamp_ns=tr.start_timestamp_ns,
            end_timestamp_ns=tr.end_timestamp_ns,
        )

    def to_dict(self) -> dict[str, int]:
        """Serialize to dictionary."""
        return {
            "start_timestamp_ns": self.start_timestamp_ns,
            "end_timestamp_ns": self.end_timestamp_ns,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TimeInterval":
        """Deserialize from dictionary."""
        return cls(
            start_timestamp_ns=int(data["start_timestamp_ns"]),
            end_timestamp_ns=int(data["end_timestamp_ns"]),
        )


@dataclass(frozen=True)
class LabelInformationInterval:
    """Represents a sample's label evaluation interval [t_obs, t_label_end].

    Semantics:
    - Observation timestamp: when the sample features are captured.
    - Label end timestamp: the furthest future timestamp whose information enters the
      label computation.
    - Information interval is closed: [t_obs, t_label_end].
    """

    observation_timestamp_ns: int
    label_end_timestamp_ns: int

    def __post_init__(self) -> None:
        if self.observation_timestamp_ns > self.label_end_timestamp_ns:
            raise InvalidSplitConfigError(
                f"Label observation timestamp ({self.observation_timestamp_ns}) cannot be after "
                f"label end timestamp ({self.label_end_timestamp_ns})."
            )

    @property
    def horizon_ns(self) -> int:
        """Return the forward label information horizon in nanoseconds."""
        return self.label_end_timestamp_ns - self.observation_timestamp_ns

    def touches_partition(self, partition: TimeInterval) -> bool:
        """Check if label information interval touches a half-open evaluation partition [a, b)."""
        return partition.overlaps_closed(self.observation_timestamp_ns, self.label_end_timestamp_ns)


@dataclass(frozen=True)
class PurgeEmbargoConfig:
    """Configuration governing label horizon purging and post-test embargo."""

    purge_horizon_ns: int = 0
    embargo_ns: int = 0

    def __post_init__(self) -> None:
        if self.purge_horizon_ns < 0:
            raise InvalidSplitConfigError(
                f"purge_horizon_ns cannot be negative: {self.purge_horizon_ns}"
            )
        if self.embargo_ns < 0:
            raise InvalidSplitConfigError(f"embargo_ns cannot be negative: {self.embargo_ns}")

    def to_dict(self) -> dict[str, int]:
        """Serialize configuration to dictionary."""
        return {
            "purge_horizon_ns": self.purge_horizon_ns,
            "embargo_ns": self.embargo_ns,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PurgeEmbargoConfig":
        """Deserialize configuration from dictionary."""
        return cls(
            purge_horizon_ns=int(data.get("purge_horizon_ns", 0)),
            embargo_ns=int(data.get("embargo_ns", 0)),
        )


@dataclass(frozen=True)
class SplitPartition:
    """Metadata describing a single partition within an evaluation fold."""

    role: PartitionRole
    partition_index: int
    time_boundary: TimeInterval
    record_count: int
    record_indices: tuple[int, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize partition description."""
        res: dict[str, Any] = {
            "role": self.role.value,
            "partition_index": self.partition_index,
            "time_boundary": self.time_boundary.to_dict(),
            "record_count": self.record_count,
        }
        if self.record_indices is not None:
            if len(self.record_indices) > 0:
                res["index_min"] = int(self.record_indices[0])
                res["index_max"] = int(self.record_indices[-1])
            res["index_count"] = len(self.record_indices)
            res["record_indices"] = list(self.record_indices)
        return res

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SplitPartition":
        """Deserialize partition description."""
        indices = data.get("record_indices")
        return cls(
            role=PartitionRole(data["role"]),
            partition_index=int(data["partition_index"]),
            time_boundary=TimeInterval.from_dict(data["time_boundary"]),
            record_count=int(data["record_count"]),
            record_indices=tuple(indices) if indices is not None else None,
        )


@dataclass(frozen=True)
class SplitDefinition:
    """Represents a complete evaluation fold (train, test, optional validation)."""

    split_index: int
    train_partition: SplitPartition
    test_partition: SplitPartition
    val_partition: SplitPartition | None = None
    purged_record_count: int = 0
    embargoed_record_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize split definition."""
        d: dict[str, Any] = {
            "split_index": self.split_index,
            "train": self.train_partition.to_dict(),
            "test": self.test_partition.to_dict(),
            "purged_record_count": self.purged_record_count,
            "embargoed_record_count": self.embargoed_record_count,
            "metadata": dict(self.metadata),
        }
        if self.val_partition is not None:
            d["validation"] = self.val_partition.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SplitDefinition":
        """Deserialize split definition."""
        train = SplitPartition.from_dict(data["train"])
        test = SplitPartition.from_dict(data["test"])
        val = SplitPartition.from_dict(data["validation"]) if "validation" in data else None
        return cls(
            split_index=int(data["split_index"]),
            train_partition=train,
            test_partition=test,
            val_partition=val,
            purged_record_count=int(data.get("purged_record_count", 0)),
            embargoed_record_count=int(data.get("embargoed_record_count", 0)),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class SplitManifest:
    """Cryptographically verifiable specification of dataset splits for reproducibility."""

    split_manifest_id: str
    split_type: SplitType
    total_samples: int
    time_boundary: TimeInterval
    config: dict[str, Any]
    splits: list[SplitDefinition]
    created_at_utc: str
    spec_version: str = "1.0.0"
    dataset_id: str | None = None
    dataset_manifest_sha256: str | None = None
    manifest_sha256: str = ""

    def to_dict(self, include_sha256: bool = False) -> dict[str, Any]:
        """Convert manifest to serializable dictionary."""
        d: dict[str, Any] = {
            "spec_version": self.spec_version,
            "split_manifest_id": self.split_manifest_id,
            "split_type": self.split_type.value,
            "dataset_id": self.dataset_id,
            "dataset_manifest_sha256": self.dataset_manifest_sha256,
            "total_samples": self.total_samples,
            "time_boundary": self.time_boundary.to_dict(),
            "config": dict(self.config),
            "splits": [s.to_dict() for s in self.splits],
            "created_at_utc": self.created_at_utc,
        }
        if include_sha256:
            d["manifest_sha256"] = self.manifest_sha256
        return d

    def compute_sha256(self) -> str:
        """Compute deterministic SHA-256 hash of the canonical JSON representation."""
        canonical_json = json.dumps(
            self.to_dict(include_sha256=False),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def verify_integrity(self) -> bool:
        """Verify that manifest_sha256 matches the computed content hash."""
        if not self.manifest_sha256:
            return False
        return self.compute_sha256().lower() == self.manifest_sha256.lower()

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize manifest to JSON string including manifest_sha256."""
        d = self.to_dict(include_sha256=True)
        if indent is not None:
            return json.dumps(d, indent=indent, sort_keys=True)
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def to_file(self, path: Path | str) -> None:
        """Write manifest JSON to disk."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(self.to_json())
            f.write("\n")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SplitManifest":
        """Reconstruct SplitManifest from dictionary."""
        spec_version = data.get("spec_version", "1.0.0")
        if not str(spec_version).startswith("1."):
            raise InvalidSplitConfigError(f"Unsupported split manifest version: '{spec_version}'")

        split_type = SplitType(data["split_type"])
        time_boundary = TimeInterval.from_dict(data["time_boundary"])
        splits = [SplitDefinition.from_dict(s) for s in data["splits"]]

        return cls(
            split_manifest_id=data["split_manifest_id"],
            split_type=split_type,
            total_samples=int(data["total_samples"]),
            time_boundary=time_boundary,
            config=dict(data.get("config", {})),
            splits=splits,
            created_at_utc=data["created_at_utc"],
            spec_version=spec_version,
            dataset_id=data.get("dataset_id"),
            dataset_manifest_sha256=data.get("dataset_manifest_sha256"),
            manifest_sha256=data.get("manifest_sha256", ""),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "SplitManifest":
        """Deserialize manifest from JSON string."""
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_file(cls, path: Path | str) -> "SplitManifest":
        """Load manifest from file."""
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Manifest file not found: {p}")
        with open(p, encoding="utf-8") as f:
            return cls.from_json(f.read())


@dataclass(frozen=True)
class FeatureAvailabilityRecord:
    """Record tracking feature observation vs point-in-time availability."""

    feature_name: str
    event_timestamp_ns: int
    available_timestamp_ns: int

    def __post_init__(self) -> None:
        if self.event_timestamp_ns > self.available_timestamp_ns:
            raise InvalidSplitConfigError(
                f"Feature '{self.feature_name}' event_timestamp_ns ({self.event_timestamp_ns}) "
                f"is after available_timestamp_ns ({self.available_timestamp_ns}). "
                "Event cannot occur after its availability."
            )

    @property
    def latency_ns(self) -> int:
        """Dissemination or computation delay."""
        return self.available_timestamp_ns - self.event_timestamp_ns


@dataclass(frozen=True)
class LeakageAuditReport:
    """Detailed audit report generated by LookaheadDetector."""

    is_valid: bool
    violation_count: int
    violations: tuple[str, ...]
    audited_sample_count: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "is_valid": self.is_valid,
            "violation_count": self.violation_count,
            "violations": list(self.violations),
            "audited_sample_count": self.audited_sample_count,
            "metadata": dict(self.metadata),
        }
