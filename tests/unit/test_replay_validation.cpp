#include "rexi/replay/replay_engine.hpp"
#include "rexi/replay/synthetic_generator.hpp"

#include <gtest/gtest.h>

using namespace rexi::market_data;
using namespace rexi::replay;

TEST(ReplayValidationTest, CleanStreamProducesZeroErrors) {
    auto events = SyntheticReplayFixtureGenerator::create_basic_l3_stream();
    InMemoryReplayReader reader(events);

    ReplayConfig config{
        .validation_policy = ValidationPolicy::Strict,
        .verify_sequence = true,
        .verify_checksum = false,
    };
    ReplayEngine engine(100, config);
    auto res = engine.run(reader);

    EXPECT_TRUE(res.is_clean);
    EXPECT_EQ(res.stats.events_processed, events.size());
    EXPECT_EQ(res.stats.validation_failures, 0);
    EXPECT_EQ(res.stats.sequence_gaps, 0);
    EXPECT_EQ(res.stats.duplicates, 0);
    EXPECT_EQ(res.stats.out_of_order, 0);
    EXPECT_TRUE(res.diagnostics.empty());
}

TEST(ReplayValidationTest, SequenceGapStrictHaltVsPermissiveContinue) {
    auto events = SyntheticReplayFixtureGenerator::create_gapped_stream();

    // 1. Strict Mode: halts immediately at the gap (event 2)
    {
        InMemoryReplayReader reader(events);
        ReplayConfig config{.validation_policy = ValidationPolicy::Strict};
        ReplayEngine engine(100, config);
        auto res = engine.run(reader);

        EXPECT_FALSE(res.is_clean);
        EXPECT_EQ(res.stats.events_processed, 1);  // Only first event processed
        EXPECT_EQ(res.stats.sequence_gaps, 1);
        ASSERT_FALSE(res.diagnostics.empty());
        EXPECT_EQ(res.diagnostics[0].sequence_status, SequenceStatus::Gap);
    }

    // 2. Permissive Mode: records gap diagnostic and processes remaining events
    {
        InMemoryReplayReader reader(events);
        ReplayConfig config{.validation_policy = ValidationPolicy::Permissive};
        ReplayEngine engine(100, config);
        auto res = engine.run(reader);

        EXPECT_FALSE(res.is_clean);
        EXPECT_EQ(res.stats.events_processed, 2);
        EXPECT_EQ(res.stats.sequence_gaps, 1);
        ASSERT_EQ(res.diagnostics.size(), 1);
        EXPECT_EQ(res.diagnostics[0].sequence_status, SequenceStatus::Gap);
    }
}

TEST(ReplayValidationTest, DuplicateSequenceDetection) {
    auto events = SyntheticReplayFixtureGenerator::create_duplicate_stream();

    // Strict Mode: halts on duplicate
    {
        InMemoryReplayReader reader(events);
        ReplayConfig config{.validation_policy = ValidationPolicy::Strict};
        ReplayEngine engine(100, config);
        auto res = engine.run(reader);

        EXPECT_FALSE(res.is_clean);
        EXPECT_EQ(res.stats.events_processed, 2);
        EXPECT_EQ(res.stats.duplicates, 1);
        EXPECT_EQ(res.stats.events_rejected, 1);
    }

    // Permissive Mode: rejects duplicate, skips it, continues
    {
        InMemoryReplayReader reader(events);
        ReplayConfig config{.validation_policy = ValidationPolicy::Permissive};
        ReplayEngine engine(100, config);
        auto res = engine.run(reader);

        EXPECT_FALSE(res.is_clean);
        EXPECT_EQ(res.stats.events_processed, 2);
        EXPECT_EQ(res.stats.duplicates, 1);
        EXPECT_EQ(res.stats.events_rejected, 1);
    }
}

TEST(ReplayValidationTest, OutOfOrderSequenceDetection) {
    auto events = SyntheticReplayFixtureGenerator::create_out_of_order_stream();

    // Strict Mode: seq 1, seq 3 (gap detected on 3), halts
    {
        InMemoryReplayReader reader(events);
        ReplayConfig config{.validation_policy = ValidationPolicy::Strict};
        ReplayEngine engine(100, config);
        auto res = engine.run(reader);

        EXPECT_FALSE(res.is_clean);
        EXPECT_EQ(res.stats.sequence_gaps, 1);
    }

    // Permissive Mode: detects out-of-order on seq 2 arriving after seq 3
    {
        InMemoryReplayReader reader(events);
        ReplayConfig config{.validation_policy = ValidationPolicy::Permissive};
        ReplayEngine engine(100, config);
        auto res = engine.run(reader);

        EXPECT_FALSE(res.is_clean);
        EXPECT_EQ(res.stats.sequence_gaps, 1);
        EXPECT_EQ(res.stats.out_of_order, 1);
        EXPECT_EQ(res.stats.events_rejected, 1);  // event 3 was rejected as out-of-order
    }
}

TEST(ReplayValidationTest, MalformedPayloadStrictVsPermissive) {
    auto events = SyntheticReplayFixtureGenerator::create_invalid_event_stream();

    // Strict Mode: halts on invalid price
    {
        InMemoryReplayReader reader(events);
        ReplayConfig config{.validation_policy = ValidationPolicy::Strict};
        ReplayEngine engine(100, config);
        auto res = engine.run(reader);

        EXPECT_FALSE(res.is_clean);
        EXPECT_EQ(res.stats.events_processed, 1);
        EXPECT_EQ(res.stats.validation_failures, 1);
        EXPECT_EQ(res.stats.events_rejected, 1);
    }

    // Permissive Mode: rejects malformed payload and continues
    {
        InMemoryReplayReader reader(events);
        ReplayConfig config{.validation_policy = ValidationPolicy::Permissive};
        ReplayEngine engine(100, config);
        auto res = engine.run(reader);

        EXPECT_FALSE(res.is_clean);
        EXPECT_EQ(res.stats.events_processed, 1);
        EXPECT_EQ(res.stats.validation_failures, 1);
        EXPECT_EQ(res.stats.events_rejected, 1);
        ASSERT_EQ(res.diagnostics.size(), 1);
        EXPECT_EQ(res.diagnostics[0].validation_status, ValidationStatus::InvalidPrice);
    }
}

TEST(ReplayValidationTest, ChecksumVerificationFailureDetection) {
    auto events = SyntheticReplayFixtureGenerator::create_checksum_corrupted_stream();

    InMemoryReplayReader reader(events);
    ReplayConfig config{
        .validation_policy = ValidationPolicy::Strict,
        .verify_checksum = true,
    };
    ReplayEngine engine(100, config);
    auto res = engine.run(reader);

    EXPECT_FALSE(res.is_clean);
    EXPECT_EQ(res.stats.checksum_failures, 1);
    EXPECT_EQ(res.stats.events_rejected, 1);
    ASSERT_EQ(res.diagnostics.size(), 1);
    EXPECT_EQ(res.diagnostics[0].checksum_status, ChecksumStatus::Invalid);
}
