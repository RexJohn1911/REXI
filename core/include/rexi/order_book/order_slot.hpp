#pragma once

#include "rexi/order_book/resting_order.hpp"
#include "rexi/order_book/types.hpp"

#include <cstdint>
#include <limits>

namespace rexi::order_book {

/**
 * @brief Unsigned 32-bit handle indexing a slot within an OrderPool.
 */
using OrderHandle = uint32_t;

/**
 * @brief Sentinel value indicating an invalid or unassigned order handle.
 */
inline constexpr OrderHandle kInvalidOrderHandle = std::numeric_limits<OrderHandle>::max();

/**
 * @brief Preallocated slot in an OrderPool containing resting order data and intrusive links.
 *
 * Designed for deterministic, allocation-free FIFO queue operations and O(1) removals.
 * 8-byte aligned to maximize memory density and cache utilization.
 */
struct alignas(8) OrderSlot {
    RestingOrder order{};
    OrderHandle prev{kInvalidOrderHandle};
    OrderHandle next{kInvalidOrderHandle};
    uint32_t generation{0};
    bool is_occupied{false};

    [[nodiscard]] constexpr bool is_free() const noexcept { return !is_occupied; }
};

}  // namespace rexi::order_book
