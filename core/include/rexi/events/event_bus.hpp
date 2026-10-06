#pragma once

#include "rexi/events/event.hpp"
#include "rexi/events/event_dispatcher.hpp"
#include "rexi/events/spsc_ring_buffer.hpp"

#include <cstddef>
#include <cstdint>

namespace rexi::events {

/**
 * @brief Channel-based Buffered Event Bus wrapping an SPSC Ring Buffer and EventDispatcher.
 *
 * Provides both:
 * 1. Synchronous direct publish via immediate dispatch.
 * 2. Asynchronous thread-safe enqueue/poll via lock-free SPSC ring buffer.
 *
 * @tparam EventT Event envelope type (e.g. Event<TestEventPayload>).
 * @tparam Capacity Ring buffer capacity (power of 2).
 */
template <typename EventT, size_t Capacity = 1024>
class EventBus {
public:
    using QueueType = SpscRingBuffer<EventT, Capacity>;

    EventBus() = default;
    ~EventBus() = default;

    EventBus(const EventBus&) = delete;
    EventBus& operator=(const EventBus&) = delete;
    EventBus(EventBus&&) = delete;
    EventBus& operator=(EventBus&&) = delete;

    /**
     * @brief Access the underlying typed event dispatcher for subscriptions.
     */
    [[nodiscard]] EventDispatcher& dispatcher() noexcept { return dispatcher_; }

    [[nodiscard]] const EventDispatcher& dispatcher() const noexcept { return dispatcher_; }

    /**
     * @brief Publish and immediately dispatch synchronously to all subscribers.
     *
     * @param event The event envelope to dispatch.
     * @return size_t Count of invoked subscribers.
     */
    template <typename Payload>
    size_t publish_sync(const Event<Payload>& event) {
        return dispatcher_.dispatch(event);
    }

    /**
     * @brief Non-blocking publish into the SPSC buffer (Producer thread).
     *
     * @param event The event to enqueue.
     * @return true if enqueued successfully, false if the queue is full.
     */
    bool publish_async(const EventT& event) noexcept { return queue_.try_push(event); }

    /**
     * @brief Poll and process a single queued event (Consumer thread).
     *
     * @return true if an event was popped and dispatched, false if queue was empty.
     */
    bool poll_one() {
        EventT event{};
        if (queue_.try_pop(event)) {
            dispatcher_.dispatch(event);
            return true;
        }
        return false;
    }

    /**
     * @brief Poll and process all currently available events in the queue.
     *
     * @param max_batch Maximum number of events to process in one pass.
     * @return size_t Number of events processed.
     */
    size_t poll_batch(size_t max_batch = Capacity) {
        size_t processed = 0;
        while (processed < max_batch && poll_one()) {
            ++processed;
        }
        return processed;
    }

    /**
     * @brief Check whether the asynchronous queue is empty.
     */
    [[nodiscard]] bool is_queue_empty() const noexcept { return queue_.empty(); }

    /**
     * @brief Get count of pending events in the queue.
     */
    [[nodiscard]] size_t pending_count() const noexcept { return queue_.size(); }

private:
    EventDispatcher dispatcher_{};
    QueueType queue_{};
};

}  // namespace rexi::events
