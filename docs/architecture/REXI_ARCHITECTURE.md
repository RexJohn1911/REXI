# REXI Architecture Specification

**Project:** REXI — Real-time EXecution & Intelligence  
**Phase:** 00 — Constitution & Architecture Foundation  
**Status:** Active  

---

## 1. Executive Summary & Vision

REXI is an institutional-grade, high-frequency quantitative research and execution platform designed for U.S. financial markets. The system harmonizes two foundational disciplines:
1. **Deterministic, low-latency execution and market microstructure engineering** (C++20/23).
2. **AI-driven quantitative hypothesis generation, statistical modeling, and ML/RL research** (Python/PyTorch/Polars/Arrow).

REXI is explicitly architected to prevent common design failures observed in modern algorithmic platforms—specifically the dangerous coupling of unconstrained AI generation with raw trade execution.

```
+-------------------------------------------------------------------------+
|                        RESEARCH & DISCOVERY LAYER                       |
|  AI Research Agent --> Hypothesis Generation --> Controlled Experiments |
|                                   |                                     |
|                                   v                                     |
|                       Quantitative Validation                           |
|              (No-Lookahead Backtesting & Walk-Forward Testing)          |
+-----------------------------------|-------------------------------------+
                                    | Promoted Strategies
                                    v
+-------------------------------------------------------------------------+
|                     PRODUCTION & EXECUTION HOT PATH                     |
|                      Deterministic Production Model                     |
|                                   |                                     |
|                                   v                                     |
|                       Deterministic Risk Engine                         |
|                                   |                                     |
|                                   v                                     |
|                     Ultra-Low Latency Execution Engine                  |
|                                   |                                     |
|                                   v                                     |
|                       Market / Broker Connection                        |
+-------------------------------------------------------------------------+
```

---

## 2. Core Architectural Separation: The Two-World Model

REXI strictly segregates its architecture into two distinct operational planes:

```
+-------------------------------------------------------------------------------+
|                       WORLD A: PRODUCTION / EXECUTION                         |
|  - Language: C++20 / C++23                                                    |
|  - Philosophy: Zero/Low heap allocation in hot path, deterministic, modular   |
|  - Latency Budget: Sub-microsecond to low-microsecond deterministic pipeline  |
|  - Subsystems: Market Data, L2/L3 Book, Microstructure, Risk, Order Exec      |
+-------------------------------------------------------------------------------+
                                    ^ |
                       Interface / Data Bridge:
                 FlatBuffers / Arrow / Zero-Copy IPC
                                    | v
+-------------------------------------------------------------------------------+
|                       WORLD B: QUANTITATIVE RESEARCH & AI                     |
|  - Language: Python (NumPy, Polars, PyTorch, SciPy)                           |
|  - Philosophy: Expressive, vectorized, immutable dataframes, reproducible     |
|  - Scope: Feature Engineering, Model Training, AI Hypothesis Agent, Lab       |
|  - Subsystems: Data Lake, Research Framework, ML/DL/RL Models, Lab, Dashboard|
+-------------------------------------------------------------------------------+
```

### World A: The Production / HFT Engine (`core/`, `simulator/`)
- **Technology:** C++20 / C++23 compiled with Clang/GCC, built via CMake/Ninja.
- **Constraints:**
  - Zero dynamic memory allocations during active market data / trading hot path loops.
  - Cache-friendly data structures (flat arrays, ring buffers, contiguous memory layouts).
  - Explicit deterministic event processing.
  - Platform-independent abstraction layers for core structures (memory mapping, clock sources, networking primitives).

### World B: The Research & Intelligence Engine (`research/`, `ml/`)
- **Technology:** Python ecosystem (NumPy, Polars, Pandas, SciPy, PyTorch, Apache Arrow/Parquet).
- **Constraints:**
  - Strict temporal causality: absolute prohibition of lookahead bias.
  - Experiment tracking and immutable artifact versioning.
  - Vectorized operations and zero-copy dataset sharing with production representations where possible.

### Interface & Boundary
- Communication between World A and World B occurs over formal schema-driven protocols (Apache Arrow IPC, FlatBuffers, Parquet datasets, or memory-mapped ring buffers).
- Python code NEVER executes inside the production hot path.
- LLMs or AI agents NEVER make unconstrained, real-time `BUY`/`SELL` decisions directly to exchange gateways.

---

## 3. Platform & Portability Strategy

REXI enforces cross-platform compatibility from day zero to ensure high developer velocity without sacrificing production scalability:

1. **Development Environment (macOS):**
   - Developed and validated on macOS (Apple Silicon ARM64 & Intel x86_64).
   - Uses standard C++20 constructs, POSIX standards, and portable threading/synchronization primitives (`std::jthread`, `std::atomic`, `std::chrono`).
   - Strict avoidance of Linux-only headers (`sys/epoll.h`, `sched.h` CPU pinning, kernel bypass APIs) inside core business logic.

2. **Platform Abstraction Layer (`infrastructure/`):**
   - Platform-specific capabilities (e.g., `kqueue` on macOS vs. `epoll`/`io_uring` on Linux, thread affinity, high-resolution hardware counters) are isolated behind strict interface contracts.

3. **Production Target (Linux):**
   - The eventual production target is high-performance Linux (kernel tuning, CPU core isolation, kernel bypass networking).
   - Continuous Integration (CI) builds and tests across both macOS and Linux environments.

---

## 4. Folder Discipline & Canonical Organization

