#pragma once

#include "rexi/market_data/types.hpp"

#include <cstdint>
#include <type_traits>

namespace rexi::market_data {

/**
 * @brief Standardized 40-byte compact market data message header.
 *
 * Aligned to 8 bytes, trivially copyable, cache-line conscious.
 */
struct alignas(8) MarketDataHeader {
    std::uint16_t version{CurrentProtocolVersion};
    MarketDataMessageType message_type{MarketDataMessageType::Unknown};
    std::uint8_t flags{0};
    VenueId venue_id{0};
    FeedId feed_id{0};
    InstrumentId instrument_id{0};
    std::uint32_t checksum{0};
    SequenceNumber sequence_num{0};
    Timestamp source_timestamp_ns{0};
    Timestamp receive_timestamp_ns{0};
};

static_assert(sizeof(MarketDataHeader) == 40, "MarketDataHeader must be exactly 40 bytes");
static_assert(std::is_trivially_copyable_v<MarketDataHeader>,
              "MarketDataHeader must be trivially copyable for zero-allocation transport");
static_assert(std::is_standard_layout_v<MarketDataHeader>,
              "MarketDataHeader must have standard layout");

[[nodiscard]] constexpr MarketDataHeader make_md_header(
    MarketDataMessageType type, InstrumentId instrument_id = 0, VenueId venue_id = 0,
    FeedId feed_id = 0, SequenceNumber seq = 0, Timestamp source_ts = 0, Timestamp recv_ts = 0,
    std::uint32_t flags = 0, std::uint32_t checksum = 0,
    std::uint16_t version = CurrentProtocolVersion) noexcept {
    return MarketDataHeader{
        .version = version,
        .message_type = type,
        .flags = static_cast<std::uint8_t>(flags & 0xFF),
        .venue_id = venue_id,
        .feed_id = feed_id,
        .instrument_id = instrument_id,
        .checksum = checksum,
        .sequence_num = seq,
        .source_timestamp_ns = source_ts,
        .receive_timestamp_ns = recv_ts,
    };
}

}  // namespace rexi::market_data
