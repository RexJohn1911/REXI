#include "rexi/events/event_dispatcher.hpp"
#include "rexi/simulator/events.hpp"
#include "rexi/simulator/exchange.hpp"

#include <gtest/gtest.h>

using namespace rexi::simulator;
using namespace rexi::events;

class ExchangeTest : public ::testing::Test {
protected:
    void SetUp() override {
        Instrument inst{
            .id = 1,
            .tick_size = 1,
            .min_quantity = 1,
            .max_quantity = 10000,
            .lot_size = 1,
        };
        exchange_.register_instrument(inst);
    }

    Exchange& exchange() noexcept { return exchange_; }

private:
    Exchange exchange_{};
};

TEST_F(ExchangeTest, RejectsWhenSessionClosed) {
    uint32_t rejected_events = 0;
    RejectReason last_reason = RejectReason::None;

    exchange().dispatcher().subscribe<OrderRejectedPayload>(
        [&](const Event<OrderRejectedPayload>& evt) {
            ++rejected_events;
            last_reason = evt.payload.reason;
        });

    // Session is closed by default
    EXPECT_FALSE(exchange().is_open());
    OrderStatus status = exchange().submit_order(1, 10, 1, Side::Buy, OrderType::Limit, 100, 10);

    EXPECT_EQ(status, OrderStatus::Rejected);
    EXPECT_EQ(rejected_events, 1);
    EXPECT_EQ(last_reason, RejectReason::SessionClosed);
}

TEST_F(ExchangeTest, OrderAcceptedAndEventEmitted) {
    exchange().open_session();
    exchange().clock().set_time_ns(123456789);

    uint32_t accepted_events = 0;
    SequenceNum recorded_seq = 0;
    TimestampNs recorded_time = 0;

    exchange().dispatcher().subscribe<OrderAcceptedPayload>(
        [&](const Event<OrderAcceptedPayload>& evt) {
            ++accepted_events;
            recorded_seq = evt.payload.sequence;
            recorded_time = evt.header.timestamp_ns;
        });

    OrderStatus status = exchange().submit_order(1, 10, 1, Side::Buy, OrderType::Limit, 100, 10);

    EXPECT_EQ(status, OrderStatus::Accepted);
    EXPECT_EQ(accepted_events, 1);
    EXPECT_EQ(recorded_seq, 1);
    EXPECT_EQ(recorded_time, 123456789);
}

TEST_F(ExchangeTest, DuplicateOrderRejected) {
    exchange().open_session();

    uint32_t rejected_events = 0;
    RejectReason reason = RejectReason::None;

    exchange().dispatcher().subscribe<OrderRejectedPayload>(
        [&](const Event<OrderRejectedPayload>& evt) {
            ++rejected_events;
            reason = evt.payload.reason;
        });

    OrderStatus status1 = exchange().submit_order(1, 10, 1, Side::Buy, OrderType::Limit, 100, 10);
    EXPECT_EQ(status1, OrderStatus::Accepted);

    OrderStatus status2 = exchange().submit_order(1, 10, 1, Side::Buy, OrderType::Limit, 100, 10);
    EXPECT_EQ(status2, OrderStatus::Rejected);
    EXPECT_EQ(rejected_events, 1);
    EXPECT_EQ(reason, RejectReason::DuplicateOrderId);
}

TEST_F(ExchangeTest, FullFillGeneratesAllEvents) {
    exchange().open_session();

    uint32_t fill_events = 0;
    uint32_t trade_events = 0;
    uint32_t quote_events = 0;

    exchange().dispatcher().subscribe<OrderFilledPayload>(
        [&](const Event<OrderFilledPayload>&) { ++fill_events; });
    exchange().dispatcher().subscribe<TradeExecutedPayload>(
        [&](const Event<TradeExecutedPayload>&) { ++trade_events; });
    exchange().dispatcher().subscribe<TopQuoteUpdatedPayload>(
        [&](const Event<TopQuoteUpdatedPayload>&) { ++quote_events; });

    // Resting sell
    exchange().submit_order(1, 10, 1, Side::Sell, OrderType::Limit, 105, 20);

    // Incoming crossing buy
    exchange().submit_order(2, 20, 1, Side::Buy, OrderType::Limit, 105, 20);

    // Both taker and maker generate OrderFilled event = 2
    EXPECT_EQ(fill_events, 2);
    // Public trade event = 1
    EXPECT_EQ(trade_events, 1);
    // Quote updates after each order = 2
    EXPECT_EQ(quote_events, 2);
}

TEST_F(ExchangeTest, CancelEmitsOrderCancelledEvent) {
    exchange().open_session();

    uint32_t cancel_events = 0;
    exchange().dispatcher().subscribe<OrderCancelledPayload>(
        [&](const Event<OrderCancelledPayload>& evt) {
            ++cancel_events;
            EXPECT_EQ(evt.payload.order_id, 1);
            EXPECT_EQ(evt.payload.cancelled_quantity, 30);
        });

    exchange().submit_order(1, 10, 1, Side::Buy, OrderType::Limit, 100, 30);
    EXPECT_TRUE(exchange().cancel_order(1));
    EXPECT_EQ(cancel_events, 1);
}
