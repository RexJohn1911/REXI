#pragma once

#include "rexi/market_data/types.hpp"

#include <cstdint>

namespace rexi::replay {

/**
 * @brief Zero-wall-clock deterministic historical replay clock.
 *
 * Decoupled entirely from system and steady clocks to ensure 100% reproducible
 * historical simulation and test executions.
 */
class ReplayClock {
public:
    explicit constexpr ReplayClock(market_data::Timestamp initial_time_ns = 0) noexcept
        : current_time_ns_(initial_time_ns),
          previous_time_ns_(initial_time_ns),
          first_time_ns_(initial_time_ns),
          started_(initial_time_ns > 0) {}

    /**
     * @brief Advance clock to a specific historical timestamp.
     *
     * @param new_ts Incoming historical event timestamp in nanoseconds.
     */
    constexpr void advance_to(market_data::Timestamp new_ts) noexcept {
        if (!started_) {
            first_time_ns_ = new_ts;
            current_time_ns_ = new_ts;
            previous_time_ns_ = new_ts;
            started_ = true;
        } else {
            previous_time_ns_ = current_time_ns_;
            current_time_ns_ = new_ts;
        }
        ++event_index_;
    }

    /**
     * @brief Advance clock by a relative delta.
     */
    constexpr void advance_by(uint64_t delta_ns) noexcept {
        if (!started_) {
            first_time_ns_ = delta_ns;
            current_time_ns_ = delta_ns;
            previous_time_ns_ = 0;
            started_ = true;
        } else {
            previous_time_ns_ = current_time_ns_;
            current_time_ns_ += delta_ns;
        }
        ++event_index_;
    }

    /**
     * @brief Reset clock state.
     */
    constexpr void reset(market_data::Timestamp initial_time_ns = 0) noexcept {
        current_time_ns_ = initial_time_ns;
        previous_time_ns_ = initial_time_ns;
        first_time_ns_ = initial_time_ns;
        event_index_ = 0;
        started_ = (initial_time_ns > 0);
    }

    [[nodiscard]] constexpr market_data::Timestamp now_ns() const noexcept {
        return current_time_ns_;
    }

    [[nodiscard]] constexpr market_data::Timestamp current_time_ns() const noexcept {
        return current_time_ns_;
    }

    [[nodiscard]] constexpr market_data::Timestamp previous_time_ns() const noexcept {
        return previous_time_ns_;
    }

    [[nodiscard]] constexpr market_data::Timestamp first_time_ns() const noexcept {
        return first_time_ns_;
    }

    [[nodiscard]] constexpr uint64_t event_index() const noexcept { return event_index_; }

    [[nodiscard]] constexpr bool is_started() const noexcept { return started_; }

    [[nodiscard]] constexpr uint64_t elapsed_replay_time_ns() const noexcept {
        if (!started_ || current_time_ns_ < first_time_ns_) {
            return 0;
        }
        return current_time_ns_ - first_time_ns_;
    }

private:
    market_data::Timestamp current_time_ns_{0};
    market_data::Timestamp previous_time_ns_{0};
    market_data::Timestamp first_time_ns_{0};
    uint64_t event_index_{0};
    bool started_{false};
};

}  // namespace rexi::replay
