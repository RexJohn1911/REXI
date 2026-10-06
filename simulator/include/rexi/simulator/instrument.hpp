#pragma once

#include "rexi/simulator/types.hpp"

namespace rexi::simulator {

/**
 * @brief Tradable instrument definition and validation specification.
 */
struct Instrument {
    InstrumentId id{0};
    Price tick_size{1};
    Quantity min_quantity{1};
    Quantity max_quantity{1'000'000'000};
    Quantity lot_size{1};

    /**
     * @brief Validate an incoming order request against instrument constraints.
     */
    [[nodiscard]] constexpr bool validate_order(Side side, OrderType type, Price price,
                                                Quantity quantity,
                                                RejectReason& reason) const noexcept {
        (void)side;
        if (quantity < min_quantity || quantity > max_quantity) {
            reason = RejectReason::InvalidQuantity;
            return false;
        }

        if (lot_size > 1 && (quantity % lot_size != 0)) {
            reason = RejectReason::InvalidQuantity;
            return false;
        }

        if (type == OrderType::Limit) {
            if (price <= 0) {
                reason = RejectReason::InvalidPrice;
                return false;
            }
            if (tick_size > 1 && (price % tick_size != 0)) {
                reason = RejectReason::InvalidPrice;
                return false;
            }
        } else if (type == OrderType::Market) {
            // Market orders must not require a positive limit price
            if (price < 0) {
                reason = RejectReason::InvalidPrice;
                return false;
            }
        } else {
            reason = RejectReason::UnsupportedOrderType;
            return false;
        }

        reason = RejectReason::None;
        return true;
    }
};

}  // namespace rexi::simulator
