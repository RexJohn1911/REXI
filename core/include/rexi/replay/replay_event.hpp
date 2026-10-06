#pragma once

#include "rexi/events/event_types.hpp"
#include "rexi/events/source_id.hpp"
#include "rexi/market_data/message_header.hpp"
#include "rexi/market_data/messages.hpp"
#include "rexi/market_data/types.hpp"

#include <cstdint>
#include <string_view>
#include <type_traits>
#include <variant>

namespace rexi::replay {

/**
 * @brief Tagged variant over all canonical Phase 04 market-data message payloads.
 *
 * Trivially copyable, bounded size, zero heap allocations.
 */
using ReplayPayload =
    std::variant<std::monostate, market_data::InstrumentDefinitionMessage,
                 market_data::TopOfBookMessage, market_data::TradeMessage,
                 market_data::OrderBookAddMessage, market_data::OrderBookModifyMessage,
                 market_data::OrderBookDeleteMessage, market_data::OrderBookSnapshotMessage,
                 market_data::MarketStatusMessage>;

static_assert(std::is_trivially_copyable_v<ReplayPayload>,
              "ReplayPayload variant must be trivially copyable for zero-allocation replay");

/**
 * @brief Canonical historical replay record envelope.
 *
 * Encapsulates the canonical Phase 04 MarketDataHeader, the typed message payload,
 * source provenance, and an invariant input index for deterministic tie-breaking.
 */
struct alignas(8) ReplayEvent {
    market_data::MarketDataHeader header{};
    events::SourceId source{events::SourceId::Internal};
    uint64_t input_index{0};
    ReplayPayload payload{std::monostate{}};

    [[nodiscard]] constexpr market_data::MarketDataMessageType message_type() const noexcept {
        return header.message_type;
    }

    [[nodiscard]] constexpr market_data::InstrumentId instrument_id() const noexcept {
        return header.instrument_id;
    }

    [[nodiscard]] constexpr market_data::VenueId venue_id() const noexcept {
        return header.venue_id;
    }

    [[nodiscard]] constexpr market_data::FeedId feed_id() const noexcept { return header.feed_id; }

    [[nodiscard]] constexpr market_data::SequenceNumber sequence_num() const noexcept {
        return header.sequence_num;
    }

    [[nodiscard]] constexpr market_data::Timestamp source_timestamp_ns() const noexcept {
        return header.source_timestamp_ns;
    }

    [[nodiscard]] constexpr market_data::Timestamp receive_timestamp_ns() const noexcept {
        return header.receive_timestamp_ns;
    }

    [[nodiscard]] constexpr uint32_t checksum() const noexcept { return header.checksum; }

    [[nodiscard]] constexpr uint16_t version() const noexcept { return header.version; }

    template <typename T>
    [[nodiscard]] constexpr bool is() const noexcept {
        return std::holds_alternative<T>(payload);
    }

    template <typename T>
    [[nodiscard]] const T& get() const {
        return std::get<T>(payload);
    }

