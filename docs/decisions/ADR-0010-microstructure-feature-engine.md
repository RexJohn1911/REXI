# ADR-0010: Microstructure Feature Engine

## Status
Accepted

## Date
2026-10-22

## Context
Quantitative feature extraction in algorithmic trading requires high-fidelity, deterministic microstructure metrics derived from quote books, order books, and trade flows. In real-time trading, these features must be computed with sub-microsecond latency and zero memory allocations. In quantitative research, features must be computed over historical datasets without lookahead bias, respecting point-in-time causality ($T_{\text{available}} \le T_{\text{decision}}$) and integrating seamlessly with Phase 08 Data Lake datasets and Phase 09 leakage safeguards.

Prior to Phase 10, REXI possessed L2/L3 order book implementations, synthetic generators, historical market replay, a partitioned columnar data lake, and no-leakage chronological splitters, but lacked a unified microstructure feature calculation layer.

## Decisions

### 1. Two-World Architecture
- **C++ Hot-Path Engine** (`core/include/rexi/microstructure/`): Zero steady-state dynamic memory allocation, cache-friendly contiguous structures, fixed ring buffers, sub-50-nanosecond update latency, strict temporal validation.
- **Python Research Feature Engine & Pipeline** (`research/features/`): Vectorized and streaming PyArrow table feature generation, seamless reading from Phase 08 `DatasetReader`, writing via `DatasetWriter` under `MICROSTRUCTURE_FEATURES_SCHEMA_V1`, and causality verification via Phase 09 `LookaheadDetector`.

### 2. Strict Causal Timestamps and Out-of-Order Handling
Every feature record tracks:
- Event timestamp $T_{\text{event}}$ (venue quote/trade timestamp).
- Source timestamp $T_{\text{source}}$ (feed ingestion timestamp).
- Decision availability timestamp $T_{\text{decision}} = \max(T_{\text{event}}, T_{\text{source}})$.
Events violating non-decreasing monotonic timestamps ($T_{\text{event}}[i] < T_{\text{event}}[i-1]$) are dropped explicitly, with a drop counter incremented. Feature availability timestamps are audited against lookahead violations using `LookaheadDetector.audit_point_in_time`.

### 3. Explicit Feature Validity Gating (No Silent Zeros)
Every feature has an explicit boolean validity flag (`has_bid`, `has_ask`, `is_crossed`, `has_spread`, `has_mid`, `has_weighted_mid`, `has_book_imbalance`, `has_depth_imbalance`, `has_instant_ofi`, `has_rolling_ofi`, `has_trade`, `has_trade_flow`, `has_vwap`, `has_log_return`, `has_realized_volatility`, `has_roll_spread`, `has_vpin`). Missing quotes, crossed/locked books, insufficient history, or non-negative Roll autocovariances are never substituted with silent zeros.

### 4. Canonical Microstructure Formulations
- **Level 1**: Integer spread, relative spread, arithmetic mid-price, volume-weighted micro-price, top-of-book depth imbalance.
- **Level 2**: Multi-level aggregated depth ($K=5$) and depth imbalance.
- **Order Flow Imbalance (OFI)**: Cont, Kukanov & Stoikov (2014) price/volume transition formulation and rolling circular sum.
- **Trade Flow Dynamics**: Signed volume, buyer/seller rolling volumes, trade flow imbalance, and rolling VWAP.
- **Returns & Volatility**: Log returns of mid-price and sample realized volatility.
- **Advanced Microstructure**: Roll (1984) effective spread via price change lag-1 autocovariance; Easley, Lopez de Prado & O'Hara (2012) VPIN with deterministic volume bucket boundary splitting.

## Consequences

### Positive
- Unified, deterministic feature definitions shared between C++ execution and Python quantitative research.
- Sub-50ns update latency in C++ ensures suitability for low-latency live trading pipelines.
- Absolute prevention of lookahead leakage in research features through Phase 09 integration.
- Full round-trip dataset persistence supported in Phase 08 Data Lake under `rexi.features.microstructure` schema.

### Negative / Trade-offs
- Crossed or locked books invalidate spread and mid-price features during transient arbitrage/error intervals.
- Roll spread requires negative lag-1 autocovariance; during trending markets where autocovariance is non-negative, the feature is marked invalid.
