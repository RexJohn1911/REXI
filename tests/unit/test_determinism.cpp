#include "rexi/events/event_dispatcher.hpp"
#include "rexi/simulator/events.hpp"
#include "rexi/simulator/exchange.hpp"

#include <cstdint>
#include <string>
#include <vector>

#include <gtest/gtest.h>

using namespace rexi::simulator;
using namespace rexi::events;

struct SimulationLog {
    struct EventRecord {
        uint64_t sequence{0};
        uint64_t timestamp_ns{0};
        std::string event_type{};
        uint64_t entity_id{0};
        int64_t price{0};
        uint64_t quantity{0};
    };

    std::vector<OrderStatus> statuses{};
    std::vector<EventRecord> events{};

    bool operator==(const SimulationLog& other) const {
        if (statuses != other.statuses) {
            return false;
        }
        if (events.size() != other.events.size()) {
            return false;
        }
        for (size_t i = 0; i < events.size(); ++i) {
            const auto& a = events[i];
            const auto& b = other.events[i];
            if (a.sequence != b.sequence || a.timestamp_ns != b.timestamp_ns ||
                a.event_type != b.event_type || a.entity_id != b.entity_id || a.price != b.price ||
                a.quantity != b.quantity) {
                return false;
            }
        }
        return true;
    }
};

static SimulationLog run_deterministic_workload() {
    Exchange exchange;
    SimulationLog log;

    exchange.dispatcher().subscribe<OrderAcceptedPayload>(
        [&](const Event<OrderAcceptedPayload>& evt) {
            log.events.push_back({evt.payload.sequence, evt.header.timestamp_ns, "Accepted",
                                  evt.payload.order_id, evt.payload.price, evt.payload.quantity});
        });

    exchange.dispatcher().subscribe<OrderRejectedPayload>(
        [&](const Event<OrderRejectedPayload>& evt) {
            log.events.push_back({evt.header.sequence_num, evt.header.timestamp_ns, "Rejected",
                                  evt.payload.order_id, evt.payload.price, evt.payload.quantity});
        });

    exchange.dispatcher().subscribe<OrderCancelledPayload>(
        [&](const Event<OrderCancelledPayload>& evt) {
            log.events.push_back({evt.payload.sequence, evt.header.timestamp_ns, "Cancelled",
                                  evt.payload.order_id, 0, evt.payload.cancelled_quantity});
        });

    exchange.dispatcher().subscribe<OrderFilledPayload>([&](const Event<OrderFilledPayload>& evt) {
        log.events.push_back({evt.payload.sequence, evt.header.timestamp_ns, "Filled",
                              evt.payload.order_id, evt.payload.fill_price,
                              evt.payload.fill_quantity});
    });

    exchange.dispatcher().subscribe<TradeExecutedPayload>(
        [&](const Event<TradeExecutedPayload>& evt) {
            log.events.push_back({evt.payload.sequence, evt.header.timestamp_ns, "Trade",
                                  evt.payload.execution_id, evt.payload.price,
                                  evt.payload.quantity});
        });

    Instrument inst1{
        .id = 1, .tick_size = 1, .min_quantity = 1, .max_quantity = 100000, .lot_size = 1};
    Instrument inst2{
        .id = 2, .tick_size = 5, .min_quantity = 5, .max_quantity = 100000, .lot_size = 5};
    exchange.register_instrument(inst1);
    exchange.register_instrument(inst2);

    exchange.open_session();

    // Deterministic pseudo-random seed generator (LCG)
    uint64_t state = 42424242;
    auto lcg_rand = [&state]() -> uint64_t {
        state = state * 6364136223846793005ULL + 1442695040888963407ULL;
        return state;
    };

    OrderId current_order_id = 1;
    for (int i = 0; i < 1000; ++i) {
        exchange.clock().advance_by_ns(100);
        uint64_t r = lcg_rand();

        int action = static_cast<int>(r % 10);
        InstrumentId inst_id = ((r >> 4) % 2 == 0) ? 1 : 2;
        Price tick = (inst_id == 1) ? 1 : 5;
        uint64_t tick_u = static_cast<uint64_t>(tick);

        if (action < 4) {
            // Submit Limit Buy
            Price p = static_cast<Price>(1000 + (static_cast<Price>((r >> 8) % 20) * tick));
            Quantity q = static_cast<Quantity>(10 + ((r >> 12) % 10) * tick_u);
            OrderStatus st = exchange.submit_order(current_order_id++, 101, inst_id, Side::Buy,
                                                   OrderType::Limit, p, q);
            log.statuses.push_back(st);
        } else if (action < 8) {
            // Submit Limit Sell
            Price p = static_cast<Price>(1000 + (static_cast<Price>((r >> 8) % 20) * tick));
            Quantity q = static_cast<Quantity>(10 + ((r >> 12) % 10) * tick_u);
            OrderStatus st = exchange.submit_order(current_order_id++, 102, inst_id, Side::Sell,
                                                   OrderType::Limit, p, q);
            log.statuses.push_back(st);
        } else if (action == 8) {
            // Submit Market Order
            Side side = ((r >> 16) % 2 == 0) ? Side::Buy : Side::Sell;
            Quantity q = static_cast<Quantity>(5 + ((r >> 20) % 5) * tick_u);
            OrderStatus st = exchange.submit_order(current_order_id++, 103, inst_id, side,
                                                   OrderType::Market, 0, q);
            log.statuses.push_back(st);
        } else {
            // Cancel an earlier order
            if (current_order_id > 1) {
                OrderId target = 1 + (r % (current_order_id - 1));
                exchange.cancel_order(target);
            }
        }
    }

    return log;
}

TEST(SimulatorDeterminismTest, IdenticalExecutionProducesIdenticalOutputs) {
    SimulationLog run1 = run_deterministic_workload();
    SimulationLog run2 = run_deterministic_workload();

    ASSERT_EQ(run1.statuses.size(), run2.statuses.size());
    ASSERT_EQ(run1.events.size(), run2.events.size());
    EXPECT_GT(run1.events.size(), 500u);

    EXPECT_TRUE(run1 == run2);

    for (size_t i = 0; i < run1.events.size(); ++i) {
        EXPECT_EQ(run1.events[i].sequence, run2.events[i].sequence);
        EXPECT_EQ(run1.events[i].timestamp_ns, run2.events[i].timestamp_ns);
        EXPECT_EQ(run1.events[i].event_type, run2.events[i].event_type);
        EXPECT_EQ(run1.events[i].entity_id, run2.events[i].entity_id);
        EXPECT_EQ(run1.events[i].price, run2.events[i].price);
        EXPECT_EQ(run1.events[i].quantity, run2.events[i].quantity);
    }
}
