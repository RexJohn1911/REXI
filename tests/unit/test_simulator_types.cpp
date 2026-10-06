#include "rexi/simulator/exchange.hpp"
#include "rexi/simulator/instrument.hpp"
#include "rexi/simulator/order.hpp"
#include "rexi/simulator/session.hpp"
#include "rexi/simulator/types.hpp"

#include <gtest/gtest.h>

using namespace rexi::simulator;

TEST(SimulatorTypesTest, StringConversions) {
    EXPECT_EQ(to_string(Side::Buy), "Buy");
    EXPECT_EQ(to_string(Side::Sell), "Sell");

    EXPECT_EQ(to_string(OrderType::Limit), "Limit");
    EXPECT_EQ(to_string(OrderType::Market), "Market");

    EXPECT_EQ(to_string(OrderStatus::New), "New");
    EXPECT_EQ(to_string(OrderStatus::Accepted), "Accepted");
    EXPECT_EQ(to_string(OrderStatus::PartiallyFilled), "PartiallyFilled");
    EXPECT_EQ(to_string(OrderStatus::Filled), "Filled");
    EXPECT_EQ(to_string(OrderStatus::Cancelled), "Cancelled");
    EXPECT_EQ(to_string(OrderStatus::Rejected), "Rejected");

    EXPECT_EQ(to_string(RejectReason::None), "None");
    EXPECT_EQ(to_string(RejectReason::SessionClosed), "SessionClosed");
    EXPECT_EQ(to_string(RejectReason::UnknownInstrument), "UnknownInstrument");
    EXPECT_EQ(to_string(RejectReason::InvalidQuantity), "InvalidQuantity");
    EXPECT_EQ(to_string(RejectReason::InvalidPrice), "InvalidPrice");
    EXPECT_EQ(to_string(RejectReason::DuplicateOrderId), "DuplicateOrderId");
    EXPECT_EQ(to_string(RejectReason::OrderNotFound), "OrderNotFound");
    EXPECT_EQ(to_string(RejectReason::OrderNotActive), "OrderNotActive");
    EXPECT_EQ(to_string(RejectReason::UnsupportedOrderType), "UnsupportedOrderType");

    EXPECT_EQ(to_string(SessionState::Created), "Created");
    EXPECT_EQ(to_string(SessionState::Open), "Open");
    EXPECT_EQ(to_string(SessionState::Closed), "Closed");
}

TEST(SimulatorTypesTest, OrderLifecycleAndFill) {
    Order order{
        .order_id = 1,
        .client_id = 10,
        .instrument_id = 100,
        .side = Side::Buy,
        .type = OrderType::Limit,
        .price = 10000,
        .initial_quantity = 100,
        .remaining_quantity = 100,
        .filled_quantity = 0,
        .priority_seq = 1,
        .status = OrderStatus::Accepted,
        .accepted_timestamp_ns = 1'000'000,
    };

    EXPECT_TRUE(order.is_active());

    // Partial fill
    order.fill(40);
    EXPECT_EQ(order.filled_quantity, 40);
    EXPECT_EQ(order.remaining_quantity, 60);
    EXPECT_EQ(order.status, OrderStatus::PartiallyFilled);
    EXPECT_TRUE(order.is_active());

    // Complete fill
    order.fill(60);
    EXPECT_EQ(order.filled_quantity, 100);
    EXPECT_EQ(order.remaining_quantity, 0);
    EXPECT_EQ(order.status, OrderStatus::Filled);
    EXPECT_FALSE(order.is_active());
}

TEST(SimulatorTypesTest, OrderCancellation) {
    Order order{
        .order_id = 2,
        .client_id = 10,
        .instrument_id = 100,
        .side = Side::Sell,
        .type = OrderType::Limit,
        .price = 10500,
        .initial_quantity = 50,
        .remaining_quantity = 50,
        .filled_quantity = 0,
        .priority_seq = 2,
        .status = OrderStatus::Accepted,
        .accepted_timestamp_ns = 2'000'000,
    };

    EXPECT_TRUE(order.is_active());
    order.cancel();
    EXPECT_EQ(order.status, OrderStatus::Cancelled);
    EXPECT_FALSE(order.is_active());
}

TEST(SimulatorTypesTest, InstrumentOrderValidation) {
    Instrument inst{
        .id = 1,
        .tick_size = 5,
        .min_quantity = 10,
        .max_quantity = 1000,
        .lot_size = 10,
    };

    RejectReason reason = RejectReason::None;

    // Valid limit order
    EXPECT_TRUE(inst.validate_order(Side::Buy, OrderType::Limit, 1005, 50, reason));
    EXPECT_EQ(reason, RejectReason::None);

    // Invalid price (not multiple of tick_size 5)
    EXPECT_FALSE(inst.validate_order(Side::Buy, OrderType::Limit, 1003, 50, reason));
    EXPECT_EQ(reason, RejectReason::InvalidPrice);

    // Invalid price (zero or negative)
    EXPECT_FALSE(inst.validate_order(Side::Buy, OrderType::Limit, 0, 50, reason));
    EXPECT_EQ(reason, RejectReason::InvalidPrice);
    EXPECT_FALSE(inst.validate_order(Side::Buy, OrderType::Limit, -50, 50, reason));
    EXPECT_EQ(reason, RejectReason::InvalidPrice);

    // Invalid quantity (< min_quantity)
    EXPECT_FALSE(inst.validate_order(Side::Buy, OrderType::Limit, 1005, 5, reason));
    EXPECT_EQ(reason, RejectReason::InvalidQuantity);

    // Invalid quantity (> max_quantity)
    EXPECT_FALSE(inst.validate_order(Side::Buy, OrderType::Limit, 1005, 2000, reason));
    EXPECT_EQ(reason, RejectReason::InvalidQuantity);

    // Invalid quantity (not multiple of lot_size 10)
    EXPECT_FALSE(inst.validate_order(Side::Buy, OrderType::Limit, 1005, 55, reason));
    EXPECT_EQ(reason, RejectReason::InvalidQuantity);

    // Valid market order (price 0 allowed)
    EXPECT_TRUE(inst.validate_order(Side::Sell, OrderType::Market, 0, 50, reason));
    EXPECT_EQ(reason, RejectReason::None);
}

TEST(SimulatorTypesTest, SessionLifecycle) {
    ExchangeSession session;
    EXPECT_EQ(session.state(), SessionState::Created);
    EXPECT_FALSE(session.is_open());

    session.open();
    EXPECT_EQ(session.state(), SessionState::Open);
    EXPECT_TRUE(session.is_open());

    session.close();
    EXPECT_EQ(session.state(), SessionState::Closed);
    EXPECT_FALSE(session.is_open());

    session.reset();
    EXPECT_EQ(session.state(), SessionState::Created);
    EXPECT_FALSE(session.is_open());
}
