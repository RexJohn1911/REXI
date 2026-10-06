#pragma once

#include "rexi/market_data/checksum.hpp"
#include "rexi/market_data/message_header.hpp"
#include "rexi/market_data/messages.hpp"
#include "rexi/market_data/types.hpp"
#include "rexi/replay/replay_event.hpp"

#include <cstdint>
#include <vector>

namespace rexi::replay {

/**
 * @brief Deterministic, fixed-seed pseudo-random generator for synthetic test streams.
 */
class DeterministicPrng {
public:
    explicit constexpr DeterministicPrng(uint64_t seed = 0x853c49e6748fea9bULL) noexcept
        : state_(seed) {}

    constexpr uint64_t next_u64() noexcept {
        uint64_t z = (state_ += 0x9e3779b97f4a7c15ULL);
        z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
        z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
        return z ^ (z >> 31);
    }

    constexpr uint64_t uniform_u64(uint64_t min_val, uint64_t max_val) noexcept {
        if (min_val >= max_val) {
            return min_val;
        }
        return min_val + (next_u64() % (max_val - min_val + 1));
    }

private:
    uint64_t state_{0};
};

/**
 * @brief Factory for deterministic synthetic market data replay test fixtures.
 */
class SyntheticReplayFixtureGenerator {
public:
    /**
     * @brief Basic clean L3 order lifecycle stream: adds, modifies, deletes, trades.
     */
    static std::vector<ReplayEvent> create_basic_l3_stream(market_data::InstrumentId inst_id = 100,
                                                           market_data::VenueId venue = 1,
                                                           market_data::FeedId feed = 1) {
        std::vector<ReplayEvent> events;
        events.reserve(20);

        market_data::SequenceNumber seq = 1;
        market_data::Timestamp ts = 1'000'000'000ULL;  // 1 second
        uint64_t idx = 0;

        // 1. Five bids at prices 100, 99, 98
        for (uint64_t id = 1; id <= 5; ++id) {
            market_data::Price p = 100 - static_cast<market_data::Price>((id - 1) / 2);
            market_data::Quantity q = id * 10;
            auto hdr = market_data::make_md_header(market_data::MarketDataMessageType::OrderBookAdd,
                                                   inst_id, venue, feed, seq++, ts, ts);
            market_data::OrderBookAddMessage msg{
                .order_id = id,
                .side = market_data::MarketSide::Buy,
                .price = p,
                .quantity = q,
            };
            events.push_back(make_replay_add(hdr, msg, idx++));
            ts += 10'000ULL;
        }

        // 2. Five asks at prices 105, 106, 107
        for (uint64_t id = 6; id <= 10; ++id) {
            market_data::Price p = 105 + static_cast<market_data::Price>((id - 6) / 2);
            market_data::Quantity q = (id - 5) * 10;
            auto hdr = market_data::make_md_header(market_data::MarketDataMessageType::OrderBookAdd,
                                                   inst_id, venue, feed, seq++, ts, ts);
            market_data::OrderBookAddMessage msg{
                .order_id = id,
                .side = market_data::MarketSide::Sell,
                .price = p,
                .quantity = q,
            };
            events.push_back(make_replay_add(hdr, msg, idx++));
            ts += 10'000ULL;
        }

        // 3. Modify bid order 1 (reduce qty from 10 to 5)
        {
            auto hdr =
                market_data::make_md_header(market_data::MarketDataMessageType::OrderBookModify,
                                            inst_id, venue, feed, seq++, ts, ts);
            market_data::OrderBookModifyMessage msg{
                .order_id = 1,
                .side = market_data::MarketSide::Buy,
                .price = 100,
                .new_quantity = 5,
                .delta_quantity = 5,
            };
            events.push_back(make_replay_modify(hdr, msg, idx++));
            ts += 10'000ULL;
        }

        // 4. Cancel ask order 6
        {
            auto hdr =
                market_data::make_md_header(market_data::MarketDataMessageType::OrderBookDelete,
                                            inst_id, venue, feed, seq++, ts, ts);
            market_data::OrderBookDeleteMessage msg{
                .order_id = 6,
                .side = market_data::MarketSide::Sell,
                .price = 105,
                .cancelled_quantity = 10,
            };
            events.push_back(make_replay_delete(hdr, msg, idx++));
            ts += 10'000ULL;
        }

        // 5. Public Trade
        {
            auto hdr = market_data::make_md_header(market_data::MarketDataMessageType::Trade,
                                                   inst_id, venue, feed, seq++, ts, ts);
            market_data::TradeMessage msg{
                .trade_id = 501,
                .price = 105,
                .quantity = 10,
                .aggressor_side = market_data::MarketSide::Buy,
                .maker_order_id = 7,
                .taker_order_id = 999,
            };
            events.push_back(make_replay_trade(hdr, msg, idx++));
        }

        return events;
    }

