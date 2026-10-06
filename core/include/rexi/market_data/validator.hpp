#pragma once

#include "rexi/market_data/message_header.hpp"
#include "rexi/market_data/messages.hpp"
#include "rexi/market_data/types.hpp"

namespace rexi::market_data {

/**
 * @brief Deterministic structural validator for canonical market data messages.
 */
class MessageValidator {
public:
    [[nodiscard]] static constexpr ValidationStatus validate_header(
        const MarketDataHeader& header, bool require_instrument = true) noexcept {
        if (header.version != CurrentProtocolVersion) {
            return ValidationStatus::InvalidVersion;
        }
        if (require_instrument && header.instrument_id == 0) {
            return ValidationStatus::InvalidInstrument;
        }
        if (header.sequence_num == 0) {
            return ValidationStatus::InvalidSequence;
        }
        return ValidationStatus::Valid;
    }

    [[nodiscard]] static constexpr ValidationStatus validate(
        const MarketDataHeader& header, const TopOfBookMessage& message) noexcept {
        const auto header_status = validate_header(header, true);
        if (header_status != ValidationStatus::Valid) {
            return header_status;
        }

        if (message.best_bid_price < 0 || message.best_ask_price < 0) {
            return ValidationStatus::InvalidPrice;
        }

        if (message.best_bid_price > 0 && message.best_ask_price > 0 &&
            message.best_bid_price > message.best_ask_price) {
            // Crossed market validation
            return ValidationStatus::InvalidPrice;
        }

        if ((message.best_bid_price > 0 && message.best_bid_quantity == 0) ||
            (message.best_ask_price > 0 && message.best_ask_quantity == 0)) {
            return ValidationStatus::InvalidQuantity;
        }

        return ValidationStatus::Valid;
    }

    [[nodiscard]] static constexpr ValidationStatus validate(const MarketDataHeader& header,
                                                             const TradeMessage& message) noexcept {
        const auto header_status = validate_header(header, true);
        if (header_status != ValidationStatus::Valid) {
            return header_status;
        }

        if (message.price <= 0) {
            return ValidationStatus::InvalidPrice;
        }

        if (message.quantity == 0) {
            return ValidationStatus::InvalidQuantity;
        }

        if (message.aggressor_side != MarketSide::Buy &&
            message.aggressor_side != MarketSide::Sell) {
            return ValidationStatus::MalformedPayload;
        }

        return ValidationStatus::Valid;
    }

    [[nodiscard]] static constexpr ValidationStatus validate(
        const MarketDataHeader& header, const OrderBookAddMessage& message) noexcept {
        const auto header_status = validate_header(header, true);
        if (header_status != ValidationStatus::Valid) {
            return header_status;
        }

        if (message.order_id == 0) {
            return ValidationStatus::MalformedPayload;
        }

        if (message.price <= 0) {
            return ValidationStatus::InvalidPrice;
        }

        if (message.quantity == 0) {
            return ValidationStatus::InvalidQuantity;
        }

        if (message.side != MarketSide::Buy && message.side != MarketSide::Sell) {
            return ValidationStatus::MalformedPayload;
        }

        return ValidationStatus::Valid;
    }

    [[nodiscard]] static constexpr ValidationStatus validate(
        const MarketDataHeader& header, const OrderBookModifyMessage& message) noexcept {
        const auto header_status = validate_header(header, true);
        if (header_status != ValidationStatus::Valid) {
            return header_status;
        }

        if (message.order_id == 0) {
            return ValidationStatus::MalformedPayload;
        }

        if (message.price <= 0) {
            return ValidationStatus::InvalidPrice;
        }

        return ValidationStatus::Valid;
    }

    [[nodiscard]] static constexpr ValidationStatus validate(
        const MarketDataHeader& header, const OrderBookDeleteMessage& message) noexcept {
        const auto header_status = validate_header(header, true);
        if (header_status != ValidationStatus::Valid) {
            return header_status;
        }

        if (message.order_id == 0) {
            return ValidationStatus::MalformedPayload;
        }

        return ValidationStatus::Valid;
    }

    [[nodiscard]] static constexpr ValidationStatus validate(
        const MarketDataHeader& header, const OrderBookSnapshotMessage& message) noexcept {
        const auto header_status = validate_header(header, true);
        if (header_status != ValidationStatus::Valid) {
            return header_status;
        }

        if (message.bid_levels_count > MaxSnapshotLevels ||
            message.ask_levels_count > MaxSnapshotLevels) {
            return ValidationStatus::MalformedPayload;
        }

        return ValidationStatus::Valid;
    }

    [[nodiscard]] static constexpr ValidationStatus validate(
        const MarketDataHeader& header, const MarketStatusMessage& message) noexcept {
        const auto header_status = validate_header(header, false);
        if (header_status != ValidationStatus::Valid) {
            return header_status;
        }

        if (message.status == TradingStatus::Unknown) {
            return ValidationStatus::MalformedPayload;
        }

        return ValidationStatus::Valid;
    }

    [[nodiscard]] static constexpr ValidationStatus validate(
        const MarketDataHeader& header, const InstrumentDefinitionMessage& message) noexcept {
        const auto header_status = validate_header(header, true);
        if (header_status != ValidationStatus::Valid) {
            return header_status;
        }

        if (message.tick_size <= 0) {
            return ValidationStatus::InvalidPrice;
        }

        if (message.lot_size == 0 || message.min_quantity == 0 ||
            message.max_quantity < message.min_quantity) {
            return ValidationStatus::InvalidQuantity;
        }

        return ValidationStatus::Valid;
    }
};

}  // namespace rexi::market_data
