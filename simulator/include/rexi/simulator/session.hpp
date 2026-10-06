#pragma once

#include <cstdint>
#include <string_view>

namespace rexi::simulator {

/**
 * @brief Exchange session operational lifecycle states.
 */
enum class SessionState : std::uint8_t { Created = 0, Open = 1, Closed = 2 };

[[nodiscard]] constexpr std::string_view to_string(SessionState state) noexcept {
    switch (state) {
        case SessionState::Created:
            return "Created";
        case SessionState::Open:
            return "Open";
        case SessionState::Closed:
            return "Closed";
    }
    return "InvalidSessionState";
}

/**
 * @brief Exchange session state controller.
 */
class ExchangeSession {
public:
    constexpr ExchangeSession() noexcept = default;

    [[nodiscard]] constexpr SessionState state() const noexcept { return state_; }

    [[nodiscard]] constexpr bool is_open() const noexcept { return state_ == SessionState::Open; }

    constexpr void open() noexcept { state_ = SessionState::Open; }

    constexpr void close() noexcept { state_ = SessionState::Closed; }

    constexpr void reset() noexcept { state_ = SessionState::Created; }

private:
    SessionState state_{SessionState::Created};
};

}  // namespace rexi::simulator
