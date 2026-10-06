#include "rexi/events/foundation_events.hpp"
#include "rexi/events/spsc_ring_buffer.hpp"

#include <atomic>
#include <thread>
#include <vector>

#include <gtest/gtest.h>

namespace rexi::events::tests {

TEST(EventConcurrencyTest, MultiThreadedProducerConsumerStress) {
    constexpr size_t QueueCapacity = 1024;
    constexpr uint64_t TotalMessages = 500'000;

    SpscRingBuffer<TestEvent, QueueCapacity> queue;
    std::atomic<bool> producer_done{false};

    std::vector<uint64_t> received_values;
    received_values.reserve(TotalMessages);

    // Producer Thread
    std::jthread producer([&queue, &producer_done]() {
        for (uint64_t seq = 0; seq < TotalMessages; ++seq) {
            const auto event =
                make_event(TestEventPayload{.value_a = seq, .value_b = seq * 2, .value_c = seq * 3},
                           SourceId::Simulator, seq);

            while (!queue.try_push(event)) {
                std::this_thread::yield();
            }
        }
        producer_done.store(true, std::memory_order_release);
    });

    // Consumer Thread
    std::jthread consumer([&queue, &producer_done, &received_values]() {
        TestEvent event{};
        uint64_t expected_seq = 0;

        while (true) {
            if (queue.try_pop(event)) {
                EXPECT_EQ(event.header.sequence_num, expected_seq);
                EXPECT_EQ(event.payload.value_a, expected_seq);
                EXPECT_EQ(event.payload.value_b, expected_seq * 2);
                EXPECT_EQ(event.payload.value_c, expected_seq * 3);
                received_values.push_back(event.payload.value_a);
                ++expected_seq;
            } else if (producer_done.load(std::memory_order_acquire)) {
                // Drain any remainder
                while (queue.try_pop(event)) {
                    EXPECT_EQ(event.header.sequence_num, expected_seq);
                    EXPECT_EQ(event.payload.value_a, expected_seq);
                    received_values.push_back(event.payload.value_a);
                    ++expected_seq;
                }
                break;
            } else {
                std::this_thread::yield();
            }
        }
    });

    producer.join();
    consumer.join();

    EXPECT_EQ(received_values.size(), TotalMessages);
    for (size_t i = 0; i < received_values.size(); ++i) {
        EXPECT_EQ(received_values[i], static_cast<uint64_t>(i));
    }
}

}  // namespace rexi::events::tests
