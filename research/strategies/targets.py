"""Target construction and holding-period semantics with Phase 09 purging integration.

LEAKAGE SAFETY MANDATE:
Targets computed by this module represent FUTURE outcomes (labels). They are strictly
intended for:
1. Model training label construction (supervised learning).
2. Out-of-sample statistical evaluation.
3. Defining closed holding-period LabelInformationIntervals for de Prado purging.

Under no circumstances may ForwardTarget or BarrierEvent fields (forward_price,
return_value, exit_price, exit_timestamp_ns) be exposed to a strategy's decision logic
at or before observation_timestamp_ns.
"""

import math
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass

import pyarrow as pa

from research.leakage.types import LabelInformationInterval


@dataclass(frozen=True)
class ForwardTarget:
    """Fixed-horizon forward return target paired with a closed LabelInformationInterval.

    Represents the future return realized over [t_obs, t_obs + horizon_ns].
    """

    observation_timestamp_ns: int
    horizon_ns: int
    forward_timestamp_ns: int
    current_price: float
    forward_price: float
    log_return: float
    arithmetic_return: float
    is_valid: bool
    label_interval: LabelInformationInterval


@dataclass(frozen=True)
class BarrierEvent:
    """Triple-barrier event (upper barrier, lower barrier, or vertical time barrier).

    Represents the outcome of a trade initiated at observation_timestamp_ns.
    """

    observation_timestamp_ns: int
    exit_timestamp_ns: int
    current_price: float
    exit_price: float
    return_value: float
    hit_upper: bool
    hit_lower: bool
    hit_vertical: bool
    is_valid: bool
    label_interval: LabelInformationInterval


