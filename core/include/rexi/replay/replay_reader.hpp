#pragma once

#include "rexi/replay/replay_event.hpp"

#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

namespace rexi::replay {

/**
 * @brief Abstract interface for historical market replay input readers.
 */
class IReplayReader {
public:
    virtual ~IReplayReader() = default;

    [[nodiscard]] virtual bool has_next() const noexcept = 0;
    virtual const ReplayEvent* next() noexcept = 0;
    virtual void reset() noexcept = 0;
    [[nodiscard]] virtual size_t total_events() const noexcept = 0;
    [[nodiscard]] virtual size_t current_index() const noexcept = 0;
};

/**
 * @brief High-throughput, zero-allocation in-memory event stream reader.
 *
 * Operates directly over a contiguous span of ReplayEvents without heap churn.
 */
class InMemoryReplayReader final : public IReplayReader {
public:
    constexpr InMemoryReplayReader() noexcept = default;

    explicit constexpr InMemoryReplayReader(std::span<const ReplayEvent> events) noexcept
        : events_(events) {}

    explicit InMemoryReplayReader(const std::vector<ReplayEvent>& events) noexcept
        : events_(events.data(), events.size()) {}

    [[nodiscard]] bool has_next() const noexcept override { return cursor_ < events_.size(); }

    const ReplayEvent* next() noexcept override {
        if (cursor_ < events_.size()) {
            return &events_[cursor_++];
        }
        return nullptr;
    }

    void reset() noexcept override { cursor_ = 0; }

    [[nodiscard]] size_t total_events() const noexcept override { return events_.size(); }

    [[nodiscard]] size_t current_index() const noexcept override { return cursor_; }

    [[nodiscard]] size_t remaining() const noexcept {
        return (cursor_ < events_.size()) ? (events_.size() - cursor_) : 0;
    }

    [[nodiscard]] std::span<const ReplayEvent> events() const noexcept { return events_; }

    void set_events(std::span<const ReplayEvent> events) noexcept {
        events_ = events;
        cursor_ = 0;
    }

private:
    std::span<const ReplayEvent> events_{};
    size_t cursor_{0};
};

}  // namespace rexi::replay
