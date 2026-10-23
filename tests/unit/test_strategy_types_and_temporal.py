"""Unit tests for Strategy Laboratory types, temporal semantics, and target construction."""

import math

import pyarrow as pa
import pytest

from research.features.types import MicrostructureFeatureRecord
from research.leakage.exceptions import TemporalOrderError, TimestampSafetyError
from research.leakage.types import LabelInformationInterval, TimeInterval
from research.strategies.base import SIGNAL_SCHEMA_V1, FlatBenchmarkStrategy
from research.strategies.targets import TargetGenerator
from research.strategies.types import (
    FillRecord,
    OrderIntent,
    OrderSide,
    OrderType,
    PositionState,
    Signal,
    TimeInForce,
    validate_temporal_coordinates,
)


class TestStrategyTypesAndTemporal:
    """Tests for Strategy Laboratory data types and temporal coordinate integrity."""

    def test_temporal_coordinate_chain_success(self) -> None:
        """Verify valid 5-point temporal coordinate sequence passes without error."""
        t_event = 1_000_000_000
        t_avail = 1_000_000_100
        t_decision = 1_000_000_200
        t_actionable = 1_000_000_300
        t_fill = 1_000_000_400

        validate_temporal_coordinates(
            event_timestamp_ns=t_event,
            available_timestamp_ns=t_avail,
            decision_timestamp_ns=t_decision,
            actionable_timestamp_ns=t_actionable,
            fill_timestamp_ns=t_fill,
        )

        # Simultaneous timestamps (zero-latency boundary) also valid
        validate_temporal_coordinates(
            event_timestamp_ns=t_event,
            available_timestamp_ns=t_event,
            decision_timestamp_ns=t_event,
            actionable_timestamp_ns=t_event,
            fill_timestamp_ns=t_event,
        )

    def test_temporal_coordinate_pairwise_equalities_and_inequalities(self) -> None:
        """Verify each adjacent step in the 5-point chain allows equality and strict ordering."""
        base = 1_000_000_000
        # Case 1: T_event == T_available < T_decision == T_actionable < T_fill
        validate_temporal_coordinates(
            event_timestamp_ns=base,
            available_timestamp_ns=base,
            decision_timestamp_ns=base + 10,
            actionable_timestamp_ns=base + 10,
            fill_timestamp_ns=base + 20,
        )

        # Case 2: T_event < T_available == T_decision < T_actionable == T_fill
        validate_temporal_coordinates(
            event_timestamp_ns=base,
            available_timestamp_ns=base + 10,
            decision_timestamp_ns=base + 10,
            actionable_timestamp_ns=base + 20,
            fill_timestamp_ns=base + 20,
        )

    def test_temporal_coordinate_chain_violations(self) -> None:
        """Verify each point in the temporal chain strictly enforces causal ordering."""
        base = 1_000_000_000

        # Violation 1: T_event > T_available (Physical causality violation)
        with pytest.raises(TemporalOrderError, match="Physical causality violation"):
            validate_temporal_coordinates(
                event_timestamp_ns=base + 10,
                available_timestamp_ns=base,
                decision_timestamp_ns=base + 20,
                actionable_timestamp_ns=base + 30,
                fill_timestamp_ns=base + 40,
            )

        # Violation 2: T_available > T_decision (Lookahead violation)
        with pytest.raises(TemporalOrderError, match="Point-in-time lookahead violation"):
            validate_temporal_coordinates(
                event_timestamp_ns=base,
                available_timestamp_ns=base + 25,
                decision_timestamp_ns=base + 20,
                actionable_timestamp_ns=base + 30,
                fill_timestamp_ns=base + 40,
            )

        # Violation 3: T_decision > T_actionable (Actionable causality violation)
        with pytest.raises(TemporalOrderError, match="Execution causality violation"):
            validate_temporal_coordinates(
                event_timestamp_ns=base,
                available_timestamp_ns=base + 10,
                decision_timestamp_ns=base + 35,
                actionable_timestamp_ns=base + 30,
                fill_timestamp_ns=base + 40,
            )

        # Violation 4: T_actionable > T_fill (Fill causality violation)
        with pytest.raises(TemporalOrderError, match="Fill causality violation"):
            validate_temporal_coordinates(
                event_timestamp_ns=base,
                available_timestamp_ns=base + 10,
                decision_timestamp_ns=base + 20,
                actionable_timestamp_ns=base + 50,
                fill_timestamp_ns=base + 40,
            )

    def test_temporal_coordinate_invalid_types_raise(self) -> None:
        """Verify non-integer or boolean timestamps are rejected."""
        with pytest.raises(TimestampSafetyError):
            validate_temporal_coordinates(
                event_timestamp_ns=True,  # bool is rejected by runtime check
                available_timestamp_ns=100,
                decision_timestamp_ns=200,
                actionable_timestamp_ns=300,
                fill_timestamp_ns=400,
            )

        with pytest.raises(TimestampSafetyError):
            validate_temporal_coordinates(
                event_timestamp_ns=100,
                available_timestamp_ns=100.5,  # type: ignore[arg-type]
                decision_timestamp_ns=200,
                actionable_timestamp_ns=300,
                fill_timestamp_ns=400,
            )

    def test_signal_dataclass_validation(self) -> None:
        """Verify Signal dataclass enforces valid ranges, types, and direction/weight alignment."""
        sig = Signal(
            decision_timestamp_ns=1_000_000,
            instrument_id=1,
            direction=1,
            target_weight=0.5,
            strength=0.8,
            confidence=0.9,
            is_valid=True,
            metadata={"source": "test"},
        )
        assert sig.direction == 1
        assert sig.target_weight == 0.5

        # Invalid direction
        with pytest.raises(ValueError, match="direction must be -1, 0, or 1"):
            Signal(decision_timestamp_ns=100, instrument_id=1, direction=2, target_weight=0.5)

        # Non-finite weight
        with pytest.raises(ValueError, match="target_weight must be a finite float"):
            Signal(
                decision_timestamp_ns=100,
                instrument_id=1,
                direction=1,
                target_weight=float("nan"),
            )

        # Weight out of bounds
        with pytest.raises(ValueError, match="target_weight must be in"):
            Signal(decision_timestamp_ns=100, instrument_id=1, direction=1, target_weight=1.5)

        # Strength out of bounds
        with pytest.raises(ValueError, match="strength must be in"):
            Signal(
                decision_timestamp_ns=100,
                instrument_id=1,
                direction=1,
                target_weight=0.5,
                strength=-0.1,
            )

        # Invariant: is_valid=False requires Flat (direction=0, target_weight=0.0)
        with pytest.raises(ValueError, match="Invalid signal.*must be Flat"):
            Signal(
                decision_timestamp_ns=100,
                instrument_id=1,
                direction=1,
                target_weight=0.5,
                is_valid=False,
            )

        # Invariant: direction=0 requires target_weight=0.0
        with pytest.raises(ValueError, match="direction=0.*requires target_weight=0.0"):
            Signal(
                decision_timestamp_ns=100,
                instrument_id=1,
                direction=0,
                target_weight=0.1,
            )

        # Invariant: direction=1 requires target_weight > 0.0
        with pytest.raises(ValueError, match="direction=1.*requires target_weight > 0.0"):
            Signal(
                decision_timestamp_ns=100,
                instrument_id=1,
                direction=1,
                target_weight=-0.5,
            )

        # Invariant: direction=-1 requires target_weight < 0.0
        with pytest.raises(ValueError, match="direction=-1.*requires target_weight < 0.0"):
            Signal(
                decision_timestamp_ns=100,
                instrument_id=1,
                direction=-1,
                target_weight=0.5,
            )

    def test_order_intent_dataclass_validation(self) -> None:
        """Verify OrderIntent dataclass enforces positive quantity, order_id, and limits."""
        intent = OrderIntent(
            order_id="ORD-001",
            decision_timestamp_ns=1_000_000,
            actionable_timestamp_ns=1_000_050,
            instrument_id=101,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
        )
        assert intent.quantity == 100
        assert intent.time_in_force == TimeInForce.IOC

        # Empty order_id
        with pytest.raises(ValueError, match="order_id must be a non-empty string"):
            OrderIntent(
                order_id="",
                decision_timestamp_ns=100,
                actionable_timestamp_ns=100,
                instrument_id=101,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=100,
            )

        # Inverted timestamps
        with pytest.raises(TemporalOrderError):
            OrderIntent(
                order_id="ORD-002",
                decision_timestamp_ns=1_000_100,
                actionable_timestamp_ns=1_000_000,
                instrument_id=101,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=100,
            )

        # Zero or negative quantity
        with pytest.raises(ValueError, match="quantity must be a positive integer"):
            OrderIntent(
                order_id="ORD-003",
                decision_timestamp_ns=100,
                actionable_timestamp_ns=100,
                instrument_id=101,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=0,
            )

        # Limit order missing limit price
        with pytest.raises(ValueError, match="Limit order requires a positive integer limit_price"):
            OrderIntent(
                order_id="ORD-004",
                decision_timestamp_ns=100,
                actionable_timestamp_ns=100,
                instrument_id=101,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=100,
                limit_price=None,
            )

        # Market order with limit price
        with pytest.raises(ValueError, match="Market orders cannot specify limit_price"):
            OrderIntent(
                order_id="ORD-005",
                decision_timestamp_ns=100,
                actionable_timestamp_ns=100,
                instrument_id=101,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=100,
                limit_price=15000,
            )

    def test_fill_record_dataclass_validation(self) -> None:
        """Verify FillRecord validates prices, quantities, costs, and rebates."""
        fill = FillRecord(
            fill_id="FILL-001",
            order_id="ORD-001",
            fill_timestamp_ns=1_000_200,
            instrument_id=101,
            side=OrderSide.BUY,
            quantity=100,
            price=15000,  # $150.00
            spread_cost=0.50,
            slippage_cost=0.10,
            exchange_fee=-0.20,  # Negative fee = maker rebate
            regulatory_fee=0.00,
            is_passive=True,
        )
        assert fill.price == 15000
        # Total cost: 0.50 + 0.10 - 0.20 + 0.00 = 0.40
        assert math.isclose(fill.total_transaction_cost, 0.40)

        # Non-positive price
        with pytest.raises(ValueError, match="price must be a positive integer"):
            FillRecord(
                fill_id="F-1",
                order_id="O-1",
                fill_timestamp_ns=100,
                instrument_id=1,
                side=OrderSide.BUY,
                quantity=100,
                price=0,
            )

        # Negative spread cost
        with pytest.raises(ValueError, match="spread_cost cannot be negative"):
            FillRecord(
                fill_id="F-2",
                order_id="O-2",
                fill_timestamp_ns=100,
                instrument_id=1,
                side=OrderSide.BUY,
                quantity=100,
                price=1000,
                spread_cost=-0.50,
            )

    def test_position_state_tracking(self) -> None:
        """Verify PositionState tracks long, short, and flat status."""
        pos = PositionState(instrument_id=1)
        assert pos.is_flat
        assert not pos.is_long
        assert not pos.is_short

        pos.quantity = 200
        assert pos.is_long
        assert not pos.is_flat

        pos.quantity = -150
        assert pos.is_short
        assert not pos.is_flat


