#pragma once

#include "rexi/market_data/types.hpp"
#include "rexi/order_book/types.hpp"

#include <cstdint>
#include <string_view>

namespace rexi::replay {

/**
 * @brief Policy governing replay behavior upon encountering malformed data or sequence gaps.
 */
enum class ValidationPolicy : uint8_t {
    Strict = 0,     ///< Halt replay immediately upon encountering any invalid event
    Permissive = 1  ///< Reject invalid event, record structured diagnostic, continue stream
};

[[nodiscard]] constexpr std::string_view to_string(ValidationPolicy policy) noexcept {
    switch (policy) {
        case ValidationPolicy::Strict:
            return "Strict";
        case ValidationPolicy::Permissive:
            return "Permissive";
    }
    return "InvalidValidationPolicy";
}

/**
 * @brief Operational replay modes.
 */
enum class ReplayMode : uint8_t {
    Step = 0,       ///< Process exactly one event per invocation
    MaxSpeed = 1,   ///< Run stream as fast as possible until completion
    TimeScaled = 2  ///< Paced replay governed by historical timestamps
};

[[nodiscard]] constexpr std::string_view to_string(ReplayMode mode) noexcept {
    switch (mode) {
        case ReplayMode::Step:
            return "Step";
        case ReplayMode::MaxSpeed:
            return "MaxSpeed";
        case ReplayMode::TimeScaled:
            return "TimeScaled";
    }
    return "InvalidReplayMode";
}

/**
 * @brief Deterministic termination conditions for replay execution.
 */
struct ReplayStopCondition {
    uint64_t max_events{0};  ///< Maximum events to process (0 = unlimited)
    market_data::Timestamp stop_timestamp_ns{
        0};                    ///< Terminate once timestamp reached (0 = unlimited)
    bool stop_on_error{true};  ///< Terminate immediately on error
};

/**
 * @brief Canonical configuration structure for the ReplayEngine.
 */
struct ReplayConfig {
    ValidationPolicy validation_policy{ValidationPolicy::Strict};
    bool verify_sequence{true};
    bool verify_checksum{false};
    bool apply_trades_to_book{false};
    order_book::OrderBookConfig book_config{};
    order_book::CrossedBookPolicy crossed_book_policy{order_book::CrossedBookPolicy::Reject};
    ReplayStopCondition stop_condition{};
    double time_scale{0.0};  ///< 0.0 indicates unpaced maximum speed
};

}  // namespace rexi::replay
