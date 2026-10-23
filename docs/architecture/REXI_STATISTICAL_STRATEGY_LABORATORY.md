# REXI Statistical Strategy Laboratory Architecture

## 1. Executive Summary

Phase 11 establishes the canonical **Statistical Strategy Laboratory** and **Deterministic Backtesting Engine** for REXI. Operating under the quantitative research framework established in Phases 08, 09, and 10, this phase provides:
1. **Strategy Contracts and Causal Invariants** (`research/strategies/types.py`, `research/strategies/base.py`):
   - Strict 5-point temporal coordinate chain: $T_{\text{event}} \le T_{\text{available}} \le T_{\text{decision}} \le T_{\text{actionable}} \le T_{\text{fill}}$.
   - Immutable signal, order intent, fill record, and position state dataclasses with strict value-range validations.
   - Clean abstract base strategy interface `StrategyBase` and deterministic baseline benchmark `FlatBenchmarkStrategy`.
2. **Forward Target & Barrier Generation** (`research/strategies/targets.py`):
   - Mathematical target generation (fixed-horizon log returns and de Prado triple-barrier labeling).
   - Binding forward return calculations to Phase 09 `LabelInformationInterval` $[t_{\text{obs}}, t_{\text{label\_end}}]$ for de Prado label horizon purging.
   - Robust handling of non-positive prices, non-finite values, and boundary censoring.
3. **Deterministic Event-Driven Backtesting Engine** (`research/backtesting/engine.py`, `research/backtesting/exceptions.py`):
   - Strict causal execution: decisions evaluated at $T_{\text{decision}}$, fills executed at $T_{\text{fill}} \ge T_{\text{decision}}$.
   - Realistic liquidity consumption: fills consume available top-of-book displayed depth with configurable partial fill policies.
   - Rejection of stale quotes ($T_{\text{quote}} < T_{\text{decision}} - \tau_{\text{stale}}$) and crossed/locked markets.
   - Full cash ledger accounting, position tracking (flat, long, short), realized and unrealized PnL, and terminal mark-to-market liquidation.
4. **Regulatory Transaction Cost & Clearing Engine** (`research/backtesting/costs.py`):
   - Accurate modeling of half-spread, linear slippage, and temporary market impact.
   - U.S. Regulatory fee schedules:
     - **SEC Section 31**: Full historical and future effective rate schedule (including May 2025–April 2026 $0/million, April 2026+ $20.60/million), applying strictly to covered equity sell transactions.
     - **FINRA Trading Activity Fee (TAF)**: Multi-year equity schedule pursuant to SR-FINRA-2026-020 (Release No. 34-106410), including 2026 Q4 fee pause, 2027–2028 resumption at $0.000195/share (capped at $9.79), 2029 rate of $0.000232/share (capped at $11.61), 2030 rate of $0.000240/share (capped at $12.05), and 2031+ rate of $0.000249/share (capped at $12.50).
     - **Date Convention Separation**: Rigorous separation of Eastern calendar execution date, FINRA 20:00:00 ET TRF reporting cutoff (`is_as_of_reporting`), statutory T+1 settlement date (SEC Rule 15c6-1(a)), and SEC Section 31 charge date (17 CFR § 240.31(a)(3)).

---

## 2. Temporal Coordinate Chain & Causal Invariants

To eliminate lookahead bias and execution drift, REXI models event progression across five discrete timestamps:

```
T_event                     T_available                 T_decision                  T_actionable                T_fill
  |                             |                           |                           |                          |
  +-----------------------------+---------------------------+---------------------------+--------------------------+
      Feed & Market Arrival        Feature Calculation          Strategy Alpha Signal      Order Transmission Delay     Exchange Matching
```

