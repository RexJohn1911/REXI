# REXI Engineering Toolchain & Developer Guide

This document specifies the official developer workflow, toolchain requirements, build presets, testing harnesses, and linting standards for the REXI platform.

---

## 1. Prerequisites & Required Tools

| Component | Minimum Version | Recommended / Standard |
| :--- | :--- | :--- |
| **C++ Compiler** | C++20 Compliant | Apple Clang >= 15 (macOS), Clang >= 16 or GCC >= 12 (Linux) |
| **Build System** | CMake >= 3.22 | CMake 3.28+ with Ninja generator |
| **Build Tool** | Ninja >= 1.11 | Ninja 1.12+ |
| **Python** | Python >= 3.10 | Python 3.11 / 3.12 (virtualenv recommended) |
| **Python Tooling** | `pytest >= 8.0`, `ruff >= 0.5`, `mypy >= 1.10` | Installed via `pyproject.toml` |
| **Code Formatting** | `clang-format >= 16` | Standard `.clang-format` (Google/LLVM baseline) |

---

## 2. C++ Production Engine Workflow

REXI uses CMake Presets to ensure reproducible out-of-source builds across development (macOS) and production (Linux) targets.

### Configuration Presets
- `debug`: Builds with debug symbols and full testing/benchmark targets in `build/debug/`.
- `release`: Builds optimized binary with full testing/benchmark targets in `build/release/`.

### Commands

```bash
# Configure Debug Build
cmake --preset debug

# Build Debug Targets (rexi_core, rexi_unit_tests, rexi_benchmarks)
cmake --build --preset debug

# Run CTest Unit Tests
ctest --test-dir build/debug --output-on-failure

# Configure & Build Release Build
cmake --preset release
cmake --build --preset release

# Run Release Unit Tests
ctest --test-dir build/release --output-on-failure

# Run Microbenchmarks
./build/release/benchmarks/rexi_benchmarks
```

---

## 3. Python Research Engine Workflow

The research and machine learning modules reside in `research/` and `ml/`. All configuration is centralized in [`pyproject.toml`](file:///Users/rexjohnabraham/Documents/REXI/pyproject.toml).

### Setup

```bash
# Create and activate virtual environment (optional)
python3 -m venv .venv
source .venv/bin/activate

# Install development dependencies
pip install -e ".[dev]"
```

### Testing, Linting & Type Checking

```bash
# Run pytest test suite
pytest

# Run Ruff linter
ruff check .

# Run Ruff auto-formatter
ruff format --check .

# Run Mypy static type checker
mypy research ml tests/unit/test_research_foundation.py
```

---

## 4. Code Formatting & Quality

### C++ Code Quality
```bash
# Verify formatting across C++ headers and source files
clang-format --dry-run --Werror core/include/rexi/*.hpp core/src/*.cpp tests/unit/*.cpp benchmarks/*.cpp

# Automatically apply formatting
clang-format -i core/include/rexi/*.hpp core/src/*.cpp tests/unit/*.cpp benchmarks/*.cpp
```

---

## 5. Continuous Integration (CI)

GitHub Actions workflows are defined in [`.github/workflows/ci.yml`](file:///Users/rexjohnabraham/Documents/REXI/.github/workflows/ci.yml).
The pipeline automatically validates:
1. **C++ Matrix:** Compiles, builds, and runs unit tests + benchmarks on `macos-latest` and `ubuntu-latest` across `Debug` and `Release` configurations.
2. **Python Quality:** Runs `clang-format` checks, `ruff` linting, `mypy` strict type-checking, and `pytest` test discovery on `ubuntu-latest`.
