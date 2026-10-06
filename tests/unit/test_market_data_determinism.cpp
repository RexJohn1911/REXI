#include "rexi/events/event_dispatcher.hpp"
#include "rexi/market_data/checksum.hpp"
#include "rexi/market_data/events.hpp"
#include "rexi/market_data/message_header.hpp"
#include "rexi/market_data/messages.hpp"
#include "rexi/market_data/sequence_manager.hpp"
#include "rexi/market_data/validator.hpp"

#include <cstdint>
#include <string>
#include <vector>

#include <gtest/gtest.h>

using namespace rexi::market_data;
using namespace rexi::events;

struct MarketDataRunLog {
    struct LogEntry {
        SequenceNumber seq{0};
        Timestamp timestamp_ns{0};
        std::string type{};
        ValidationStatus val_status{ValidationStatus::Valid};
        SequenceStatus seq_status{SequenceStatus::Expected};
        ChecksumStatus chk_status{ChecksumStatus::Valid};
        Price price{0};
        Quantity quantity{0};
    };

    std::vector<LogEntry> entries;

    bool operator==(const MarketDataRunLog& other) const {
        if (entries.size() != other.entries.size()) {
            return false;
        }
        for (size_t i = 0; i < entries.size(); ++i) {
            const auto& a = entries[i];
            const auto& b = other.entries[i];
            if (a.seq != b.seq || a.timestamp_ns != b.timestamp_ns || a.type != b.type ||
                a.val_status != b.val_status || a.seq_status != b.seq_status ||
                a.chk_status != b.chk_status || a.price != b.price || a.quantity != b.quantity) {
                return false;
            }
        }
        return true;
    }
};

static MarketDataRunLog run_deterministic_market_data_pipeline() {
    MarketDataRunLog log;
    SequenceManager seq_mgr(1);

    uint64_t state = 987654321ULL;
    auto lcg_rand = [&state]() -> uint64_t {
        state = state * 6364136223846793005ULL + 1442695040888963407ULL;
        return state;
    };

    for (int i = 0; i < 1000; ++i) {
        uint64_t r = lcg_rand();
        SequenceNumber incoming_seq = static_cast<SequenceNumber>(i + 1);
        Timestamp ts = 1'000'000ULL + static_cast<Timestamp>(i * 100);

        int msg_type = static_cast<int>(r % 3);
        if (msg_type == 0) {
            // TopOfBook
            Price bid_p = 1000 + static_cast<Price>((r >> 8) % 20);
            Price ask_p = bid_p + 1 + static_cast<Price>((r >> 12) % 5);
            Quantity bid_q = 10 + static_cast<Quantity>((r >> 16) % 50);
            Quantity ask_q = 10 + static_cast<Quantity>((r >> 20) % 50);

            TopOfBookMessage tob{
                .best_bid_price = bid_p,
                .best_bid_quantity = bid_q,
                .best_ask_price = ask_p,
                .best_ask_quantity = ask_q,
            };

            auto chk = IntegrityChecksum::calculate_for_payload(tob);
            MarketDataHeader hdr = make_md_header(MarketDataMessageType::TopOfBook, 1001, 1, 1,
                                                  incoming_seq, ts, ts, 0, chk);

            ValidationStatus v_stat = MessageValidator::validate(hdr, tob);
            SequenceStatus s_stat = seq_mgr.validate_and_advance(incoming_seq);
            ChecksumStatus c_stat = IntegrityChecksum::verify(hdr, tob);

            log.entries.push_back(
                {incoming_seq, ts, "TopOfBook", v_stat, s_stat, c_stat, bid_p, bid_q});
        } else if (msg_type == 1) {
            // Trade
            Price p = 1000 + static_cast<Price>((r >> 8) % 25);
            Quantity q = 5 + static_cast<Quantity>((r >> 16) % 30);
            TradeMessage trade{
                .trade_id = static_cast<TradeId>(i + 1),
                .price = p,
                .quantity = q,
                .aggressor_side = ((r >> 24) % 2 == 0) ? MarketSide::Buy : MarketSide::Sell,
                .maker_order_id = 100 + static_cast<OrderId>(i),
                .taker_order_id = 200 + static_cast<OrderId>(i),
            };

            auto chk = IntegrityChecksum::calculate_for_payload(trade);
            MarketDataHeader hdr = make_md_header(MarketDataMessageType::Trade, 1001, 1, 1,
                                                  incoming_seq, ts, ts, 0, chk);

            ValidationStatus v_stat = MessageValidator::validate(hdr, trade);
            SequenceStatus s_stat = seq_mgr.validate_and_advance(incoming_seq);
            ChecksumStatus c_stat = IntegrityChecksum::verify(hdr, trade);

            log.entries.push_back({incoming_seq, ts, "Trade", v_stat, s_stat, c_stat, p, q});
        } else {
            // OrderBookAdd
            Price p = 1000 + static_cast<Price>((r >> 8) % 30);
            Quantity q = 10 + static_cast<Quantity>((r >> 16) % 20);
            OrderBookAddMessage add{
                .order_id = static_cast<OrderId>(i + 1),
                .side = ((r >> 24) % 2 == 0) ? MarketSide::Buy : MarketSide::Sell,
                .price = p,
                .quantity = q,
                .priority_rank = 1,
            };

            auto chk = IntegrityChecksum::calculate_for_payload(add);
            MarketDataHeader hdr = make_md_header(MarketDataMessageType::OrderBookAdd, 1001, 1, 1,
                                                  incoming_seq, ts, ts, 0, chk);

            ValidationStatus v_stat = MessageValidator::validate(hdr, add);
            SequenceStatus s_stat = seq_mgr.validate_and_advance(incoming_seq);
            ChecksumStatus c_stat = IntegrityChecksum::verify(hdr, add);

            log.entries.push_back({incoming_seq, ts, "OrderBookAdd", v_stat, s_stat, c_stat, p, q});
        }
    }

    return log;
}

TEST(MarketDataDeterminismTest, IdenticalRunsProduceIdenticalOutputs) {
    MarketDataRunLog run1 = run_deterministic_market_data_pipeline();
    MarketDataRunLog run2 = run_deterministic_market_data_pipeline();

    ASSERT_EQ(run1.entries.size(), 1000U);
    ASSERT_EQ(run2.entries.size(), 1000U);
    EXPECT_TRUE(run1 == run2);

    for (size_t i = 0; i < run1.entries.size(); ++i) {
        EXPECT_EQ(run1.entries[i].seq, run2.entries[i].seq);
        EXPECT_EQ(run1.entries[i].timestamp_ns, run2.entries[i].timestamp_ns);
        EXPECT_EQ(run1.entries[i].type, run2.entries[i].type);
        EXPECT_EQ(run1.entries[i].val_status, run2.entries[i].val_status);
        EXPECT_EQ(run1.entries[i].seq_status, run2.entries[i].seq_status);
        EXPECT_EQ(run1.entries[i].chk_status, run2.entries[i].chk_status);
        EXPECT_EQ(run1.entries[i].price, run2.entries[i].price);
        EXPECT_EQ(run1.entries[i].quantity, run2.entries[i].quantity);
    }
}
