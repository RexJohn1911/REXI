#pragma once

#include <array>
#include <atomic>
#include <cstddef>
#include <new>
#include <type_traits>

namespace rexi::events {

#if defined(__cpp_lib_hardware_interference_size)
using std::hardware_destructive_interference_size;
#else
// Standard 64-byte L1 cache line size on x86_64 and ARM64
constexpr size_t hardware_destructive_interference_size = 64;
#endif

/**
 * @brief Bounded, Lock-Free, Single-Producer Single-Consumer (SPSC) Ring Buffer.
 *
 * Guarantees:
 * - Wait-free progress for single producer and single consumer.
 * - Zero dynamic heap allocation after construction.
 * - Cache-line separation to eliminate false sharing between producer and consumer cores.
 * - Explicit acquire/release memory ordering guaranteeing visibility of written payload.
 *
 * @tparam T Element type (must be trivially copyable for event pipelines)
 * @tparam Capacity Total buffer capacity, MUST be a power of 2.
 */
template <typename T, size_t Capacity>
class SpscRingBuffer {
    static_assert((Capacity > 0) && ((Capacity & (Capacity - 1)) == 0),
                  "SpscRingBuffer Capacity must be a non-zero power of 2");
    static_assert(std::is_trivially_copyable_v<T>,
                  "SpscRingBuffer payload must be trivially copyable");

public:
    static constexpr size_t IndexMask = Capacity - 1;

    constexpr SpscRingBuffer() noexcept : write_index_(0), read_index_(0) {}

    // Non-copyable and non-movable to ensure pointer stability across threads
    SpscRingBuffer(const SpscRingBuffer&) = delete;
    SpscRingBuffer& operator=(const SpscRingBuffer&) = delete;
    SpscRingBuffer(SpscRingBuffer&&) = delete;
    SpscRingBuffer& operator=(SpscRingBuffer&&) = delete;

    ~SpscRingBuffer() = default;

    /**
     * @brief Attempt to enqueue an item into the buffer (Producer only).
     *
     * @param item The value to copy into the buffer.
     * @return true if enqueued successfully, false if the queue is full.
     */
    bool try_push(const T& item) noexcept {
        const size_t current_write = write_index_.load(std::memory_order_relaxed);

        if (current_write - cached_read_index_ >= Capacity) {
            cached_read_index_ = read_index_.load(std::memory_order_acquire);
            if (current_write - cached_read_index_ >= Capacity) {
                return false;  // Buffer is full
            }
        }

        buffer_[current_write & IndexMask] = item;
        write_index_.store(current_write + 1, std::memory_order_release);
        return true;
    }

    /**
     * @brief Attempt to dequeue an item from the buffer (Consumer only).
     *
     * @param value Reference to receive the popped item.
     * @return true if an item was dequeued, false if the queue is empty.
     */
    bool try_pop(T& value) noexcept {
        const size_t current_read = read_index_.load(std::memory_order_relaxed);

        if (current_read == cached_write_index_) {
            cached_write_index_ = write_index_.load(std::memory_order_acquire);
            if (current_read == cached_write_index_) {
                return false;  // Buffer is empty
            }
        }

        value = buffer_[current_read & IndexMask];
        read_index_.store(current_read + 1, std::memory_order_release);
        return true;
    }

    /**
     * @brief Check whether the buffer is currently empty (approximate if called concurrently).
     */
    [[nodiscard]] bool empty() const noexcept {
        return read_index_.load(std::memory_order_relaxed) ==
               write_index_.load(std::memory_order_relaxed);
    }

    /**
     * @brief Check whether the buffer is currently full (approximate if called concurrently).
     */
    [[nodiscard]] bool full() const noexcept { return size() >= Capacity; }

    /**
     * @brief Get current approximate number of elements in the buffer.
     */
    [[nodiscard]] size_t size() const noexcept {
        const size_t write = write_index_.load(std::memory_order_relaxed);
        const size_t read = read_index_.load(std::memory_order_relaxed);
        return (write >= read) ? (write - read) : 0;
    }

    /**
     * @brief Get fixed capacity of the buffer.
     */
    [[nodiscard]] static constexpr size_t capacity() noexcept { return Capacity; }

private:
    // Buffer storage aligned to cache line
    alignas(hardware_destructive_interference_size) std::array<T, Capacity> buffer_{};

    // Producer state on its own dedicated cache line
    alignas(hardware_destructive_interference_size) std::atomic<size_t> write_index_{0};
    size_t cached_read_index_{0};

    // Consumer state on its own dedicated cache line
    alignas(hardware_destructive_interference_size) std::atomic<size_t> read_index_{0};
    size_t cached_write_index_{0};
};

}  // namespace rexi::events