class TestFlatBenchmarkStrategy:
    """Tests for FlatBenchmarkStrategy baseline."""

    def test_flat_benchmark_emits_clean_null_signals(self) -> None:
        """Verify FlatBenchmarkStrategy emits 0.0 weight signals conforming to SIGNAL_SCHEMA_V1."""
        strat = FlatBenchmarkStrategy(instrument_id=42)
        assert strat.is_fitted

        # Table generation
        ts = [1_000_000, 2_000_000, 3_000_000]
        dummy_feat_table = pa.Table.from_arrays(
            [pa.array(ts, type=pa.int64())],
            names=["decision_timestamp_ns"],
        )

        sig_table = strat.generate_signals(dummy_feat_table)
        assert sig_table.schema == SIGNAL_SCHEMA_V1
        assert len(sig_table) == 3
        assert sig_table["direction"].to_pylist() == [0, 0, 0]
        assert sig_table["target_weight"].to_pylist() == [0.0, 0.0, 0.0]
        assert sig_table["is_valid"].to_pylist() == [True, True, True]

        # Streaming generation
        dummy_record = MicrostructureFeatureRecord(
            instrument_id=42,
            sequence_num=1,
            event_timestamp_ns=4_999_990,
            source_timestamp_ns=4_999_990,
            decision_timestamp_ns=5_000_000,
            best_bid_price=10000,
            best_bid_quantity=100,
            best_ask_price=10010,
            best_ask_quantity=100,
            spread=10,
            relative_spread=0.001,
            mid_price=100.05,
            weighted_mid_price=100.05,
            book_imbalance_top=0.0,
            bid_depth_k=500,
            ask_depth_k=500,
            depth_imbalance_k=0.0,
            instant_ofi=0,
            rolling_ofi=0,
            last_signed_volume=50,
            rolling_trade_volume=50,
            rolling_buy_volume=50,
            rolling_sell_volume=0,
            trade_flow_imbalance=0.0,
            rolling_vwap=100.05,
            log_return=0.0,
            realized_volatility=0.0,
            roll_spread=0.0,
            vpin=0.0,
            has_bid=True,
            has_ask=True,
            is_crossed=False,
            has_spread=True,
            has_mid=True,
            has_weighted_mid=True,
            has_book_imbalance=True,
            has_depth_imbalance=True,
            has_instant_ofi=True,
            has_rolling_ofi=True,
            has_trade=True,
            has_trade_flow=True,
            has_vwap=True,
            has_log_return=True,
            has_realized_volatility=True,
            has_roll_spread=True,
            has_vpin=True,
        )
        stream_sig = strat.on_features(dummy_record)
        assert stream_sig is not None
        assert stream_sig.direction == 0
        assert stream_sig.target_weight == 0.0
        assert stream_sig.decision_timestamp_ns == 5_000_000


