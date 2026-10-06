#pragma once

#include "rexi/market_data/types.hpp"
#include "rexi/order_book/order_book.hpp"
#include "rexi/replay/replay_clock.hpp"
#include "rexi/replay/replay_result.hpp"

#include <cstdint>

namespace rexi::replay {

/**
 * @brief Lightweight snapshot of historical replay state for point-in-time recovery.
 */
struct ReplayCheckpoint {
    ReplayClock clock{0};
    order_book::OrderBook book_snapshot{0};
    ReplayStatistics stats{};
};

}  // namespace rexi::replay
