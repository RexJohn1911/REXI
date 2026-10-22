"""Dataset manifest schema, serialization, and cryptographic integrity verification."""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from research.datasets.exceptions import DatasetIntegrityError, IncompleteDatasetError


def compute_file_sha256(path: Path | str, chunk_size: int = 65536) -> str:
    """Compute the SHA-256 cryptographic hex digest of a physical file."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_file_sha256(path: Path | str, expected_sha256: str) -> bool:
    """Verify that a physical file matches its expected SHA-256 checksum."""
    p = Path(path)
    if not p.is_file():
        return False
    return compute_file_sha256(p).lower() == expected_sha256.lower()


def validate_relative_path(path_str: str) -> str:
    """Validate and normalize a partition relative path.

    Rejects:
    - Empty or whitespace paths
    - Absolute paths
    - Paths with null bytes or backslash traversal
    - Paths containing '..' or '.' directory traversal parts
    """
    if not isinstance(path_str, str) or not path_str.strip():
        raise DatasetIntegrityError("Partition relative path cannot be empty.")

    clean = path_str.strip()
    if "\0" in clean:
        raise DatasetIntegrityError("Null byte detected in partition path.")

    # Check for leading slashes
    if clean.startswith("/") or clean.startswith("\\"):
        raise DatasetIntegrityError(f"Absolute partition paths are prohibited: '{path_str}'")

    p = Path(clean)
    if p.is_absolute() or (p.drive and len(p.drive) > 0):
        raise DatasetIntegrityError(f"Absolute partition paths are prohibited: '{path_str}'")

    for part in p.parts:
        if part in ("..", ".", ""):
            raise DatasetIntegrityError(
                f"Path traversal or invalid component in partition path: '{path_str}'"
            )

    return p.as_posix()


def resolve_partition_path(base_dir: Path | str, relative_path: str) -> Path:
    """Safely resolve a partition path against a base dataset directory.

    Ensures the resolved path is strictly contained within the base directory and
    does not escape via directory traversal or symlinks.
    """
    clean_rel = validate_relative_path(relative_path)
    base = Path(base_dir).resolve()
    target = (base / clean_rel).resolve()

    if not target.is_relative_to(base):
        raise DatasetIntegrityError(
            f"Path traversal detected: partition path '{relative_path}' resolves outside "
            f"dataset root '{base}'"
        )
    return target


@dataclass(frozen=True)
class PartitionFile:
    """Metadata describing a single physical partition file within a dataset."""

    relative_path: str
    record_count: int
    byte_size: int
    sha256_checksum: str
    min_timestamp_ns: int | None = None
    max_timestamp_ns: int | None = None
    min_sequence: int | None = None
    max_sequence: int | None = None
    partition_values: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        clean = validate_relative_path(self.relative_path)
        object.__setattr__(self, "relative_path", clean)
        if self.record_count < 0:
            raise DatasetIntegrityError(f"Record count cannot be negative: {self.record_count}")
        if self.byte_size < 0:
            raise DatasetIntegrityError(f"Byte size cannot be negative: {self.byte_size}")

    def to_dict(self) -> dict[str, Any]:
        """Convert partition descriptor to serializable dictionary."""
        return {
            "relative_path": self.relative_path,
            "record_count": self.record_count,
            "byte_size": self.byte_size,
            "sha256_checksum": self.sha256_checksum,
            "min_timestamp_ns": self.min_timestamp_ns,
            "max_timestamp_ns": self.max_timestamp_ns,
            "min_sequence": self.min_sequence,
            "max_sequence": self.max_sequence,
            "partition_values": dict(self.partition_values),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PartitionFile":
        """Reconstruct partition descriptor from dictionary."""
        return cls(
            relative_path=data["relative_path"],
            record_count=data["record_count"],
            byte_size=data["byte_size"],
            sha256_checksum=data["sha256_checksum"],
            min_timestamp_ns=data.get("min_timestamp_ns"),
            max_timestamp_ns=data.get("max_timestamp_ns"),
            min_sequence=data.get("min_sequence"),
            max_sequence=data.get("max_sequence"),
            partition_values=dict(data.get("partition_values", {})),
        )


@dataclass
class DatasetManifest:
    """Comprehensive, versioned metadata manifest recording dataset identity, schema, and layout."""

    manifest_version: str
    dataset_id: str
    name: str
    kind: str
    domain: str
    schema_name: str
    schema_version: str
    created_at_utc: str
    time_range: dict[str, int]
    record_count: int
    partition_count: int
    total_byte_size: int
    instruments: list[int]
    venues: list[int]
    feeds: list[int]
    dates: list[str]
    partition_keys: list[str]
    partitions: list[PartitionFile]
    provenance: dict[str, Any]
    compression: str
    validation_status: str
    validation_rules_version: str
    is_complete: bool

    def to_json(self) -> str:
        """Serialize manifest to deterministic formatted JSON with sorted keys."""
        d = {
            "manifest_version": self.manifest_version,
            "dataset_id": self.dataset_id,
            "name": self.name,
            "kind": self.kind,
            "domain": self.domain,
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "created_at_utc": self.created_at_utc,
            "time_range": self.time_range,
            "record_count": self.record_count,
            "partition_count": self.partition_count,
            "total_byte_size": self.total_byte_size,
            "instruments": sorted(self.instruments),
            "venues": sorted(self.venues),
            "feeds": sorted(self.feeds),
            "dates": sorted(self.dates),
            "partition_keys": list(self.partition_keys),
            "partitions": [p.to_dict() for p in self.partitions],
            "provenance": self.provenance,
            "compression": self.compression,
            "validation_status": self.validation_status,
            "validation_rules_version": self.validation_rules_version,
            "is_complete": self.is_complete,
        }
        return json.dumps(d, indent=2, sort_keys=True)

    def to_file(self, path: Path | str) -> None:
        """Write manifest JSON to disk."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(self.to_json())
            f.write("\n")

    @classmethod
    def from_json(cls, json_str: str) -> "DatasetManifest":
        """Deserialize manifest from JSON string."""
        data = json.loads(json_str)

        # Validate required manifest schema version
        mver = data.get("manifest_version")
        if not mver or not str(mver).startswith("1."):
            raise DatasetIntegrityError(f"Unsupported manifest version: '{mver}'")

        if not data.get("is_complete", False):
            raise IncompleteDatasetError(
                f"Dataset '{data.get('dataset_id')}' manifest is marked incomplete."
            )

        raw_parts = data.get("partitions", [])
        partitions = [PartitionFile.from_dict(p) for p in raw_parts]

        # Reject duplicate partition paths
        seen_paths: set[str] = set()
        for p in partitions:
            norm_path = p.relative_path
            if norm_path in seen_paths:
                raise DatasetIntegrityError(
                    f"Duplicate partition path detected in manifest: '{norm_path}'"
                )
            seen_paths.add(norm_path)

        # Validate internal consistency of counts and sizes
        declared_partition_count = data.get("partition_count")
        if declared_partition_count != len(partitions):
            raise DatasetIntegrityError(
                f"Manifest partition count mismatch: declared {declared_partition_count}, "
                f"actual entries {len(partitions)}"
            )

        declared_record_count = data.get("record_count")
        sum_records = sum(p.record_count for p in partitions)
        if declared_record_count != sum_records:
            raise DatasetIntegrityError(
                f"Manifest record count mismatch: declared {declared_record_count}, "
                f"partition sum {sum_records}"
            )

        declared_total_bytes = data.get("total_byte_size")
        sum_bytes = sum(p.byte_size for p in partitions)
        if declared_total_bytes != sum_bytes:
            raise DatasetIntegrityError(
                f"Manifest total byte size mismatch: declared {declared_total_bytes}, "
                f"partition sum {sum_bytes}"
            )

        return cls(
            manifest_version=data["manifest_version"],
            dataset_id=data["dataset_id"],
            name=data["name"],
            kind=data["kind"],
            domain=data["domain"],
            schema_name=data["schema_name"],
            schema_version=data["schema_version"],
            created_at_utc=data["created_at_utc"],
            time_range=data["time_range"],
            record_count=data["record_count"],
            partition_count=data["partition_count"],
            total_byte_size=data["total_byte_size"],
            instruments=list(data.get("instruments", [])),
            venues=list(data.get("venues", [])),
            feeds=list(data.get("feeds", [])),
            dates=list(data.get("dates", [])),
            partition_keys=list(data.get("partition_keys", [])),
            partitions=partitions,
            provenance=dict(data.get("provenance", {})),
            compression=data["compression"],
            validation_status=data["validation_status"],
            validation_rules_version=data["validation_rules_version"],
            is_complete=bool(data["is_complete"]),
        )

    @classmethod
    def from_file(cls, path: Path | str) -> "DatasetManifest":
        """Load manifest from a file path."""
        p = Path(path)
        if not p.is_file():
            raise DatasetIntegrityError(f"Manifest file not found: {p}")
        with open(p, encoding="utf-8") as f:
            return cls.from_json(f.read())

    def verify_integrity(self, base_dir: Path | str) -> tuple[bool, list[str]]:
        """Verify cryptographic checksums, sizes, Parquet structures, and consistency."""
        root = Path(base_dir).resolve()
        errors: list[str] = []

        if not self.is_complete:
            errors.append(f"Dataset '{self.dataset_id}' is marked incomplete.")

        total_records = 0
        total_bytes = 0

        for part in self.partitions:
            try:
                part_path = resolve_partition_path(root, part.relative_path)
            except DatasetIntegrityError as e:
                errors.append(f"Security error resolving '{part.relative_path}': {e}")
                continue

            if not part_path.is_file():
                errors.append(f"Missing partition file: '{part.relative_path}'")
                continue

            actual_size = part_path.stat().st_size
            if actual_size != part.byte_size:
                errors.append(
                    f"File size mismatch for '{part.relative_path}': expected {part.byte_size}, "
                    f"got {actual_size}"
                )

            actual_sha = compute_file_sha256(part_path)
            if actual_sha.lower() != part.sha256_checksum.lower():
                errors.append(
                    f"Checksum mismatch for '{part.relative_path}': expected "
                    f"{part.sha256_checksum}, got {actual_sha}"
                )

            # Deep Parquet integrity check: verify file structure and row counts
            try:
                pq_file = pq.ParquetFile(str(part_path))
                actual_rows = pq_file.metadata.num_rows
                if actual_rows != part.record_count:
                    errors.append(
                        f"Parquet row count mismatch for '{part.relative_path}': "
                        f"manifest states {part.record_count}, parquet metadata has {actual_rows}"
                    )
            except Exception as e:
                errors.append(f"Corrupted or invalid Parquet file '{part.relative_path}': {e}")

            total_records += part.record_count
            total_bytes += actual_size

        if total_records != self.record_count:
            errors.append(
                f"Record count mismatch: manifest states {self.record_count}, "
                f"partition sum is {total_records}"
            )

        if total_bytes != self.total_byte_size:
            errors.append(
                f"Total byte size mismatch: manifest states {self.total_byte_size}, "
                f"actual files sum is {total_bytes}"
            )

        return (len(errors) == 0, errors)
