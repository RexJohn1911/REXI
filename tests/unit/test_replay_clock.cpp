#include "rexi/replay/replay_clock.hpp"

#include <gtest/gtest.h>

using namespace rexi::replay;

TEST(ReplayClockTest, InitialStateDefaultConstructed) {
    ReplayClock clock;
    EXPECT_FALSE(clock.is_started());
    EXPECT_EQ(clock.current_time_ns(), 0);
    EXPECT_EQ(clock.previous_time_ns(), 0);
    EXPECT_EQ(clock.first_time_ns(), 0);
    EXPECT_EQ(clock.event_index(), 0);
    EXPECT_EQ(clock.elapsed_replay_time_ns(), 0);
}

TEST(ReplayClockTest, InitialStateWithExplicitTime) {
    ReplayClock clock(500'000'000ULL);
    EXPECT_TRUE(clock.is_started());
    EXPECT_EQ(clock.current_time_ns(), 500'000'000ULL);
    EXPECT_EQ(clock.previous_time_ns(), 500'000'000ULL);
    EXPECT_EQ(clock.first_time_ns(), 500'000'000ULL);
    EXPECT_EQ(clock.event_index(), 0);
    EXPECT_EQ(clock.elapsed_replay_time_ns(), 0);
}

TEST(ReplayClockTest, AdvanceToEstablishesBaselineOnFirstEvent) {
    ReplayClock clock;
    clock.advance_to(1'000'000'000ULL);

    EXPECT_TRUE(clock.is_started());
    EXPECT_EQ(clock.first_time_ns(), 1'000'000'000ULL);
    EXPECT_EQ(clock.current_time_ns(), 1'000'000'000ULL);
    EXPECT_EQ(clock.previous_time_ns(), 1'000'000'000ULL);
    EXPECT_EQ(clock.event_index(), 1);
    EXPECT_EQ(clock.elapsed_replay_time_ns(), 0);

    // Second event 500us later
    clock.advance_to(1'000'500'000ULL);
    EXPECT_EQ(clock.first_time_ns(), 1'000'000'000ULL);
    EXPECT_EQ(clock.current_time_ns(), 1'000'500'000ULL);
    EXPECT_EQ(clock.previous_time_ns(), 1'000'000'000ULL);
    EXPECT_EQ(clock.event_index(), 2);
    EXPECT_EQ(clock.elapsed_replay_time_ns(), 500'000ULL);
}

TEST(ReplayClockTest, AdvanceToWithZeroDeltaSameTimestamp) {
    ReplayClock clock;
    clock.advance_to(100'000ULL);
    clock.advance_to(100'000ULL);
    clock.advance_to(100'000ULL);

    EXPECT_EQ(clock.current_time_ns(), 100'000ULL);
    EXPECT_EQ(clock.previous_time_ns(), 100'000ULL);
    EXPECT_EQ(clock.event_index(), 3);
    EXPECT_EQ(clock.elapsed_replay_time_ns(), 0);
}

TEST(ReplayClockTest, AdvanceByRelativeDelta) {
    ReplayClock clock;
    clock.advance_to(1'000'000ULL);
    EXPECT_EQ(clock.elapsed_replay_time_ns(), 0);

    clock.advance_by(250'000ULL);
    EXPECT_EQ(clock.current_time_ns(), 1'250'000ULL);
    EXPECT_EQ(clock.previous_time_ns(), 1'000'000ULL);
    EXPECT_EQ(clock.event_index(), 2);
    EXPECT_EQ(clock.elapsed_replay_time_ns(), 250'000ULL);
}

TEST(ReplayClockTest, ResetRestoresCleanBaseline) {
    ReplayClock clock;
    clock.advance_to(1'000'000ULL);
    clock.advance_to(2'000'000ULL);
    EXPECT_EQ(clock.event_index(), 2);
    EXPECT_EQ(clock.elapsed_replay_time_ns(), 1'000'000ULL);

    clock.reset();
    EXPECT_FALSE(clock.is_started());
    EXPECT_EQ(clock.current_time_ns(), 0);
    EXPECT_EQ(clock.previous_time_ns(), 0);
    EXPECT_EQ(clock.first_time_ns(), 0);
    EXPECT_EQ(clock.event_index(), 0);
    EXPECT_EQ(clock.elapsed_replay_time_ns(), 0);

    // Can be started anew with a different baseline
    clock.advance_to(5'000'000ULL);
    EXPECT_TRUE(clock.is_started());
    EXPECT_EQ(clock.first_time_ns(), 5'000'000ULL);
    EXPECT_EQ(clock.event_index(), 1);
}
