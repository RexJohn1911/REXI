"""Unit tests for Stage 2: Event-Driven Backtester & Dated Cost Accounting."""

import math
from datetime import UTC, date, datetime

import pyarrow as pa
import pytest

from research.backtesting.costs import (
    US_EASTERN_TZ,
    US_SETTLEMENT_HOLIDAYS_2024_2029,
    US_SETTLEMENT_HOLIDAYS_2024_2032,
    CostModelConfig,
    DatedFeeSchedule,
    SecChargeDateRule,
    TradeDateResolution,
    TransactionCostCalculator,
    calculate_settlement_timestamp_ns,
    create_standard_us_equities_schedules,
    get_us_settlement_holidays_for_year,
    parse_iso_date_to_eastern_ns,
    parse_iso_date_to_utc_ns,
    resolve_trade_and_settlement_dates,
    timestamp_ns_to_eastern_date,
)
from research.backtesting.engine import (
    BacktestEngineConfig,
    DeterministicBacktestEngine,
)
from research.backtesting.exceptions import (
    BacktestConfigurationError,
    UnsupportedOrderTypeError,
)
from research.features.types import MicrostructureFeatureRecord
from research.strategies.base import BaseStrategy, FlatBenchmarkStrategy
from research.strategies.types import (
    OrderIntent,
    OrderSide,
    OrderType,
    Signal,
)


