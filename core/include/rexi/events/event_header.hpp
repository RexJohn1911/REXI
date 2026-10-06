#pragma once

#include "rexi/events/clock.hpp"
#include "rexi/events/event_types.hpp"
#include "rexi/events/source_id.hpp"

#include <cstdint>
#include <type_traits>

namespace rexi::events {

/**
 * @brief Standardized 24-byte event header for all REXI message envelopes.
 *
 * Designed to fit within a single CPU cache line, aligned to 8 bytes.
 */
struct alignas(8) EventHeader {
    EventType type{EventType::Unknown};
    SourceId source{SourceId::Unknown};
    uint32_t flags{0};
    uint64_t sequence_num{0};
    TimestampNs timestamp_ns{0};
};

static_assert(sizeof(EventHeader) == 24, "EventHeader must be exactly 24 bytes");
static_assert(std::is_trivially_copyable_v<EventHeader>, "EventHeader must be trivially copyable");
static_assert(std::is_standard_layout_v<EventHeader>, "EventHeader must have standard layout");

/**
 * @brief Factory helper to construct a timestamped EventHeader.
 */
[[nodiscard]] inline EventHeader make_header(EventType type, SourceId source = SourceId::Internal,
                                             uint64_t sequence = 0, uint32_t flags = 0,
                                             TimestampNs ts = MonotonicClock::now_ns()) noexcept {
    return EventHeader{
        .type = type,
        .source = source,
        .flags = flags,
        .sequence_num = sequence,
        .timestamp_ns = ts,
    };
}

}  // namespace rexi::events
