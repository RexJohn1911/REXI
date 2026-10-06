#pragma once

#include "rexi/events/event.hpp"
#include "rexi/events/event_dispatcher.hpp"
#include "rexi/events/source_id.hpp"
#include "rexi/simulator/clock.hpp"
#include "rexi/simulator/events.hpp"
#include "rexi/simulator/instrument.hpp"
#include "rexi/simulator/matching_engine.hpp"
#include "rexi/simulator/order.hpp"
#include "rexi/simulator/session.hpp"
#include "rexi/simulator/types.hpp"

#include <cstdint>
#include <memory>
#include <optional>
#include <unordered_set>
#include <utility>

namespace rexi::simulator {

/**
 * @brief Top-level exchange simulator coordinating sessions, matching engine, clock, and event
 * dispatch.
 */
class Exchange {
public:
    explicit Exchange(rexi::events::EventDispatcher* external_dispatcher = nullptr)
        : external_dispatcher_(external_dispatcher) {}

    bool register_instrument(const Instrument& instrument) {
        return matching_engine_.register_instrument(instrument);
    }

    void open_session() noexcept { session_.open(); }

    void close_session() noexcept { session_.close(); }

    [[nodiscard]] bool is_open() const noexcept { return session_.is_open(); }

    [[nodiscard]] const ExchangeSession& session() const noexcept { return session_; }

    [[nodiscard]] SimulationClock& clock() noexcept { return clock_; }
    [[nodiscard]] const SimulationClock& clock() const noexcept { return clock_; }

    [[nodiscard]] MatchingEngine& matching_engine() noexcept { return matching_engine_; }
    [[nodiscard]] const MatchingEngine& matching_engine() const noexcept {
        return matching_engine_;
    }

    [[nodiscard]] rexi::events::EventDispatcher& dispatcher() noexcept {
        return external_dispatcher_ != nullptr ? *external_dispatcher_ : internal_dispatcher_;
    }

    [[nodiscard]] SequenceNum current_sequence() const noexcept { return sequence_; }

    /**
     * @brief Submit a new order to the exchange.
     */
    OrderStatus submit_order(OrderId order_id, ClientId client_id, InstrumentId instrument_id,
                             Side side, OrderType type, Price price, Quantity quantity) {
        RejectReason reason = RejectReason::None;

        if (!session_.is_open()) {
            emit_rejection(order_id, client_id, instrument_id, side, type, price, quantity,
                           RejectReason::SessionClosed);
            return OrderStatus::Rejected;
        }

        if (submitted_orders_.contains(order_id)) {
            emit_rejection(order_id, client_id, instrument_id, side, type, price, quantity,
                           RejectReason::DuplicateOrderId);
            return OrderStatus::Rejected;
        }

        const Instrument* inst = matching_engine_.get_instrument(instrument_id);
        if (inst == nullptr) {
            emit_rejection(order_id, client_id, instrument_id, side, type, price, quantity,
                           RejectReason::UnknownInstrument);
            return OrderStatus::Rejected;
        }

        if (!inst->validate_order(side, type, price, quantity, reason)) {
            emit_rejection(order_id, client_id, instrument_id, side, type, price, quantity, reason);
            return OrderStatus::Rejected;
        }

        // Assign deterministic sequence number upon acceptance
        SequenceNum seq = ++sequence_;
        uint64_t timestamp = clock_.now_ns();
        submitted_orders_.insert(order_id);

        Order order{
            .order_id = order_id,
            .client_id = client_id,
            .instrument_id = instrument_id,
            .side = side,
            .type = type,
            .price = price,
            .initial_quantity = quantity,
            .remaining_quantity = quantity,
            .filled_quantity = 0,
            .priority_seq = seq,
            .status = OrderStatus::Accepted,
            .accepted_timestamp_ns = timestamp,
        };

        // Emit OrderAcceptedEvent
        OrderAcceptedPayload accepted_payload{
            .order_id = order_id,
            .client_id = client_id,
            .instrument_id = instrument_id,
            .side = side,
            .order_type = type,
            .price = price,
            .quantity = quantity,
            .sequence = seq,
        };
        emit_event(accepted_payload, seq, timestamp);

        // Process through matching engine
        MatchResult result = matching_engine_.process_order(order, seq, timestamp);

        // Emit fill and trade events
        for (size_t i = 0; i < result.executions.size(); ++i) {
            const auto& exec = result.executions[i];
            const auto& maker = result.affected_resting_orders[i];

            // Taker fill event
            OrderFilledPayload taker_fill{
                .order_id = exec.taker_order_id,
                .client_id = exec.taker_client_id,
                .instrument_id = exec.instrument_id,
                .execution_id = exec.execution_id,
                .fill_price = exec.price,
                .fill_quantity = exec.quantity,
                .remaining_quantity = order.remaining_quantity,
                .status = order.status,
                .sequence = seq,
            };
            emit_event(taker_fill, seq, timestamp);

            // Maker fill event
            OrderFilledPayload maker_fill{
                .order_id = exec.maker_order_id,
                .client_id = exec.maker_client_id,
                .instrument_id = exec.instrument_id,
                .execution_id = exec.execution_id,
                .fill_price = exec.price,
                .fill_quantity = exec.quantity,
                .remaining_quantity = maker.remaining_quantity,
                .status = maker.status,
                .sequence = seq,
            };
            emit_event(maker_fill, seq, timestamp);

            // Public trade event
            TradeExecutedPayload trade{
                .execution_id = exec.execution_id,
                .instrument_id = exec.instrument_id,
                .price = exec.price,
                .quantity = exec.quantity,
                .aggressor_side = exec.aggressor_side,
                .maker_order_id = exec.maker_order_id,
                .taker_order_id = exec.taker_order_id,
                .sequence = seq,
            };
            emit_event(trade, seq, timestamp);
        }

        emit_top_quote(instrument_id, seq, timestamp);

        return result.final_order_status;
    }