class TestTargetGenerator:
    """Tests for forward return calculation and triple barrier labeling."""

    def test_compute_fixed_horizon_targets_mathematical_correctness(self) -> None:
        """Verify log return and arithmetic return against hand calculations."""
        # Timestamps every 1 second: [0s, 1s, 2s, 3s, 4s]
        ts = [0, 1_000_000_000, 2_000_000_000, 3_000_000_000, 4_000_000_000]
        prices = [100.0, 105.0, 110.0, 115.0, 120.0]
        horizon_ns = 2_000_000_000  # 2 seconds forward

        targets = TargetGenerator.compute_fixed_horizon_targets(
            timestamps=ts,
            prices=prices,
            horizon_ns=horizon_ns,
        )
        assert len(targets) == 5

        # Row 0: t=0 -> forward is t=2s (price 110.0)
        # Arith return: (110 - 100) / 100 = 0.10
        # Log return: ln(1.10)
        t0 = targets[0]
        assert t0.is_valid
        assert t0.forward_price == 110.0
        assert math.isclose(t0.arithmetic_return, 0.10)
        assert math.isclose(t0.log_return, math.log(1.10))
        assert t0.label_interval.observation_timestamp_ns == 0
        assert t0.label_interval.label_end_timestamp_ns == 2_000_000_000

        # Row 3 & 4: Horizon extends past dataset boundary -> is_valid must be False and return NaN
        assert not targets[3].is_valid
        assert math.isnan(targets[3].arithmetic_return)
        assert math.isnan(targets[3].log_return)
        assert not targets[4].is_valid

    def test_fixed_horizon_non_positive_and_non_finite_prices(self) -> None:
        """Verify non-positive or non-finite prices are gated with is_valid=False and NaN."""
        ts = [100, 200, 300]
        prices = [10.0, 0.0, 12.0]
        targets = TargetGenerator.compute_fixed_horizon_targets(ts, prices, horizon_ns=100)

        # Row 0: current=10.0, forward=0.0 -> non-positive forward price
        assert not targets[0].is_valid
        assert math.isnan(targets[0].arithmetic_return)
        assert math.isnan(targets[0].log_return)

    def test_fixed_horizon_purging_boundary_overlap(self) -> None:
        """Verify that forward label interval properly detects overlap with test intervals."""
        ts = [1_000, 2_000, 3_000, 4_000]
        prices = [10.0, 10.0, 10.0, 10.0]
        horizon_ns = 2_000

        targets = TargetGenerator.compute_fixed_horizon_targets(ts, prices, horizon_ns)
        test_partition = TimeInterval(2500, 5000)

        # Row 0 label interval [1000, 3000] touches [2500, 5000) because 3000 >= 2500
        assert targets[0].label_interval.touches_partition(test_partition)

        # Pre-test partition [0, 500) does not touch [1000, 3000]
        past_partition = TimeInterval(0, 500)
        assert not targets[0].label_interval.touches_partition(past_partition)

    def test_compute_triple_barrier_targets_barriers(self) -> None:
        """Verify take-profit, stop-loss, and vertical barrier triggers."""
        ts = [0, 100, 200, 300, 400]
        prices = [100.0, 101.0, 102.5, 99.0, 100.0]

        # Upper barrier = +2% (0.02), Lower barrier = -1% (0.01), max_holding = 500ns
        barriers = TargetGenerator.compute_triple_barrier_targets(
            timestamps=ts,
            prices=prices,
            upper_threshold=0.02,
            lower_threshold=0.01,
            max_holding_ns=500,
        )

        # Observation 0 (price 100): reaches 102.5 at t=200 -> hits upper barrier (+2.5%)
        b0 = barriers[0]
        assert b0.is_valid
        assert b0.hit_upper
        assert not b0.hit_lower
        assert not b0.hit_vertical
        assert b0.exit_timestamp_ns == 200
        assert math.isclose(b0.return_value, 0.025)
        assert b0.label_interval == LabelInformationInterval(0, 200)

        # Path where stop-loss is hit
        prices_down = [100.0, 99.5, 98.5, 100.0, 100.0]
        barriers_down = TargetGenerator.compute_triple_barrier_targets(
            timestamps=ts,
            prices=prices_down,
            upper_threshold=0.02,
            lower_threshold=0.01,
            max_holding_ns=500,
        )
        b_down = barriers_down[0]
        assert b_down.is_valid
        assert b_down.hit_lower
        assert not b_down.hit_upper
        assert b_down.exit_timestamp_ns == 200
        assert math.isclose(b_down.return_value, -0.015)

        # Path where vertical time expiry barrier is hit
        prices_flat = [100.0, 100.1, 100.2, 100.3, 100.4]
        barriers_vert = TargetGenerator.compute_triple_barrier_targets(
            timestamps=ts,
            prices=prices_flat,
            upper_threshold=0.02,
            lower_threshold=0.01,
            max_holding_ns=250,  # Max holding 250ns: expires at t=300
        )
        b_vert = barriers_vert[0]
        assert b_vert.is_valid
        assert b_vert.hit_vertical
        assert not b_vert.hit_upper
        assert not b_vert.hit_lower
        assert b_vert.exit_timestamp_ns == 300

    def test_compute_triple_barrier_censored_dataset_boundary(self) -> None:
        """Verify incomplete episode at dataset boundary has is_valid=False and NaN return."""
        ts = [0, 100, 200]
        prices = [100.0, 100.1, 100.2]  # Moves never reach +/- 5%

        barriers = TargetGenerator.compute_triple_barrier_targets(
            timestamps=ts,
            prices=prices,
            upper_threshold=0.05,
            lower_threshold=0.05,
            max_holding_ns=500,  # Max holding exceeds dataset end (200)
        )
        # Episode reaches dataset boundary without hitting any barrier
        b0 = barriers[0]
        assert not b0.is_valid
        assert not b0.hit_upper
        assert not b0.hit_lower
        assert not b0.hit_vertical
        assert math.isnan(b0.return_value)

    def test_compute_triple_barrier_non_positive_price_raises(self) -> None:
        """Verify non-positive or non-finite prices raise ValueError."""
        with pytest.raises(ValueError, match="Non-positive or non-finite price"):
            TargetGenerator.compute_triple_barrier_targets(
                timestamps=[100, 200],
                prices=[0.0, 10.0],
                upper_threshold=0.01,
                lower_threshold=0.01,
                max_holding_ns=100,
            )

    def test_enrich_with_forward_returns_table(self) -> None:
        """Verify Arrow table enrichment with forward return columns."""
        ts = [100, 200, 300, 400]
        mid = [50.0, 52.0, 54.0, 56.0]
        table = pa.Table.from_arrays(
            [pa.array(ts, type=pa.int64()), pa.array(mid, type=pa.float64())],
            names=["decision_timestamp_ns", "mid_price"],
        )

        enriched = TargetGenerator.enrich_with_forward_returns(
            table=table,
            horizon_ns=200,
            price_col="mid_price",
            ts_col="decision_timestamp_ns",
        )

        assert "forward_return" in enriched.column_names
        assert "forward_log_return" in enriched.column_names
        assert "has_forward_target" in enriched.column_names

        # Row 0: t=100 -> t=300 (price 54.0) -> return (54-50)/50 = 0.08
        ret0 = enriched["forward_return"][0].as_py()
        assert math.isclose(ret0, 0.08)
        assert enriched["has_forward_target"][0].as_py() is True

        # Last row extends past end -> has_forward_target False
        assert enriched["has_forward_target"][3].as_py() is False
        assert math.isnan(enriched["forward_return"][3].as_py())
