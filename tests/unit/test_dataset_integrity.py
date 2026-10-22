"""Unit tests for dataset cryptographic integrity verification, path security, crash recovery,
and failure modes.
"""

import json
import multiprocessing as mp
import os
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from research.datasets.catalog import DatasetCatalog
from research.datasets.exceptions import (
    DatasetExistsError,
    DatasetIntegrityError,
    DatasetNotFoundError,
)
from research.datasets.generator import SyntheticMarketDataGenerator
from research.datasets.manifest import (
    DatasetManifest,
    resolve_partition_path,
    validate_relative_path,
)
from research.datasets.reader import DatasetReader
from research.datasets.types import DataDomain, DatasetKind
from research.datasets.writer import DatasetLock, DatasetWriter


def _stale_lock_worker(root_dir: str, dataset_id: str, result_queue: Any) -> None:
    """Worker process to verify that stale locks are not mistaken for active transactions."""
    try:
        is_active = DatasetLock.is_active(root_dir, dataset_id)
        if is_active:
            result_queue.put("ERROR_LOCK_MARKED_ACTIVE")
            return

        try:
            DatasetReader(dataset_id, root_dir=root_dir)
            result_queue.put("ERROR_READER_SHOULD_HAVE_FAILED")
            return
        except DatasetNotFoundError as e:
            if "active publication" in str(e):
                result_queue.put("ERROR_CLAIMED_ACTIVE_PUBLICATION")
                return

        cat = DatasetCatalog(root_dir=root_dir)
        recovery_res = cat.recover_datasets()
        if dataset_id not in recovery_res["recovered"]:
            result_queue.put("ERROR_NOT_RECOVERED")
            return

        reader = DatasetReader(dataset_id, root_dir=root_dir)
        if reader.record_count != 50:
            result_queue.put(f"ERROR_ROW_COUNT_{reader.record_count}")
            return

        result_queue.put("SUCCESS")
    except Exception as exc:
        result_queue.put(f"EXCEPTION_{exc}")


def _concurrent_writer_worker(
    root_dir: str, dataset_id: str, count: int, result_queue: Any
) -> None:
    """Worker process targeting the same dataset ID to test process lock collision."""
    try:
        gen = SyntheticMarketDataGenerator(seed=123)
        t = gen.generate_trades(count=count)
        with DatasetWriter(
            dataset_id=dataset_id,
            name="Concurrent Worker",
            kind=DatasetKind.TRADES,
            domain=DataDomain.MARKET_DATA,
            schema_name="rexi.market_data.trade",
            root_dir=root_dir,
        ) as w:
            w.write_batch(t)
        result_queue.put("SUCCESS")
    except DatasetExistsError:
        result_queue.put("LOCKED")
    except Exception as e:
        result_queue.put(f"ERROR: {e}")


