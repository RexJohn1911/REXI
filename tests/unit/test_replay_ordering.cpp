#include "rexi/replay/replay_event.hpp"

#include <algorithm>
#include <vector>

#include <gtest/gtest.h>

using namespace rexi::market_data;
using namespace rexi::replay;

TEST(ReplayOrderingTest, SequenceOrderingWithinSameFeed) {
    auto hdr1 = make_md_header(MarketDataMessageType::OrderBookAdd, 100, 1, 1, 10, 1000, 1000);
    auto hdr2 = make_md_header(MarketDataMessageType::OrderBookAdd, 100, 1, 1, 11, 1000, 1000);
    OrderBookAddMessage msg{};

    auto evt1 = make_replay_add(hdr1, msg, 0);
    auto evt2 = make_replay_add(hdr2, msg, 1);

    EXPECT_TRUE(evt1 < evt2);
    EXPECT_FALSE(evt2 < evt1);
}

TEST(ReplayOrderingTest, SourceTimestampOrderingAcrossDifferentFeeds) {
    auto hdr1 = make_md_header(MarketDataMessageType::OrderBookAdd, 100, 1, 1, 10, 1000, 1000);
    auto hdr2 = make_md_header(MarketDataMessageType::OrderBookAdd, 100, 2, 1, 5, 2000, 2000);
    OrderBookAddMessage msg{};

    auto evt1 = make_replay_add(hdr1, msg, 0);
    auto evt2 = make_replay_add(hdr2, msg, 1);

    // evt1 has earlier source timestamp
    EXPECT_TRUE(evt1 < evt2);
    EXPECT_FALSE(evt2 < evt1);
}

TEST(ReplayOrderingTest, EqualTimestampTieBreakByReceiveTimestamp) {
    auto hdr1 = make_md_header(MarketDataMessageType::OrderBookAdd, 100, 2, 1, 10, 1000, 1000);
    auto hdr2 = make_md_header(MarketDataMessageType::OrderBookAdd, 100, 1, 1, 10, 1000, 1500);
    OrderBookAddMessage msg{};

    auto evt1 = make_replay_add(hdr1, msg, 0);
    auto evt2 = make_replay_add(hdr2, msg, 1);

    EXPECT_TRUE(evt1 < evt2);
    EXPECT_FALSE(evt2 < evt1);
}

TEST(ReplayOrderingTest, EqualTimestampTieBreakByVenueAndFeedId) {
    auto hdr1 = make_md_header(MarketDataMessageType::OrderBookAdd, 100, 1, 1, 10, 1000, 1000);
    auto hdr2 = make_md_header(MarketDataMessageType::OrderBookAdd, 100, 2, 1, 10, 1000, 1000);
    OrderBookAddMessage msg{};

    auto evt1 = make_replay_add(hdr1, msg, 0);
    auto evt2 = make_replay_add(hdr2, msg, 1);

    EXPECT_TRUE(evt1 < evt2);
    EXPECT_FALSE(evt2 < evt1);
}

TEST(ReplayOrderingTest, DeterministicInputIndexFallback) {
    auto hdr1 = make_md_header(MarketDataMessageType::OrderBookAdd, 100, 1, 1, 10, 1000, 1000);
    auto hdr2 = make_md_header(MarketDataMessageType::OrderBookAdd, 100, 1, 1, 10, 1000, 1000);
    OrderBookAddMessage msg{};

    auto evt1 = make_replay_add(hdr1, msg, 5);
    auto evt2 = make_replay_add(hdr2, msg, 9);

    EXPECT_TRUE(evt1 < evt2);
    EXPECT_FALSE(evt2 < evt1);
}

TEST(ReplayOrderingTest, SortShuffledStreamReconstructsCanonicalOrder) {
    std::vector<ReplayEvent> canonical;
    for (uint64_t i = 1; i <= 10; ++i) {
        auto hdr =
            make_md_header(MarketDataMessageType::OrderBookAdd, 100, 1, 1, i, i * 1000, i * 1000);
        OrderBookAddMessage msg{
            .order_id = i, .side = MarketSide::Buy, .price = 100, .quantity = 10};
        canonical.push_back(make_replay_add(hdr, msg, i));
    }

    std::vector<ReplayEvent> shuffled = canonical;
    std::reverse(shuffled.begin(), shuffled.end());

    std::sort(shuffled.begin(), shuffled.end(), ReplayEventComparator{});

    for (size_t i = 0; i < canonical.size(); ++i) {
        EXPECT_EQ(shuffled[i].sequence_num(), canonical[i].sequence_num());
        EXPECT_EQ(shuffled[i].source_timestamp_ns(), canonical[i].source_timestamp_ns());
        EXPECT_EQ(shuffled[i].input_index, canonical[i].input_index);
    }
}
