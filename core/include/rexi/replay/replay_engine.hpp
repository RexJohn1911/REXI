#pragma once

#include "rexi/events/event.hpp"
#include "rexi/events/event_dispatcher.hpp"
#include "rexi/market_data/checksum.hpp"
#include "rexi/market_data/events.hpp"
#include "rexi/market_data/sequence_manager.hpp"
#include "rexi/market_data/validator.hpp"
#include "rexi/order_book/order_book.hpp"
#include "rexi/replay/replay_checkpoint.hpp"
#include "rexi/replay/replay_clock.hpp"
#include "rexi/replay/replay_config.hpp"
#include "rexi/replay/replay_event.hpp"
#include "rexi/replay/replay_reader.hpp"
#include "rexi/replay/replay_result.hpp"

#include <array>
#include <chrono>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

namespace rexi::replay {

/**
 * @brief Canonical deterministic historical market replay engine.
 *
 * Replays recorded market-data event streams through the canonical Phase 04 protocol
 * and feeds state updates into the canonical Phase 05/06 OrderBook.
 */
class ReplayEngine {
public:
    explicit ReplayEngine(market_data::InstrumentId instrument_id, ReplayConfig config = {})
        : book_(instrument_id, config.crossed_book_policy, config.book_config), config_(config) {
        diagnostics_.reserve(32);
    }

    explicit ReplayEngine(order_book::OrderBook initial_book, ReplayConfig config = {})
        : book_(std::move(initial_book)), config_(config) {
        diagnostics_.reserve(32);
    }

    /**
     * @brief Connect optional Phase 02 EventDispatcher to observe replayed events.
     */
    void set_event_dispatcher(events::EventDispatcher* dispatcher) noexcept {
        dispatcher_ = dispatcher;
    }

    /**
     * @brief Reset engine to initial state for reproducible repeat runs.
     */
    void reset() {
        book_.clear();
        clock_.reset();
        stats_ = ReplayStatistics{};
        diagnostics_.clear();
        for (size_t i = 0; i < feed_count_; ++i) {
            feed_cache_[i].manager.reset(1);
            feed_cache_[i].active = false;
        }
        feed_count_ = 0;
        sequence_managers_fallback_.clear();
        stopped_ = false;
    }

    /**
     * @brief Process exactly one event from the reader (Step Mode).
     *
     * @return true if an event was processed and replay may continue, false if stopped or stream
     * exhausted.
     */
    bool step(IReplayReader& reader) { return step_internal(reader); }

    template <typename Reader>
        requires(!std::is_base_of_v<IReplayReader, Reader>)
    bool step(Reader& reader) {
        return step_internal(reader);
    }

    /**
     * @brief Replay stream to completion at maximum speed (Max Speed Mode).
     */
    ReplayResult run(IReplayReader& reader) { return run_internal(reader, config_.stop_condition); }

    template <typename Reader>
        requires(!std::is_base_of_v<IReplayReader, Reader>)
    ReplayResult run(Reader& reader) {
        return run_internal(reader, config_.stop_condition);
    }

    /**
     * @brief Replay stream until an explicit stop condition is met.
     */
    ReplayResult run_until(IReplayReader& reader, const ReplayStopCondition& stop_cond) {
        return run_internal(reader, stop_cond);
    }

    template <typename Reader>
        requires(!std::is_base_of_v<IReplayReader, Reader>)
    ReplayResult run_until(Reader& reader, const ReplayStopCondition& stop_cond) {
        return run_internal(reader, stop_cond);
    }

    [[nodiscard]] const order_book::OrderBook& book() const noexcept { return book_; }

    [[nodiscard]] order_book::OrderBook& book() noexcept { return book_; }

    [[nodiscard]] const ReplayClock& clock() const noexcept { return clock_; }

    [[nodiscard]] const ReplayConfig& config() const noexcept { return config_; }

    [[nodiscard]] const ReplayStatistics& statistics() const noexcept { return stats_; }

