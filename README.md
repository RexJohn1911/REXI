# REXI — Real-time EXecution & Intelligence

> **Institutional-grade high-frequency quantitative research and deterministic execution platform for U.S. markets.**

---

## 1. System Vision

REXI is engineered as a dual-engine quantitative platform that bridges modern statistical research and artificial intelligence with ultra-low-latency, deterministic market execution:

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

### Core Tenet: AI Safety in Quantitative Trading
REXI strictly prevents generative AI / LLM agents from direct execution access. The AI research layer formulates hypotheses, analyzes features, and explores parameter spaces offline. Execution is solely managed by deterministic, risk-gated C++ engines.

---

## 2. Two-World Architecture

REXI separates execution and research into two dedicated engines:

1. **Production Engine (`core/`, `simulator/`):**
   - **Language:** C++20 / C++23
   - **Characteristics:** Zero/low allocation in hot loops, deterministic event processing, cache-friendly data structures, cross-platform portability (macOS development to high-performance Linux targets).
2. **Research & AI Engine (`research/`, `ml/`):**
   - **Language:** Python 3.11+
   - **Ecosystem:** NumPy, Polars, PyTorch, SciPy, Apache Arrow / Parquet.
   - **Scope:** Feature discovery, microstructure metrics (OFI, VPIN), classical ML / deep learning, statistical modeling, and no-lookahead backtesting.

---

## 3. Directory Layout

REXI enforces strict single-canonical-location folder discipline:

```text
REXI/
├── apps/
│   └── dashboard/                  # Future Claymorphism web dashboard
├── core/                           # C++ Production Engine
│   ├── events/                     # Event loop, clock, and dispatchers
│   ├── market_data/                # Market data decoders and feed handlers
│   ├── order_book/                 # L2/L3 order book reconstruction
│   ├── microstructure/             # Real-time book signals & queue dynamics
│   ├── alpha/                      # Low-latency compiled alpha signals
│   ├── strategies/                 # Deterministic execution strategies
│   ├── risk/                       # Pre-trade deterministic risk engine
│   ├── execution/                  # Smart order routing and execution logic
│   └── portfolio/                  # Position, cash, and PnL accounting
├── simulator/                      # C++ Simulation Environment
│   ├── exchange/                   # Deterministic matching engine
│   ├── matching/                   # Queue position & fill simulator
│   ├── market_data/                # Synthetic & feed generator
│   └── replay/                     # Historical nanosecond replay engine
├── research/                       # Python Quantitative Research
│   ├── datasets/                   # Ingestion & point-in-time reference data
│   ├── features/                   # Microstructure & alpha feature library
│   ├── models/                     # Statistical & mathematical models
│   ├── experiments/                # Versioned experiment logs & artifacts
│   ├── backtesting/                # Vectorized & event-driven backtesting
│   └── notebooks/                  # Ad-hoc exploratory notebooks
├── ml/                             # Machine Learning & AI
│   ├── classical/                  # Gradient boosting, linear & factor models
│   ├── deep_learning/              # PyTorch architectures (TCN, Transformers)
│   └── reinforcement_learning/     # Gym/Gymnasium market environments & agents
├── infrastructure/                 # Core Infrastructure & Systems
│   ├── networking/                 # Socket, IPC, and packet buffers
│   ├── storage/                    # Time-series persistence & Parquet writers
│   ├── monitoring/                 # Metrics collectors & telemetry
│   └── configuration/              # Config parsers & limit managers
├── tests/                          # Automated Testing Suites
│   ├── unit/                       # Unit tests (GoogleTest & pytest)
│   ├── integration/                # Cross-component integration tests
│   ├── regression/                 # Regression suites
│   └── performance/                # Throughput & latency validation
├── benchmarks/                     # Google Benchmark hot-path microbenchmarks
├── scripts/                        # Build, data download, and tooling scripts
├── configs/                        # Configuration files and parameters
├── docs/                           # Documentation
│   ├── architecture/               # Architecture specifications
│   ├── decisions/                  # Architectural Decision Records (ADRs)
│   ├── research/                   # Research notes and whitepapers
│   └── checkpoints/                # Phase checkpoint archives
├── data/                           # Data storage (git-ignored)
│   ├── raw/
│   ├── processed/
│   └── sample/
├── models/                         # Serialized model weights (git-ignored)
│   ├── development/
│   └── production/
├── docker/                         # Container definitions for CI/CD
└── .github/workflows/              # GitHub Actions CI pipelines
```

---

## 4. Key Documentation Links

- **Architecture Manual:** [REXI_ARCHITECTURE.md](file:///Users/rexjohnabraham/Documents/REXI/docs/architecture/REXI_ARCHITECTURE.md)
- **Architectural Decision Record 0001:** [ADR-0001](file:///Users/rexjohnabraham/Documents/REXI/docs/decisions/ADR-0001-project-architecture.md)
- **32-Phase Roadmap:** [REXI_ROADMAP.md](file:///Users/rexjohnabraham/Documents/REXI/REXI_ROADMAP.md)
- **Architecture Decisions Log:** [REXI_DECISIONS.md](file:///Users/rexjohnabraham/Documents/REXI/REXI_DECISIONS.md)
- **Known Issues & Constraints:** [REXI_KNOWN_ISSUES.md](file:///Users/rexjohnabraham/Documents/REXI/REXI_KNOWN_ISSUES.md)
- **Current System State:** [REXI_STATE.md](file:///Users/rexjohnabraham/Documents/REXI/REXI_STATE.md)
- **Phase 00 Checkpoint:** [PHASE_00_CHECKPOINT.md](file:///Users/rexjohnabraham/Documents/REXI/docs/checkpoints/PHASE_00_CHECKPOINT.md)

---

## 5. Current Status

REXI is currently at **PHASE 00 — Constitution & Architecture Foundation** (Completed).  
The next planned milestone is **PHASE 01 — Repository & Engineering Foundation**.
