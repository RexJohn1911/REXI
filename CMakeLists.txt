cmake_minimum_required(VERSION 3.22)

# ==============================================================================
# REXI — Real-time EXecution & Intelligence
# Root CMake Configuration (Phase 01 Engineering Foundation)
# ==============================================================================

project(REXI
    VERSION 0.1.0
    DESCRIPTION "High-frequency quantitative research and deterministic execution platform"
    LANGUAGES CXX
)

# Standard C++ Definition
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Export compile commands for clangd / clang-tidy
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Project Options
option(REXI_ENABLE_TESTING "Build unit and integration test suites" ON)
option(REXI_ENABLE_BENCHMARKS "Build performance benchmark targets" ON)
option(REXI_ENABLE_WARNINGS_AS_ERRORS "Treat compiler warnings as errors" OFF)

# Platform / Toolchain Status Reporting
message(STATUS "--------------------------------------------------")
message(STATUS "Configuring ${PROJECT_NAME} v${PROJECT_VERSION}")
message(STATUS "Host System:    ${CMAKE_SYSTEM_NAME} (${CMAKE_SYSTEM_PROCESSOR})")
message(STATUS "C++ Compiler:   ${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}")
message(STATUS "Build Type:     ${CMAKE_BUILD_TYPE}")
message(STATUS "Testing Target: ${REXI_ENABLE_TESTING}")
message(STATUS "Benchmarks:     ${REXI_ENABLE_BENCHMARKS}")
message(STATUS "--------------------------------------------------")

# FetchContent for Dependencies
include(FetchContent)

# ------------------------------------------------------------------------------
# GoogleTest Integration
# ------------------------------------------------------------------------------
if(REXI_ENABLE_TESTING)
    enable_testing()
    FetchContent_Declare(
        googletest
        GIT_REPOSITORY https://github.com/google/googletest.git
        GIT_TAG v1.14.0
        GIT_SHALLOW TRUE
    )
    # Prevent installation of GoogleTest targets
    set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
    set(BUILD_GMOCK OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(googletest)
endif()

# ------------------------------------------------------------------------------
# Google Benchmark Integration
# ------------------------------------------------------------------------------
if(REXI_ENABLE_BENCHMARKS)
    FetchContent_Declare(
        googlebenchmark
        GIT_REPOSITORY https://github.com/google/benchmark.git
        GIT_TAG v1.8.3
        GIT_SHALLOW TRUE
    )
    set(BENCHMARK_ENABLE_TESTING OFF CACHE BOOL "" FORCE)
    set(BENCHMARK_ENABLE_INSTALL OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(googlebenchmark)
endif()

# ------------------------------------------------------------------------------
# Subdirectories
# ------------------------------------------------------------------------------
add_subdirectory(core)

if(REXI_ENABLE_TESTING)
    add_subdirectory(tests)
endif()

if(REXI_ENABLE_BENCHMARKS)
    add_subdirectory(benchmarks)
endif()