Every source file, header, test, configuration, and artifact belongs in exactly one canonical directory.

| Directory | Canonical Responsibility |
| :--- | :--- |
| `apps/dashboard/` | Future user interface and interactive monitoring dashboard. |
| `core/events/` | Event definitions, event loops, clock primitives, dispatchers. |
| `core/market_data/` | Market data decoders, packet handlers, BBO and trade normalizers. |
| `core/order_book/` | L2 (price level) and L3 (individual order / MBO) book reconstruction. |
| `core/microstructure/`| Real-time order flow imbalance (OFI), queue position, micro-price calculations. |
| `core/alpha/` | Low-latency compiled signal generators and feature evaluators. |
| `core/strategies/` | Deterministic strategy implementations. |
| `core/risk/` | Pre-trade risk checks, kill switches, fat-finger safeguards, drawdowns. |
| `core/execution/` | Smart order routing (SOR), passive pegging, slicing, execution algorithms. |
| `core/portfolio/` | Position tracking, cash balances, PnL accounting, margin models. |
| `simulator/exchange/` | Matching engine logic, price-time priority, maker/taker rules. |
| `simulator/matching/` | Queue simulation, fill latency modeling, cancelation mechanics. |
| `simulator/market_data/`| Synthetic and historical feed generators. |
| `simulator/replay/` | Deterministic, nanosecond-accurate historical PCAP / CSV / Parquet replay. |
| `research/datasets/` | Ingestion pipelines, cleaning routines, point-in-time reference data. |
| `research/features/` | Alpha feature definitions, cross-sectional transforms, factor libraries. |
| `research/models/` | Statistical formulations, cointegration, mean-reversion, regime filters. |
| `research/experiments/`| Structured, versioned research notebooks and experiment configurations. |
| `research/backtesting/` | Vectorized and event-driven Python research backtesters. |
| `research/notebooks/` | Interactive Jupyter notebooks for ad-hoc exploratory analysis. |
| `ml/classical/` | Gradient boosting (LightGBM/XGBoost), linear models, ridge/lasso, PCA. |
| `ml/deep_learning/` | PyTorch architectures: Transformers, Temporal Convolutional Networks (TCN), LSTMs. |
| `ml/reinforcement_learning/`| Environment wrappers (Gym/Gymnasium), policy gradients, actor-critic agents. |
| `infrastructure/networking/`| Portable network wrappers, socket buffers, IPC transports. |
| `infrastructure/storage/`| High-throughput time-series persistence, Parquet writers, memory-mapped files. |
| `infrastructure/monitoring/`| Metrics collectors, telemetry, logging infrastructure. |
| `infrastructure/configuration/`| Configuration parsers (YAML/JSON/TOML), environment managers. |
| `tests/unit/` | Isolated unit tests for individual functions and classes. |
| `tests/integration/` | Multi-component integration tests (e.g., Book -> Alpha -> Risk -> Exec). |
| `tests/regression/` | Deterministic regression test suites verifying fixed bug scenarios. |
| `tests/performance/` | Micro-benchmarks, throughput, and latency percentile validation. |
| `benchmarks/` | Google Benchmark suites measuring hot-path execution cycles and cache misses. |
| `scripts/` | Tooling, build scripts, dataset downloaders, environment setup. |
| `configs/` | System configuration definitions, strategy parameters, risk limits. |
| `docs/` | Architecture specs, Architectural Decision Records (ADRs), research logs, checkpoints. |
| `data/` | Local storage for raw, processed, and sample datasets (git-ignored data). |
| `models/` | Serialized model checkpoints (development vs. production-promoted). |
| `docker/` | Dockerfiles and container definitions for reproducible build and run environments. |
| `.github/workflows/` | Continuous Integration and automation pipelines. |

---

## 5. Quantitative Integrity & Research Philosophy

1. **Zero Lookahead Bias:**
   - Every dataset, calculation, and feature matrix must be strictly timestamped at point-of-availability.
   - Point-in-time historical data must account for latency, publishing delays, and revision history.

2. **No-Leakage Guarantee:**
   - Preprocessing, standardizations, and transformations must be fitted exclusively on training windows and strictly applied out-of-sample.

3. **Realistic Friction Modeling:**
   - Backtests and simulations must incorporate exchange fee tiers, rebate schedules, half-spread costs, market impact models, latency jitter, and queue placement penalties.

4. **Strategy Promotion Pipeline:**
   - A model transitions from `research/` to `core/` only after passing rigorous statistical significance tests, out-of-sample validation, deflated Sharpe ratio criteria, and paper-trading verification.

---

## 6. UI / Dashboard Design System (Future State)

When the dashboard (`apps/dashboard/`) is developed in subsequent phases, it will adhere to a **Claymorphism** design system with quantitative ergonomics:
- **Visual Style:** Soft tactile 3D elevation, generous corner radii, subtle inner bevels/highlights, soft layered shadows, restrained neutral/dark palettes with pastel accents.
- **Information Architecture:** Persistent sidebar navigation, stable high-density data grids, non-collapsing core panels, predictable layouts.
- **Ergonomics:** Uncompromising legibility for tick charts, order book ladders, PnL series, latency distributions, and risk telemetry. No crucial data hidden behind accordion cards.

---

## 7. Operational Integrity & Checkpointing

REXI enforces interrupted-workflow resilience. Every major development phase requires updating the state file `REXI_STATE.md` and archiving a discrete phase checkpoint in `docs/checkpoints/PHASE_XX_CHECKPOINT.md`.
