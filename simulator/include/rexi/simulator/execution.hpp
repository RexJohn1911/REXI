#pragma once

#include "rexi/simulator/types.hpp"

#include <cstdint>

namespace rexi::simulator {

/**
 * @brief Immutable trade execution record representing a matched fill.
 */
struct Execution {
    ExecutionId execution_id{0};
    InstrumentId instrument_id{0};
    Price price{0};
    Quantity quantity{0};
    Side aggressor_side{Side::Buy};
    OrderId maker_order_id{0};
    OrderId taker_order_id{0};
    ClientId maker_client_id{0};
    ClientId taker_client_id{0};
    SequenceNum sequence{0};
    uint64_t timestamp_ns{0};
};

}  // namespace rexi::simulator