class TestDatedFeeSchedulesAndCosts:
    """Tests for transaction cost calculations, dated schedules, and cost separation."""

    def test_dated_fee_schedules_boundaries_all_transitions(self) -> None:
        """Verify regulatory fee rates immediately before, on, and after each effective date.

        Statutory effective dates take effect at midnight Eastern Time (America/New_York).
        """
        cfg = CostModelConfig(fee_schedules=create_standard_us_equities_schedules())
        calc = TransactionCostCalculator(cfg)

        ts_2024_05_22 = parse_iso_date_to_eastern_ns("2024-05-22")
        ts_2025_05_14 = parse_iso_date_to_eastern_ns("2025-05-14")
        ts_2026_04_04 = parse_iso_date_to_eastern_ns("2026-04-04")
        ts_2026_10_01 = parse_iso_date_to_eastern_ns("2026-10-01")
        ts_2027_01_01 = parse_iso_date_to_eastern_ns("2027-01-01")
        ts_2029_01_01 = parse_iso_date_to_eastern_ns("2029-01-01")
        ts_2030_01_01 = parse_iso_date_to_eastern_ns("2030-01-01")
        ts_2031_01_01 = parse_iso_date_to_eastern_ns("2031-01-01")

        # 1. Transition 1: 2024-05-22 (SEC increases from $8.00 to $27.80/million)
        # Immediately before (2024-05-21 23:59:59.999999999 UTC)
        sched_before_1 = cfg.get_fee_schedule(ts_2024_05_22 - 1)
        assert sched_before_1.sec_section_31_rate == 0.0000080
        assert sched_before_1.finra_taf_rate_per_share == 0.000195
        assert sched_before_1.finra_taf_max_per_trade == 9.79

        # On effective date (2024-05-22 00:00:00 UTC)
        sched_on_1 = cfg.get_fee_schedule(ts_2024_05_22)
        assert sched_on_1.sec_section_31_rate == 0.0000278
        assert sched_on_1.finra_taf_rate_per_share == 0.000195
        assert sched_on_1.finra_taf_max_per_trade == 9.79

        # Immediately after (2024-05-22 00:00:00.000000001 UTC)
        sched_after_1 = cfg.get_fee_schedule(ts_2024_05_22 + 1)
        assert sched_after_1.sec_section_31_rate == 0.0000278

        # 2. Transition 2: 2025-05-14 (SEC drops to $0.00/million: statutory target reached)
        # Immediately before
        sched_before_2 = cfg.get_fee_schedule(ts_2025_05_14 - 1)
        assert sched_before_2.sec_section_31_rate == 0.0000278

        # On effective date
        sched_on_2 = cfg.get_fee_schedule(ts_2025_05_14)
        assert sched_on_2.sec_section_31_rate == 0.0
        assert sched_on_2.finra_taf_rate_per_share == 0.000195
        assert sched_on_2.finra_taf_max_per_trade == 9.79

        # Immediately after
        sched_after_2 = cfg.get_fee_schedule(ts_2025_05_14 + 1)
        assert sched_after_2.sec_section_31_rate == 0.0

        # Verify cost calculation in $0 SEC period
        _, _, _, reg_fee_zero_sec = calc.calculate_costs(
            timestamp_ns=ts_2025_05_14,
            side=OrderSide.SELL,
            quantity=1000,
            fill_price_ticks=10000,
            quote_bid_ticks=10000,
            quote_ask_ticks=10010,
        )
        # SEC fee is $0.00; only TAF applies: 1,000 * 0.000195 = $0.195
        assert math.isclose(reg_fee_zero_sec, 0.195, abs_tol=1e-5)

        # 3. Transition 3: 2026-04-04 (SEC resets to $20.60/million: regular FY26 enacted)
        # Immediately before
        sched_before_3 = cfg.get_fee_schedule(ts_2026_04_04 - 1)
        assert sched_before_3.sec_section_31_rate == 0.0

        # On effective date
        sched_on_3 = cfg.get_fee_schedule(ts_2026_04_04)
        assert sched_on_3.sec_section_31_rate == 0.0000206
        assert sched_on_3.finra_taf_rate_per_share == 0.000195
        assert sched_on_3.finra_taf_max_per_trade == 9.79

        # Immediately after
        sched_after_3 = cfg.get_fee_schedule(ts_2026_04_04 + 1)
        assert sched_after_3.sec_section_31_rate == 0.0000206

        # 4. Transition 4: 2026-10-01 (FINRA TAF temporary pause begins under SR-FINRA-2026-021)
        # Immediately before (2026-09-30 23:59:59.999999999 UTC)
        sched_before_4 = cfg.get_fee_schedule(ts_2026_10_01 - 1)
        assert sched_before_4.sec_section_31_rate == 0.0000206
        assert sched_before_4.finra_taf_rate_per_share == 0.000195
        assert sched_before_4.finra_taf_max_per_trade == 9.79
        assert sched_before_4.finra_taf_min_per_trade == 0.0

        # On effective date (2026-10-01 00:00:00 UTC)
        sched_on_4 = cfg.get_fee_schedule(ts_2026_10_01)
        assert sched_on_4.sec_section_31_rate == 0.0000206
        assert sched_on_4.finra_taf_rate_per_share == 0.0
        assert sched_on_4.finra_taf_min_per_trade == 0.0
        assert sched_on_4.finra_taf_max_per_trade == 0.0

        # 5. Transition 5: 2027-01-01
        # (FINRA TAF pause ends, resumes $0.000195, cap $9.79 per SR-FINRA-2026-020)
        # Immediately before (2026-12-31 23:59:59.999999999 UTC)
        sched_before_5 = cfg.get_fee_schedule(ts_2027_01_01 - 1)
        assert sched_before_5.finra_taf_rate_per_share == 0.0

        # On effective date (2027-01-01 00:00:00 UTC)
        sched_on_5 = cfg.get_fee_schedule(ts_2027_01_01)
        assert sched_on_5.sec_section_31_rate == 0.0000206
        assert sched_on_5.finra_taf_rate_per_share == 0.000195
        assert sched_on_5.finra_taf_max_per_trade == 9.79
        assert sched_on_5.finra_taf_min_per_trade == 0.0

        # Immediately after
        sched_after_5 = cfg.get_fee_schedule(ts_2027_01_01 + 1)
        assert sched_after_5.finra_taf_rate_per_share == 0.000195

        # 6. Transition 6: 2029-01-01
        # (FINRA TAF delayed increase takes effect: $0.000232/share, cap $11.61)
        # Immediately before (2028-12-31 23:59:59.999999999 UTC)
        sched_before_6 = cfg.get_fee_schedule(ts_2029_01_01 - 1)
        assert sched_before_6.finra_taf_rate_per_share == 0.000195
        assert sched_before_6.finra_taf_max_per_trade == 9.79

        # On effective date (2029-01-01 00:00:00 UTC)
        sched_on_6 = cfg.get_fee_schedule(ts_2029_01_01)
        assert sched_on_6.sec_section_31_rate == 0.0000206
        assert sched_on_6.finra_taf_rate_per_share == 0.000232
        assert sched_on_6.finra_taf_max_per_trade == 11.61
        assert sched_on_6.finra_taf_min_per_trade == 0.0

        # Immediately after
        sched_after_6 = cfg.get_fee_schedule(ts_2029_01_01 + 1)
        assert sched_after_6.finra_taf_rate_per_share == 0.000232
        assert sched_after_6.finra_taf_max_per_trade == 11.61

        # 7. Transition 7: 2030-01-01
        # (FINRA TAF step-up year 2 takes effect: $0.000240/share, cap $12.05)
        # Immediately before (2029-12-31 23:59:59.999999999 UTC)
        sched_before_7 = cfg.get_fee_schedule(ts_2030_01_01 - 1)
        assert sched_before_7.finra_taf_rate_per_share == 0.000232
        assert sched_before_7.finra_taf_max_per_trade == 11.61

        # On effective date (2030-01-01 00:00:00 UTC)
        sched_on_7 = cfg.get_fee_schedule(ts_2030_01_01)
        assert sched_on_7.sec_section_31_rate == 0.0000206
        assert sched_on_7.finra_taf_rate_per_share == 0.000240
        assert sched_on_7.finra_taf_max_per_trade == 12.05
        assert sched_on_7.finra_taf_min_per_trade == 0.0

        # Immediately after
        sched_after_7 = cfg.get_fee_schedule(ts_2030_01_01 + 1)
        assert sched_after_7.finra_taf_rate_per_share == 0.000240
        assert sched_after_7.finra_taf_max_per_trade == 12.05

        # 8. Transition 8: 2031-01-01
        # (FINRA TAF step-up year 3 onward takes effect: $0.000249/share, cap $12.50)
        # Immediately before (2030-12-31 23:59:59.999999999 UTC)
        sched_before_8 = cfg.get_fee_schedule(ts_2031_01_01 - 1)
        assert sched_before_8.finra_taf_rate_per_share == 0.000240
        assert sched_before_8.finra_taf_max_per_trade == 12.05

        # On effective date (2031-01-01 00:00:00 UTC)
        sched_on_8 = cfg.get_fee_schedule(ts_2031_01_01)
        assert sched_on_8.sec_section_31_rate == 0.0000206
        assert sched_on_8.finra_taf_rate_per_share == 0.000249
        assert sched_on_8.finra_taf_max_per_trade == 12.50
        assert sched_on_8.finra_taf_min_per_trade == 0.0

        # Immediately after
        sched_after_8 = cfg.get_fee_schedule(ts_2031_01_01 + 1)
        assert sched_after_8.finra_taf_rate_per_share == 0.000249
        assert sched_after_8.finra_taf_max_per_trade == 12.50

    def test_current_october_2026_period_fee_schedule(self) -> None:
        """Verify fee calculations during the current active October 2026 environment."""
        cfg = CostModelConfig(fee_schedules=create_standard_us_equities_schedules())
        calc = TransactionCostCalculator(cfg)

        # October 23, 2026: SEC = $20.60/million, FINRA TAF paused = $0.00
        t_now = parse_iso_date_to_utc_ns("2026-10-23")
        sched = cfg.get_fee_schedule(t_now)
        assert sched.sec_section_31_rate == 0.0000206
        assert sched.finra_taf_rate_per_share == 0.0
        assert sched.finra_taf_min_per_trade == 0.0
        assert sched.finra_taf_max_per_trade == 0.0

        # Sell 10,000 shares @ $50.00 = $500,000 gross sale principal
        # Price: 5000 ticks, Price scale: 100.0
        _, _, ex_fee, reg_fee = calc.calculate_costs(
            timestamp_ns=t_now,
            side=OrderSide.SELL,
            quantity=10_000,
            fill_price_ticks=5000,
            quote_bid_ticks=5000,
            quote_ask_ticks=5010,
        )

        # SEC fee: 0.0000206 * $500,000 = $10.30
        # FINRA TAF: $0.00 (under SR-FINRA-2026-021)
        assert math.isclose(reg_fee, 10.30, abs_tol=1e-5)
        # Exchange taker fee: 10,000 * $0.0030 = $30.00
        assert math.isclose(ex_fee, 30.00, abs_tol=1e-5)

    def test_unsupported_dates_strict_versus_permissive(self) -> None:
        """Verify handling of dates preceding the earliest verified schedule (e.g. 2023)."""
        ts_2023 = parse_iso_date_to_utc_ns("2023-06-15")

        # 1. Permissive mode (default): falls back to earliest schedule
        cfg_permissive = CostModelConfig(
            fee_schedules=create_standard_us_equities_schedules(),
            strict_schedule_coverage=False,
        )
        sched_perm = cfg_permissive.get_fee_schedule(ts_2023)
        assert sched_perm.effective_start_date_str == "2024-01-01"

        # 2. Strict mode: raises BacktestConfigurationError on unsupported dates
        cfg_strict = CostModelConfig(
            fee_schedules=create_standard_us_equities_schedules(),
            strict_schedule_coverage=True,
        )
        with pytest.raises(BacktestConfigurationError, match="precedes earliest verified schedule"):
            cfg_strict.get_fee_schedule(ts_2023)

    def test_finra_taf_equity_statutory_all_caps_and_no_floor(self) -> None:
        """Verify FINRA TAF has no floor, raw 10-share fees, and tests all statutory caps."""
        cfg = CostModelConfig(fee_schedules=create_standard_us_equities_schedules())
        calc = TransactionCostCalculator(cfg)
        t_2024 = parse_iso_date_to_utc_ns("2024-06-01")
        t_2029 = parse_iso_date_to_utc_ns("2029-01-15")
        t_2030 = parse_iso_date_to_utc_ns("2030-01-15")
        t_2031 = parse_iso_date_to_utc_ns("2031-01-15")

        # Case 1: Small trade (10 shares) -> raw TAF = 10 * rate.
        # FINRA Schedule A does NOT impose a $0.01 floor for equities.
        # Raw fee calculation before any optional broker-billing rounding must be exact.
        sched_2024 = cfg.get_fee_schedule(t_2024)
        sched_2029 = cfg.get_fee_schedule(t_2029)
        sched_2030 = cfg.get_fee_schedule(t_2030)
        sched_2031 = cfg.get_fee_schedule(t_2031)

        assert math.isclose(10 * sched_2024.finra_taf_rate_per_share, 0.00195, abs_tol=1e-7)
        assert math.isclose(10 * sched_2029.finra_taf_rate_per_share, 0.00232, abs_tol=1e-7)
        assert math.isclose(10 * sched_2024.finra_taf_rate_per_share, 0.00195, abs_tol=1e-7)
        assert math.isclose(10 * sched_2030.finra_taf_rate_per_share, 0.00240, abs_tol=1e-7)
        assert math.isclose(10 * sched_2031.finra_taf_rate_per_share, 0.00249, abs_tol=1e-7)

        # Baseline calculation through calculator
        _, _, _, reg_fee_small = calc.calculate_costs(
            timestamp_ns=t_2024,
            side=OrderSide.SELL,
            quantity=10,
            fill_price_ticks=1000,
            quote_bid_ticks=1000,
            quote_ask_ticks=1002,
        )
        sec_fee_small = 0.0000278 * (1000 * 10 / 100.0)
        expected_taf_small = 10 * 0.000195  # Exactly $0.00195, NOT $0.01!
        assert math.isclose(reg_fee_small, sec_fee_small + expected_taf_small, abs_tol=1e-5)

        # Case 2: Baseline cap ($9.79 per trade) under SR-FINRA-2026-020 (Through 2028-12-31)
        # Huge trade (100,000 shares) -> raw TAF = 100,000 * 0.000195 = $19.50 -> Cap $9.79 applies
        _, _, _, reg_fee_large_2024 = calc.calculate_costs(
            timestamp_ns=t_2024,
            side=OrderSide.SELL,
            quantity=100_000,
            fill_price_ticks=5000,
            quote_bid_ticks=5000,
            quote_ask_ticks=5010,
        )
        sec_fee_large_2024 = 0.0000278 * (5000 * 100_000 / 100.0)
        assert math.isclose(reg_fee_large_2024, sec_fee_large_2024 + 9.79, abs_tol=1e-5)

        # Case 3: Step-up year 1 cap ($11.61 per trade) under SR-FINRA-2026-020 (2029)
        # Huge trade (100,000 shares) -> raw TAF = 100,000 * 0.000232 = $23.20 -> Cap $11.61 applies
        _, _, _, reg_fee_large_2029 = calc.calculate_costs(
            timestamp_ns=t_2029,
            side=OrderSide.SELL,
            quantity=100_000,
            fill_price_ticks=5000,
            quote_bid_ticks=5000,
            quote_ask_ticks=5010,
        )
        sec_fee_large_2029 = 0.0000206 * (5000 * 100_000 / 100.0)
        assert math.isclose(reg_fee_large_2029, sec_fee_large_2029 + 11.61, abs_tol=1e-5)

        # Case 4: Step-up year 2 cap ($12.05 per trade) under SR-FINRA-2026-020 (2030)
        # Huge trade (100,000 shares) -> raw TAF = 100,000 * 0.000240 = $24.00 -> Cap $12.05 applies
        _, _, _, reg_fee_large_2030 = calc.calculate_costs(
            timestamp_ns=t_2030,
            side=OrderSide.SELL,
            quantity=100_000,
            fill_price_ticks=5000,
            quote_bid_ticks=5000,
            quote_ask_ticks=5010,
        )
        sec_fee_large_2030 = 0.0000206 * (5000 * 100_000 / 100.0)
        assert math.isclose(reg_fee_large_2030, sec_fee_large_2030 + 12.05, abs_tol=1e-5)

        # Case 5: Step-up year 3 onward cap ($12.50 per trade) under SR-FINRA-2026-020 (2031+)
        # Huge trade (100,000 shares) -> raw TAF = 100,000 * 0.000249 = $24.90 -> Cap $12.50 applies
        _, _, _, reg_fee_large_2031 = calc.calculate_costs(
            timestamp_ns=t_2031,
            side=OrderSide.SELL,
            quantity=100_000,
            fill_price_ticks=5000,
            quote_bid_ticks=5000,
            quote_ask_ticks=5010,
        )
        sec_fee_large_2031 = 0.0000206 * (5000 * 100_000 / 100.0)
        assert math.isclose(reg_fee_large_2031, sec_fee_large_2031 + 12.50, abs_tol=1e-5)

    def test_finra_taf_sub_rate_price_exemption(self) -> None:
        """Verify transactions executed below the TAF rate ($0.000195) are exempt from TAF."""
        cfg = CostModelConfig(
            fee_schedules=create_standard_us_equities_schedules(),
            price_scale=1_000_000.0,  # 1 million ticks per dollar for sub-penny resolution
        )
        calc = TransactionCostCalculator(cfg)
        t = parse_iso_date_to_utc_ns("2024-06-01")

        # Execution price: $0.000150 per share (150 ticks @ price_scale 1,000,000)
        # Since $0.000150 < $0.000195, TAF must be $0.00
        _, _, _, reg_fee_exempt = calc.calculate_costs(
            timestamp_ns=t,
            side=OrderSide.SELL,
            quantity=1_000_000,
            fill_price_ticks=150,
            quote_bid_ticks=150,
            quote_ask_ticks=160,
        )
        sec_fee = 0.0000278 * (150 * 1_000_000 / 1_000_000.0)
        assert math.isclose(reg_fee_exempt, sec_fee, abs_tol=1e-5)
        # Only SEC fee applies; TAF is 0.0
        assert math.isclose(reg_fee_exempt, sec_fee, abs_tol=1e-5)

    def test_calculate_settlement_timestamp_ns(self) -> None:
        """Verify statutory settlement computation under 17 CFR § 240.15c6-1(a) with holidays."""
        # 1. Pre-May 28, 2024: Standard T+2 business days
        # Tuesday May 21, 2024 14:30:00 UTC -> settles Thursday May 23, 2024 14:30:00 UTC
        t_tue_may_21 = parse_iso_date_to_utc_ns("2024-05-21") + 14 * 3600 * 1_000_000_000
        settle_tue = calculate_settlement_timestamp_ns(t_tue_may_21)
        expected_tue_settle = (
            parse_iso_date_to_utc_ns("2024-05-23") + 14 * 3600 * 1_000_000_000
        )
        assert settle_tue == expected_tue_settle

        # Friday May 24, 2024 16:00:00 UTC:
        # Memorial Day is Monday May 27, 2024 (Clearing holiday).
        # T+2 skips weekend (May 25-26) AND Memorial Day (May 27).
        # Day 1 is Tuesday May 28, Day 2 is Wednesday May 29, 2024!
        t_fri_may_24 = parse_iso_date_to_utc_ns("2024-05-24") + 16 * 3600 * 1_000_000_000
        settle_fri = calculate_settlement_timestamp_ns(t_fri_may_24)
        expected_fri_settle = (
            parse_iso_date_to_utc_ns("2024-05-29") + 16 * 3600 * 1_000_000_000
        )
        assert settle_fri == expected_fri_settle

        # 2. On and after May 28, 2024: Standard T+1 business day (SEC Release No. 34-96930)
        # Tuesday May 28, 2024 14:30:00 UTC -> settles Wednesday May 29, 2024 14:30:00 UTC
        t_tue_may_28 = parse_iso_date_to_utc_ns("2024-05-28") + 14 * 3600 * 1_000_000_000
        settle_tue_post = calculate_settlement_timestamp_ns(t_tue_may_28)
        expected_tue_post = (
            parse_iso_date_to_utc_ns("2024-05-29") + 14 * 3600 * 1_000_000_000
        )
        assert settle_tue_post == expected_tue_post

        # Friday May 31, 2024 15:00:00 UTC -> settles Monday June 3, 2024 15:00:00 UTC
        t_fri_may_31 = parse_iso_date_to_utc_ns("2024-05-31") + 15 * 3600 * 1_000_000_000
        settle_fri_post = calculate_settlement_timestamp_ns(t_fri_may_31)
        expected_fri_post = (
            parse_iso_date_to_utc_ns("2024-06-03") + 15 * 3600 * 1_000_000_000
        )
        assert settle_fri_post == expected_fri_post

        # Holiday awareness test: Wednesday July 3, 2024 (T+1):
        # Thursday July 4 is Independence Day (holiday).
        # Settles Friday July 5, 2024!
        t_wed_jul_03 = parse_iso_date_to_utc_ns("2024-07-03") + 15 * 3600 * 1_000_000_000
        settle_wed_jul = calculate_settlement_timestamp_ns(t_wed_jul_03)
        expected_wed_jul = (
            parse_iso_date_to_utc_ns("2024-07-05") + 15 * 3600 * 1_000_000_000
        )
        assert settle_wed_jul == expected_wed_jul

        # 3. Explicit override of settlement days
        settle_custom = calculate_settlement_timestamp_ns(t_tue_may_21, settlement_days=1)
        expected_custom = (
            parse_iso_date_to_utc_ns("2024-05-22") + 14 * 3600 * 1_000_000_000
        )
        assert settle_custom == expected_custom

        # 4. Strict requirement for unsupported years outside 2024-2032
        t_unsupported_past = (
            parse_iso_date_to_eastern_ns("2023-05-15") + 14 * 3600 * 1_000_000_000
        )
        with pytest.raises(
            BacktestConfigurationError,
            match="outside the verified U.S. settlement holiday calendar period",
        ):
            calculate_settlement_timestamp_ns(t_unsupported_past)

        t_unsupported_future = (
            parse_iso_date_to_eastern_ns("2033-05-15") + 14 * 3600 * 1_000_000_000
        )
        with pytest.raises(
            BacktestConfigurationError,
            match="outside the verified U.S. settlement holiday calendar period",
        ):
            calculate_settlement_timestamp_ns(t_unsupported_future)

        # Providing explicit custom settlement holidays for unsupported year succeeds
        settle_unsupported_ok = calculate_settlement_timestamp_ns(
            t_unsupported_past,
            settlement_days=1,
            settlement_holidays=frozenset({date(2023, 5, 29)}),
        )
        expected_unsupported_ok = (
            parse_iso_date_to_eastern_ns("2023-05-16") + 14 * 3600 * 1_000_000_000
        )
        assert settle_unsupported_ok == expected_unsupported_ok

        # Verify holiday set and yearly calendar helper
        holidays_2024 = get_us_settlement_holidays_for_year(2024)
        assert date(2024, 1, 1) in holidays_2024
        assert date(2024, 7, 4) in US_SETTLEMENT_HOLIDAYS_2024_2032
        assert date(2024, 7, 4) in US_SETTLEMENT_HOLIDAYS_2024_2029

        # Error handling for negative values
        with pytest.raises(BacktestConfigurationError, match="must be non-negative"):
            calculate_settlement_timestamp_ns(-1)
        with pytest.raises(BacktestConfigurationError, match="must be non-negative"):
            calculate_settlement_timestamp_ns(t_tue_may_21, settlement_days=-1)

    def test_settlement_calendar_observed_new_years_day_regression(self) -> None:
        """Regression tests for observed New Year's Day falling on Friday Dec 31 in prior year.

        Verifies:
        1. New Year's Day 2028 (Saturday, Jan 1, 2028) is observed on Friday, Dec 31, 2027.
        2. calculate_settlement_timestamp_ns treats Dec 31, 2027 as a non-settlement day.
        3. A trade executed on Thursday Dec 30, 2027 settles on Monday Jan 3, 2028 under T+1.
        4. A trade executed on Friday Dec 31, 2027 (holiday) rolls forward and settles
           Tuesday Jan 4, 2028.
        5. A trade executed on Wednesday Dec 29, 2027 settles normally on Thursday Dec 30, 2027.
        6. Observed New Year's holidays falling in the previous year are handled correctly for
           every supported year across the 2024-2032 calendar.
        """
        # 1. Direct membership verification for 2027-12-31 (observed New Year's Day 2028)
        observed_ny_2028 = date(2027, 12, 31)
        assert observed_ny_2028 in US_SETTLEMENT_HOLIDAYS_2024_2032
        assert observed_ny_2028 in US_SETTLEMENT_HOLIDAYS_2024_2029
        # Present in both 2027 set (observed for next year) and 2028 set (observed NYD)
        assert observed_ny_2028 in get_us_settlement_holidays_for_year(2027)
        assert observed_ny_2028 in get_us_settlement_holidays_for_year(2028)

        # 2. Thursday Dec 30, 2027 (trade date): T+1 must skip Friday Dec 31 (holiday) + weekend
        # -> Settles Monday Jan 3, 2028!
        t_thu_dec_30_2027 = (
            parse_iso_date_to_utc_ns("2027-12-30") + 15 * 3600 * 1_000_000_000
        )
        settle_dec_30 = calculate_settlement_timestamp_ns(t_thu_dec_30_2027)
        expected_settle_jan_03 = (
            parse_iso_date_to_utc_ns("2028-01-03") + 15 * 3600 * 1_000_000_000
        )
        assert settle_dec_30 == expected_settle_jan_03

        # 3. Friday Dec 31, 2027: Non-settlement day; rolls to Mon Jan 3 + 1 = Tue Jan 4, 2028
        t_fri_dec_31_2027 = (
            parse_iso_date_to_utc_ns("2027-12-31") + 15 * 3600 * 1_000_000_000
        )
        settle_dec_31 = calculate_settlement_timestamp_ns(t_fri_dec_31_2027)
        expected_settle_jan_04 = (
            parse_iso_date_to_utc_ns("2028-01-04") + 15 * 3600 * 1_000_000_000
        )
        assert settle_dec_31 == expected_settle_jan_04

        # 4. Wednesday Dec 29, 2027: T+1 settles Thursday Dec 30, 2027 (business day)
        t_wed_dec_29_2027 = (
            parse_iso_date_to_utc_ns("2027-12-29") + 15 * 3600 * 1_000_000_000
        )
        settle_dec_29 = calculate_settlement_timestamp_ns(t_wed_dec_29_2027)
        expected_settle_dec_30 = (
            parse_iso_date_to_utc_ns("2027-12-30") + 15 * 3600 * 1_000_000_000
        )
        assert settle_dec_29 == expected_settle_dec_30

        # 5. New Year's Day 2033 (Saturday, Jan 1, 2033): Observed Friday, Dec 31, 2032
        assert date(2033, 1, 1).weekday() == 5
        observed_ny_2033 = date(2032, 12, 31)
        assert observed_ny_2033 in US_SETTLEMENT_HOLIDAYS_2024_2032
        assert observed_ny_2033 in get_us_settlement_holidays_for_year(2032)

        # Thursday Dec 30, 2032 settles Monday Jan 3, 2033
        t_thu_dec_30_2032 = (
            parse_iso_date_to_utc_ns("2032-12-30") + 14 * 3600 * 1_000_000_000
        )
        # Settle dec 30, 2032: Friday Dec 31 is holiday, Saturday Jan 1, Sunday Jan 2
        # But Jan 3, 2033 is in 2033. Providing holidays_2032_2033 frozenset or checking calendar:
        # Note: calculate_settlement_timestamp_ns checks trade_date year (2032 <= 2032)
        settle_dec_30_2032 = calculate_settlement_timestamp_ns(t_thu_dec_30_2032)
        expected_settle_jan_03_2033 = (
            parse_iso_date_to_utc_ns("2033-01-03") + 14 * 3600 * 1_000_000_000
        )
        assert settle_dec_30_2032 == expected_settle_jan_03_2033

        # 6. Comprehensive invariant across all supported calendar years 2024..2032
        for year in range(2024, 2033):
            # Check if next year's New Year's Day falls on Saturday
            ny_next_year = date(year + 1, 1, 1)
            if ny_next_year.weekday() == 5:
                observed_date = date(year, 12, 31)
                assert observed_date in US_SETTLEMENT_HOLIDAYS_2024_2032, (
                    f"Observed New Year's Day {observed_date} missing from holidays calendar"
                )
                assert observed_date in get_us_settlement_holidays_for_year(year)
                assert observed_date in get_us_settlement_holidays_for_year(year + 1)

                # Verify calculate_settlement_timestamp_ns skips observed_date
                t_dec_30 = parse_iso_date_to_utc_ns(f"{year}-12-30") + 12 * 3600 * 1_000_000_000
                res = calculate_settlement_timestamp_ns(t_dec_30)
                # Must settle in the next calendar year, skipping Friday Dec 31
                assert res > parse_iso_date_to_utc_ns(f"{year}-12-31")

    def test_trade_date_vs_settlement_date_statutory_applicability(self) -> None:
        """Verify SEC Rule 31 charge date resolution vs. FINRA TAF trade date semantics.

        Statutory Citations:
        - SEC Rule 31 (17 CFR § 240.31(a)(3); SEC Release No. 34-49928):
          (i) For covered sales reported using clearing agency data (§ 240.31(a)(3)(i)),
              charge date is the SETTLEMENT DATE.
          (ii) For covered sales reported other than through clearing agency data
              (§ 240.31(a)(3)(ii)), charge date is the TRADE DATE.
        - FINRA Schedule A, Section 1(b) (SR-FINRA-2026-020, SR-FINRA-2026-021):
          TAF is assessed strictly based on the TRANSACTION DATE (Trade Execution Date).
        """
        # Transition boundary: Fill immediately before May 22, 2024 (May 21, 2024 23:59:59 UTC)
        # May 22, 2024 is the effective date of SEC Release No. 34-100006 ($8.00 -> $27.80/million).
        t_trade_may_21 = (
            parse_iso_date_to_utc_ns("2024-05-21")
            + (23 * 3600 + 59 * 60 + 59) * 1_000_000_000
        )
        # Model sale of 1,000 shares @ $100.00 = $100,000 gross principal
        qty = 1000
        price_ticks = 10000  # $100.00 @ price_scale 100.0
        principal = 100_000.0

        # --- Case 1: CLEARING_SETTLEMENT_DATE (17 CFR § 240.31(a)(3)(i)) ---
        # The trade executed on May 21 settles on or after May 22, 2024.
        # Its charge date is >= May 22, 2024, so it MUST resolve the SEC rate to $27.80/million!
        # Meanwhile, FINRA TAF is evaluated on trade date (May 21), paying $0.000195/share.
        cfg_clearing = CostModelConfig(
            fee_schedules=create_standard_us_equities_schedules(),
            sec_charge_date_rule=SecChargeDateRule.CLEARING_SETTLEMENT_DATE,
            settlement_days=1,  # Explicitly models settlement on May 22, 2024
        )
        calc_clearing = TransactionCostCalculator(cfg_clearing)

        _, _, _, reg_fee_clearing = calc_clearing.calculate_costs(
            timestamp_ns=t_trade_may_21,
            side=OrderSide.SELL,
            quantity=qty,
            fill_price_ticks=price_ticks,
            quote_bid_ticks=price_ticks,
            quote_ask_ticks=price_ticks + 10,
        )
        expected_sec_2780 = 0.0000278 * principal  # $2.78
        expected_taf_trade_date = 0.000195 * qty   # $0.195
        assert math.isclose(
            reg_fee_clearing, expected_sec_2780 + expected_taf_trade_date, abs_tol=1e-5
        )

        # --- Case 2: TRADE_DATE (17 CFR § 240.31(a)(3)(ii)) ---
        # For non-clearing direct reporting, charge date is the trade execution date (May 21).
        # Since May 21 < May 22, it resolves the SEC rate to $8.00/million!
        cfg_trade = CostModelConfig(
            fee_schedules=create_standard_us_equities_schedules(),
            sec_charge_date_rule=SecChargeDateRule.TRADE_DATE,
        )
        calc_trade = TransactionCostCalculator(cfg_trade)

        _, _, _, reg_fee_trade = calc_trade.calculate_costs(
            timestamp_ns=t_trade_may_21,
            side=OrderSide.SELL,
            quantity=qty,
            fill_price_ticks=price_ticks,
            quote_bid_ticks=price_ticks,
            quote_ask_ticks=price_ticks + 10,
        )
        expected_sec_800 = 0.0000080 * principal  # $0.80
        assert math.isclose(
            reg_fee_trade, expected_sec_800 + expected_taf_trade_date, abs_tol=1e-5
        )

        # --- Case 3: Both sides of rate transition ---
        # (a) Trade executed Friday May 17, 2024 settling Tuesday May 21, 2024 (pre-transition):
        # Charge date is May 21 under both rules -> rate is $8.00/million.
        t_trade_may_17 = parse_iso_date_to_utc_ns("2024-05-17") + 14 * 3600 * 1_000_000_000
        _, _, _, reg_fee_pre = calc_clearing.calculate_costs(
            timestamp_ns=t_trade_may_17,
            side=OrderSide.SELL,
            quantity=qty,
            fill_price_ticks=price_ticks,
            quote_bid_ticks=price_ticks,
            quote_ask_ticks=price_ticks + 10,
            settlement_timestamp_ns=(
                parse_iso_date_to_eastern_ns("2024-05-21") + 14 * 3600 * 1_000_000_000
            ),
        )
        assert math.isclose(reg_fee_pre, expected_sec_800 + expected_taf_trade_date, abs_tol=1e-5)

        # (b) Trade executed on Wednesday May 22, 2024 settling May 23 (post-transition):
        # Charge date is May 22 or 23 -> rate is $27.80/million under both rules.
        t_trade_may_22 = parse_iso_date_to_utc_ns("2024-05-22") + 14 * 3600 * 1_000_000_000
        _, _, _, reg_fee_post_clearing = calc_clearing.calculate_costs(
            timestamp_ns=t_trade_may_22,
            side=OrderSide.SELL,
            quantity=qty,
            fill_price_ticks=price_ticks,
            quote_bid_ticks=price_ticks,
            quote_ask_ticks=price_ticks + 10,
        )
        _, _, _, reg_fee_post_trade = calc_trade.calculate_costs(
            timestamp_ns=t_trade_may_22,
            side=OrderSide.SELL,
            quantity=qty,
            fill_price_ticks=price_ticks,
            quote_bid_ticks=price_ticks,
            quote_ask_ticks=price_ticks + 10,
        )
        assert math.isclose(
            reg_fee_post_clearing, expected_sec_2780 + expected_taf_trade_date, abs_tol=1e-5
        )
        assert math.isclose(
            reg_fee_post_trade, expected_sec_2780 + expected_taf_trade_date, abs_tol=1e-5
        )

        # --- Case 4: May 14, 2025 Transition ($27.80 -> $0.00/million) ---
        # Trade executed May 13, 2025 settling May 14, 2025:
        # Clearing rule: charge date is May 14 -> SEC rate is $0.00!
        # Trade-date rule: charge date is May 13 -> SEC rate is $27.80!
        t_trade_may_13 = parse_iso_date_to_utc_ns("2025-05-13") + 14 * 3600 * 1_000_000_000
        _, _, _, fee_may_13_clearing = calc_clearing.calculate_costs(
            timestamp_ns=t_trade_may_13,
            side=OrderSide.SELL,
            quantity=qty,
            fill_price_ticks=price_ticks,
            quote_bid_ticks=price_ticks,
            quote_ask_ticks=price_ticks + 10,
            settlement_timestamp_ns=(
                parse_iso_date_to_eastern_ns("2025-05-14") + 14 * 3600 * 1_000_000_000
            ),
        )
        _, _, _, fee_may_13_trade = calc_trade.calculate_costs(
            timestamp_ns=t_trade_may_13,
            side=OrderSide.SELL,
            quantity=qty,
            fill_price_ticks=price_ticks,
            quote_bid_ticks=price_ticks,
            quote_ask_ticks=price_ticks + 10,
        )
        # Clearing receives $0.00 SEC + $0.195 TAF = $0.195
        assert math.isclose(fee_may_13_clearing, expected_taf_trade_date, abs_tol=1e-5)
        # Trade-date receives $2.78 SEC + $0.195 TAF = $2.975
        assert math.isclose(
            fee_may_13_trade, expected_sec_2780 + expected_taf_trade_date, abs_tol=1e-5
        )

    def test_finra_taf_trade_date_independence_and_resumption(self) -> None:
        """Verify FINRA TAF applies strictly on trade date, independent of SEC charge date.

        Tests:
        1. Trade on 2026-09-30 (settling 2026-10-01): TAF active ($0.000195/share, cap $9.79).
        2. Trade on 2026-10-01: FINRA TAF paused ($0.00/share per SR-FINRA-2026-021).
        3. Trade on 2027-01-01: TAF resumes ($0.000195/share, cap $9.79, SR-FINRA-2026-020).
        4. Trade on 2029-01-01: TAF delayed hike ($0.000232/share, cap $11.61).
        """
        cfg = CostModelConfig(
            fee_schedules=create_standard_us_equities_schedules(),
            sec_charge_date_rule=SecChargeDateRule.CLEARING_SETTLEMENT_DATE,
        )
        calc = TransactionCostCalculator(cfg)
        qty = 10_000
        price_ticks = 5000  # $50.00 @ price_scale 100.0
        principal = 500_000.0  # 10,000 * $50.00
        expected_sec_fee = 0.0000206 * principal  # $10.30

        # Step 1: Trade on 2026-09-30 20:00:00 UTC, settling on 2026-10-01
        t_sep_30 = (
            parse_iso_date_to_utc_ns("2026-09-30") + 20 * 3600 * 1_000_000_000
        )
        t_settle_oct_01 = (
            parse_iso_date_to_eastern_ns("2026-10-01") + 14 * 3600 * 1_000_000_000
        )
        _, _, _, reg_sep_30 = calc.calculate_costs(
            timestamp_ns=t_sep_30,
            side=OrderSide.SELL,
            quantity=qty,
            fill_price_ticks=price_ticks,
            quote_bid_ticks=price_ticks,
            quote_ask_ticks=price_ticks + 10,
            settlement_timestamp_ns=t_settle_oct_01,
        )
        # SEC fee evaluated on Oct 1 ($20.60/mil -> $10.30)
        # FINRA TAF evaluated on Sep 30 (Trade Date: $0.000195 * 10,000 = $1.95)
        # Even though settlement is in October pause, TAF is NOT paused because
        # the trade date is Sept 30!
        assert math.isclose(reg_sep_30, expected_sec_fee + 1.95, abs_tol=1e-5)

        # Step 2: Trade on 2026-10-01 14:30:00 UTC (In Pause Period)
        t_oct_01 = parse_iso_date_to_utc_ns("2026-10-01") + 14 * 3600 * 1_000_000_000
        _, _, _, reg_oct_01 = calc.calculate_costs(
            timestamp_ns=t_oct_01,
            side=OrderSide.SELL,
            quantity=qty,
            fill_price_ticks=price_ticks,
            quote_bid_ticks=price_ticks,
            quote_ask_ticks=price_ticks + 10,
        )
        # SEC fee: $10.30; FINRA TAF: $0.00
        assert math.isclose(reg_oct_01, expected_sec_fee + 0.0, abs_tol=1e-5)

        # Step 3: Trade on 2027-01-01 14:30:00 UTC (Resumption Period)
        t_jan_01 = parse_iso_date_to_utc_ns("2027-01-01") + 14 * 3600 * 1_000_000_000
        _, _, _, reg_jan_01 = calc.calculate_costs(
            timestamp_ns=t_jan_01,
            side=OrderSide.SELL,
            quantity=qty,
            fill_price_ticks=price_ticks,
            quote_bid_ticks=price_ticks,
            quote_ask_ticks=price_ticks + 10,
        )
        # SEC fee: $10.30; FINRA TAF resumes at $0.000195 * 10,000 = $1.95
        assert math.isclose(reg_jan_01, expected_sec_fee + 1.95, abs_tol=1e-5)

        # Step 4: Trade on 2029-01-01 14:30:00 UTC (Delayed Fee Increase Period)
        t_jan_01_2029 = parse_iso_date_to_utc_ns("2029-01-01") + 14 * 3600 * 1_000_000_000
        _, _, _, reg_jan_01_2029 = calc.calculate_costs(
            timestamp_ns=t_jan_01_2029,
            side=OrderSide.SELL,
            quantity=qty,
            fill_price_ticks=price_ticks,
            quote_bid_ticks=price_ticks,
            quote_ask_ticks=price_ticks + 10,
        )
        # SEC fee: $10.30; FINRA TAF step-up at $0.000232 * 10,000 = $2.32
        assert math.isclose(reg_jan_01_2029, expected_sec_fee + 2.32, abs_tol=1e-5)

        # Step 5: Trade on 2030-01-01 14:30:00 UTC (2030 Fee Step-Up)
        t_jan_01_2030 = parse_iso_date_to_utc_ns("2030-01-01") + 14 * 3600 * 1_000_000_000
        _, _, _, reg_jan_01_2030 = calc.calculate_costs(
            timestamp_ns=t_jan_01_2030,
            side=OrderSide.SELL,
            quantity=qty,
            fill_price_ticks=price_ticks,
            quote_bid_ticks=price_ticks,
            quote_ask_ticks=price_ticks + 10,
        )
        # SEC fee: $10.30; FINRA TAF step-up at $0.000240 * 10,000 = $2.40
        assert math.isclose(reg_jan_01_2030, expected_sec_fee + 2.40, abs_tol=1e-5)

        # Step 6: Trade on 2031-01-01 14:30:00 UTC (2031 Onward Fee Step-Up)
        t_jan_01_2031 = parse_iso_date_to_utc_ns("2031-01-01") + 14 * 3600 * 1_000_000_000
        _, _, _, reg_jan_01_2031 = calc.calculate_costs(
            timestamp_ns=t_jan_01_2031,
            side=OrderSide.SELL,
            quantity=qty,
            fill_price_ticks=price_ticks,
            quote_bid_ticks=price_ticks,
            quote_ask_ticks=price_ticks + 10,
        )
        # SEC fee: $10.30; FINRA TAF step-up at $0.000249 * 10,000 = $2.49
        assert math.isclose(reg_jan_01_2031, expected_sec_fee + 2.49, abs_tol=1e-5)

    def test_cost_model_config_charge_date_validation(self) -> None:
        """Verify configuration validation and string normalization for charge date rules."""
        cfg_str1 = CostModelConfig(sec_charge_date_rule="settlement_date")
        assert cfg_str1.sec_charge_date_rule == SecChargeDateRule.CLEARING_SETTLEMENT_DATE

        cfg_str2 = CostModelConfig(sec_charge_date_rule="clearing_settlement_date")
        assert cfg_str2.sec_charge_date_rule == SecChargeDateRule.CLEARING_SETTLEMENT_DATE

        cfg_str3 = CostModelConfig(sec_charge_date_rule="trade_date")
        assert cfg_str3.sec_charge_date_rule == SecChargeDateRule.TRADE_DATE

        with pytest.raises(BacktestConfigurationError, match="Invalid sec_charge_date_rule"):
            CostModelConfig(sec_charge_date_rule="invalid_rule")

        with pytest.raises(BacktestConfigurationError, match="settlement_days cannot be negative"):
            CostModelConfig(settlement_days=-2)

    def test_timezone_utc_midnight_boundaries_and_after_hours(self) -> None:
        """Verify fee schedules evaluate using America/New_York date, not UTC date.

        Tests:
        1. EDT (UTC-4) transition May 21 -> May 22, 2024:
           - 19:30 EDT May 21 (23:30 UTC May 21): $8.00 SEC rate.
           - 20:00 EDT May 21 (00:00 UTC May 22, UTC midnight): $8.00 SEC rate (still May 21 in NY).
           - 20:30 EDT May 21 (00:30 UTC May 22): $8.00 SEC rate (after-hours, still May 21 in NY).
           - 23:59:59.999999999 EDT May 21 (03:59:59 UTC May 22): $8.00 SEC rate.
           - 00:00:00.000000000 EDT May 22 (04:00:00 UTC May 22, Eastern midnight): $27.80 SEC rate.
           - 09:30:00 EDT May 22 (13:30:00 UTC May 22, market open): $27.80 SEC rate.
        2. EST (UTC-5) transition Dec 31, 2026 -> Jan 1, 2027:
           - 19:30 EST Dec 31 (00:30 UTC Jan 1): TAF paused at $0.00.
           - 20:00 EST Dec 31 (01:00 UTC Jan 1): TAF paused at $0.00.
           - 23:59:59.999999999 EST Dec 31 (04:59:59 UTC Jan 1): TAF paused at $0.00.
           - 00:00:00.000000000 EST Jan 1 (05:00:00 UTC Jan 1, Eastern midnight): TAF resumed.
        """
        cfg = CostModelConfig(fee_schedules=create_standard_us_equities_schedules())

        # 1. EDT Transition: May 21 -> May 22, 2024
        ts_may_21_midnight_eastern = parse_iso_date_to_eastern_ns("2024-05-21")
        ts_may_22_midnight_eastern = parse_iso_date_to_eastern_ns("2024-05-22")

        # 19:30 EDT on May 21 (23:30 UTC May 21)
        t_1930_edt = ts_may_21_midnight_eastern + int(19.5 * 3600 * 1_000_000_000)
        assert timestamp_ns_to_eastern_date(t_1930_edt) == date(2024, 5, 21)
        assert cfg.get_fee_schedule(t_1930_edt).sec_section_31_rate == 0.0000080

        # 20:00 EDT on May 21 (00:00:00 UTC May 22, UTC Midnight!)
        t_2000_edt_utc_midnight = (
            ts_may_21_midnight_eastern + 20 * 3600 * 1_000_000_000
        )
        assert timestamp_ns_to_eastern_date(t_2000_edt_utc_midnight) == date(2024, 5, 21)
        assert (
            cfg.get_fee_schedule(t_2000_edt_utc_midnight).sec_section_31_rate
            == 0.0000080
        )

        # 20:30 EDT on May 21 (00:30:00 UTC May 22)
        t_2030_edt = ts_may_21_midnight_eastern + int(20.5 * 3600 * 1_000_000_000)
        assert timestamp_ns_to_eastern_date(t_2030_edt) == date(2024, 5, 21)
        assert cfg.get_fee_schedule(t_2030_edt).sec_section_31_rate == 0.0000080

        # 23:59:59.999999999 EDT on May 21 (03:59:59.999999999 UTC May 22)
        t_last_ns_may_21 = ts_may_22_midnight_eastern - 1
        assert timestamp_ns_to_eastern_date(t_last_ns_may_21) == date(2024, 5, 21)
        assert cfg.get_fee_schedule(t_last_ns_may_21).sec_section_31_rate == 0.0000080

        # 00:00:00.000000000 EDT on May 22 (04:00:00 UTC May 22, Eastern Midnight)
        assert timestamp_ns_to_eastern_date(ts_may_22_midnight_eastern) == date(2024, 5, 22)
        assert (
            cfg.get_fee_schedule(ts_may_22_midnight_eastern).sec_section_31_rate
            == 0.0000278
        )

        # 09:30:00 EDT on May 22 (13:30:00 UTC May 22, Market Open)
        t_0930_edt = ts_may_22_midnight_eastern + int(9.5 * 3600 * 1_000_000_000)
        assert timestamp_ns_to_eastern_date(t_0930_edt) == date(2024, 5, 22)
        assert cfg.get_fee_schedule(t_0930_edt).sec_section_31_rate == 0.0000278

        # 2. EST Transition: Dec 31, 2026 -> Jan 1, 2027 (TAF pause -> resumption)
        ts_dec_31_midnight_eastern = parse_iso_date_to_eastern_ns("2026-12-31")
        ts_jan_01_midnight_eastern = parse_iso_date_to_eastern_ns("2027-01-01")

        # 19:30 EST Dec 31 (00:30 UTC Jan 1, 2027)
        t_1930_est = ts_dec_31_midnight_eastern + int(19.5 * 3600 * 1_000_000_000)
        assert timestamp_ns_to_eastern_date(t_1930_est) == date(2026, 12, 31)
        assert cfg.get_fee_schedule(t_1930_est).finra_taf_rate_per_share == 0.0

        # 20:00 EST Dec 31 (01:00 UTC Jan 1, 2027)
        t_2000_est = ts_dec_31_midnight_eastern + 20 * 3600 * 1_000_000_000
        assert timestamp_ns_to_eastern_date(t_2000_est) == date(2026, 12, 31)
        assert cfg.get_fee_schedule(t_2000_est).finra_taf_rate_per_share == 0.0

        # 23:59:59.999999999 EST Dec 31 (04:59:59.999999999 UTC Jan 1, 2027)
        t_last_ns_dec_31 = ts_jan_01_midnight_eastern - 1
        assert timestamp_ns_to_eastern_date(t_last_ns_dec_31) == date(2026, 12, 31)
        assert cfg.get_fee_schedule(t_last_ns_dec_31).finra_taf_rate_per_share == 0.0

        # 00:00:00.000000000 EST Jan 1, 2027 (05:00:00 UTC Jan 1, 2027)
        assert timestamp_ns_to_eastern_date(ts_jan_01_midnight_eastern) == date(2027, 1, 1)
        assert (
            cfg.get_fee_schedule(ts_jan_01_midnight_eastern).finra_taf_rate_per_share
            == 0.000195
        )

    def test_settlement_calendar_utc_midnight_and_after_hours(self) -> None:
        """Verify settlement derives correct trade and settlement dates across UTC midnight.

        Tests executions on Thursday Dec 30, 2027 around the 20:00:00 EST boundary:
        - In UTC, Eastern evening timestamps cross into the next UTC calendar day (Dec 31).
        - In America/New_York, calendar execution date is Dec 30, 2027.
        - Friday Dec 31, 2027 is observed New Year's Day (official clearing holiday).
        - Saturday Jan 1 and Sunday Jan 2 are weekend.

        Statutory Settlement vs. Reporting Distinction:
        - Under SEC Rule 15c6-1(a) (17 CFR § 240.15c6-1(a)), standard statutory settlement is
          T+1 business day from the trade date.
        - Under FINRA Rules 6380A/6380B, all executions on Thursday Dec 30, 2027 have regulatory
          trade date = Dec 30, 2027.
        - The 20:00:00 ET TRF operating close governs only the reporting submission window
          ('as/of' reporting due by 08:15 ET next business day); it does NOT postpone settlement.
        - Therefore, executions at 10:00, 19:59:59, 20:00:00, and 20:30 EST all settle on
          Monday Jan 3, 2028 under standard statutory T+1 settlement.
        """
        # 1. Regular hours trade at 10:00 EST on Thursday Dec 30, 2027
        t_trade_1000_est = (
            parse_iso_date_to_eastern_ns("2027-12-30") + 10 * 3600 * 1_000_000_000
        )
        settle_1000 = calculate_settlement_timestamp_ns(t_trade_1000_est)
        expected_1000 = (
            parse_iso_date_to_eastern_ns("2028-01-03") + 10 * 3600 * 1_000_000_000
        )
        assert settle_1000 == expected_1000
        assert timestamp_ns_to_eastern_date(settle_1000) == date(2028, 1, 3)

        # 2. Before 20:00:00 cutoff: 19:59:59 EST on Thursday Dec 30, 2027
        # In UTC: 2027-12-31 00:59:59 UTC (past UTC midnight)
        t_trade_1959_est = (
            parse_iso_date_to_eastern_ns("2027-12-30")
            + 19 * 3600 * 1_000_000_000
            + 59 * 60 * 1_000_000_000
            + 59 * 1_000_000_000
        )
        sec_1959_utc = t_trade_1959_est // 1_000_000_000
        dt_1959_utc = datetime.fromtimestamp(sec_1959_utc, tz=UTC)
        assert dt_1959_utc.date() == date(2027, 12, 31)
        assert dt_1959_utc.hour == 0
        assert dt_1959_utc.minute == 59
        assert dt_1959_utc.second == 59

        assert timestamp_ns_to_eastern_date(t_trade_1959_est) == date(2027, 12, 30)
        settle_1959 = calculate_settlement_timestamp_ns(t_trade_1959_est)
        expected_1959 = (
            parse_iso_date_to_eastern_ns("2028-01-03")
            + 19 * 3600 * 1_000_000_000
            + 59 * 60 * 1_000_000_000
            + 59 * 1_000_000_000
        )
        assert settle_1959 == expected_1959
        assert timestamp_ns_to_eastern_date(settle_1959) == date(2028, 1, 3)

        # 3. Exactly at 20:00:00 cutoff: 20:00:00 EST on Thursday Dec 30, 2027
        # In UTC: 2027-12-31 01:00:00 UTC (past UTC midnight)
        t_trade_2000_est = (
            parse_iso_date_to_eastern_ns("2027-12-30") + 20 * 3600 * 1_000_000_000
        )
        sec_2000_utc = t_trade_2000_est // 1_000_000_000
        dt_2000_utc = datetime.fromtimestamp(sec_2000_utc, tz=UTC)
        assert dt_2000_utc.date() == date(2027, 12, 31)
        assert dt_2000_utc.hour == 1

        assert timestamp_ns_to_eastern_date(t_trade_2000_est) == date(2027, 12, 30)

        # Under SEC Rule 15c6-1(a) standard T+1 settlement:
        # Trade date is Dec 30, 2027 -> settles Monday Jan 3, 2028!
        settle_2000 = calculate_settlement_timestamp_ns(t_trade_2000_est)
        expected_2000 = (
            parse_iso_date_to_eastern_ns("2028-01-03") + 20 * 3600 * 1_000_000_000
        )
        assert settle_2000 == expected_2000
        assert timestamp_ns_to_eastern_date(settle_2000) == date(2028, 1, 3)

        # 4. After-hours between 20:00 and midnight: 20:30:00 EST on Thursday Dec 30, 2027
        t_trade_2030_est = (
            parse_iso_date_to_eastern_ns("2027-12-30")
            + 20 * 3600 * 1_000_000_000
            + 30 * 60 * 1_000_000_000
        )
        settle_2030 = calculate_settlement_timestamp_ns(t_trade_2030_est)
        expected_2030 = (
            parse_iso_date_to_eastern_ns("2028-01-03")
            + 20 * 3600 * 1_000_000_000
            + 30 * 60 * 1_000_000_000
        )
        assert settle_2030 == expected_2030
        assert timestamp_ns_to_eastern_date(settle_2030) == date(2028, 1, 3)

    def test_finra_8pm_rule_6380a_trade_date_resolution(self) -> None:
        """Verify FINRA Rules 6380A/6380B trade date and reporting resolution.

        Distinguishes regulatory, reporting, and settlement date concepts:
        1. Eastern calendar date of execution (timestamp in America/New_York)
        2. FINRA regulatory trade date (contractual date of execution)
        3. FINRA reporting deadline ('as/of' deadline for >= 20:00 ET or non-business days)
        4. Settlement date (statutory T+1 from effective clearing date under 17 CFR § 240.15c6-1(a))
        5. SEC Section 31 charge date (settlement date for clearing; trade date for non-clearing)
        """
        # Scenario 1: Regular market hours (14:30:00 EST, Thursday Dec 30, 2027)
        t_1430 = (
            parse_iso_date_to_eastern_ns("2027-12-30")
            + 14 * 3600 * 1_000_000_000
            + 30 * 60 * 1_000_000_000
        )
        res_1430_clr = resolve_trade_and_settlement_dates(
            t_1430, sec_charge_date_rule=SecChargeDateRule.CLEARING_SETTLEMENT_DATE
        )
        assert isinstance(res_1430_clr, TradeDateResolution)
        assert res_1430_clr.execution_eastern_date == date(2027, 12, 30)
        assert res_1430_clr.finra_regulatory_trade_date == date(2027, 12, 30)
        assert res_1430_clr.finra_reporting_date == date(2027, 12, 30)
        assert res_1430_clr.is_as_of_reporting is False
        assert res_1430_clr.effective_clearing_date == date(2027, 12, 30)
        assert res_1430_clr.settlement_date == date(2028, 1, 3)
        assert res_1430_clr.sec_charge_date == date(2028, 1, 3)

        res_1430_td = resolve_trade_and_settlement_dates(
            t_1430, sec_charge_date_rule=SecChargeDateRule.TRADE_DATE
        )
        assert res_1430_td.sec_charge_date == date(2027, 12, 30)

        # Scenario 2: Immediately before 20:00 cutoff (19:59:59.999 EST, Thursday Dec 30, 2027)
        t_1959 = (
            parse_iso_date_to_eastern_ns("2027-12-30")
            + 19 * 3600 * 1_000_000_000
            + 59 * 60 * 1_000_000_000
            + 59 * 1_000_000_000
            + 999_000_000
        )
        res_1959 = resolve_trade_and_settlement_dates(t_1959)
        assert res_1959.execution_eastern_date == date(2027, 12, 30)
        assert res_1959.finra_regulatory_trade_date == date(2027, 12, 30)
        assert res_1959.finra_reporting_date == date(2027, 12, 30)
        assert res_1959.is_as_of_reporting is False
        assert res_1959.effective_clearing_date == date(2027, 12, 30)
        assert res_1959.settlement_date == date(2028, 1, 3)
        assert res_1959.sec_charge_date == date(2028, 1, 3)

        # Scenario 3: At exact 20:00:00.000 EST cutoff (Thursday Dec 30, 2027)
        # TRF facility closed (Rule 6380A); requires as/of reporting by next business day 08:15 ET.
        # Contractual trade date and statutory settlement date remain Dec 30, 2027 and Jan 3, 2028!
        t_2000 = (
            parse_iso_date_to_eastern_ns("2027-12-30") + 20 * 3600 * 1_000_000_000
        )
        res_2000 = resolve_trade_and_settlement_dates(t_2000)
        assert res_2000.execution_eastern_date == date(2027, 12, 30)
        assert res_2000.finra_regulatory_trade_date == date(2027, 12, 30)
        # Next reporting business day is Monday Jan 3, 2028 (Dec 31 is holiday, Jan 1-2 weekend)
        assert res_2000.finra_reporting_date == date(2028, 1, 3)
        assert res_2000.is_as_of_reporting is True
        # Business day execution enters clearing on execution date
        assert res_2000.effective_clearing_date == date(2027, 12, 30)
        # Standard T+1 settlement settles Monday Jan 3, 2028
        assert res_2000.settlement_date == date(2028, 1, 3)
        assert res_2000.sec_charge_date == date(2028, 1, 3)

        # Trade date SEC charge date rule uses execution date
        res_2000_td = resolve_trade_and_settlement_dates(
            t_2000, sec_charge_date_rule=SecChargeDateRule.TRADE_DATE
        )
        assert res_2000_td.sec_charge_date == date(2027, 12, 30)

        # Scenario 4: Between 20:00:00 and midnight (20:30:00 EST, Thursday Dec 30, 2027)
        t_2030 = (
            parse_iso_date_to_eastern_ns("2027-12-30")
            + 20 * 3600 * 1_000_000_000
            + 30 * 60 * 1_000_000_000
        )
        res_2030 = resolve_trade_and_settlement_dates(t_2030)
        assert res_2030.execution_eastern_date == date(2027, 12, 30)
        assert res_2030.finra_regulatory_trade_date == date(2027, 12, 30)
        assert res_2030.finra_reporting_date == date(2028, 1, 3)
        assert res_2030.is_as_of_reporting is True
        assert res_2030.effective_clearing_date == date(2027, 12, 30)
        assert res_2030.settlement_date == date(2028, 1, 3)

        # Scenario 5: End of day (23:59:59 EST, Thursday Dec 30, 2027)
        t_2359 = (
            parse_iso_date_to_eastern_ns("2027-12-30")
            + 23 * 3600 * 1_000_000_000
            + 59 * 60 * 1_000_000_000
            + 59 * 1_000_000_000
        )
        res_2359 = resolve_trade_and_settlement_dates(t_2359)
        assert res_2359.execution_eastern_date == date(2027, 12, 30)
        assert res_2359.finra_reporting_date == date(2028, 1, 3)
        assert res_2359.is_as_of_reporting is True
        assert res_2359.effective_clearing_date == date(2027, 12, 30)
        assert res_2359.settlement_date == date(2028, 1, 3)

        # Scenario 6: Observed Holiday (Friday Dec 31, 2027 at 11:00 EST)
        t_holiday = (
            parse_iso_date_to_eastern_ns("2027-12-31") + 11 * 3600 * 1_000_000_000
        )
        res_holiday = resolve_trade_and_settlement_dates(t_holiday)
        assert res_holiday.execution_eastern_date == date(2027, 12, 31)
        assert res_holiday.finra_regulatory_trade_date == date(2027, 12, 31)
        assert res_holiday.finra_reporting_date == date(2028, 1, 3)
        assert res_holiday.is_as_of_reporting is True
        assert res_holiday.effective_clearing_date == date(2028, 1, 3)
        assert res_holiday.settlement_date == date(2028, 1, 4)

        # Scenario 7: Weekend (Saturday Jan 1, 2028 at 12:00 EST)
        t_weekend = (
            parse_iso_date_to_eastern_ns("2028-01-01") + 12 * 3600 * 1_000_000_000
        )
        res_weekend = resolve_trade_and_settlement_dates(t_weekend)
        assert res_weekend.execution_eastern_date == date(2028, 1, 1)
        assert res_weekend.finra_regulatory_trade_date == date(2028, 1, 1)
        assert res_weekend.finra_reporting_date == date(2028, 1, 3)
        assert res_weekend.is_as_of_reporting is True
        assert res_weekend.effective_clearing_date == date(2028, 1, 3)
        assert res_weekend.settlement_date == date(2028, 1, 4)

        # Scenario 8: Integration with TransactionCostCalculator
        calc = TransactionCostCalculator(CostModelConfig())
        _, _, _, reg_fee = calc.calculate_costs(
            timestamp_ns=t_2000,
            side=OrderSide.SELL,
            quantity=1000,
            fill_price_ticks=10000,  # $100.00
            quote_bid_ticks=10000,
            quote_ask_ticks=10002,
        )
        assert reg_fee > 0.0

    def test_daylight_saving_transitions_settlement(self) -> None:
        """Verify settlement timestamps handle U.S. DST spring forward and fall back shifts."""
        # 1. Spring Forward 2026:
        # Friday, March 6, 2026 15:30 EST (UTC-5) -> 20:30 UTC
        # Sunday, March 8, 2026 02:00: Clocks forward 1 hour (EST -> EDT, UTC-4)
        # Monday, March 9, 2026 15:30 EDT (UTC-4) -> 19:30 UTC
        dt_fri_spring = datetime(2026, 3, 6, 15, 30, 0, tzinfo=US_EASTERN_TZ)
        t_trade_spring = int(dt_fri_spring.astimezone(UTC).timestamp()) * 1_000_000_000

        settle_spring = calculate_settlement_timestamp_ns(t_trade_spring)

        dt_mon_spring = datetime(2026, 3, 9, 15, 30, 0, tzinfo=US_EASTERN_TZ)
        expected_spring = int(dt_mon_spring.astimezone(UTC).timestamp()) * 1_000_000_000

        assert settle_spring == expected_spring
        assert timestamp_ns_to_eastern_date(settle_spring) == date(2026, 3, 9)
        # UTC duration is 71 hours (not 72) due to 1-hour spring forward jump:
        # 3 days * 24h = 72h - 1h = 71h
        duration_hours = (settle_spring - t_trade_spring) / (3600 * 1_000_000_000)
        assert math.isclose(duration_hours, 71.0, abs_tol=1e-5)

        # 2. Fall Back 2026:
        # Friday, October 30, 2026 15:30 EDT (UTC-4) -> 19:30 UTC
        # Sunday, November 1, 2026 02:00: Clocks back 1 hour (EDT -> EST, UTC-5)
        # Monday, November 2, 2026 15:30 EST (UTC-5) -> 20:30 UTC
        dt_fri_fall = datetime(2026, 10, 30, 15, 30, 0, tzinfo=US_EASTERN_TZ)
        t_trade_fall = int(dt_fri_fall.astimezone(UTC).timestamp()) * 1_000_000_000

        settle_fall = calculate_settlement_timestamp_ns(t_trade_fall)

        dt_mon_fall = datetime(2026, 11, 2, 15, 30, 0, tzinfo=US_EASTERN_TZ)
        expected_fall = int(dt_mon_fall.astimezone(UTC).timestamp()) * 1_000_000_000

        assert settle_fall == expected_fall
        assert timestamp_ns_to_eastern_date(settle_fall) == date(2026, 11, 2)
        # UTC duration is 73 hours (not 72) due to 1-hour fall back repeat:
        # 3 days * 24h = 72h + 1h = 73h
        duration_fall_hours = (settle_fall - t_trade_fall) / (3600 * 1_000_000_000)
        assert math.isclose(duration_fall_hours, 73.0, abs_tol=1e-5)

    def test_get_fee_schedule_for_date_convenience_helper(self) -> None:
        """Verify get_fee_schedule_for_date resolves fee schedules by calendar date."""
        cfg = CostModelConfig(fee_schedules=create_standard_us_equities_schedules())

        sched_2024_05_21 = cfg.get_fee_schedule_for_date(date(2024, 5, 21))
        assert sched_2024_05_21.sec_section_31_rate == 0.0000080

        sched_2024_05_22 = cfg.get_fee_schedule_for_date(date(2024, 5, 22))
        assert sched_2024_05_22.sec_section_31_rate == 0.0000278

        sched_pause = cfg.get_fee_schedule_for_date(date(2026, 10, 15))
        assert sched_pause.finra_taf_rate_per_share == 0.0

        sched_resume = cfg.get_fee_schedule_for_date(date(2027, 2, 1))
        assert sched_resume.finra_taf_rate_per_share == 0.000195

        sched_2029 = cfg.get_fee_schedule_for_date(date(2029, 6, 1))
        assert sched_2029.finra_taf_rate_per_share == 0.000232

        sched_2030 = cfg.get_fee_schedule_for_date(date(2030, 6, 1))
        assert sched_2030.finra_taf_rate_per_share == 0.000240

        sched_2031 = cfg.get_fee_schedule_for_date(date(2031, 6, 1))
        assert sched_2031.finra_taf_rate_per_share == 0.000249

    def test_buys_exempt_from_regulatory_fees(self) -> None:
        """Verify Buy orders pay zero SEC Section 31 and zero FINRA TAF."""
        cfg = CostModelConfig(fee_schedules=create_standard_us_equities_schedules())
        calc = TransactionCostCalculator(cfg)
        t = parse_iso_date_to_utc_ns("2024-06-01")

        _, _, _, reg_fee_buy = calc.calculate_costs(
            timestamp_ns=t,
            side=OrderSide.BUY,
            quantity=5000,
            fill_price_ticks=10010,
            quote_bid_ticks=10000,
            quote_ask_ticks=10010,
        )
        assert reg_fee_buy == 0.0

    def test_spread_and_slippage_separation_no_double_counting(self) -> None:
        """Verify spread cost and slippage are computed separately without overlap."""
        cfg = CostModelConfig(
            fixed_slippage_per_share=0.01,  # $0.01 per share slippage beyond touch
            slippage_impact_coeff=0.0,
            price_scale=100.0,
        )
        calc = TransactionCostCalculator(cfg)
        t = parse_iso_date_to_utc_ns("2024-06-01")

        # Bid = $100.00 (10000), Ask = $100.10 (10010), Mid = $100.05 (10005)
        # Half-spread is $0.05 (5 ticks = 0.05 dollars)
        spread_cost, slippage_cost, _, _ = calc.calculate_costs(
            timestamp_ns=t,
            side=OrderSide.BUY,
            quantity=200,
            fill_price_ticks=10010,
            quote_bid_ticks=10000,
            quote_ask_ticks=10010,
        )

        # Spread cost: 200 * $0.05 = $10.00
        assert math.isclose(spread_cost, 10.00)
        # Slippage cost: 200 * $0.01 = $2.00
        assert math.isclose(slippage_cost, 2.00)


