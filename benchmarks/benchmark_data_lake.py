"""Reproducible benchmark suite for REXI Research Data Lake operations."""

import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Add project root to sys.path for standalone script execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyarrow as pa

from research.datasets import (
    CompressionType,
    DataDomain,
    DatasetCatalog,
    DatasetKind,
    DatasetReader,
    DatasetWriter,
    SyntheticMarketDataGenerator,
)


def run_benchmarks() -> None:
    print("=" * 70)
    print("REXI RESEARCH DATA LAKE (PHASE 08) PERFORMANCE BENCHMARKS")
    print("=" * 70)
    print(f"Platform: {platform.system()} {platform.machine()} ({platform.processor()})")
    print(f"Python: {platform.python_version()}")
    print(f"PyArrow: {pa.__version__}")
    print("=" * 70)

    temp_dir = Path(tempfile.mkdtemp(prefix="rexi_bench_datalake_"))
    try:
        gen = SyntheticMarketDataGenerator(seed=42)
        catalog = DatasetCatalog(root_dir=temp_dir)

        # -----------------------------------------------------------------
        # Benchmark 1: Writing Synthetic Batches to Parquet (ZSTD)
        # -----------------------------------------------------------------
        for count in [10_000, 100_000]:
            table = gen.generate_trades(count=count)
            dataset_id = f"bench_write_trades_{count}"

            # Warmup
            with DatasetWriter(
                dataset_id=f"{dataset_id}_warmup",
                name="Warmup",
                kind=DatasetKind.TRADES,
                domain=DataDomain.MARKET_DATA,
                schema_name="rexi.market_data.trade",
                root_dir=temp_dir,
                compression=CompressionType.ZSTD,
            ) as w:
                w.write_batch(table)

            # Timed run
            start_t = time.perf_counter()
            with DatasetWriter(
                dataset_id=dataset_id,
                name=f"Bench Write {count}",
                kind=DatasetKind.TRADES,
                domain=DataDomain.MARKET_DATA,
                schema_name="rexi.market_data.trade",
                root_dir=temp_dir,
                compression=CompressionType.ZSTD,
            ) as w:
                w.write_batch(table)
            elapsed = time.perf_counter() - start_t

            reader = DatasetReader(dataset_id, root_dir=temp_dir)
            total_bytes = reader.manifest.total_byte_size
            mb = total_bytes / (1024 * 1024)
            rate_records = count / elapsed
            rate_mb = mb / elapsed

            print(
                f"[BM_DataLake_Write_ZSTD_{count:<7}] "
                f"Records: {count:>7} | Elapsed: {elapsed * 1000:>6.2f} ms | "
                f"Throughput: {rate_records:>10.0f} rec/s ({rate_mb:>6.2f} MB/s) | "
                f"Compressed Size: {mb:.3f} MB"
            )

        # -----------------------------------------------------------------
        # Benchmark 2: Bounded Batch Streaming Reading
        # -----------------------------------------------------------------
        read_dataset_id = "bench_write_trades_100000"
        reader = DatasetReader(read_dataset_id, root_dir=temp_dir)

        for batch_size in [1000, 10_000, 50_000]:
            # Warmup
            for _ in reader.read_batch_iter(batch_size=batch_size):
                pass

            start_t = time.perf_counter()
            rows_read = 0
            batch_count = 0
            for batch in reader.read_batch_iter(batch_size=batch_size):
                rows_read += batch.num_rows
                batch_count += 1
            elapsed = time.perf_counter() - start_t

            rate_records = rows_read / elapsed
            print(
                f"[BM_DataLake_Read_Iter_{batch_size:<5}] "
                f"BatchSize: {batch_size:>5} | Batches: {batch_count:>3} | "
                f"Elapsed: {elapsed * 1000:>6.2f} ms | "
                f"Throughput: {rate_records:>10.0f} rec/s"
            )

        # -----------------------------------------------------------------
        # Benchmark 3: Cryptographic SHA-256 Manifest Integrity Validation
        # -----------------------------------------------------------------
        iterations = 20
        start_t = time.perf_counter()
        for _ in range(iterations):
            ok, errors = reader.verify_integrity()
            assert ok is True
        elapsed = time.perf_counter() - start_t
        avg_ms = (elapsed / iterations) * 1000
        print(
            f"[BM_DataLake_Verify_Integrity ] "
            f"Iterations: {iterations:>4} | Avg Latency: {avg_ms:>6.3f} ms/verify | "
            f"Files Verified: {len(reader.partitions)}"
        )

        # -----------------------------------------------------------------
        # Benchmark 4: Partition Metadata Scanning & Discovery
        # -----------------------------------------------------------------
        # Create 10 partitioned datasets
        for i in range(10):
            ds_name = f"catalog_bench_ds_{i}"
            sub_table = gen.generate_trades(count=1000, instrument_id=i + 1)
            with DatasetWriter(
                dataset_id=ds_name,
                name=f"Catalog Bench {i}",
                kind=DatasetKind.TRADES,
                domain=DataDomain.MARKET_DATA,
                schema_name="rexi.market_data.trade",
                root_dir=temp_dir,
            ) as w:
                w.write_batch(sub_table)

        scan_iters = 50
        start_t = time.perf_counter()
        for _ in range(scan_iters):
            datasets = catalog.list_datasets()
            assert len(datasets) >= 10
        elapsed = time.perf_counter() - start_t
        avg_scan_us = (elapsed / scan_iters) * 1_000_000

        print(
            f"[BM_DataLake_Catalog_Scan    ] "
            f"Datasets: {len(datasets):>4} | Iterations: {scan_iters:>4} | "
            f"Avg Scan Latency: {avg_scan_us:>6.1f} µs"
        )

        print("=" * 70)
        print("ALL DATA LAKE BENCHMARKS COMPLETED SUCCESSFULLY")
        print("=" * 70)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    run_benchmarks()
