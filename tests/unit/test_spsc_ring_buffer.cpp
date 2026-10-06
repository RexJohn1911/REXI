#include "rexi/events/spsc_ring_buffer.hpp"

#include <gtest/gtest.h>

namespace rexi::events::tests {

TEST(SpscRingBufferTest, InitialStateEmpty) {
    SpscRingBuffer<uint64_t, 8> buffer;
    EXPECT_TRUE(buffer.empty());
    EXPECT_FALSE(buffer.full());
    EXPECT_EQ(buffer.size(), 0U);
    EXPECT_EQ(buffer.capacity(), 8U);

    uint64_t val = 0;
    EXPECT_FALSE(buffer.try_pop(val));
}

TEST(SpscRingBufferTest, PushAndPopSingleElement) {
    SpscRingBuffer<uint64_t, 8> buffer;
    EXPECT_TRUE(buffer.try_push(42ULL));
    EXPECT_FALSE(buffer.empty());
    EXPECT_EQ(buffer.size(), 1U);

    uint64_t val = 0;
    EXPECT_TRUE(buffer.try_pop(val));
    EXPECT_EQ(val, 42ULL);
    EXPECT_TRUE(buffer.empty());
    EXPECT_EQ(buffer.size(), 0U);
}

TEST(SpscRingBufferTest, CapacityLimitAndFullBehavior) {
    constexpr size_t Cap = 4;
    SpscRingBuffer<uint32_t, Cap> buffer;

    for (uint32_t i = 0; i < Cap; ++i) {
        EXPECT_TRUE(buffer.try_push(i + 10U));
    }

    EXPECT_TRUE(buffer.full());
    EXPECT_EQ(buffer.size(), Cap);

    // Further push should fail deterministically
    EXPECT_FALSE(buffer.try_push(999U));

    // Pop all elements and verify FIFO
    for (uint32_t i = 0; i < Cap; ++i) {
        uint32_t out = 0;
        EXPECT_TRUE(buffer.try_pop(out));
        EXPECT_EQ(out, i + 10U);
    }

    EXPECT_TRUE(buffer.empty());
}

TEST(SpscRingBufferTest, IndexWraparoundStress) {
    constexpr size_t Cap = 16;
    SpscRingBuffer<uint64_t, Cap> buffer;
    constexpr uint64_t TotalIterations = 100'000;

    for (uint64_t i = 0; i < TotalIterations; ++i) {
        EXPECT_TRUE(buffer.try_push(i));
        uint64_t val = 0;
        EXPECT_TRUE(buffer.try_pop(val));
        EXPECT_EQ(val, i);
    }

    EXPECT_TRUE(buffer.empty());
}

}  // namespace rexi::events::tests
