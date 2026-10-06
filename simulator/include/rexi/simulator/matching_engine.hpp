#pragma once

#include "rexi/simulator/execution.hpp"
#include "rexi/simulator/instrument.hpp"
#include "rexi/simulator/order.hpp"
#include "rexi/simulator/order_book.hpp"
#include "rexi/simulator/types.hpp"

#include <algorithm>
#include <cstdint>
#include <optional>
#include <unordered_map>
#include <vector>

namespace rexi::simulator {

/**
 * @brief Result struct returned by MatchingEngine::process_order.
 */
struct MatchResult {
    OrderStatus final_order_status{OrderStatus::New};
    Quantity executed_quantity{0};
    Quantity remaining_quantity{0};
    Quantity cancelled_remainder_quantity{0};
    std::vector<Execution> executions;
    std::vector<Order> affected_resting_orders;
};

/**
 * @brief Deterministic, single-threaded price-time priority matching engine.
 *
 * Implements strict FIFO execution at each price level with resting-order price priority.
 */
class MatchingEngine {
public:
    MatchingEngine() = default;

    bool register_instrument(const Instrument& instrument) {
        if (instruments_.contains(instrument.id)) {
            return false;
        }
        instruments_[instrument.id] = instrument;
        books_.emplace(instrument.id, OrderBook(instrument.id));
        return true;
    }

    [[nodiscard]] bool has_instrument(InstrumentId instrument_id) const noexcept {
        return instruments_.contains(instrument_id);
    }

    [[nodiscard]] const Instrument* get_instrument(InstrumentId instrument_id) const noexcept {
        auto inst_it = instruments_.find(instrument_id);
        return (inst_it != instruments_.end()) ? &inst_it->second : nullptr;
    }

    [[nodiscard]] OrderBook* get_order_book(InstrumentId instrument_id) noexcept {
        auto book_it = books_.find(instrument_id);
        return (book_it != books_.end()) ? &book_it->second : nullptr;
    }

    [[nodiscard]] const OrderBook* get_order_book(InstrumentId instrument_id) const noexcept {
        auto book_it = books_.find(instrument_id);
        return (book_it != books_.end()) ? &book_it->second : nullptr;
    }

    [[nodiscard]] bool has_order(OrderId order_id) const noexcept {
        return std::ranges::any_of(
            books_, [order_id](const auto& pair) { return pair.second.has_order(order_id); });
    }

    [[nodiscard]] const Order* find_order(OrderId order_id) const noexcept {
        for (const auto& [inst_id, book] : books_) {
            (void)inst_id;
            const Order* order = book.find_order(order_id);
            if (order != nullptr) {
                return order;
            }
        }
        return nullptr;
    }

    /**
     * @brief Process an accepted incoming order through matching logic.
     */
    MatchResult process_order(Order& incoming_order, SequenceNum current_seq,
                              uint64_t current_timestamp_ns) {
        MatchResult result{};
        auto book_it = books_.find(incoming_order.instrument_id);
        if (book_it == books_.end()) {
            incoming_order.status = OrderStatus::Rejected;
            result.final_order_status = OrderStatus::Rejected;
            return result;
        }

        OrderBook& book = book_it->second;

        if (incoming_order.side == Side::Buy) {
            match_buy_order(incoming_order, book, current_seq, current_timestamp_ns, result);
        } else {
            match_sell_order(incoming_order, book, current_seq, current_timestamp_ns, result);
        }

        result.final_order_status = incoming_order.status;
        result.executed_quantity = incoming_order.filled_quantity;
        result.remaining_quantity = incoming_order.remaining_quantity;

        return result;
    }

    /**
     * @brief Cancel an active resting order from the order book.
     */
    bool cancel_order(InstrumentId instrument_id, OrderId order_id, Order& cancelled_order) {
        auto book_it = books_.find(instrument_id);
        if (book_it == books_.end()) {
            return false;
        }
        return book_it->second.cancel_order(order_id, cancelled_order);
    }

    /**
     * @brief Cancel an active resting order across all books.
     */
    bool cancel_order(OrderId order_id, Order& cancelled_order) {
        for (auto& [inst_id, book] : books_) {
            (void)inst_id;
            if (book.cancel_order(order_id, cancelled_order)) {
                return true;
            }
        }
        return false;
    }

