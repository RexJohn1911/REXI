#include "rexi/market_data/normalizer.hpp"

#include <cstdint>

#include <gtest/gtest.h>

using namespace rexi::market_data;

// Mock raw exchange feed packet representation
struct RawMockPacket {
    std::uint32_t symbol_id{0};
    std::int64_t bid_px{0};
    std::uint64_t bid_sz{0};
    std::int64_t ask_px{0};
    std::uint64_t ask_sz{0};
    std::uint64_t seq{0};
    std::uint64_t timestamp{0};
};

class MockFeedNormalizer : public INormalizer<RawMockPacket> {
public:
    MarketDataMessage normalize(const RawMockPacket& raw) override {
        MarketDataHeader header = make_md_header(MarketDataMessageType::TopOfBook, raw.symbol_id, 1,
                                                 1, raw.seq, raw.timestamp, raw.timestamp);

        TopOfBookMessage tob{
            .best_bid_price = raw.bid_px,
            .best_bid_quantity = raw.bid_sz,
            .best_ask_price = raw.ask_px,
            .best_ask_quantity = raw.ask_sz,
        };

        return MarketDataMessage{.header = header, .payload = tob};
    }
};

TEST(MarketDataNormalizerTest, NormalizedMessageExtraction) {
    MockFeedNormalizer normalizer;
    RawMockPacket raw{
        .symbol_id = 500,
        .bid_px = 15000,
        .bid_sz = 100,
        .ask_px = 15005,
        .ask_sz = 200,
        .seq = 10,
        .timestamp = 1'234'567,
    };

    MarketDataMessage msg = normalizer.normalize(raw);
    EXPECT_EQ(msg.header.instrument_id, 500U);
    EXPECT_EQ(msg.header.sequence_num, 10U);
    EXPECT_EQ(msg.header.message_type, MarketDataMessageType::TopOfBook);

    EXPECT_TRUE(msg.holds<TopOfBookMessage>());
    const auto* tob = msg.get<TopOfBookMessage>();
    ASSERT_NE(tob, nullptr);
    EXPECT_EQ(tob->best_bid_price, 15000);
    EXPECT_EQ(tob->best_bid_quantity, 100U);
    EXPECT_EQ(tob->best_ask_price, 15005);
    EXPECT_EQ(tob->best_ask_quantity, 200U);
}
