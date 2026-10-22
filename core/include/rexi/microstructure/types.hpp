#pragma once

#include "rexi/market_data/types.hpp"

#include <cstddef>
#include <cstdint>

namespace rexi::microstructure {

using Price = market_data::Price;
using Quantity = market_data::Quantity;
using Timestamp = market_data::Timestamp;
using InstrumentId = market_data::InstrumentId;
using SequenceNumber = market_data::SequenceNumber;
using MarketSide = market_data::MarketSide;

/**
 * @brief Fixed-size record containing all computed microstructure features at a decision point.
 *
 * All features possess explicit availability semantics and corresponding boolean flags.
 * Missing or un-warmed values are never silently defaulted to zero without has_* being false.
 */
struct alignas(64) MicrostructureFeatures {
    // -------------------------------------------------------------------------
    // Identifiers and Timestamps
    // -------------------------------------------------------------------------
    InstrumentId instrument_id{0};
    SequenceNumber sequence_number{0};
    Timestamp event_timestamp_ns{0};      // Venue execution/quote timestamp (T_event)
    Timestamp source_timestamp_ns{0};     // Local ingestion timestamp (T_source)
    Timestamp decision_timestamp_ns{0};   // Availability/decision cutoff timestamp (T_avail >= T_event)

    // -------------------------------------------------------------------------
    // Level 1: Top of Book / Best Bid and Offer (BBO)
    // -------------------------------------------------------------------------
    Price best_bid_price{0};
    Quantity best_bid_quantity{0};
    Price best_ask_price{0};
    Quantity best_ask_quantity{0};

    Price spread{0};                    // best_ask_price - best_bid_price (integer ticks)
    double relative_spread{0.0};        // spread / mid_price (fraction)
    double mid_price{0.0};              // (best_bid_price + best_ask_price) / 2.0
    double weighted_mid_price{0.0};     // (P_bid * Q_ask + P_ask * Q_bid) / (Q_bid + Q_ask)
    double book_imbalance_top{0.0};     // (Q_bid - Q_ask) / (Q_bid + Q_ask) in [-1.0, 1.0]

    // -------------------------------------------------------------------------
    // Level 2: Multi-Level Aggregated Depth and Imbalance
    // -------------------------------------------------------------------------
    Quantity bid_depth_k{0};            // Cumulative bid depth over top K levels
    Quantity ask_depth_k{0};            // Cumulative ask depth over top K levels
    double depth_imbalance_k{0.0};      // (bid_depth - ask_depth) / (bid_depth + ask_depth)

    // -------------------------------------------------------------------------
    // Order Flow Imbalance (OFI)
    // -------------------------------------------------------------------------
    int64_t instant_ofi{0};             // Cont-Kukanov-Stoikov (2014) instantaneous OFI delta
    int64_t rolling_ofi{0};             // Sum of instant_ofi over rolling window

    // -------------------------------------------------------------------------
    // Trade Flow Metrics
    // -------------------------------------------------------------------------
    int64_t last_signed_volume{0};      // +Q for buyer-aggressor, -Q for seller-aggressor
    Quantity rolling_trade_volume{0};   // Sum of trade quantity over rolling trade window
    Quantity rolling_buy_volume{0};     // Sum of buyer-initiated trade volume
    Quantity rolling_sell_volume{0};    // Sum of seller-initiated trade volume
    double trade_flow_imbalance{0.0};   // (buy_vol - sell_vol) / (buy_vol + sell_vol)
    double rolling_vwap{0.0};           // Sum(P_i * Q_i) / Sum(Q_i) over rolling trade window

    // -------------------------------------------------------------------------
    // Short-Horizon Returns & Volatility
    // -------------------------------------------------------------------------
    double log_return{0.0};             // ln(mid_price_t / mid_price_{t-k})
    double realized_volatility{0.0};    // Sample std-dev of log returns over rolling window

    // -------------------------------------------------------------------------
    // Advanced Microstructure Models
    // -------------------------------------------------------------------------
    double roll_spread{0.0};            // 2 * sqrt(-Cov(Delta P_t, Delta P_{t-1})) Roll (1984)
    double vpin{0.0};                   // Volume-Synchronized Probability of Toxicity [0.0, 1.0]

    // -------------------------------------------------------------------------
    // Explicit Feature Availability and Validity Flags
    // -------------------------------------------------------------------------
    bool has_bid{false};
    bool has_ask{false};
    bool is_crossed{false};             // best_bid >= best_ask
    bool has_spread{false};
    bool has_mid{false};
    bool has_weighted_mid{false};
    bool has_book_imbalance{false};
    bool has_depth_imbalance{false};
    bool has_instant_ofi{false};
    bool has_rolling_ofi{false};
    bool has_trade{false};
    bool has_trade_flow{false};
    bool has_vwap{false};
    bool has_log_return{false};
    bool has_realized_volatility{false};
    bool has_roll_spread{false};
    bool has_vpin{false};
};

/**
 * @brief Configuration parameters for MicrostructureFeatureEngine.
 */
struct FeatureEngineConfig {
    std::size_t return_lookback{1};         // Mid-price return step lookback
    std::size_t volatility_window{20};      // Window of returns for realized volatility
    std::size_t ofi_window{20};             // Rolling window of OFI events
    std::size_t trade_window{20};           // Rolling window of trade executions
    std::size_t roll_window{30};            // Window of price diffs for Roll spread covariance
    Quantity vpin_bucket_volume{1000};      // Volume per VPIN bucket
    std::size_t vpin_num_buckets{20};       // Rolling number of completed buckets
    std::size_t depth_levels{5};            // Top K levels for multi-level depth features
};

} // namespace rexi::microstructure
