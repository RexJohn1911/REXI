#pragma once

#include "rexi/market_data/message_header.hpp"
#include "rexi/market_data/messages.hpp"
#include "rexi/market_data/types.hpp"

#include <variant>

namespace rexi::market_data {

/**
 * @brief Unified canonical market data message container pairing header with typed payload.
 */
struct MarketDataMessage {
    MarketDataHeader header{};
    std::variant<std::monostate, InstrumentDefinitionMessage, TopOfBookMessage, TradeMessage,
                 OrderBookAddMessage, OrderBookModifyMessage, OrderBookDeleteMessage,
                 OrderBookSnapshotMessage, MarketStatusMessage>
        payload{std::monostate{}};

    template <typename T>
    [[nodiscard]] bool holds() const noexcept {
        return std::holds_alternative<T>(payload);
    }

    template <typename T>
    [[nodiscard]] const T* get() const noexcept {
        return std::get_if<T>(&payload);
    }
};

/**
 * @brief Normalization interface contract for converting diverse raw feed messages into canonical
 * MarketDataMessage.
 */
template <typename RawFeedMessage>
class INormalizer {
public:
    virtual ~INormalizer() = default;

    [[nodiscard]] virtual MarketDataMessage normalize(const RawFeedMessage& raw) = 0;
};

}  // namespace rexi::market_data
