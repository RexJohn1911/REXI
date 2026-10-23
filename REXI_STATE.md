# REXI State Tracker

**Project:** REXI — Real-time EXecution & Intelligence
**Current Phase:** PHASE 11 — Statistical Strategy Laboratory
**Phase Status:** COMPLETED & VALIDATION-PASSED
**Next Phase:** PHASE 12 — Market Making Engine
**Last Updated:** 2026-10-23

---

## Current System State Summary

- **Statistical Strategy Laboratory Subsystem:** Quantitative strategy research and deterministic backtesting framework operating under the two-world architecture:
  - Strategy contracts and causal invariants (`research/strategies/types.py`, `research/strategies/base.py`): strict 5-point temporal coordinate chain ($T_{\text{event}} \le T_{\text{available}} \le T_{\text{decision}} \le T_{\text{actionable}} \le T_{\text{fill}}$), immutable signal, order intent, fill record, and position state structures, `StrategyBase` contract, and baseline `FlatBenchmarkStrategy`.
  - Forward target generation (`research/strategies/targets.py`): mathematical fixed-horizon log returns, de Prado triple-barrier path labeling with vertical expiration barriers, and closed `LabelInformationInterval` metadata for integration with Phase 09 purging.
  - Deterministic event-driven backtesting engine (`research/backtesting/engine.py`, `research/backtesting/exceptions.py`): causal execution, displayed-depth liquidity consumption with partial fill support, stale-quote rejection, crossed/locked book rejection, cash ledger and mark-to-market position accounting.
  - Transaction costs and regulatory accounting (`research/backtesting/costs.py`): decomposed cost attribution (half-spread, linear slippage, temporary impact, venue fees), SEC Section 31 dated fee schedules with Rule 31 charge-date lookup, FINRA TAF multi-year equity schedules pursuant to SR-FINRA-2026-020 (Release No. 34-106410), U.S. Eastern timezone normalization, and strict separation of FINRA 20:00:00 ET TRF reporting deadlines from statutory T+1 settlement dates.
- **Microstructure Feature Engine Subsystem:** High-performance, deterministic microstructure feature calculation layer operating under C++ hot-path streaming and Python research pipeline (`research/features/`).
- **No-Leakage Research Framework Subsystem:** Point-in-time causal partitioning, label horizon purging, targeted post-test embargo, and lookahead verification engine (`research.leakage`).
- **Research Data Lake Subsystem:** Hardened, deterministic, schema-enforced columnar storage tier (`research.datasets`).
- **Engineering Quality:** 164/164 Python tests passing, 142/142 C++ GoogleTests passing across Debug and Release builds, Ruff 100% clean, strict Mypy 100% clean, `git diff --check` clean.
- **Git State:** Maintained on branch `main`.

---

## Active Phase Progress (Phase 11)

- [x] Design strategy contracts and 5-point temporal coordinate chain ([types.py](research/strategies/types.py))
- [x] Implement abstract StrategyBase and FlatBenchmarkStrategy ([base.py](research/strategies/base.py))
- [x] Implement TargetGenerator with de Prado triple-barrier and fixed-horizon returns ([targets.py](research/strategies/targets.py))
- [x] Implement dated transaction cost model with SEC Section 31 and FINRA TAF schedules ([costs.py](research/backtesting/costs.py))
- [x] Implement DeterministicBacktestEngine with displayed-depth consumption and causal fill execution ([engine.py](research/backtesting/engine.py))
- [x] Implement strategy types and temporal causality unit tests ([test_strategy_types_and_temporal.py](tests/unit/test_strategy_types_and_temporal.py))
- [x] Implement backtest costs, settlement calendar, and engine unit tests ([test_backtest_costs_and_engine.py](tests/unit/test_backtest_costs_and_engine.py))
- [x] Author Statistical Strategy Laboratory Architecture ([REXI_STATISTICAL_STRATEGY_LABORATORY.md](docs/architecture/REXI_STATISTICAL_STRATEGY_LABORATORY.md)) and ADR ([ADR-0011](docs/decisions/ADR-0011-statistical-strategy-laboratory.md))
- [x] Author Phase 11 Checkpoint ([PHASE_11_CHECKPOINT.md](docs/checkpoints/PHASE_11_CHECKPOINT.md))
- [x] Update project decisions log ([REXI_DECISIONS.md](REXI_DECISIONS.md)), known issues ([REXI_KNOWN_ISSUES.md](REXI_KNOWN_ISSUES.md)), and roadmap ([REXI_ROADMAP.md](REXI_ROADMAP.md))

---

## Next Action Plan (Phase 12)

- **Target Phase:** PHASE 12 — Market Making Engine
- **Objectives:**
  - Avellaneda-Stoikov optimal inventory models.
  - Symmetric and asymmetric quote skewing based on inventory risk and book imbalance.
  - Adverse selection guards and toxicity filters consuming Phase 10 VPIN and OFI.
  - Post-only quoting mechanisms with passive queue preservation.
