#pragma once

#include "rexi/events/event_dispatcher.hpp"
#include "rexi/events/source_id.hpp"
#include "rexi/market_data/checksum.hpp"
#include "rexi/market_data/events.hpp"
#include "rexi/market_data/message_header.hpp"
#include "rexi/market_data/messages.hpp"
#include "rexi/market_data/sequence_manager.hpp"
#include "rexi/market_data/types.hpp"
#include "rexi/simulator/events.hpp"

namespace rexi::market_data {

/**
 * @brief Deterministic bridge translating Phase 03 Simulator events into canonical Market Data
 * protocol messages.
 */
class SimulatorMarketDataBridge {
public:
    explicit SimulatorMarketDataBridge(rexi::events::EventDispatcher& simulator_dispatcher,
                                       rexi::events::EventDispatcher& market_data_dispatcher,
                                       VenueId venue_id = 1, FeedId feed_id = 1)
        : venue_id_(venue_id), feed_id_(feed_id), market_data_dispatcher_(market_data_dispatcher) {
        subscribe_to_simulator(simulator_dispatcher);
    }

    [[nodiscard]] const SequenceManager& sequence_manager() const noexcept {
        return sequence_manager_;
    }

    [[nodiscard]] SequenceManager& sequence_manager() noexcept { return sequence_manager_; }

    [[nodiscard]] std::uint64_t emitted_trades_count() const noexcept {
        return emitted_trades_count_;
    }

    [[nodiscard]] std::uint64_t emitted_quotes_count() const noexcept {
        return emitted_quotes_count_;
    }

private:
    void subscribe_to_simulator(rexi::events::EventDispatcher& sim_dispatcher) {
        // Translate TradeExecutedPayload -> TradeMessage
        sim_dispatcher.subscribe<rexi::simulator::TradeExecutedPayload>(
            [this](const rexi::events::Event<rexi::simulator::TradeExecutedPayload>& evt) {
                const auto& sim_trade = evt.payload;
                SequenceNumber seq = sequence_manager_.expected_sequence();
                sequence_manager_.validate_and_advance(seq);

                TradeMessage trade_msg{
                    .trade_id = sim_trade.execution_id,
                    .price = sim_trade.price,
                    .quantity = sim_trade.quantity,
                    .aggressor_side = (sim_trade.aggressor_side == rexi::simulator::Side::Buy)
                                          ? MarketSide::Buy
                                          : MarketSide::Sell,
                    .maker_order_id = sim_trade.maker_order_id,
                    .taker_order_id = sim_trade.taker_order_id,
                };

                const auto checksum = IntegrityChecksum::calculate_for_payload(trade_msg);
                MarketDataHeader header = make_md_header(
                    MarketDataMessageType::Trade, sim_trade.instrument_id, venue_id_, feed_id_, seq,
                    evt.header.timestamp_ns, evt.header.timestamp_ns, 0, checksum);
                (void)header;

                auto out_evt = rexi::events::make_event(
                    trade_msg, rexi::events::SourceId::Simulator, seq, 0, evt.header.timestamp_ns);
                (void)market_data_dispatcher_.dispatch(out_evt);
                ++emitted_trades_count_;
            });

        // Translate TopQuoteUpdatedPayload -> TopOfBookMessage
        sim_dispatcher.subscribe<rexi::simulator::TopQuoteUpdatedPayload>(
            [this](const rexi::events::Event<rexi::simulator::TopQuoteUpdatedPayload>& evt) {
                const auto& sim_quote = evt.payload;
                SequenceNumber seq = sequence_manager_.expected_sequence();
                sequence_manager_.validate_and_advance(seq);

                TopOfBookMessage quote_msg{
                    .best_bid_price = sim_quote.best_bid_price,
                    .best_bid_quantity = sim_quote.best_bid_quantity,
                    .best_ask_price = sim_quote.best_ask_price,
                    .best_ask_quantity = sim_quote.best_ask_quantity,
                };

                const auto checksum = IntegrityChecksum::calculate_for_payload(quote_msg);
                MarketDataHeader header = make_md_header(
                    MarketDataMessageType::TopOfBook, sim_quote.instrument_id, venue_id_, feed_id_,
                    seq, evt.header.timestamp_ns, evt.header.timestamp_ns, 0, checksum);
                (void)header;

                auto out_evt = rexi::events::make_event(
                    quote_msg, rexi::events::SourceId::Simulator, seq, 0, evt.header.timestamp_ns);
                (void)market_data_dispatcher_.dispatch(out_evt);
                ++emitted_quotes_count_;
            });
    }

    VenueId venue_id_{1};
    FeedId feed_id_{1};
    SequenceManager sequence_manager_{1};
    rexi::events::EventDispatcher& market_data_dispatcher_;
    std::uint64_t emitted_trades_count_{0};
    std::uint64_t emitted_quotes_count_{0};
};

}  // namespace rexi::market_data
