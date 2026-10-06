#include "rexi/market_data/message_header.hpp"
#include "rexi/market_data/messages.hpp"
#include "rexi/order_book/order_book.hpp"

#include <gtest/gtest.h>

using namespace rexi::market_data;
using namespace rexi::order_book;

class OrderBookMarketDataTest : public ::testing::Test {
protected:
    void SetUp() override { book_ = OrderBook(100); }

    OrderBook book_{100};
};

TEST_F(OrderBookMarketDataTest, ApplyAddModifyDeleteMessages) {
    // 1. Apply OrderBookAdd for Buy order
    MarketDataHeader add_hdr =
        make_md_header(MarketDataMessageType::OrderBookAdd, 100, 1, 1, 10, 1000, 1000);
    OrderBookAddMessage add_msg{
        .order_id = 101,
        .side = MarketSide::Buy,
        .price = 500,
        .quantity = 25,
    };

    EXPECT_EQ(book_.apply_add(add_hdr, add_msg), OrderBookStatus::Success);
    EXPECT_EQ(book_.order_count(), 1);
    EXPECT_EQ(book_.best_bid_price(), 500);
    EXPECT_EQ(book_.best_bid_quantity(), 25);

    // 2. Apply OrderBookModify (quantity reduction from 25 to 15)
    MarketDataHeader mod_hdr =
        make_md_header(MarketDataMessageType::OrderBookModify, 100, 1, 1, 11, 2000, 2000);
    OrderBookModifyMessage mod_msg{
        .order_id = 101,
        .side = MarketSide::Buy,
        .price = 500,
        .new_quantity = 15,
        .delta_quantity = 10,
    };
    EXPECT_EQ(book_.apply_modify(mod_hdr, mod_msg), OrderBookStatus::Success);
    EXPECT_EQ(book_.best_bid_quantity(), 15);

    // 3. Apply OrderBookModify (price change to 505)
    OrderBookModifyMessage mod_price_msg{
        .order_id = 101,
        .side = MarketSide::Buy,
        .price = 505,
        .new_quantity = 15,
        .delta_quantity = 0,
    };
    EXPECT_EQ(book_.apply_modify(mod_hdr, mod_price_msg), OrderBookStatus::Success);
    EXPECT_EQ(book_.best_bid_price(), 505);

    // 4. Apply OrderBookDelete
    MarketDataHeader del_hdr =
        make_md_header(MarketDataMessageType::OrderBookDelete, 100, 1, 1, 12, 3000, 3000);
    OrderBookDeleteMessage del_msg{.order_id = 101};
    EXPECT_EQ(book_.apply_delete(del_hdr, del_msg), OrderBookStatus::Success);
    EXPECT_TRUE(book_.is_empty());

    EXPECT_TRUE(book_.validate().is_valid);
}

TEST_F(OrderBookMarketDataTest, InvalidIncrementalUpdateLeavesBookUnchanged) {
    // Add valid order
    MarketDataHeader add_hdr =
        make_md_header(MarketDataMessageType::OrderBookAdd, 100, 1, 1, 1, 1000, 1000);
    OrderBookAddMessage add_msg{
        .order_id = 1,
        .side = MarketSide::Buy,
        .price = 100,
        .quantity = 50,
    };
    EXPECT_EQ(book_.apply_add(add_hdr, add_msg), OrderBookStatus::Success);

    // Snapshot state before invalid operation
    size_t prev_count = book_.order_count();
    Price prev_best = book_.best_bid_price().value();

    // Invalid instrument ID
    MarketDataHeader bad_inst_hdr =
        make_md_header(MarketDataMessageType::OrderBookAdd, 999, 1, 1, 2, 2000, 2000);
    EXPECT_EQ(book_.apply_add(bad_inst_hdr, add_msg), OrderBookStatus::InstrumentMismatch);

    // Duplicate OrderId
    EXPECT_EQ(book_.apply_add(add_hdr, add_msg), OrderBookStatus::DuplicateOrderId);

    // Invalid Price
    OrderBookAddMessage bad_price_msg = add_msg;
    bad_price_msg.order_id = 2;
    bad_price_msg.price = 0;
    EXPECT_EQ(book_.apply_add(add_hdr, bad_price_msg), OrderBookStatus::InvalidPrice);

    // Verify book is completely unchanged
    EXPECT_EQ(book_.order_count(), prev_count);
    EXPECT_EQ(book_.best_bid_price().value(), prev_best);
    EXPECT_TRUE(book_.validate().is_valid);
}