    [[nodiscard]] const std::vector<ReplayDiagnostic>& diagnostics() const noexcept {
        return diagnostics_;
    }

    [[nodiscard]] uint64_t compute_digest() const noexcept {
        return compute_state_digest(book_, clock_, stats_);
    }

    [[nodiscard]] bool is_stopped() const noexcept { return stopped_; }

    /**
     * @brief Capture lightweight deterministic replay checkpoint.
     */
    [[nodiscard]] ReplayCheckpoint create_checkpoint() const {
        return ReplayCheckpoint{
            .clock = clock_,
            .book_snapshot = book_,
            .stats = stats_,
        };
    }

    /**
     * @brief Restore engine from previously captured checkpoint.
     */
    void restore_checkpoint(const ReplayCheckpoint& checkpoint) {
        book_ = checkpoint.book_snapshot;
        clock_ = checkpoint.clock;
        stats_ = checkpoint.stats;
        stopped_ = false;
    }

private:
    template <typename Reader>
    bool step_internal(Reader& reader) {
        if (stopped_ || !reader.has_next()) {
            return false;
        }

        const ReplayEvent* event = reader.next();
        if (event == nullptr) {
            return false;
        }

        ++stats_.events_read;
        return process_event(*event);
    }

    template <typename Reader>
    ReplayResult run_internal(Reader& reader, const ReplayStopCondition& stop_cond) {
        const auto start_wall = std::chrono::steady_clock::now();

        while (!stopped_ && reader.has_next()) {
            if (stop_cond.max_events > 0 && stats_.events_processed >= stop_cond.max_events) {
                break;
            }

            const ReplayEvent* event = reader.next();
            if (event == nullptr) {
                break;
            }

            if (stop_cond.stop_timestamp_ns > 0 &&
                event->source_timestamp_ns() > stop_cond.stop_timestamp_ns) {
                break;
            }

            ++stats_.events_read;
            const bool success = process_event(*event);
            if (!success && stop_cond.stop_on_error &&
                config_.validation_policy == ValidationPolicy::Strict) {
                stopped_ = true;
                break;
            }
        }

        const auto end_wall = std::chrono::steady_clock::now();
        stats_.wall_time_ns = static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(end_wall - start_wall).count());

        return build_result();
    }