class TestDeterministicBacktestEngine:
    """Tests for deterministic event-driven execution, causality, and accounting."""

    def test_flat_benchmark_produces_zero_trades_and_zero_cost(self) -> None:
        """Verify FlatBenchmarkStrategy results in zero activity, zero friction, and flat equity."""
        engine = DeterministicBacktestEngine(BacktestEngineConfig(initial_cash=500_000.0))
        flat_strat = FlatBenchmarkStrategy(instrument_id=1)

        # Create dummy market table
        n = 10
        ts = [1_000_000_000 + i * 1_000_000 for i in range(n)]
        table = pa.Table.from_pydict(
            {
                "event_timestamp_ns": ts,
                "decision_timestamp_ns": ts,
                "best_bid_price": [10000 + i * 5 for i in range(n)],
                "best_bid_quantity": [500] * n,
                "best_ask_price": [10010 + i * 5 for i in range(n)],
                "best_ask_quantity": [500] * n,
                "mid_price": [100.05 + i * 0.05 for i in range(n)],
            }
        )

        res = engine.run(table, flat_strat)
        assert res.total_trades == 0
        assert len(res.fills) == 0
        assert len(res.orders) == 0
        assert res.total_friction_cost == 0.0
        assert math.isclose(res.final_cash, 500_000.0)
        assert math.isclose(res.final_equity, 500_000.0)
        assert math.isclose(res.gross_pnl, 0.0)
        assert math.isclose(res.net_pnl, 0.0)

    def test_market_orders_only_rejects_limit_orders(self) -> None:
        """Verify submitting a LIMIT order raises error and records rejection."""
        engine = DeterministicBacktestEngine()
        limit_order = OrderIntent(
            order_id="LMT-001",
            decision_timestamp_ns=1_000,
            actionable_timestamp_ns=1_000,
            instrument_id=1,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            limit_price=10000,
        )

        with pytest.raises(UnsupportedOrderTypeError, match="strictly executes MARKET orders"):
            engine.submit_order_direct(limit_order)

    def test_causal_execution_with_latency(self) -> None:
        """Verify an order cannot fill prior to T_actionable and fills at future quote, not past."""
        latency_ns = 50_000_000  # 50ms latency
        engine = DeterministicBacktestEngine(
            BacktestEngineConfig(initial_cash=100_000.0, execution_latency_ns=latency_ns)
        )

        # t=0: Quote is Bid $100.00 (10000), Ask $100.10 (10010)
        engine.update_quote_direct(
            event_ts=100_000_000,
            avail_ts=100_000_000,
            bid_price=10000,
            bid_qty=1000,
            ask_price=10010,
            ask_qty=1000,
        )

        # t=100ms: Strategy makes decision to BUY 100 shares.
        # Order actionable timestamp is 100ms + 50ms = 150ms.
        order = OrderIntent(
            order_id="ORD-01",
            decision_timestamp_ns=100_000_000,
            actionable_timestamp_ns=150_000_000,
            instrument_id=1,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
            signal_event_timestamp_ns=100_000_000,
            signal_available_timestamp_ns=100_000_000,
        )
        engine.submit_order_direct(order)

        # At t=120ms (before actionable time), market updates to Ask $100.15 (10015)
        # Pending order MUST NOT fill yet!
        engine.update_quote_direct(
            event_ts=120_000_000,
            avail_ts=120_000_000,
            bid_price=10005,
            bid_qty=1000,
            ask_price=10015,
            ask_qty=1000,
        )
        engine.process_pending_orders_direct(120_000_000)
        assert len(engine._fills) == 0  # Still pending!

        # At t=150ms (actionable time arrives), market has moved to Ask $100.25 (10025)
        engine.update_quote_direct(
            event_ts=150_000_000,
            avail_ts=150_000_000,
            bid_price=10015,
            bid_qty=1000,
            ask_price=10025,
            ask_qty=1000,
        )
        engine.process_pending_orders_direct(150_000_000)

        # Order must now be filled at $100.25 (the prevailing ask at actionable time),
        # NEVER at the stale $100.10 from decision time!
        assert len(engine._fills) == 1
        fill = engine._fills[0]
        assert fill.price == 10025
        assert fill.fill_timestamp_ns == 150_000_000

    def test_liquidity_limits_and_partial_fill_behavior(self) -> None:
        """Verify engine rejects orders exceeding displayed depth unless partial fills allowed."""
        # Config 1: allow_partial_fills = False -> reject
        engine_strict = DeterministicBacktestEngine(
            BacktestEngineConfig(allow_partial_fills=False, enforce_liquidity_limits=True)
        )
        engine_strict.update_quote_direct(
            event_ts=100,
            avail_ts=100,
            bid_price=1000,
            bid_qty=50,  # Only 50 shares displayed at Bid
            ask_price=1010,
            ask_qty=50,
        )
        order_oversized = OrderIntent(
            order_id="ORD-BIG",
            decision_timestamp_ns=100,
            actionable_timestamp_ns=100,
            instrument_id=1,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,  # Wants 100 shares, but only 50 available
        )
        engine_strict.submit_order_direct(order_oversized)
        engine_strict.process_pending_orders_direct(100)

        assert len(engine_strict._fills) == 0
        assert len(engine_strict._rejected_orders) == 1
        assert "Insufficient liquidity" in engine_strict._rejected_orders[0][1]

        # Config 2: allow_partial_fills = True -> fills 50 shares
        engine_partial = DeterministicBacktestEngine(
            BacktestEngineConfig(allow_partial_fills=True, enforce_liquidity_limits=True)
        )
        engine_partial.update_quote_direct(
            event_ts=100,
            avail_ts=100,
            bid_price=1000,
            bid_qty=50,
            ask_price=1010,
            ask_qty=50,
        )
        engine_partial.submit_order_direct(order_oversized)
        engine_partial.process_pending_orders_direct(100)

        assert len(engine_partial._fills) == 1
        assert engine_partial._fills[0].quantity == 50

    def test_deterministic_replay_repeatability(self) -> None:
        """Verify identical inputs and configuration yield 100% bit-for-bit identical results."""
        cfg = BacktestEngineConfig(initial_cash=200_000.0, execution_latency_ns=10_000_000)

        # Synthetic alternating signal strategy
        class AlternatingStrategy(BaseStrategy):
            def fit(self, train_table: pa.Table) -> None:
                self._is_fitted = True

            def reset(self) -> None:
                pass

            def generate_signals(self, features_table: pa.Table) -> pa.Table:
                n = len(features_table)
                weights = [0.2 if i % 2 == 0 else -0.2 for i in range(n)]
                dirs = [1 if w > 0 else -1 for w in weights]
                dec_ts = features_table["decision_timestamp_ns"].to_pylist()
                return pa.Table.from_pydict(
                    {
                        "decision_timestamp_ns": dec_ts,
                        "instrument_id": [1] * n,
                        "direction": dirs,
                        "target_weight": weights,
                        "strength": [1.0] * n,
                        "confidence": [1.0] * n,
                        "is_valid": [True] * n,
                    }
                )

            def on_features(self, record: MicrostructureFeatureRecord) -> Signal | None:
                return None

        strat = AlternatingStrategy("Alternating")

        ts_base = parse_iso_date_to_utc_ns("2024-06-03") + 14 * 3600 * 1_000_000_000
        n = 20
        ts = [ts_base + i * 100_000_000 for i in range(n)]
        table = pa.Table.from_pydict(
            {
                "event_timestamp_ns": ts,
                "decision_timestamp_ns": ts,
                "best_bid_price": [10000 + (i % 3) * 10 for i in range(n)],
                "best_bid_quantity": [5000] * n,
                "best_ask_price": [10010 + (i % 3) * 10 for i in range(n)],
                "best_ask_quantity": [5000] * n,
                "mid_price": [100.05 + (i % 3) * 0.10 for i in range(n)],
            }
        )

        engine1 = DeterministicBacktestEngine(cfg)
        res1 = engine1.run(table, strat)

        engine2 = DeterministicBacktestEngine(cfg)
        res2 = engine2.run(table, strat)

        # Compare outputs for bit-for-bit equivalence
        assert res1.final_cash == res2.final_cash
        assert res1.final_equity == res2.final_equity
        assert res1.gross_pnl == res2.gross_pnl
        assert res1.net_pnl == res2.net_pnl
        assert res1.total_trades == res2.total_trades
        assert res1.total_friction_cost == res2.total_friction_cost
        assert len(res1.fills) == len(res2.fills)
        for f1, f2 in zip(res1.fills, res2.fills, strict=True):
            assert f1.price == f2.price
            assert f1.quantity == f2.quantity
            assert f1.total_transaction_cost == f2.total_transaction_cost

    def test_hand_calculated_trade_lifecycle_pnl_and_costs(self) -> None:
        """Penny-for-penny validation of Gross/Net PnL, Cash, and Costs on known Long trade."""
        # Setup: zero slippage, zero latency, standard fee schedule
        # (Post-May 22: $27.80/million SEC, $0.000195/share TAF capped at $9.79)
        schedules = [
            DatedFeeSchedule(
                effective_start_date_str="2024-01-01",
                effective_start_timestamp_ns=0,
                sec_section_31_rate=0.0000278,
                finra_taf_rate_per_share=0.000195,
                finra_taf_max_per_trade=9.79,
                finra_taf_min_per_trade=0.0,
                taker_fee_per_share=0.0030,
            )
        ]
        cost_cfg = CostModelConfig(
            fee_schedules=schedules,
            fixed_slippage_per_share=0.0,
            price_scale=100.0,
        )
        engine = DeterministicBacktestEngine(
            BacktestEngineConfig(
                initial_cash=100_000.0,
                execution_latency_ns=0,
                price_scale=100.0,
                cost_config=cost_cfg,
            )
        )

        t1 = parse_iso_date_to_utc_ns("2024-06-03") + 14 * 3600 * 1_000_000_000
        # Step 1: BUY 100 shares @ Ask $100.10 (Bid $100.00, Mid $100.05)
        # Trade notional @ touch = 100 * $100.10 = $10,010.00
        # Spread cost (economic attribution vs mid) = 100 * ($100.10 - $100.05) = $5.00
        # Exchange fee = 100 * $0.0030 = $0.30
        # Regulatory fee = $0.00 (Buy)
        # Out-of-pocket external friction on buy = $0.30
        # Cash after buy = $100,000.00 - $10,010.00 - $0.30 = $89,989.70
        engine.update_quote_direct(
            event_ts=t1, avail_ts=t1, bid_price=10000, bid_qty=500, ask_price=10010, ask_qty=500
        )
        order_buy = OrderIntent(
            order_id="BUY-01",
            decision_timestamp_ns=t1,
            actionable_timestamp_ns=t1,
            instrument_id=1,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
            signal_event_timestamp_ns=t1,
            signal_available_timestamp_ns=t1,
        )
        engine.submit_order_direct(order_buy)
        engine.process_pending_orders_direct(t1)

        assert math.isclose(engine._cash, 89989.70, abs_tol=1e-5)
        assert engine._position.quantity == 100
        assert math.isclose(engine._position.average_entry_price, 100.10, abs_tol=1e-5)

        # Mark to market equity at Mid $100.05:
        # Equity = $89,989.70 + (100 * $100.05) = $99,994.70
        # Net PnL = $99,994.70 - $100,000.00 = -$5.30 (exactly -$5.00 spread - $0.30 fee)
        curr_mid = (10000 + 10010) / (2.0 * 100.0)
        curr_equity = engine._calculate_current_equity(curr_mid)
        assert math.isclose(curr_equity, 99994.70, abs_tol=1e-5)

        # Step 2: Market price moves up to Bid $102.00, Ask $102.10 (Mid $102.05)
        t2 = parse_iso_date_to_utc_ns("2024-06-03") + 15 * 3600 * 1_000_000_000
        engine.update_quote_direct(
            event_ts=t2, avail_ts=t2, bid_price=10200, bid_qty=500, ask_price=10210, ask_qty=500
        )

        # Step 3: SELL 100 shares @ Bid $102.00 (Mid $102.05)
        # Trade notional @ touch = 100 * $102.00 = $10,200.00
        # Spread cost (economic attribution vs mid) = 100 * ($102.05 - $102.00) = $5.00
        # Exchange fee = 100 * $0.0030 = $0.30
        # SEC fee = 0.0000278 * $10,200 = $0.28356
        # FINRA TAF = 0.000195 * 100 = $0.0195
        # Regulatory fee = 0.28356 + 0.0195 = 0.30306
        # Out-of-pocket external friction on sell = $0.30 + $0.30306 = $0.60306
        # Cash after sell = $89,989.70 + $10,200.00 - $0.60306 = $100,189.09694
        order_sell = OrderIntent(
            order_id="SELL-01",
            decision_timestamp_ns=t2,
            actionable_timestamp_ns=t2,
            instrument_id=1,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=100,
            signal_event_timestamp_ns=t2,
            signal_available_timestamp_ns=t2,
        )
        engine.submit_order_direct(order_sell)
        engine.process_pending_orders_direct(t2)

        expected_final_cash = 89989.70 + 10200.00 - 0.60306
        assert math.isclose(engine._cash, expected_final_cash, abs_tol=1e-4)
        assert engine._position.quantity == 0

        # Step 4: Validate Gross PnL vs Net PnL reconciliation
        # Total friction costs across both legs:
        # Total Spread: $5.00 (buy) + $5.00 (sell) = $10.00
        # Total Exchange: $0.30 + $0.30 = $0.60
        # Total Regulatory: $0.30306
        # Total Friction: $10.00 + $0.60 + $0.30306 = $10.90306
        # Net PnL = Final Cash - Initial Cash = $100,189.09694 - $100,000.00 = +$189.09694
        # Economic Gross PnL (mid-to-mid): 100 * ($102.05 - $100.05) = $200.00
        res = engine._build_result()
        assert math.isclose(res.net_pnl, 189.09694, abs_tol=1e-4)
        assert math.isclose(res.total_spread_cost, 10.00, abs_tol=1e-4)
        assert math.isclose(res.total_exchange_fees, 0.60, abs_tol=1e-4)
        assert math.isclose(res.total_regulatory_fees, 0.30306, abs_tol=1e-4)
        assert math.isclose(res.total_friction_cost, 10.90306, abs_tol=1e-4)
        assert math.isclose(res.gross_pnl, 200.00, abs_tol=1e-4)
        # Fundamental Invariant: Net PnL + Total Friction == Gross PnL
        assert math.isclose(res.net_pnl + res.total_friction_cost, res.gross_pnl, abs_tol=1e-4)

    def test_hand_calculated_short_trade_lifecycle_pnl_and_costs(self) -> None:
        """Penny-for-penny validation of Gross/Net PnL, Cash, and Costs on Short trade."""
        schedules = [
            DatedFeeSchedule(
                effective_start_date_str="2024-01-01",
                effective_start_timestamp_ns=0,
                sec_section_31_rate=0.0000278,
                finra_taf_rate_per_share=0.000195,
                finra_taf_max_per_trade=9.79,
                finra_taf_min_per_trade=0.0,
                taker_fee_per_share=0.0030,
            )
        ]
        cost_cfg = CostModelConfig(fee_schedules=schedules, price_scale=100.0)
        engine = DeterministicBacktestEngine(
            BacktestEngineConfig(initial_cash=100_000.0, cost_config=cost_cfg)
        )

        t1 = parse_iso_date_to_utc_ns("2024-06-03") + 14 * 3600 * 1_000_000_000
        # Step 1: SELL SHORT 100 shares @ Bid $100.00 (Ask $100.10, Mid $100.05)
        # Notional = 100 * $100.00 = $10,000.00
        # Spread cost = 100 * ($100.05 - $100.00) = $5.00
        # Exchange fee = 100 * $0.0030 = $0.30
        # SEC fee = 0.0000278 * $10,000.00 = $0.278
        # FINRA TAF = 0.000195 * 100 = $0.0195
        # Regulatory fee = $0.2975
        # External friction = $0.30 + $0.2975 = $0.5975
        # Cash after short sale = $100,000.00 + $10,000.00 - $0.5975 = $109,999.4025
        engine.update_quote_direct(
            event_ts=t1, avail_ts=t1, bid_price=10000, bid_qty=500, ask_price=10010, ask_qty=500
        )
        order_short = OrderIntent(
            order_id="SHORT-01",
            decision_timestamp_ns=t1,
            actionable_timestamp_ns=t1,
            instrument_id=1,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=100,
            signal_event_timestamp_ns=t1,
            signal_available_timestamp_ns=t1,
        )
        engine.submit_order_direct(order_short)
        engine.process_pending_orders_direct(t1)

        assert math.isclose(engine._cash, 109999.4025, abs_tol=1e-4)
        assert engine._position.quantity == -100

        # Mark-to-market equity at Mid $100.05:
        # Equity = $109,999.4025 - (100 * $100.05) = $99,994.4025
        # Net PnL = $99,994.4025 - $100,000.00 = -$5.5975 (-$5.00 spread - $0.5975 fees)
        curr_mid = 100.05
        assert math.isclose(
            engine._calculate_current_equity(curr_mid), 99994.4025, abs_tol=1e-4
        )

        # Step 2: Stock price falls to Bid $98.00, Ask $98.10 (Mid $98.05)
        t2 = parse_iso_date_to_utc_ns("2024-06-03") + 15 * 3600 * 1_000_000_000
        engine.update_quote_direct(
            event_ts=t2, avail_ts=t2, bid_price=9800, bid_qty=500, ask_price=9810, ask_qty=500
        )

        # Step 3: BUY TO COVER 100 shares @ Ask $98.10
        # Notional = 100 * $98.10 = $9,810.00
        # Spread cost = 100 * ($98.10 - $98.05) = $5.00
        # Exchange fee = 100 * $0.0030 = $0.30
        # Regulatory fee = $0.00 (Buy)
        # External friction = $0.30
        # Cash after cover = $109,999.4025 - $9,810.00 - $0.30 = $100,189.1025
        order_cover = OrderIntent(
            order_id="COVER-01",
            decision_timestamp_ns=t2,
            actionable_timestamp_ns=t2,
            instrument_id=1,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
            signal_event_timestamp_ns=t2,
            signal_available_timestamp_ns=t2,
        )
        engine.submit_order_direct(order_cover)
        engine.process_pending_orders_direct(t2)

        assert math.isclose(engine._cash, 100189.1025, abs_tol=1e-4)
        assert engine._position.quantity == 0

        # Step 4: Reconcile short trade PnL
        # Economic Gross PnL: shorted @ mid $100.05, covered @ mid $98.05 = +$2.00 * 100 = $200.00
        # Total Friction: $10.00 spread + $0.60 exchange + $0.2975 reg fees = $10.8975
        # Net PnL: $200.00 - $10.8975 = +$189.1025
        res = engine._build_result()
        assert math.isclose(res.net_pnl, 189.1025, abs_tol=1e-4)
        assert math.isclose(res.total_friction_cost, 10.8975, abs_tol=1e-4)
        assert math.isclose(res.gross_pnl, 200.00, abs_tol=1e-4)
        assert math.isclose(res.net_pnl + res.total_friction_cost, res.gross_pnl, abs_tol=1e-4)

    def test_displayed_depth_consumption_across_sequential_orders(self) -> None:
        """Verify sequential orders consume displayed size and cannot reuse depleted depth."""
        engine = DeterministicBacktestEngine(
            BacktestEngineConfig(
                initial_cash=100_000.0,
                enforce_liquidity_limits=True,
                allow_partial_fills=False,
            )
        )
        t = 1_000_000_000
        # Quote with 150 shares displayed at Ask
        engine.update_quote_direct(
            event_ts=t, avail_ts=t, bid_price=10000, bid_qty=500, ask_price=10010, ask_qty=150
        )

        # Order 1: Buy 100 shares
        ord1 = OrderIntent(
            order_id="ORD-01",
            decision_timestamp_ns=t,
            actionable_timestamp_ns=t,
            instrument_id=1,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
        )
        engine.submit_order_direct(ord1)
        engine.process_pending_orders_direct(t)

        assert len(engine._fills) == 1
        assert engine._fills[0].quantity == 100
        # Displayed ask depth must now be reduced to 50 shares
        assert engine._best_ask_qty == 50

        # Order 2: Buy 60 shares (exceeds remaining 50 shares -> must be rejected)
        ord2 = OrderIntent(
            order_id="ORD-02",
            decision_timestamp_ns=t,
            actionable_timestamp_ns=t,
            instrument_id=1,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=60,
        )
        engine.submit_order_direct(ord2)
        engine.process_pending_orders_direct(t)

        assert len(engine._fills) == 1  # No new fill
        assert len(engine._rejected_orders) == 1
        assert "Insufficient liquidity" in engine._rejected_orders[0][1]

        # Order 3: Buy remaining 50 shares -> must fill successfully
        ord3 = OrderIntent(
            order_id="ORD-03",
            decision_timestamp_ns=t,
            actionable_timestamp_ns=t,
            instrument_id=1,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=50,
        )
        engine.submit_order_direct(ord3)
        engine.process_pending_orders_direct(t)

        assert len(engine._fills) == 2
        assert engine._fills[1].quantity == 50
        assert engine._best_ask_qty == 0

    def test_slippage_dimensional_consistency_and_safe_volume_fallback(self) -> None:
        """Verify dimensional consistency and safe handling of zero/missing volume."""
        cfg = CostModelConfig(
            fixed_slippage_per_share=0.01,
            slippage_impact_coeff=0.05,
            price_scale=100.0,
        )
        calc = TransactionCostCalculator(cfg)
        t = parse_iso_date_to_utc_ns("2024-06-01")

        # 1. Normal case with valid volume and volatility
        # Mid = $100.05, sigma = 0.02 (2%), Q = 100, V = 10,000
        # volume_ratio = sqrt(100 / 10000) = 0.1
        # impact_per_share = 0.05 * 100.05 * 0.02 * 0.1 = 0.010005 $/share
        # total slippage/share = 0.01 (fixed) + 0.010005 = 0.020005 $/share
        # slippage cost for 100 shares = 100 * 0.020005 = $2.0005
        _, slip_normal, _, _ = calc.calculate_costs(
            timestamp_ns=t,
            side=OrderSide.BUY,
            quantity=100,
            fill_price_ticks=10010,
            quote_bid_ticks=10000,
            quote_ask_ticks=10010,
            realized_volatility=0.02,
            reference_volume=10_000,
        )
        assert math.isclose(slip_normal, 2.0005, abs_tol=1e-5)

        # 2. Zero volume fallback: should not divide by zero or crash
        _, slip_zero_vol, _, _ = calc.calculate_costs(
            timestamp_ns=t,
            side=OrderSide.BUY,
            quantity=100,
            fill_price_ticks=10010,
            quote_bid_ticks=10000,
            quote_ask_ticks=10010,
            realized_volatility=0.02,
            reference_volume=0,
        )
        assert math.isfinite(slip_zero_vol)
        assert slip_zero_vol > 0.0

        # 3. None / negative volume fallback
        _, slip_neg_vol, _, _ = calc.calculate_costs(
            timestamp_ns=t,
            side=OrderSide.BUY,
            quantity=100,
            fill_price_ticks=10010,
            quote_bid_ticks=10000,
            quote_ask_ticks=10010,
            realized_volatility=0.02,
            reference_volume=-500,
        )
        assert math.isfinite(slip_neg_vol)

        # 4. Zero / non-finite volatility: impact component drops to zero
        _, slip_zero_volat, _, _ = calc.calculate_costs(
            timestamp_ns=t,
            side=OrderSide.BUY,
            quantity=100,
            fill_price_ticks=10010,
            quote_bid_ticks=10000,
            quote_ask_ticks=10010,
            realized_volatility=0.0,
            reference_volume=10_000,
        )
        # Only fixed slippage applies: 100 * $0.01 = $1.00
        assert math.isclose(slip_zero_volat, 1.00, abs_tol=1e-5)

    def test_maker_rebates_strictly_prohibited(self) -> None:
        """Verify attempting passive maker execution raises UnsupportedOrderTypeError."""
        calc = TransactionCostCalculator()
        with pytest.raises(UnsupportedOrderTypeError, match="Passive limit execution"):
            calc.calculate_costs(
                timestamp_ns=1_000_000_000,
                side=OrderSide.BUY,
                quantity=100,
                fill_price_ticks=10000,
                quote_bid_ticks=10000,
                quote_ask_ticks=10010,
                is_passive=True,
            )

    def test_regulatory_fee_cents_rounding(self) -> None:
        """Verify round_regulatory_to_cents rounds SEC and FINRA fees to whole cents."""
        cfg = CostModelConfig(
            fee_schedules=create_standard_us_equities_schedules(),
            round_regulatory_to_cents=True,
        )
        calc = TransactionCostCalculator(cfg)
        t = parse_iso_date_to_utc_ns("2024-06-01")

        # Sell 100 shares @ $50.00 = $5,000 gross principal
        # Exact SEC: 0.0000278 * $5,000 = $0.139 -> rounded to $0.14
        # Exact TAF: 0.000195 * 100 = $0.0195 -> rounded to $0.02
        # Expected rounded total = $0.16
        _, _, _, reg_fee_rounded = calc.calculate_costs(
            timestamp_ns=t,
            side=OrderSide.SELL,
            quantity=100,
            fill_price_ticks=5000,
            quote_bid_ticks=5000,
            quote_ask_ticks=5010,
        )
        assert math.isclose(reg_fee_rounded, 0.16, abs_tol=1e-5)

