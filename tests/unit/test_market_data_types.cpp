#include "rexi/market_data/message_header.hpp"
#include "rexi/market_data/messages.hpp"
#include "rexi/market_data/types.hpp"

#include <gtest/gtest.h>

using namespace rexi::market_data;

TEST(MarketDataTypesTest, StringConversions) {
    EXPECT_EQ(to_string(MarketSide::Buy), "Buy");
    EXPECT_EQ(to_string(MarketSide::Sell), "Sell");

    EXPECT_EQ(to_string(MarketDataMessageType::Unknown), "Unknown");
    EXPECT_EQ(to_string(MarketDataMessageType::InstrumentDefinition), "InstrumentDefinition");
    EXPECT_EQ(to_string(MarketDataMessageType::TopOfBook), "TopOfBook");
    EXPECT_EQ(to_string(MarketDataMessageType::Trade), "Trade");
    EXPECT_EQ(to_string(MarketDataMessageType::OrderBookAdd), "OrderBookAdd");
    EXPECT_EQ(to_string(MarketDataMessageType::OrderBookModify), "OrderBookModify");
    EXPECT_EQ(to_string(MarketDataMessageType::OrderBookDelete), "OrderBookDelete");
    EXPECT_EQ(to_string(MarketDataMessageType::OrderBookSnapshot), "OrderBookSnapshot");
    EXPECT_EQ(to_string(MarketDataMessageType::MarketStatus), "MarketStatus");

    EXPECT_EQ(to_string(TradingStatus::Unknown), "Unknown");
    EXPECT_EQ(to_string(TradingStatus::PreOpen), "PreOpen");
    EXPECT_EQ(to_string(TradingStatus::Open), "Open");
    EXPECT_EQ(to_string(TradingStatus::Halted), "Halted");
    EXPECT_EQ(to_string(TradingStatus::Closed), "Closed");

    EXPECT_EQ(to_string(ValidationStatus::Valid), "Valid");
    EXPECT_EQ(to_string(ValidationStatus::InvalidInstrument), "InvalidInstrument");
    EXPECT_EQ(to_string(ValidationStatus::InvalidVenue), "InvalidVenue");
    EXPECT_EQ(to_string(ValidationStatus::InvalidPrice), "InvalidPrice");
    EXPECT_EQ(to_string(ValidationStatus::InvalidQuantity), "InvalidQuantity");
    EXPECT_EQ(to_string(ValidationStatus::InvalidTimestamp), "InvalidTimestamp");
    EXPECT_EQ(to_string(ValidationStatus::InvalidSequence), "InvalidSequence");
    EXPECT_EQ(to_string(ValidationStatus::InvalidVersion), "InvalidVersion");
    EXPECT_EQ(to_string(ValidationStatus::MalformedPayload), "MalformedPayload");
    EXPECT_EQ(to_string(ValidationStatus::InvalidChecksum), "InvalidChecksum");

    EXPECT_EQ(to_string(SequenceStatus::Expected), "Expected");
    EXPECT_EQ(to_string(SequenceStatus::Duplicate), "Duplicate");
    EXPECT_EQ(to_string(SequenceStatus::Gap), "Gap");
    EXPECT_EQ(to_string(SequenceStatus::OutOfOrder), "OutOfOrder");
    EXPECT_EQ(to_string(SequenceStatus::ResetRequired), "ResetRequired");

    EXPECT_EQ(to_string(ChecksumStatus::NotSupplied), "NotSupplied");
    EXPECT_EQ(to_string(ChecksumStatus::Valid), "Valid");
    EXPECT_EQ(to_string(ChecksumStatus::Invalid), "Invalid");
}

TEST(MarketDataTypesTest, HeaderConstructionAndLayout) {
    EXPECT_EQ(sizeof(MarketDataHeader), 40U);
    EXPECT_EQ(alignof(MarketDataHeader), 8U);

    MarketDataHeader header = make_md_header(MarketDataMessageType::TopOfBook, 1001, 1, 2, 42,
                                             1'000'000, 1'000'050, 0x01, 0xAABBCCDD);

    EXPECT_EQ(header.version, CurrentProtocolVersion);
    EXPECT_EQ(header.message_type, MarketDataMessageType::TopOfBook);
    EXPECT_EQ(header.instrument_id, 1001U);
    EXPECT_EQ(header.venue_id, 1U);
    EXPECT_EQ(header.feed_id, 2U);
    EXPECT_EQ(header.sequence_num, 42U);
    EXPECT_EQ(header.source_timestamp_ns, 1'000'000U);
    EXPECT_EQ(header.receive_timestamp_ns, 1'000'050U);
    EXPECT_EQ(header.flags, 0x01U);
    EXPECT_EQ(header.checksum, 0xAABBCCDDU);
}

TEST(MarketDataTypesTest, MessageLayoutsAndDefaults) {
    TopOfBookMessage tob{.best_bid_price = 1000,
                         .best_bid_quantity = 50,
                         .best_ask_price = 1005,
                         .best_ask_quantity = 60};
    EXPECT_EQ(tob.best_bid_price, 1000);
    EXPECT_EQ(tob.best_bid_quantity, 50U);
    EXPECT_EQ(tob.best_ask_price, 1005);
    EXPECT_EQ(tob.best_ask_quantity, 60U);

    TradeMessage trade{.trade_id = 999,
                       .price = 1005,
                       .quantity = 25,
                       .aggressor_side = MarketSide::Buy,
                       .maker_order_id = 10,
                       .taker_order_id = 20};
    EXPECT_EQ(trade.trade_id, 999U);
    EXPECT_EQ(trade.price, 1005);
    EXPECT_EQ(trade.quantity, 25U);
    EXPECT_EQ(trade.aggressor_side, MarketSide::Buy);
    EXPECT_EQ(trade.maker_order_id, 10U);
    EXPECT_EQ(trade.taker_order_id, 20U);
}
