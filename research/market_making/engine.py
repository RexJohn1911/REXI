"""Market Making Engine implementation and BaseStrategy lifecycle integration."""

from typing import Any

import pyarrow as pa

from research.features.types import MicrostructureFeatureRecord
from research.market_making.guards import CompositeMarketGuard
from research.market_making.model import (
    build_raw_quotes,
    compute_optimal_half_spread,
    compute_reservation_price,
)
from research.market_making.types import (
    InventoryState,
    MarketMakingConfig,
    MarketQuoteSnapshot,
    QuoteDecision,
    QuoteIntent,
    QuoteSuppressionReason,
)
from research.strategies.base import SIGNAL_SCHEMA_V1, BaseStrategy
from research.strategies.types import (
    FillRecord,
    OrderIntent,
    OrderSide,
    OrderType,
    Signal,
    TimeInForce,
)


class MarketMakingStrategy(BaseStrategy):
    """Deterministic, inventory-aware market making strategy engine.

    Integrates the Avellaneda-Stoikov (2008) reservation-price model,
    adverse-selection quality guards, and strict 5-point temporal causality
    into the canonical REXI Strategy Laboratory.
    """

    def __init__(self, config: MarketMakingConfig | None = None) -> None:
        cfg = config or MarketMakingConfig(instrument_id=0)
        super().__init__(name="AvellanedaStoikovMarketMaker", config=cfg.__dict__)
        self.mm_config: MarketMakingConfig = cfg
        self.guard_system: CompositeMarketGuard = CompositeMarketGuard()

        # Authoritative internal inventory state
        self._inventory_state: InventoryState = InventoryState(
            instrument_id=self.mm_config.instrument_id,
            inventory=0,
            cash=1_000_000.0,
        )

        self._quote_decision_seq: int = 0
        self._order_seq: int = 0
        self._is_fitted: bool = True

    @property
    def inventory_state(self) -> InventoryState:
        """Current inventory and risk exposure state."""
        return self._inventory_state

    def reset(self) -> None:
        """Reset internal inventory and state for a clean replay."""
        self._inventory_state = InventoryState(
            instrument_id=self.mm_config.instrument_id,
            inventory=0,
            cash=1_000_000.0,
        )
        self._quote_decision_seq = 0
        self._order_seq = 0

    def fit(self, train_table: pa.Table) -> None:
        """In-sample calibration (e.g. estimating volatility or arrival intensity)."""
        self._is_fitted = True

    def on_fill(self, fill: FillRecord) -> None:
        """Authoritatively update inventory and portfolio state upon trade execution."""
        if fill.instrument_id != self.mm_config.instrument_id:
            return

        old_inv = self._inventory_state.inventory
        old_cost = self._inventory_state.average_entry_price
        fill_price_dollars = fill.price / self.mm_config.price_scale
        qty = fill.quantity
        side = fill.side

        delta_qty = qty if side == OrderSide.BUY else -qty
        new_inv = old_inv + delta_qty

        # Cash adjustment (including friction costs)
        notional_dollars = qty * fill_price_dollars
        cash_delta = (
            -(notional_dollars + fill.total_transaction_cost)
            if side == OrderSide.BUY
            else (notional_dollars - fill.total_transaction_cost)
        )
        new_cash = self._inventory_state.cash + cash_delta

        # PnL & Average cost tracking
        realized_delta = 0.0
        new_cost = old_cost

        if old_inv == 0:
            new_cost = fill_price_dollars
        elif (old_inv > 0 and side == OrderSide.BUY) or (old_inv < 0 and side == OrderSide.SELL):
            # Adding to existing position
            total_shares = abs(old_inv) + qty
            new_cost = ((abs(old_inv) * old_cost) + (qty * fill_price_dollars)) / total_shares
        elif (old_inv > 0 and side == OrderSide.SELL) or (old_inv < 0 and side == OrderSide.BUY):
            # Reducing position
            shares_closed = min(abs(old_inv), qty)
            if old_inv > 0:
                realized_delta = shares_closed * (fill_price_dollars - old_cost)
            else:
                realized_delta = shares_closed * (old_cost - fill_price_dollars)

            if abs(new_inv) == 0:
                new_cost = 0.0
            elif (old_inv > 0 and new_inv < 0) or (old_inv < 0 and new_inv > 0):
                # Flipped side
                new_cost = fill_price_dollars

        self._inventory_state = InventoryState(
            instrument_id=self.mm_config.instrument_id,
            inventory=new_inv,
            cash=new_cash,
            average_entry_price=new_cost,
            realized_pnl=self._inventory_state.realized_pnl + realized_delta,
            unrealized_pnl=self._inventory_state.unrealized_pnl,
            last_update_timestamp_ns=fill.fill_timestamp_ns,
        )

    def set_inventory_direct(
        self,
        inventory: int,
        cash: float = 1_000_000.0,
        average_entry_price: float = 0.0,
        timestamp_ns: int = 0,
    ) -> None:
        """Explicitly set inventory state (useful for unit tests and state syncing)."""
        self._inventory_state = InventoryState(
            instrument_id=self.mm_config.instrument_id,
            inventory=inventory,
            cash=cash,
            average_entry_price=average_entry_price,
            last_update_timestamp_ns=timestamp_ns,
        )

    def compute_quotes(
        self,
        quote_snapshot: MarketQuoteSnapshot,
        decision_timestamp_ns: int | None = None,
        feature_record: MicrostructureFeatureRecord | None = None,
    ) -> QuoteDecision:
        """Compute passive market-making bid/ask quotes from prevailing market state."""
        self._quote_decision_seq += 1
        dec_ts = (
            decision_timestamp_ns
            if decision_timestamp_ns is not None
            else quote_snapshot.available_timestamp_ns
        )

        mid_dollars = quote_snapshot.mid_dollars
        q = self._inventory_state.inventory

        # 1. Effective volatility
        vol = self.mm_config.volatility
        if feature_record is not None and feature_record.has_realized_volatility:
            if feature_record.realized_volatility is not None:
                vol = feature_record.realized_volatility

        # 2. Reservation Price
        try:
            r = compute_reservation_price(
                mid_price=mid_dollars,
                inventory=q,
                risk_aversion=self.mm_config.risk_aversion,
                volatility=vol,
                horizon=self.mm_config.terminal_horizon,
                skew_factor=self.mm_config.skew_factor,
            )
        except (ValueError, TypeError) as exc:
            # Fallback to mid if reservation price calculation fails
            r = mid_dollars
            suppression_reasons = [QuoteSuppressionReason.INVALID_RESERVATION_PRICE]
            bid_intent = QuoteIntent(
                side=OrderSide.BUY,
                price_ticks=0,
                price_dollars=0.0,
                quantity=0,
                distance_from_mid=0.0,
                is_post_only=True,
                is_suppressed=True,
                suppression_reason=QuoteSuppressionReason.INVALID_RESERVATION_PRICE,
            )
            ask_intent = QuoteIntent(
                side=OrderSide.SELL,
                price_ticks=0,
                price_dollars=0.0,
                quantity=0,
                distance_from_mid=0.0,
                is_post_only=True,
                is_suppressed=True,
                suppression_reason=QuoteSuppressionReason.INVALID_RESERVATION_PRICE,
            )
            return QuoteDecision(
                decision_timestamp_ns=dec_ts,
                instrument_id=self.mm_config.instrument_id,
                mid_price=mid_dollars,
                reservation_price=r,
                target_half_spread=self.mm_config.half_spread,
                inventory=q,
                bid_quote=bid_intent,
                ask_quote=ask_intent,
                is_valid=False,
                suppression_reasons=suppression_reasons,
                diagnostics={"error": str(exc)},
            )

        # 3. Target Half-Spread
        if self.mm_config.use_optimal_spread:
            half_spread = compute_optimal_half_spread(
                risk_aversion=self.mm_config.risk_aversion,
                order_arrival_intensity=self.mm_config.order_arrival_intensity,
                min_half_spread=self.mm_config.min_half_spread,
                max_half_spread=self.mm_config.max_half_spread,
            )
        else:
            half_spread = self.mm_config.half_spread

        # 4. Construct raw rounded quotes
        raw_bid, raw_ask = build_raw_quotes(
            mid_price=mid_dollars,
            reservation_price=r,
            half_spread=half_spread,
            config=self.mm_config,
        )

        # 5. Evaluate Guards
        filtered_bid, filtered_ask, reasons, guard_diag = self.guard_system.filter_quotes(
            bid_quote=raw_bid,
            ask_quote=raw_ask,
            quote_snapshot=quote_snapshot,
            inventory_state=self._inventory_state,
            config=self.mm_config,
            feature_record=feature_record,
            decision_timestamp_ns=dec_ts,
        )

        is_valid = not filtered_bid.is_suppressed or not filtered_ask.is_suppressed

        diagnostics: dict[str, Any] = {
            "decision_seq": self._quote_decision_seq,
            "raw_reservation_price": r,
            "inventory_penalty": mid_dollars - r,
            "effective_volatility": vol,
            "effective_half_spread": half_spread,
            "guards": guard_diag,
        }

        return QuoteDecision(
            decision_timestamp_ns=dec_ts,
            instrument_id=self.mm_config.instrument_id,
            mid_price=mid_dollars,
            reservation_price=r,
            target_half_spread=half_spread,
            inventory=q,
            bid_quote=filtered_bid,
            ask_quote=filtered_ask,
            is_valid=is_valid,
            suppression_reasons=reasons,
            diagnostics=diagnostics,
        )

    def create_order_intents(
        self,
        decision: QuoteDecision,
        actionable_timestamp_ns: int | None = None,
        latency_ns: int = 0,
    ) -> list[OrderIntent]:
        """Convert an active QuoteDecision into executable passive OrderIntent objects."""
        intents: list[OrderIntent] = []
        act_ts = (
            actionable_timestamp_ns
            if actionable_timestamp_ns is not None
            else decision.decision_timestamp_ns + latency_ns
        )

        if decision.has_active_bid:
            self._order_seq += 1
            bid_intent = OrderIntent(
                order_id=f"MM-BID-{self._order_seq:07d}",
                decision_timestamp_ns=decision.decision_timestamp_ns,
                actionable_timestamp_ns=act_ts,
                instrument_id=decision.instrument_id,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=decision.bid_quote.quantity,
                limit_price=decision.bid_quote.price_ticks,
                time_in_force=TimeInForce.IOC,
                metadata={
                    "is_post_only": decision.bid_quote.is_post_only,
                    "distance_from_mid": decision.bid_quote.distance_from_mid,
                    "reservation_price": decision.reservation_price,
                },
            )
            intents.append(bid_intent)

        if decision.has_active_ask:
            self._order_seq += 1
            ask_intent = OrderIntent(
                order_id=f"MM-ASK-{self._order_seq:07d}",
                decision_timestamp_ns=decision.decision_timestamp_ns,
                actionable_timestamp_ns=act_ts,
                instrument_id=decision.instrument_id,
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=decision.ask_quote.quantity,
                limit_price=decision.ask_quote.price_ticks,
                time_in_force=TimeInForce.IOC,
                metadata={
                    "is_post_only": decision.ask_quote.is_post_only,
                    "distance_from_mid": decision.ask_quote.distance_from_mid,
                    "reservation_price": decision.reservation_price,
                },
            )
            intents.append(ask_intent)

        return intents

    def on_features(self, record: MicrostructureFeatureRecord) -> Signal | None:
        """Stream feature event handler generating canonical Strategy Laboratory Signal."""
        if not record.has_bid or not record.has_ask:
            return None
        if record.best_bid_price is None or record.best_ask_price is None:
            return None
        if record.best_bid_quantity is None or record.best_ask_quantity is None:
            return None

        # Build market quote snapshot
        try:
            snapshot = MarketQuoteSnapshot(
                instrument_id=record.instrument_id,
                event_timestamp_ns=record.event_timestamp_ns,
                available_timestamp_ns=record.decision_timestamp_ns,
                best_bid_price=record.best_bid_price,
                best_bid_quantity=record.best_bid_quantity,
                best_ask_price=record.best_ask_price,
                best_ask_quantity=record.best_ask_quantity,
                price_scale=self.mm_config.price_scale,
                is_valid=not record.is_crossed,
            )
        except (ValueError, TypeError):
            return None

        decision = self.compute_quotes(
            quote_snapshot=snapshot,
            decision_timestamp_ns=record.decision_timestamp_ns,
            feature_record=record,
        )

        # Inventory rebalancing direction:
        # Long inventory -> direction = -1 (wants to sell to reduce risk)
        # Short inventory -> direction = +1 (wants to buy to cover short)
        # Flat -> direction = 0
        q = self._inventory_state.inventory
        if q > 0:
            direction = -1
            max_limit = self.mm_config.max_long_inventory
            target_weight = -min(1.0, q / max_limit) if max_limit > 0 else -0.5
        elif q < 0:
            direction = 1
            max_limit = self.mm_config.max_short_inventory
            target_weight = min(1.0, abs(q) / max_limit) if max_limit > 0 else 0.5
        else:
            direction = 0
            target_weight = 0.0

        skew_dist = abs(decision.reservation_price - decision.mid_price)
        strength = min(1.0, skew_dist / decision.target_half_spread)
        confidence = 1.0 if decision.is_two_sided else (0.5 if decision.is_valid else 0.0)

        sig_valid = decision.is_valid
        if not sig_valid:
            direction = 0
            target_weight = 0.0

        return Signal(
            decision_timestamp_ns=decision.decision_timestamp_ns,
            instrument_id=self.mm_config.instrument_id,
            direction=direction,
            target_weight=target_weight,
            strength=strength,
            confidence=confidence,
            is_valid=sig_valid,
            metadata={
                "reservation_price": decision.reservation_price,
                "mid_price": decision.mid_price,
                "inventory": q,
                "has_active_bid": decision.has_active_bid,
                "has_active_ask": decision.has_active_ask,
                "suppression_reasons": [r.value for r in decision.suppression_reasons],
            },
        )

    def generate_signals(self, features_table: pa.Table) -> pa.Table:
        """Process a market data or features table to generate a causal table of Signals."""
        n_rows = len(features_table)
        if n_rows == 0:
            return pa.Table.from_batches([], schema=SIGNAL_SCHEMA_V1)

        cols = features_table.column_names
        is_features = "mid_price" in cols

        if is_features:
            ev_ts_list = features_table["event_timestamp_ns"].to_pylist()
            dec_ts_list = features_table["decision_timestamp_ns"].to_pylist()
            bid_p_list = features_table["best_bid_price"].to_pylist()
            bid_q_list = features_table["best_bid_quantity"].to_pylist()
            ask_p_list = features_table["best_ask_price"].to_pylist()
            ask_q_list = features_table["best_ask_quantity"].to_pylist()
            crossed_list = (
                features_table["is_crossed"].to_pylist()
                if "is_crossed" in cols
                else [False] * n_rows
            )
        else:
            ev_ts_list = features_table["source_timestamp_ns"].to_pylist()
            dec_ts_list = features_table["receive_timestamp_ns"].to_pylist()
            bid_p_list = features_table["best_bid_price"].to_pylist()
            bid_q_list = features_table["best_bid_quantity"].to_pylist()
            ask_p_list = features_table["best_ask_price"].to_pylist()
            ask_q_list = features_table["best_ask_quantity"].to_pylist()
            crossed_list = [False] * n_rows

        dec_ts_arr: list[int] = []
        inst_id_arr: list[int] = []
        dir_arr: list[int] = []
        weight_arr: list[float] = []
        strength_arr: list[float] = []
        conf_arr: list[float] = []
        valid_arr: list[bool] = []

        for i in range(n_rows):
            dec_ts = dec_ts_list[i]
            ev_ts = ev_ts_list[i]
            bp = bid_p_list[i]
            bq = bid_q_list[i]
            ap = ask_p_list[i]
            aq = ask_q_list[i]
            is_crossed = crossed_list[i] or False

            # Validity check
            if bp is None or ap is None or bq is None or aq is None or bp <= 0 or ap <= 0:
                dec_ts_arr.append(dec_ts)
                inst_id_arr.append(self.mm_config.instrument_id)
                dir_arr.append(0)
                weight_arr.append(0.0)
                strength_arr.append(0.0)
                conf_arr.append(0.0)
                valid_arr.append(False)
                continue

            try:
                snapshot = MarketQuoteSnapshot(
                    instrument_id=self.mm_config.instrument_id,
                    event_timestamp_ns=ev_ts,
                    available_timestamp_ns=dec_ts,
                    best_bid_price=bp,
                    best_bid_quantity=bq,
                    best_ask_price=ap,
                    best_ask_quantity=aq,
                    price_scale=self.mm_config.price_scale,
                    is_valid=not is_crossed,
                )
                decision = self.compute_quotes(
                    quote_snapshot=snapshot,
                    decision_timestamp_ns=dec_ts,
                )

                q = self._inventory_state.inventory
                if q > 0:
                    d = -1
                    max_limit = self.mm_config.max_long_inventory
                    tw = -min(1.0, q / max_limit) if max_limit > 0 else -0.5
                elif q < 0:
                    d = 1
                    max_limit = self.mm_config.max_short_inventory
                    tw = min(1.0, abs(q) / max_limit) if max_limit > 0 else 0.5
                else:
                    d = 0
                    tw = 0.0

                skew_dist = abs(decision.reservation_price - decision.mid_price)
                str_val = min(1.0, skew_dist / decision.target_half_spread)
                c_val = 1.0 if decision.is_two_sided else (0.5 if decision.is_valid else 0.0)
                v_val = decision.is_valid

                if not v_val:
                    d = 0
                    tw = 0.0

                dec_ts_arr.append(dec_ts)
                inst_id_arr.append(self.mm_config.instrument_id)
                dir_arr.append(d)
                weight_arr.append(tw)
                strength_arr.append(str_val)
                conf_arr.append(c_val)
                valid_arr.append(v_val)

            except (ValueError, TypeError):
                dec_ts_arr.append(dec_ts)
                inst_id_arr.append(self.mm_config.instrument_id)
                dir_arr.append(0)
                weight_arr.append(0.0)
                strength_arr.append(0.0)
                conf_arr.append(0.0)
                valid_arr.append(False)

        arrays = [
            pa.array(dec_ts_arr, type=pa.int64()),
            pa.array(inst_id_arr, type=pa.int64()),
            pa.array(dir_arr, type=pa.int8()),
            pa.array(weight_arr, type=pa.float64()),
            pa.array(strength_arr, type=pa.float64()),
            pa.array(conf_arr, type=pa.float64()),
            pa.array(valid_arr, type=pa.bool_()),
        ]
        return pa.Table.from_arrays(arrays, schema=SIGNAL_SCHEMA_V1)
