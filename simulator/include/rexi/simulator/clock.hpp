#pragma once

#include <cstdint>

namespace rexi::simulator {

/**
 * @brief Deterministic, explicitly controlled simulator clock.
 *
 * Decoupled from wall-clock / steady_clock to guarantee 100% reproducible execution
 * and historical replay capability.
 */
class SimulationClock {
public:
    explicit constexpr SimulationClock(uint64_t initial_time_ns = 0) noexcept
        : current_time_ns_(initial_time_ns) {}

    [[nodiscard]] constexpr uint64_t now_ns() const noexcept { return current_time_ns_; }

    constexpr void advance_by_ns(uint64_t delta_ns) noexcept { current_time_ns_ += delta_ns; }

    constexpr void set_time_ns(uint64_t new_time_ns) noexcept { current_time_ns_ = new_time_ns; }

    constexpr void reset(uint64_t initial_time_ns = 0) noexcept {
        current_time_ns_ = initial_time_ns;
    }

private:
    uint64_t current_time_ns_{0};
};

}  // namespace rexi::simulator
