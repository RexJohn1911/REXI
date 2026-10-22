# ADR-0009: No-Leakage Research Framework

## Status
Accepted

## Date
2026-10-22

## Context
In quantitative finance and machine learning research, information leakage—incorporating future or out-of-sample data into model training, feature generation, or cross-validation folds—is the most prevalent cause of overfitted, non-viable trading strategies.

Phase 08 established the persistent Research Data Lake (`research.datasets`). Phase 09 requires a reliable, reproducible, strictly offline research framework preventing future information from leaking into model training, feature generation, or evaluation.

Key architectural requirements:
1. Strict chronological ordering (Train $\to$ Validation $\to$ Test); zero random shuffling of time-series records.
2. Canonical 64-bit nanosecond timestamps with explicit UTC timezone enforcement, pre-1970 negative epoch support, and rejection of naive/ambiguous representations.
3. Separation of event time ($T_{\text{event}}$) from point-in-time availability time ($T_{\text{available}}$), enforcing $T_{\text{available}} \le T_{\text{decision}}$.
4. Explicit representation of label information intervals $[t_{\text{obs}}, t_{\text{label\_end}}]$, with de Prado purging of overlapping samples.
5. Targeted embargo applied strictly to post-test training data to eliminate autoregressive serial correlation leakage.
6. Deterministic tie-preservation for duplicate timestamps at partition boundaries.
7. Seamless, non-mutating integration with Phase 08 Data Lake datasets, producing cryptographically sealed `SplitManifest` metadata.

## Decisions

### 1. Isolated Python Research Subsystem
We implement the framework in `research/leakage/`, keeping it strictly within the Python research environment and decoupled from the C++ production execution engine.

### 2. Standardized Half-Open and Closed Interval Semantics
- Partition time boundaries are defined as half-open: $[t_{\text{start}}, t_{\text{end}})$.
- Label information intervals are defined as closed: $[t_{\text{obs}}, t_{\text{label\_end}}]$.
- Purging occurs if and only if $t_{\text{obs}} < t_{\text{test, end}}$ and $t_{\text{label\_end}} \ge t_{\text{test, start}}$.
- Embargo applies strictly to post-test training samples where $t_{\text{obs}} \in [t_{\text{test, end}}, t_{\text{test, end}} + \Delta_{\text{embargo}})$.

### 3. Duplicate Decision Timestamp Boundary Preservation
Boundary cuts never arbitrarily separate identical nanosecond timestamps across train and test partitions. Ties are deterministically kept within the earlier or later partition, or rejected if safe partitioning is mathematically impossible.

### 4. Point-in-Time Availability and As-Of Alignment
We establish `PointInTimeAligner` to enforce:
$$T_{\text{event}} \le T_{\text{available}} \le T_{\text{decision}}$$
Features published after decision timestamp $T_{\text{decision}}$ cannot be observed at $T_{\text{decision}}$.

### 5. Verifiable Causal Audit Engine
`LookaheadDetector` verifies mathematical causality invariants: availability constraints, boundary disjointness, purge completeness, and embargo buffers. Statistical heuristics (such as feature-target correlation) are treated strictly as optional diagnostics, never as proof of leakage.

### 6. Phase 08 Data Lake Integration & SplitManifest Specification
`DatasetSplitter` partitions Phase 08 datasets directly via `DatasetReader`, generating verifiable `SplitManifest` files referencing the source dataset ID and manifest SHA-256. `SplitDatasetReader` provides projection tables for specific partition roles.

## Consequences

### Positive
- Prevents lookahead bias and label leakage in all downstream research phases (Phases 10 through 18).
- Reproducible, bit-for-bit deterministic cross-validation splits.
- Preserves Phase 08 Data Lake datasets immutably without duplicating data files.

### Negative / Trade-offs
- Purging and embargo discard training samples near evaluation boundaries, reducing effective training set size.
- Strictly offline: does not operate in live trading hot paths.
