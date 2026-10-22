#pragma once

#include "rexi/market_data/message_header.hpp"
#include "rexi/market_data/messages.hpp"
#include "rexi/microstructure/rolling_window.hpp"
#include "rexi/microstructure/types.hpp"
#include "rexi/order_book/order_book.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <optional>

namespace rexi::microstructure {

/**
 * @brief Trade record stored in rolling circular buffers for trade-flow analytics.
 */
struct TradeRecord {
    Price price{0};
    Quantity quantity{0};
    MarketSide side{MarketSide::Buy};
    Timestamp timestamp_ns{0};
};

/**
 * @brief High-performance, deterministic microstructure feature engine.
 *
 * Implements Level 1 BBO, Level 2 multi-level depth imbalance, Cont et al. (2014) OFI,
 * signed trade flow, rolling VWAP, short-horizon returns and realized volatility,
 * Roll (1984) effective spread, and Easley et al. (2012) VPIN.
 *
 * Guarantees:
 * 1. Zero steady-state heap allocations.
 * 2. Strict temporal causality (T_avail >= T_event).
 * 3. Explicit handling and boolean gating of missing data, empty/crossed books, and warm-ups.
 */
class MicrostructureFeatureEngine {
public:
    static constexpr std::size_t MaxWindowCapacity = 256;

    explicit MicrostructureFeatureEngine(InstrumentId instrument_id,
                                         FeatureEngineConfig config = {}) noexcept
        : instrument_id_(instrument_id), config_(config) {
        features_.instrument_id = instrument_id;
    }

    // -------------------------------------------------------------------------
    // Event Ingestion Handlers
    // -------------------------------------------------------------------------

    /**
     * @brief Process a Top-of-Book / BBO quote message.
     *
     * @return true if event was processed, false if dropped due to non-monotonic timestamp.
     */
    bool on_top_of_book(const market_data::MarketDataHeader& header,
                        const market_data::TopOfBookMessage& msg) noexcept {
        return on_top_of_book(header.source_timestamp_ns,
                              header.receive_timestamp_ns,
                              header.sequence_num,
                              msg.best_bid_price,
                              msg.best_bid_quantity,
                              msg.best_ask_price,
                              msg.best_ask_quantity);
    }

    bool on_top_of_book(Timestamp event_time,
                        Timestamp source_time,
                        SequenceNumber seq,
                        Price bid_price,
                        Quantity bid_qty,
                        Price ask_price,
                        Quantity ask_qty) noexcept {
        if (!validate_timestamp(event_time)) {
            return false;
        }

        update_timestamps(event_time, source_time, seq);

        // Store previous valid quote for OFI before updating current
        const bool had_valid_quote = features_.has_bid && features_.has_ask && !features_.is_crossed;
        const Price prev_bid_price = features_.best_bid_price;
        const Quantity prev_bid_qty = features_.best_bid_quantity;
        const Price prev_ask_price = features_.best_ask_price;
        const Quantity prev_ask_qty = features_.best_ask_quantity;

        // Level 1 raw quotes
        features_.best_bid_price = bid_price;
        features_.best_bid_quantity = bid_qty;
        features_.best_ask_price = ask_price;
        features_.best_ask_quantity = ask_qty;

        features_.has_bid = (bid_price > 0 && bid_qty > 0);
        features_.has_ask = (ask_price > 0 && ask_qty > 0);

        if (features_.has_bid && features_.has_ask) {
            features_.is_crossed = (bid_price >= ask_price);
            if (!features_.is_crossed) {
                features_.spread = ask_price - bid_price;
                features_.mid_price = static_cast<double>(bid_price + ask_price) * 0.5;
                features_.relative_spread = static_cast<double>(features_.spread) / features_.mid_price;
                features_.has_spread = true;
                features_.has_mid = true;

                const double total_qty = static_cast<double>(bid_qty + ask_qty);
                if (total_qty > 0.0) {
                    features_.weighted_mid_price =
                        (static_cast<double>(bid_price) * static_cast<double>(ask_qty) +
                         static_cast<double>(ask_price) * static_cast<double>(bid_qty)) / total_qty;
                    features_.book_imbalance_top =
                        static_cast<double>(static_cast<int64_t>(bid_qty) - static_cast<int64_t>(ask_qty)) / total_qty;
                    features_.has_weighted_mid = true;
                    features_.has_book_imbalance = true;
                } else {
                    features_.weighted_mid_price = 0.0;
                    features_.book_imbalance_top = 0.0;
                    features_.has_weighted_mid = false;
                    features_.has_book_imbalance = false;
                }

                // Update mid-price returns and volatility
                update_mid_price_returns(features_.mid_price);

                // Compute Cont-Kukanov-Stoikov (2014) OFI
                if (had_valid_quote) {
                    compute_ofi(prev_bid_price, prev_bid_qty,
                                prev_ask_price, prev_ask_qty,
                                bid_price, bid_qty,
                                ask_price, ask_qty);
                }
            } else {
                // Book is crossed or locked
                features_.spread = ask_price - bid_price;
                features_.has_spread = false;
                features_.has_mid = false;
                features_.has_weighted_mid = false;
                features_.has_book_imbalance = false;
                features_.has_instant_ofi = false;
            }
        } else {
            // One-sided or empty book
            features_.is_crossed = false;
            features_.spread = 0;
            features_.relative_spread = 0.0;
            features_.mid_price = 0.0;
            features_.weighted_mid_price = 0.0;
            features_.book_imbalance_top = 0.0;
            features_.has_spread = false;
            features_.has_mid = false;
            features_.has_weighted_mid = false;
            features_.has_book_imbalance = false;
            features_.has_instant_ofi = false;
        }

        return true;
    }

