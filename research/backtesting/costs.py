"""Dated transaction cost models, fee schedules, and friction accounting for U.S. Equities.

COST SEPARATION & NO-DOUBLE-COUNTING MANDATE:
1. Spread Cost: Explicitly reflects the economic cost of crossing the prevailing bid-ask spread
   from the prevailing mid-price to the quoted touch:
     Spread Cost = (P_touch - P_mid) * Quantity / Price_Scale
   It represents execution distance from the mid-price benchmark and must NEVER be
   double-counted by subtracting it from cash when trades execute at touch prices.
2. Slippage & Market Impact: Represents adverse execution price drift beyond the quoted
   touch, parameterized by fixed per-share slippage and a dimensionally consistent
   square-root research approximation:
     impact_per_share = eta * P_mid * sigma * sqrt(Q / V)
   NOTE: This is a configurable research approximation, NOT an empirically calibrated model.
3. Exchange Taker Fees: Venue tariff charged per share for liquidity-removing orders.
   NOTE: Exchange tariffs vary by venue and tier. Default rates are illustrative configurable
   assumptions based on the Reg NMS Rule 610(c) 30 mil/share lit access fee cap.
4. Regulatory Fees (U.S. Equities): Statutory fees levied strictly on covered sales:
   - SEC Section 31: Rate * Gross Sale Principal (historically verified via SEC Fee Advisories).
   - FINRA Trading Activity Fee (TAF): Per-share sold, subject to statutory floor and cap
     (historically verified via FINRA Regulatory Notice 12-40).
   - Buys are strictly exempt from SEC Section 31 and FINRA TAF.
"""

import math
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

from research.backtesting.exceptions import (
    BacktestConfigurationError,
    UnsupportedOrderTypeError,
)
from research.strategies.types import OrderSide

US_EASTERN_TZ: ZoneInfo = ZoneInfo("America/New_York")


def timestamp_ns_to_eastern_date(timestamp_ns: int) -> date:
    """Convert a UTC nanosecond timestamp to the corresponding U.S. Eastern calendar date.

    Uses America/New_York to correctly account for both Eastern Standard Time (EST, UTC-5)
    and Eastern Daylight Time (EDT, UTC-4), including daylight-saving transitions and
    after-hours trading sessions (which fall on the current Eastern calendar date even
    when extending past 00:00:00 UTC midnight).
    """
    if timestamp_ns < 0:
        raise BacktestConfigurationError(
            f"timestamp_ns must be non-negative, got {timestamp_ns}"
        )
    sec = timestamp_ns // 1_000_000_000
    return datetime.fromtimestamp(sec, tz=US_EASTERN_TZ).date()