    bool process_event(const ReplayEvent& event) {
        const bool strict = (config_.validation_policy == ValidationPolicy::Strict);

        // 1. Validate Header
        const bool require_inst =
            (event.message_type() != market_data::MarketDataMessageType::MarketStatus);
        const auto hdr_status =
            market_data::MessageValidator::validate_header(event.header, require_inst);
        if (hdr_status != market_data::ValidationStatus::Valid) {
            record_diagnostic(event, "Header validation failure", hdr_status,
                              market_data::SequenceStatus::Expected,
                              market_data::ChecksumStatus::NotSupplied);
            ++stats_.validation_failures;
            ++stats_.events_rejected;
            if (strict) {
                stopped_ = true;
                return false;
            }
            return true;
        }

        // 2. Validate Payload
        market_data::ValidationStatus payload_status = market_data::ValidationStatus::Valid;
        std::visit(
            [&](const auto& payload) {
                using T = std::decay_t<decltype(payload)>;
                if constexpr (!std::is_same_v<T, std::monostate>) {
                    payload_status = market_data::MessageValidator::validate(event.header, payload);
                } else {
                    payload_status = market_data::ValidationStatus::MalformedPayload;
                }
            },
            event.payload);

        if (payload_status != market_data::ValidationStatus::Valid) {
            record_diagnostic(event, "Payload validation failure", payload_status,
                              market_data::SequenceStatus::Expected,
                              market_data::ChecksumStatus::NotSupplied);
            ++stats_.validation_failures;
            ++stats_.events_rejected;
            if (strict) {
                stopped_ = true;
                return false;
            }
            return true;
        }

        // 3. Verify Checksum
        if (config_.verify_checksum && event.header.checksum != 0) {
            market_data::ChecksumStatus cs_status = market_data::ChecksumStatus::Valid;
            std::visit(
                [&](const auto& payload) {
                    using T = std::decay_t<decltype(payload)>;
                    if constexpr (!std::is_same_v<T, std::monostate>) {
                        cs_status = market_data::IntegrityChecksum::verify(event.header, payload);
                    }
                },
                event.payload);

            if (cs_status == market_data::ChecksumStatus::Invalid) {
                record_diagnostic(event, "Checksum mismatch",
                                  market_data::ValidationStatus::InvalidChecksum,
                                  market_data::SequenceStatus::Expected, cs_status);
                ++stats_.checksum_failures;
                ++stats_.events_rejected;
                if (strict) {
                    stopped_ = true;
                    return false;
                }
                return true;
            }
        }

        // 4. Verify Sequence Progression
        if (config_.verify_sequence) {
            auto& seq_mgr = get_or_create_seq_mgr(event.venue_id(), event.feed_id());
            if (event.message_type() == market_data::MarketDataMessageType::OrderBookSnapshot) {
                const auto* snap = event.get_if<market_data::OrderBookSnapshotMessage>();
                if (snap != nullptr && snap->last_included_sequence > 0) {
                    seq_mgr.fast_forward(snap->last_included_sequence + 1);
                }
            } else if (event.sequence_num() > 0) {
                const auto seq_status = seq_mgr.validate_and_advance(event.sequence_num());
                if (seq_status == market_data::SequenceStatus::Gap) {
                    ++stats_.sequence_gaps;
                    record_diagnostic(event, "Sequence gap detected",
                                      market_data::ValidationStatus::Valid, seq_status,
                                      market_data::ChecksumStatus::Valid);
                    if (strict) {
                        stopped_ = true;
                        return false;
                    }
                    seq_mgr.fast_forward(event.sequence_num() + 1);
                } else if (seq_status == market_data::SequenceStatus::Duplicate) {
                    ++stats_.duplicates;
                    ++stats_.events_rejected;
                    record_diagnostic(event, "Duplicate sequence detected",
                                      market_data::ValidationStatus::Valid, seq_status,
                                      market_data::ChecksumStatus::Valid);
                    if (strict) {
                        stopped_ = true;
                        return false;
                    }
                    return true;
                } else if (seq_status == market_data::SequenceStatus::OutOfOrder) {
                    ++stats_.out_of_order;
                    ++stats_.events_rejected;
                    record_diagnostic(event, "Out-of-order sequence detected",
                                      market_data::ValidationStatus::Valid, seq_status,
                                      market_data::ChecksumStatus::Valid);
                    if (strict) {
                        stopped_ = true;
                        return false;
                    }
                    return true;
                }
            }
        }

        // 5. Advance Replay Clock
        clock_.advance_to(event.source_timestamp_ns());

        // 6. Apply to Canonical OrderBook & Dispatch Phase 02 Events
        order_book::OrderBookStatus book_status = order_book::OrderBookStatus::Success;

        switch (event.message_type()) {
            case market_data::MarketDataMessageType::OrderBookAdd: {
                const auto& add_msg = event.get<market_data::OrderBookAddMessage>();
                book_status = book_.apply_add(event.header, add_msg);
                if (book_status == order_book::OrderBookStatus::Success) {
                    ++stats_.book_updates;
                    if (dispatcher_ != nullptr) {
                        dispatcher_->dispatch<market_data::OrderBookAddMessage>(
                            events::make_event(add_msg, event.source, event.sequence_num(), 0,
                                               event.source_timestamp_ns()));
                    }
                }
                break;
            }
            case market_data::MarketDataMessageType::OrderBookModify: {
                const auto& mod_msg = event.get<market_data::OrderBookModifyMessage>();
                book_status = book_.apply_modify(event.header, mod_msg);
                if (book_status == order_book::OrderBookStatus::Success) {
                    ++stats_.book_updates;
                    if (dispatcher_ != nullptr) {
                        dispatcher_->dispatch<market_data::OrderBookModifyMessage>(
                            events::make_event(mod_msg, event.source, event.sequence_num(), 0,
                                               event.source_timestamp_ns()));
                    }
                }
                break;
            }
            case market_data::MarketDataMessageType::OrderBookDelete: {
                const auto& del_msg = event.get<market_data::OrderBookDeleteMessage>();
                book_status = book_.apply_delete(event.header, del_msg);
                if (book_status == order_book::OrderBookStatus::Success) {
                    ++stats_.book_updates;
                    if (dispatcher_ != nullptr) {
                        dispatcher_->dispatch<market_data::OrderBookDeleteMessage>(
                            events::make_event(del_msg, event.source, event.sequence_num(), 0,
                                               event.source_timestamp_ns()));
                    }
                }
                break;
            }
            case market_data::MarketDataMessageType::OrderBookSnapshot: {
                const auto& snap_msg = event.get<market_data::OrderBookSnapshotMessage>();
                book_status = book_.apply_snapshot(snap_msg);
                if (book_status == order_book::OrderBookStatus::Success) {
                    ++stats_.snapshots_applied;
                    ++stats_.book_updates;
                    if (dispatcher_ != nullptr) {
                        dispatcher_->dispatch<market_data::OrderBookSnapshotMessage>(
                            events::make_event(snap_msg, event.source, event.sequence_num(), 0,
                                               event.source_timestamp_ns()));
                    }
                }
                break;
            }
            case market_data::MarketDataMessageType::Trade: {
                const auto& trd_msg = event.get<market_data::TradeMessage>();
                ++stats_.trades_observed;
                if (config_.apply_trades_to_book && trd_msg.maker_order_id != 0 &&
                    book_.find_order(trd_msg.maker_order_id) != nullptr) {
                    book_status = book_.reduce_order(trd_msg.maker_order_id, trd_msg.quantity);
                    if (book_status == order_book::OrderBookStatus::Success) {
                        ++stats_.book_updates;
                    }
                }
                if (dispatcher_ != nullptr) {
                    dispatcher_->dispatch<market_data::TradeMessage>(
                        events::make_event(trd_msg, event.source, event.sequence_num(), 0,
                                           event.source_timestamp_ns()));
                }
                break;
            }
            case market_data::MarketDataMessageType::TopOfBook: {
                const auto& tob_msg = event.get<market_data::TopOfBookMessage>();
                if (dispatcher_ != nullptr) {
                    dispatcher_->dispatch<market_data::TopOfBookMessage>(
                        events::make_event(tob_msg, event.source, event.sequence_num(), 0,
                                           event.source_timestamp_ns()));
                }
                break;
            }
            case market_data::MarketDataMessageType::MarketStatus: {
                const auto& stat_msg = event.get<market_data::MarketStatusMessage>();
                if (dispatcher_ != nullptr) {
                    dispatcher_->dispatch<market_data::MarketStatusMessage>(
                        events::make_event(stat_msg, event.source, event.sequence_num(), 0,
                                           event.source_timestamp_ns()));
                }
                break;
            }
            case market_data::MarketDataMessageType::InstrumentDefinition: {
                const auto& inst_msg = event.get<market_data::InstrumentDefinitionMessage>();
                if (dispatcher_ != nullptr) {
                    dispatcher_->dispatch<market_data::InstrumentDefinitionMessage>(
                        events::make_event(inst_msg, event.source, event.sequence_num(), 0,
                                           event.source_timestamp_ns()));
                }
                break;
            }
            default:
                break;
        }

        if (book_status != order_book::OrderBookStatus::Success) {
            record_diagnostic(event, "OrderBook rejected update",
                              market_data::ValidationStatus::Valid,
                              market_data::SequenceStatus::Expected,
                              market_data::ChecksumStatus::Valid, book_status);
            ++stats_.events_rejected;
            if (strict) {
                stopped_ = true;
                return false;
            }
            return true;
        }

        // 7. Update Replay Statistics
        ++stats_.events_processed;
        if (stats_.first_timestamp_ns == 0) {
            stats_.first_timestamp_ns = event.source_timestamp_ns();
        }
        stats_.last_timestamp_ns = event.source_timestamp_ns();
        if (stats_.last_timestamp_ns >= stats_.first_timestamp_ns) {
            stats_.elapsed_replay_time_ns = stats_.last_timestamp_ns - stats_.first_timestamp_ns;
        }

        return true;
    }

