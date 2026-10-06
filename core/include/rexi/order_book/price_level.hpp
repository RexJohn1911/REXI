#pragma once

#include "rexi/order_book/resting_order.hpp"
#include "rexi/order_book/types.hpp"

#include <cstdint>
#include <iterator>
#include <list>

namespace rexi::order_book {

/**
 * @brief Price level maintaining aggregated L2 quantities and a strict FIFO L3 order queue.
 */
class PriceLevel {
public:
    using OrderList = std::list<RestingOrder>;
    using OrderIterator = OrderList::iterator;
    using ConstOrderIterator = OrderList::const_iterator;

    explicit PriceLevel(Price price = 0) noexcept : price_(price) {}

    [[nodiscard]] Price price() const noexcept { return price_; }
    [[nodiscard]] Quantity total_quantity() const noexcept { return total_quantity_; }
    [[nodiscard]] uint32_t order_count() const noexcept { return order_count_; }
    [[nodiscard]] bool is_empty() const noexcept { return order_count_ == 0; }
    [[nodiscard]] bool is_l2_aggregate_only() const noexcept { return is_l2_aggregate_only_; }

    [[nodiscard]] const OrderList& orders() const noexcept { return orders_; }
    [[nodiscard]] OrderList& orders() noexcept { return orders_; }

    /**
     * @brief Append a new resting order to the back of the FIFO queue.
     */
    OrderIterator push_back(const RestingOrder& order) {
        total_quantity_ += order.remaining_quantity;
        ++order_count_;
        is_l2_aggregate_only_ = false;
        return orders_.insert(orders_.end(), order);
    }

    /**
     * @brief Erase a resting order by iterator in O(1) time.
     */
    void erase(OrderIterator order_it) {
        if (order_it != orders_.end()) {
            total_quantity_ -= order_it->remaining_quantity;
            if (order_count_ > 0) {
                --order_count_;
            }
            orders_.erase(order_it);
        }
    }

    /**
     * @brief Reduce the remaining quantity of an order in O(1) time.
     */
    void reduce(OrderIterator order_it, Quantity executed_qty) noexcept {
        Quantity actual_red = std::min(executed_qty, order_it->remaining_quantity);
        order_it->remaining_quantity -= actual_red;
        total_quantity_ -= actual_red;
    }

    /**
     * @brief Add quantity to the level aggregate.
     */
    void add_quantity(Quantity qty) noexcept { total_quantity_ += qty; }

    /**
     * @brief Move an existing order to the back of the FIFO queue (lose priority).
     */
    void move_to_back(OrderIterator order_it) {
        if (order_it != orders_.end() && std::next(order_it) != orders_.end()) {
            orders_.splice(orders_.end(), orders_, order_it);
        }
    }

    /**
     * @brief Set aggregated quantities from an external L2 snapshot without individual L3 orders.
     */
    // NOLINTNEXTLINE(bugprone-easily-swappable-parameters)
    void set_l2_aggregate(Quantity total_qty, uint32_t count) noexcept {
        total_quantity_ = total_qty;
        order_count_ = count;
        is_l2_aggregate_only_ = true;
        orders_.clear();
    }

    /**
     * @brief Generate an immutable LevelView snapshot of this price level.
     */
    [[nodiscard]] LevelView to_view() const noexcept {
        return LevelView{
            .price = price_,
            .total_quantity = total_quantity_,
            .order_count = order_count_,
        };
    }

private:
    Price price_{0};
    Quantity total_quantity_{0};
    uint32_t order_count_{0};
    bool is_l2_aggregate_only_{false};
    OrderList orders_;
};

}  // namespace rexi::order_book
