# REXI No-Leakage Research Framework Architecture

## 1. Executive Summary

Phase 09 establishes the canonical **No-Leakage Research Framework** for REXI. Operating strictly offline within the Python research environment (`research.leakage`), this framework provides mathematically rigorous, reproducible, point-in-time causal partitioning, label horizon purging, targeted post-test embargo, and lookahead bias verification for quantitative research.

The framework ensures that quantitative models, feature pipelines, and strategy evaluations are built on causal foundations, preventing future information from leaking into training folds, validation sets, or decision points.

---

## 2. Core Architecture & Pipeline

```
+-------------------------------------------------------------------------+
|                  Phase 08 Research Data Lake Subsystem                  |
|          (Parquet Partitioned Datasets, Schema Registry, Manifests)     |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                    Timestamp Safety & Normalization                     |
|   - Canonical 64-bit signed integer nanoseconds since UNIX epoch        |
|   - Pre-1970 negative epoch timestamps supported                        |
|   - Explicit UTC timezone enforcement (naive/ambiguous rejected)        |
|   - Monotonic order verification (non-decreasing timestamps)            |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                    Strict Chronological Partitioning                    |
|   - Zero random shuffling (strict temporal ordering)                    |
|   - Preserves duplicate decision timestamps intact at boundaries        |
|   - Chronological Hold-out: Train -> [Validation] -> Test               |
|   - Walk-Forward Validation: Rolling & Expanding time windows           |
|   - Purged K-Fold Cross-Validation & Combinatorial Purged CV (CPCV)     |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                Label Horizon Purging & Targeted Embargo                 |
|   - Half-open partition boundaries: [t_start, t_end)                    |
|   - Closed label information intervals: [t_obs, t_label_end]           |
|   - Purging: drops training samples touching evaluation partitions      |
|   - Embargo: applies buffer strictly to post-test training samples      |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|               Point-in-Time Feature Alignment & Detector                |
|   - Physical causality: T_event <= T_available                          |
|   - Decision causality: T_available <= T_decision                       |
|   - As-of join engine with configurable staleness limits                |
|   - Verifiable causal auditor: LookaheadDetector reports violations     |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                 Reproducible Split Manifest Specification               |
|   - SplitManifest: cryptographically sealed with SHA-256 digest         |
|   - Provenance linkage to source Phase 08 DatasetManifest SHA-256       |
|   - Bit-for-bit determinism across identical configurations             |
+-------------------------------------------------------------------------+
```

---

## 3. Mathematical Specifications & Interval Semantics

### A. Endpoint Definitions
To eliminate off-by-one errors and interval ambiguities, the framework strictly enforces:

1. **Partition Time Boundary (Half-Open):** $[t_{\text{start}}, t_{\text{end}})$
   - A record with timestamp $t$ belongs to the partition if and only if:
     $$t_{\text{start}} \le t < t_{\text{end}}$$
   - Adjacent partitions $A = [t_0, t_1)$ and $B = [t_1, t_2)$ tile the timeline continuously with zero gaps and zero overlap at $t_1$.
2. **Label Information Interval (Closed):** $[t_{\text{obs}}, t_{\text{label\_end}}]$
   - For a sample observed at $t_{\text{obs}}$, forward information up to settlement or barrier resolution at $t_{\text{label\_end}}$ enters the target computation.
   - Forward horizon: $h = t_{\text{label\_end}} - t_{\text{obs}} \ge 0$.
3. **Purge Overlap Rule:**
   - A label interval $[t_{\text{obs}}, t_{\text{label\_end}}]$ touches a half-open evaluation partition $[t_{\text{test, start}}, t_{\text{test, end}})$ if and only if:
     $$t_{\text{obs}} < t_{\text{test, end}} \quad \text{and} \quad t_{\text{label\_end}} \ge t_{\text{test, start}}$$
   - Any training sample satisfying this condition is purged (removed from training).
4. **Targeted Embargo Rule:**
   - Embargo applies **strictly to training samples that follow an evaluation partition** in time ($t_{\text{train}} \ge t_{\text{test, end}}$).
   - Any post-test training sample observed within $[t_{\text{test, end}}, t_{\text{test, end}} + \Delta_{\text{embargo}})$ is embargoed and removed from training.
   - Pre-test training data ($t_{\text{train}} < t_{\text{test, start}}$) is never subjected to post-test embargo.

