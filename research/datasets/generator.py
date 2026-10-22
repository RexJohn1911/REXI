"""Deterministic synthetic market data fixture generator for tests and benchmarks."""

import random
from typing import Any

import pyarrow as pa

from research.datasets.schema import (
    INSTRUMENT_DEFINITION_SCHEMA_V1,
    MARKET_STATUS_SCHEMA_V1,
    ORDER_BOOK_SNAPSHOT_SCHEMA_V1,
    ORDER_BOOK_UPDATE_SCHEMA_V1,
    REPLAY_EVENT_SCHEMA_V1,
    REPLAY_EVENT_SCHEMA_V2,
    TOP_OF_BOOK_SCHEMA_V1,
    TRADE_SCHEMA_V1,
)
from research.datasets.types import MarketDataMessageType, MarketSide, TradingStatus


class SyntheticMarketDataGenerator:
    """Fixed-seed PRNG deterministic market data event generator."""

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self._rng = random.Random(seed)

    def reset(self, seed: int | None = None) -> None:
        """Reset internal PRNG state to seed."""
        if seed is not None:
            self.seed = seed
        self._rng = random.Random(self.seed)

    def generate_trades(
        self,
        count: int,
        instrument_id: int = 1,
        venue_id: int = 1,
        feed_id: int = 1,
        base_price: int = 100_000,
        start_time_ns: int = 1_700_000_000_000_000_000,
        time_step_ns: int = 1_000_000,  # 1ms
    ) -> pa.Table:
        """Generate deterministic synthetic Trade messages conforming to TRADE_SCHEMA_V1."""
        rows: list[dict[str, Any]] = []
        current_time = start_time_ns
        seq = 1
        trade_id = 1000
        curr_price = base_price

        for i in range(count):
            price_delta = self._rng.choice([-10, -5, 0, 5, 10])
            curr_price = max(10, curr_price + price_delta)
            qty = self._rng.choice([10, 50, 100, 200, 500])
            aggressor = self._rng.choice([MarketSide.BUY.value, MarketSide.SELL.value])

            row = {
                "version": 1,
                "message_type": MarketDataMessageType.TRADE.value,
                "flags": 0,
                "venue_id": venue_id,
                "feed_id": feed_id,
                "instrument_id": instrument_id,
                "checksum": 0,
                "sequence_num": seq,
                "source_timestamp_ns": current_time,
                "receive_timestamp_ns": current_time + 500_000,  # +0.5ms gateway latency
                "trade_id": trade_id + i,
                "price": curr_price,
                "quantity": qty,
                "aggressor_side": aggressor,
                "maker_order_id": 10000 + i,
                "taker_order_id": 20000 + i,
            }
            rows.append(row)
            current_time += time_step_ns
            seq += 1

        return pa.Table.from_pylist(rows, schema=TRADE_SCHEMA_V1)

    def generate_top_of_book(
        self,
        count: int,
        instrument_id: int = 1,
        venue_id: int = 1,
        feed_id: int = 1,
        base_price: int = 100_000,
        spread: int = 10,
        start_time_ns: int = 1_700_000_000_000_000_000,
        time_step_ns: int = 500_000,  # 0.5ms
    ) -> pa.Table:
        """Generate deterministic Best Bid & Offer (BBO) quotes."""
        rows: list[dict[str, Any]] = []
        current_time = start_time_ns
        seq = 1
        curr_bid = base_price - (spread // 2)

        for _ in range(count):
            drift = self._rng.choice([-5, 0, 5])
            curr_bid = max(10, curr_bid + drift)
            curr_ask = curr_bid + spread
            bid_qty = self._rng.choice([100, 200, 500, 1000])
            ask_qty = self._rng.choice([100, 200, 500, 1000])

            row = {
                "version": 1,
                "message_type": MarketDataMessageType.TOP_OF_BOOK.value,
                "flags": 0,
                "venue_id": venue_id,
                "feed_id": feed_id,
                "instrument_id": instrument_id,
                "checksum": 0,
                "sequence_num": seq,
                "source_timestamp_ns": current_time,
                "receive_timestamp_ns": current_time + 200_000,
                "best_bid_price": curr_bid,
                "best_bid_quantity": bid_qty,
                "best_ask_price": curr_ask,
                "best_ask_quantity": ask_qty,
            }
            rows.append(row)
            current_time += time_step_ns
            seq += 1

        return pa.Table.from_pylist(rows, schema=TOP_OF_BOOK_SCHEMA_V1)

    def generate_order_book_updates(
        self,
        count: int,
        instrument_id: int = 1,
        venue_id: int = 1,
        feed_id: int = 1,
        base_price: int = 100_000,
        start_time_ns: int = 1_700_000_000_000_000_000,
        time_step_ns: int = 100_000,  # 0.1ms
    ) -> pa.Table:
        """Generate deterministic L3 OrderBook Add/Modify/Delete messages."""
        rows: list[dict[str, Any]] = []
        current_time = start_time_ns
        seq = 1
        active_orders: list[tuple[int, int, int]] = []  # (order_id, price, qty)
        order_counter = 1

        for _ in range(count):
            action_choice = (
                MarketDataMessageType.ORDER_BOOK_ADD.value
                if len(active_orders) < 5
                else self._rng.choice([4, 4, 5, 6])
            )

            side = self._rng.choice([MarketSide.BUY.value, MarketSide.SELL.value])
            price_offset = self._rng.randint(-20, 20)
            order_price = max(10, base_price + price_offset)
            qty = self._rng.choice([10, 20, 50, 100])

            order_id = order_counter
            priority_rank: int | None = None
            delta_qty: int | None = None

            if action_choice == MarketDataMessageType.ORDER_BOOK_ADD.value:
                order_counter += 1
                priority_rank = len(active_orders) + 1
                active_orders.append((order_id, order_price, qty))
            elif action_choice == MarketDataMessageType.ORDER_BOOK_MODIFY.value:
                # Modify an existing order
                existing = self._rng.choice(active_orders)
                order_id = existing[0]
                order_price = existing[1]
                delta_qty = 10
                qty = existing[2] + delta_qty
            else:  # Delete
                existing = active_orders.pop(self._rng.randint(0, len(active_orders) - 1))
                order_id = existing[0]
                order_price = existing[1]
                qty = existing[2]

            row = {
                "version": 1,
                "message_type": action_choice,
                "flags": 0,
                "venue_id": venue_id,
                "feed_id": feed_id,
                "instrument_id": instrument_id,
                "checksum": 0,
                "sequence_num": seq,
                "source_timestamp_ns": current_time,
                "receive_timestamp_ns": current_time + 100_000,
                "action": action_choice,
                "order_id": order_id,
                "side": side,
                "price": order_price,
                "quantity": qty,
                "priority_rank": priority_rank,
                "delta_quantity": delta_qty,
            }
            rows.append(row)
            current_time += time_step_ns
            seq += 1

        return pa.Table.from_pylist(rows, schema=ORDER_BOOK_UPDATE_SCHEMA_V1)

    def generate_order_book_snapshots(
        self,
        count: int,
        instrument_id: int = 1,
        venue_id: int = 1,
        feed_id: int = 1,
        base_price: int = 100_000,
        levels: int = 5,
        start_time_ns: int = 1_700_000_000_000_000_000,
        time_step_ns: int = 1_000_000_000,  # 1s
    ) -> pa.Table:
        """Generate deterministic L2 OrderBookDepthSnapshot messages conforming to schema."""
        rows: list[dict[str, Any]] = []
        current_time = start_time_ns
        seq = 1

        for _ in range(count):
            bid_list: list[dict[str, Any]] = []
            ask_list: list[dict[str, Any]] = []

            for lvl in range(levels):
                bid_list.append(
                    {
                        "price": base_price - (lvl + 1) * 10,
                        "quantity": 100 * (lvl + 1),
                        "order_count": lvl + 1,
                    }
                )
                ask_list.append(
                    {
                        "price": base_price + (lvl + 1) * 10,
                        "quantity": 150 * (lvl + 1),
                        "order_count": lvl + 1,
                    }
                )

            row = {
                "version": 1,
                "message_type": MarketDataMessageType.ORDER_BOOK_SNAPSHOT.value,
                "flags": 0,
                "venue_id": venue_id,
                "feed_id": feed_id,
                "instrument_id": instrument_id,
                "checksum": 0,
                "sequence_num": seq,
                "source_timestamp_ns": current_time,
                "receive_timestamp_ns": current_time + 100_000,
                "last_included_sequence": seq - 1,
                "bid_levels_count": len(bid_list),
                "ask_levels_count": len(ask_list),
                "bids": bid_list,
                "asks": ask_list,
            }
            rows.append(row)
            current_time += time_step_ns
            seq += 1

        return pa.Table.from_pylist(rows, schema=ORDER_BOOK_SNAPSHOT_SCHEMA_V1)

    def generate_market_status(
        self,
        count: int,
        instrument_id: int = 1,
        venue_id: int = 1,
        feed_id: int = 1,
        start_time_ns: int = 1_700_000_000_000_000_000,
        time_step_ns: int = 3_600_000_000_000,  # 1 hour
    ) -> pa.Table:
        """Generate deterministic MarketStatus messages conforming to schema."""
        rows: list[dict[str, Any]] = []
        current_time = start_time_ns
        seq = 1
        statuses = [
            TradingStatus.PRE_OPEN.value,
            TradingStatus.OPEN.value,
            TradingStatus.HALTED.value,
            TradingStatus.OPEN.value,
            TradingStatus.CLOSED.value,
        ]

        for i in range(count):
            st = statuses[i % len(statuses)]
            row = {
                "version": 1,
                "message_type": MarketDataMessageType.MARKET_STATUS.value,
                "flags": 0,
                "venue_id": venue_id,
                "feed_id": feed_id,
                "instrument_id": instrument_id,
                "checksum": 0,
                "sequence_num": seq,
                "source_timestamp_ns": current_time,
                "receive_timestamp_ns": current_time + 50_000,
                "status": st,
                "status_flags": 0,
            }
            rows.append(row)
            current_time += time_step_ns
            seq += 1

        return pa.Table.from_pylist(rows, schema=MARKET_STATUS_SCHEMA_V1)

    def generate_instrument_definitions(
        self,
        count: int,
        start_instrument_id: int = 1,
        venue_id: int = 1,
        feed_id: int = 1,
        start_time_ns: int = 1_700_000_000_000_000_000,
        time_step_ns: int = 1_000_000_000,
    ) -> pa.Table:
        """Generate deterministic InstrumentDefinition messages conforming to schema."""
        rows: list[dict[str, Any]] = []
        current_time = start_time_ns
        seq = 1

        for i in range(count):
            inst_id = start_instrument_id + i
            row = {
                "version": 1,
                "message_type": MarketDataMessageType.INSTRUMENT_DEFINITION.value,
                "flags": 0,
                "venue_id": venue_id,
                "feed_id": feed_id,
                "instrument_id": inst_id,
                "checksum": 0,
                "sequence_num": seq,
                "source_timestamp_ns": current_time,
                "receive_timestamp_ns": current_time + 50_000,
                "tick_size": 10,
                "lot_size": 1,
                "min_quantity": 1,
                "max_quantity": 1_000_000_000,
            }
            rows.append(row)
            current_time += time_step_ns
            seq += 1

        return pa.Table.from_pylist(rows, schema=INSTRUMENT_DEFINITION_SCHEMA_V1)

    def generate_replay_stream(
        self,
        count: int,
        instrument_id: int = 1,
        venue_id: int = 1,
        feed_id: int = 1,
        start_time_ns: int = 1_700_000_000_000_000_000,
        time_step_ns: int = 100_000,
        schema_version: str = "1.1.0",
    ) -> pa.Table:
        """Generate deterministic Phase 07 compatible unified ReplayEvent stream.

        Supports schema_version '1.0.0' (baseline) and '1.1.0' (full snapshot fidelity).
        """
        rows: list[dict[str, Any]] = []
        current_time = start_time_ns
        seq = 1

        allowed_types = [
            MarketDataMessageType.TOP_OF_BOOK.value,
            MarketDataMessageType.TRADE.value,
            MarketDataMessageType.ORDER_BOOK_ADD.value,
        ]
        if schema_version != "1.0.0":
            allowed_types.append(MarketDataMessageType.ORDER_BOOK_SNAPSHOT.value)

        for i in range(count):
            msg_type = self._rng.choice(allowed_types)

            row: dict[str, Any] = {
                "version": 1,
                "message_type": msg_type,
                "flags": 0,
                "venue_id": venue_id,
                "feed_id": feed_id,
                "instrument_id": instrument_id,
                "checksum": 0,
                "sequence_num": seq,
                "source_timestamp_ns": current_time,
                "receive_timestamp_ns": current_time + 50_000,
                "source": 1,  # events::SourceId::Internal
                "input_index": i,
                "order_id": None,
                "side": None,
                "price": None,
                "quantity": None,
                "trade_id": None,
                "aggressor_side": None,
                "maker_order_id": None,
                "taker_order_id": None,
                "best_bid_price": None,
                "best_bid_quantity": None,
                "best_ask_price": None,
                "best_ask_quantity": None,
                "priority_rank": None,
                "delta_quantity": None,
                "status": None,
                "status_flags": None,
                "tick_size": None,
                "lot_size": None,
                "min_quantity": None,
                "max_quantity": None,
            }

            if schema_version != "1.0.0":
                row.update(
                    {
                        "last_included_sequence": None,
                        "bid_levels_count": None,
                        "ask_levels_count": None,
                        "bids": None,
                        "asks": None,
                    }
                )

            if msg_type == MarketDataMessageType.TOP_OF_BOOK.value:
                row["best_bid_price"] = 100_000
                row["best_bid_quantity"] = 500
                row["best_ask_price"] = 100_010
                row["best_ask_quantity"] = 600
            elif msg_type == MarketDataMessageType.TRADE.value:
                row["trade_id"] = 5000 + i
                row["price"] = 100_005
                row["quantity"] = 100
                row["aggressor_side"] = MarketSide.BUY.value
                row["maker_order_id"] = 1000 + i
                row["taker_order_id"] = 2000 + i
            elif msg_type == MarketDataMessageType.ORDER_BOOK_ADD.value:
                row["order_id"] = 3000 + i
                row["side"] = MarketSide.BUY.value
                row["price"] = 100_000
                row["quantity"] = 50
                row["priority_rank"] = 1
            elif msg_type == MarketDataMessageType.ORDER_BOOK_SNAPSHOT.value:
                row["last_included_sequence"] = seq - 1
                row["bid_levels_count"] = 2
                row["ask_levels_count"] = 2
                row["bids"] = [
                    {"price": 99990, "quantity": 100, "order_count": 2},
                    {"price": 99980, "quantity": 200, "order_count": 3},
                ]
                row["asks"] = [
                    {"price": 100010, "quantity": 150, "order_count": 2},
                    {"price": 100020, "quantity": 250, "order_count": 4},
                ]

            rows.append(row)
            current_time += time_step_ns
            seq += 1

        selected_schema = (
            REPLAY_EVENT_SCHEMA_V1 if schema_version == "1.0.0" else REPLAY_EVENT_SCHEMA_V2
        )
        return pa.Table.from_pylist(rows, schema=selected_schema)
