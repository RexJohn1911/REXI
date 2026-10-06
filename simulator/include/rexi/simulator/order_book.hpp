#pragma once

#include "rexi/simulator/order.hpp"
#include "rexi/simulator/types.hpp"

#include <deque>
#include <functional>
#include <map>
#include <optional>
#include <unordered_map>
#include <utility>

namespace rexi::simulator {

/**
 * @brief Price-time priority limit order book for a single instrument.
 *
 * Bids are ordered highest-price first; Asks are ordered lowest-price first.
 * At each price level, orders are queued in strict FIFO sequence priority.
 */
class OrderBook {
public:
    using BidMap = std::map<Price, std::deque<Order>, std::greater<>>;
    using AskMap = std::map<Price, std::deque<Order>, std::less<>>;

    explicit OrderBook(InstrumentId instrument_id = 0) noexcept : instrument_id_(instrument_id) {}

    [[nodiscard]] InstrumentId instrument_id() const noexcept { return instrument_id_; }

    [[nodiscard]] bool has_bids() const noexcept { return !bids_.empty(); }

    [[nodiscard]] bool has_asks() const noexcept { return !asks_.empty(); }

    [[nodiscard]] std::optional<std::pair<Price, Quantity>> best_bid() const noexcept {
        if (bids_.empty()) {
            return std::nullopt;
        }
        const auto& [price, queue] = *bids_.begin();
        Quantity level_qty = 0;
        for (const auto& order : queue) {
            level_qty += order.remaining_quantity;
        }
        return std::make_pair(price, level_qty);
    }

    [[nodiscard]] std::optional<std::pair<Price, Quantity>> best_ask() const noexcept {
        if (asks_.empty()) {
            return std::nullopt;
        }
        const auto& [price, queue] = *asks_.begin();
        Quantity level_qty = 0;
        for (const auto& order : queue) {
            level_qty += order.remaining_quantity;
        }
        return std::make_pair(price, level_qty);
    }

    [[nodiscard]] size_t order_count() const noexcept { return order_locations_.size(); }

    [[nodiscard]] bool has_order(OrderId order_id) const noexcept {
        return order_locations_.contains(order_id);
    }

    [[nodiscard]] const Order* find_order(OrderId order_id) const noexcept {
        auto loc_it = order_locations_.find(order_id);
        if (loc_it == order_locations_.end()) {
            return nullptr;
        }
        const auto& loc = loc_it->second;
        if (loc.side == Side::Buy) {
            auto bid_it = bids_.find(loc.price);
            if (bid_it != bids_.end()) {
                for (const auto& order : bid_it->second) {
                    if (order.order_id == order_id) {
                        return &order;
                    }
                }
            }
        } else {
            auto ask_it = asks_.find(loc.price);
            if (ask_it != asks_.end()) {
                for (const auto& order : ask_it->second) {
                    if (order.order_id == order_id) {
                        return &order;
                    }
                }
            }
        }
        return nullptr;
    }

    void insert_order(const Order& order) {
        if (order.remaining_quantity == 0 || !order.is_active()) {
            return;
        }

        if (order.side == Side::Buy) {
            bids_[order.price].push_back(order);
        } else {
            asks_[order.price].push_back(order);
        }
        order_locations_[order.order_id] = OrderLocation{.side = order.side, .price = order.price};
    }

    bool cancel_order(OrderId order_id, Order& cancelled_order) {
        auto loc_it = order_locations_.find(order_id);
        if (loc_it == order_locations_.end()) {
            return false;
        }

        OrderLocation loc = loc_it->second;
        order_locations_.erase(loc_it);

        if (loc.side == Side::Buy) {
            return cancel_from_map(bids_, loc.price, order_id, cancelled_order);
        }
        return cancel_from_map(asks_, loc.price, order_id, cancelled_order);
    }

    [[nodiscard]] BidMap& bids() noexcept { return bids_; }
    [[nodiscard]] const BidMap& bids() const noexcept { return bids_; }

    [[nodiscard]] AskMap& asks() noexcept { return asks_; }
    [[nodiscard]] const AskMap& asks() const noexcept { return asks_; }

    void erase_order_index(OrderId order_id) noexcept { order_locations_.erase(order_id); }

    void clear() noexcept {
        bids_.clear();
        asks_.clear();
        order_locations_.clear();
    }

private:
    struct OrderLocation {
        Side side{Side::Buy};
        Price price{0};
    };

    template <typename MapType>
    static bool cancel_from_map(MapType& order_map, Price price, OrderId order_id,
                                Order& cancelled_order) {
        auto map_it = order_map.find(price);
        if (map_it == order_map.end()) {
            return false;
        }
        auto& queue = map_it->second;
        for (auto queue_it = queue.begin(); queue_it != queue.end(); ++queue_it) {
            if (queue_it->order_id == order_id) {
                cancelled_order = *queue_it;
                cancelled_order.cancel();
                queue.erase(queue_it);
                if (queue.empty()) {
                    order_map.erase(map_it);
                }
                return true;
            }
        }
        return false;
    }

    InstrumentId instrument_id_{0};
    BidMap bids_;
    AskMap asks_;
    std::unordered_map<OrderId, OrderLocation> order_locations_;
};

}  // namespace rexi::simulator
