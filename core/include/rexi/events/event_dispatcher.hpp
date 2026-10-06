#pragma once

#include "rexi/events/event.hpp"
#include "rexi/events/event_header.hpp"
#include "rexi/events/event_types.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <type_traits>
#include <vector>

namespace rexi::events {

/**
 * @brief Maximum supported distinct EventType IDs for direct table indexing.
 */
inline constexpr size_t MaxEventTypes = 256;

/**
 * @brief Deterministic, strongly typed in-process Event Dispatcher.
 *
 * Provides sub-microsecond event routing to registered handlers based on EventType.
 * Handlers are registered during configuration/initialization.
 * Dispatching is completely non-allocating.
 */
class EventDispatcher {
public:
    using RawHandler = std::function<void(const EventHeader&, const void*)>;

    EventDispatcher() = default;
    ~EventDispatcher() = default;

    EventDispatcher(const EventDispatcher&) = delete;
    EventDispatcher& operator=(const EventDispatcher&) = delete;
    EventDispatcher(EventDispatcher&&) = delete;
    EventDispatcher& operator=(EventDispatcher&&) = delete;

    /**
     * @brief Register a strongly typed handler for a specific event payload type.
     *
     * @tparam Payload The payload type (must have EventTraits specialization).
     * @param handler Callable taking const Event<Payload>&.
     */
    template <typename Payload, typename HandlerFunc>
    void subscribe(HandlerFunc&& handler) {
        constexpr auto event_type = EventTraits<Payload>::type;
        const auto type_idx = static_cast<size_t>(event_type);

        if (type_idx >= MaxEventTypes) {
            return;
        }

        handlers_[type_idx].emplace_back([fn = std::forward<HandlerFunc>(handler)](
                                             const EventHeader& header, const void* raw_payload) {
            const auto* typed_payload = static_cast<const Payload*>(raw_payload);
            const Event<Payload> event{.header = header, .payload = *typed_payload};
            fn(event);
        });
    }

    /**
     * @brief Dispatch a strongly typed event to all subscribed handlers.
     *
     * @tparam Payload The payload type.
     * @param event The event envelope to dispatch.
     * @return size_t The number of handlers invoked.
     */
    template <typename Payload>
    size_t dispatch(const Event<Payload>& event) const {
        const auto type_idx = static_cast<size_t>(event.header.type);
        if (type_idx >= MaxEventTypes) {
            return 0;
        }

        const auto& handler_list = handlers_[type_idx];
        for (const auto& handler : handler_list) {
            handler(event.header, &event.payload);
        }
        return handler_list.size();
    }

    /**
     * @brief Get the number of registered subscribers for a specific EventType.
     */
    [[nodiscard]] size_t subscriber_count(EventType type) const noexcept {
        const auto type_idx = static_cast<size_t>(type);
        if (type_idx >= MaxEventTypes) {
            return 0;
        }
        return handlers_[type_idx].size();
    }

    /**
     * @brief Clear all registered handlers.
     */
    void clear() noexcept {
        for (auto& handler_list : handlers_) {
            handler_list.clear();
        }
    }

private:
    std::array<std::vector<RawHandler>, MaxEventTypes> handlers_{};
};

}  // namespace rexi::events
