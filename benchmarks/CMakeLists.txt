# ==============================================================================
# REXI Performance Benchmark Targets
# ==============================================================================

add_executable(rexi_benchmarks
    benchmark_foundation.cpp
)

target_link_libraries(rexi_benchmarks PRIVATE
    rexi_core
    benchmark::benchmark
)

target_compile_features(rexi_benchmarks PRIVATE cxx_std_20)
