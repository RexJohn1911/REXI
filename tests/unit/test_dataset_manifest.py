"""Unit tests for DatasetManifest serialization, deserialization, and checksum verification."""

from pathlib import Path

import pytest

from research.datasets.exceptions import DatasetIntegrityError, IncompleteDatasetError
from research.datasets.manifest import (
    DatasetManifest,
    PartitionFile,
    compute_file_sha256,
    verify_file_sha256,
)
from research.datasets.types import ProvenanceInfo


def test_sha256_computation_and_verification(tmp_path: Path) -> None:
    test_file = tmp_path / "sample.bin"
    content = b"REXI Quantitative Research Data Lake - Phase 08"
    test_file.write_bytes(content)

    sha = compute_file_sha256(test_file)
    assert len(sha) == 64
    assert verify_file_sha256(test_file, sha)
    assert not verify_file_sha256(test_file, "0" * 64)


def test_manifest_serialization_and_roundtrip(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"

    prov = ProvenanceInfo(
        source_files=["raw_capture_20261022.bin"],
        source_dataset_id="raw_market_data_001",
        generator_name="test_generator",
        generator_version="1.0.0",
        replay_state_digest=0x123456789ABCDEF0,
        notes="Generated during unit testing",
    )

    part = PartitionFile(
        relative_path="date=2026-10-22/part-00000.parquet",
        record_count=1000,
        byte_size=20480,
        sha256_checksum="a" * 64,
        min_timestamp_ns=1_000_000,
        max_timestamp_ns=2_000_000,
        min_sequence=1,
        max_sequence=1000,
        partition_values={"date": "2026-10-22"},
    )

    manifest = DatasetManifest(
        manifest_version="1.0.0",
        dataset_id="trades_sample_01",
        name="Sample Trades",
        kind="trades",
        domain="market_data",
        schema_name="rexi.market_data.trade",
        schema_version="1.0.0",
        created_at_utc="2026-10-22T10:00:00Z",
        time_range={"start_timestamp_ns": 1_000_000, "end_timestamp_ns": 2_000_000},
        record_count=1000,
        partition_count=1,
        total_byte_size=20480,
        instruments=[1, 2],
        venues=[1],
        feeds=[1],
        dates=["2026-10-22"],
        partition_keys=["date"],
        partitions=[part],
        provenance=prov.to_dict(),
        compression="zstd",
        validation_status="VALID",
        validation_rules_version="1.0.0",
        is_complete=True,
    )

    manifest.to_file(manifest_path)
    loaded = DatasetManifest.from_file(manifest_path)

    assert loaded.dataset_id == "trades_sample_01"
    assert loaded.schema_name == "rexi.market_data.trade"
    assert loaded.record_count == 1000
    assert loaded.total_byte_size == 20480
    assert len(loaded.partitions) == 1
    assert loaded.partitions[0].relative_path == "date=2026-10-22/part-00000.parquet"
    assert loaded.is_complete is True

    # Provenance reconstruction
    prov_loaded = ProvenanceInfo.from_dict(loaded.provenance)
    assert prov_loaded.replay_state_digest == 0x123456789ABCDEF0
    assert prov_loaded.source_files == ["raw_capture_20261022.bin"]


def test_manifest_rejection_of_incomplete_dataset() -> None:
    bad_json = """
    {
        "manifest_version": "1.0.0",
        "dataset_id": "incomplete_01",
        "is_complete": false
    }
    """
    with pytest.raises(IncompleteDatasetError, match="marked incomplete"):
        DatasetManifest.from_json(bad_json)


def test_manifest_rejection_of_unsupported_version() -> None:
    bad_json = """
    {
        "manifest_version": "2.0.0",
        "dataset_id": "future_version_01",
        "is_complete": true
    }
    """
    with pytest.raises(DatasetIntegrityError, match="Unsupported manifest version"):
        DatasetManifest.from_json(bad_json)
