"""Deterministic event-driven backtesting engine for market-order strategy evaluation.

EXECUTION & TIMING ASSUMPTIONS:
1. Strict Temporal Causality:
   T_event <= T_available <= T_decision <= T_actionable <= T_fill
   An order can NEVER fill at a price observed prior to T_actionable.
2. Market-Order Execution:
   - Market orders cross the prevailing BBO (Buy at Ask, Sell at Bid).
   - In accordance with Stage 2 scope, LIMIT orders are strictly rejected.
3. Liquidity & Displayed Depth:
   - By default, orders are bounded by displayed top-of-book depth (best_bid_quantity
     or best_ask_quantity).
   - If order quantity exceeds displayed depth, the engine either rejects the order
     (allow_partial_fills=False) or executes a partial fill (allow_partial_fills=True).
4. Equal-Timestamp Deterministic Sequence:
   When multiple market updates or order events share the exact same timestamp:
     Step A: Apply incoming market quote updates.
     Step B: Execute pending orders whose actionable_timestamp_ns <= current_timestamp_ns.
     Step C: Call strategy on_features / generate_signals at current_timestamp_ns.
     Step D: Process new order intents (if actionable_timestamp_ns == current_timestamp_ns).
"""

import math
from dataclasses import dataclass
from typing import Any

import pyarrow as pa

from research.backtesting.costs import CostModelConfig, TransactionCostCalculator
from research.backtesting.exceptions import (
    BacktestConfigurationError,
    StaleQuoteError,
    UnsupportedOrderTypeError,
)
from research.strategies.base import BaseStrategy
from research.strategies.types import (
    FillRecord,
    OrderIntent,
    OrderSide,
    OrderType,
    PositionState,
    validate_temporal_coordinates,
)


@dataclass(frozen=True)
class BacktestEngineConfig:
    """Configuration for deterministic backtest execution.

    Liquidity Enforcement vs. Unlimited-Depth Approximation:
    - enforce_liquidity_limits=True (default): Orders are strictly bounded by prevailing
      top-of-book displayed depth. Fills consume displayed size across sequential orders within
      the same quote snapshot.
    - enforce_liquidity_limits=False: Orders execute under an explicit unlimited-depth
      simplification where the quoted touch is assumed to have infinite liquidity.
    """

    initial_cash: float = 1_000_000.0
    execution_latency_ns: int = 0  # Latency between decision and actionable time
    max_fill_fraction_of_depth: float = 1.0  # Max allowable fraction of top depth
    allow_partial_fills: bool = False
    price_scale: float = 100.0  # Ticks per dollar (e.g. cents = 100.0)
    cost_config: CostModelConfig | None = None
    enforce_liquidity_limits: bool = True  # If True, checks against top-of-book displayed depth

    def __post_init__(self) -> None:
        if self.initial_cash <= 0.0 or not math.isfinite(self.initial_cash):
            raise BacktestConfigurationError("initial_cash must be positive and finite.")
        if self.execution_latency_ns < 0:
            raise BacktestConfigurationError("execution_latency_ns cannot be negative.")
        if not (0.0 < self.max_fill_fraction_of_depth <= 1.0):
            raise BacktestConfigurationError(
                "max_fill_fraction_of_depth must be in (0.0, 1.0]."
            )
        if self.price_scale <= 0.0 or not math.isfinite(self.price_scale):
            raise BacktestConfigurationError("price_scale must be positive and finite.")


@dataclass(frozen=True)
class BacktestSnapshot:
    """Point-in-time portfolio valuation snapshot."""

    timestamp_ns: int
    cash: float
    position_qty: int
    market_mid_price: float
    portfolio_equity: float
    realized_pnl: float
    unrealized_pnl: float
    cumulative_spread_cost: float
    cumulative_slippage_cost: float
    cumulative_exchange_fees: float
    cumulative_regulatory_fees: float
    cumulative_turnover: float

    @property
    def cumulative_friction_cost(self) -> float:
        """Total cumulative transaction costs."""
        return (
            self.cumulative_spread_cost
            + self.cumulative_slippage_cost
            + self.cumulative_exchange_fees
            + self.cumulative_regulatory_fees
        )