    /**
     * @brief Cancel a resting order by order ID.
     */
    bool cancel_order(OrderId order_id) {
        if (!session_.is_open()) {
            return false;
        }

        Order cancelled_order{};
        if (!matching_engine_.cancel_order(order_id, cancelled_order)) {
            return false;
        }

        SequenceNum seq = ++sequence_;
        uint64_t timestamp = clock_.now_ns();

        OrderCancelledPayload cancelled_payload{
            .order_id = cancelled_order.order_id,
            .client_id = cancelled_order.client_id,
            .instrument_id = cancelled_order.instrument_id,
            .cancelled_quantity = cancelled_order.remaining_quantity,
            .sequence = seq,
        };
        emit_event(cancelled_payload, seq, timestamp);

        emit_top_quote(cancelled_order.instrument_id, seq, timestamp);

        return true;
    }

    void reset() noexcept {
        session_.reset();
        matching_engine_.reset();
        clock_.reset();
        sequence_ = 0;
        submitted_orders_.clear();
    }

private:
    void emit_rejection(OrderId order_id, ClientId client_id, InstrumentId instrument_id, Side side,
                        OrderType type, Price price, Quantity quantity, RejectReason reason) {
        SequenceNum seq = ++sequence_;
        uint64_t timestamp = clock_.now_ns();
        OrderRejectedPayload rejected_payload{
            .order_id = order_id,
            .client_id = client_id,
            .instrument_id = instrument_id,
            .side = side,
            .order_type = type,
            .price = price,
            .quantity = quantity,
            .reason = reason,
        };
        emit_event(rejected_payload, seq, timestamp);
    }

    template <typename Payload>
    void emit_event(const Payload& payload, SequenceNum seq, uint64_t timestamp) {
        auto evt =
            rexi::events::make_event(payload, rexi::events::SourceId::Simulator, seq, 0, timestamp);
        (void)dispatcher().dispatch(evt);
    }

    void emit_top_quote(InstrumentId instrument_id, SequenceNum seq, uint64_t timestamp) {
        const auto* book = matching_engine_.get_order_book(instrument_id);
        if (book == nullptr) {
            return;
        }

        auto best_bid = book->best_bid();
        auto best_ask = book->best_ask();

        TopQuoteUpdatedPayload quote{
            .instrument_id = instrument_id,
            .best_bid_price = best_bid.has_value() ? best_bid->first : 0,
            .best_bid_quantity = best_bid.has_value() ? best_bid->second : 0,
            .best_ask_price = best_ask.has_value() ? best_ask->first : 0,
            .best_ask_quantity = best_ask.has_value() ? best_ask->second : 0,
            .sequence = seq,
        };
        emit_event(quote, seq, timestamp);
    }

    ExchangeSession session_;
    SimulationClock clock_;
    MatchingEngine matching_engine_;
    rexi::events::EventDispatcher* external_dispatcher_{nullptr};
    rexi::events::EventDispatcher internal_dispatcher_;
    SequenceNum sequence_{0};
    std::unordered_set<OrderId> submitted_orders_;
};

}  // namespace rexi::simulator
