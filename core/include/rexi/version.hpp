#pragma once

#include <cstdint>
#include <string_view>

namespace rexi {

/**
 * @brief Semantic version definition for the REXI platform.
 */
struct Version {
    uint32_t major{0};
    uint32_t minor{1};
    uint32_t patch{0};
    std::string_view suffix{"dev"};
};

/**
 * @brief Retrieve the structured semantic version of REXI.
 */
[[nodiscard]] constexpr Version get_version() noexcept {
    return Version{.major = 0, .minor = 1, .patch = 0, .suffix = "dev"};
}

/**
 * @brief Retrieve the formatted version string.
 */
[[nodiscard]] std::string_view get_version_string() noexcept;

/**
 * @brief Retrieve build and compiler metadata string.
 */
[[nodiscard]] std::string_view get_build_info() noexcept;

}  // namespace rexi
