# REXI Microstructure Feature Engine Architecture

## 1. Executive Summary

Phase 10 establishes the canonical **Microstructure Feature Engine** for REXI, realizing the two-world paradigm:
1. **C++ Hot-Path Streaming Engine** (`core/include/rexi/microstructure/`): Zero steady-state heap allocations, sub-50-nanosecond update latency, deterministic streaming calculations, strict temporal causality gating, and zero network dependencies.
2. **Python Research Feature Engine & Pipeline** (`research/features/`): Point-in-time causal dataset processing, full integration with Phase 08 Data Lake datasets, PyArrow schema enforcement (`MICROSTRUCTURE_FEATURES_SCHEMA_V1`), and verified zero lookahead bias via Phase 09 `LookaheadDetector` and `PointInTimeAligner`.

---

## 2. Core Architecture & Pipeline

```
+-----------------------------------------------------------------------------------+
|                        Inbound Market Data Event Stream                           |
|       (TopOfBookMessage, TradeMessage, OrderBookDepthSnapshot, Replay Stream)     |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                     Temporal Order & Monotonicity Verification                    |
|    - Monotonic event timestamp enforcement: T_event[i] >= T_event[i-1]            |
|    - Explicit handling and drop counters for out-of-order events                  |
|    - Availability timestamp assignment: T_avail = max(T_event, T_source)          |
|    - Decision availability invariant: T_avail <= T_decision                       |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                      Microstructure Feature Engine Core                           |
|  +-----------------------------------------------------------------------------+  |
|  | Level 1 Top of Book (BBO):                                                  |  |
|  | - Best bid/ask price and quantity                                           |  |
|  | - Spread = P_ask - P_bid; Relative Spread = Spread / P_mid                  |  |
|  | - Mid-price = (P_bid + P_ask) / 2.0; Micro-price / Weighted Mid              |  |
|  | - Top-of-book depth imbalance = (Q_bid - Q_ask) / (Q_bid + Q_ask)          |  |
|  | - Crossed/locked book detection: is_crossed = (P_bid >= P_ask)              |  |
|  +-----------------------------------------------------------------------------+  |
|  | Level 2 Multi-Level Aggregated Depth (Top K Levels):                        |  |
|  | - Aggregated bid/ask depth over top K levels (K=5 default)                  |  |
|  | - Depth imbalance = (Bid_Depth - Ask_Depth) / (Bid_Depth + Ask_Depth)       |  |
|  +-----------------------------------------------------------------------------+  |
|  | Order Flow Imbalance (OFI - Cont, Kukanov & Stoikov 2014):                   |  |
|  | - Instantaneous OFI delta based on quote price & quantity transitions       |  |
|  | - Rolling OFI sum over fixed circular ring buffer window                    |  |
|  +-----------------------------------------------------------------------------+  |
|  | Trade Flow Dynamics & Rolling VWAP:                                         |  |
|  | - Signed volume = +Q (buy aggressor) / -Q (sell aggressor)                 |  |
|  | - Rolling trade, buy, and sell volume; Trade flow imbalance                 |  |
|  | - Rolling Volume-Weighted Average Price (VWAP) = Sum(P * Q) / Sum(Q)        |  |
|  +-----------------------------------------------------------------------------+  |
|  | Short-Horizon Returns & Realized Volatility:                                |  |
|  | - Mid-price log returns: ln(P_mid,t / P_mid,t-k)                            |  |
|  | - Rolling sample realized volatility: sqrt(Sum(r - r_bar)^2 / (N - 1))      |  |
|  +-----------------------------------------------------------------------------+  |
|  | Advanced Microstructure Models:                                             |  |
|  | - Roll (1984) effective spread: 2 * sqrt(-Cov(Delta P_t, Delta P_t-1))      |  |
|  | - Easley et al. (2012) VPIN: Volume-Synchronized Probability of Toxicity    |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                      Explicit Availability & Gating Semantics                     |
|  - Every feature gated by boolean validity flag (has_bid, has_spread, etc.)       |
|  - Missing data, crossed books, and insufficient warm-up NEVER defaulted to 0.0   |
|  - Invalid prices, empty books, and positive Roll autocovariances gated False     |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|               Phase 08 / Phase 09 Research Lake & Leakage Integration             |
|  - PyArrow MICROSTRUCTURE_FEATURES_SCHEMA_V1 export                               |
|  - Phase 09 LookaheadDetector causal validation (audit_point_in_time)             |
|  - PointInTimeAligner causal as-of alignment for point-in-time model inputs       |
+-----------------------------------------------------------------------------------+
```

---

## 3. Mathematical Feature Definitions & Semantics

### 3.1 Top of Book (Level 1)
- **Inputs**: Best bid price $P_B$, best bid quantity $Q_B$, best ask price $P_A$, best ask quantity $Q_A$.
- **Gating**:
  - `has_bid`: $P_B > 0 \land Q_B > 0$.
  - `has_ask`: $P_A > 0 \land Q_A > 0$.
  - `is_crossed`: `has_bid` $\land$ `has_ask` $\land (P_B \ge P_A)$.
- **Spread & Relative Spread**:
  $$\text{Spread} = P_A - P_B \quad (\text{integer tick units})$$
  $$\text{Relative Spread} = \frac{\text{Spread}}{P_{\text{mid}}}$$
  Gated by `has_spread = has_bid && has_ask && !is_crossed`.
