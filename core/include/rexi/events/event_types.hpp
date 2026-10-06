#pragma once

#include <cstdint>
#include <string_view>

namespace rexi::events {

/**
 * @brief Strongly typed event identifier for deterministic dispatching.
 *
 * Underlying uint16_t enables high-performance direct table indexing without
 * string parsing or runtime reflection.
 */
enum class EventType : uint16_t {
    Unknown = 0,
    TimerTick = 1,
    Heartbeat = 2,
    SystemStatus = 3,
    TestEvent = 4,
    CustomBase = 100
};

/**
 * @brief Convert EventType to string representation for logging and diagnostics.
 */
[[nodiscard]] constexpr std::string_view to_string(EventType type) noexcept {
    switch (type) {
        case EventType::Unknown:
            return "Unknown";
        case EventType::TimerTick:
            return "TimerTick";
        case EventType::Heartbeat:
            return "Heartbeat";
        case EventType::SystemStatus:
            return "SystemStatus";
        case EventType::TestEvent:
            return "TestEvent";
        case EventType::CustomBase:
            return "CustomBase";
    }
    return "InvalidEventType";
}

}  // namespace rexi::events
