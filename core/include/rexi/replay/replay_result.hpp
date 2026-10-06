#pragma once

#include "rexi/market_data/types.hpp"
#include "rexi/order_book/order_book.hpp"
#include "rexi/order_book/types.hpp"
#include "rexi/replay/replay_clock.hpp"

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace rexi::replay {

/**
 * @brief Structured diagnostic record for rejected or anomalous replay events.
 */
struct ReplayDiagnostic {
    uint64_t event_index{0};
    market_data::SequenceNumber sequence_num{0};
    market_data::Timestamp timestamp_ns{0};
    market_data::InstrumentId instrument_id{0};
    market_data::MarketDataMessageType message_type{market_data::MarketDataMessageType::Unknown};
    std::string reason;
    market_data::ValidationStatus validation_status{market_data::ValidationStatus::Valid};
    market_data::SequenceStatus sequence_status{market_data::SequenceStatus::Expected};
    market_data::ChecksumStatus checksum_status{market_data::ChecksumStatus::Valid};
    order_book::OrderBookStatus book_status{order_book::OrderBookStatus::Success};
};

/**
 * @brief Deterministic execution statistics gathered during historical replay.
 *
 * NOTE: Historical elapsed time is strictly decoupled from host machine wall time.
 */
struct ReplayStatistics {
    uint64_t events_read{0};
    uint64_t events_processed{0};
    uint64_t events_rejected{0};
    uint64_t sequence_gaps{0};
    uint64_t duplicates{0};
    uint64_t out_of_order{0};
    uint64_t validation_failures{0};
    uint64_t checksum_failures{0};
    uint64_t snapshots_applied{0};
    uint64_t book_updates{0};
    uint64_t trades_observed{0};
    market_data::Timestamp first_timestamp_ns{0};
    market_data::Timestamp last_timestamp_ns{0};
    uint64_t elapsed_replay_time_ns{0};

    /// Host wall-clock execution duration in nanoseconds (for benchmark reporting only)
    uint64_t wall_time_ns{0};
};

/**
 * @brief 64-bit FNV-1a hash combiner for deterministic state digest generation.
 */
class DeterministicStateHasher {
public:
    static constexpr uint64_t Fnv64OffsetBasis = 0xcbf29ce484222325ULL;
    static constexpr uint64_t Fnv64Prime = 0x100000001b3ULL;

    constexpr DeterministicStateHasher() noexcept : hash_(Fnv64OffsetBasis) {}

    constexpr void add_u64(uint64_t val) noexcept {
        hash_ ^= val;
        hash_ *= Fnv64Prime;
    }

    constexpr void add_i64(int64_t val) noexcept { add_u64(static_cast<uint64_t>(val)); }

    [[nodiscard]] constexpr uint64_t digest() const noexcept { return hash_; }

private:
    uint64_t hash_{Fnv64OffsetBasis};
};

/**
 * @brief Compute a deterministic 64-bit state digest across the order book and replay state.
 *
 * Traverses price levels and resting orders in canonical sorted FIFO order, ensuring
 * identical states across independent executions yield identical hashes.
 */
[[nodiscard]] inline uint64_t compute_state_digest(const order_book::OrderBook& book,
                                                   const ReplayClock& clock,
                                                   const ReplayStatistics& stats) noexcept {
    DeterministicStateHasher hasher;

    // 1. Core instrument and clock metadata
    hasher.add_u64(book.instrument_id());
    hasher.add_u64(clock.event_index());
    hasher.add_u64(clock.current_time_ns());
    hasher.add_u64(stats.events_processed);

    // 2. Best quotes
    auto bbo = book.top_quote();
    hasher.add_i64(bbo.bid_price.value_or(0));
    hasher.add_u64(bbo.bid_quantity);
    hasher.add_i64(bbo.ask_price.value_or(0));
    hasher.add_u64(bbo.ask_quantity);
    hasher.add_u64(book.order_count());

    // 3. Complete canonical L3 order book state
    auto l3_snap = book.to_l3_snapshot();
    hasher.add_u64(l3_snap.orders.size());
    for (const auto& ord : l3_snap.orders) {
        hasher.add_u64(ord.order_id);
        hasher.add_u64(static_cast<uint64_t>(ord.side));
        hasher.add_i64(ord.price);
        hasher.add_u64(ord.remaining_quantity);
        hasher.add_u64(ord.priority_seq);
    }

    return hasher.digest();
}

/**
 * @brief Comprehensive summary of a completed historical replay session.
 */
struct ReplayResult {
    ReplayStatistics stats{};
    uint64_t state_digest{0};
    std::vector<ReplayDiagnostic> diagnostics{};
    std::optional<order_book::Price> best_bid_price{std::nullopt};
    order_book::Quantity best_bid_quantity{0};
    std::optional<order_book::Price> best_ask_price{std::nullopt};
    order_book::Quantity best_ask_quantity{0};
    size_t total_orders{0};
    size_t bid_levels{0};
    size_t ask_levels{0};
    bool is_clean{true};
};

}  // namespace rexi::replay
