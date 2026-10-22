"""Deterministic Microstructure Feature Engine for quantitative research and dataset enrichment."""

import collections
import math
from typing import Any

import pyarrow as pa

from research.features.schema import MICROSTRUCTURE_FEATURES_SCHEMA_V1
from research.features.types import (
    AggressorSide,
    FeatureEngineConfig,
    InvalidEventDataError,
    MicrostructureFeatureRecord,
)


class MicrostructureFeatureEngine:
    """Deterministic, point-in-time causal microstructure feature generator."""

    def __init__(self, instrument_id: int, config: FeatureEngineConfig | None = None) -> None:
        self.instrument_id = instrument_id
        self.config = config or FeatureEngineConfig()

        # State tracking
        self._last_event_time: int = 0
        self._out_of_order_count: int = 0

        # Current quote state
        self._has_bid: bool = False
        self._has_ask: bool = False
        self._is_crossed: bool = False
        self._bid_price: int = 0
        self._bid_qty: int = 0
        self._ask_price: int = 0
        self._ask_qty: int = 0

        # Level 2 state
        self._bid_depth_k: int = 0
        self._ask_depth_k: int = 0
        self._has_depth_imbalance: bool = False
        self._depth_imbalance_k: float = 0.0

        # History ring buffers
        self._mid_prices: collections.deque[float] = collections.deque(
            maxlen=self.config.volatility_window + self.config.return_lookback + 5
        )
        self._returns_history: collections.deque[float] = collections.deque(
            maxlen=self.config.volatility_window
        )
        self._ofi_history: collections.deque[int] = collections.deque(maxlen=self.config.ofi_window)
        self._trades_history: collections.deque[tuple[int, int, AggressorSide, int]] = (
            collections.deque(maxlen=self.config.trade_window)
        )
        self._price_changes: collections.deque[float] = collections.deque(
            maxlen=self.config.roll_window
        )
        self._last_trade_price: int = 0

        # VPIN bucket tracking
        self._vpin_curr_buy: int = 0
        self._vpin_curr_sell: int = 0
        self._vpin_curr_total: int = 0
        self._vpin_bucket_imbalances: collections.deque[float] = collections.deque(
            maxlen=self.config.vpin_num_buckets
        )

        # Most recent feature record
        self._current_record: MicrostructureFeatureRecord | None = None

    @property
    def current_features(self) -> MicrostructureFeatureRecord | None:
        """Get the latest computed feature record."""
        return self._current_record

    @property
    def out_of_order_count(self) -> int:
        """Count of dropped out-of-order events."""
        return self._out_of_order_count

    def reset(self) -> None:
        """Reset internal engine state."""
        self._last_event_time = 0
        self._out_of_order_count = 0
        self._has_bid = False
        self._has_ask = False
        self._is_crossed = False
        self._bid_price = 0
        self._bid_qty = 0
        self._ask_price = 0
        self._ask_qty = 0
        self._bid_depth_k = 0
        self._ask_depth_k = 0
        self._has_depth_imbalance = False
        self._depth_imbalance_k = 0.0
        self._mid_prices.clear()
        self._returns_history.clear()
        self._ofi_history.clear()
        self._trades_history.clear()
        self._price_changes.clear()
        self._last_trade_price = 0
        self._vpin_curr_buy = 0
        self._vpin_curr_sell = 0
        self._vpin_curr_total = 0
        self._vpin_bucket_imbalances.clear()
        self._current_record = None

    def on_top_of_book(
        self,
        event_time_ns: int,
        source_time_ns: int,
        seq: int,
        bid_price: int,
        bid_qty: int,
        ask_price: int,
        ask_qty: int,
    ) -> MicrostructureFeatureRecord | None:
        """Process a Top-of-Book / BBO update."""
        if not self._validate_timestamp(event_time_ns):
            return None

        decision_time_ns = max(event_time_ns, source_time_ns)

        # Prior valid quote state for OFI
        had_valid_quote = self._has_bid and self._has_ask and not self._is_crossed
        prev_b_p, prev_b_q = self._bid_price, self._bid_qty
        prev_a_p, prev_a_q = self._ask_price, self._ask_qty

        # Update Level 1 state
        self._bid_price = bid_price
        self._bid_qty = bid_qty
        self._ask_price = ask_price
        self._ask_qty = ask_qty

        self._has_bid = bid_price > 0 and bid_qty > 0
        self._has_ask = ask_price > 0 and ask_qty > 0

        spread: int | None = None
        rel_spread: float | None = None
        mid: float | None = None
        weighted_mid: float | None = None
        book_imbalance: float | None = None
        has_spread = False
        has_mid = False
        has_weighted_mid = False
        has_book_imbalance = False
        instant_ofi: int | None = None
        has_instant_ofi = False
        rolling_ofi: int | None = None
        has_rolling_ofi = False

        if self._has_bid and self._has_ask:
            self._is_crossed = bid_price >= ask_price
            if not self._is_crossed:
                spread = ask_price - bid_price
                mid = (bid_price + ask_price) * 0.5
                rel_spread = spread / mid if mid > 0 else 0.0
                has_spread = True
                has_mid = True

                total_qty = bid_qty + ask_qty
                if total_qty > 0:
                    weighted_mid = (bid_price * ask_qty + ask_price * bid_qty) / total_qty
                    book_imbalance = (bid_qty - ask_qty) / total_qty
                    has_weighted_mid = True
                    has_book_imbalance = True

                # Update mid returns and volatility
                self._update_mid_returns(mid)

                # Compute OFI (Cont, Kukanov & Stoikov 2014)
                if had_valid_quote:
                    instant_ofi, rolling_ofi = self._compute_ofi(
                        prev_b_p,
                        prev_b_q,
                        prev_a_p,
                        prev_a_q,
                        bid_price,
                        bid_qty,
                        ask_price,
                        ask_qty,
                    )
                    has_instant_ofi = True
                    has_rolling_ofi = len(self._ofi_history) >= self.config.ofi_window
            else:
                self._is_crossed = True
        else:
            self._is_crossed = False

        # Returns & Volatility features
        log_ret, vol, has_ret, has_vol = self._get_returns_and_vol()

        # Trade flow features
        (
            last_signed_vol,
            roll_trade_vol,
            roll_buy_vol,
            roll_sell_vol,
            tfi,
            vwap,
            has_trade,
            has_tfi,
            has_vwap,
        ) = self._get_trade_flow_stats()

        # Advanced models
        roll_spr, has_roll = self._get_roll_spread()
        vpin_val, has_vpin = self._get_vpin()

        record = MicrostructureFeatureRecord(
            instrument_id=self.instrument_id,
            sequence_num=seq,
            event_timestamp_ns=event_time_ns,
            source_timestamp_ns=source_time_ns,
            decision_timestamp_ns=decision_time_ns,
            best_bid_price=self._bid_price if self._has_bid else None,
            best_bid_quantity=self._bid_qty if self._has_bid else None,
            best_ask_price=self._ask_price if self._has_ask else None,
            best_ask_quantity=self._ask_qty if self._has_ask else None,
            spread=spread,
            relative_spread=rel_spread,
            mid_price=mid,
            weighted_mid_price=weighted_mid,
            book_imbalance_top=book_imbalance,
            bid_depth_k=self._bid_depth_k if self._has_depth_imbalance else None,
            ask_depth_k=self._ask_depth_k if self._has_depth_imbalance else None,
            depth_imbalance_k=self._depth_imbalance_k if self._has_depth_imbalance else None,
            instant_ofi=instant_ofi,
            rolling_ofi=rolling_ofi,
            last_signed_volume=last_signed_vol,
            rolling_trade_volume=roll_trade_vol,
            rolling_buy_volume=roll_buy_vol,
            rolling_sell_volume=roll_sell_vol,
            trade_flow_imbalance=tfi,
            rolling_vwap=vwap,
            log_return=log_ret,
            realized_volatility=vol,
            roll_spread=roll_spr,
            vpin=vpin_val,
            has_bid=self._has_bid,
            has_ask=self._has_ask,
            is_crossed=self._is_crossed,
            has_spread=has_spread,
            has_mid=has_mid,
            has_weighted_mid=has_weighted_mid,
            has_book_imbalance=has_book_imbalance,
            has_depth_imbalance=self._has_depth_imbalance,
            has_instant_ofi=has_instant_ofi,
            has_rolling_ofi=has_rolling_ofi,
            has_trade=has_trade,
            has_trade_flow=has_tfi,
            has_vwap=has_vwap,
            has_log_return=has_ret,
            has_realized_volatility=has_vol,
            has_roll_spread=has_roll,
            has_vpin=has_vpin,
        )

        self._current_record = record
        return record

    def on_trade(
        self,
        event_time_ns: int,
        source_time_ns: int,
        seq: int,
        price: int,
        quantity: int,
        aggressor_side: AggressorSide | int,
    ) -> MicrostructureFeatureRecord | None:
        """Process an executed public trade event."""
        if not self._validate_timestamp(event_time_ns):
            return None

        if price <= 0 or quantity <= 0:
            raise InvalidEventDataError(f"Invalid trade price ({price}) or quantity ({quantity})")

        decision_time_ns = max(event_time_ns, source_time_ns)
        side = (
            aggressor_side
            if isinstance(aggressor_side, AggressorSide)
            else AggressorSide(aggressor_side)
        )

        # Store trade into rolling trade buffer
        self._trades_history.append((price, quantity, side, event_time_ns))

        # Roll spread update
        if self._last_trade_price > 0:
            self._price_changes.append(float(price - self._last_trade_price))
        self._last_trade_price = price

        # VPIN update
        self._update_vpin(quantity, side)

        # Extract features
        (
            last_signed_vol,
            roll_trade_vol,
            roll_buy_vol,
            roll_sell_vol,
            tfi,
            vwap,
            has_trade,
            has_tfi,
            has_vwap,
        ) = self._get_trade_flow_stats()
        roll_spr, has_roll = self._get_roll_spread()
        vpin_val, has_vpin = self._get_vpin()
        log_ret, vol, has_ret, has_vol = self._get_returns_and_vol()

        spread = (
            (self._ask_price - self._bid_price)
            if (self._has_bid and self._has_ask and not self._is_crossed)
            else None
        )
        mid = (
            (self._bid_price + self._ask_price) * 0.5
            if (self._has_bid and self._has_ask and not self._is_crossed)
            else None
        )
        rel_spread = (
            (spread / mid)
            if (spread is not None and mid is not None and mid > 0)
            else None
        )

        tot_q = self._bid_qty + self._ask_qty
        weighted_mid = (
            (self._bid_price * self._ask_qty + self._ask_price * self._bid_qty) / tot_q
            if (tot_q > 0 and self._has_bid and self._has_ask and not self._is_crossed)
            else None
        )
        book_imb = (
            (self._bid_qty - self._ask_qty) / tot_q
            if (tot_q > 0 and self._has_bid and self._has_ask and not self._is_crossed)
            else None
        )

        record = MicrostructureFeatureRecord(
            instrument_id=self.instrument_id,
            sequence_num=seq,
            event_timestamp_ns=event_time_ns,
            source_timestamp_ns=source_time_ns,
            decision_timestamp_ns=decision_time_ns,
            best_bid_price=self._bid_price if self._has_bid else None,
            best_bid_quantity=self._bid_qty if self._has_bid else None,
            best_ask_price=self._ask_price if self._has_ask else None,
            best_ask_quantity=self._ask_qty if self._has_ask else None,
            spread=spread,
            relative_spread=rel_spread,
            mid_price=mid,
            weighted_mid_price=weighted_mid,
            book_imbalance_top=book_imb,
            bid_depth_k=self._bid_depth_k if self._has_depth_imbalance else None,
            ask_depth_k=self._ask_depth_k if self._has_depth_imbalance else None,
            depth_imbalance_k=self._depth_imbalance_k if self._has_depth_imbalance else None,
            instant_ofi=None,
            rolling_ofi=(
                sum(self._ofi_history)
                if len(self._ofi_history) >= self.config.ofi_window
                else None
            ),
            last_signed_volume=last_signed_vol,
            rolling_trade_volume=roll_trade_vol,
            rolling_buy_volume=roll_buy_vol,
            rolling_sell_volume=roll_sell_vol,
            trade_flow_imbalance=tfi,
            rolling_vwap=vwap,
            log_return=log_ret,
            realized_volatility=vol,
            roll_spread=roll_spr,
            vpin=vpin_val,
            has_bid=self._has_bid,
            has_ask=self._has_ask,
            is_crossed=self._is_crossed,
            has_spread=spread is not None,
            has_mid=mid is not None,
            has_weighted_mid=weighted_mid is not None,
            has_book_imbalance=book_imb is not None,
            has_depth_imbalance=self._has_depth_imbalance,
            has_instant_ofi=False,
            has_rolling_ofi=len(self._ofi_history) >= self.config.ofi_window,
            has_trade=has_trade,
            has_trade_flow=has_tfi,
            has_vwap=has_vwap,
            has_log_return=has_ret,
            has_realized_volatility=has_vol,
            has_roll_spread=has_roll,
            has_vpin=has_vpin,
        )

        self._current_record = record
        return record

    def on_depth_snapshot(
        self,
        event_time_ns: int,
        source_time_ns: int,
        seq: int,
        bids: list[dict[str, Any]],
        asks: list[dict[str, Any]],
    ) -> MicrostructureFeatureRecord | None:
        """Process an aggregated L2 depth snapshot."""
        if not self._validate_timestamp(event_time_ns):
            return None

        k = self.config.depth_levels
        bids_sorted = sorted(bids, key=lambda x: int(x["price"]), reverse=True)[:k]
        asks_sorted = sorted(asks, key=lambda x: int(x["price"]))[:k]

        bid_p = int(bids_sorted[0]["price"]) if bids_sorted else 0
        bid_q = int(bids_sorted[0]["quantity"]) if bids_sorted else 0
        ask_p = int(asks_sorted[0]["price"]) if asks_sorted else 0
        ask_q = int(asks_sorted[0]["quantity"]) if asks_sorted else 0

        # Update Level 1 state
        self.on_top_of_book(event_time_ns, source_time_ns, seq, bid_p, bid_q, ask_p, ask_q)

        # Multi-level depth accumulation
        bid_depth = sum(int(lvl["quantity"]) for lvl in bids_sorted)
        ask_depth = sum(int(lvl["quantity"]) for lvl in asks_sorted)
        tot_depth = bid_depth + ask_depth

        self._bid_depth_k = bid_depth
        self._ask_depth_k = ask_depth

        if tot_depth > 0 and not self._is_crossed:
            self._depth_imbalance_k = (bid_depth - ask_depth) / tot_depth
            self._has_depth_imbalance = True
        else:
            self._depth_imbalance_k = 0.0
            self._has_depth_imbalance = False

        if self._current_record is not None:
            # Reconstruct record with depth fields
            self._current_record = MicrostructureFeatureRecord(
                instrument_id=self._current_record.instrument_id,
                sequence_num=self._current_record.sequence_num,
                event_timestamp_ns=self._current_record.event_timestamp_ns,
                source_timestamp_ns=self._current_record.source_timestamp_ns,
                decision_timestamp_ns=self._current_record.decision_timestamp_ns,
                best_bid_price=self._current_record.best_bid_price,
                best_bid_quantity=self._current_record.best_bid_quantity,
                best_ask_price=self._current_record.best_ask_price,
                best_ask_quantity=self._current_record.best_ask_quantity,
                spread=self._current_record.spread,
                relative_spread=self._current_record.relative_spread,
                mid_price=self._current_record.mid_price,
                weighted_mid_price=self._current_record.weighted_mid_price,
                book_imbalance_top=self._current_record.book_imbalance_top,
                bid_depth_k=self._bid_depth_k if self._has_depth_imbalance else None,
                ask_depth_k=self._ask_depth_k if self._has_depth_imbalance else None,
                depth_imbalance_k=(
                    self._depth_imbalance_k if self._has_depth_imbalance else None
                ),
                instant_ofi=self._current_record.instant_ofi,
                rolling_ofi=self._current_record.rolling_ofi,
                last_signed_volume=self._current_record.last_signed_volume,
                rolling_trade_volume=self._current_record.rolling_trade_volume,
                rolling_buy_volume=self._current_record.rolling_buy_volume,
                rolling_sell_volume=self._current_record.rolling_sell_volume,
                trade_flow_imbalance=self._current_record.trade_flow_imbalance,
                rolling_vwap=self._current_record.rolling_vwap,
                log_return=self._current_record.log_return,
                realized_volatility=self._current_record.realized_volatility,
                roll_spread=self._current_record.roll_spread,
                vpin=self._current_record.vpin,
                has_bid=self._current_record.has_bid,
                has_ask=self._current_record.has_ask,
                is_crossed=self._current_record.is_crossed,
                has_spread=self._current_record.has_spread,
                has_mid=self._current_record.has_mid,
                has_weighted_mid=self._current_record.has_weighted_mid,
                has_book_imbalance=self._current_record.has_book_imbalance,
                has_depth_imbalance=self._has_depth_imbalance,
                has_instant_ofi=self._current_record.has_instant_ofi,
                has_rolling_ofi=self._current_record.has_rolling_ofi,
                has_trade=self._current_record.has_trade,
                has_trade_flow=self._current_record.has_trade_flow,
                has_vwap=self._current_record.has_vwap,
                has_log_return=self._current_record.has_log_return,
                has_realized_volatility=self._current_record.has_realized_volatility,
                has_roll_spread=self._current_record.has_roll_spread,
                has_vpin=self._current_record.has_vpin,
            )

        return self._current_record

    def extract_from_table(self, table: pa.Table, event_type: str = "auto") -> pa.Table:
        """Extract canonical microstructure feature table from an input market data PyArrow table.
        """
        if len(table) == 0:
            return pa.Table.from_arrays(
                [pa.array([], type=f.type) for f in MICROSTRUCTURE_FEATURES_SCHEMA_V1],
                schema=MICROSTRUCTURE_FEATURES_SCHEMA_V1,
            )

        col_names = set(table.column_names)
        if event_type == "auto":
            if "best_bid_price" in col_names and "best_ask_price" in col_names:
                event_type = "top_of_book"
            elif "aggressor_side" in col_names and "price" in col_names:
                event_type = "trade"
            elif "bids" in col_names and "asks" in col_names:
                event_type = "snapshot"
            else:
                raise InvalidEventDataError(f"Cannot infer event type from columns: {col_names}")

        records: list[MicrostructureFeatureRecord] = []

        # Stream row by row in deterministic chronological order
        pydict = table.to_pydict()
        n = len(table)

        src_ts_list = pydict.get("source_timestamp_ns", [0] * n)
        recv_ts_list = pydict.get("receive_timestamp_ns", [0] * n)
        seq_list = pydict.get("sequence_num", list(range(1, n + 1)))

        for i in range(n):
            ev_ts = src_ts_list[i]
            rec_ts = recv_ts_list[i]
            seq = seq_list[i]

            rec: MicrostructureFeatureRecord | None = None
            if event_type == "top_of_book":
                rec = self.on_top_of_book(
                    ev_ts,
                    rec_ts,
                    seq,
                    pydict["best_bid_price"][i],
                    pydict["best_bid_quantity"][i],
                    pydict["best_ask_price"][i],
                    pydict["best_ask_quantity"][i],
                )
            elif event_type == "trade":
                rec = self.on_trade(
                    ev_ts,
                    rec_ts,
                    seq,
                    pydict["price"][i],
                    pydict["quantity"][i],
                    pydict["aggressor_side"][i],
                )
            elif event_type == "snapshot":
                rec = self.on_depth_snapshot(
                    ev_ts,
                    rec_ts,
                    seq,
                    pydict["bids"][i],
                    pydict["asks"][i],
                )

            if rec is not None:
                records.append(rec)

        return self.records_to_table(records)

    @staticmethod
    def records_to_table(records: list[MicrostructureFeatureRecord]) -> pa.Table:
        """Convert a list of feature records into a PyArrow Table adhering to schema."""
        if not records:
            return pa.Table.from_arrays(
                [pa.array([], type=f.type) for f in MICROSTRUCTURE_FEATURES_SCHEMA_V1],
                schema=MICROSTRUCTURE_FEATURES_SCHEMA_V1,
            )

        arrays: list[pa.Array] = [
            pa.array([r.instrument_id for r in records], type=pa.uint32()),
            pa.array([r.sequence_num for r in records], type=pa.uint64()),
            pa.array([r.event_timestamp_ns for r in records], type=pa.int64()),
            pa.array([r.source_timestamp_ns for r in records], type=pa.int64()),
            pa.array([r.decision_timestamp_ns for r in records], type=pa.int64()),
            pa.array([r.best_bid_price for r in records], type=pa.int64()),
            pa.array([r.best_bid_quantity for r in records], type=pa.uint64()),
            pa.array([r.best_ask_price for r in records], type=pa.int64()),
            pa.array([r.best_ask_quantity for r in records], type=pa.uint64()),
            pa.array([r.spread for r in records], type=pa.int64()),
            pa.array([r.relative_spread for r in records], type=pa.float64()),
            pa.array([r.mid_price for r in records], type=pa.float64()),
            pa.array([r.weighted_mid_price for r in records], type=pa.float64()),
            pa.array([r.book_imbalance_top for r in records], type=pa.float64()),
            pa.array([r.bid_depth_k for r in records], type=pa.uint64()),
            pa.array([r.ask_depth_k for r in records], type=pa.uint64()),
            pa.array([r.depth_imbalance_k for r in records], type=pa.float64()),
            pa.array([r.instant_ofi for r in records], type=pa.int64()),
            pa.array([r.rolling_ofi for r in records], type=pa.int64()),
            pa.array([r.last_signed_volume for r in records], type=pa.int64()),
            pa.array([r.rolling_trade_volume for r in records], type=pa.uint64()),
            pa.array([r.rolling_buy_volume for r in records], type=pa.uint64()),
            pa.array([r.rolling_sell_volume for r in records], type=pa.uint64()),
            pa.array([r.trade_flow_imbalance for r in records], type=pa.float64()),
            pa.array([r.rolling_vwap for r in records], type=pa.float64()),
            pa.array([r.log_return for r in records], type=pa.float64()),
            pa.array([r.realized_volatility for r in records], type=pa.float64()),
            pa.array([r.roll_spread for r in records], type=pa.float64()),
            pa.array([r.vpin for r in records], type=pa.float64()),
            pa.array([r.has_bid for r in records], type=pa.bool_()),
            pa.array([r.has_ask for r in records], type=pa.bool_()),
            pa.array([r.is_crossed for r in records], type=pa.bool_()),
            pa.array([r.has_spread for r in records], type=pa.bool_()),
            pa.array([r.has_mid for r in records], type=pa.bool_()),
            pa.array([r.has_weighted_mid for r in records], type=pa.bool_()),
            pa.array([r.has_book_imbalance for r in records], type=pa.bool_()),
            pa.array([r.has_depth_imbalance for r in records], type=pa.bool_()),
            pa.array([r.has_instant_ofi for r in records], type=pa.bool_()),
            pa.array([r.has_rolling_ofi for r in records], type=pa.bool_()),
            pa.array([r.has_trade for r in records], type=pa.bool_()),
            pa.array([r.has_trade_flow for r in records], type=pa.bool_()),
            pa.array([r.has_vwap for r in records], type=pa.bool_()),
            pa.array([r.has_log_return for r in records], type=pa.bool_()),
            pa.array([r.has_realized_volatility for r in records], type=pa.bool_()),
            pa.array([r.has_roll_spread for r in records], type=pa.bool_()),
            pa.array([r.has_vpin for r in records], type=pa.bool_()),
        ]

        return pa.Table.from_arrays(arrays, schema=MICROSTRUCTURE_FEATURES_SCHEMA_V1)

    # -------------------------------------------------------------------------
    # Internal Calculation Helpers
    # -------------------------------------------------------------------------

    def _validate_timestamp(self, event_time_ns: int) -> bool:
        if self._last_event_time > 0 and event_time_ns < self._last_event_time:
            self._out_of_order_count += 1
            return False
        self._last_event_time = event_time_ns
        return True

    def _compute_ofi(
        self,
        prev_b_p: int,
        prev_b_q: int,
        prev_a_p: int,
        prev_a_q: int,
        curr_b_p: int,
        curr_b_q: int,
        curr_a_p: int,
        curr_a_q: int,
    ) -> tuple[int, int | None]:
        if curr_b_p > prev_b_p:
            delta_b = curr_b_q
        elif curr_b_p == prev_b_p:
            delta_b = curr_b_q - prev_b_q
        else:
            delta_b = -prev_b_q

        if curr_a_p < prev_a_p:
            delta_a = -curr_a_q
        elif curr_a_p == prev_a_p:
            delta_a = -(curr_a_q - prev_a_q)
        else:
            delta_a = prev_a_q

        instant_ofi = delta_b + delta_a
        self._ofi_history.append(instant_ofi)

        rolling_ofi = (
            sum(self._ofi_history)
            if len(self._ofi_history) >= self.config.ofi_window
            else None
        )
        return instant_ofi, rolling_ofi

    def _update_mid_returns(self, current_mid: float) -> None:
        if current_mid <= 0:
            return
        self._mid_prices.append(current_mid)
        lookback = max(1, self.config.return_lookback)
        if len(self._mid_prices) > lookback:
            past_mid = self._mid_prices[-1 - lookback]
            if past_mid > 0:
                ret = math.log(current_mid / past_mid)
                self._returns_history.append(ret)

    def _get_returns_and_vol(self) -> tuple[float | None, float | None, bool, bool]:
        lookback = max(1, self.config.return_lookback)
        has_ret = len(self._mid_prices) > lookback
        log_ret = self._returns_history[-1] if self._returns_history else None

        win = self.config.volatility_window
        has_vol = len(self._returns_history) >= win and win >= 2
        vol: float | None = None
        if has_vol:
            rets = list(self._returns_history)[-win:]
            mean = sum(rets) / len(rets)
            sum_sq = sum((x - mean) ** 2 for x in rets)
            vol = math.sqrt(sum_sq / (len(rets) - 1))

        return log_ret, vol, has_ret, has_vol

    def _get_trade_flow_stats(
        self,
    ) -> tuple[
        int | None,
        int | None,
        int | None,
        int | None,
        float | None,
        float | None,
        bool,
        bool,
        bool,
    ]:
        if not self._trades_history:
            return None, None, None, None, None, None, False, False, False

        last_p, last_q, last_side, _ = self._trades_history[-1]
        last_signed_vol = last_q if last_side == AggressorSide.BUY else -last_q

        win = self.config.trade_window
        recent_trades = list(self._trades_history)[-win:]
        tot_vol = sum(t[1] for t in recent_trades)
        buy_vol = sum(t[1] for t in recent_trades if t[2] == AggressorSide.BUY)
        sell_vol = sum(t[1] for t in recent_trades if t[2] == AggressorSide.SELL)

        price_qty_sum = sum(t[0] * t[1] for t in recent_trades)
        vwap = (price_qty_sum / tot_vol) if tot_vol > 0 else None
        tfi = ((buy_vol - sell_vol) / tot_vol) if tot_vol > 0 else None

        has_tfi = len(recent_trades) >= win and tot_vol > 0
        has_vwap = tot_vol > 0

        return (
            last_signed_vol,
            tot_vol,
            buy_vol,
            sell_vol,
            tfi,
            vwap,
            True,
            has_tfi,
            has_vwap,
        )

    def _get_roll_spread(self) -> tuple[float | None, bool]:
        win = self.config.roll_window
        if len(self._price_changes) < win or win < 3:
            return None, False

        diffs = list(self._price_changes)[-win:]
        mean = sum(diffs) / len(diffs)
        cov_sum = sum((diffs[i] - mean) * (diffs[i - 1] - mean) for i in range(1, len(diffs)))
        gamma_1 = cov_sum / (len(diffs) - 1)

        if gamma_1 < 0.0:
            roll_spread = 2.0 * math.sqrt(-gamma_1)
            return roll_spread, True
        return None, False

    def _update_vpin(self, quantity: int, side: AggressorSide) -> None:
        bucket_vol = self.config.vpin_bucket_volume
        if bucket_vol <= 0:
            return

        remaining = quantity
        while remaining > 0:
            space = bucket_vol - self._vpin_curr_total
            fill = min(remaining, space)
            if side == AggressorSide.BUY:
                self._vpin_curr_buy += fill
            else:
                self._vpin_curr_sell += fill
            self._vpin_curr_total += fill
            remaining -= fill

            if self._vpin_curr_total >= bucket_vol:
                abs_imb = abs(self._vpin_curr_buy - self._vpin_curr_sell)
                self._vpin_bucket_imbalances.append(float(abs_imb))
                self._vpin_curr_buy = 0
                self._vpin_curr_sell = 0
                self._vpin_curr_total = 0

    def _get_vpin(self) -> tuple[float | None, bool]:
        num_b = self.config.vpin_num_buckets
        if len(self._vpin_bucket_imbalances) < num_b or num_b <= 0:
            return None, False

        imbalances = list(self._vpin_bucket_imbalances)[-num_b:]
        denom = num_b * self.config.vpin_bucket_volume
        if denom > 0:
            vpin_val = sum(imbalances) / denom
            return vpin_val, True
        return None, False