@dataclass(frozen=True)
class BacktestResult:
    """Complete, immutable output of a deterministic backtest execution run."""

    engine_config: BacktestEngineConfig
    initial_cash: float
    final_cash: float
    final_equity: float
    final_position_qty: int
    gross_pnl: float
    net_pnl: float
    total_trades: int
    total_volume_traded: int
    total_turnover: float
    total_spread_cost: float
    total_slippage_cost: float
    total_exchange_fees: float
    total_regulatory_fees: float
    total_friction_cost: float
    fills: list[FillRecord]
    orders: list[OrderIntent]
    rejected_orders: list[tuple[OrderIntent, str]]
    snapshots: list[BacktestSnapshot]

    def to_equity_table(self) -> pa.Table:
        """Convert portfolio snapshots to a PyArrow table for time-series analysis."""
        if len(self.snapshots) == 0:
            return pa.Table.from_batches([])

        cols: dict[str, list[Any]] = {
            "timestamp_ns": [s.timestamp_ns for s in self.snapshots],
            "cash": [s.cash for s in self.snapshots],
            "position_qty": [s.position_qty for s in self.snapshots],
            "market_mid_price": [s.market_mid_price for s in self.snapshots],
            "portfolio_equity": [s.portfolio_equity for s in self.snapshots],
            "realized_pnl": [s.realized_pnl for s in self.snapshots],
            "unrealized_pnl": [s.unrealized_pnl for s in self.snapshots],
            "cumulative_spread_cost": [s.cumulative_spread_cost for s in self.snapshots],
            "cumulative_slippage_cost": [s.cumulative_slippage_cost for s in self.snapshots],
            "cumulative_exchange_fees": [s.cumulative_exchange_fees for s in self.snapshots],
            "cumulative_regulatory_fees": [s.cumulative_regulatory_fees for s in self.snapshots],
            "cumulative_turnover": [s.cumulative_turnover for s in self.snapshots],
        }
        return pa.Table.from_pydict(cols)


