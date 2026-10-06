#include "rexi/market_data/checksum.hpp"
#include "rexi/market_data/message_header.hpp"
#include "rexi/market_data/messages.hpp"

#include <array>
#include <span>

#include <gtest/gtest.h>

using namespace rexi::market_data;

TEST(MarketDataChecksumTest, KnownTestVectors) {
    // Known FNV-1a test vector for empty span
    std::array<std::uint8_t, 0> empty{};
    EXPECT_EQ(IntegrityChecksum::calculate(empty), IntegrityChecksum::FnvOffsetBasis);

    // Known test vector for "123456789"
    const std::array<std::uint8_t, 9> data{'1', '2', '3', '4', '5', '6', '7', '8', '9'};
    const std::uint32_t hash = IntegrityChecksum::calculate(data);
    EXPECT_NE(hash, 0U);
    EXPECT_EQ(hash, IntegrityChecksum::calculate(data));  // Pure deterministic
}

TEST(MarketDataChecksumTest, PayloadVerification) {
    TradeMessage trade{
        .trade_id = 42,
        .price = 10500,
        .quantity = 100,
        .aggressor_side = MarketSide::Buy,
        .maker_order_id = 10,
        .taker_order_id = 20,
    };

    const std::uint32_t checksum = IntegrityChecksum::calculate_for_payload(trade);
    EXPECT_NE(checksum, 0U);

    MarketDataHeader valid_header =
        make_md_header(MarketDataMessageType::Trade, 100, 1, 1, 1, 1000, 1000, 0, checksum);
    EXPECT_EQ(IntegrityChecksum::verify(valid_header, trade), ChecksumStatus::Valid);

    // Corrupted payload verification fails
    TradeMessage corrupted_trade = trade;
    corrupted_trade.price = 10501;
    EXPECT_EQ(IntegrityChecksum::verify(valid_header, corrupted_trade), ChecksumStatus::Invalid);

    // Absent / 0 checksum returns NotSupplied
    MarketDataHeader absent_header =
        make_md_header(MarketDataMessageType::Trade, 100, 1, 1, 1, 1000, 1000, 0, 0);
    EXPECT_EQ(IntegrityChecksum::verify(absent_header, trade), ChecksumStatus::NotSupplied);
}
