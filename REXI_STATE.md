# REXI State Tracker

**Project:** REXI — Real-time EXecution & Intelligence
**Current Phase:** PHASE 09 — No-Leakage Research Framework
**Phase Status:** COMPLETED & AUDIT-VERIFIED
**Next Phase:** PHASE 10 — Microstructure Feature Engine
**Last Updated:** 2026-10-22

---

## Current System State Summary

- **No-Leakage Research Framework Subsystem:** Point-in-time causal partitioning, label horizon purging, targeted post-test embargo, and lookahead verification engine (`research.leakage`).
  - Strict chronological splitting: Train -> [Validation] -> Test, rolling/expanding walk-forward, Purged K-Fold, and Combinatorial Purged Cross-Validation (CPCV) with zero random shuffling.
  - Mathematically formal interval semantics: half-open partition boundaries $[t_{\text{start}}, t_{\text{end}})$, closed label information intervals $[t_{\text{obs}}, t_{\text{label\_end}}]$, exact-boundary purging, and targeted post-test embargo buffer $[t_{\text{test, end}}, t_{\text{test, end}} + \Delta_{\text{embargo}})$.
  - Duplicate decision timestamp preservation: boundary cuts never arbitrarily divide identical nanosecond timestamps across train and test partitions.
  - Point-in-time causal alignment: `PointInTimeAligner` enforces physical ($T_{\text{event}} \le T_{\text{available}}$) and decision ($T_{\text{available}} \le T_{\text{decision}}$) causality via Arrow-native as-of joins with staleness guards.
  - Verifiable causal auditor: `LookaheadDetector` verifies timestamp availability, physical order, partition disjointness, and purge/embargo compliance.
  - Phase 08 integration: `DatasetSplitter` creates cryptographically signed `SplitManifest` metadata linked to source Phase 08 `DatasetManifest` SHA-256 without copying or mutating underlying Parquet datasets; `SplitDatasetReader` provides memory-bounded partition projections.
- **Research Data Lake Subsystem:** Hardened, deterministic, schema-enforced columnar storage tier (`research.datasets`).
  - Centralized `SchemaRegistry` managing versioned PyArrow schemas for trades, quotes, L3 book updates, depth snapshots, market status, instrument definitions, and unified replay events (including full `OrderBookSnapshotMessage` payload fields).
  - Strict financial typing: 64-bit signed integer tick prices (`pa.int64()`), discrete lot quantities (`pa.uint64()`), nanosecond timestamps, zero floating-point conversions.
  - Safe, transactional `DatasetWriter` with 3-phase backup publication swap and non-blocking process file locking (`.lock_{dataset_id}`).
- **Engineering Quality:** 101/101 Python tests passing, 128/128 C++ GoogleTests passing across Debug and Release builds, Ruff 100% clean, strict Mypy 100% clean.
- **Git State:** Maintained on branch `main` at commit `e613e8e`; working tree preserved uncommitted for user review.

---

## Active Phase Progress (Phase 09)

- [x] Design domain models, enums, dataclasses, and custom exceptions ([types.py](file:///Users/rexjohnabraham/Documents/REXI/research/leakage/types.py), [exceptions.py](file:///Users/rexjohnabraham/Documents/REXI/research/leakage/exceptions.py))
- [x] Implement timestamp normalization with UTC timezone enforcement and pre-1970 negative epoch support ([types.py](file:///Users/rexjohnabraham/Documents/REXI/research/leakage/types.py))
- [x] Implement strict chronological train/val/test holdout, rolling/expanding walk-forward splitters ([split.py](file:///Users/rexjohnabraham/Documents/REXI/research/leakage/split.py))
- [x] Implement duplicate decision timestamp boundary preservation ([split.py](file:///Users/rexjohnabraham/Documents/REXI/research/leakage/split.py))
- [x] Implement closed label information intervals and de Prado purging ([split.py](file:///Users/rexjohnabraham/Documents/REXI/research/leakage/split.py))
- [x] Implement targeted post-test embargo for Purged K-Fold and CPCV ([split.py](file:///Users/rexjohnabraham/Documents/REXI/research/leakage/split.py))
- [x] Implement point-in-time as-of causal feature aligner ($T_{\text{avail}} \le T_{\text{decision}}$) ([point_in_time.py](file:///Users/rexjohnabraham/Documents/REXI/research/leakage/point_in_time.py))
- [x] Implement verifiable causal leakage auditor ([detector.py](file:///Users/rexjohnabraham/Documents/REXI/research/leakage/detector.py))
- [x] Implement Phase 08 Data Lake integration & SplitManifest serialization ([dataset_split.py](file:///Users/rexjohnabraham/Documents/REXI/research/leakage/dataset_split.py))
- [x] Implement unit tests for types, safety, and intervals ([test_leakage_types_and_safety.py](file:///Users/rexjohnabraham/Documents/REXI/tests/unit/test_leakage_types_and_safety.py))
- [x] Implement unit tests for chronological splits and walk-forward ([test_leakage_chronological_split.py](file:///Users/rexjohnabraham/Documents/REXI/tests/unit/test_leakage_chronological_split.py))
- [x] Implement unit tests for purging, embargo, and Purged K-Fold ([test_leakage_purging_embargo.py](file:///Users/rexjohnabraham/Documents/REXI/tests/unit/test_leakage_purging_embargo.py))
- [x] Implement unit tests for point-in-time alignment and lookahead detector ([test_leakage_point_in_time.py](file:///Users/rexjohnabraham/Documents/REXI/tests/unit/test_leakage_point_in_time.py))
- [x] Implement unit tests for Phase 08 Data Lake integration ([test_leakage_dataset_integration.py](file:///Users/rexjohnabraham/Documents/REXI/tests/unit/test_leakage_dataset_integration.py))
- [x] Implement end-to-end integration test pipeline ([test_leakage_pipeline.py](file:///Users/rexjohnabraham/Documents/REXI/tests/integration/test_leakage_pipeline.py))
- [x] Author No-Leakage Research Framework Architecture ([REXI_NO_LEAKAGE_RESEARCH_FRAMEWORK.md](file:///Users/rexjohnabraham/Documents/REXI/docs/architecture/REXI_NO_LEAKAGE_RESEARCH_FRAMEWORK.md)) and ADR ([ADR-0009](file:///Users/rexjohnabraham/Documents/REXI/docs/decisions/ADR-0009-no-leakage-research-framework.md))

---

## Next Action Plan (Phase 10)

- **Target Phase:** PHASE 10 — Microstructure Feature Engine
- **Objectives:**
  - Order Flow Imbalance (OFI) feature generator across L2/L3 order book states.
  - Volume-Synchronized Probability of Toxicity (VPIN).
  - Micro-price, Roll impact, and queue depletion indicators operating on point-in-time causal event streams.