    /**
     * @brief Initial snapshot followed by incremental updates.
     */
    static std::vector<ReplayEvent> create_snapshot_and_incremental_stream(
        market_data::InstrumentId inst_id = 100, market_data::VenueId venue = 1,
        market_data::FeedId feed = 1) {
        std::vector<ReplayEvent> events;
        uint64_t idx = 0;

        // 1. Initial snapshot with 3 bids and 3 asks, establishing baseline sequence = 100
        market_data::Timestamp ts = 2'000'000'000ULL;
        auto snap_hdr =
            market_data::make_md_header(market_data::MarketDataMessageType::OrderBookSnapshot,
                                        inst_id, venue, feed, 100, ts, ts);
        market_data::OrderBookSnapshotMessage snap_msg{};
        snap_msg.last_included_sequence = 100;
        snap_msg.bid_levels_count = 3;
        snap_msg.bids[0] =
            market_data::OrderBookSnapshotLevel{.price = 102, .quantity = 300, .order_count = 3};
        snap_msg.bids[1] =
            market_data::OrderBookSnapshotLevel{.price = 101, .quantity = 500, .order_count = 5};
        snap_msg.bids[2] =
            market_data::OrderBookSnapshotLevel{.price = 100, .quantity = 200, .order_count = 2};
        snap_msg.ask_levels_count = 3;
        snap_msg.asks[0] =
            market_data::OrderBookSnapshotLevel{.price = 105, .quantity = 400, .order_count = 4};
        snap_msg.asks[1] =
            market_data::OrderBookSnapshotLevel{.price = 106, .quantity = 600, .order_count = 6};
        snap_msg.asks[2] =
            market_data::OrderBookSnapshotLevel{.price = 107, .quantity = 800, .order_count = 8};
        events.push_back(make_replay_snapshot(snap_hdr, snap_msg, idx++));

        // 2. Incremental L3 updates continuing at sequence 101, 102
        ts += 50'000ULL;
        auto add1_hdr = market_data::make_md_header(
            market_data::MarketDataMessageType::OrderBookAdd, inst_id, venue, feed, 101, ts, ts);
        market_data::OrderBookAddMessage add1_msg{
            .order_id = 1001,
            .side = market_data::MarketSide::Buy,
            .price = 103,  // New best bid
            .quantity = 50,
        };
        events.push_back(make_replay_add(add1_hdr, add1_msg, idx++));

        ts += 50'000ULL;
        auto add2_hdr = market_data::make_md_header(
            market_data::MarketDataMessageType::OrderBookAdd, inst_id, venue, feed, 102, ts, ts);
        market_data::OrderBookAddMessage add2_msg{
            .order_id = 1002,
            .side = market_data::MarketSide::Sell,
            .price = 104,  // New best ask
            .quantity = 75,
        };
        events.push_back(make_replay_add(add2_hdr, add2_msg, idx++));

        return events;
    }

    /**
     * @brief Stream containing an intentional sequence gap (seq 1 followed by seq 5).
     */
    static std::vector<ReplayEvent> create_gapped_stream(market_data::InstrumentId inst_id = 100) {
        std::vector<ReplayEvent> events;
        market_data::Timestamp ts = 1'000'000'000ULL;

        auto hdr1 = market_data::make_md_header(market_data::MarketDataMessageType::OrderBookAdd,
                                                inst_id, 1, 1, 1, ts, ts);
        market_data::OrderBookAddMessage msg1{
            .order_id = 1, .side = market_data::MarketSide::Buy, .price = 100, .quantity = 10};
        events.push_back(make_replay_add(hdr1, msg1, 0));

        ts += 10'000ULL;
        auto hdr2 = market_data::make_md_header(market_data::MarketDataMessageType::OrderBookAdd,
                                                inst_id, 1, 1, 5, ts, ts);  // GAP from 1 to 5
        market_data::OrderBookAddMessage msg2{
            .order_id = 2, .side = market_data::MarketSide::Buy, .price = 99, .quantity = 10};
        events.push_back(make_replay_add(hdr2, msg2, 1));

        return events;
    }

