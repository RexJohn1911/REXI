#pragma once

#include "rexi/simulator/types.hpp"

#include <cstdint>

namespace rexi::simulator {

/**
 * @brief Order entity with explicit lifecycle tracking and price-time priority.
 */
struct Order {
    OrderId order_id{0};
    ClientId client_id{0};
    InstrumentId instrument_id{0};
    Side side{Side::Buy};
    OrderType type{OrderType::Limit};
    Price price{0};
    Quantity initial_quantity{0};
    Quantity remaining_quantity{0};
    Quantity filled_quantity{0};
    SequenceNum priority_seq{0};
    OrderStatus status{OrderStatus::New};
    uint64_t accepted_timestamp_ns{0};

    [[nodiscard]] constexpr bool is_active() const noexcept {
        return status == OrderStatus::Accepted || status == OrderStatus::PartiallyFilled;
    }

    constexpr void fill(Quantity fill_qty) noexcept {
        if (fill_qty >= remaining_quantity) {
            filled_quantity += remaining_quantity;
            remaining_quantity = 0;
            status = OrderStatus::Filled;
        } else {
            filled_quantity += fill_qty;
            remaining_quantity -= fill_qty;
            status = OrderStatus::PartiallyFilled;
        }
    }

    constexpr void cancel() noexcept {
        if (is_active()) {
            status = OrderStatus::Cancelled;
        }
    }
};

}  // namespace rexi::simulator
