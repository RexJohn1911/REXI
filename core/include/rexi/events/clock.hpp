#pragma once

#include <chrono>
#include <cstdint>

namespace rexi::events {

/**
 * @brief High-resolution nanosecond timestamp count.
 */
using TimestampNs = uint64_t;

/**
 * @brief Zero-allocation monotonic clock provider for internal event metadata.
 */
class MonotonicClock {
public:
    /**
     * @brief Get the current monotonic timestamp in nanoseconds since epoch.
     */
    [[nodiscard]] static TimestampNs now_ns() noexcept {
        const auto now = std::chrono::steady_clock::now();
        return static_cast<TimestampNs>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count());
    }
};

}  // namespace rexi::events
