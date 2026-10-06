#pragma once

#include <atomic>
#include <cstddef>

namespace rexi::test {

extern std::atomic<size_t> g_alloc_count;
extern std::atomic<bool> g_track_allocations;

/**
 * @brief RAII guard to track heap allocations during steady-state test execution.
 */
class ScopedAllocationGuard {
public:
    ScopedAllocationGuard();
    ~ScopedAllocationGuard();

    [[nodiscard]] size_t allocations() const noexcept;
};

}  // namespace rexi::test
