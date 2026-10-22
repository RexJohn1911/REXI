"""Unit tests for timestamp safety, interval mathematics, and leakage domain types."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from research.datasets.types import TimeRange
from research.leakage.exceptions import (
    InvalidSplitConfigError,
    TimestampSafetyError,
)
from research.leakage.types import (
    LabelInformationInterval,
    PartitionRole,
    SplitDefinition,
    SplitManifest,
    SplitPartition,
    SplitType,
    TimeInterval,
    normalize_timestamp_ns,
)


def test_negative_epoch_timestamps_accepted() -> None:
    """Pre-1970 negative epoch timestamps are valid and preserved."""
    neg_ts = -3_600_000_000_000  # -1 hour relative to UNIX epoch
    normalized = normalize_timestamp_ns(neg_ts)
    assert normalized == neg_ts
    assert isinstance(normalized, int)


def test_timezone_aware_datetime_normalization() -> None:
    """Timezone-aware datetimes with non-UTC offsets normalize to exact UTC nanoseconds."""
    # 1970-01-01 05:30:00+05:30 is 1970-01-01 00:00:00 UTC (epoch = 0)
    dt_ist = datetime.fromisoformat("1970-01-01T05:30:00+05:30")
    ts_ns = normalize_timestamp_ns(dt_ist)
    assert ts_ns == 0

    # 2026-10-22 12:00:00 UTC
    dt_utc = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)
    expected_ns = int(dt_utc.timestamp()) * 1_000_000_000
    assert normalize_timestamp_ns(dt_utc) == expected_ns


def test_naive_datetime_rejected_without_explicit_tz() -> None:
    """Naive datetimes are strictly rejected unless an explicit default_tz is provided."""
    dt_naive = datetime(2026, 10, 22, 12, 0, 0)
    with pytest.raises(TimestampSafetyError, match="Naive datetime.*rejected"):
        normalize_timestamp_ns(dt_naive)

    # When explicit default_tz is provided, it normalizes correctly
    ts_ns = normalize_timestamp_ns(dt_naive, default_tz=UTC)
    assert ts_ns == int(dt_naive.replace(tzinfo=UTC).timestamp()) * 1_000_000_000


def test_iso_string_with_explicit_timezone() -> None:
    """ISO strings with Z or offsets parse accurately to nanoseconds."""
    # With Z
    ts1 = normalize_timestamp_ns("1970-01-01T00:00:00Z")
    assert ts1 == 0

    # With +00:00
    ts2 = normalize_timestamp_ns("1970-01-01T00:00:00+00:00")
    assert ts2 == 0

    # Pre-1970 string
    ts3 = normalize_timestamp_ns("1969-12-31T23:00:00Z")
    assert ts3 == -3600 * 1_000_000_000

    # Missing timezone rejected
    with pytest.raises(TimestampSafetyError, match="lacks explicit timezone"):
        normalize_timestamp_ns("2026-10-22T12:00:00")


def test_invalid_types_rejected() -> None:
    """Float, NaN, Inf, None, and boolean types are rejected."""
    with pytest.raises(TimestampSafetyError, match="cannot be None"):
        normalize_timestamp_ns(None)

    with pytest.raises(TimestampSafetyError, match="Boolean value"):
        normalize_timestamp_ns(True)

    with pytest.raises(TimestampSafetyError, match="Floating-point timestamp"):
        normalize_timestamp_ns(123456789.0)

    with pytest.raises(TimestampSafetyError, match="Float NaN or Inf"):
        normalize_timestamp_ns(float("nan"))


def test_time_interval_half_open_semantics() -> None:
    """TimeInterval behaves strictly as half-open [start, end)."""
    interval = TimeInterval(start_timestamp_ns=100, end_timestamp_ns=200)
    assert interval.duration_ns() == 100
    assert not interval.is_empty()

    assert not interval.contains(99)
    assert interval.contains(100)
    assert interval.contains(199)
    assert not interval.contains(200)

    # Inverted interval rejected
    with pytest.raises(InvalidSplitConfigError, match="Inverted interval"):
        TimeInterval(start_timestamp_ns=200, end_timestamp_ns=100)


def test_time_interval_exact_boundary_overlap() -> None:
    """Closed label interval [a1, b1] vs half-open partition [a2, b2) overlap semantics."""
    partition = TimeInterval(100, 200)

    # Case 1: Label ends strictly before partition starts
    assert not partition.overlaps_closed(50, 99)

    # Case 2: Label ends exactly at partition start (touches boundary point 100)
    # [50, 100] touches [100, 200) at 100 -> overlaps!
    assert partition.overlaps_closed(50, 100)

    # Case 3: Label entirely inside partition
    assert partition.overlaps_closed(120, 150)

    # Case 4: Label straddles right boundary (starts at 199, ends at 250)
    assert partition.overlaps_closed(199, 250)

    # Case 5: Label starts exactly at partition end
    # [200, 250] does NOT overlap [100, 200) because partition excludes 200
    assert not partition.overlaps_closed(200, 250)


def test_phase_08_time_range_compatibility() -> None:
    """TimeInterval cleanly converts to and from Phase 08 TimeRange."""
    tr = TimeRange(start_timestamp_ns=1_000, end_timestamp_ns=2_000)
    ti = TimeInterval.from_time_range(tr)
    assert ti.start_timestamp_ns == 1_000
    assert ti.end_timestamp_ns == 2_000

    tr_back = ti.to_time_range()
    assert tr_back.start_timestamp_ns == 1_000
    assert tr_back.end_timestamp_ns == 2_000


def test_label_information_interval() -> None:
    """LabelInformationInterval represents closed information horizon."""
    label = LabelInformationInterval(observation_timestamp_ns=100, label_end_timestamp_ns=150)
    assert label.horizon_ns == 50

    # Inverted rejected
    with pytest.raises(InvalidSplitConfigError, match="cannot be after"):
        LabelInformationInterval(observation_timestamp_ns=150, label_end_timestamp_ns=100)

    partition = TimeInterval(120, 200)
    assert label.touches_partition(partition)


def test_split_manifest_cryptographic_verification() -> None:
    """SplitManifest computes deterministic SHA-256 and validates integrity."""
    part_train = SplitPartition(
        role=PartitionRole.TRAIN,
        partition_index=0,
        time_boundary=TimeInterval(0, 500),
        record_count=50,
        record_indices=tuple(range(50)),
    )
    part_test = SplitPartition(
        role=PartitionRole.TEST,
        partition_index=1,
        time_boundary=TimeInterval(500, 1000),
        record_count=50,
        record_indices=tuple(range(50, 100)),
    )
    split_def = SplitDefinition(
        split_index=0,
        train_partition=part_train,
        test_partition=part_test,
    )
    manifest = SplitManifest(
        split_manifest_id="split_test_001",
        split_type=SplitType.CHRONOLOGICAL_HOLD_OUT,
        total_samples=100,
        time_boundary=TimeInterval(0, 1000),
        config={"train_ratio": 0.5, "test_ratio": 0.5},
        splits=[split_def],
        created_at_utc="2026-10-22T19:30:00Z",
    )

    sha = manifest.compute_sha256()
    assert len(sha) == 64
    assert not manifest.verify_integrity()  # empty manifest_sha256 initially

    # Manifest with correct sha matches
    signed_manifest = SplitManifest(
        split_manifest_id=manifest.split_manifest_id,
        split_type=manifest.split_type,
        total_samples=manifest.total_samples,
        time_boundary=manifest.time_boundary,
        config=manifest.config,
        splits=manifest.splits,
        created_at_utc=manifest.created_at_utc,
        manifest_sha256=sha,
    )
    assert signed_manifest.verify_integrity()


def test_split_manifest_serialization_and_tamper_detection(tmp_path: Path) -> None:
    """Verify canonical deterministic serialization, round-trip deserialization,
    and tamper detection.
    """
    part_train = SplitPartition(
        role=PartitionRole.TRAIN,
        partition_index=0,
        time_boundary=TimeInterval(1000, 5000),
        record_count=40,
        record_indices=tuple(range(40)),
    )
    part_test = SplitPartition(
        role=PartitionRole.TEST,
        partition_index=1,
        time_boundary=TimeInterval(5000, 10000),
        record_count=60,
        record_indices=tuple(range(40, 100)),
    )
    split_def = SplitDefinition(
        split_index=0,
        train_partition=part_train,
        test_partition=part_test,
    )
    manifest = SplitManifest(
        split_manifest_id="split_tamper_test",
        split_type=SplitType.CHRONOLOGICAL_HOLD_OUT,
        dataset_id="sample_lake_dataset",
        dataset_manifest_sha256="a" * 64,
        total_samples=100,
        time_boundary=TimeInterval(1000, 10000),
        config={"train_ratio": 0.4, "test_ratio": 0.6},
        splits=[split_def],
        created_at_utc="2026-10-22T20:00:00Z",
    )
    signed_manifest = SplitManifest(
        split_manifest_id=manifest.split_manifest_id,
        split_type=manifest.split_type,
        dataset_id=manifest.dataset_id,
        dataset_manifest_sha256=manifest.dataset_manifest_sha256,
        total_samples=manifest.total_samples,
        time_boundary=manifest.time_boundary,
        config=manifest.config,
        splits=manifest.splits,
        created_at_utc=manifest.created_at_utc,
        manifest_sha256=manifest.compute_sha256(),
    )
    assert signed_manifest.verify_integrity()

    # 1. Round-trip JSON serialization
    json_str = signed_manifest.to_json()
    from_json_manifest = SplitManifest.from_json(json_str)
    assert from_json_manifest.verify_integrity()
    assert from_json_manifest.split_manifest_id == signed_manifest.split_manifest_id
    assert from_json_manifest.manifest_sha256 == signed_manifest.manifest_sha256
    assert from_json_manifest.splits[0].train_partition.record_indices == (
        signed_manifest.splits[0].train_partition.record_indices
    )

    # 2. Round-trip file serialization
    file_path = tmp_path / "split_manifest.json"
    signed_manifest.to_file(file_path)
    from_file_manifest = SplitManifest.from_file(file_path)
    assert from_file_manifest.verify_integrity()
    assert from_file_manifest.manifest_sha256 == signed_manifest.manifest_sha256

    # 3. Tamper detection: modify total_samples
    tampered_samples = SplitManifest.from_dict({
        **signed_manifest.to_dict(include_sha256=True),
        "total_samples": 999,
    })
    assert not tampered_samples.verify_integrity()

    # 4. Tamper detection: modify start_timestamp_ns
    boundary_dict = signed_manifest.time_boundary.to_dict()
    boundary_dict["start_timestamp_ns"] = 500
    tampered_boundary = SplitManifest.from_dict({
        **signed_manifest.to_dict(include_sha256=True),
        "time_boundary": boundary_dict,
    })
    assert not tampered_boundary.verify_integrity()

    # 5. Tamper detection: modify record_indices in train partition
    splits_dict = [s.to_dict() for s in signed_manifest.splits]
    splits_dict[0]["train"]["record_indices"][0] = 999
    tampered_indices = SplitManifest.from_dict({
        **signed_manifest.to_dict(include_sha256=True),
        "splits": splits_dict,
    })
    assert not tampered_indices.verify_integrity()

    # 6. Tamper detection: modify dataset_manifest_sha256
    tampered_dataset_sha = SplitManifest.from_dict({
        **signed_manifest.to_dict(include_sha256=True),
        "dataset_manifest_sha256": "b" * 64,
    })
    assert not tampered_dataset_sha.verify_integrity()

    # 7. Tamper detection: modify config
    tampered_config = SplitManifest.from_dict({
        **signed_manifest.to_dict(include_sha256=True),
        "config": {"train_ratio": 0.5, "test_ratio": 0.5},
    })
    assert not tampered_config.verify_integrity()

    # 8. Tamper detection: invalid manifest_sha256
    tampered_sha = SplitManifest.from_dict({
        **signed_manifest.to_dict(include_sha256=True),
        "manifest_sha256": "c" * 64,
    })
    assert not tampered_sha.verify_integrity()

    # 9. Non-existent file raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        SplitManifest.from_file(tmp_path / "non_existent.json")

    # 10. Unsupported spec_version raises InvalidSplitConfigError
    with pytest.raises(InvalidSplitConfigError, match="Unsupported split manifest version"):
        SplitManifest.from_dict({
            **signed_manifest.to_dict(include_sha256=True),
            "spec_version": "2.0.0",
        })
