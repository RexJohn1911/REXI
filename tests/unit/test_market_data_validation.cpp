#include "rexi/market_data/message_header.hpp"
#include "rexi/market_data/messages.hpp"
#include "rexi/market_data/validator.hpp"

#include <gtest/gtest.h>

using namespace rexi::market_data;

TEST(MarketDataValidationTest, HeaderValidation) {
    MarketDataHeader valid_header =
        make_md_header(MarketDataMessageType::TopOfBook, 100, 1, 1, 10, 1000, 1000);
    EXPECT_EQ(MessageValidator::validate_header(valid_header), ValidationStatus::Valid);

    // Invalid protocol version
    MarketDataHeader bad_version = valid_header;
    bad_version.version = 999;
    EXPECT_EQ(MessageValidator::validate_header(bad_version), ValidationStatus::InvalidVersion);

    // Invalid zero instrument
    MarketDataHeader bad_inst = valid_header;
    bad_inst.instrument_id = 0;
    EXPECT_EQ(MessageValidator::validate_header(bad_inst, true),
              ValidationStatus::InvalidInstrument);

    // Invalid zero sequence number
    MarketDataHeader bad_seq = valid_header;
    bad_seq.sequence_num = 0;
    EXPECT_EQ(MessageValidator::validate_header(bad_seq), ValidationStatus::InvalidSequence);
}

TEST(MarketDataValidationTest, TopOfBookValidation) {
    MarketDataHeader header =
        make_md_header(MarketDataMessageType::TopOfBook, 100, 1, 1, 10, 1000, 1000);

    TopOfBookMessage valid_tob{.best_bid_price = 100,
                               .best_bid_quantity = 10,
                               .best_ask_price = 105,
                               .best_ask_quantity = 20};
    EXPECT_EQ(MessageValidator::validate(header, valid_tob), ValidationStatus::Valid);

    // Crossed book (bid > ask)
    TopOfBookMessage crossed_tob{.best_bid_price = 110,
                                 .best_bid_quantity = 10,
                                 .best_ask_price = 105,
                                 .best_ask_quantity = 20};
    EXPECT_EQ(MessageValidator::validate(header, crossed_tob), ValidationStatus::InvalidPrice);

    // Negative price
    TopOfBookMessage negative_bid{.best_bid_price = -5,
                                  .best_bid_quantity = 10,
                                  .best_ask_price = 105,
                                  .best_ask_quantity = 20};
    EXPECT_EQ(MessageValidator::validate(header, negative_bid), ValidationStatus::InvalidPrice);

    // Zero quantity for non-zero price
    TopOfBookMessage zero_qty{.best_bid_price = 100,
                              .best_bid_quantity = 0,
                              .best_ask_price = 105,
                              .best_ask_quantity = 20};
    EXPECT_EQ(MessageValidator::validate(header, zero_qty), ValidationStatus::InvalidQuantity);
}

TEST(MarketDataValidationTest, TradeValidation) {
    MarketDataHeader header =
        make_md_header(MarketDataMessageType::Trade, 100, 1, 1, 10, 1000, 1000);

    TradeMessage valid_trade{.trade_id = 1,
                             .price = 105,
                             .quantity = 20,
                             .aggressor_side = MarketSide::Buy,
                             .maker_order_id = 10,
                             .taker_order_id = 20};
    EXPECT_EQ(MessageValidator::validate(header, valid_trade), ValidationStatus::Valid);

    // Non-positive price
    TradeMessage zero_price = valid_trade;
    zero_price.price = 0;
    EXPECT_EQ(MessageValidator::validate(header, zero_price), ValidationStatus::InvalidPrice);

    // Zero quantity
    TradeMessage zero_qty = valid_trade;
    zero_qty.quantity = 0;
    EXPECT_EQ(MessageValidator::validate(header, zero_qty), ValidationStatus::InvalidQuantity);

    // Malformed side
    TradeMessage bad_side = valid_trade;
    bad_side.aggressor_side = static_cast<MarketSide>(99);
    EXPECT_EQ(MessageValidator::validate(header, bad_side), ValidationStatus::MalformedPayload);
}

TEST(MarketDataValidationTest, OrderBookDeltasValidation) {
    MarketDataHeader header =
        make_md_header(MarketDataMessageType::OrderBookAdd, 100, 1, 1, 10, 1000, 1000);

    OrderBookAddMessage valid_add{
        .order_id = 123, .side = MarketSide::Buy, .price = 100, .quantity = 50, .priority_rank = 1};
    EXPECT_EQ(MessageValidator::validate(header, valid_add), ValidationStatus::Valid);

    // Zero order ID
    OrderBookAddMessage zero_order_id = valid_add;
    zero_order_id.order_id = 0;
    EXPECT_EQ(MessageValidator::validate(header, zero_order_id),
              ValidationStatus::MalformedPayload);

    // Modify validation
    OrderBookModifyMessage valid_mod{.order_id = 123,
                                     .side = MarketSide::Buy,
                                     .price = 100,
                                     .new_quantity = 40,
                                     .delta_quantity = 10};
    EXPECT_EQ(MessageValidator::validate(header, valid_mod), ValidationStatus::Valid);

    // Delete validation
    OrderBookDeleteMessage valid_del{
        .order_id = 123, .side = MarketSide::Buy, .price = 100, .cancelled_quantity = 40};
    EXPECT_EQ(MessageValidator::validate(header, valid_del), ValidationStatus::Valid);
}

TEST(MarketDataValidationTest, SnapshotAndStatusValidation) {
    MarketDataHeader header =
        make_md_header(MarketDataMessageType::OrderBookSnapshot, 100, 1, 1, 10, 1000, 1000);

    OrderBookSnapshotMessage valid_snap{
        .bid_levels_count = 2,
        .ask_levels_count = 2,
        .last_included_sequence = 9,
        .bids = {{{.price = 100, .quantity = 50, .order_count = 2},
                  {.price = 99, .quantity = 100, .order_count = 5}}},
        .asks = {{{.price = 105, .quantity = 50, .order_count = 1},
                  {.price = 106, .quantity = 100, .order_count = 3}}},
    };
    EXPECT_EQ(MessageValidator::validate(header, valid_snap), ValidationStatus::Valid);

    // Overflow level counts
    OrderBookSnapshotMessage overflow_snap = valid_snap;
    overflow_snap.bid_levels_count = 99;
    EXPECT_EQ(MessageValidator::validate(header, overflow_snap),
              ValidationStatus::MalformedPayload);

    // Market status validation
    MarketDataHeader status_header =
        make_md_header(MarketDataMessageType::MarketStatus, 0, 1, 1, 10, 1000, 1000);
    MarketStatusMessage valid_status{.status = TradingStatus::Open, .status_flags = 0};
    EXPECT_EQ(MessageValidator::validate(status_header, valid_status), ValidationStatus::Valid);

    MarketStatusMessage unknown_status{.status = TradingStatus::Unknown, .status_flags = 0};
    EXPECT_EQ(MessageValidator::validate(status_header, unknown_status),
              ValidationStatus::MalformedPayload);
}
