#pragma once

#include "rexi/market_data/message_header.hpp"
#include "rexi/market_data/types.hpp"

#include <cstddef>
#include <cstdint>
#include <span>

namespace rexi::market_data {

/**
 * @brief Fast, deterministic 32-bit FNV-1a checksum implementation for protocol verification.
 */
class IntegrityChecksum {
public:
    static constexpr std::uint32_t FnvOffsetBasis = 0x811C9DC5U;
    static constexpr std::uint32_t FnvPrime = 0x01000193U;

    /**
     * @brief Calculate 32-bit FNV-1a hash across a contiguous byte span.
     */
    [[nodiscard]] static constexpr std::uint32_t calculate(
        std::span<const std::uint8_t> bytes) noexcept {
        std::uint32_t hash = FnvOffsetBasis;
        for (const std::uint8_t byte : bytes) {
            hash ^= static_cast<std::uint32_t>(byte);
            hash *= FnvPrime;
        }
        return hash;
    }

    /**
     * @brief Calculate checksum for an arbitrary trivially copyable object.
     */
    template <typename T>
        requires std::is_trivially_copyable_v<T>
    [[nodiscard]] static constexpr std::uint32_t calculate_for_payload(const T& payload) noexcept {
        // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast)
        const auto* raw_ptr = reinterpret_cast<const std::uint8_t*>(&payload);
        return calculate(std::span<const std::uint8_t>(raw_ptr, sizeof(T)));
    }

    /**
     * @brief Verify message checksum against payload bytes.
     */
    template <typename Payload>
        requires std::is_trivially_copyable_v<Payload>
    [[nodiscard]] static ChecksumStatus verify(const MarketDataHeader& header,
                                               const Payload& payload) noexcept {
        if (header.checksum == 0) {
            return ChecksumStatus::NotSupplied;
        }
        const std::uint32_t calculated = calculate_for_payload(payload);
        return (calculated == header.checksum) ? ChecksumStatus::Valid : ChecksumStatus::Invalid;
    }
};

}  // namespace rexi::market_data
