"""Unit tests for deterministic SyntheticMarketDataGenerator."""

from research.datasets.generator import SyntheticMarketDataGenerator


def test_synthetic_trades_deterministic_reproducibility() -> None:
    gen1 = SyntheticMarketDataGenerator(seed=42)
    t1 = gen1.generate_trades(count=500, instrument_id=1)

    gen2 = SyntheticMarketDataGenerator(seed=42)
    t2 = gen2.generate_trades(count=500, instrument_id=1)

    assert t1.equals(t2)
    assert t1["price"].to_pylist() == t2["price"].to_pylist()
    assert t1["sequence_num"].to_pylist() == t2["sequence_num"].to_pylist()


def test_synthetic_top_of_book_monotonicity() -> None:
    gen = SyntheticMarketDataGenerator(seed=101)
    bbo = gen.generate_top_of_book(count=100, instrument_id=1, spread=10)

    # Check timestamps and sequence numbers are strictly increasing
    timestamps = bbo["source_timestamp_ns"].to_pylist()
    sequences = bbo["sequence_num"].to_pylist()

    for i in range(1, len(timestamps)):
        assert timestamps[i] > timestamps[i - 1]
        assert sequences[i] == sequences[i - 1] + 1

    # Check that ask > bid for every quote
    bids = bbo["best_bid_price"].to_pylist()
    asks = bbo["best_ask_price"].to_pylist()
    for b, a in zip(bids, asks, strict=True):
        assert a > b
        assert (a - b) == 10


def test_synthetic_replay_stream_generation() -> None:
    gen = SyntheticMarketDataGenerator(seed=202)
    replay = gen.generate_replay_stream(count=100, instrument_id=5)

    assert replay.num_rows == 100
    assert "source" in replay.column_names
    assert "input_index" in replay.column_names
    assert "message_type" in replay.column_names

    indices = replay["input_index"].to_pylist()
    assert indices == list(range(100))
