cmake_minimum_required(VERSION 3.22)

# ==============================================================================
# REXI — Real-time EXecution & Intelligence
# Root CMake Configuration (Phase 00 Foundation)
# ==============================================================================

project(REXI
    VERSION 0.1.0
    DESCRIPTION "High-frequency quantitative research and execution platform"
    LANGUAGES CXX
)

# Standard C++ Standard Definition
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Export compile commands for language server support (clangd, clang-tidy)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Platform / Architecture Detection
message(STATUS "Configuring REXI v${PROJECT_VERSION}")
message(STATUS "Target System: ${CMAKE_SYSTEM_NAME} (${CMAKE_SYSTEM_PROCESSOR})")
message(STATUS "Compiler: ${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}")

# Compiler Flags & Sanitizers Setup (Prepared for Phase 01+)
if (CMAKE_CXX_COMPILER_ID MATCHES "Clang|AppleClang|GNU")
    add_compile_options(
        -Wall
        -Wextra
        -Wpedantic
        -Wconversion
        -Wsign-conversion
        -Wshadow
        -Wnon-virtual-dtor
    )
endif()

# Build Options
option(REXI_ENABLE_TESTING "Enable unit and integration test targets" ON)
option(REXI_ENABLE_BENCHMARKS "Enable performance benchmark targets" ON)
option(REXI_BUILD_DOCS "Enable documentation generation targets" OFF)

# Subdirectories will be enabled in subsequent phases as components are introduced
# add_subdirectory(core)
# add_subdirectory(simulator)
# add_subdirectory(infrastructure)
# add_subdirectory(tests)
# add_subdirectory(benchmarks)