1. **$T_{\text{event}}$ (Venue Event Time)**: Physical nanosecond timestamp when the market quote or trade occurred at the exchange matching engine.
2. **$T_{\text{available}}$ (Data Ingestion / Feature Time)**: Point in time when market data arrived over the network and features were computed ($T_{\text{available}} \ge T_{\text{event}}$).
3. **$T_{\text{decision}}$ (Alpha Computation Time)**: Point in time when strategy logic evaluates features and generates a `Signal` ($T_{\text{decision}} \ge T_{\text{available}}$).
4. **$T_{\text{actionable}}$ (Order Transmission Time)**: Point in time when an `OrderIntent` leaves the trading engine after local routing and pre-trade risk checks ($T_{\text{actionable}} \ge T_{\text{decision}}$).
5. **$T_{\text{fill}}$ (Execution Time)**: Point in time when the order arrives at the matching venue and generates a `FillRecord` ($T_{\text{fill}} \ge T_{\text{actionable}}$).

Any event, signal, or order violating this non-decreasing monotonic sequence ($T_1 \le T_2 \le T_3 \le T_4 \le T_5$) is rejected with `TemporalOrderError`.

---

## 3. Forward Target Generation & De Prado Purging Integration

Supervised alpha models and machine learning pipelines require forward-looking labels during training, but backtest signals must never observe them. The `TargetGenerator` produces forward targets while constructing explicit Phase 09 `LabelInformationInterval` metadata:

### Fixed-Horizon Forward Returns
For a specified forward horizon $\Delta t$, forward return is computed as:
$$r_{t, \Delta t} = \ln\left(\frac{P_{t + \Delta t}}{P_t}\right)$$
The label information interval is defined as the closed interval:
$$I_{\text{label}} = [t_{\text{obs}}, t_{\text{obs}} + \Delta t]$$
Any sample whose $I_{\text{label}}$ overlaps a test evaluation partition in cross-validation is purged by the Phase 09 `DatasetSplitter`.

### Triple-Barrier Target Labeling
Following Marcos López de Prado (2018), paths are monitored over a maximum forward window $[t_{\text{obs}}, t_{\text{obs}} + \Delta t_{\max}]$ against upper and lower profit-taking/stop-loss barriers:
- **Upper Barrier Touch**: Return $\ge +u$ at $t_{\text{touch}} \le t_{\text{obs}} + \Delta t_{\max} \implies \text{label} = +1, I_{\text{label}} = [t_{\text{obs}}, t_{\text{touch}}]$.
- **Lower Barrier Touch**: Return $\le -l$ at $t_{\text{touch}} \le t_{\text{obs}} + \Delta t_{\max} \implies \text{label} = -1, I_{\text{label}} = [t_{\text{obs}}, t_{\text{touch}}]$.
- **Vertical Barrier (Timeout)**: No barrier touched before $t_{\text{obs}} + \Delta t_{\max} \implies \text{label} = \operatorname{sign}(r_{\text{terminal}}), I_{\text{label}} = [t_{\text{obs}}, t_{\text{obs}} + \Delta t_{\max}]$.

---

## 4. Deterministic Backtesting Engine Architecture

The `DeterministicBacktestEngine` provides an event-driven simulation loop operating over time-series data:

```
+---------------------------------------------------------------------------------+
|                        Deterministic Backtesting Pipeline                       |
+---------------------------------------------------------------------------------+
                                         |
                                         v
+---------------------------------------------------------------------------------+
|                      Event Sequence & Quote Cache                               |
|   - Time-ordered processing of QuoteEvent records                               |
|   - Rejection of backward time jumps and non-finite quotes                      |
|   - Detection of crossed/locked books (bid >= ask)                              |
+---------------------------------------------------------------------------------+
                                         |
                                         v
+---------------------------------------------------------------------------------+
|                      Strategy Signal Generation (T_decision)                    |
|   - Strategy receives immutable quote snapshot at T_decision                    |
|   - Evaluates alpha logic and returns Signal(direction, target_weight)          |
|   - Signal validation: direction in {-1, 0, 1}, weight in [0, 1]                |
+---------------------------------------------------------------------------------+
                                         |
                                         v
+---------------------------------------------------------------------------------+
|                      Order Sizing & Risk Routing (T_actionable)                 |
|   - Converts target portfolio weight to target share quantity                   |
|   - Computes delta shares required relative to current position                 |
|   - Emits OrderIntent(order_type, side, quantity, T_actionable)                 |
+---------------------------------------------------------------------------------+
                                         |
                                         v
+---------------------------------------------------------------------------------+
|                      Causal Execution & Fill Engine (T_fill)                    |
|   - Execution latency: T_fill = T_actionable + latency_ns                       |
|   - Fetches quote valid at T_fill: rejects if stale (T_fill - T_quote > max)    |
|   - Liquidity check: fills against displayed depth (partial fill if requested)  |
|   - Execution price: ask + slippage (buys), bid - slippage (sells)              |
+---------------------------------------------------------------------------------+
                                         |
                                         v
+---------------------------------------------------------------------------------+
|                      Transaction Cost & Regulatory Accounting                   |
|   - Venue fee / rebate (per share)                                              |
|   - Linear market impact model                                                  |
|   - SEC Section 31 fee (sell orders, settlement/charge date lookup)             |
|   - FINRA TAF (sell orders, trade date lookup)                                  |
|   - Cash balance and position state updates                                     |
+---------------------------------------------------------------------------------+
```

### Liquidity & Depth Model
Orders execute against displayed top-of-book quotes:
- **Buy Orders**: Match against `best_ask_price` up to `best_ask_qty`.
- **Sell Orders**: Match against `best_bid_price` up to `best_bid_qty`.
- **Partial Fill Policy**: If requested quantity exceeds displayed depth:
  - If `allow_partial_fills=True`: Executes up to available depth; remaining quantity is canceled.
  - If `allow_partial_fills=False`: Order is rejected with `InsufficientLiquidityError`.

---

## 5. Transaction Costs and Regulatory Rules

### Cost Component Attribution
Total transaction cost per fill is decomposed into distinct accounting categories:
1. **Half-Spread Cost**: Explicitly captured by executing at the ask (for buys) or bid (for sells) relative to the prevailing midpoint.
2. **Slippage**: Deterministic model $\Delta P_{\text{slip}} = c_{\text{slip}} \times P$.
3. **Market Impact**: Stylized linear model $I = \eta \times \left(\frac{Q}{Q_{\text{book}}}\right) \times P$.
4. **Exchange / Venue Fees**: Fee per share $f_{\text{venue}}$ or rebate.
5. **Regulatory Fees**:
   - **SEC Section 31**: Assessed on all covered equity sales. Effective fee rate is retrieved using the transaction's SEC charge date.
   - **FINRA Trading Activity Fee (TAF)**: Assessed on covered equity sales per share, subject to statutory per-trade caps. Effective fee rate is retrieved using the transaction's trade date.

### Regulatory Date & Timezone Conventions
All regulatory date lookups evaluate timestamps under U.S. Eastern Time (`America/New_York`):
- **FINRA Trade Reporting Cutoff**: FINRA Rules 6380A and 6380B mandate that trades executed between 08:00:00 and 20:00:00 ET be reported within 10 seconds. Trades executed after 20:00:00 ET must be reported on the next business day by 08:15:00 ET with an `.AR` (as/of) modifier.
- **Settlement Separation**: Crucially, FINRA's 8:00 p.m. trade-reporting cutoff alters report timing and as/of status, but does **not** modify contractual settlement under SEC Rule 15c6-1(a) (statutory T+1). Trades executed at 19:59:59 ET, 20:00:00 ET, and 20:30:00 ET on Thursday, December 30, 2027 all have a regulatory trade date of December 30, 2027 and settle on Monday, January 3, 2028 (since Friday, December 31, 2027 is an observed New Year's Day settlement holiday).
- **SEC Rule 31 Charge Date**: Under 17 CFR § 240.31(a)(3), for covered sales reported through a designated clearing agency (NSCC/DTCC), the charge date is the settlement date.