    /**
     * @brief Process an executed public Trade message.
     *
     * @return true if event was processed, false if dropped due to non-monotonic timestamp.
     */
    bool on_trade(const market_data::MarketDataHeader& header,
                  const market_data::TradeMessage& msg) noexcept {
        return on_trade(header.source_timestamp_ns,
                        header.receive_timestamp_ns,
                        header.sequence_num,
                        msg.price,
                        msg.quantity,
                        msg.aggressor_side);
    }

    bool on_trade(Timestamp event_time,
                  Timestamp source_time,
                  SequenceNumber seq,
                  Price price,
                  Quantity quantity,
                  MarketSide aggressor_side) noexcept {
        if (!validate_timestamp(event_time)) {
            return false;
        }

        update_timestamps(event_time, source_time, seq);

        if (price <= 0 || quantity == 0) {
            return false;
        }

        features_.has_trade = true;
        features_.last_signed_volume = (aggressor_side == MarketSide::Buy)
            ? static_cast<int64_t>(quantity)
            : -static_cast<int64_t>(quantity);

        // Store into rolling trade buffer
        TradeRecord rec{price, quantity, aggressor_side, event_time};
        trade_history_.push_back(rec);

        // Update trade flow stats
        update_trade_flow();

        // Update Roll effective spread model
        update_roll_spread(price);

        // Update VPIN toxicity model
        update_vpin(quantity, aggressor_side);

        return true;
    }

    /**
     * @brief Process an updated L2/L3 OrderBook state to extract multi-level depth features.
     */
    bool on_order_book_update(const order_book::OrderBook& book,
                              Timestamp event_time,
                              Timestamp source_time,
                              SequenceNumber seq) noexcept {
        // Extract top of book from OrderBook
        const auto best_bid = book.best_bid();
        const auto best_ask = book.best_ask();

        Price b_p = best_bid ? best_bid->price : 0;
        Quantity b_q = best_bid ? best_bid->total_quantity : 0;
        Price a_p = best_ask ? best_ask->price : 0;
        Quantity a_q = best_ask ? best_ask->total_quantity : 0;

        // Process top-of-book logic (validates timestamps and updates L1)
        if (!on_top_of_book(event_time, source_time, seq, b_p, b_q, a_p, a_q)) {
            return false;
        }

        // Compute multi-level depth imbalance with zero heap allocations
        const std::size_t k = config_.depth_levels;
        Quantity bid_depth = book.bids_depth_quantity(k);
        Quantity ask_depth = book.asks_depth_quantity(k);

        features_.bid_depth_k = bid_depth;
        features_.ask_depth_k = ask_depth;

        const double total_depth = static_cast<double>(bid_depth + ask_depth);
        if (total_depth > 0.0 && !features_.is_crossed) {
            features_.depth_imbalance_k =
                static_cast<double>(static_cast<int64_t>(bid_depth) - static_cast<int64_t>(ask_depth)) / total_depth;
            features_.has_depth_imbalance = true;
        } else {
            features_.depth_imbalance_k = 0.0;
            features_.has_depth_imbalance = false;
        }

        return true;
    }

