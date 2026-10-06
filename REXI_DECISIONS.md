# REXI Architectural & Technical Decisions Log

This document tracks all high-level technical decisions, standards, and conventions agreed upon for the REXI platform.

---

## Index of Decisions

| ID | Date | Category | Summary | Status |
| :--- | :--- | :--- | :--- | :--- |
| **DEC-0001** | 2026-10-06 | Architecture | Two-World System: C++20/23 Execution + Python Research | Accepted |
| **DEC-0002** | 2026-10-06 | AI / Safety | AI Research Agent strictly decoupled from trading hot path | Accepted |
| **DEC-0003** | 2026-10-06 | Platform | macOS (Apple Silicon/Intel) development target with Linux production target | Accepted |
| **DEC-0004** | 2026-10-06 | Build System | CMake 3.22+ with Ninja generator for C++ toolchain | Accepted |
| **DEC-0005** | 2026-10-06 | Testing | Multi-tiered testing: GoogleTest + Google Benchmark (C++) and pytest (Python) | Accepted |
| **DEC-0006** | 2026-10-06 | Data Storage | Apache Arrow and Parquet for research and intermediate representations | Accepted |
| **DEC-0007** | 2026-10-06 | UI / Dashboard | Future dashboard uses Claymorphism (tactile, non-collapsing, quantitative density) | Accepted |
| **DEC-0008** | 2026-10-06 | Discipline | Strict single-canonical-location folder discipline | Accepted |
| **DEC-0009** | 2026-10-06 | Toolchain | Standardized CMakePresets.json with Debug and Release profiles | Accepted |
| **DEC-0010** | 2026-10-06 | Code Style | C++ namespace `rexi` with Google/C++20 clang-format standards | Accepted |
| **DEC-0011** | 2026-10-06 | Python Setup | Centralized pyproject.toml for pytest, ruff, and mypy | Accepted |
| **DEC-0012** | 2026-10-06 | Dependencies | FetchContent shallow clones for GoogleTest v1.14.0 and Benchmark v1.8.3 | Accepted |

---

## Detailed Records

### DEC-0001: Two-World Architecture
- **Decision:** Separate production execution (`core/`, `simulator/`) in modern C++ (C++20/23) from quantitative research (`research/`, `ml/`) in Python.
- **Rationale:** Delivers microsecond-level deterministic low-allocation execution while preserving rapid ML/data-science research velocity.
- **Reference:** [ADR-0001](file:///Users/rexjohnabraham/Documents/REXI/docs/decisions/ADR-0001-project-architecture.md)

### DEC-0002: AI Research Layer Safety Boundary
- **Decision:** AI agents and LLMs will never sit inside the live trading hot path. AI operates solely in the research and hypothesis generation loop:
  `AI Agent -> Hypothesis -> Experiment -> Quantitative Validation -> Promoted Model -> Risk Engine -> Execution -> Exchange`.
- **Rationale:** Unconstrained generative models introduce non-deterministic latencies, hallucinations, and catastrophic tail-risk when placed directly in execution loops.

### DEC-0003: Cross-Platform Development (macOS to Linux)
- **Decision:** All core C++ code must compile, run, and pass tests on macOS (Apple Silicon ARM64 and x86_64) using portable C++ standard features. Platform-specific optimizations (e.g., Linux `io_uring`, epoll, CPU core pinning) will reside behind infrastructure abstraction layers.
- **Rationale:** Maximizes developer productivity on macOS workstations while preserving a clean transition to production Linux servers.

### DEC-0004: Build System Toolchain
- **Decision:** Standardize on CMake (>= 3.22) paired with the Ninja build generator.
- **Rationale:** Industry standard for high-performance C++ builds, enabling fast incremental compilation and cross-IDE support via `compile_commands.json`.

### DEC-0005: Testing Frameworks
- **Decision:** Use GoogleTest (`gtest`) and Google Benchmark (`benchmark`) for C++ components; use `pytest` with hypothesis/coverage for Python modules.
- **Rationale:** Provides rigorous unit, regression, integration, and nanosecond microbenchmarking capabilities across both technology stacks.

### DEC-0006: Data Formats
- **Decision:** Use Apache Arrow (in-memory columnar data) and Apache Parquet (compressed on-disk storage) for tick datasets, feature caches, and model training matrices.
- **Rationale:** High throughput, zero-copy capabilities, cross-language interoperability between C++ and Python.

### DEC-0007: Claymorphism UI Design System (Future State)
- **Decision:** The eventual `apps/dashboard/` will implement a professional, tactile Claymorphism design system with fixed/persistent navigation and non-collapsing core panels.
- **Rationale:** Provides modern, premium aesthetics without sacrificing numerical legibility, chart clarity, or quantitative density.

### DEC-0008: Folder Discipline
- **Decision:** Every file has exactly one canonical location. No random folders, no duplicate source files, and no ad-hoc folder creation.
- **Rationale:** Ensures clean scalability across all 32 development phases.

### DEC-0009: CMake Presets Specification
- **Decision:** Maintain `CMakePresets.json` with standardized `debug` and `release` configure, build, and test presets using `build/debug` and `build/release` out-of-source directories.
- **Rationale:** Provides identical, one-command builds across developer workstations and CI runners.

### DEC-0010: C++ Namespace and Style Conventions
- **Decision:** Root namespace is `rexi`, with subsystem namespaces such as `rexi::core`, `rexi::events`, `rexi::tests`, `rexi::benchmarks`. Formatting strictly enforced via `.clang-format` (Google baseline with C++20 standard).
- **Rationale:** Avoids namespace collisions and ensures code formatting consistency across all contributors.

### DEC-0011: Centralized Python Packaging
- **Decision:** Centralize all Python tooling configuration (`pytest`, `ruff`, `mypy`) within `pyproject.toml` in the repository root.
- **Rationale:** Eliminates scattered configuration files and guarantees uniform linting and type-checking rules.

### DEC-0012: Reproducible C++ Test/Benchmark Dependencies
- **Decision:** Fetch GoogleTest (v1.14.0) and Google Benchmark (v1.8.3) via CMake `FetchContent` using shallow git tags.
- **Rationale:** Ensures hermetic, zero-dependency builds without requiring global system package installations or committing third-party code.