class TargetGenerator:
    """Deterministic forward return and triple-barrier target constructor."""

    @staticmethod
    def compute_fixed_horizon_targets(
        timestamps: Sequence[int],
        prices: Sequence[float | int],
        horizon_ns: int,
    ) -> list[ForwardTarget]:
        """Compute fixed-horizon forward returns with closed LabelInformationIntervals.

        For each observation at t_obs:
        Target forward price is the price at the first observation t >= t_obs + horizon_ns.
        If t_obs + horizon_ns exceeds the last timestamp or prices are non-finite/non-positive,
        the target is marked is_valid = False and returns are set to NaN (DEC-0053).
        """
        n = len(timestamps)
        if n != len(prices):
            raise ValueError(f"Length mismatch: {n} timestamps vs {len(prices)} prices.")
        if horizon_ns <= 0:
            raise ValueError(f"horizon_ns must be positive, got {horizon_ns}")

        targets: list[ForwardTarget] = []
        last_ts = timestamps[-1] if n > 0 else 0

        for i in range(n):
            t_obs = timestamps[i]
            p_curr = float(prices[i])
            t_target = t_obs + horizon_ns

            if t_target > last_ts:
                # Horizon extends beyond dataset boundary: invalid forward target
                targets.append(
                    ForwardTarget(
                        observation_timestamp_ns=t_obs,
                        horizon_ns=horizon_ns,
                        forward_timestamp_ns=t_target,
                        current_price=p_curr,
                        forward_price=float("nan"),
                        log_return=float("nan"),
                        arithmetic_return=float("nan"),
                        is_valid=False,
                        label_interval=LabelInformationInterval(t_obs, t_target),
                    )
                )
                continue

            # Find first index with timestamp >= t_target
            fwd_idx = bisect_left(timestamps, t_target)
            if fwd_idx >= n:
                fwd_idx = n - 1

            p_fwd = float(prices[fwd_idx])
            t_fwd_actual = timestamps[fwd_idx]

            if (
                not math.isfinite(p_curr)
                or not math.isfinite(p_fwd)
                or p_curr <= 0.0
                or p_fwd <= 0.0
            ):
                is_valid = False
                log_ret = float("nan")
                arith_ret = float("nan")
                p_fwd_val = float("nan")
            else:
                is_valid = True
                log_ret = math.log(p_fwd / p_curr)
                arith_ret = (p_fwd - p_curr) / p_curr
                p_fwd_val = p_fwd

            targets.append(
                ForwardTarget(
                    observation_timestamp_ns=t_obs,
                    horizon_ns=horizon_ns,
                    forward_timestamp_ns=t_fwd_actual,
                    current_price=p_curr,
                    forward_price=p_fwd_val,
                    log_return=log_ret,
                    arithmetic_return=arith_ret,
                    is_valid=is_valid,
                    label_interval=LabelInformationInterval(t_obs, t_fwd_actual),
                )
            )

        return targets

    @staticmethod
    def compute_triple_barrier_targets(
        timestamps: Sequence[int],
        prices: Sequence[float | int],
        upper_threshold: float,
        lower_threshold: float,
        max_holding_ns: int,
    ) -> list[BarrierEvent]:
        """Compute de Prado triple-barrier outcomes with closed LabelInformationIntervals.

        Barriers:
        1. Upper barrier: return >= upper_threshold (Take Profit)
        2. Lower barrier: return <= -lower_threshold (Stop Loss)
        3. Vertical barrier: elapsed time >= max_holding_ns (Time Expiry)

        Tie & Precedence Semantics:
        - If t_curr < t_vert, horizontal barriers (take-profit/stop-loss) take precedence.
        - If t_curr >= t_vert, vertical time expiry barrier takes precedence (position is
          closed at t_vert).
        - If dataset boundary is reached before any barrier is triggered, the event is
          censored / incomplete: is_valid = False and return_value = NaN.

        Parameters:
        - upper_threshold: Positive relative return threshold (e.g. 0.0020 for 20 bps)
        - lower_threshold: Positive relative return threshold (e.g. 0.0010 for 10 bps loss)
        - max_holding_ns: Maximum holding duration in nanoseconds
        """
        n = len(timestamps)
        if n != len(prices):
            raise ValueError(f"Length mismatch: {n} timestamps vs {len(prices)} prices.")
        if upper_threshold <= 0.0 or not math.isfinite(upper_threshold):
            raise ValueError(f"upper_threshold must be positive and finite, got {upper_threshold}")
        if lower_threshold <= 0.0 or not math.isfinite(lower_threshold):
            raise ValueError(f"lower_threshold must be positive and finite, got {lower_threshold}")
        if max_holding_ns <= 0:
            raise ValueError(f"max_holding_ns must be positive, got {max_holding_ns}")

        events: list[BarrierEvent] = []

        for i in range(n):
            t_obs = timestamps[i]
            p_entry = float(prices[i])

            if not math.isfinite(p_entry) or p_entry <= 0.0:
                raise ValueError(f"Non-positive or non-finite price {p_entry} at index {i}")

            t_vert = t_obs + max_holding_ns
            hit_upper = False
            hit_lower = False
            hit_vertical = False
            is_valid = True
            exit_ts = t_obs
            exit_p = p_entry
            ret_val = 0.0

            # Scan forward through time
            for j in range(i + 1, n):
                t_curr = timestamps[j]
                p_curr = float(prices[j])

                if not math.isfinite(p_curr) or p_curr <= 0.0:
                    raise ValueError(f"Non-positive or non-finite price {p_curr} at index {j}")

                # Check vertical barrier first: if expired, position closed at current market
                if t_curr >= t_vert:
                    hit_vertical = True
                    exit_ts = t_curr
                    exit_p = p_curr
                    ret_val = (p_curr - p_entry) / p_entry
                    break

                # Calculate cumulative relative return from entry
                curr_ret = (p_curr - p_entry) / p_entry

                if curr_ret >= upper_threshold:
                    hit_upper = True
                    exit_ts = t_curr
                    exit_p = p_curr
                    ret_val = curr_ret
                    break
                elif curr_ret <= -lower_threshold:
                    hit_lower = True
                    exit_ts = t_curr
                    exit_p = p_curr
                    ret_val = curr_ret
                    break

            if not (hit_upper or hit_lower or hit_vertical):
                # Series ended before touching any barrier: censored / incomplete episode
                exit_ts = timestamps[-1]
                exit_p = float(prices[-1])
                ret_val = float("nan")
                is_valid = False

            events.append(
                BarrierEvent(
                    observation_timestamp_ns=t_obs,
                    exit_timestamp_ns=exit_ts,
                    current_price=p_entry,
                    exit_price=exit_p,
                    return_value=ret_val,
                    hit_upper=hit_upper,
                    hit_lower=hit_lower,
                    hit_vertical=hit_vertical,
                    is_valid=is_valid,
                    label_interval=LabelInformationInterval(t_obs, exit_ts),
                )
            )

        return events

    @staticmethod
    def enrich_with_forward_returns(
        table: pa.Table,
        horizon_ns: int,
        price_col: str = "mid_price",
        ts_col: str = "decision_timestamp_ns",
    ) -> pa.Table:
        """Enrich a PyArrow table with forward return columns and validity flags."""
        if len(table) == 0:
            empty_ret = pa.array([], type=pa.float64())
            empty_bool = pa.array([], type=pa.bool_())
            return (
                table.append_column("forward_return", empty_ret)
                .append_column("forward_log_return", empty_ret)
                .append_column("has_forward_target", empty_bool)
            )

        ts = table[ts_col].to_pylist()
        prices = table[price_col].to_pylist()

        targets = TargetGenerator.compute_fixed_horizon_targets(
            timestamps=ts,
            prices=prices,
            horizon_ns=horizon_ns,
        )

        fwd_returns = [t.arithmetic_return for t in targets]
        fwd_log_returns = [t.log_return for t in targets]
        has_targets = [t.is_valid for t in targets]

        return (
            table.append_column("forward_return", pa.array(fwd_returns, type=pa.float64()))
            .append_column("forward_log_return", pa.array(fwd_log_returns, type=pa.float64()))
            .append_column("has_forward_target", pa.array(has_targets, type=pa.bool_()))
        )
