#pragma once

#include "rexi/order_book/order_slot.hpp"
#include "rexi/order_book/types.hpp"

#include <algorithm>
#include <cstdint>
#include <vector>

namespace rexi::order_book {

/**
 * @brief Entry in the flat open-addressing OrderId index table.
 */
struct alignas(8) IndexEntry {
    OrderId order_id{0};
    OrderHandle handle{kInvalidOrderHandle};
    Side side{Side::Buy};
    uint8_t reserved[3]{0};
    Price price{0};

    [[nodiscard]] constexpr bool is_empty() const noexcept { return order_id == 0; }
};

/**
 * @brief High-performance, open-addressing linear-probing hash table mapping OrderId to
 * OrderHandle.
 *
 * Employs backward-shift deletion to eliminate tombstones completely, maintaining peak lookup
 * velocity and zero heap allocations during steady-state operations.
 */
class OrderIdIndex {
public:
    explicit OrderIdIndex(size_t initial_capacity = 1024, bool allow_growth = false)
        : allow_growth_(allow_growth) {
        size_t cap = 16;
        while (cap < initial_capacity * 2) {
            cap <<= 1;
        }
        capacity_ = cap;
        mask_ = capacity_ - 1;
        table_.resize(capacity_);
    }

    [[nodiscard]] size_t size() const noexcept { return size_; }
    [[nodiscard]] size_t capacity() const noexcept { return capacity_; }
    [[nodiscard]] bool empty() const noexcept { return size_ == 0; }
    [[nodiscard]] bool allow_growth() const noexcept { return allow_growth_; }

    [[nodiscard]] bool contains(OrderId id) const noexcept { return find(id) != nullptr; }

    [[nodiscard]] const IndexEntry* find(OrderId id) const noexcept {
        if (id == 0 || size_ == 0) {
            return nullptr;
        }
        size_t idx = hash_order_id(id) & mask_;
        while (table_[idx].order_id != 0) {
            if (table_[idx].order_id == id) {
                return &table_[idx];
            }
            idx = (idx + 1) & mask_;
        }
        return nullptr;
    }

    /**
     * @brief Insert or update an OrderId mapping.
     *
     * @return true on success, false if capacity limit reached and growth is disallowed.
     */
    bool insert(OrderId id, OrderHandle handle, Side side, Price price) {
        if (id == 0) {
            return false;
        }

        // Check load factor (70%)
        if ((size_ + 1) * 10 >= capacity_ * 7) {
            if (allow_growth_) {
                grow();
            } else {
                // Check if key already exists so we can update in-place even if full
                const auto* existing = find(id);
                if (existing == nullptr) {
                    return false;
                }
            }
        }

        size_t idx = hash_order_id(id) & mask_;
        while (table_[idx].order_id != 0) {
            if (table_[idx].order_id == id) {
                table_[idx].handle = handle;
                table_[idx].side = side;
                table_[idx].price = price;
                return true;
            }
            idx = (idx + 1) & mask_;
        }

        table_[idx] = IndexEntry{
            .order_id = id,
            .handle = handle,
            .side = side,
            .reserved = {0, 0, 0},
            .price = price,
        };
        ++size_;
        return true;
    }

    /**
     * @brief Erase an OrderId using backward-shift deletion (no tombstones).
     */
    bool erase(OrderId id) noexcept {
        if (id == 0 || size_ == 0) {
            return false;
        }

        size_t idx = hash_order_id(id) & mask_;
        while (table_[idx].order_id != 0) {
            if (table_[idx].order_id == id) {
                // Backward-shift deletion
                size_t i = idx;
                size_t j = i;
                while (true) {
                    table_[i] = IndexEntry{};
                    while (true) {
                        j = (j + 1) & mask_;
                        if (table_[j].order_id == 0) {
                            --size_;
                            return true;
                        }
                        size_t k = hash_order_id(table_[j].order_id) & mask_;
                        // Does slot j belong before or at i circularly?
                        bool can_move = (i <= j) ? (k <= i || k > j) : (k <= i && k > j);
                        if (can_move) {
                            break;
                        }
                    }
                    table_[i] = table_[j];
                    i = j;
                }
            }
            idx = (idx + 1) & mask_;
        }
        return false;
    }

    void clear() noexcept {
        size_ = 0;
        std::fill(table_.begin(), table_.end(), IndexEntry{});
    }

    OrderIdIndex(const OrderIdIndex&) = default;
    OrderIdIndex& operator=(const OrderIdIndex&) = default;
    OrderIdIndex(OrderIdIndex&&) noexcept = default;
    OrderIdIndex& operator=(OrderIdIndex&&) noexcept = default;
    ~OrderIdIndex() = default;

private:
    static constexpr uint64_t hash_order_id(OrderId id) noexcept {
        uint64_t x = static_cast<uint64_t>(id);
        x ^= x >> 30;
        x *= 0xbf58476d1ce4e5b9ULL;
        x ^= x >> 27;
        x *= 0x94d049bb133111ebULL;
        x ^= x >> 31;
        return x;
    }

    void grow() {
        size_t new_cap = capacity_ * 2;
        std::vector<IndexEntry> old_table = std::move(table_);

        capacity_ = new_cap;
        mask_ = capacity_ - 1;
        table_.resize(capacity_);
        size_ = 0;

        for (const auto& entry : old_table) {
            if (entry.order_id != 0) {
                insert(entry.order_id, entry.handle, entry.side, entry.price);
            }
        }
    }

    size_t capacity_{16};
    size_t mask_{15};
    size_t size_{0};
    bool allow_growth_{false};
    std::vector<IndexEntry> table_{};
};

}  // namespace rexi::order_book