def parse_iso_date_to_eastern_ns(date_str: str) -> int:
    """Parse an ISO date string (YYYY-MM-DD) to midnight Eastern Time in UTC nanoseconds."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=US_EASTERN_TZ)
        return int(dt.timestamp()) * 1_000_000_000
    except Exception as e:
        raise BacktestConfigurationError(f"Invalid date format '{date_str}': {e}") from e


class SecChargeDateRule(str, Enum):
    """Charge date determination rule under SEC Rule 31 (17 CFR § 240.31(a)(3)).

    Primary Regulatory Sources:
    - 17 CFR § 240.31(a)(3) [SEC Rule 31(a)(3)]
    - SEC Release No. 34-49928 (69 FR 41060, June 28, 2004)

    Categories:
    - CLEARING_SETTLEMENT_DATE: For covered sales reported using data received from
      a designated clearing agency (NSCC/DTCC) pursuant to 17 CFR § 240.31(a)(3)(i).
      The charge date is the settlement date (T+2 business days prior to May 28, 2024,
      and T+1 business day on and after May 28, 2024 per amended SEC Rule 15c6-1(a)).
      This represents standard institutional and retail broker-dealer equity transactions.
    - TRADE_DATE: For covered sales reported using data received other than from a
      designated clearing agency pursuant to 17 CFR § 240.31(a)(3)(ii).
      The charge date is the trade execution date (fill timestamp).
    """

    CLEARING_SETTLEMENT_DATE = "clearing_settlement_date"
    TRADE_DATE = "trade_date"


@dataclass(frozen=True)
class TradeDateResolution:
    """Distinct date conventions for an execution timestamp under U.S. regulatory rules.

    Distinguishes:
    1. execution_eastern_date: Calendar date in America/New_York (00:00:00 to 23:59:59.999 ET)
       when the trade execution fill occurred.
    2. finra_regulatory_trade_date: Regulatory trade date under FINRA Rules 6380A/6380B.
       For executions occurring on calendar date D, the trade date is date D.
    3. finra_reporting_date: Business date when the trade report must be submitted to the TRF.
       Same day for executions during facility hours (08:00 to 20:00 ET on business days);
       next business day by 08:15 ET for executions outside facility hours (>= 20:00 ET,
       weekends, or clearing holidays).
    4. is_as_of_reporting: Boolean indicating whether the trade took place outside TRF
       operating hours, requiring 'as/of' trade reporting under Rule 6380A(a)(2)(D).
    5. effective_clearing_date: The first clearing business day on or after execution.
       For executions on a business day, this is the trade date itself; for executions on
       weekends or clearing holidays, this rolls to the next business day.
    6. settlement_date: Statutory settlement date under SEC Rule 15c6-1(a) (17 CFR § 240.15c6-1(a)).
       Standard T+1 business day from the trade date on/after May 28, 2024 (T+2 prior).
       The FINRA 20:00 ET trade reporting cutoff does NOT alter the statutory settlement date.
    7. sec_charge_date: Applicable charge date under 17 CFR § 240.31(a)(3) (settlement date for
       clearing agency reported sales; trade date for non-clearing direct reporting).
    """

    execution_eastern_date: date
    finra_regulatory_trade_date: date
    finra_reporting_date: date
    is_as_of_reporting: bool
    effective_clearing_date: date
    settlement_date: date
    sec_charge_date: date


def compute_easter_sunday(year: int) -> date:
    """Compute Easter Sunday using the anonymous Gregorian algorithm (Meeus/Jones/Butcher)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observe_fixed_holiday(d: date) -> date:
    """Apply standard U.S. federal/clearing weekend holiday observation rules.

    - Sunday holidays are observed on the following Monday.
    - Saturday holidays are observed on the preceding Friday.
    """
    if d.weekday() == 5:  # Saturday -> Friday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday -> Monday
        return d + timedelta(days=1)
    return d


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """Return the nth occurrence of a weekday (0=Mon...6=Sun) in a given year and month."""
    d = date(year, month, 1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d + timedelta(weeks=n - 1)


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """Return the last occurrence of a weekday (0=Mon...6=Sun) in a given year and month."""
    if month == 12:
        d = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def get_us_settlement_holidays_for_year(year: int) -> set[date]:
    """Compute official U.S. equity settlement holidays for a given year.

    Observed by DTC/NSCC and the Federal Reserve Bank (non-settlement days):
    1. New Year's Day (Jan 1; observed Mon if Sun; observed Fri Dec 31 if Sat)
    2. Martin Luther King Jr. Day (3rd Monday in January)
    3. Washington's Birthday / Presidents' Day (3rd Monday in February)
    4. Good Friday (Friday before Easter Sunday)
    5. Memorial Day (last Monday in May)
    6. Juneteenth National Independence Day (June 19; observed if weekend)
    7. Independence Day (July 4; observed if weekend)
    8. Labor Day (1st Monday in September)
    9. Columbus Day / Indigenous Peoples' Day (2nd Monday in October; Fedwire closed)
    10. Veterans Day (Nov 11; observed if weekend; Fedwire closed)
    11. Thanksgiving Day (4th Thursday in November)
    12. Christmas Day (Dec 25; observed if weekend)
    """
    holidays: set[date] = set()

    # 1. New Year's Day
    ny = date(year, 1, 1)
    if ny.weekday() == 6:
        holidays.add(date(year, 1, 2))
    elif ny.weekday() != 5:
        holidays.add(ny)
    else:
        holidays.add(date(year - 1, 12, 31))

    # Also check if following year's Jan 1 falls on Saturday (observed Dec 31 of this year)
    if date(year + 1, 1, 1).weekday() == 5:
        holidays.add(date(year, 12, 31))

    # 2. Martin Luther King Jr. Day (3rd Monday in January)
    holidays.add(_nth_weekday_of_month(year, 1, 0, 3))

    # 3. Washington's Birthday / Presidents' Day (3rd Monday in February)
    holidays.add(_nth_weekday_of_month(year, 2, 0, 3))

    # 4. Good Friday (Friday before Easter Sunday)
    easter = compute_easter_sunday(year)
    holidays.add(easter - timedelta(days=2))

    # 5. Memorial Day (last Monday in May)
    holidays.add(_last_weekday_of_month(year, 5, 0))

    # 6. Juneteenth National Independence Day (June 19)
    holidays.add(_observe_fixed_holiday(date(year, 6, 19)))

    # 7. Independence Day (July 4)
    holidays.add(_observe_fixed_holiday(date(year, 7, 4)))

    # 8. Labor Day (1st Monday in September)
    holidays.add(_nth_weekday_of_month(year, 9, 0, 1))

    # 9. Columbus Day / Indigenous Peoples' Day (2nd Monday in October; Fedwire closed)
    holidays.add(_nth_weekday_of_month(year, 10, 0, 2))

    # 10. Veterans Day (November 11; Fedwire closed)
    holidays.add(_observe_fixed_holiday(date(year, 11, 11)))

    # 11. Thanksgiving Day (4th Thursday in November)
    holidays.add(_nth_weekday_of_month(year, 11, 3, 4))

    # 12. Christmas Day (December 25)
    holidays.add(_observe_fixed_holiday(date(year, 12, 25)))

    return holidays


VERIFIED_SETTLEMENT_CALENDAR_START_YEAR = 2024
VERIFIED_SETTLEMENT_CALENDAR_END_YEAR = 2032

US_SETTLEMENT_HOLIDAYS_2024_2032: frozenset[date] = frozenset(
    h
    for y in range(
        VERIFIED_SETTLEMENT_CALENDAR_START_YEAR,
        VERIFIED_SETTLEMENT_CALENDAR_END_YEAR + 1,
    )
    for h in get_us_settlement_holidays_for_year(y)
)
# Backward-compatible alias for previous 2024-2029 definition
US_SETTLEMENT_HOLIDAYS_2024_2029: frozenset[date] = US_SETTLEMENT_HOLIDAYS_2024_2032


def resolve_trade_and_settlement_dates(
    trade_timestamp_ns: int,
    sec_charge_date_rule: SecChargeDateRule | str = SecChargeDateRule.CLEARING_SETTLEMENT_DATE,
    settlement_days: int | None = None,
    settlement_holidays: set[date] | frozenset[date] | None = None,
) -> TradeDateResolution:
    """Resolve an execution timestamp into distinct regulatory, reporting, and settlement dates.

    Regulatory & Settlement Structure:
    1. Execution Eastern Date:
       Calendar date in America/New_York (00:00:00 to 23:59:59.999999999 ET) when fill occurred.
    2. FINRA Regulatory Trade Date (FINRA Rules 6380A/6380B):
       - For executions occurring on calendar date D, the contractual trade date is date D.
    3. FINRA Report Submission Deadline & As/Of Modifier:
       - TRF facility operating hours are 08:00 to 20:00 ET on business days.
       - Executions between 08:00:00 and 19:59:59.999 ET are reported same day (within 10 seconds).
       - Executions at or after 20:00:00 ET (20:00 to midnight), or on weekends and holidays,
         occur when the facility is closed. Under Rules 6380A(a)(2)(B)/(D) and 6380B(a)(2)(B)/(D),
         these trades must be reported to the TRF on the next business day (T+1) by 08:15 ET
         on an 'as/of' basis with an outside-normal-market-hours modifier.
       - NOTE: The 'as/of' reporting deadline is a transaction reporting rule for trade
         dissemination; it does NOT alter the contractual trade date or statutory settlement date.
    4. Effective Clearing Date:
       - For executions on a business day, clearing begins on the trade date itself.
       - For executions on non-business days (weekends or clearing holidays), clearing begins
         on the next clearing business day.
    5. Statutory Settlement Date (SEC Rule 15c6-1(a), 17 CFR § 240.15c6-1(a)):
       - T+1 business day on and after May 28, 2024 (SEC Release No. 34-96930; T+2 prior).
       - Computed from the effective clearing date by adding standard settlement business days.
       - An execution at 20:00:00 ET or later on a business day has the same trade date and
         the same statutory settlement date as an execution earlier on that same business day.
    6. SEC Section 31 Charge Date (17 CFR § 240.31(a)(3)):
       - For CLEARING_SETTLEMENT_DATE (§ 240.31(a)(3)(i)), charge date is the settlement date.
       - For TRADE_DATE (§ 240.31(a)(3)(ii)), charge date is the trade execution date.

    Model Scope & Limitations:
    - REXI models standard statutory T+1 settlement under 17 CFR § 240.15c6-1(a).
    - REXI does NOT infer an extra settlement day from FINRA's 20:00 ET reporting cutoff.
    - Proprietary clearing broker cutoffs or overnight ATS trading session date assignments
      (e.g., assigning a next-business-day trade date for 24-hour retail sessions) are venue-
      specific commercial practices, not statutory mandates; REXI does not claim full
      venue-specific clearing fidelity beyond standard statutory settlement.
    """
    if trade_timestamp_ns < 0:
        raise BacktestConfigurationError(
            f"trade_timestamp_ns must be non-negative, got {trade_timestamp_ns}"
        )

    sec = trade_timestamp_ns // 1_000_000_000
    dt_eastern = datetime.fromtimestamp(sec, tz=US_EASTERN_TZ)
    execution_date = dt_eastern.date()

    if settlement_holidays is not None:
        holidays = settlement_holidays
    else:
        if not (
            VERIFIED_SETTLEMENT_CALENDAR_START_YEAR
            <= execution_date.year
            <= VERIFIED_SETTLEMENT_CALENDAR_END_YEAR
        ):
            raise BacktestConfigurationError(
                f"Trade date {execution_date} is outside the verified U.S. settlement holiday "
                f"calendar period ({VERIFIED_SETTLEMENT_CALENDAR_START_YEAR}-"
                f"{VERIFIED_SETTLEMENT_CALENDAR_END_YEAR}). An explicit settlement timestamp or "
                f"custom settlement_holidays must be provided."
            )
        holidays = US_SETTLEMENT_HOLIDAYS_2024_2032

    # Determine facility hours & as/of reporting status
    is_weekend = dt_eastern.weekday() >= 5
    is_holiday = execution_date in holidays
    is_after_8pm = dt_eastern.hour >= 20
    is_outside_facility_hours = is_weekend or is_holiday or is_after_8pm

    finra_trade_date = execution_date

    if is_outside_facility_hours:
        is_as_of = True
        # Determine next business day for reporting
        curr_rep = execution_date + timedelta(
            days=1 if is_after_8pm or is_weekend or is_holiday else 0
        )
        while curr_rep.weekday() >= 5 or curr_rep in holidays:
            curr_rep += timedelta(days=1)
        finra_rep_date = curr_rep
    else:
        is_as_of = False
        finra_rep_date = execution_date

    # Determine effective clearing date:
    # On a business day, clearing begins on the trade date itself (execution_date).
    # On non-business days (weekends or clearing holidays), clearing rolls to next business day.
    curr_clr = execution_date
    while curr_clr.weekday() >= 5 or curr_clr in holidays:
        curr_clr += timedelta(days=1)
    effective_clearing_date = curr_clr

    # Determine statutory settlement cycle days
    if settlement_days is None:
        days_to_add = 2 if execution_date < date(2024, 5, 28) else 1
    else:
        if settlement_days < 0:
            raise BacktestConfigurationError(
                f"settlement_days must be non-negative, got {settlement_days}"
            )
        days_to_add = settlement_days

    # Add settlement business days
    curr_stl = effective_clearing_date
    added = 0
    while added < days_to_add:
        curr_stl += timedelta(days=1)
        if curr_stl.weekday() < 5 and curr_stl not in holidays:
            added += 1
    settlement_date = curr_stl

    # Resolve SEC charge date
    rule_str = (
        sec_charge_date_rule.value
        if isinstance(sec_charge_date_rule, SecChargeDateRule)
        else str(sec_charge_date_rule).lower()
    )
    if rule_str in ("clearing_settlement_date", "settlement_date"):
        sec_charge_date = settlement_date
    elif rule_str == "trade_date":
        sec_charge_date = finra_trade_date
    else:
        raise BacktestConfigurationError(
            f"Unsupported sec_charge_date_rule: {sec_charge_date_rule}"
        )

    return TradeDateResolution(
        execution_eastern_date=execution_date,
        finra_regulatory_trade_date=finra_trade_date,
        finra_reporting_date=finra_rep_date,
        is_as_of_reporting=is_as_of,
        effective_clearing_date=effective_clearing_date,
        settlement_date=settlement_date,
        sec_charge_date=sec_charge_date,
    )


def calculate_settlement_timestamp_ns(
    trade_timestamp_ns: int,
    settlement_days: int | None = None,
    settlement_holidays: set[date] | frozenset[date] | None = None,
) -> int:
    """Calculate the settlement timestamp corresponding to a trade execution timestamp.

    Statutory Settlement Cycles & Timezone Semantics:
    - Timezone Convention: Evaluated using U.S. Eastern Time (America/New_York) to derive
      the statutory trade date and settlement dates.
    - Statutory Cycles:
      - Prior to 2024-05-28: Standard T+2 business days (17 CFR § 240.15c6-1(a)).
      - On and after 2024-05-28: Standard T+1 business day (SEC Release No. 34-96930;
        amended 17 CFR § 240.15c6-1(a)).
    - Non-settlement days include weekends and official U.S. clearing holidays
      (DTC/NSCC and Federal Reserve closures).
    - FINRA Trade Reporting Separation: Executions occurring at or after 20:00:00 ET on a
      business day have the same contractual trade date and standard statutory settlement
      date under SEC Rule 15c6-1(a) as earlier executions on that date. The 20:00 ET TRF
      reporting cutoff governs only trade report submission deadlines to the TRF ('as/of'
      reporting by 08:15 ET next business day) and does NOT add an extra settlement day.
    """
    res = resolve_trade_and_settlement_dates(
        trade_timestamp_ns=trade_timestamp_ns,
        settlement_days=settlement_days,
        settlement_holidays=settlement_holidays,
    )

    sec = trade_timestamp_ns // 1_000_000_000
    nsec_rem = trade_timestamp_ns % 1_000_000_000
    dt_eastern = datetime.fromtimestamp(sec, tz=US_EASTERN_TZ)

    settlement_dt_eastern = datetime(
        res.settlement_date.year,
        res.settlement_date.month,
        res.settlement_date.day,
        dt_eastern.hour,
        dt_eastern.minute,
        dt_eastern.second,
        dt_eastern.microsecond,
        tzinfo=US_EASTERN_TZ,
    )
    settlement_sec = int(settlement_dt_eastern.astimezone(UTC).timestamp())
    return settlement_sec * 1_000_000_000 + nsec_rem


@dataclass(frozen=True)
class DatedFeeSchedule:
    """Effective-dated fee schedule for U.S. equities transaction accounting.

    Attributes:
    - effective_start_date_str: ISO-8601 date string (e.g. '2024-05-22').
    - effective_start_timestamp_ns: Nanoseconds since UNIX epoch when schedule becomes active.
    - effective_end_date_str: ISO-8601 date string for schedule expiry (empty if open-ended).
    - effective_end_timestamp_ns: Nanoseconds since UNIX epoch when schedule expires (or None).
    - sec_section_31_rate: SEC Section 31 transaction fee rate per dollar of covered sales.
      (Authoritative: SEC Fee Advisories pursuant to Section 31 of Securities Exchange Act).
    - finra_taf_rate_per_share: FINRA Trading Activity Fee per share sold.
      (Authoritative: FINRA By-Laws Schedule A, Section 1(b); SR-FINRA-2026-020,
       SEC Release No. 34-106410; SR-FINRA-2026-021, SEC Release No. 34-106409).
    - finra_taf_max_per_trade: Statutory maximum FINRA TAF per sell execution ($9.79 cap
      through 2028; $11.61 cap beginning Jan 1, 2029).
    - finra_taf_min_per_trade: Statutory minimum charge per trade (default 0.0 for equities;
      FINRA Schedule A does NOT assess a minimum cash charge for equities; only security
      futures carry a statutory $0.014 minimum).
    - taker_fee_per_share: Venue fee charged per share for liquidity-removing orders.
      (Illustrative configurable assumption based on Reg NMS Rule 610(c) 30 mil lit cap).
    - maker_rebate_per_share: Venue rebate paid per share for liquidity-adding orders.
      (Inactive in Stage 2 market-order-only engine; maker rebates are strictly prohibited).
    - source_reference: Public regulatory filing or bulletin citation.

    SEC Section 31 Charge Date vs. FINRA TAF Date Legal Conventions:
    - SEC Section 31 (17 CFR § 240.31(a)(3); SEC Release No. 34-49928):
      The SEC statutory definition of "charge date" explicitly distinguishes transaction
      categories:
      (i) Under 17 CFR § 240.31(a)(3)(i), for covered sales of equity securities reported
          pursuant to § 240.31a-1 using data received from a designated clearing agency
          (NSCC/DTCC), the charge date is the SETTLEMENT DATE.
          Settlement is T+2 business days prior to May 28, 2024, and T+1 business day on and
          after May 28, 2024 (17 CFR § 240.15c6-1(a); SEC Release No. 34-96930).
          This represents standard exchange-traded and OTC equity transactions clearing via DTCC.
      (ii) Under 17 CFR § 240.31(a)(3)(ii), for covered sales reported using data received
          other than from a designated clearing agency, the charge date is the TRADE DATE.
    - FINRA Trading Activity Fee (FINRA By-Laws Schedule A, Section 1(b)):
      FINRA assesses TAF based strictly on trade execution date (Transaction Date / Trade Date),
      independent of SEC Rule 31 charge date definitions.
    - Fee Schedules and Rate Resolution:
      The backtesting engine models separate fee-date semantics: SEC Section 31 is resolved
      at the applicable SEC charge date (governed by SecChargeDateRule), while FINRA TAF and
      exchange tariffs are resolved at the trade execution timestamp.
    """

    effective_start_date_str: str
    effective_start_timestamp_ns: int
    sec_section_31_rate: float
    effective_end_date_str: str = ""
    effective_end_timestamp_ns: int | None = None
    finra_taf_rate_per_share: float = 0.000195
    finra_taf_max_per_trade: float = 9.79
    finra_taf_min_per_trade: float = 0.0
    taker_fee_per_share: float = 0.0030
    maker_rebate_per_share: float = 0.0
    source_reference: str = ""

    def __post_init__(self) -> None:
        if self.effective_start_timestamp_ns < 0:
            raise BacktestConfigurationError("effective_start_timestamp_ns must be non-negative.")
        if (
            self.effective_end_timestamp_ns is not None
            and self.effective_end_timestamp_ns <= self.effective_start_timestamp_ns
        ):
            raise BacktestConfigurationError(
                f"effective_end_timestamp_ns ({self.effective_end_timestamp_ns}) must be "
                f"greater than start ({self.effective_start_timestamp_ns})"
            )
        rates = [
            ("sec_section_31_rate", self.sec_section_31_rate),
            ("finra_taf_rate_per_share", self.finra_taf_rate_per_share),
            ("finra_taf_max_per_trade", self.finra_taf_max_per_trade),
            ("finra_taf_min_per_trade", self.finra_taf_min_per_trade),
            ("taker_fee_per_share", self.taker_fee_per_share),
            ("maker_rebate_per_share", self.maker_rebate_per_share),
        ]
        for name, r in rates:
            if not isinstance(r, int | float) or isinstance(r, bool) or not math.isfinite(r):
                raise BacktestConfigurationError(f"{name} must be a finite float, got {r}")
            if r < 0.0:
                raise BacktestConfigurationError(f"{name} cannot be negative, got {r}")

        if self.finra_taf_min_per_trade > self.finra_taf_max_per_trade:
            raise BacktestConfigurationError(
                f"FINRA TAF min ({self.finra_taf_min_per_trade}) cannot exceed "
                f"max ({self.finra_taf_max_per_trade})"
            )


def parse_iso_date_to_utc_ns(date_str: str) -> int:
    """Parse an ISO date string (YYYY-MM-DD) to midnight UTC nanoseconds."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        return int(dt.timestamp()) * 1_000_000_000 + dt.microsecond * 1_000
    except Exception as e:
        raise BacktestConfigurationError(f"Invalid date format '{date_str}': {e}") from e


def create_standard_us_equities_schedules() -> list[DatedFeeSchedule]:
    """Create verified historical U.S. Equities regulatory fee schedules.

    Authoritative Regulatory Sources & Verified Transitions:
    1. 2024-01-01 through 2024-05-21:
       - SEC Section 31: $8.00 per million ($0.0000080) (SEC Release No. 34-97097).
       - FINRA TAF: $0.000195/share, cap $9.79 (SR-FINRA-2026-020, SEC Release No. 34-106410).
    2. 2024-05-22 through 2025-05-13:
       - SEC Section 31: $27.80 per million ($0.0000278) (SEC Release No. 34-100006).
       - FINRA TAF: $0.000195/share, cap $9.79.
    3. 2025-05-14 through 2026-04-03:
       - SEC Section 31: $0.00 per million ($0.0000000) (SEC Fee Rate Advisory for FY 2025;
         statutory collection target achieved early).
       - FINRA TAF: $0.000195/share, cap $9.79.
    4. 2026-04-04 through 2026-09-30:
       - SEC Section 31: $20.60 per million ($0.0000206) (SEC Fee Rate Advisory for FY 2026;
         enactment of regular FY 2026 appropriation).
       - FINRA TAF: $0.000195/share, cap $9.79.
    5. 2026-10-01 through 2026-12-31:
       - SEC Section 31: $20.60 per million ($0.0000206).
       - FINRA TAF: $0.00/share, cap $0.00 (SR-FINRA-2026-021, SEC Release No. 34-106409;
         temporary fee pause).
    6. 2027-01-01 through 2028-12-31:
       - SEC Section 31: $20.60 per million ($0.0000206).
       - FINRA TAF: $0.000195/share, cap $9.79 (SR-FINRA-2026-020, SEC Release No. 34-106410;
         automatic resumption at baseline rate).
    7. 2029-01-01 through 2029-12-31:
       - SEC Section 31: $20.60 per million ($0.0000206).
       - FINRA TAF: $0.000232/share, cap $11.61 (SR-FINRA-2026-020, SEC Release No. 34-106410;
         step-up year 1 postponed from 2027 to 2029).
    8. 2030-01-01 through 2030-12-31:
       - SEC Section 31: $20.60 per million ($0.0000206).
       - FINRA TAF: $0.000240/share, cap $12.05 (SR-FINRA-2026-020, SEC Release No. 34-106410;
         step-up year 2).
    9. 2031-01-01 onward:
       - SEC Section 31: $20.60 per million ($0.0000206).
       - FINRA TAF: $0.000249/share, cap $12.50 (SR-FINRA-2026-020, SEC Release No. 34-106410;
         final step-up year 3 onward).

    Venue Fee Assumptions:
    - taker_fee_per_share: Set to $0.0030/share as an illustrative baseline matching the
      statutory Reg NMS Rule 610(c) access fee cap (30 mils) for continuous lit exchanges.
      This is an illustrative configurable assumption, NOT a universal broker or venue fee.
    - maker_rebate_per_share: Set to 0.0 (passive orders/rebates disabled in Stage 2).
    """
    ts_2024_01_01 = parse_iso_date_to_eastern_ns("2024-01-01")
    ts_2024_05_22 = parse_iso_date_to_eastern_ns("2024-05-22")
    ts_2025_05_14 = parse_iso_date_to_eastern_ns("2025-05-14")
    ts_2026_04_04 = parse_iso_date_to_eastern_ns("2026-04-04")
    ts_2026_10_01 = parse_iso_date_to_eastern_ns("2026-10-01")
    ts_2027_01_01 = parse_iso_date_to_eastern_ns("2027-01-01")
    ts_2029_01_01 = parse_iso_date_to_eastern_ns("2029-01-01")
    ts_2030_01_01 = parse_iso_date_to_eastern_ns("2030-01-01")
    ts_2031_01_01 = parse_iso_date_to_eastern_ns("2031-01-01")

    return [
        DatedFeeSchedule(
            effective_start_date_str="2024-01-01",
            effective_start_timestamp_ns=ts_2024_01_01,
            effective_end_date_str="2024-05-22",
            effective_end_timestamp_ns=ts_2024_05_22,
            sec_section_31_rate=0.0000080,  # $8.00 per million
            finra_taf_rate_per_share=0.000195,
            finra_taf_max_per_trade=9.79,
            finra_taf_min_per_trade=0.0,
            taker_fee_per_share=0.0030,
            maker_rebate_per_share=0.0,
            source_reference="SEC Release No. 34-97097; SR-FINRA-2026-020 (Rel. 34-106410)",
        ),
        DatedFeeSchedule(
            effective_start_date_str="2024-05-22",
            effective_start_timestamp_ns=ts_2024_05_22,
            effective_end_date_str="2025-05-14",
            effective_end_timestamp_ns=ts_2025_05_14,
            sec_section_31_rate=0.0000278,  # $27.80 per million
            finra_taf_rate_per_share=0.000195,
            finra_taf_max_per_trade=9.79,
            finra_taf_min_per_trade=0.0,
            taker_fee_per_share=0.0030,
            maker_rebate_per_share=0.0,
            source_reference="SEC Release No. 34-100006; SR-FINRA-2026-020 (Rel. 34-106410)",
        ),
        DatedFeeSchedule(
            effective_start_date_str="2025-05-14",
            effective_start_timestamp_ns=ts_2025_05_14,
            effective_end_date_str="2026-04-04",
            effective_end_timestamp_ns=ts_2026_04_04,
            sec_section_31_rate=0.0,  # $0.00 per million (statutory target achieved)
            finra_taf_rate_per_share=0.000195,
            finra_taf_max_per_trade=9.79,
            finra_taf_min_per_trade=0.0,
            taker_fee_per_share=0.0030,
            maker_rebate_per_share=0.0,
            source_reference=(
                "SEC Fee Rate Advisory for FY 2025; SR-FINRA-2026-020 (Rel. 34-106410)"
            ),
        ),
        DatedFeeSchedule(
            effective_start_date_str="2026-04-04",
            effective_start_timestamp_ns=ts_2026_04_04,
            effective_end_date_str="2026-10-01",
            effective_end_timestamp_ns=ts_2026_10_01,
            sec_section_31_rate=0.0000206,  # $20.60 per million
            finra_taf_rate_per_share=0.000195,
            finra_taf_max_per_trade=9.79,
            finra_taf_min_per_trade=0.0,
            taker_fee_per_share=0.0030,
            maker_rebate_per_share=0.0,
            source_reference=(
                "SEC Fee Rate Advisory for FY 2026; SR-FINRA-2026-020 (Rel. 34-106410)"
            ),
        ),
        DatedFeeSchedule(
            effective_start_date_str="2026-10-01",
            effective_start_timestamp_ns=ts_2026_10_01,
            effective_end_date_str="2027-01-01",
            effective_end_timestamp_ns=ts_2027_01_01,
            sec_section_31_rate=0.0000206,  # $20.60 per million
            finra_taf_rate_per_share=0.0,  # FINRA temporary pause ($0.00 rate)
            finra_taf_max_per_trade=0.0,
            finra_taf_min_per_trade=0.0,
            taker_fee_per_share=0.0030,
            maker_rebate_per_share=0.0,
            source_reference=(
                "SEC Fee Rate Advisory for FY 2026; SR-FINRA-2026-021 (Rel. 34-106409)"
            ),
        ),
        DatedFeeSchedule(
            effective_start_date_str="2027-01-01",
            effective_start_timestamp_ns=ts_2027_01_01,
            effective_end_date_str="2029-01-01",
            effective_end_timestamp_ns=ts_2029_01_01,
            sec_section_31_rate=0.0000206,  # $20.60 per million
            finra_taf_rate_per_share=0.000195,  # Baseline resumption through 2028
            finra_taf_max_per_trade=9.79,
            finra_taf_min_per_trade=0.0,
            taker_fee_per_share=0.0030,
            maker_rebate_per_share=0.0,
            source_reference=(
                "SEC Fee Rate Advisory for FY 2026; SR-FINRA-2026-020 (Rel. 34-106410)"
            ),
        ),
        DatedFeeSchedule(
            effective_start_date_str="2029-01-01",
            effective_start_timestamp_ns=ts_2029_01_01,
            effective_end_date_str="2030-01-01",
            effective_end_timestamp_ns=ts_2030_01_01,
            sec_section_31_rate=0.0000206,  # $20.60 per million
            finra_taf_rate_per_share=0.000232,  # Step-up year 1 (SR-FINRA-2026-020)
            finra_taf_max_per_trade=11.61,
            finra_taf_min_per_trade=0.0,
            taker_fee_per_share=0.0030,
            maker_rebate_per_share=0.0,
            source_reference=(
                "SEC Fee Rate Advisory for FY 2026; SR-FINRA-2026-020 (Rel. 34-106410)"
            ),
        ),
        DatedFeeSchedule(
            effective_start_date_str="2030-01-01",
            effective_start_timestamp_ns=ts_2030_01_01,
            effective_end_date_str="2031-01-01",
            effective_end_timestamp_ns=ts_2031_01_01,
            sec_section_31_rate=0.0000206,  # $20.60 per million
            finra_taf_rate_per_share=0.000240,  # Step-up year 2 (SR-FINRA-2026-020)
            finra_taf_max_per_trade=12.05,
            finra_taf_min_per_trade=0.0,
            taker_fee_per_share=0.0030,
            maker_rebate_per_share=0.0,
            source_reference=(
                "SEC Fee Rate Advisory for FY 2026; SR-FINRA-2026-020 (Rel. 34-106410)"
            ),
        ),
        DatedFeeSchedule(
            effective_start_date_str="2031-01-01",
            effective_start_timestamp_ns=ts_2031_01_01,
            effective_end_date_str="",
            effective_end_timestamp_ns=None,
            sec_section_31_rate=0.0000206,  # $20.60 per million
            finra_taf_rate_per_share=0.000249,  # Step-up year 3 onward (SR-FINRA-2026-020)
            finra_taf_max_per_trade=12.50,
            finra_taf_min_per_trade=0.0,
            taker_fee_per_share=0.0030,
            maker_rebate_per_share=0.0,
            source_reference=(
                "SEC Fee Rate Advisory for FY 2026; SR-FINRA-2026-020 (Rel. 34-106410)"
            ),
        ),
    ]


@dataclass(frozen=True)
class CostModelConfig:
    """Configuration for transaction friction and execution cost calculations.

    Model Assumptions and Transaction Categories:
    - sec_charge_date_rule: Modeled reporting category under SEC Rule 31 (17 CFR § 240.31(a)(3)).
      Defaults to SecChargeDateRule.CLEARING_SETTLEMENT_DATE, representing standard broker-dealer
      trades reported through NSCC clearing data where the charge date is the settlement date.
      Can be set to SecChargeDateRule.TRADE_DATE for non-clearing direct reporting categories.
    - settlement_days: Optional integer specifying explicit business days to settlement.
      If None, automatically determines T+2 prior to May 28, 2024, and T+1 on/after May 28, 2024
      pursuant to SEC Rule 15c6-1(a).
    - settlement_holidays: Optional custom set of dates recognized as non-settlement days.
      If None, uses the verified U.S. equity clearing holiday calendar (2024-2032).
    - round_regulatory_to_cents: Modeled broker-dealer billing convention.
      Defaults to False (raw statutory calculation without per-trade cent rounding).
      Under 17 CFR § 240.31 and FINRA Schedule A, statutory SRO assessments are aggregate,
      without a statutory per-trade cent rounding mandate. Per-trade cent rounding is an
      optional commercial broker billing simulation.
    """

    fee_schedules: list[DatedFeeSchedule] = field(
        default_factory=create_standard_us_equities_schedules
    )
    fixed_slippage_per_share: float = 0.0
    slippage_impact_coeff: float = 0.0
    price_scale: float = 100.0  # Default: 100 ticks per dollar (cents)
    sec_charge_date_rule: SecChargeDateRule | str = SecChargeDateRule.CLEARING_SETTLEMENT_DATE
    settlement_days: int | None = None
    settlement_holidays: frozenset[date] | set[date] | None = None
    round_regulatory_to_cents: bool = False
    strict_schedule_coverage: bool = False

    def __post_init__(self) -> None:
        if len(self.fee_schedules) == 0:
            raise BacktestConfigurationError("At least one DatedFeeSchedule must be provided.")
        if self.price_scale <= 0.0 or not math.isfinite(self.price_scale):
            raise BacktestConfigurationError(
                f"price_scale must be positive, got {self.price_scale}"
            )
        if self.fixed_slippage_per_share < 0.0:
            raise BacktestConfigurationError("fixed_slippage_per_share cannot be negative.")
        if self.slippage_impact_coeff < 0.0:
            raise BacktestConfigurationError("slippage_impact_coeff cannot be negative.")

        if isinstance(self.sec_charge_date_rule, str):
            val = self.sec_charge_date_rule.lower()
            if val in ("settlement_date", "clearing_settlement_date"):
                object.__setattr__(
                    self, "sec_charge_date_rule", SecChargeDateRule.CLEARING_SETTLEMENT_DATE
                )
            elif val == "trade_date":
                object.__setattr__(self, "sec_charge_date_rule", SecChargeDateRule.TRADE_DATE)
            else:
                raise BacktestConfigurationError(
                    f"Invalid sec_charge_date_rule '{self.sec_charge_date_rule}'. "
                    f"Must be one of {[r.value for r in SecChargeDateRule]}"
                )
        elif not isinstance(self.sec_charge_date_rule, SecChargeDateRule):
            raise BacktestConfigurationError(
                f"sec_charge_date_rule must be a SecChargeDateRule or string, "
                f"got {type(self.sec_charge_date_rule)}"
            )

        if self.settlement_days is not None:
            if not isinstance(self.settlement_days, int) or isinstance(self.settlement_days, bool):
                raise BacktestConfigurationError(
                    f"settlement_days must be an integer, got {self.settlement_days}"
                )
            if self.settlement_days < 0:
                raise BacktestConfigurationError(
                    f"settlement_days cannot be negative, got {self.settlement_days}"
                )

        # Ensure schedules are sorted strictly by effective_start_timestamp_ns
        prev_ts = -1
        for s in self.fee_schedules:
            if s.effective_start_timestamp_ns <= prev_ts:
                raise BacktestConfigurationError(
                    "fee_schedules must be strictly ordered by effective_start_timestamp_ns."
                )
            prev_ts = s.effective_start_timestamp_ns

    def get_fee_schedule(self, timestamp_ns: int) -> DatedFeeSchedule:
        """Find the active fee schedule for a given event timestamp."""
        earliest_start = self.fee_schedules[0].effective_start_timestamp_ns
        if timestamp_ns < earliest_start:
            if self.strict_schedule_coverage:
                raise BacktestConfigurationError(
                    f"Timestamp {timestamp_ns} precedes earliest verified schedule "
                    f"({self.fee_schedules[0].effective_start_date_str})."
                )
            return self.fee_schedules[0]

        ts_list = [s.effective_start_timestamp_ns for s in self.fee_schedules]
        idx = bisect_right(ts_list, timestamp_ns) - 1
        return self.fee_schedules[idx]

    def get_fee_schedule_for_date(self, calendar_date: date) -> DatedFeeSchedule:
        """Find the active fee schedule for a given calendar date in America/New_York.

        Resolves to the fee schedule active at 12:00:00 (noon) Eastern Time on that date.
        """
        dt_eastern = datetime(
            calendar_date.year,
            calendar_date.month,
            calendar_date.day,
            12,
            0,
            0,
            tzinfo=US_EASTERN_TZ,
        )
        ts_ns = int(dt_eastern.astimezone(UTC).timestamp()) * 1_000_000_000
        return self.get_fee_schedule(ts_ns)


class TransactionCostCalculator:
    """Deterministic transaction cost calculation engine preventing double-counting."""

    def __init__(self, config: CostModelConfig | None = None) -> None:
        self.config = config or CostModelConfig()

    def calculate_costs(
        self,
        timestamp_ns: int,
        side: OrderSide,
        quantity: int,
        fill_price_ticks: int,
        quote_bid_ticks: int,
        quote_ask_ticks: int,
        is_passive: bool = False,
        realized_volatility: float = 0.0,
        reference_volume: int | float | None = None,
        settlement_timestamp_ns: int | None = None,
    ) -> tuple[float, float, float, float]:
        """Compute the 4 separate friction components for an executed trade fill.

        Units and Dimensions:
        - quantity: shares (Q > 0 integer).
        - fill_price_ticks, quote_bid_ticks, quote_ask_ticks: integer price in ticks.
        - price_scale: ticks per currency unit (e.g. 100 ticks = $1.00).
        - realized_volatility: dimensionless fractional return standard deviation (sigma >= 0).
        - reference_volume: shares (displayed top depth or bar volume V > 0).
        - settlement_timestamp_ns: optional explicit settlement timestamp for SEC charge date
          determination under 17 CFR § 240.31(a)(3)(i). If None, computed automatically based
          on statutory T+2/T+1 settlement rules and U.S. clearing holidays.

        Returns:
        (spread_cost, slippage_cost, exchange_fee, regulatory_fee) in currency units (dollars).
        """
        if quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {quantity}")
        if fill_price_ticks <= 0:
            raise ValueError(f"fill_price_ticks must be positive, got {fill_price_ticks}")
        if quote_bid_ticks <= 0 or quote_ask_ticks <= 0:
            raise ValueError("Quotes must be positive")
        if quote_bid_ticks > quote_ask_ticks:
            raise ValueError(
                f"Crossed quote: bid ({quote_bid_ticks}) > ask ({quote_ask_ticks})"
            )
        if is_passive:
            raise UnsupportedOrderTypeError(
                "Passive limit execution and maker rebates are disabled in this "
                "market-order backtesting engine."
            )

        # Trade execution schedule applies to execution-time venue tariffs (taker fees)
        # and FINRA TAF
        trade_schedule = self.config.get_fee_schedule(timestamp_ns)
        price_scale = self.config.price_scale

        # 1. Spread Cost
        # Mid price in dollars
        mid_ticks = (quote_bid_ticks + quote_ask_ticks) / 2.0
        if side == OrderSide.BUY:
            # Paid ask relative to mid
            touch_ticks = float(quote_ask_ticks)
            spread_ticks_paid = touch_ticks - mid_ticks
        else:
            # Received bid relative to mid
            touch_ticks = float(quote_bid_ticks)
            spread_ticks_paid = mid_ticks - touch_ticks

        spread_cost_dollars = max(0.0, (spread_ticks_paid / price_scale) * quantity)

        # 2. Slippage & Market Impact (beyond the quoted touch)
        # Fixed per-share component (dollars / share)
        slippage_per_share = self.config.fixed_slippage_per_share

        # Configurable research approximation (Kyle / Almgren-Chriss inspired square-root impact)
        # impact_per_share = eta * mid_dollars * sigma * sqrt(Q / V)
        # Dimension: [1] * [$] * [1] * sqrt([shares] / [shares]) = [$ / share]
        if (
            self.config.slippage_impact_coeff > 0.0
            and realized_volatility > 0.0
            and math.isfinite(realized_volatility)
        ):
            mid_dollars = mid_ticks / price_scale
            # Safely handle missing, non-positive, or non-finite reference volume
            if (
                reference_volume is not None
                and isinstance(reference_volume, int | float)
                and math.isfinite(reference_volume)
                and reference_volume > 0
            ):
                volume_ratio = math.sqrt(quantity / reference_volume)
            else:
                # Safe fallback if volume is unavailable or zero: ratio is bounded at 1.0
                volume_ratio = 1.0

            impact_per_share = (
                self.config.slippage_impact_coeff * mid_dollars * realized_volatility * volume_ratio
            )
            slippage_per_share += impact_per_share

        slippage_cost_dollars = slippage_per_share * quantity

        # 3. Exchange Taker Fee (Taker execution only)
        exchange_fee_dollars = trade_schedule.taker_fee_per_share * quantity

        # 4. Regulatory Fees (U.S. Equities: Sells Only)
        # Authoritative Statutory Rules & Fee Date Separation:
        # - SEC Section 31 (17 CFR § 240.31(a)(3); SEC Release No. 34-49928):
        #   Charge date depends on transaction category: settlement date for clearing agency
        #   reported sales (§ 240.31(a)(3)(i)); trade date for non-clearing sales
        #   (§ 240.31(a)(3)(ii)).
        # - FINRA Trading Activity Fee (FINRA By-Laws Schedule A, Section 1(b)):
        #   Assessed strictly based on trade execution date (Transaction Date / Trade Date),
        #   independent of SEC Rule 31 charge date definitions.
        regulatory_fee_dollars = 0.0
        if side == OrderSide.SELL:
            gross_principal_dollars = (fill_price_ticks * quantity) / price_scale

            # Resolve applicable SEC Section 31 charge date timestamp
            if self.config.sec_charge_date_rule == SecChargeDateRule.CLEARING_SETTLEMENT_DATE:
                sec_charge_ts = (
                    settlement_timestamp_ns
                    if settlement_timestamp_ns is not None
                    else calculate_settlement_timestamp_ns(
                        timestamp_ns,
                        settlement_days=self.config.settlement_days,
                        settlement_holidays=self.config.settlement_holidays,
                    )
                )
            elif self.config.sec_charge_date_rule == SecChargeDateRule.TRADE_DATE:
                sec_charge_ts = timestamp_ns
            else:
                raise BacktestConfigurationError(
                    f"Unsupported sec_charge_date_rule: {self.config.sec_charge_date_rule}"
                )

            # 1. SEC Section 31 Fee: evaluated at SEC charge date
            sec_schedule = self.config.get_fee_schedule(sec_charge_ts)
            sec_fee = sec_schedule.sec_section_31_rate * gross_principal_dollars

            # 2. FINRA Trading Activity Fee (TAF): evaluated at Trade Execution Date
            # Primary Source: FINRA By-Laws Schedule A, Section 1(b); SR-FINRA-2026-020
            # Under FINRA Schedule A, Section 1(b)(1), covered equity transactions with an
            # execution price below the TAF rate ($0.000195) are exempt (no fee assessed).
            # The statutory maximum cap is $9.79 per trade through 2028, and $11.61 per trade
            # beginning Jan 1, 2029. There is NO statutory minimum charge ($0.00 floor)
            # for equity securities (only security futures have a $0.014 min).
            share_price_dollars = fill_price_ticks / price_scale
            if (
                trade_schedule.finra_taf_rate_per_share <= 0.0
                or share_price_dollars < trade_schedule.finra_taf_rate_per_share
            ):
                finra_taf = 0.0
            else:
                raw_taf = trade_schedule.finra_taf_rate_per_share * quantity
                if trade_schedule.finra_taf_min_per_trade > 0.0:
                    raw_taf = max(raw_taf, trade_schedule.finra_taf_min_per_trade)
                finra_taf = min(raw_taf, trade_schedule.finra_taf_max_per_trade)

            if self.config.round_regulatory_to_cents:
                # Modeled broker/customer confirmation rounding to nearest cent.
                # (Broker-dealer billing convention; not a statutory Rule 31 / Schedule A rule).
                sec_fee = round(sec_fee, 2)
                finra_taf = round(finra_taf, 2)

            regulatory_fee_dollars = sec_fee + finra_taf

        return (
            spread_cost_dollars,
            slippage_cost_dollars,
            exchange_fee_dollars,
            regulatory_fee_dollars,
        )