    template <typename T>
    [[nodiscard]] const T* get_if() const noexcept {
        return std::get_if<T>(&payload);
    }
};

static_assert(std::is_trivially_copyable_v<ReplayEvent>, "ReplayEvent must be trivially copyable");

/**
 * @brief Canonical strict total ordering comparator for historical replay events.
 *
 * Enforces total ordering contract:
 * 1. Monotonic sequence number for matching feed (venue_id, feed_id) when sequence > 0
 * 2. Source timestamp (historical exchange time)
 * 3. Receive timestamp (gateway arrival time)
 * 4. Venue ID & Feed ID tie-breakers
 * 5. Sequence number tie-breaker
 * 6. Stable input index fallback for bit-for-bit reproducible tie-breaking
 */
struct ReplayEventComparator {
    constexpr bool operator()(const ReplayEvent& lhs, const ReplayEvent& rhs) const noexcept {
        // 1. Authoritative feed sequence continuity
        if (lhs.header.venue_id == rhs.header.venue_id &&
            lhs.header.feed_id == rhs.header.feed_id && lhs.header.sequence_num > 0 &&
            rhs.header.sequence_num > 0) {
            if (lhs.header.sequence_num != rhs.header.sequence_num) {
                return lhs.header.sequence_num < rhs.header.sequence_num;
            }
        }

        // 2. Source timestamp
        if (lhs.header.source_timestamp_ns != rhs.header.source_timestamp_ns) {
            return lhs.header.source_timestamp_ns < rhs.header.source_timestamp_ns;
        }

        // 3. Receive timestamp
        if (lhs.header.receive_timestamp_ns != rhs.header.receive_timestamp_ns) {
            return lhs.header.receive_timestamp_ns < rhs.header.receive_timestamp_ns;
        }

        // 4. Feed identifiers
        if (lhs.header.venue_id != rhs.header.venue_id) {
            return lhs.header.venue_id < rhs.header.venue_id;
        }
        if (lhs.header.feed_id != rhs.header.feed_id) {
            return lhs.header.feed_id < rhs.header.feed_id;
        }
        if (lhs.header.sequence_num != rhs.header.sequence_num) {
            return lhs.header.sequence_num < rhs.header.sequence_num;
        }

        // 5. Stable input index as final deterministic tie-breaker
        return lhs.input_index < rhs.input_index;
    }
};

[[nodiscard]] constexpr bool operator<(const ReplayEvent& lhs, const ReplayEvent& rhs) noexcept {
    return ReplayEventComparator{}(lhs, rhs);
}

// -----------------------------------------------------------------------------
// Canonical Factory Helpers
// -----------------------------------------------------------------------------

[[nodiscard]] inline ReplayEvent make_replay_add(
    const market_data::MarketDataHeader& header, const market_data::OrderBookAddMessage& msg,
    uint64_t input_index = 0, events::SourceId source = events::SourceId::Internal) noexcept {
    return ReplayEvent{
        .header = header,
        .source = source,
        .input_index = input_index,
        .payload = msg,
    };
}

[[nodiscard]] inline ReplayEvent make_replay_modify(
    const market_data::MarketDataHeader& header, const market_data::OrderBookModifyMessage& msg,
    uint64_t input_index = 0, events::SourceId source = events::SourceId::Internal) noexcept {
    return ReplayEvent{
        .header = header,
        .source = source,
        .input_index = input_index,
        .payload = msg,
    };
}

[[nodiscard]] inline ReplayEvent make_replay_delete(
    const market_data::MarketDataHeader& header, const market_data::OrderBookDeleteMessage& msg,
    uint64_t input_index = 0, events::SourceId source = events::SourceId::Internal) noexcept {
    return ReplayEvent{
        .header = header,
        .source = source,
        .input_index = input_index,
        .payload = msg,
    };
}

[[nodiscard]] inline ReplayEvent make_replay_snapshot(
    const market_data::MarketDataHeader& header, const market_data::OrderBookSnapshotMessage& msg,
    uint64_t input_index = 0, events::SourceId source = events::SourceId::Internal) noexcept {
    return ReplayEvent{
        .header = header,
        .source = source,
        .input_index = input_index,
        .payload = msg,
    };
}

[[nodiscard]] inline ReplayEvent make_replay_trade(
    const market_data::MarketDataHeader& header, const market_data::TradeMessage& msg,
    uint64_t input_index = 0, events::SourceId source = events::SourceId::Internal) noexcept {
    return ReplayEvent{
        .header = header,
        .source = source,
        .input_index = input_index,
        .payload = msg,
    };
}

[[nodiscard]] inline ReplayEvent make_replay_top_of_book(
    const market_data::MarketDataHeader& header, const market_data::TopOfBookMessage& msg,
    uint64_t input_index = 0, events::SourceId source = events::SourceId::Internal) noexcept {
    return ReplayEvent{
        .header = header,
        .source = source,
        .input_index = input_index,
        .payload = msg,
    };
}

[[nodiscard]] inline ReplayEvent make_replay_status(
    const market_data::MarketDataHeader& header, const market_data::MarketStatusMessage& msg,
    uint64_t input_index = 0, events::SourceId source = events::SourceId::Internal) noexcept {
    return ReplayEvent{
        .header = header,
        .source = source,
        .input_index = input_index,
        .payload = msg,
    };
}

[[nodiscard]] inline ReplayEvent make_replay_instrument(
    const market_data::MarketDataHeader& header,
    const market_data::InstrumentDefinitionMessage& msg, uint64_t input_index = 0,
    events::SourceId source = events::SourceId::Internal) noexcept {
    return ReplayEvent{
        .header = header,
        .source = source,
        .input_index = input_index,
        .payload = msg,
    };
}

}  // namespace rexi::replay
