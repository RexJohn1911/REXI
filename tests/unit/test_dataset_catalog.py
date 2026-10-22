"""Unit tests for DatasetCatalog discovery, indexing, and maintenance."""

import time
from pathlib import Path

import pytest

from research.datasets.catalog import DatasetCatalog, _extract_dataset_id_from_name
from research.datasets.exceptions import DatasetNotFoundError
from research.datasets.generator import SyntheticMarketDataGenerator
from research.datasets.types import DataDomain, DatasetKind
from research.datasets.writer import DatasetWriter


def test_catalog_discovery_and_retrieval(tmp_path: Path) -> None:
    catalog = DatasetCatalog(root_dir=tmp_path)
    assert catalog.list_datasets() == []

    gen = SyntheticMarketDataGenerator(seed=10)
    t = gen.generate_trades(count=100)

    # Write two datasets
    with DatasetWriter(
        dataset_id="ds_alpha",
        name="Dataset Alpha",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as w:
        w.write_batch(t)

    with DatasetWriter(
        dataset_id="ds_beta",
        name="Dataset Beta",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as w:
        w.write_batch(t)

    datasets = catalog.list_datasets()
    assert len(datasets) == 2
    ids = {d.dataset_id for d in datasets}
    assert ids == {"ds_alpha", "ds_beta"}

    manifest_alpha = catalog.get_dataset("ds_alpha")
    assert manifest_alpha.name == "Dataset Alpha"
    assert manifest_alpha.record_count == 100

    # Non-existent
    with pytest.raises(DatasetNotFoundError, match="not found in catalog"):
        catalog.get_dataset("ds_gamma")


def test_catalog_clean_stale_staging(tmp_path: Path) -> None:
    catalog = DatasetCatalog(root_dir=tmp_path)

    # Simulate an abandoned staging directory with valid 8-hex-character suffix
    stale_dir = tmp_path / ".staging_abandoned_1a2b3c4d"
    stale_dir.mkdir(parents=True, exist_ok=True)
    dummy_file = stale_dir / "temp.parquet"
    dummy_file.write_bytes(b"stale data")

    # When max_age_seconds is very large, it should not clean it
    cleaned_none = catalog.clean_stale_staging(max_age_seconds=3600.0)
    assert cleaned_none == 0
    assert stale_dir.exists()

    # When max_age_seconds is 0.0 or negative, it treats it as stale and cleans it
    time.sleep(0.01)
    cleaned = catalog.clean_stale_staging(max_age_seconds=0.0)
    assert cleaned == 1
    assert not stale_dir.exists()


def test_extract_dataset_id_from_name_strict_parsing() -> None:
    """Validate strict directory suffix format [0-9a-fA-F]{8} and rejection of malformed names."""
    # 1. Valid IDs containing underscores and hyphens
    assert _extract_dataset_id_from_name(".backup_", ".backup_my_data_01_1a2b3c4d") == "my_data_01"
    assert _extract_dataset_id_from_name(".backup_", ".backup_my-data-01_1a2b3c4d") == "my-data-01"
    assert (
        _extract_dataset_id_from_name(".backup_", ".backup_binance_btc-usdt_trades_1a2b3c4d")
        == "binance_btc-usdt_trades"
    )
    assert (
        _extract_dataset_id_from_name(".staging_", ".staging_my_data_01_1a2b3c4d")
        == "my_data_01"
    )
    assert (
        _extract_dataset_id_from_name(".staging_", ".staging_my-data-01_1a2b3c4d")
        == "my-data-01"
    )

    # 2. Valid uppercase and lowercase hexadecimal suffixes
    assert _extract_dataset_id_from_name(".backup_", ".backup_dataset_1a2b3c4d") == "dataset"
    assert _extract_dataset_id_from_name(".backup_", ".backup_dataset_1A2B3C4D") == "dataset"
    assert _extract_dataset_id_from_name(".backup_", ".backup_dataset_aAbBcCdD") == "dataset"
    assert _extract_dataset_id_from_name(".backup_", ".backup_dataset_01234567") == "dataset"
    assert _extract_dataset_id_from_name(".backup_", ".backup_dataset_89abcdef") == "dataset"
    assert _extract_dataset_id_from_name(".backup_", ".backup_dataset_89ABCDEF") == "dataset"

    # 3. Malformed non-hex suffixes (must return None)
    assert _extract_dataset_id_from_name(".backup_", ".backup_dataset_1234567g") is None
    assert _extract_dataset_id_from_name(".backup_", ".backup_dataset_nothex12") is None
    assert _extract_dataset_id_from_name(".backup_", ".backup_dataset_1234567Z") is None
    assert _extract_dataset_id_from_name(".staging_", ".staging_dataset_1234567g") is None
    assert _extract_dataset_id_from_name(".staging_", ".staging_dataset_nothex12") is None

    # 4. Seven-character and nine-character suffixes (must return None)
    assert _extract_dataset_id_from_name(".backup_", ".backup_dataset_1234567") is None
    assert _extract_dataset_id_from_name(".backup_", ".backup_dataset_123456789") is None
    assert _extract_dataset_id_from_name(".staging_", ".staging_dataset_1234567") is None
    assert _extract_dataset_id_from_name(".staging_", ".staging_dataset_123456789") is None

    # 5. Missing suffixes (must return None; no permissive fallback)
    assert _extract_dataset_id_from_name(".backup_", ".backup_dataset") is None
    assert _extract_dataset_id_from_name(".backup_", ".backup_dataset_") is None
    assert _extract_dataset_id_from_name(".staging_", ".staging_dataset") is None
    assert _extract_dataset_id_from_name(".staging_", ".staging_dataset_") is None

    # 6. Empty IDs (must return None)
    assert _extract_dataset_id_from_name(".backup_", ".backup__1a2b3c4d") is None
    assert _extract_dataset_id_from_name(".backup_", ".backup_") is None
    assert _extract_dataset_id_from_name(".staging_", ".staging__1a2b3c4d") is None
    assert _extract_dataset_id_from_name(".staging_", ".staging_") is None

    # 7. IDs ending in an underscore plus eight hexadecimal characters
    # e.g., dataset ID is "order_book_1a2b3c4d",
    # writer directory is .backup_order_book_1a2b3c4d_e5f60718
    assert (
        _extract_dataset_id_from_name(".backup_", ".backup_order_book_1a2b3c4d_e5f60718")
        == "order_book_1a2b3c4d"
    )

    # 8. Unmatched prefix
    assert _extract_dataset_id_from_name(".backup_", ".other_dataset_1a2b3c4d") is None
    assert _extract_dataset_id_from_name(".staging_", ".backup_dataset_1a2b3c4d") is None


def test_malformed_backup_name_quarantine_does_not_lock_or_modify_dataset(tmp_path: Path) -> None:
    """A malformed backup directory cannot cause recovery to lock or modify an existing dataset."""
    catalog = DatasetCatalog(root_dir=tmp_path)
    gen = SyntheticMarketDataGenerator(seed=42)
    trades = gen.generate_trades(count=50)

    # Write a valid target dataset "my_trades"
    with DatasetWriter(
        dataset_id="my_trades",
        name="Valid Trades",
        kind=DatasetKind.TRADES,
        domain=DataDomain.MARKET_DATA,
        schema_name="rexi.market_data.trade",
        root_dir=tmp_path,
    ) as w:
        w.write_batch(trades)

    # Create a malformed backup directory with non-hex suffix and NO manifest
    malformed_backup = tmp_path / ".backup_my_trades_nothex12"
    malformed_backup.mkdir(parents=True, exist_ok=True)
    (malformed_backup / "corrupt_data.bin").write_bytes(b"garbage")

    # Run recovery
    res = catalog.recover_datasets()

    # Recovery must NOT recover or touch "my_trades", and must quarantine the malformed backup
    assert "my_trades" not in res["recovered"]
    assert any("unknown" in q for q in res["quarantined"])

    # Valid target dataset must remain completely intact and valid
    reader = catalog.get_dataset("my_trades")
    assert reader.record_count == 50
    ok, errors = catalog.verify_dataset("my_trades")
    assert ok is True
    assert len(errors) == 0
