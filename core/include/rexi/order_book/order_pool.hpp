#pragma once

#include "rexi/order_book/order_slot.hpp"
#include "rexi/order_book/resting_order.hpp"
#include "rexi/order_book/types.hpp"

#include <algorithm>
#include <cstdint>
#include <vector>

namespace rexi::order_book {

/**
 * @brief Configuration parameters for preallocated OrderPool.
 */
struct OrderPoolConfig {
    size_t initial_capacity{1024};
    size_t max_capacity{1024};
    bool allow_growth{false};
};

/**
 * @brief Preallocated, reusable contiguous memory pool for resting orders.
 *
 * Eliminates heap allocation during order insertions and cancellations.
 * Free slots are tracked via an intrusive free-list embedded directly in the slot structures.
 */
class OrderPool {
public:
    explicit OrderPool(const OrderPoolConfig& config = {})
        : config_(config), free_head_(kInvalidOrderHandle), allocated_count_(0) {
        size_t cap = std::max<size_t>(1, config_.initial_capacity);
        slots_.resize(cap);
        init_free_list(0, cap);
    }

    [[nodiscard]] size_t capacity() const noexcept { return slots_.size(); }
    [[nodiscard]] size_t allocated_count() const noexcept { return allocated_count_; }
    [[nodiscard]] size_t free_count() const noexcept { return slots_.size() - allocated_count_; }
    [[nodiscard]] bool is_full() const noexcept { return allocated_count_ >= slots_.size(); }
    [[nodiscard]] const OrderPoolConfig& config() const noexcept { return config_; }

    /**
     * @brief Allocate a slot from the pool and initialize it with order data.
     *
     * @param order RestingOrder to store in the allocated slot.
     * @return OrderHandle of allocated slot, or kInvalidOrderHandle if exhausted.
     */
    [[nodiscard]] OrderHandle allocate(const RestingOrder& order) {
        if (free_head_ == kInvalidOrderHandle) {
            if (config_.allow_growth && slots_.size() < config_.max_capacity) {
                grow();
            } else {
                return kInvalidOrderHandle;
            }
        }

        OrderHandle handle = free_head_;
        auto& slot = slots_[handle];
        free_head_ = slot.next;

        slot.order = order;
        slot.prev = kInvalidOrderHandle;
        slot.next = kInvalidOrderHandle;
        slot.is_occupied = true;
        ++slot.generation;
        ++allocated_count_;

        return handle;
    }

    /**
     * @brief Deallocate a slot and return it to the free-list.
     */
    void deallocate(OrderHandle handle) noexcept {
        if (handle >= slots_.size()) {
            return;
        }
        auto& slot = slots_[handle];
        if (!slot.is_occupied) {
            return;
        }
        slot.is_occupied = false;
        slot.prev = kInvalidOrderHandle;
        slot.next = free_head_;
        free_head_ = handle;
        --allocated_count_;
    }

    [[nodiscard]] bool is_valid_handle(OrderHandle handle) const noexcept {
        return handle < slots_.size() && slots_[handle].is_occupied;
    }

    [[nodiscard]] const OrderSlot& slot(OrderHandle handle) const noexcept {
        return slots_[handle];
    }

    [[nodiscard]] OrderSlot& slot(OrderHandle handle) noexcept { return slots_[handle]; }

    [[nodiscard]] const RestingOrder& order(OrderHandle handle) const noexcept {
        return slots_[handle].order;
    }

    [[nodiscard]] RestingOrder& order(OrderHandle handle) noexcept { return slots_[handle].order; }

    /**
     * @brief Clear all allocations and rebuild the free-list without reallocating vector capacity.
     */
    void clear() noexcept {
        allocated_count_ = 0;
        free_head_ = kInvalidOrderHandle;
        init_free_list(0, slots_.size());
    }

    OrderPool(const OrderPool&) = default;
    OrderPool& operator=(const OrderPool&) = default;
    OrderPool(OrderPool&&) noexcept = default;
    OrderPool& operator=(OrderPool&&) noexcept = default;
    ~OrderPool() = default;

private:
    void init_free_list(size_t start_idx, size_t count) {
        for (size_t i = start_idx; i < start_idx + count; ++i) {
            slots_[i].is_occupied = false;
            slots_[i].prev = kInvalidOrderHandle;
            slots_[i].next =
                (i + 1 < start_idx + count) ? static_cast<OrderHandle>(i + 1) : free_head_;
        }
        free_head_ = static_cast<OrderHandle>(start_idx);
    }

    void grow() {
        size_t old_size = slots_.size();
        size_t new_size = std::min(old_size * 2, config_.max_capacity);
        if (new_size <= old_size) {
            return;
        }
        slots_.resize(new_size);
        init_free_list(old_size, new_size - old_size);
    }

    OrderPoolConfig config_{};
    std::vector<OrderSlot> slots_{};
    OrderHandle free_head_{kInvalidOrderHandle};
    size_t allocated_count_{0};
};

}  // namespace rexi::order_book