    void record_diagnostic(
        const ReplayEvent& event, std::string_view reason,
        market_data::ValidationStatus val_stat = market_data::ValidationStatus::Valid,
        market_data::SequenceStatus seq_stat = market_data::SequenceStatus::Expected,
        market_data::ChecksumStatus cs_stat = market_data::ChecksumStatus::Valid,
        order_book::OrderBookStatus bk_stat = order_book::OrderBookStatus::Success) {
        diagnostics_.push_back(ReplayDiagnostic{
            .event_index = clock_.event_index(),
            .sequence_num = event.sequence_num(),
            .timestamp_ns = event.source_timestamp_ns(),
            .instrument_id = event.instrument_id(),
            .message_type = event.message_type(),
            .reason = std::string(reason),
            .validation_status = val_stat,
            .sequence_status = seq_stat,
            .checksum_status = cs_stat,
            .book_status = bk_stat,
        });
    }

    static constexpr size_t MaxCachedFeeds = 16;
    struct FeedSequenceEntry {
        uint32_t feed_key{0};
        market_data::SequenceManager manager{1};
        bool active{false};
    };

    market_data::SequenceManager& get_or_create_seq_mgr(market_data::VenueId venue,
                                                        market_data::FeedId feed) {
        const uint32_t key = (static_cast<uint32_t>(venue) << 16) | static_cast<uint32_t>(feed);
        for (size_t i = 0; i < feed_count_; ++i) {
            if (feed_cache_[i].active && feed_cache_[i].feed_key == key) {
                return feed_cache_[i].manager;
            }
        }
        if (feed_count_ < MaxCachedFeeds) {
            auto& entry = feed_cache_[feed_count_++];
            entry.feed_key = key;
            entry.manager.reset(1);
            entry.active = true;
            return entry.manager;
        }
        auto it = sequence_managers_fallback_.find(key);
        if (it == sequence_managers_fallback_.end()) {
            it = sequence_managers_fallback_.emplace(key, market_data::SequenceManager(1)).first;
        }
        return it->second;
    }

