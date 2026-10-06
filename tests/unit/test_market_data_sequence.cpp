#include "rexi/market_data/sequence_manager.hpp"

#include <gtest/gtest.h>

using namespace rexi::market_data;

TEST(MarketDataSequenceTest, FirstSequenceInitialization) {
    SequenceManager manager(0);
    EXPECT_EQ(manager.expected_sequence(), 0U);

    // Initial message with sequence 100
    EXPECT_EQ(manager.validate_and_advance(100), SequenceStatus::Expected);
    EXPECT_EQ(manager.last_processed_sequence(), 100U);
    EXPECT_EQ(manager.expected_sequence(), 101U);
}

TEST(MarketDataSequenceTest, SequentialMessageAdvancement) {
    SequenceManager manager(1);

    for (SequenceNumber seq = 1; seq <= 10; ++seq) {
        EXPECT_EQ(manager.validate_and_advance(seq), SequenceStatus::Expected);
        EXPECT_EQ(manager.last_processed_sequence(), seq);
    }
    EXPECT_EQ(manager.expected_sequence(), 11U);
    EXPECT_EQ(manager.gap_count(), 0U);
    EXPECT_EQ(manager.duplicate_count(), 0U);
}

TEST(MarketDataSequenceTest, GapAndDuplicateDetection) {
    SequenceManager manager(1);

    EXPECT_EQ(manager.validate_and_advance(1), SequenceStatus::Expected);
    EXPECT_EQ(manager.validate_and_advance(2), SequenceStatus::Expected);

    // Gap: sequence 5 arrives when 3 was expected
    EXPECT_EQ(manager.validate_and_advance(5), SequenceStatus::Gap);
    EXPECT_EQ(manager.gap_count(), 1U);
    EXPECT_EQ(manager.expected_sequence(), 3U);  // Did not advance without fast forward

    // Duplicate: sequence 2 arrives again
    EXPECT_EQ(manager.validate_and_advance(2), SequenceStatus::Duplicate);
    EXPECT_EQ(manager.duplicate_count(), 1U);

    // Fast-forward after snapshot sync
    manager.fast_forward(6);
    EXPECT_EQ(manager.expected_sequence(), 6U);
    EXPECT_EQ(manager.validate_and_advance(6), SequenceStatus::Expected);
}

TEST(MarketDataSequenceTest, ResetBehavior) {
    SequenceManager manager(1);
    manager.validate_and_advance(1);
    manager.validate_and_advance(5);  // Gap

    EXPECT_EQ(manager.gap_count(), 1U);

    manager.reset(100);
    EXPECT_EQ(manager.expected_sequence(), 100U);
    EXPECT_EQ(manager.last_processed_sequence(), 0U);
    EXPECT_EQ(manager.gap_count(), 0U);
    EXPECT_EQ(manager.duplicate_count(), 0U);
}