    // -------------------------------------------------------------------------
    // State Accessors
    // -------------------------------------------------------------------------

    [[nodiscard]] const MicrostructureFeatures& features() const noexcept {
        return features_;
    }

    [[nodiscard]] uint64_t out_of_order_drops() const noexcept {
        return out_of_order_drops_;
    }

    [[nodiscard]] const FeatureEngineConfig& config() const noexcept {
        return config_;
    }

    void reset() noexcept {
        features_ = MicrostructureFeatures{};
        features_.instrument_id = instrument_id_;
        last_event_time_ = 0;
        out_of_order_drops_ = 0;
        mid_prices_.clear();
        returns_history_.clear();
        trade_history_.clear();
        price_changes_.clear();
        last_trade_price_ = 0;
        vpin_buckets_.clear();
        curr_vpin_buy_vol_ = 0;
        curr_vpin_sell_vol_ = 0;
        curr_vpin_total_vol_ = 0;
        ofi_history_.clear();
    }

private:
    // -------------------------------------------------------------------------
    // Validation & Timestamps
    // -------------------------------------------------------------------------

    [[nodiscard]] bool validate_timestamp(Timestamp event_time) noexcept {
        if (last_event_time_ > 0 && event_time < last_event_time_) {
            ++out_of_order_drops_;
            return false;
        }
        last_event_time_ = event_time;
        return true;
    }

    void update_timestamps(Timestamp event_time, Timestamp source_time, SequenceNumber seq) noexcept {
        features_.event_timestamp_ns = event_time;
        features_.source_timestamp_ns = source_time;
        features_.decision_timestamp_ns = std::max(event_time, source_time);
        features_.sequence_number = seq;
    }

    // -------------------------------------------------------------------------
    // OFI Calculation (Cont et al. 2014)
    // -------------------------------------------------------------------------

    void compute_ofi(Price prev_b_p, Quantity prev_b_q,
                     Price prev_a_p, Quantity prev_a_q,
                     Price curr_b_p, Quantity curr_b_q,
                     Price curr_a_p, Quantity curr_a_q) noexcept {
        int64_t delta_b = 0;
        if (curr_b_p > prev_b_p) {
            delta_b = static_cast<int64_t>(curr_b_q);
        } else if (curr_b_p == prev_b_p) {
            delta_b = static_cast<int64_t>(curr_b_q) - static_cast<int64_t>(prev_b_q);
        } else {
            delta_b = -static_cast<int64_t>(prev_b_q);
        }

        int64_t delta_a = 0;
        if (curr_a_p < prev_a_p) {
            delta_a = -static_cast<int64_t>(curr_a_q);
        } else if (curr_a_p == prev_a_p) {
            delta_a = -(static_cast<int64_t>(curr_a_q) - static_cast<int64_t>(prev_a_q));
        } else {
            delta_a = static_cast<int64_t>(prev_a_q);
        }

        features_.instant_ofi = delta_b + delta_a;
        features_.has_instant_ofi = true;

        // Push to rolling OFI window
        ofi_history_.push_back(features_.instant_ofi);

        const std::size_t win = std::min(config_.ofi_window, MaxWindowCapacity);
        if (ofi_history_.size() >= win && win > 0) {
            int64_t sum = 0;
            const std::size_t start = ofi_history_.size() - win;
            for (std::size_t i = start; i < ofi_history_.size(); ++i) {
                sum += ofi_history_[i];
            }
            features_.rolling_ofi = sum;
            features_.has_rolling_ofi = true;
        } else {
            features_.rolling_ofi = 0;
            features_.has_rolling_ofi = false;
        }
    }

