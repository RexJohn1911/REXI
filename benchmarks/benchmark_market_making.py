"""Performance benchmarks for REXI Market Making Engine (Phase 12)."""

import platform
import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.market_making.engine import MarketMakingStrategy
from research.market_making.types import MarketMakingConfig, MarketQuoteSnapshot


def run_benchmark() -> None:
    print("=" * 70)
    print("REXI MARKET MAKING ENGINE (PHASE 12) PERFORMANCE BENCHMARKS")
    print("=" * 70)
    print(f"Platform: {platform.system()} {platform.machine()} ({platform.processor()})")
    print(f"Python: {platform.python_version()}")
    print("=" * 70)

    config = MarketMakingConfig(
        instrument_id=1,
        tick_size=0.01,
        price_scale=100.0,
        quote_size=100,
        risk_aversion=0.1,
        volatility=0.02,
        terminal_horizon=1.0,
        half_spread=0.05,
    )
    strategy = MarketMakingStrategy(config)

    # Pre-generate 100,000 market quote snapshots
    n_quotes = 100_000
    snapshots: list[MarketQuoteSnapshot] = []
    base_ts = 1_000_000_000

    for i in range(n_quotes):
        bid_p = 10000 + (i % 20)
        ask_p = bid_p + 10
        ts = base_ts + i * 1000
        snap = MarketQuoteSnapshot(
            instrument_id=1,
            event_timestamp_ns=ts,
            available_timestamp_ns=ts,
            best_bid_price=bid_p,
            best_bid_quantity=500,
            best_ask_price=ask_p,
            best_ask_quantity=500,
            price_scale=100.0,
        )
        snapshots.append(snap)

    # Warmup
    for i in range(1_000):
        strategy.compute_quotes(snapshots[i])

    strategy.reset()

    # Timed run: 100,000 quote decisions
    start_time = time.perf_counter()
    for snap in snapshots:
        strategy.compute_quotes(snap)
    elapsed = time.perf_counter() - start_time

    rate = n_quotes / elapsed
    latency_us = (elapsed / n_quotes) * 1_000_000.0

    print(f"Quotes Processed:     {n_quotes:,}")
    print(f"Total Elapsed Time:   {elapsed:.4f} s")
    print(f"Decision Throughput:  {rate:,.1f} decisions/sec")
    print(f"Mean Decision Latency:{latency_us:.2f} µs/decision")
    print("=" * 70)


if __name__ == "__main__":
    run_benchmark()