def test_corrupted_file_detected_by_checksum_verification(tmp_path: Path) -> None:
    gen = SyntheticMarketDataGenerator(seed=42)
    trades = gen.generate_trades(count=200)

    with DatasetWriter(
        dataset_id="integrity_test_01",
        name="Integrity Test",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(trades)

    reader = DatasetReader("integrity_test_01", root_dir=tmp_path)
    ok, errors = reader.verify_integrity()
    assert ok is True
    assert errors == []

    # Tamper with the partition file by appending one byte
    part_file = tmp_path / "integrity_test_01" / reader.partitions[0].relative_path
    with open(part_file, "ab") as f:
        f.write(b"\x00")

    # Integrity verification must detect size and checksum mismatch
    ok_after_tamper, errors_after_tamper = reader.verify_integrity()
    assert ok_after_tamper is False
    assert any("Checksum mismatch" in e for e in errors_after_tamper)


def test_missing_partition_file_detected(tmp_path: Path) -> None:
    gen = SyntheticMarketDataGenerator(seed=42)
    trades = gen.generate_trades(count=100)

    with DatasetWriter(
        dataset_id="missing_part_test",
        name="Missing Part Test",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(trades)

    reader = DatasetReader("missing_part_test", root_dir=tmp_path)
    part_file = tmp_path / "missing_part_test" / reader.partitions[0].relative_path
    part_file.unlink()

    ok, errors = reader.verify_integrity()
    assert ok is False
    assert any("Missing partition file" in e for e in errors)


def test_writer_aborts_cleanly_on_exception(tmp_path: Path) -> None:
    gen = SyntheticMarketDataGenerator(seed=42)
    trades = gen.generate_trades(count=100)

    try:
        with DatasetWriter(
            dataset_id="abort_test",
            name="Abort Test",
            kind=DatasetKind.TRADES,
            domain=DataDomain.MARKET_DATA,
            schema_name="rexi.market_data.trade",
            root_dir=tmp_path,
        ) as writer:
            writer.write_batch(trades)
            raise RuntimeError("Simulated processing error during batch write")
    except RuntimeError:
        pass

    assert not (tmp_path / "abort_test").exists()
    staging_dirs = list(tmp_path.glob(".staging_abort_test_*"))
    assert len(staging_dirs) == 0

    catalog = DatasetCatalog(root_dir=tmp_path)
    assert catalog.list_datasets() == []


def test_failed_replacement_preserves_original_valid_dataset(tmp_path: Path) -> None:
    """CRIT-001 regression: If overwrite fails during publication, original remains intact."""
    gen = SyntheticMarketDataGenerator(seed=101)
    original_trades = gen.generate_trades(count=150)

    # Publish original dataset
    with DatasetWriter(
        dataset_id="preserve_on_failure",
        name="Original Valid",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(original_trades)

    reader = DatasetReader("preserve_on_failure", root_dir=tmp_path)
    assert reader.record_count == 150
    ok, _ = reader.verify_integrity()
    assert ok is True

    # Attempt replacement that fails during phase 2 (staging -> target rename)
    replacement_trades = gen.generate_trades(count=250)
    w = DatasetWriter(
        dataset_id="preserve_on_failure",
        name="Replacement Attempt",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
        overwrite=True,
    )
    w.open()
    w.write_batch(replacement_trades)

    # Mock os.replace so that the second call (moving staging to target) fails
    with (
        patch(
            "os.replace",
            side_effect=[None, OSError("Simulated disk error during staging move")],
        ),
        pytest.raises(DatasetIntegrityError, match="Failed to publish dataset replacement"),
    ):
        w.close()

    # Verify that the original dataset was restored and remains completely valid
    reader_after = DatasetReader("preserve_on_failure", root_dir=tmp_path)
    assert reader_after.record_count == 150
    ok_after, errs_after = reader_after.verify_integrity()
    assert ok_after is True
    assert errs_after == []


def test_interrupted_staging_discovery_and_cleanup(tmp_path: Path) -> None:
    """Incomplete staging directories must not appear in catalog and can be cleaned."""
    gen = SyntheticMarketDataGenerator(seed=202)
    trades = gen.generate_trades(count=50)

    w = DatasetWriter(
        dataset_id="interrupted_dataset",
        name="Interrupted",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    )
    w.open()
    w.write_batch(trades)
    # Don't call close(), leave staging as-is
    w._release_lock()

    catalog = DatasetCatalog(root_dir=tmp_path)
    datasets = catalog.list_datasets()
    assert all(d.dataset_id != "interrupted_dataset" for d in datasets)

    # Clean staging older than 0 seconds
    cleaned = catalog.clean_stale_staging(max_age_seconds=-1.0)
    assert cleaned >= 1


def test_concurrent_writer_process_locking(tmp_path: Path) -> None:
    """Attempting to open the same dataset concurrently in two writers raises DatasetExistsError."""
    w1 = DatasetWriter(
        dataset_id="concurrent_target",
        name="Concurrent 1",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    )
    w1.open()

    w2 = DatasetWriter(
        dataset_id="concurrent_target",
        name="Concurrent 2",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
        overwrite=True,
    )
    with pytest.raises(DatasetExistsError, match="currently locked"):
        w2.open()

    w1.abort()


def test_multiprocess_concurrent_writers_lock_rejection(tmp_path: Path) -> None:
    """Simultaneous writers targeting the same dataset in separate OS processes."""
    ctx = mp.get_context("spawn")
    q = ctx.Queue()

    # Pre-acquire lock by opening first writer
    w1 = DatasetWriter(
        dataset_id="mp_lock_target",
        name="Lock Holder",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    )
    w1.open()

    # Spawn second writer in independent process
    p = ctx.Process(
        target=_concurrent_writer_worker,
        args=(str(tmp_path), "mp_lock_target", 50, q),
    )
    p.start()
    p.join(timeout=10)

    result = q.get(timeout=5)
    assert result == "LOCKED"

    w1.abort()


def test_manifest_path_security_traversal_rejected(tmp_path: Path) -> None:
    """CRIT-003: Manifest partition paths must not escape the dataset root."""
    with pytest.raises(DatasetIntegrityError, match="Absolute partition paths"):
        validate_relative_path("/etc/passwd")

    with pytest.raises(DatasetIntegrityError, match="Path traversal"):
        validate_relative_path("../outside.parquet")

    with pytest.raises(DatasetIntegrityError, match="Path traversal"):
        validate_relative_path("sub/../../outside.parquet")

    with pytest.raises(DatasetIntegrityError, match="cannot be empty"):
        validate_relative_path("   ")

    dataset_dir = tmp_path / "safe_dir"
    dataset_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    symlink_path = dataset_dir / "escaped_link.parquet"
    symlink_path.symlink_to(outside_dir)

    with pytest.raises(DatasetIntegrityError, match="resolves outside dataset root"):
        resolve_partition_path(dataset_dir, "escaped_link.parquet")


def test_manifest_rejects_duplicate_partitions(tmp_path: Path) -> None:
    """CRIT-004: Manifests with duplicate partition paths must be rejected."""
    gen = SyntheticMarketDataGenerator(seed=303)
    trades = gen.generate_trades(count=100)

    with DatasetWriter(
        dataset_id="dupe_manifest_part",
        name="Dupe Partition",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(trades)

    manifest_file = tmp_path / "dupe_manifest_part" / "manifest.json"
    data = json.loads(manifest_file.read_text())

    data["partitions"].append(data["partitions"][0])
    data["partition_count"] = len(data["partitions"])
    data["record_count"] *= 2
    data["total_byte_size"] *= 2

    manifest_file.write_text(json.dumps(data))

    with pytest.raises(DatasetIntegrityError, match="Duplicate partition path detected"):
        DatasetReader("dupe_manifest_part", root_dir=tmp_path)


def test_manifest_internal_consistency_validation(tmp_path: Path) -> None:
    """Manifest record count, partition count, and byte size mismatches must be rejected."""
    gen = SyntheticMarketDataGenerator(seed=404)
    trades = gen.generate_trades(count=100)

    with DatasetWriter(
        dataset_id="consistency_test",
        name="Consistency Test",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(trades)

    manifest_file = tmp_path / "consistency_test" / "manifest.json"
    original_text = manifest_file.read_text()

    data = json.loads(original_text)
    data["record_count"] = 9999
    manifest_file.write_text(json.dumps(data))
    with pytest.raises(DatasetIntegrityError, match="Manifest record count mismatch"):
        DatasetManifest.from_file(manifest_file)

    data = json.loads(original_text)
    data["partition_count"] = 5
    manifest_file.write_text(json.dumps(data))
    with pytest.raises(DatasetIntegrityError, match="Manifest partition count mismatch"):
        DatasetManifest.from_file(manifest_file)

    data = json.loads(original_text)
    data["total_byte_size"] = 1
    manifest_file.write_text(json.dumps(data))
    with pytest.raises(DatasetIntegrityError, match="Manifest total byte size mismatch"):
        DatasetManifest.from_file(manifest_file)


def test_deep_parquet_integrity_and_row_count_mismatch(tmp_path: Path) -> None:
    """Verify that verify_integrity checks Parquet structure and row counts."""
    gen = SyntheticMarketDataGenerator(seed=505)
    trades = gen.generate_trades(count=100)

    with DatasetWriter(
        dataset_id="deep_parquet_test",
        name="Deep Parquet",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(trades)

    reader = DatasetReader("deep_parquet_test", root_dir=tmp_path)
    ok, errors = reader.verify_integrity()
    assert ok is True

    part_path = tmp_path / "deep_parquet_test" / reader.partitions[0].relative_path
    with open(part_path, "wb") as f:
        f.write(b"PAR1corrupted_header_data_not_valid_parquet")

    ok_bad, errors_bad = reader.verify_integrity()
    assert ok_bad is False
    assert any(
        "Corrupted or invalid Parquet file" in e or "Checksum mismatch" in e
        for e in errors_bad
    )


# =============================================================================
# Crash Recovery and Backup Preservation Tests
# =============================================================================

def test_recovery_when_backup_exists_and_target_missing(tmp_path: Path) -> None:
    """Crash scenario: target was moved to backup, process crashed before staging promoted."""
    gen = SyntheticMarketDataGenerator(seed=606)
    trades = gen.generate_trades(count=120)

    # Create original dataset
    with DatasetWriter(
        dataset_id="crash_recovery_01",
        name="Crash Recovery Test",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(trades)

    target_dir = tmp_path / "crash_recovery_01"
    backup_dir = tmp_path / ".backup_crash_recovery_01_aabbccdd"

    # Simulate crash after Phase 1 (target renamed to backup, target missing)
    os.replace(target_dir, backup_dir)
    assert not target_dir.exists()
    assert backup_dir.exists()

    catalog = DatasetCatalog(root_dir=tmp_path)
    summary = catalog.recover_datasets()

    assert "crash_recovery_01" in summary["recovered"]
    assert target_dir.exists()
    assert not backup_dir.exists()

    # Verify recovered dataset
    reader = DatasetReader("crash_recovery_01", root_dir=tmp_path)
    assert reader.record_count == 120
    ok, _ = reader.verify_integrity()
    assert ok is True


def test_recovery_when_both_target_and_backup_exist_target_valid(tmp_path: Path) -> None:
    """Crash scenario: staging promoted to target, but crash occurred before backup purged."""
    gen = SyntheticMarketDataGenerator(seed=707)
    trades = gen.generate_trades(count=80)

    with DatasetWriter(
        dataset_id="redundant_backup_test",
        name="Redundant Backup Test",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(trades)

    target_dir = tmp_path / "redundant_backup_test"
    backup_dir = tmp_path / ".backup_redundant_backup_test_11223344"

    # Copy target to backup to simulate leftover redundant backup after success
    shutil.copytree(target_dir, backup_dir)

    catalog = DatasetCatalog(root_dir=tmp_path)
    summary = catalog.recover_datasets()
    assert backup_dir.name in summary["redundant"]
    assert target_dir.exists()

    # Now run clean_stale_staging with age threshold exceeded
    cleaned = catalog.clean_stale_staging(max_age_seconds=-1.0)
    assert cleaned >= 1
    assert not backup_dir.exists()
    assert target_dir.exists()


def test_recovery_when_both_target_and_backup_exist_target_corrupt(tmp_path: Path) -> None:
    """Crash scenario: staging was promoted to target, but target was truncated/corrupted."""
    gen = SyntheticMarketDataGenerator(seed=808)
    trades = gen.generate_trades(count=90)

    with DatasetWriter(
        dataset_id="corrupt_target_test",
        name="Corrupt Target Test",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(trades)

    target_dir = tmp_path / "corrupt_target_test"
    backup_dir = tmp_path / ".backup_corrupt_target_test_55667788"

    # Move valid target to backup
    os.replace(target_dir, backup_dir)

    # Create a corrupt target directory with invalid manifest
    target_dir.mkdir()
    (target_dir / "manifest.json").write_text("invalid JSON corruption")

    catalog = DatasetCatalog(root_dir=tmp_path)
    summary = catalog.recover_datasets()

    assert "corrupt_target_test" in summary["recovered"]
    assert target_dir.exists()

    # Confirm restored target is valid
    reader = DatasetReader("corrupt_target_test", root_dir=tmp_path)
    assert reader.record_count == 90
    ok, _ = reader.verify_integrity()
    assert ok is True


def test_invalid_or_corrupt_backup_preserved_never_deleted(tmp_path: Path) -> None:
    """Safety guarantee: A corrupt backup is quarantined and NEVER blindly deleted."""
    backup_dir = tmp_path / ".backup_corrupt_only_99999999"
    backup_dir.mkdir()
    (backup_dir / "manifest.json").write_text("corrupted manifest content")

    catalog = DatasetCatalog(root_dir=tmp_path)
    catalog.clean_stale_staging(max_age_seconds=-1.0)

    # Ensure no data was deleted: backup or quarantined directory still exists on disk
    remaining = [p.name for p in tmp_path.iterdir() if p.is_dir()]
    assert any("corrupt_backup" in name or name == backup_dir.name for name in remaining)


def test_cleanup_never_deletes_only_valid_dataset(tmp_path: Path) -> None:
    """Safety guarantee: clean_stale_staging must recover a valid backup rather than deleting it."""
    gen = SyntheticMarketDataGenerator(seed=909)
    trades = gen.generate_trades(count=60)

    with DatasetWriter(
        dataset_id="sole_surviving_backup",
        name="Sole Surviving",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(trades)

    target_dir = tmp_path / "sole_surviving_backup"
    backup_dir = tmp_path / ".backup_sole_surviving_backup_deadbeef"
    os.replace(target_dir, backup_dir)
    assert not target_dir.exists()

    # Run cleanup with aggressive max_age_seconds=-1.0
    catalog = DatasetCatalog(root_dir=tmp_path)
    catalog.clean_stale_staging(max_age_seconds=-1.0)

    # Target MUST be recovered and NOT deleted!
    assert target_dir.exists()
    reader = DatasetReader("sole_surviving_backup", root_dir=tmp_path)
    assert reader.record_count == 60


def test_failed_rollback_preserves_backup_directory(tmp_path: Path) -> None:
    """If Phase 2 fails AND rollback fails, backup directory must be preserved on disk."""
    gen = SyntheticMarketDataGenerator(seed=1010)
    trades = gen.generate_trades(count=70)

    with DatasetWriter(
        dataset_id="failed_rollback_test",
        name="Failed Rollback Test",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(trades)

    # Now attempt replacement where both promotion and rollback raise errors
    w = DatasetWriter(
        dataset_id="failed_rollback_test",
        name="Replacement",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
        overwrite=True,
    )
    w.open()
    w.write_batch(trades)

    real_replace = os.replace

    def mock_replace(src: Any, dst: Any) -> None:
        if ".staging_" in str(src):
            raise OSError("Simulated promotion disk error")
        if ".backup_" in str(src):
            raise OSError("Simulated rollback disk error")
        real_replace(src, dst)

    with (
        patch("os.replace", side_effect=mock_replace),
        pytest.raises(DatasetIntegrityError, match="Original dataset preserved in backup"),
    ):
        w.close()

    # Verify backup directory was preserved on disk
    backups = [
        p for p in tmp_path.iterdir()
        if p.is_dir() and p.name.startswith(".backup_failed_rollback_test_")
    ]
    assert len(backups) == 1

    # Catalog recovery restores it cleanly
    catalog = DatasetCatalog(root_dir=tmp_path)
    catalog.recover_datasets()
    assert (tmp_path / "failed_rollback_test").exists()


def test_reader_error_during_publication_gap(tmp_path: Path) -> None:
    """Reader attempting to open dataset during publication transaction receives clear error.

    When lock is released, the persistent lock file must not be mistaken for an active tx.
    """
    lock = DatasetLock(tmp_path, "active_gap_dataset")
    lock.acquire()
    try:
        with pytest.raises(
            DatasetNotFoundError,
            match="dataset is currently undergoing an active publication/replacement transaction",
        ):
            DatasetReader("active_gap_dataset", root_dir=tmp_path)
    finally:
        lock.release()

    # Now the lock is released, but the empty .lock_active_gap_dataset file persists on disk
    assert (tmp_path / ".lock_active_gap_dataset").is_file()
    # Reader should now raise standard not-found without claiming active transaction
    with pytest.raises(DatasetNotFoundError) as exc_info:
        DatasetReader("active_gap_dataset", root_dir=tmp_path)
    assert "currently undergoing an active publication" not in str(exc_info.value)


def test_reader_opens_valid_dataset_with_persistent_lock_file(tmp_path: Path) -> None:
    """Reader opens and queries a valid dataset after writer closes, even with persistent lock."""
    gen = SyntheticMarketDataGenerator(seed=111)
    trades = gen.generate_trades(count=60)

    with DatasetWriter(
        dataset_id="valid_dataset_persistent_lock",
        name="Valid DS",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(trades)

    # Confirm the persistent lock file remains on disk after writer close
    lock_file = tmp_path / ".lock_valid_dataset_persistent_lock"
    assert lock_file.is_file()

    # Reader opens successfully and queries records
    reader = DatasetReader("valid_dataset_persistent_lock", root_dir=tmp_path)
    assert reader.record_count == 60
    table = reader.read_table()
    assert table.num_rows == 60


def test_multiprocess_readers_and_recovery_do_not_mistake_stale_lock_for_active_tx(
    tmp_path: Path,
) -> None:
    """In an independent process, readers and recovery treat stale lock as inactive and recover."""
    dataset_id = "mp_stale_lock_ds"

    # Step 1: Create a valid dataset in a staging dir then rename to backup to simulate crash
    gen = SyntheticMarketDataGenerator(seed=222)
    trades = gen.generate_trades(count=50)

    with DatasetWriter(
        dataset_id=dataset_id,
        name="MP Stale Lock Test",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(trades)

    target_dir = tmp_path / dataset_id
    backup_dir = tmp_path / f".backup_{dataset_id}_11223344"
    os.replace(target_dir, backup_dir)

    # Persistent lock file exists from the writer
    lock_file = tmp_path / f".lock_{dataset_id}"
    assert lock_file.is_file()
    assert not target_dir.exists()
    assert backup_dir.exists()

    # Step 2: Spawn independent process to verify that reader does not mistake lock for active,
    # and recovery successfully acquires the lock and restores the dataset
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    p = ctx.Process(target=_stale_lock_worker, args=(str(tmp_path), dataset_id, q))
    p.start()
    p.join(timeout=10)

    res = q.get(timeout=5)
    assert res == "SUCCESS"
    assert target_dir.exists()


def test_recovery_skipped_when_another_process_holds_dataset_lock(tmp_path: Path) -> None:
    """Recovery must never race with an active writer holding the dataset lock."""
    dataset_id = "active_locked_recovery_ds"
    gen = SyntheticMarketDataGenerator(seed=333)
    trades = gen.generate_trades(count=40)

    with DatasetWriter(
        dataset_id=dataset_id,
        name="Active Lock DS",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(trades)

    target_dir = tmp_path / dataset_id
    backup_dir = tmp_path / f".backup_{dataset_id}_aabbccdd"
    os.replace(target_dir, backup_dir)

    # Now acquire the lock to simulate an active concurrent writer publishing/operating on it
    lock = DatasetLock(tmp_path, dataset_id)
    lock.acquire()

    catalog = DatasetCatalog(root_dir=tmp_path)
    res = catalog.recover_datasets()
    # Recovery must skip active locked dataset; target must still be missing and backup intact
    assert dataset_id not in res["recovered"]
    assert not target_dir.exists()
    assert backup_dir.exists()

    # Release the lock
    lock.release()

    # Now recovery can safely proceed
    res2 = catalog.recover_datasets()
    assert dataset_id in res2["recovered"]
    assert target_dir.exists()
    assert not backup_dir.exists()


def test_repeated_recovery_is_idempotent(tmp_path: Path) -> None:
    """Repeated runs of recover_datasets() are strictly idempotent and cause no damage."""
    dataset_id = "idempotent_ds"
    gen = SyntheticMarketDataGenerator(seed=444)
    trades = gen.generate_trades(count=30)

    with DatasetWriter(
        dataset_id=dataset_id,
        name="Idempotent DS",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as writer:
        writer.write_batch(trades)

    target_dir = tmp_path / dataset_id
    backup_dir = tmp_path / f".backup_{dataset_id}_99887766"
    os.replace(target_dir, backup_dir)

    catalog = DatasetCatalog(root_dir=tmp_path)

    # Run 1: Recovers
    res1 = catalog.recover_datasets()
    assert dataset_id in res1["recovered"]
    assert target_dir.exists()

    # Run 2: Target is valid, nothing to recover
    res2 = catalog.recover_datasets()
    assert res2 == {"recovered": [], "quarantined": [], "redundant": []}

    # Run 3: Still no-op
    res3 = catalog.recover_datasets()
    assert res3 == {"recovered": [], "quarantined": [], "redundant": []}

    # Verify dataset integrity remains perfect
    reader = DatasetReader(dataset_id, root_dir=tmp_path)
    assert reader.record_count == 30
    ok, _ = reader.verify_integrity()
    assert ok
