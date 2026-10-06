#include "rexi/version.hpp"

#include <benchmark/benchmark.h>

namespace rexi::benchmarks {

static void BM_VersionAccess(benchmark::State& state) {
    for (auto state_iter : state) {
        auto ver = rexi::get_version();
        benchmark::DoNotOptimize(ver);
    }
}
BENCHMARK(BM_VersionAccess);

static void BM_VersionStringAccess(benchmark::State& state) {
    for (auto state_iter : state) {
        auto str = rexi::get_version_string();
        benchmark::DoNotOptimize(str);
    }
}
BENCHMARK(BM_VersionStringAccess);

}  // namespace rexi::benchmarks

BENCHMARK_MAIN();
