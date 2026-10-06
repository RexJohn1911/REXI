# REXI Known Issues & Technical Debt Tracker

This document tracks known issues, risks, technical debt, and architectural constraints identified during the project lifecycle.

---

## Active Issues

*No active code defects currently recorded — Phase 00 established initial architecture and project constitution.*

---

## Architectural Constraints & Watch Items

| ID | Area | Severity | Description | Mitigation Plan |
| :--- | :--- | :--- | :--- | :--- |
| **CON-0001** | Platform | Medium | macOS Darwin kernel lacks Linux `epoll`, `io_uring`, and explicit thread-to-core hard affinity APIs (`pthread_setaffinity_np`). | Implement clean platform abstraction layers under `infrastructure/networking/` and `infrastructure/execution/` that use `kqueue` / standard C++ threads on macOS and native high-perf APIs on Linux. |
| **CON-0002** | Data | Medium | High tick volume (L2/L3 order book data) can consume massive memory and I/O bandwidth during backtesting. | Enforce chunked streaming, memory-mapped Parquet/Arrow structures, and zero-copy binary formats in Phase 08+. |
| **CON-0003** | AI Safety | High | Risk of AI research agents generating overfitted strategies or leaking out-of-sample data. | Enforce strict no-leakage verification frameworks, deflated Sharpe calculations, and automated temporal causal checks in Phase 09. |
| **CON-0004** | Latency | High | Cross-language IPC (Python to C++) introduces latency overhead if not properly structured. | Maintain complete separation: production execution runs entirely inside native C++ without runtime Python dependencies. |
| **CON-0005** | Simulator | Low | Exotic order types (iceberg, pegged, stop-loss) and stochastic network jitter models are excluded from Phase 03 baseline. | Keep simulator core minimal, deterministic, and modular so specialized order types can be added cleanly in later execution phases (Phase 22). |
| **CON-0006** | Market Data | Low | Canonical flat `OrderBookSnapshotMessage` is bounded to 16 bid/ask levels for zero heap allocation. | Deeper L2 full-depth snapshots or full-book recovery in Phase 05/07 will use multi-packet chunking or out-of-band snapshot channels. |

---

## Resolved Issues

| ID | Area | Resolution | Phase | Verification Evidence |
| :--- | :--- | :--- | :--- | :--- |
| **CON-0007** | Order Book | Replaced `std::list` nodes and `std::unordered_map` with preallocated `OrderPool` and open-addressing `OrderIdIndex` with backward-shift deletion. | Phase 06 | Verified zero heap allocations in steady-state operations via `ScopedAllocationGuard` in `test_order_book_allocation.cpp`. Batch add latency improved to 18.5 ns/order. |
