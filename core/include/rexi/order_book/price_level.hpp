#pragma once

#include "rexi/order_book/order_pool.hpp"
#include "rexi/order_book/order_slot.hpp"
#include "rexi/order_book/resting_order.hpp"
#include "rexi/order_book/types.hpp"

#include <algorithm>
#include <cstdint>
#include <iterator>

namespace rexi::order_book {

/**
 * @brief Forward iterator for traversing orders resting in a PriceLevel without heap allocations.
 */
class PriceLevelOrderIterator {
public:
    using iterator_category = std::forward_iterator_tag;
    using value_type = RestingOrder;
    using difference_type = std::ptrdiff_t;
    using pointer = const RestingOrder*;
    using reference = const RestingOrder&;

    PriceLevelOrderIterator() = default;
    PriceLevelOrderIterator(OrderHandle handle, const OrderPool* pool) noexcept
        : current_(handle), pool_(pool) {}

    reference operator*() const noexcept { return pool_->order(current_); }
    pointer operator->() const noexcept { return &pool_->order(current_); }

    PriceLevelOrderIterator& operator++() noexcept {
        if (pool_ != nullptr && current_ != kInvalidOrderHandle) {
            current_ = pool_->slot(current_).next;
        }
        return *this;
    }

    PriceLevelOrderIterator operator++(int) noexcept {
        auto tmp = *this;
        ++(*this);
        return tmp;
    }

    bool operator==(const PriceLevelOrderIterator& other) const noexcept {
        return current_ == other.current_ && pool_ == other.pool_;
    }
    bool operator!=(const PriceLevelOrderIterator& other) const noexcept {
        return !(*this == other);
    }

    [[nodiscard]] OrderHandle handle() const noexcept { return current_; }

private:
    OrderHandle current_{kInvalidOrderHandle};
    const OrderPool* pool_{nullptr};
};

/**
 * @brief Price level maintaining aggregated L2 quantities and an intrusive FIFO L3 order queue.
 *
 * Backed by handles indexing into an OrderPool. Does not allocate heap memory.
 */
class PriceLevel {
public:
    explicit PriceLevel(Price price = 0) noexcept : price_(price) {}

    [[nodiscard]] Price price() const noexcept { return price_; }
    [[nodiscard]] Quantity total_quantity() const noexcept { return total_quantity_; }
    [[nodiscard]] uint32_t order_count() const noexcept { return order_count_; }
    [[nodiscard]] bool is_empty() const noexcept { return order_count_ == 0; }
    [[nodiscard]] bool is_l2_aggregate_only() const noexcept { return is_l2_aggregate_only_; }
    [[nodiscard]] OrderHandle head() const noexcept { return head_; }
    [[nodiscard]] OrderHandle tail() const noexcept { return tail_; }

    /**
     * @brief Append a slot handle to the back of the FIFO queue in O(1) time.
     */
    void push_back(OrderHandle handle, Quantity qty, OrderPool& pool) noexcept {
        total_quantity_ += qty;
        ++order_count_;
        is_l2_aggregate_only_ = false;

        auto& slot = pool.slot(handle);
        slot.prev = tail_;
        slot.next = kInvalidOrderHandle;
        if (tail_ != kInvalidOrderHandle) {
            pool.slot(tail_).next = handle;
        } else {
            head_ = handle;
        }
        tail_ = handle;
    }

    /**
     * @brief Erase a slot handle from the intrusive queue in O(1) time.
     */
    void erase(OrderHandle handle, OrderPool& pool) noexcept {
        if (handle == kInvalidOrderHandle || !pool.is_valid_handle(handle)) {
            return;
        }
        auto& slot = pool.slot(handle);
        total_quantity_ -= slot.order.remaining_quantity;
        if (order_count_ > 0) {
            --order_count_;
        }

        if (slot.prev != kInvalidOrderHandle) {
            pool.slot(slot.prev).next = slot.next;
        } else {
            head_ = slot.next;
        }

        if (slot.next != kInvalidOrderHandle) {
            pool.slot(slot.next).prev = slot.prev;
        } else {
            tail_ = slot.prev;
        }

        slot.prev = kInvalidOrderHandle;
        slot.next = kInvalidOrderHandle;
    }

    /**
     * @brief Reduce the remaining quantity of an order in O(1) time.
     */
    void reduce(OrderHandle handle, Quantity executed_qty, OrderPool& pool) noexcept {
        auto& slot = pool.slot(handle);
        Quantity actual_red = std::min(executed_qty, slot.order.remaining_quantity);
        slot.order.remaining_quantity -= actual_red;
        total_quantity_ -= actual_red;
    }

    /**
     * @brief Add quantity to the level aggregate.
     */
    void add_quantity(Quantity qty) noexcept { total_quantity_ += qty; }

    /**
     * @brief Move an existing order handle to the back of the FIFO queue (loses priority).
     */
    void move_to_back(OrderHandle handle, OrderPool& pool) noexcept {
        if (handle == tail_ || handle == kInvalidOrderHandle) {
            return;
        }
        auto& slot = pool.slot(handle);

        // Unlink from current position
        if (slot.prev != kInvalidOrderHandle) {
            pool.slot(slot.prev).next = slot.next;
        } else {
            head_ = slot.next;
        }

        if (slot.next != kInvalidOrderHandle) {
            pool.slot(slot.next).prev = slot.prev;
        }

        // Re-link at tail
        slot.prev = tail_;
        slot.next = kInvalidOrderHandle;
        if (tail_ != kInvalidOrderHandle) {
            pool.slot(tail_).next = handle;
        }
        tail_ = handle;
    }

    /**
     * @brief Set aggregated quantities from an external L2 snapshot without individual L3 orders.
     */
    void set_l2_aggregate(Quantity total_qty, uint32_t count) noexcept {
        total_quantity_ = total_qty;
        order_count_ = count;
        is_l2_aggregate_only_ = true;
        head_ = kInvalidOrderHandle;
        tail_ = kInvalidOrderHandle;
    }

    /**
     * @brief Traverse orders in FIFO priority.
     */
    template <typename Fn>
    void for_each_order(const OrderPool& pool, Fn&& fn) const {
        OrderHandle curr = head_;
        while (curr != kInvalidOrderHandle) {
            const auto& slot = pool.slot(curr);
            fn(slot.order);
            curr = slot.next;
        }
    }

    [[nodiscard]] PriceLevelOrderIterator begin(const OrderPool& pool) const noexcept {
        return PriceLevelOrderIterator(head_, &pool);
    }

    [[nodiscard]] PriceLevelOrderIterator end(const OrderPool& pool) const noexcept {
        return PriceLevelOrderIterator(kInvalidOrderHandle, &pool);
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
    OrderHandle head_{kInvalidOrderHandle};
    OrderHandle tail_{kInvalidOrderHandle};
};

}  // namespace rexi::order_book