    [[nodiscard]] ReplayResult build_result() const {
        auto quote = book_.top_quote();
        const bool clean = diagnostics_.empty() && stats_.validation_failures == 0 &&
                           stats_.sequence_gaps == 0 && stats_.duplicates == 0 &&
                           stats_.out_of_order == 0;

        return ReplayResult{
            .stats = stats_,
            .state_digest = compute_digest(),
            .diagnostics = diagnostics_,
            .best_bid_price = quote.bid_price,
            .best_bid_quantity = quote.bid_quantity,
            .best_ask_price = quote.ask_price,
            .best_ask_quantity = quote.ask_quantity,
            .total_orders = book_.order_count(),
            .bid_levels = book_.bid_level_count(),
            .ask_levels = book_.ask_level_count(),
            .is_clean = clean,
        };
    }

    order_book::OrderBook book_;
    ReplayClock clock_{0};
    ReplayConfig config_{};
    ReplayStatistics stats_{};
    std::vector<ReplayDiagnostic> diagnostics_{};
    std::array<FeedSequenceEntry, MaxCachedFeeds> feed_cache_{};
    size_t feed_count_{0};
    std::unordered_map<uint32_t, market_data::SequenceManager> sequence_managers_fallback_{};
    events::EventDispatcher* dispatcher_{nullptr};
    bool stopped_{false};
};

}  // namespace rexi::replay