---

## 4. Cross-Validation Topologies

| Strategy | Structure | Purging Rule | Embargo Rule |
| :--- | :--- | :--- | :--- |
| **Chronological Holdout** | Train $\to$ [Val] $\to$ Test | Applied at right boundaries of Train and Val | Not applicable (Train strictly precedes Test) |
| **Walk-Forward Rolling** | Fixed-width Train $\to$ Test | Applied to right boundary of Train | Not applicable (Train strictly precedes Test) |
| **Walk-Forward Expanding** | Anchored Train $\to$ Test | Applied to right boundary of Train | Not applicable (Train strictly precedes Test) |
| **Purged K-Fold** | $K$ temporal blocks | Applied to all pre-test training samples touching test block | Applied to training samples in $[t_{\text{test, end}}, t_{\text{test, end}} + \Delta_{\text{embargo}})$ |
| **Combinatorial Purged (CPCV)** | $\binom{K}{k}$ combinations of test blocks | Applied to all pre-test training samples for each test block | Applied to post-test training samples following each test block |

---

## 5. Duplicate Boundary Tie Preservation

In high-frequency quantitative datasets, bursts of events frequently share identical nanosecond timestamps. Standard ratio-based cutoffs can inadvertently split records with identical timestamps across train and test boundaries.

`ChronologicalSplitter` inspects boundary points:
- If $t_{\text{boundary}} == t_{\text{boundary}-1}$, the duplicate span $[t_{\text{start}}, t_{\text{end}})$ is analyzed.
- The boundary is deterministically shifted to keep the duplicate run entirely within the earlier partition or entirely within the later partition.
- If all records in the series share the identical timestamp or no valid non-empty partition can be formed, `InvalidSplitConfigError` is raised.

---

## 6. Point-in-Time Availability & Causal Alignment

At any decision point $T_{\text{decision}}$, an automated strategy may only observe feature values that were physically available as of that timestamp:
$$T_{\text{available}} \le T_{\text{decision}}$$
Furthermore, physical causality mandates:
$$T_{\text{event}} \le T_{\text{available}}$$

`PointInTimeAligner` implements an Arrow-native as-of join selecting the most recent feature record satisfying $T_{\text{available}} \le T_{\text{decision}}$. Features published after $T_{\text{decision}}$ are strictly excluded.

---

## 7. Verifiable Causality vs. Statistical Diagnostics

`LookaheadDetector` enforces **verifiable causal invariants**:
1. $T_{\text{available}} \le T_{\text{decision}}$ (zero lookahead).
2. $T_{\text{event}} \le T_{\text{available}}$ (physical causal ordering).
3. $\text{Train}_{\text{indices}} \cap \text{Test}_{\text{indices}} = \emptyset$ (strictly disjoint sample partitions).
4. Verification that zero training samples have label horizons touching evaluation partitions.
5. Verification that zero post-test training samples fall inside embargo buffers.

**Statistical Diagnostics:** Feature-target correlation or matching is provided strictly as an *optional exploratory diagnostic*. It is never used as proof of leakage, as genuine predictive alpha naturally exhibits correlation with forward targets.

---

## 8. Documented Limitations & Invariants

> [!IMPORTANT]
> **What the Framework Guarantees:**
> - Mathematical verification of temporal causality, availability timestamps, disjoint split boundaries, and label horizon purging.
> - Bit-for-bit reproducible split manifests with SHA-256 cryptographic verification.
> - Protection against post-test autoregressive leakage via targeted embargo.
>
> **What the Framework CANNOT Guarantee:**
> - It cannot guarantee zero leakage if feature values themselves have lookahead baked in prior to ingestion (e.g. user passes an externally centered moving average or pre-computed forward statistic).
> - It cannot detect leakage if timestamps in the raw input data were fabricated, mislabeled, or recorded out of order prior to entering REXI.
> - It does not guarantee predictive performance or strategy profitability; it guarantees causal integrity.
