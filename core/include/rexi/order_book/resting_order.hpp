#pragma once

#include "rexi/order_book/types.hpp"

#include <cstdint>

namespace rexi::order_book {

/**
 * @brief Represents an individual resting Level 3 order in the book.
 *
 * Trivially copyable, standard layout, containing all metadata necessary
 * for FIFO price-time priority tracking and execution.
 */
struct alignas(8) RestingOrder {
    OrderId order_id{0};
    InstrumentId instrument_id{0};
    Side side{Side::Buy};
    Price price{0};
    Quantity initial_quantity{0};
    Quantity remaining_quantity{0};
    SequenceNumber priority_seq{0};
    Timestamp timestamp_ns{0};

    [[nodiscard]] constexpr bool is_active() const noexcept { return remaining_quantity > 0; }

    [[nodiscard]] constexpr bool is_filled() const noexcept { return remaining_quantity == 0; }

    constexpr void reduce(Quantity qty) noexcept {
        if (qty >= remaining_quantity) {
            remaining_quantity = 0;
        } else {
            remaining_quantity -= qty;
        }
    }

    [[nodiscard]] constexpr bool operator==(const RestingOrder& other) const noexcept {
        return order_id == other.order_id && instrument_id == other.instrument_id &&
               side == other.side && price == other.price &&
               initial_quantity == other.initial_quantity &&
               remaining_quantity == other.remaining_quantity &&
               priority_seq == other.priority_seq && timestamp_ns == other.timestamp_ns;
    }
};

}  // namespace rexi::order_book