class DeterministicBacktestEngine:
    """Event-driven, point-in-time causal backtesting engine."""

    def __init__(self, config: BacktestEngineConfig | None = None) -> None:
        self.config = config or BacktestEngineConfig()
        cost_cfg = self.config.cost_config or CostModelConfig(price_scale=self.config.price_scale)
        self.cost_calculator = TransactionCostCalculator(cost_cfg)

        # Portfolio state
        self._cash: float = self.config.initial_cash
        self._position: PositionState = PositionState(instrument_id=0)
        self._gross_realized_pnl: float = 0.0

        # Market state tracking
        self._current_time_ns: int = 0
        self._last_quote_event_time_ns: int = 0
        self._last_quote_avail_time_ns: int = 0
        self._best_bid_price: int | None = None
        self._best_bid_qty: int | None = None
        self._best_ask_price: int | None = None
        self._best_ask_qty: int | None = None
        self._realized_volatility: float = 0.0

        # Queues and logs
        self._pending_orders: list[OrderIntent] = []
        self._fills: list[FillRecord] = []
        self._all_orders: list[OrderIntent] = []
        self._rejected_orders: list[tuple[OrderIntent, str]] = []
        self._snapshots: list[BacktestSnapshot] = []

        # Friction totals
        self._total_spread_cost: float = 0.0
        self._total_slippage_cost: float = 0.0
        self._total_exchange_fees: float = 0.0
        self._total_regulatory_fees: float = 0.0
        self._total_turnover: float = 0.0
        self._total_volume_traded: int = 0
        self._fill_counter: int = 0

    def reset(self) -> None:
        """Reset internal engine state for a clean replay."""
        self._cash = self.config.initial_cash
        self._position = PositionState(instrument_id=0)
        self._gross_realized_pnl = 0.0
        self._current_time_ns = 0
        self._last_quote_event_time_ns = 0
        self._last_quote_avail_time_ns = 0
        self._best_bid_price = None
        self._best_bid_qty = None
        self._best_ask_price = None
        self._best_ask_qty = None
        self._realized_volatility = 0.0
        self._pending_orders.clear()
        self._fills.clear()
        self._all_orders.clear()
        self._rejected_orders.clear()
        self._snapshots.clear()
        self._total_spread_cost = 0.0
        self._total_slippage_cost = 0.0
        self._total_exchange_fees = 0.0
        self._total_regulatory_fees = 0.0
        self._total_turnover = 0.0
        self._total_volume_traded = 0
        self._fill_counter = 0

    def run(self, market_table: pa.Table, strategy: BaseStrategy) -> BacktestResult:
        """Run an end-to-end event-driven backtest against a market data table.

        Accepts tables conforming to MICROSTRUCTURE_FEATURES_SCHEMA_V1 or TOP_OF_BOOK_SCHEMA_V1.
        """
        self.reset()
        n_rows = len(market_table)
        if n_rows == 0:
            return self._build_result()

        # Identify column names
        cols = market_table.column_names
        is_feature_table = "mid_price" in cols

        # Extract columns as Python lists for low-overhead sequential iteration
        if is_feature_table:
            event_ts_list = market_table["event_timestamp_ns"].to_pylist()
            avail_ts_list = market_table["decision_timestamp_ns"].to_pylist()
            bid_p_list = market_table["best_bid_price"].to_pylist()
            bid_q_list = market_table["best_bid_quantity"].to_pylist()
            ask_p_list = market_table["best_ask_price"].to_pylist()
            ask_q_list = market_table["best_ask_quantity"].to_pylist()
            vol_list = (
                market_table["realized_volatility"].to_pylist()
                if "realized_volatility" in cols
                else [0.0] * n_rows
            )
        else:
            event_ts_list = market_table["source_timestamp_ns"].to_pylist()
            avail_ts_list = market_table["receive_timestamp_ns"].to_pylist()
            bid_p_list = market_table["best_bid_price"].to_pylist()
            bid_q_list = market_table["best_bid_quantity"].to_pylist()
            ask_p_list = market_table["best_ask_price"].to_pylist()
            ask_q_list = market_table["best_ask_quantity"].to_pylist()
            vol_list = [0.0] * n_rows

        # Pre-generate signals from strategy if table-based
        signals_table = strategy.generate_signals(market_table)
        target_weights = signals_table["target_weight"].to_pylist()
        is_valids = signals_table["is_valid"].to_pylist()
        dec_ts_list = signals_table["decision_timestamp_ns"].to_pylist()

        order_seq = 0

        # Sequential event loop
        for i in range(n_rows):
            ev_ts = event_ts_list[i]
            av_ts = avail_ts_list[i]
            self._current_time_ns = av_ts

            # Step A: Update market quote state
            self._update_quote(
                event_ts=ev_ts,
                avail_ts=av_ts,
                bid_price=bid_p_list[i],
                bid_qty=bid_q_list[i],
                ask_price=ask_p_list[i],
                ask_qty=ask_q_list[i],
                vol=vol_list[i] or 0.0,
            )

            # Step B: Process pending orders whose actionable_time <= av_ts
            self._process_pending_orders(current_timestamp_ns=av_ts)

            # Step C: Evaluate strategy signal at current_timestamp_ns
            sig_valid = is_valids[i]
            sig_weight = target_weights[i]
            dec_ts = dec_ts_list[i]

            # Enforce non-lookahead invariant on strategy decision
            if dec_ts < av_ts:
                raise StaleQuoteError(
                    f"Decision timestamp {dec_ts} precedes available timestamp {av_ts}"
                )

            # Determine desired position based on target weight
            # Assuming notional position sizing based on portfolio equity and current mid
            curr_mid = self._get_current_mid_dollars()
            if sig_valid and curr_mid > 0.0:
                current_equity = self._calculate_current_equity(curr_mid)
                target_notional = current_equity * sig_weight
                target_qty = round(target_notional / curr_mid)

                qty_diff = target_qty - self._position.quantity
                if qty_diff != 0:
                    order_seq += 1
                    order_side = OrderSide.BUY if qty_diff > 0 else OrderSide.SELL
                    actionable_ts = dec_ts + self.config.execution_latency_ns
                    intent = OrderIntent(
                        order_id=f"ORD-{order_seq:06d}",
                        decision_timestamp_ns=dec_ts,
                        actionable_timestamp_ns=actionable_ts,
                        instrument_id=self._position.instrument_id,
                        side=order_side,
                        order_type=OrderType.MARKET,
                        quantity=abs(qty_diff),
                        signal_event_timestamp_ns=ev_ts,
                        signal_available_timestamp_ns=av_ts,
                    )
                    self._submit_order(intent)

            # Step D: Execute orders that are actionable at current time
            self._process_pending_orders(current_timestamp_ns=av_ts)

            # Record snapshot
            self._record_snapshot(av_ts)

        return self._build_result()

    def submit_order_direct(self, order: OrderIntent) -> None:
        """Directly submit an order intent (for testing and streaming workflows)."""
        self._submit_order(order)

    def process_pending_orders_direct(self, timestamp_ns: int) -> None:
        """Directly trigger pending order evaluation at a designated timestamp."""
        self._process_pending_orders(timestamp_ns)

    def update_quote_direct(
        self,
        event_ts: int,
        avail_ts: int,
        bid_price: int | None,
        bid_qty: int | None,
        ask_price: int | None,
        ask_qty: int | None,
        vol: float = 0.0,
    ) -> None:
        """Directly update engine quote state (for testing)."""
        self._update_quote(
            event_ts=event_ts,
            avail_ts=avail_ts,
            bid_price=bid_price,
            bid_qty=bid_qty,
            ask_price=ask_price,
            ask_qty=ask_qty,
            vol=vol,
        )

    def _update_quote(
        self,
        event_ts: int,
        avail_ts: int,
        bid_price: int | None,
        bid_qty: int | None,
        ask_price: int | None,
        ask_qty: int | None,
        vol: float,
    ) -> None:
        if event_ts > avail_ts:
            raise StaleQuoteError(
                f"Physical causality violation: event_ts ({event_ts}) > avail_ts ({avail_ts})"
            )
        self._last_quote_event_time_ns = event_ts
        self._last_quote_avail_time_ns = avail_ts
        self._best_bid_price = bid_price
        self._best_bid_qty = bid_qty
        self._best_ask_price = ask_price
        self._best_ask_qty = ask_qty
        self._realized_volatility = vol

    def _submit_order(self, order: OrderIntent) -> None:
        """Validate and queue an incoming order intent."""
        self._all_orders.append(order)

        # Enforce market-orders-only constraint
        if order.order_type != OrderType.MARKET:
            msg = f"Unsupported order type: {order.order_type}. Only MARKET orders permitted."
            self._rejected_orders.append((order, msg))
            raise UnsupportedOrderTypeError(
                f"Stage 2 backtester strictly executes MARKET orders. Got {order.order_type}"
            )

        self._pending_orders.append(order)

    def _process_pending_orders(self, current_timestamp_ns: int) -> None:
        """Evaluate and execute pending market orders whose actionable time has arrived."""
        if len(self._pending_orders) == 0:
            return

        still_pending: list[OrderIntent] = []

        for order in self._pending_orders:
            # Order cannot execute before actionable time
            if order.actionable_timestamp_ns > current_timestamp_ns:
                still_pending.append(order)
                continue

            # Quote must have been observed at or after actionable time
            if self._last_quote_avail_time_ns < order.actionable_timestamp_ns:
                # No quote update has arrived since the order became actionable: defer execution
                still_pending.append(order)
                continue

            # Attempt market fill against current BBO
            self._execute_market_order(order, fill_timestamp_ns=current_timestamp_ns)

        self._pending_orders = still_pending

    def _execute_market_order(self, order: OrderIntent, fill_timestamp_ns: int) -> None:
        """Execute a market order crossing the prevailing quote."""
        bid_p = self._best_bid_price
        bid_q = self._best_bid_qty
        ask_p = self._best_ask_price
        ask_q = self._best_ask_qty

        # Verify quote availability
        if (
            bid_p is None
            or ask_p is None
            or bid_q is None
            or ask_q is None
            or bid_p <= 0
            or ask_p <= 0
        ):
            self._rejected_orders.append(
                (order, "Missing or non-positive quote prices/quantities.")
            )
            return

        # Check crossed/locked book
        if bid_p >= ask_p:
            self._rejected_orders.append((order, f"Crossed book: bid {bid_p} >= ask {ask_p}"))
            return

        # Determine touch price and available displayed depth
        if order.side == OrderSide.BUY:
            touch_price = ask_p
            available_depth = ask_q
        else:
            touch_price = bid_p
            available_depth = bid_q

        # Liquidity constraint check
        max_fillable = int(available_depth * self.config.max_fill_fraction_of_depth)
        fill_qty = order.quantity

        if self.config.enforce_liquidity_limits and order.quantity > max_fillable:
            if not self.config.allow_partial_fills:
                self._rejected_orders.append(
                    (
                        order,
                        f"Insufficient liquidity: order qty {order.quantity} > "
                        f"fillable depth {max_fillable}",
                    )
                )
                return
            else:
                fill_qty = max_fillable
                if fill_qty <= 0:
                    self._rejected_orders.append(
                        (order, "Zero fillable liquidity on partial fill attempt.")
                    )
                    return

        # 1. Validate causal signal generation chain
        signal_ev_ts = (
            order.signal_event_timestamp_ns
            if order.signal_event_timestamp_ns is not None
            else order.decision_timestamp_ns
        )
        signal_av_ts = (
            order.signal_available_timestamp_ns
            if order.signal_available_timestamp_ns is not None
            else order.decision_timestamp_ns
        )

        validate_temporal_coordinates(
            event_timestamp_ns=signal_ev_ts,
            available_timestamp_ns=signal_av_ts,
            decision_timestamp_ns=order.decision_timestamp_ns,
            actionable_timestamp_ns=order.actionable_timestamp_ns,
            fill_timestamp_ns=fill_timestamp_ns,
        )

        # 2. Validate fill quote causality
        if self._last_quote_event_time_ns > self._last_quote_avail_time_ns:
            raise StaleQuoteError(
                f"Fill quote event_ts ({self._last_quote_event_time_ns}) > "
                f"avail_ts ({self._last_quote_avail_time_ns})"
            )
        if self._last_quote_avail_time_ns > fill_timestamp_ns:
            raise StaleQuoteError(
                f"Fill quote lookahead: avail_ts ({self._last_quote_avail_time_ns}) > "
                f"fill_ts ({fill_timestamp_ns})"
            )
        if self._last_quote_avail_time_ns < order.actionable_timestamp_ns:
            raise StaleQuoteError(
                f"Stale quote: quote avail_ts ({self._last_quote_avail_time_ns}) < "
                f"order actionable_ts ({order.actionable_timestamp_ns})"
            )

        # Calculate separated friction costs
        (
            spread_cost,
            slippage_cost,
            exchange_fee,
            regulatory_fee,
        ) = self.cost_calculator.calculate_costs(
            timestamp_ns=fill_timestamp_ns,
            side=order.side,
            quantity=fill_qty,
            fill_price_ticks=touch_price,
            quote_bid_ticks=bid_p,
            quote_ask_ticks=ask_p,
            is_passive=False,
            realized_volatility=self._realized_volatility,
            reference_volume=available_depth,
        )

        # Consume displayed size across sequential orders within the same quote snapshot
        if self.config.enforce_liquidity_limits:
            if order.side == OrderSide.BUY and self._best_ask_qty is not None:
                self._best_ask_qty = max(0, self._best_ask_qty - fill_qty)
            elif order.side == OrderSide.SELL and self._best_bid_qty is not None:
                self._best_bid_qty = max(0, self._best_bid_qty - fill_qty)

        # Apply position and cash updates
        # NOTE: touch_price ALREADY accounts for the spread relative to mid-price
        # (Ask for BUY, Bid for SELL). Therefore, deducting spread_cost again from cash
        # would double-count the spread. External friction includes out-of-pocket fees.
        price_scale = self.config.price_scale
        trade_notional_dollars = (touch_price * fill_qty) / price_scale
        external_friction = slippage_cost + exchange_fee + regulatory_fee

        if order.side == OrderSide.BUY:
            self._cash -= trade_notional_dollars + external_friction
            self._update_position_buy(fill_qty, touch_price / price_scale)
        else:
            self._cash += trade_notional_dollars - external_friction
            self._update_position_sell(fill_qty, touch_price / price_scale)

        # Update totals
        self._fill_counter += 1
        self._total_spread_cost += spread_cost
        self._total_slippage_cost += slippage_cost
        self._total_exchange_fees += exchange_fee
        self._total_regulatory_fees += regulatory_fee
        self._total_turnover += trade_notional_dollars
        self._total_volume_traded += fill_qty

        # Record fill
        fill_record = FillRecord(
            fill_id=f"FILL-{self._fill_counter:06d}",
            order_id=order.order_id,
            fill_timestamp_ns=fill_timestamp_ns,
            instrument_id=order.instrument_id,
            side=order.side,
            quantity=fill_qty,
            price=touch_price,
            spread_cost=spread_cost,
            slippage_cost=slippage_cost,
            exchange_fee=exchange_fee,
            regulatory_fee=regulatory_fee,
            is_passive=False,
            metadata={"quote_bid": bid_p, "quote_ask": ask_p},
        )
        self._fills.append(fill_record)

    def _update_position_buy(self, qty: int, price_dollars: float) -> None:
        """Update position state on a Buy fill."""
        curr_qty = self._position.quantity
        if curr_qty >= 0:
            # Adding to existing long: compute weighted average entry price
            total_qty = curr_qty + qty
            if total_qty > 0:
                self._position.average_entry_price = (
                    (curr_qty * self._position.average_entry_price) + (qty * price_dollars)
                ) / total_qty
            self._position.quantity = total_qty
        else:
            # Closing short position (FIFO / Average Cost)
            closed_qty = min(abs(curr_qty), qty)
            gross_pnl_trade = closed_qty * (self._position.average_entry_price - price_dollars)
            self._gross_realized_pnl += gross_pnl_trade
            self._position.realized_pnl += gross_pnl_trade

            rem_qty = curr_qty + qty
            self._position.quantity = rem_qty
            if rem_qty > 0:
                # Flipped from short to long
                self._position.average_entry_price = price_dollars
            elif rem_qty == 0:
                self._position.average_entry_price = 0.0

    def _update_position_sell(self, qty: int, price_dollars: float) -> None:
        """Update position state on a Sell fill."""
        curr_qty = self._position.quantity
        if curr_qty <= 0:
            # Adding to existing short: compute weighted average entry price
            total_short = abs(curr_qty) + qty
            if total_short > 0:
                self._position.average_entry_price = (
                    (abs(curr_qty) * self._position.average_entry_price) + (qty * price_dollars)
                ) / total_short
            self._position.quantity = -total_short
        else:
            # Closing long position (FIFO / Average Cost)
            closed_qty = min(curr_qty, qty)
            gross_pnl_trade = closed_qty * (price_dollars - self._position.average_entry_price)
            self._gross_realized_pnl += gross_pnl_trade
            self._position.realized_pnl += gross_pnl_trade

            rem_qty = curr_qty - qty
            self._position.quantity = rem_qty
            if rem_qty < 0:
                # Flipped from long to short
                self._position.average_entry_price = price_dollars
            elif rem_qty == 0:
                self._position.average_entry_price = 0.0

    def _get_current_mid_dollars(self) -> float:
        """Get prevailing mid price in dollars."""
        if (
            self._best_bid_price is None
            or self._best_ask_price is None
            or self._best_bid_price <= 0
            or self._best_ask_price <= 0
        ):
            return 0.0
        return (self._best_bid_price + self._best_ask_price) / (2.0 * self.config.price_scale)

    def _calculate_current_equity(self, current_mid_dollars: float) -> float:
        """Compute mark-to-market portfolio equity."""
        return self._cash + (self._position.quantity * current_mid_dollars)

    def _record_snapshot(self, timestamp_ns: int) -> None:
        """Record point-in-time portfolio status."""
        mid_dollars = self._get_current_mid_dollars()
        equity = self._calculate_current_equity(mid_dollars)

        # Unrealized PnL based on mid price
        if self._position.quantity != 0 and mid_dollars > 0.0:
            if self._position.quantity > 0:
                unrealized = self._position.quantity * (
                    mid_dollars - self._position.average_entry_price
                )
            else:
                unrealized = abs(self._position.quantity) * (
                    self._position.average_entry_price - mid_dollars
                )
        else:
            unrealized = 0.0

        self._snapshots.append(
            BacktestSnapshot(
                timestamp_ns=timestamp_ns,
                cash=self._cash,
                position_qty=self._position.quantity,
                market_mid_price=mid_dollars,
                portfolio_equity=equity,
                realized_pnl=self._position.realized_pnl,
                unrealized_pnl=unrealized,
                cumulative_spread_cost=self._total_spread_cost,
                cumulative_slippage_cost=self._total_slippage_cost,
                cumulative_exchange_fees=self._total_exchange_fees,
                cumulative_regulatory_fees=self._total_regulatory_fees,
                cumulative_turnover=self._total_turnover,
            )
        )

    def _build_result(self) -> BacktestResult:
        """Construct the immutable final backtest result summary."""
        final_mid = self._get_current_mid_dollars()
        final_equity = self._calculate_current_equity(final_mid)
        net_pnl = final_equity - self.config.initial_cash
        total_friction = (
            self._total_spread_cost
            + self._total_slippage_cost
            + self._total_exchange_fees
            + self._total_regulatory_fees
        )
        # Gross PnL is Net PnL + Friction Costs
        gross_pnl = net_pnl + total_friction

        return BacktestResult(
            engine_config=self.config,
            initial_cash=self.config.initial_cash,
            final_cash=self._cash,
            final_equity=final_equity,
            final_position_qty=self._position.quantity,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            total_trades=len(self._fills),
            total_volume_traded=self._total_volume_traded,
            total_turnover=self._total_turnover,
            total_spread_cost=self._total_spread_cost,
            total_slippage_cost=self._total_slippage_cost,
            total_exchange_fees=self._total_exchange_fees,
            total_regulatory_fees=self._total_regulatory_fees,
            total_friction_cost=total_friction,
            fills=list(self._fills),
            orders=list(self._all_orders),
            rejected_orders=list(self._rejected_orders),
            snapshots=list(self._snapshots),
        )