    /**
     * @brief Stream containing an intentional duplicate sequence number.
     */
    static std::vector<ReplayEvent> create_duplicate_stream(
        market_data::InstrumentId inst_id = 100) {
        std::vector<ReplayEvent> events;
        market_data::Timestamp ts = 1'000'000'000ULL;

        auto hdr1 = market_data::make_md_header(market_data::MarketDataMessageType::OrderBookAdd,
                                                inst_id, 1, 1, 1, ts, ts);
        market_data::OrderBookAddMessage msg1{
            .order_id = 1, .side = market_data::MarketSide::Buy, .price = 100, .quantity = 10};
        events.push_back(make_replay_add(hdr1, msg1, 0));

        ts += 10'000ULL;
        auto hdr2 = market_data::make_md_header(market_data::MarketDataMessageType::OrderBookAdd,
                                                inst_id, 1, 1, 2, ts, ts);
        market_data::OrderBookAddMessage msg2{
            .order_id = 2, .side = market_data::MarketSide::Buy, .price = 99, .quantity = 10};
        events.push_back(make_replay_add(hdr2, msg2, 1));

        ts += 10'000ULL;
        auto hdr3 = market_data::make_md_header(market_data::MarketDataMessageType::OrderBookAdd,
                                                inst_id, 1, 1, 2, ts, ts);  // Duplicate seq 2
        market_data::OrderBookAddMessage msg3{
            .order_id = 3, .side = market_data::MarketSide::Buy, .price = 98, .quantity = 10};
        events.push_back(make_replay_add(hdr3, msg3, 2));

        return events;
    }

    /**
     * @brief Stream containing an intentional out-of-order sequence number.
     */
    static std::vector<ReplayEvent> create_out_of_order_stream(
        market_data::InstrumentId inst_id = 100) {
        std::vector<ReplayEvent> events;
        market_data::Timestamp ts = 1'000'000'000ULL;

        auto hdr1 = market_data::make_md_header(market_data::MarketDataMessageType::OrderBookAdd,
                                                inst_id, 1, 1, 1, ts, ts);
        market_data::OrderBookAddMessage msg1{
            .order_id = 1, .side = market_data::MarketSide::Buy, .price = 100, .quantity = 10};
        events.push_back(make_replay_add(hdr1, msg1, 0));

        ts += 10'000ULL;
        auto hdr3 = market_data::make_md_header(market_data::MarketDataMessageType::OrderBookAdd,
                                                inst_id, 1, 1, 3, ts, ts);  // Jump to 3
        market_data::OrderBookAddMessage msg3{
            .order_id = 3, .side = market_data::MarketSide::Buy, .price = 98, .quantity = 10};
        events.push_back(make_replay_add(hdr3, msg3, 1));

        ts += 10'000ULL;
        auto hdr2 = market_data::make_md_header(market_data::MarketDataMessageType::OrderBookAdd,
                                                inst_id, 1, 1, 2, ts, ts);  // Out-of-order seq 2
        market_data::OrderBookAddMessage msg2{
            .order_id = 2, .side = market_data::MarketSide::Buy, .price = 99, .quantity = 10};
        events.push_back(make_replay_add(hdr2, msg2, 2));

        return events;
    }

    /**
     * @brief Stream containing an invalid payload (price <= 0).
     */
    static std::vector<ReplayEvent> create_invalid_event_stream(
        market_data::InstrumentId inst_id = 100) {
        std::vector<ReplayEvent> events;
        market_data::Timestamp ts = 1'000'000'000ULL;

        auto hdr1 = market_data::make_md_header(market_data::MarketDataMessageType::OrderBookAdd,
                                                inst_id, 1, 1, 1, ts, ts);
        market_data::OrderBookAddMessage msg1{
            .order_id = 1, .side = market_data::MarketSide::Buy, .price = 100, .quantity = 10};
        events.push_back(make_replay_add(hdr1, msg1, 0));

        ts += 10'000ULL;
        auto hdr2 = market_data::make_md_header(market_data::MarketDataMessageType::OrderBookAdd,
                                                inst_id, 1, 1, 2, ts, ts);
        market_data::OrderBookAddMessage msg2{.order_id = 2,
                                              .side = market_data::MarketSide::Buy,
                                              .price = 0,
                                              .quantity = 10};  // Invalid price 0
        events.push_back(make_replay_add(hdr2, msg2, 1));

        return events;
    }

