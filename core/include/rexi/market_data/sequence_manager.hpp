#pragma once

#include "rexi/market_data/types.hpp"

#include <cstdint>

namespace rexi::market_data {

/**
 * @brief Deterministic sequence tracker and gap detector for market data streams.
 *
 * Enforces sequence continuity, detects duplicate packets, out-of-order deliveries,
 * and transmission gaps without silently dropping or inventing missing data.
 */
class SequenceManager {
public:
    explicit constexpr SequenceManager(SequenceNumber initial_expected = 1) noexcept
        : expected_sequence_(initial_expected) {}

    /**
     * @brief Validate an incoming sequence number and update tracker state if expected.
     */
    SequenceStatus validate_and_advance(SequenceNumber incoming_seq) noexcept {
        if (expected_sequence_ == 0) {
            // Uninitialized stream: accept first observed sequence number
            last_processed_sequence_ = incoming_seq;
            expected_sequence_ = incoming_seq + 1;
            return SequenceStatus::Expected;
        }

        if (incoming_seq == expected_sequence_) {
            last_processed_sequence_ = incoming_seq;
            ++expected_sequence_;
            return SequenceStatus::Expected;
        }

        if (incoming_seq < expected_sequence_) {
            ++duplicate_count_;
            if (incoming_seq < last_processed_sequence_) {
                return SequenceStatus::OutOfOrder;
            }
            return SequenceStatus::Duplicate;
        }

        // incoming_seq > expected_sequence_
        ++gap_count_;
        return SequenceStatus::Gap;
    }

    /**
     * @brief Force-reset expected sequence number (e.g. following book snapshot sync).
     */
    void reset(SequenceNumber new_expected = 1) noexcept {
        expected_sequence_ = new_expected;
        last_processed_sequence_ = 0;
        gap_count_ = 0;
        duplicate_count_ = 0;
    }

    /**
     * @brief Accept a gap and fast-forward the expected sequence.
     */
    void fast_forward(SequenceNumber new_next_expected) noexcept {
        expected_sequence_ = new_next_expected;
        last_processed_sequence_ = (new_next_expected > 0) ? (new_next_expected - 1) : 0;
    }

    [[nodiscard]] constexpr SequenceNumber expected_sequence() const noexcept {
        return expected_sequence_;
    }

    [[nodiscard]] constexpr SequenceNumber last_processed_sequence() const noexcept {
        return last_processed_sequence_;
    }

    [[nodiscard]] constexpr std::uint64_t gap_count() const noexcept { return gap_count_; }

    [[nodiscard]] constexpr std::uint64_t duplicate_count() const noexcept {
        return duplicate_count_;
    }

private:
    SequenceNumber expected_sequence_{1};
    SequenceNumber last_processed_sequence_{0};
    std::uint64_t gap_count_{0};
    std::uint64_t duplicate_count_{0};
};

}  // namespace rexi::market_data
