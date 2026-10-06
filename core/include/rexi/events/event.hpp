#pragma once

#include "rexi/events/event_header.hpp"

#include <concepts>
#include <type_traits>

namespace rexi::events {

/**
 * @brief Compile-time traits template associating payload structs with EventType.
 */
template <typename Payload>
struct EventTraits;

/**
 * @brief Strongly typed event message container with explicit header and payload.
 *
 * Enforces trivial copyability for zero-allocation cache-friendly transport.
 */
template <typename Payload>
struct alignas(8) Event {
    static_assert(std::is_trivially_copyable_v<Payload>,
                  "Event payload must be trivially copyable for deterministic low-allocation "
                  "transport");
    static_assert(std::is_standard_layout_v<Payload>, "Event payload must have standard layout");

    EventHeader header{};
    Payload payload{};
};

/**
 * @brief Helper factory to construct a strongly typed Event<Payload>.
 */
template <typename Payload>
[[nodiscard]] inline Event<Payload> make_event(
    const Payload& payload, SourceId source = SourceId::Internal, uint64_t sequence = 0,
    uint32_t flags = 0, TimestampNs timestamp = MonotonicClock::now_ns()) noexcept {
    constexpr EventType event_type = EventTraits<Payload>::type;
    return Event<Payload>{
        .header = make_header(event_type, source, sequence, flags, timestamp),
        .payload = payload,
    };
}

}  // namespace rexi::events