TEST_F(OrderBookMarketDataTest, ApplyAndExportPhase04Snapshot) {
    // Populate an L2 snapshot with 3 bids and 2 asks
    OrderBookSnapshotMessage snap{};
    snap.bid_levels_count = 3;
    snap.bids[0] = OrderBookSnapshotLevel{.price = 102, .quantity = 300, .order_count = 3};
    snap.bids[1] = OrderBookSnapshotLevel{.price = 101, .quantity = 500, .order_count = 5};
    snap.bids[2] = OrderBookSnapshotLevel{.price = 100, .quantity = 200, .order_count = 2};

    snap.ask_levels_count = 2;
    snap.asks[0] = OrderBookSnapshotLevel{.price = 105, .quantity = 400, .order_count = 4};
    snap.asks[1] = OrderBookSnapshotLevel{.price = 106, .quantity = 600, .order_count = 6};

    EXPECT_EQ(book_.apply_snapshot(snap), OrderBookStatus::Success);
    EXPECT_EQ(book_.bid_level_count(), 3);
    EXPECT_EQ(book_.ask_level_count(), 2);
    EXPECT_EQ(book_.best_bid_price(), 102);
    EXPECT_EQ(book_.best_bid_quantity(), 300);
    EXPECT_EQ(book_.best_ask_price(), 105);
    EXPECT_EQ(book_.best_ask_quantity(), 400);
    EXPECT_EQ(book_.spread(), 3);

    // Export to Phase 04 Snapshot
    auto exported = book_.to_phase04_snapshot(12345);
    EXPECT_EQ(exported.last_included_sequence, 12345);
    EXPECT_EQ(exported.bid_levels_count, 3);
    EXPECT_EQ(exported.ask_levels_count, 2);
    EXPECT_EQ(exported.bids[0].price, 102);
    EXPECT_EQ(exported.bids[0].quantity, 300);
    EXPECT_EQ(exported.asks[0].price, 105);
    EXPECT_EQ(exported.asks[0].quantity, 400);

    EXPECT_TRUE(book_.validate().is_valid);
}

TEST_F(OrderBookMarketDataTest, SnapshotDepthTruncationAtProtocolBoundary) {
    // Fill a book with 20 bid levels and 20 ask levels (exceeding 16)
    for (int i = 1; i <= 20; ++i) {
        book_.add_order(RestingOrder{
            .order_id = static_cast<OrderId>(i),
            .instrument_id = 100,
            .side = Side::Buy,
            .price = static_cast<Price>(1000 - i),
            .initial_quantity = 10,
            .remaining_quantity = 10,
        });
        book_.add_order(RestingOrder{
            .order_id = static_cast<OrderId>(100 + i),
            .instrument_id = 100,
            .side = Side::Sell,
            .price = static_cast<Price>(2000 + i),
            .initial_quantity = 10,
            .remaining_quantity = 10,
        });
    }

    EXPECT_EQ(book_.bid_level_count(), 20);
    EXPECT_EQ(book_.ask_level_count(), 20);

    // Export must truncate to 10 levels per side at the protocol boundary
    auto exported = book_.to_phase04_snapshot(99);
    EXPECT_EQ(exported.bid_levels_count, MaxSnapshotLevels);
    EXPECT_EQ(exported.ask_levels_count, MaxSnapshotLevels);
    EXPECT_EQ(exported.bids[0].price, 999);
    EXPECT_EQ(exported.bids[9].price, 990);
    EXPECT_EQ(exported.asks[0].price, 2001);
    EXPECT_EQ(exported.asks[9].price, 2010);
}

TEST_F(OrderBookMarketDataTest, NativeL3SnapshotRoundtrip) {
    for (int i = 1; i <= 5; ++i) {
        book_.add_order(RestingOrder{
            .order_id = static_cast<OrderId>(i),
            .instrument_id = 100,
            .side = Side::Buy,
            .price = 100,
            .initial_quantity = static_cast<Quantity>(i * 10),
            .remaining_quantity = static_cast<Quantity>(i * 10),
            .priority_seq = static_cast<SequenceNumber>(i),
        });
    }

    auto l3_snap = book_.to_l3_snapshot(50, 1000);
    EXPECT_EQ(l3_snap.orders.size(), 5);
    EXPECT_EQ(l3_snap.sequence_number, 50);

    OrderBook restored_book(100);
    EXPECT_EQ(restored_book.apply_l3_snapshot(l3_snap), OrderBookStatus::Success);
    EXPECT_EQ(restored_book.order_count(), 5);
    EXPECT_EQ(restored_book.total_bid_quantity(), 150);

    for (int i = 1; i <= 5; ++i) {
        EXPECT_EQ(restored_book.get_queue_position(static_cast<OrderId>(i)), i - 1);
    }

    EXPECT_TRUE(restored_book.validate().is_valid);
}
