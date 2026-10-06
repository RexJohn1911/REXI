#pragma once

#include <cstdint>
#include <string_view>

namespace rexi::events {

/**
 * @brief Strongly typed source identifier for attributing internal event origins.
 */
enum class SourceId : uint16_t { Unknown = 0, Internal = 1, Simulator = 2, Engine = 3, Test = 4 };

/**
 * @brief Convert SourceId to human-readable string representation.
 */
[[nodiscard]] constexpr std::string_view to_string(SourceId id) noexcept {
    switch (id) {
        case SourceId::Unknown:
            return "Unknown";
        case SourceId::Internal:
            return "Internal";
        case SourceId::Simulator:
            return "Simulator";
        case SourceId::Engine:
            return "Engine";
        case SourceId::Test:
            return "Test";
    }
    return "InvalidSourceId";
}

}  // namespace rexi::events