- **Mid-Price & Micro-Price (Weighted Mid)**:
  $$P_{\text{mid}} = \frac{P_B + P_A}{2.0}$$
  $$P_{\text{micro}} = \frac{P_B \cdot Q_A + P_A \cdot Q_B}{Q_B + Q_A}$$
  Gated by `has_mid` and `has_weighted_mid = (Q_B + Q_A > 0) && !is_crossed`.
- **Top-of-Book Depth Imbalance**:
  $$I_{\text{top}} = \frac{Q_B - Q_A}{Q_B + Q_A} \in [-1.0, 1.0]$$
  Gated by `has_book_imbalance = (Q_B + Q_A > 0) && !is_crossed`.

### 3.2 Multi-Level Aggregated Depth (Level 2)
- Over top $K$ order book levels:
  $$\text{BidDepth}_K = \sum_{i=1}^K Q_{B,i}, \quad \text{AskDepth}_K = \sum_{i=1}^K Q_{A,i}$$
  $$I_{\text{depth}, K} = \frac{\text{BidDepth}_K - \text{AskDepth}_K}{\text{BidDepth}_K + \text{AskDepth}_K}$$
  Gated by `has_depth_imbalance = (BidDepth_K + AskDepth_K > 0) && !is_crossed`.

### 3.3 Order Flow Imbalance (OFI)
- Reference: Cont, Kukanov & Stoikov (2014):
  $$\Delta W_{B,t} = \begin{cases} Q_{B,t} & \text{if } P_{B,t} > P_{B,t-1} \\ Q_{B,t} - Q_{B,t-1} & \text{if } P_{B,t} = P_{B,t-1} \\ -Q_{B,t-1} & \text{if } P_{B,t} < P_{B,t-1} \end{cases}$$
  $$\Delta W_{A,t} = \begin{cases} -Q_{A,t} & \text{if } P_{A,t} < P_{A,t-1} \\ -(Q_{A,t} - Q_{A,t-1}) & \text{if } P_{A,t} = P_{A,t-1} \\ Q_{A,t-1} & \text{if } P_{A,t} > P_{A,t-1} \end{cases}$$
  $$\text{OFI}_t = \Delta W_{B,t} + \Delta W_{A,t}$$
- `rolling_ofi`: Sum of instantaneous OFI over rolling circular window $N_{\text{OFI}}$.
  Gated by `has_rolling_ofi = (count >= N_OFI)`.

### 3.4 Trade Flow Dynamics & Rolling VWAP
- `last_signed_volume`: $+Q$ for buyer-initiated aggressor, $-Q$ for seller-initiated aggressor.
- Over rolling trade window of size $N_{\text{trade}}$:
  $$\text{TFI} = \frac{\sum_{\text{buy}} Q_i - \sum_{\text{sell}} Q_i}{\sum Q_i} \in [-1.0, 1.0]$$
  $$\text{VWAP} = \frac{\sum P_i \cdot Q_i}{\sum Q_i}$$
  Gated by `has_trade_flow = (count >= N_trade)` and `has_vwap = (tot_vol > 0)`.

### 3.5 Short-Horizon Returns & Realized Volatility
- Log return:
  $$r_t = \ln\left(\frac{P_{\text{mid}, t}}{P_{\text{mid}, t - k}}\right)$$
- Sample realized volatility over rolling window of size $N_{\text{vol}}$:
  $$\sigma = \sqrt{\frac{1}{N_{\text{vol}} - 1} \sum_{j=1}^{N_{\text{vol}}} (r_j - \bar{r})^2}$$
  Gated by `has_realized_volatility = (count >= N_vol)`.

### 3.6 Roll (1984) Effective Spread
- For consecutive transaction price changes $\Delta P_t = P_t - P_{t-1}$:
  $$\gamma_1 = \text{Cov}(\Delta P_t, \Delta P_{t-1}) = \frac{1}{N - 1} \sum_{i=1}^{N-1} (\Delta P_{i+1} - \overline{\Delta P})(\Delta P_i - \overline{\Delta P})$$
  $$\text{Roll Spread} = \begin{cases} 2 \sqrt{-\gamma_1} & \text{if } \gamma_1 < 0 \\ \text{undefined} & \text{if } \gamma_1 \ge 0 \end{cases}$$
  When $\gamma_1 \ge 0$, Roll's model is violated and `has_roll_spread = false`.

### 3.7 Volume-Synchronized Probability of Toxicity (VPIN)
- Reference: Easley, Lopez de Prado & O'Hara (2012):
  Trades fill discrete buckets of constant volume $V$. Trades spanning boundaries are deterministically split across buckets.
  For $M$ completed buckets:
  $$\text{VPIN} = \frac{\sum_{\tau=1}^M |V_\tau^B - V_\tau^S|}{M \cdot V} \in [0.0, 1.0]$$
  Gated by `has_vpin = (completed_buckets >= M)`.

---

## 4. Performance & Memory Profile

- **Zero steady-state heap allocations**: Fixed-capacity ring buffers (`FixedRingBuffer<T, N>`) allocate zero memory on hot-path updates.
- **Latency Benchmarks**:
  - `BM_Microstructure_TopOfBookUpdate`: 15.9 ns.
  - `BM_Microstructure_TradeUpdate`: 33.5 ns.
  - `BM_Microstructure_OrderBookUpdate`: 43.2 ns.