    void reset() noexcept {
        for (auto& [inst_id, book] : books_) {
            (void)inst_id;
            book.clear();
        }
        next_execution_id_ = 1;
    }

private:
    void match_buy_order(Order& buy_order, OrderBook& book, SequenceNum seq, uint64_t timestamp_ns,
                         MatchResult& result) {
        auto& asks = book.asks();

        while (buy_order.remaining_quantity > 0 && !asks.empty()) {
            auto best_ask_it = asks.begin();
            Price best_ask_price = best_ask_it->first;

            if (buy_order.type == OrderType::Limit && buy_order.price < best_ask_price) {
                // Price cannot cross
                break;
            }

            auto& queue = best_ask_it->second;
            while (buy_order.remaining_quantity > 0 && !queue.empty()) {
                Order& resting_ask = queue.front();
                Quantity match_qty =
                    std::min(buy_order.remaining_quantity, resting_ask.remaining_quantity);
                Price match_price = resting_ask.price;  // Resting order determines price

                buy_order.fill(match_qty);
                resting_ask.fill(match_qty);

                Execution exec{
                    .execution_id = next_execution_id_++,
                    .instrument_id = buy_order.instrument_id,
                    .price = match_price,
                    .quantity = match_qty,
                    .aggressor_side = Side::Buy,
                    .maker_order_id = resting_ask.order_id,
                    .taker_order_id = buy_order.order_id,
                    .maker_client_id = resting_ask.client_id,
                    .taker_client_id = buy_order.client_id,
                    .sequence = seq,
                    .timestamp_ns = timestamp_ns,
                };
                result.executions.push_back(exec);
                result.affected_resting_orders.push_back(resting_ask);

                if (resting_ask.remaining_quantity == 0) {
                    book.erase_order_index(resting_ask.order_id);
                    queue.pop_front();
                }
            }

            if (queue.empty()) {
                asks.erase(best_ask_it);
            }
        }

        // Post-matching handling
        if (buy_order.remaining_quantity > 0) {
            if (buy_order.type == OrderType::Limit) {
                // Insert resting remainder into order book
                book.insert_order(buy_order);
            } else {
                // Market order exhausted liquidity: cancel unfilled remainder
                result.cancelled_remainder_quantity = buy_order.remaining_quantity;
                buy_order.remaining_quantity = 0;
                if (buy_order.filled_quantity == 0) {
                    buy_order.status = OrderStatus::Cancelled;
                } else {
                    buy_order.status = OrderStatus::PartiallyFilled;
                }
            }
        }
    }

    void match_sell_order(Order& sell_order, OrderBook& book, SequenceNum seq,
                          uint64_t timestamp_ns, MatchResult& result) {
        auto& bids = book.bids();

        while (sell_order.remaining_quantity > 0 && !bids.empty()) {
            auto best_bid_it = bids.begin();
            Price best_bid_price = best_bid_it->first;

            if (sell_order.type == OrderType::Limit && sell_order.price > best_bid_price) {
                // Price cannot cross
                break;
            }

            auto& queue = best_bid_it->second;
            while (sell_order.remaining_quantity > 0 && !queue.empty()) {
                Order& resting_bid = queue.front();
                Quantity match_qty =
                    std::min(sell_order.remaining_quantity, resting_bid.remaining_quantity);
                Price match_price = resting_bid.price;  // Resting order determines price

                sell_order.fill(match_qty);
                resting_bid.fill(match_qty);

                Execution exec{
                    .execution_id = next_execution_id_++,
                    .instrument_id = sell_order.instrument_id,
                    .price = match_price,
                    .quantity = match_qty,
                    .aggressor_side = Side::Sell,
                    .maker_order_id = resting_bid.order_id,
                    .taker_order_id = sell_order.order_id,
                    .maker_client_id = resting_bid.client_id,
                    .taker_client_id = sell_order.client_id,
                    .sequence = seq,
                    .timestamp_ns = timestamp_ns,
                };
                result.executions.push_back(exec);
                result.affected_resting_orders.push_back(resting_bid);

                if (resting_bid.remaining_quantity == 0) {
                    book.erase_order_index(resting_bid.order_id);
                    queue.pop_front();
                }
            }

            if (queue.empty()) {
                bids.erase(best_bid_it);
            }
        }

        // Post-matching handling
        if (sell_order.remaining_quantity > 0) {
            if (sell_order.type == OrderType::Limit) {
                // Insert resting remainder into order book
                book.insert_order(sell_order);
            } else {
                // Market order exhausted liquidity: cancel unfilled remainder
                result.cancelled_remainder_quantity = sell_order.remaining_quantity;
                sell_order.remaining_quantity = 0;
                if (sell_order.filled_quantity == 0) {
                    sell_order.status = OrderStatus::Cancelled;
                } else {
                    sell_order.status = OrderStatus::PartiallyFilled;
                }
            }
        }
    }

    std::unordered_map<InstrumentId, Instrument> instruments_;
    std::unordered_map<InstrumentId, OrderBook> books_;
    ExecutionId next_execution_id_{1};
};

}  // namespace rexi::simulator