    // -------------------------------------------------------------------------
    // Mid-Price Returns & Realized Volatility
    // -------------------------------------------------------------------------

    void update_mid_price_returns(double current_mid) noexcept {
        if (current_mid <= 0.0) {
            return;
        }

        mid_prices_.push_back(current_mid);

        const std::size_t lookback = config_.return_lookback > 0 ? config_.return_lookback : 1;
        if (mid_prices_.size() > lookback) {
            const double past_mid = mid_prices_[mid_prices_.size() - 1 - lookback];
            if (past_mid > 0.0) {
                features_.log_return = std::log(current_mid / past_mid);
                features_.has_log_return = true;
                returns_history_.push_back(features_.log_return);
            }
        }

        const std::size_t vol_win = std::min(config_.volatility_window, MaxWindowCapacity);
        if (returns_history_.size() >= vol_win && vol_win >= 2) {
            double sum = 0.0;
            const std::size_t start = returns_history_.size() - vol_win;
            for (std::size_t i = start; i < returns_history_.size(); ++i) {
                sum += returns_history_[i];
            }
            const double mean = sum / static_cast<double>(vol_win);

            double sum_sq_diff = 0.0;
            for (std::size_t i = start; i < returns_history_.size(); ++i) {
                const double diff = returns_history_[i] - mean;
                sum_sq_diff += diff * diff;
            }
            features_.realized_volatility = std::sqrt(sum_sq_diff / static_cast<double>(vol_win - 1));
            features_.has_realized_volatility = true;
        } else {
            features_.realized_volatility = 0.0;
            features_.has_realized_volatility = false;
        }
    }

    // -------------------------------------------------------------------------
    // Trade Flow & VWAP
    // -------------------------------------------------------------------------

    void update_trade_flow() noexcept {
        const std::size_t win = std::min(config_.trade_window, MaxWindowCapacity);
        const std::size_t count = std::min(trade_history_.size(), win);

        if (count == 0) {
            features_.has_trade_flow = false;
            features_.has_vwap = false;
            return;
        }

        Quantity total_vol = 0;
        Quantity buy_vol = 0;
        Quantity sell_vol = 0;
        double price_qty_sum = 0.0;

        const std::size_t start = trade_history_.size() - count;
        for (std::size_t i = start; i < trade_history_.size(); ++i) {
            const auto& t = trade_history_[i];
            total_vol += t.quantity;
            if (t.side == MarketSide::Buy) {
                buy_vol += t.quantity;
            } else {
                sell_vol += t.quantity;
            }
            price_qty_sum += static_cast<double>(t.price) * static_cast<double>(t.quantity);
        }

        features_.rolling_trade_volume = total_vol;
        features_.rolling_buy_volume = buy_vol;
        features_.rolling_sell_volume = sell_vol;

        if (total_vol > 0) {
            features_.trade_flow_imbalance =
                static_cast<double>(static_cast<int64_t>(buy_vol) - static_cast<int64_t>(sell_vol)) /
                static_cast<double>(total_vol);
            features_.rolling_vwap = price_qty_sum / static_cast<double>(total_vol);
            features_.has_trade_flow = (count >= win);
            features_.has_vwap = true;
        } else {
            features_.trade_flow_imbalance = 0.0;
            features_.rolling_vwap = 0.0;
            features_.has_trade_flow = false;
            features_.has_vwap = false;
        }
    }

    // -------------------------------------------------------------------------
    // Roll (1984) Effective Spread
    // -------------------------------------------------------------------------

