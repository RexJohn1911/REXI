# ==============================================================================
# REXI Performance Benchmark Targets
# ==============================================================================

add_executable(rexi_benchmarks
    benchmark_foundation.cpp
    benchmark_events.cpp
    benchmark_simulator.cpp
    benchmark_market_data.cpp
)

target_link_libraries(rexi_benchmarks PRIVATE
    rexi_core
    rexi_simulator
    benchmark::benchmark
)

target_compile_features(rexi_benchmarks PRIVATE cxx_std_20)

if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|AppleClang|GNU")
    target_compile_options(rexi_benchmarks PRIVATE
        -Wall
        -Wextra
        -Wpedantic
        -Wconversion
        -Wsign-conversion
        -Wshadow
        -Wnon-virtual-dtor
    )
endif()
