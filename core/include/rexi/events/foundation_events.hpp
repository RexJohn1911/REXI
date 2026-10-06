#pragma once

#include "rexi/events/event.hpp"

#include <cstdint>

namespace rexi::events {

/**
 * @brief Periodic timer tick event payload.
 */
struct alignas(8) TimerTickPayload {
    uint64_t tick_id{0};
    uint64_t interval_ns{0};
};

template <>
struct EventTraits<TimerTickPayload> {
    static constexpr EventType type = EventType::TimerTick;
    static constexpr std::string_view name = "TimerTick";
};

using TimerTickEvent = Event<TimerTickPayload>;

/**
 * @brief Subsystem heartbeat event payload.
 */
struct alignas(8) HeartbeatPayload {
    uint64_t sequence{0};
    uint32_t component_id{0};
    uint32_t status_flags{0};
};

template <>
struct EventTraits<HeartbeatPayload> {
    static constexpr EventType type = EventType::Heartbeat;
    static constexpr std::string_view name = "Heartbeat";
};

using HeartbeatEvent = Event<HeartbeatPayload>;

/**
 * @brief System status update event payload.
 */
struct alignas(8) SystemStatusPayload {
    uint32_t status_code{0};
    uint32_t error_code{0};
    uint64_t status_detail{0};
};

template <>
struct EventTraits<SystemStatusPayload> {
    static constexpr EventType type = EventType::SystemStatus;
    static constexpr std::string_view name = "SystemStatus";
};

using SystemStatusEvent = Event<SystemStatusPayload>;

/**
 * @brief Generic test event payload for verification and stress testing.
 */
struct alignas(8) TestEventPayload {
    uint64_t value_a{0};
    uint64_t value_b{0};
    uint64_t value_c{0};
};

template <>
struct EventTraits<TestEventPayload> {
    static constexpr EventType type = EventType::TestEvent;
    static constexpr std::string_view name = "TestEvent";
};

using TestEvent = Event<TestEventPayload>;

}  // namespace rexi::events
