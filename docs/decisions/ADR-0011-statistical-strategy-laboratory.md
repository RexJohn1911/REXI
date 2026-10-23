# ADR-0011: Statistical Strategy Laboratory and Deterministic Backtesting Engine

## Status
Accepted

## Date
2026-10-23

## Context
In quantitative trading research, strategy evaluation and backtesting are vulnerable to subtle forms of lookahead bias, unrealistic execution assumptions, and inaccurate transaction cost attribution:
1. Signal evaluation at event time $T$ often implicitly assumes orders fill instantaneously at $T$ without accounting for network propagation or matching latency.
2. Backtests frequently assume infinite liquidity at top-of-book prices, allowing large orders to execute without slippage, market impact, or partial fill constraints.
3. Transaction costs are often modeled as simple flat basis-point fees, ignoring exchange fee structures, SEC Section 31 fees, and FINRA Trading Activity Fees (TAF).
4. Regulatory fee schedules change over time (e.g., SEC Section 31 fee rate adjustments and FINRA TAF multi-year phased rate revisions), meaning a single static fee rate introduces historical distortion.
5. Backtests frequently conflate execution timestamps with settlement dates, failing to adhere to U.S. market T+1 settlement calendar rules and SEC Rule 31 charge-date definitions.

## Decisions

### 1. 5-Point Temporal Coordinate Chain
All trading events adhere strictly to a 5-point monotonically non-decreasing chain of temporal coordinates:
$$T_{\text{event}} \le T_{\text{available}} \le T_{\text{decision}} \le T_{\text{actionable}} \le T_{\text{fill}}$$
Any violation of this causality sequence triggers an explicit `TemporalOrderError`. Strategy decision logic operates strictly on data available at or before $T_{\text{decision}}$.

### 2. Deterministic Causal Execution with Displayed-Depth Consumption
Fills execute at $T_{\text{fill}} = T_{\text{actionable}} + \tau_{\text{latency}}$ against market quotes valid at $T_{\text{fill}}$. The engine enforces:
- Rejection of stale quotes exceeding maximum allowable age $\tau_{\text{stale}}$.
- Execution against available top-of-book displayed depth ($Q_{\text{bid}}$ or $Q_{\text{ask}}$).
- Configurable partial fill handling: orders exceeding available depth either execute partially up to available volume (canceling the residual) or reject immediately with `InsufficientLiquidityError`.
- Explicit rejection of unsupported order types (e.g., limit orders, stop orders) rather than silently approximating them as market orders.

### 3. Date-Aware Regulatory Fee Modeling
Regulatory fees are modeled as dated schedules reflecting official regulatory rule filings:
- **SEC Section 31**: Full historical and future fee rates, including the FY25 zero-fee interval (May 14, 2025 – April 3, 2026) and the FY26 $20.60 per million rate (April 4, 2026 onward). Assessed strictly on covered equity sales using the transaction's SEC charge date.
- **FINRA Trading Activity Fee (TAF)**: Implementation of SR-FINRA-2026-020 (Release No. 34-106410) multi-year equity fee schedule, covering the Q4 2026 fee pause ($0.00), 2027–2028 resumption ($0.000195/share, cap $9.79), 2029 tier ($0.000232/share, cap $11.61), 2030 tier ($0.000240/share, cap $12.05), and 2031+ tier ($0.000249/share, cap $12.50).
- **Date Disambiguation**: The engine evaluates dates in U.S. Eastern Time (`America/New_York`) and separates FINRA trade reporting deadlines (20:00:00 ET TRF cutoff with `.AR` as/of indicator) from contractual T+1 settlement dates (SEC Rule 15c6-1(a)) and SEC Section 31 charge dates (17 CFR § 240.31(a)(3)). Under standard clearing assumptions, post-20:00 ET executions settle on statutory T+1 from the trade date.

### 4. Integration with Phase 09 De Prado Purging
The `TargetGenerator` produces forward-looking returns and triple-barrier labels for supervised training while constructing closed `LabelInformationInterval` metadata $[t_{\text{obs}}, t_{\text{label\_end}}]$. This enables the Phase 09 `DatasetSplitter` to automatically purge overlapping observations across train/test splits.

## Consequences

### Positive
- Guarantees 100% lookahead-free backtesting and reproducible performance metrics.
- Enforces realistic liquidity constraints and prevents phantom fill execution.
- Accurately models cash flows and regulatory liabilities under U.S. equity rules.
- Fully compatible with Phase 08 Data Lake, Phase 09 No-Leakage Framework, and Phase 10 Microstructure Features.

### Negative / Trade-offs
- Currently restricted to Market Orders; resting limit orders and execution algorithms (TWAP/VWAP) are deferred to Phase 22.
- Simulates top-of-book execution only; multi-level order book sweep matching requires full L2 order book integration.