    void update_roll_spread(Price trade_price) noexcept {
        if (last_trade_price_ > 0) {
            const double delta_p = static_cast<double>(trade_price - last_trade_price_);
            price_changes_.push_back(delta_p);
        }
        last_trade_price_ = trade_price;

        const std::size_t win = std::min(config_.roll_window, MaxWindowCapacity);
        if (price_changes_.size() >= win && win >= 3) {
            // Compute mean of price changes over window
            const std::size_t start = price_changes_.size() - win;
            double sum = 0.0;
            for (std::size_t i = start; i < price_changes_.size(); ++i) {
                sum += price_changes_[i];
            }
            const double mean = sum / static_cast<double>(win);

            // Compute lag-1 autocovariance: Cov(Delta P_t, Delta P_{t-1})
            double cov_sum = 0.0;
            for (std::size_t i = start + 1; i < price_changes_.size(); ++i) {
                cov_sum += (price_changes_[i] - mean) * (price_changes_[i - 1] - mean);
            }
            const double gamma_1 = cov_sum / static_cast<double>(win - 1);

            // In Roll's model: S = 2 * sqrt(-gamma_1) when gamma_1 < 0
            if (gamma_1 < 0.0) {
                features_.roll_spread = 2.0 * std::sqrt(-gamma_1);
                features_.has_roll_spread = true;
            } else {
                features_.roll_spread = 0.0;
                features_.has_roll_spread = false;
            }
        } else {
            features_.roll_spread = 0.0;
            features_.has_roll_spread = false;
        }
    }

    // -------------------------------------------------------------------------
    // VPIN (Easley, Lopez de Prado, O'Hara 2012)
    // -------------------------------------------------------------------------

    void update_vpin(Quantity quantity, MarketSide side) noexcept {
        const Quantity bucket_vol = config_.vpin_bucket_volume;
        if (bucket_vol == 0) {
            features_.vpin = 0.0;
            features_.has_vpin = false;
            return;
        }

        Quantity remaining_qty = quantity;

        while (remaining_qty > 0) {
            const Quantity space = bucket_vol - curr_vpin_total_vol_;
            const Quantity fill = std::min(remaining_qty, space);

            if (side == MarketSide::Buy) {
                curr_vpin_buy_vol_ += fill;
            } else {
                curr_vpin_sell_vol_ += fill;
            }
            curr_vpin_total_vol_ += fill;
            remaining_qty -= fill;

            if (curr_vpin_total_vol_ >= bucket_vol) {
                // Completed a bucket!
                const int64_t buy_v = static_cast<int64_t>(curr_vpin_buy_vol_);
                const int64_t sell_v = static_cast<int64_t>(curr_vpin_sell_vol_);
                const double abs_imb = static_cast<double>(std::abs(buy_v - sell_v));

                vpin_buckets_.push_back(abs_imb);

                // Reset for next bucket
                curr_vpin_buy_vol_ = 0;
                curr_vpin_sell_vol_ = 0;
                curr_vpin_total_vol_ = 0;
            }
        }

        const std::size_t num_b = std::min(config_.vpin_num_buckets, MaxWindowCapacity);
        if (vpin_buckets_.size() >= num_b && num_b > 0) {
            double total_imb = 0.0;
            const std::size_t start = vpin_buckets_.size() - num_b;
            for (std::size_t i = start; i < vpin_buckets_.size(); ++i) {
                total_imb += vpin_buckets_[i];
            }
            const double denom = static_cast<double>(num_b) * static_cast<double>(bucket_vol);
            features_.vpin = (denom > 0.0) ? (total_imb / denom) : 0.0;
            features_.has_vpin = true;
        } else {
            features_.vpin = 0.0;
            features_.has_vpin = false;
        }
    }

    // -------------------------------------------------------------------------
    // Member Variables
    // -------------------------------------------------------------------------
    InstrumentId instrument_id_{0};
    FeatureEngineConfig config_{};
    MicrostructureFeatures features_{};

    Timestamp last_event_time_{0};
    uint64_t out_of_order_drops_{0};

    // Zero-heap ring buffers
    FixedRingBuffer<double, MaxWindowCapacity> mid_prices_{};
    FixedRingBuffer<double, MaxWindowCapacity> returns_history_{};
    FixedRingBuffer<int64_t, MaxWindowCapacity> ofi_history_{};
    FixedRingBuffer<TradeRecord, MaxWindowCapacity> trade_history_{};
    FixedRingBuffer<double, MaxWindowCapacity> price_changes_{};
    Price last_trade_price_{0};

    // VPIN tracking
    Quantity curr_vpin_buy_vol_{0};
    Quantity curr_vpin_sell_vol_{0};
    Quantity curr_vpin_total_vol_{0};
    FixedRingBuffer<double, MaxWindowCapacity> vpin_buckets_{};
};

} // namespace rexi::microstructure
