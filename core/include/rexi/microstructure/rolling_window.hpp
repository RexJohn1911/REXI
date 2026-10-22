#pragma once

#include <array>
#include <cstddef>
#include <stdexcept>
#include <type_traits>

namespace rexi::microstructure {

/**
 * @brief Zero-heap, fixed-capacity circular ring buffer for rolling window statistics.
 *
 * @tparam T Element type (must be default-constructible and copy-assignable).
 * @tparam Capacity Maximum number of elements in the ring buffer.
 */
template <typename T, std::size_t Capacity>
class FixedRingBuffer {
    static_assert(Capacity > 0, "FixedRingBuffer capacity must be greater than zero");

public:
    constexpr FixedRingBuffer() noexcept : head_(0), size_(0) {}

    /**
     * @brief Push an element to the back of the buffer, overwriting the oldest element if full.
     */
    constexpr void push_back(const T& value) noexcept {
        if (size_ < Capacity) {
            std::size_t index = (head_ + size_) % Capacity;
            buffer_[index] = value;
            ++size_;
        } else {
            // Buffer is full: overwrite head and advance head
            buffer_[head_] = value;
            head_ = (head_ + 1) % Capacity;
        }
    }

    constexpr void push_back(T&& value) noexcept {
        if (size_ < Capacity) {
            std::size_t index = (head_ + size_) % Capacity;
            buffer_[index] = std::move(value);
            ++size_;
        } else {
            buffer_[head_] = std::move(value);
            head_ = (head_ + 1) % Capacity;
        }
    }

    /**
     * @brief Clear all elements from the buffer.
     */
    constexpr void clear() noexcept {
        head_ = 0;
        size_ = 0;
    }

    [[nodiscard]] constexpr std::size_t size() const noexcept { return size_; }
    [[nodiscard]] constexpr std::size_t capacity() const noexcept { return Capacity; }
    [[nodiscard]] constexpr bool empty() const noexcept { return size_ == 0; }
    [[nodiscard]] constexpr bool full() const noexcept { return size_ == Capacity; }

    /**
     * @brief Access element by logical index (0 is oldest, size() - 1 is newest).
     */
    [[nodiscard]] constexpr const T& operator[](std::size_t index) const noexcept {
        return buffer_[(head_ + index) % Capacity];
    }

    [[nodiscard]] constexpr T& operator[](std::size_t index) noexcept {
        return buffer_[(head_ + index) % Capacity];
    }

    /**
     * @brief Access oldest element (front).
     */
    [[nodiscard]] constexpr const T& front() const noexcept {
        return buffer_[head_];
    }

    /**
     * @brief Access newest element (back).
     */
    [[nodiscard]] constexpr const T& back() const noexcept {
        return buffer_[(head_ + size_ - 1) % Capacity];
    }

private:
    std::array<T, Capacity> buffer_{};
    std::size_t head_{0};
    std::size_t size_{0};
};

} // namespace rexi::microstructure