    /**
     * @brief Stream containing an intentional checksum failure.
     */
    static std::vector<ReplayEvent> create_checksum_corrupted_stream(
        market_data::InstrumentId inst_id = 100) {
        std::vector<ReplayEvent> events;
        market_data::Timestamp ts = 1'000'000'000ULL;

        auto hdr = market_data::make_md_header(market_data::MarketDataMessageType::OrderBookAdd,
                                               inst_id, 1, 1, 1, ts, ts);
        hdr.checksum = 0xDEADBEEF;  // Corrupt checksum
        market_data::OrderBookAddMessage msg{
            .order_id = 1, .side = market_data::MarketSide::Buy, .price = 100, .quantity = 10};
        events.push_back(make_replay_add(hdr, msg, 0));

        return events;
    }

    /**
     * @brief Generate a deterministic large stream with thousands of events for stress and
     * benchmarking.
     */
    static std::vector<ReplayEvent> create_large_deterministic_stream(
        size_t count, uint64_t seed = 0xCAFEBABEDEADBEEFULL,
        market_data::InstrumentId inst_id = 100) {
        std::vector<ReplayEvent> events;
        events.reserve(count);

        DeterministicPrng prng(seed);
        market_data::SequenceNumber seq = 1;
        market_data::Timestamp ts = 1'000'000'000ULL;
        uint64_t order_id_counter = 1;
        std::vector<uint64_t> active_bids;
        std::vector<uint64_t> active_asks;
        active_bids.reserve(count / 2);
        active_asks.reserve(count / 2);

        for (size_t i = 0; i < count; ++i) {
            uint64_t action = prng.uniform_u64(0, 9);
            ts += prng.uniform_u64(1'000, 50'000);

            if (action <= 5 || (active_bids.empty() && active_asks.empty())) {
                // Add order
                const bool is_buy = (prng.next_u64() % 2 == 0);
                const uint64_t oid = order_id_counter++;
                const market_data::Price price =
                    is_buy ? static_cast<market_data::Price>(prng.uniform_u64(900, 999))
                           : static_cast<market_data::Price>(prng.uniform_u64(1001, 1100));
                const market_data::Quantity qty = prng.uniform_u64(10, 500);

                auto hdr = market_data::make_md_header(
                    market_data::MarketDataMessageType::OrderBookAdd, inst_id, 1, 1, seq++, ts, ts);
                market_data::OrderBookAddMessage msg{
                    .order_id = oid,
                    .side = is_buy ? market_data::MarketSide::Buy : market_data::MarketSide::Sell,
                    .price = price,
                    .quantity = qty,
                };
                events.push_back(make_replay_add(hdr, msg, i));

                if (is_buy) {
                    active_bids.push_back(oid);
                } else {
                    active_asks.push_back(oid);
                }
            } else if (action <= 7) {
                // Modify order (reduce)
                auto& list =
                    (prng.next_u64() % 2 == 0 && !active_bids.empty()) ? active_bids : active_asks;
                if (!list.empty()) {
                    size_t pos = prng.uniform_u64(0, list.size() - 1);
                    uint64_t oid = list[pos];
                    const bool is_b = (&list == &active_bids);
                    auto hdr = market_data::make_md_header(
                        market_data::MarketDataMessageType::OrderBookModify, inst_id, 1, 1, seq++,
                        ts, ts);
                    market_data::OrderBookModifyMessage msg{
                        .order_id = oid,
                        .side = is_b ? market_data::MarketSide::Buy : market_data::MarketSide::Sell,
                        .price = is_b ? static_cast<market_data::Price>(950)
                                      : static_cast<market_data::Price>(1050),
                        .new_quantity = 5,
                        .delta_quantity = 5,
                    };
                    events.push_back(make_replay_modify(hdr, msg, i));
                }
            } else {
                // Cancel order
                auto& list =
                    (prng.next_u64() % 2 == 0 && !active_bids.empty()) ? active_bids : active_asks;
                if (!list.empty()) {
                    size_t pos = prng.uniform_u64(0, list.size() - 1);
                    uint64_t oid = list[pos];
                    list[pos] = list.back();
                    list.pop_back();

                    auto hdr = market_data::make_md_header(
                        market_data::MarketDataMessageType::OrderBookDelete, inst_id, 1, 1, seq++,
                        ts, ts);
                    market_data::OrderBookDeleteMessage msg{
                        .order_id = oid,
                        .side = (&list == &active_bids) ? market_data::MarketSide::Buy
                                                        : market_data::MarketSide::Sell,
                        .price = 950,
                        .cancelled_quantity = 10,
                    };
                    events.push_back(make_replay_delete(hdr, msg, i));
                }
            }
        }

        return events;
    }
};

}  // namespace rexi::replay
