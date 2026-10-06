# ADR-0001: REXI Core Project Architecture & Two-World System Separation

**Status:** Accepted  
**Date:** 2026-10-06  
**Deciders:** REXI Lead Architecture Team  
**Consulted:** Core Engineering & Quantitative Research  

---

## 1. Context and Problem Statement

Building an institutional-grade algorithmic trading and research platform requires addressing two conflicting design goals:
1. **Ultra-low-latency, zero-allocation, deterministic execution** for real-time market data handling, order book maintenance, risk evaluation, and order placement.
2. **High-expressivity, rapid experimentation, matrix operations, and AI integration** for statistical research, signal discovery, feature engineering, and machine learning models.

Attempting to implement research in low-level C++ drastically slows research velocity, while attempting to execute live HFT strategies in Python introduces unacceptable garbage collection pauses, runtime overhead, and non-deterministic latency. Furthermore, directly wiring LLMs or generative AI models into trade execution creates catastrophic tail-risk.

## 2. Decision Drivers

- Need for microsecond-level deterministic processing for market data and risk checks.
- Need for modern data science, deep learning, and reinforcement learning ecosystem access (PyTorch, Polars, Arrow).
- Necessity of preventing lookahead bias, data leakage, and unconstrained AI execution errors.
- Support for development on macOS (Apple Silicon) with zero-cost deployment to high-performance Linux execution environments.
- Strict organizational discipline to scale the codebase cleanly across dozens of planned subsystems.

## 3. Considered Options

- **Option 1: Monolithic Python Platform** (Cython/Numba extensions for fast paths).
- **Option 2: Monolithic C++ Platform** (C++ for both research and execution).
- **Option 3: Strict Two-World Model** (C++20/23 Production Engine + Python Research/AI Engine communicating over well-defined data protocols).

## 4. Decision Outcome

**Chosen Option:** **Option 3 (Strict Two-World Model)**.

### Architectural Rules:
1. **World A (Production Hot Path):** Implemented in modern portable C++ (C++20/C++23), built via CMake/Ninja. Hot paths are event-driven, cache-conscious, and avoid dynamic memory allocations during runtime loops.
2. **World B (Research & AI Lab):** Implemented in Python (NumPy, Polars, SciPy, PyTorch, Apache Arrow). Responsible for offline datasets, backtesting, factor validation, and AI-assisted hypothesis generation.
3. **AI Safety Boundary:** The AI Research Agent operates strictly in the research plane (Hypothesis -> Experiment -> Quantitative Validation). An AI agent is NEVER directly connected to the broker or execution hot path.
4. **Platform Strategy:** Code is written to POSIX / C++ standard standards on macOS during development, abstracting OS-specific primitives (e.g., networking, threading, timing) behind platform layers so it compiles and optimizes seamlessly on Linux.
5. **Data Interchange:** Structured, zero-copy, or schema-enforced formats (Arrow, Parquet, FlatBuffers) serve as the bridge between research artifacts and production ingestion.

## 5. Consequences

### Positive:
- Optimal execution speed and determinism where it matters (production risk and execution).
- Maximum research velocity, flexible model training, and access to the latest machine learning breakthroughs.
- Total structural immunity from rogue AI orders executing on live exchanges.
- Clean development loop on macOS workstations with seamless path to production Linux clusters.

### Negative / Trade-offs:
- Requires maintaining two distinct language ecosystems and build setups.
- Requires explicit model translation/compilation step (e.g., ONNX runtime or compiled weight tables) when promoting validated models from Python research to the C++ core engine.
