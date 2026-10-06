#pragma once

#include "rexi/market_data/message_header.hpp"
#include "rexi/market_data/messages.hpp"
#include "rexi/market_data/types.hpp"
#include "rexi/order_book/price_level.hpp"
#include "rexi/order_book/resting_order.hpp"
#include "rexi/order_book/types.hpp"

#include <algorithm>
#include <cstdint>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace rexi::order_book {

/**
 * @brief Native Level 3 Snapshot containing explicit resting orders for deterministic recovery.
 */
struct L3Snapshot {
    InstrumentId instrument_id{0};
    SequenceNumber sequence_number{0};
    Timestamp timestamp_ns{0};
    std::vector<RestingOrder> orders{};
};

/**
 * @brief Canonical high-performance, deterministic L2/L3 Order Book.
 *
 * Implements strict price-time FIFO ordering within each price level,
 * O(1) order lookup and cancellation by OrderId, real-time L2 level aggregation,
 * and seamless application of Phase 04 market data messages.
 */
class OrderBook {
public:
    using BidMap = std::map<Price, PriceLevel, std::greater<Price>>;
    using AskMap = std::map<Price, PriceLevel, std::less<Price>>;

    explicit OrderBook(InstrumentId instrument_id = 0,
                       CrossedBookPolicy policy = CrossedBookPolicy::Reject) noexcept
        : instrument_id_(instrument_id), policy_(policy) {}

    // -------------------------------------------------------------------------
    // Rule of 5: Deep Copy & Move Semantics
    // -------------------------------------------------------------------------

    ~OrderBook() = default;

    OrderBook(const OrderBook& other)
        : instrument_id_(other.instrument_id_),
          policy_(other.policy_),
          bids_(other.bids_),
          asks_(other.asks_) {
        rebuild_order_index();
    }

    OrderBook& operator=(const OrderBook& other) {
        if (this != &other) {
            instrument_id_ = other.instrument_id_;
            policy_ = other.policy_;
            bids_ = other.bids_;
            asks_ = other.asks_;
            rebuild_order_index();
        }
        return *this;
    }

    OrderBook(OrderBook&&) noexcept = default;
    OrderBook& operator=(OrderBook&&) noexcept = default;

    // -------------------------------------------------------------------------
    // Properties & Configuration
    // -------------------------------------------------------------------------

    [[nodiscard]] InstrumentId instrument_id() const noexcept { return instrument_id_; }
    void set_instrument_id(InstrumentId id) noexcept { instrument_id_ = id; }

    [[nodiscard]] CrossedBookPolicy policy() const noexcept { return policy_; }
    void set_policy(CrossedBookPolicy policy) noexcept { policy_ = policy; }

    // -------------------------------------------------------------------------
    // Level 1: Best Bid / Best Ask / Top Quote
    // -------------------------------------------------------------------------

    [[nodiscard]] bool has_bids() const noexcept { return !bids_.empty(); }
    [[nodiscard]] bool has_asks() const noexcept { return !asks_.empty(); }
    [[nodiscard]] bool is_empty() const noexcept { return bids_.empty() && asks_.empty(); }

    [[nodiscard]] std::optional<LevelView> best_bid() const noexcept {
        if (bids_.empty()) {
            return std::nullopt;
        }
        return bids_.begin()->second.to_view();
    }

    [[nodiscard]] std::optional<LevelView> best_ask() const noexcept {
        if (asks_.empty()) {
            return std::nullopt;
        }
        return asks_.begin()->second.to_view();
    }

    [[nodiscard]] std::optional<Price> best_bid_price() const noexcept {
        if (bids_.empty()) {
            return std::nullopt;
        }
        return bids_.begin()->first;
    }

    [[nodiscard]] std::optional<Price> best_ask_price() const noexcept {
        if (asks_.empty()) {
            return std::nullopt;
        }
        return asks_.begin()->first;
    }

    [[nodiscard]] Quantity best_bid_quantity() const noexcept {
        if (bids_.empty()) {
            return 0;
        }
        return bids_.begin()->second.total_quantity();
    }

    [[nodiscard]] Quantity best_ask_quantity() const noexcept {
        if (asks_.empty()) {
            return 0;
        }
        return asks_.begin()->second.total_quantity();
    }

    [[nodiscard]] std::optional<Price> spread() const noexcept {
        if (!bids_.empty() && !asks_.empty()) {
            return asks_.begin()->first - bids_.begin()->first;
        }
        return std::nullopt;
    }

    [[nodiscard]] TopQuote top_quote() const noexcept {
        TopQuote quote{};
        if (!bids_.empty()) {
            quote.bid_price = bids_.begin()->first;
            quote.bid_quantity = bids_.begin()->second.total_quantity();
        }
        if (!asks_.empty()) {
            quote.ask_price = asks_.begin()->first;
            quote.ask_quantity = asks_.begin()->second.total_quantity();
        }
        return quote;
    }

    // -------------------------------------------------------------------------
    // Level 2: Aggregated Market Depth
    // -------------------------------------------------------------------------

    [[nodiscard]] size_t bid_level_count() const noexcept { return bids_.size(); }
    [[nodiscard]] size_t ask_level_count() const noexcept { return asks_.size(); }

    [[nodiscard]] Quantity total_bid_quantity() const noexcept {
        Quantity total = 0;
        for (const auto& [price, level] : bids_) {
            (void)price;
            total += level.total_quantity();
        }
        return total;
    }

    [[nodiscard]] Quantity total_ask_quantity() const noexcept {
        Quantity total = 0;
        for (const auto& [price, level] : asks_) {
            (void)price;
            total += level.total_quantity();
        }
        return total;
    }

    /**
     * @brief Extract aggregated bid levels ordered best-to-worst (descending).
     */
    [[nodiscard]] std::vector<LevelView> bids_depth(size_t max_depth = 0) const {
        std::vector<LevelView> depth;
        size_t count = 0;
        for (const auto& [price, level] : bids_) {
            (void)price;
            depth.push_back(level.to_view());
            ++count;
            if (max_depth > 0 && count >= max_depth) {
                break;
            }
        }
        return depth;
    }

    /**
     * @brief Extract aggregated ask levels ordered best-to-worst (ascending).
     */
    [[nodiscard]] std::vector<LevelView> asks_depth(size_t max_depth = 0) const {
        std::vector<LevelView> depth;
        size_t count = 0;
        for (const auto& [price, level] : asks_) {
            (void)price;
            depth.push_back(level.to_view());
            ++count;
            if (max_depth > 0 && count >= max_depth) {
                break;
            }
        }
        return depth;
    }

    [[nodiscard]] std::optional<LevelView> get_level(Side side, Price price) const noexcept {
        if (side == Side::Buy) {
            auto it = bids_.find(price);
            if (it != bids_.end()) {
                return it->second.to_view();
            }
        } else {
            auto it = asks_.find(price);
            if (it != asks_.end()) {
                return it->second.to_view();
            }
        }
        return std::nullopt;
    }

    // -------------------------------------------------------------------------
    // Level 3: Individual Resting Orders
    // -------------------------------------------------------------------------

    [[nodiscard]] size_t order_count() const noexcept { return order_index_.size(); }

    [[nodiscard]] bool has_order(OrderId order_id) const noexcept {
        return order_index_.contains(order_id);
    }

    [[nodiscard]] const RestingOrder* find_order(OrderId order_id) const noexcept {
        auto it = order_index_.find(order_id);
        if (it == order_index_.end()) {
            return nullptr;
        }
        return &(*it->second.order_it);
    }

    /**
     * @brief Calculate the 0-indexed FIFO queue position of an order at its price level.
     */
    [[nodiscard]] std::optional<size_t> get_queue_position(OrderId order_id) const noexcept {
        auto it = order_index_.find(order_id);
        if (it == order_index_.end()) {
            return std::nullopt;
        }
        const auto& loc = it->second;
        if (loc.side == Side::Buy) {
            auto level_it = bids_.find(loc.price);
            if (level_it != bids_.end()) {
                size_t pos = 0;
                for (auto q_it = level_it->second.orders().begin();
                     q_it != level_it->second.orders().end(); ++q_it, ++pos) {
                    if (q_it == loc.order_it) {
                        return pos;
                    }
                }
            }
        } else {
            auto level_it = asks_.find(loc.price);
            if (level_it != asks_.end()) {
                size_t pos = 0;
                for (auto q_it = level_it->second.orders().begin();
                     q_it != level_it->second.orders().end(); ++q_it, ++pos) {
                    if (q_it == loc.order_it) {
                        return pos;
                    }
                }
            }
        }
        return std::nullopt;
    }

    [[nodiscard]] std::vector<RestingOrder> orders_at_level(Side side, Price price) const {
        std::vector<RestingOrder> orders;
        if (side == Side::Buy) {
            auto it = bids_.find(price);
            if (it != bids_.end()) {
                orders.assign(it->second.orders().begin(), it->second.orders().end());
            }
        } else {
            auto it = asks_.find(price);
            if (it != asks_.end()) {
                orders.assign(it->second.orders().begin(), it->second.orders().end());
            }
        }
        return orders;
    }

    // -------------------------------------------------------------------------
    // L3 Mutations: Add, Cancel, Reduce, Modify, Replace
    // -------------------------------------------------------------------------

    /**
     * @brief Insert a new resting order into the book.
     */
    OrderBookStatus add_order(const RestingOrder& order) {
        if (order.order_id == 0) {
            return OrderBookStatus::InvalidOrderId;
        }
        if (instrument_id_ != 0 && order.instrument_id != 0 &&
            order.instrument_id != instrument_id_) {
            return OrderBookStatus::InstrumentMismatch;
        }
        if (order.price <= 0) {
            return OrderBookStatus::InvalidPrice;
        }
        if (order.remaining_quantity == 0) {
            return OrderBookStatus::InvalidQuantity;
        }
        if (order.side != Side::Buy && order.side != Side::Sell) {
            return OrderBookStatus::InvalidSide;
        }
        if (order_index_.contains(order.order_id)) {
            return OrderBookStatus::DuplicateOrderId;
        }

        // Crossed market check
        if (policy_ == CrossedBookPolicy::Reject) {
            if (order.side == Side::Buy && !asks_.empty() && order.price >= asks_.begin()->first) {
                return OrderBookStatus::CrossedMarketRejected;
            }
            if (order.side == Side::Sell && !bids_.empty() && order.price <= bids_.begin()->first) {
                return OrderBookStatus::CrossedMarketRejected;
            }
        }

        if (order.side == Side::Buy) {
            auto& level = bids_.try_emplace(order.price, order.price).first->second;
            auto it = level.push_back(order);
            order_index_[order.order_id] = OrderLocation{Side::Buy, order.price, it};
        } else {
            auto& level = asks_.try_emplace(order.price, order.price).first->second;
            auto it = level.push_back(order);
            order_index_[order.order_id] = OrderLocation{Side::Sell, order.price, it};
        }

        return OrderBookStatus::Success;
    }

    /**
     * @brief Cancel an active resting order by OrderId in O(1) time.
     */
    OrderBookStatus cancel_order(OrderId order_id, RestingOrder* out_cancelled = nullptr) {
        auto it = order_index_.find(order_id);
        if (it == order_index_.end()) {
            return OrderBookStatus::OrderNotFound;
        }

        OrderLocation loc = it->second;
        order_index_.erase(it);

        if (loc.side == Side::Buy) {
            auto level_it = bids_.find(loc.price);
            if (level_it == bids_.end()) {
                return OrderBookStatus::LevelNotFound;
            }
            if (out_cancelled != nullptr) {
                *out_cancelled = *loc.order_it;
            }
            level_it->second.erase(loc.order_it);
            if (level_it->second.is_empty()) {
                bids_.erase(level_it);
            }
        } else {
            auto level_it = asks_.find(loc.price);
            if (level_it == asks_.end()) {
                return OrderBookStatus::LevelNotFound;
            }
            if (out_cancelled != nullptr) {
                *out_cancelled = *loc.order_it;
            }
            level_it->second.erase(loc.order_it);
            if (level_it->second.is_empty()) {
                asks_.erase(level_it);
            }
        }

        return OrderBookStatus::Success;
    }

    /**
     * @brief Reduce the remaining quantity of an active order (e.g., partial fill or reduction).
     */
    OrderBookStatus reduce_order(OrderId order_id, Quantity executed_qty,
                                 RestingOrder* out_order = nullptr) {
        if (executed_qty == 0) {
            return OrderBookStatus::InvalidQuantity;
        }

        auto it = order_index_.find(order_id);
        if (it == order_index_.end()) {
            return OrderBookStatus::OrderNotFound;
        }

        OrderLocation loc = it->second;
        if (executed_qty > loc.order_it->remaining_quantity) {
            return OrderBookStatus::QuantityExceedsRemaining;
        }

        if (loc.side == Side::Buy) {
            auto level_it = bids_.find(loc.price);
            if (level_it == bids_.end()) {
                return OrderBookStatus::LevelNotFound;
            }
            level_it->second.reduce(loc.order_it, executed_qty);
            if (out_order != nullptr) {
                *out_order = *loc.order_it;
            }
            if (loc.order_it->remaining_quantity == 0) {
                level_it->second.erase(loc.order_it);
                if (level_it->second.is_empty()) {
                    bids_.erase(level_it);
                }
                order_index_.erase(it);
            }
        } else {
            auto level_it = asks_.find(loc.price);
            if (level_it == asks_.end()) {
                return OrderBookStatus::LevelNotFound;
            }
            level_it->second.reduce(loc.order_it, executed_qty);
            if (out_order != nullptr) {
                *out_order = *loc.order_it;
            }
            if (loc.order_it->remaining_quantity == 0) {
                level_it->second.erase(loc.order_it);
                if (level_it->second.is_empty()) {
                    asks_.erase(level_it);
                }
                order_index_.erase(it);
            }
        }

        return OrderBookStatus::Success;
    }

    /**
     * @brief Modify quantity at current price:
     * - Quantity decrease: strictly preserves FIFO priority.
     * - Quantity increase: loses FIFO priority (moves to back of queue).
     */
    OrderBookStatus modify_order(OrderId order_id, Quantity new_qty, SequenceNumber new_seq = 0,
                                 Timestamp new_ts = 0) {
        if (new_qty == 0) {
            return OrderBookStatus::InvalidQuantity;
        }

        auto it = order_index_.find(order_id);
        if (it == order_index_.end()) {
            return OrderBookStatus::OrderNotFound;
        }

        OrderLocation& loc = it->second;
        Quantity current_qty = loc.order_it->remaining_quantity;

        if (new_qty == current_qty) {
            return OrderBookStatus::Success;
        }

        if (loc.side == Side::Buy) {
            auto level_it = bids_.find(loc.price);
            if (level_it == bids_.end()) {
                return OrderBookStatus::LevelNotFound;
            }
            if (new_qty < current_qty) {
                // Priority preserved
                level_it->second.reduce(loc.order_it, current_qty - new_qty);
            } else {
                // Priority lost: move to back
                Quantity diff = new_qty - current_qty;
                loc.order_it->remaining_quantity = new_qty;
                level_it->second.add_quantity(diff);
                level_it->second.move_to_back(loc.order_it);
            }
        } else {
            auto level_it = asks_.find(loc.price);
            if (level_it == asks_.end()) {
                return OrderBookStatus::LevelNotFound;
            }
            if (new_qty < current_qty) {
                // Priority preserved
                level_it->second.reduce(loc.order_it, current_qty - new_qty);
            } else {
                // Priority lost: move to back
                Quantity diff = new_qty - current_qty;
                loc.order_it->remaining_quantity = new_qty;
                level_it->second.add_quantity(diff);
                level_it->second.move_to_back(loc.order_it);
            }
        }

        if (new_seq != 0) {
            loc.order_it->priority_seq = new_seq;
        }
        if (new_ts != 0) {
            loc.order_it->timestamp_ns = new_ts;
        }

        return OrderBookStatus::Success;
    }

    /**
     * @brief Replace price and/or quantity:
     * - Price change: loses FIFO priority, leaves old level, joins back of new level.
     * - Price unchanged: delegates to modify_order.
     */
    OrderBookStatus replace_order(OrderId order_id, Price new_price, Quantity new_qty,
                                  SequenceNumber new_seq = 0, Timestamp new_ts = 0) {
        if (new_price <= 0) {
            return OrderBookStatus::InvalidPrice;
        }
        if (new_qty == 0) {
            return OrderBookStatus::InvalidQuantity;
        }

        auto it = order_index_.find(order_id);
        if (it == order_index_.end()) {
            return OrderBookStatus::OrderNotFound;
        }

        OrderLocation loc = it->second;
        if (new_price == loc.price) {
            return modify_order(order_id, new_qty, new_seq, new_ts);
        }

        // Crossed market check for the new price
        if (policy_ == CrossedBookPolicy::Reject) {
            if (loc.side == Side::Buy && !asks_.empty() && new_price >= asks_.begin()->first) {
                return OrderBookStatus::CrossedMarketRejected;
            }
            if (loc.side == Side::Sell && !bids_.empty() && new_price <= bids_.begin()->first) {
                return OrderBookStatus::CrossedMarketRejected;
            }
        }

        // Copy order state
        RestingOrder updated = *loc.order_it;
        updated.price = new_price;
        updated.remaining_quantity = new_qty;
        updated.initial_quantity = new_qty;
        if (new_seq != 0) {
            updated.priority_seq = new_seq;
        }
        if (new_ts != 0) {
            updated.timestamp_ns = new_ts;
        }

        // Remove from old level
        if (loc.side == Side::Buy) {
            auto level_it = bids_.find(loc.price);
            if (level_it != bids_.end()) {
                level_it->second.erase(loc.order_it);
                if (level_it->second.is_empty()) {
                    bids_.erase(level_it);
                }
            }
            // Insert into new level
            auto& new_level = bids_.try_emplace(new_price, new_price).first->second;
            auto new_it = new_level.push_back(updated);
            it->second = OrderLocation{Side::Buy, new_price, new_it};
        } else {
            auto level_it = asks_.find(loc.price);
            if (level_it != asks_.end()) {
                level_it->second.erase(loc.order_it);
                if (level_it->second.is_empty()) {
                    asks_.erase(level_it);
                }
            }
            // Insert into new level
            auto& new_level = asks_.try_emplace(new_price, new_price).first->second;
            auto new_it = new_level.push_back(updated);
            it->second = OrderLocation{Side::Sell, new_price, new_it};
        }

        return OrderBookStatus::Success;
    }

    // -------------------------------------------------------------------------
    // Phase 04 Market Data Protocol Integration
    // -------------------------------------------------------------------------

    /**
     * @brief Apply a Phase 04 OrderBookAddMessage.
     */
    OrderBookStatus apply_add(const rexi::market_data::MarketDataHeader& header,
                              const rexi::market_data::OrderBookAddMessage& msg) {
        if (header.message_type != rexi::market_data::MarketDataMessageType::OrderBookAdd) {
            return OrderBookStatus::InvalidMessageType;
        }
        if (instrument_id_ != 0 && header.instrument_id != 0 &&
            header.instrument_id != instrument_id_) {
            return OrderBookStatus::InstrumentMismatch;
        }
        if (msg.order_id == 0) {
            return OrderBookStatus::InvalidOrderId;
        }
        if (msg.price <= 0) {
            return OrderBookStatus::InvalidPrice;
        }
        if (msg.quantity == 0) {
            return OrderBookStatus::InvalidQuantity;
        }

        auto side_opt = from_market_side(msg.side);
        if (!side_opt.has_value()) {
            return OrderBookStatus::InvalidSide;
        }

        RestingOrder order{
            .order_id = msg.order_id,
            .instrument_id = header.instrument_id,
            .side = *side_opt,
            .price = msg.price,
            .initial_quantity = msg.quantity,
            .remaining_quantity = msg.quantity,
            .priority_seq = header.sequence_num,
            .timestamp_ns = header.source_timestamp_ns,
        };

        return add_order(order);
    }

    /**
     * @brief Apply a Phase 04 OrderBookModifyMessage.
     */
    OrderBookStatus apply_modify(const rexi::market_data::MarketDataHeader& header,
                                 const rexi::market_data::OrderBookModifyMessage& msg) {
        if (header.message_type != rexi::market_data::MarketDataMessageType::OrderBookModify) {
            return OrderBookStatus::InvalidMessageType;
        }
        if (instrument_id_ != 0 && header.instrument_id != 0 &&
            header.instrument_id != instrument_id_) {
            return OrderBookStatus::InstrumentMismatch;
        }
        if (msg.order_id == 0) {
            return OrderBookStatus::InvalidOrderId;
        }
        if (msg.price <= 0) {
            return OrderBookStatus::InvalidPrice;
        }
        if (msg.new_quantity == 0) {
            return OrderBookStatus::InvalidQuantity;
        }

        return replace_order(msg.order_id, msg.price, msg.new_quantity, header.sequence_num,
                             header.source_timestamp_ns);
    }

    /**
     * @brief Apply a Phase 04 OrderBookDeleteMessage.
     */
    OrderBookStatus apply_delete(const rexi::market_data::MarketDataHeader& header,
                                 const rexi::market_data::OrderBookDeleteMessage& msg) {
        if (header.message_type != rexi::market_data::MarketDataMessageType::OrderBookDelete) {
            return OrderBookStatus::InvalidMessageType;
        }
        if (instrument_id_ != 0 && header.instrument_id != 0 &&
            header.instrument_id != instrument_id_) {
            return OrderBookStatus::InstrumentMismatch;
        }
        if (msg.order_id == 0) {
            return OrderBookStatus::InvalidOrderId;
        }

        return cancel_order(msg.order_id);
    }

    /**
     * @brief Apply a canonical Phase 04 OrderBookSnapshotMessage.
     *
     * Clears current state and reconstructs L2 aggregated price levels without
     * fabricating synthetic L3 order identities.
     */
    OrderBookStatus apply_snapshot(const rexi::market_data::OrderBookSnapshotMessage& snapshot) {
        if (snapshot.bid_levels_count > rexi::market_data::MaxSnapshotLevels ||
            snapshot.ask_levels_count > rexi::market_data::MaxSnapshotLevels) {
            return OrderBookStatus::InvalidSnapshot;
        }

        // Validate descending bids
        for (size_t i = 1; i < snapshot.bid_levels_count; ++i) {
            if (snapshot.bids[i].price >= snapshot.bids[i - 1].price) {
                return OrderBookStatus::InvalidSnapshot;
            }
        }

        // Validate ascending asks
        for (size_t i = 1; i < snapshot.ask_levels_count; ++i) {
            if (snapshot.asks[i].price <= snapshot.asks[i - 1].price) {
                return OrderBookStatus::InvalidSnapshot;
            }
        }

        // Crossed market check
        if (policy_ == CrossedBookPolicy::Reject && snapshot.bid_levels_count > 0 &&
            snapshot.ask_levels_count > 0) {
            if (snapshot.bids[0].price >= snapshot.asks[0].price) {
                return OrderBookStatus::CrossedMarketRejected;
            }
        }

        clear();

        for (size_t i = 0; i < snapshot.bid_levels_count; ++i) {
            const auto& lvl = snapshot.bids[i];
            if (lvl.price > 0 && lvl.quantity > 0) {
                auto& pl = bids_.try_emplace(lvl.price, lvl.price).first->second;
                pl.set_l2_aggregate(lvl.quantity, lvl.order_count > 0 ? lvl.order_count : 1);
            }
        }

        for (size_t i = 0; i < snapshot.ask_levels_count; ++i) {
            const auto& lvl = snapshot.asks[i];
            if (lvl.price > 0 && lvl.quantity > 0) {
                auto& pl = asks_.try_emplace(lvl.price, lvl.price).first->second;
                pl.set_l2_aggregate(lvl.quantity, lvl.order_count > 0 ? lvl.order_count : 1);
            }
        }

        return OrderBookStatus::Success;
    }

    /**
     * @brief Export the current state as a Phase 04 OrderBookSnapshotMessage.
     *
     * Truncates to the protocol's 10-level limit per side.
     */
    [[nodiscard]] rexi::market_data::OrderBookSnapshotMessage to_phase04_snapshot(
        SequenceNumber seq = 0) const noexcept {
        rexi::market_data::OrderBookSnapshotMessage snap{};
        snap.last_included_sequence = seq;

        size_t b_idx = 0;
        for (const auto& [price, level] : bids_) {
            (void)price;
            if (b_idx >= rexi::market_data::MaxSnapshotLevels) {
                break;
            }
            snap.bids[b_idx] = rexi::market_data::OrderBookSnapshotLevel{
                .price = level.price(),
                .quantity = level.total_quantity(),
                .order_count = level.order_count(),
            };
            ++b_idx;
        }
        snap.bid_levels_count = static_cast<uint32_t>(b_idx);

        size_t a_idx = 0;
        for (const auto& [price, level] : asks_) {
            (void)price;
            if (a_idx >= rexi::market_data::MaxSnapshotLevels) {
                break;
            }
            snap.asks[a_idx] = rexi::market_data::OrderBookSnapshotLevel{
                .price = level.price(),
                .quantity = level.total_quantity(),
                .order_count = level.order_count(),
            };
            ++a_idx;
        }
        snap.ask_levels_count = static_cast<uint32_t>(a_idx);

        return snap;
    }

    // -------------------------------------------------------------------------
    // Native Level 3 Snapshot Import / Export
    // -------------------------------------------------------------------------

    /**
     * @brief Apply a native L3 snapshot containing full resting order state.
     */
    OrderBookStatus apply_l3_snapshot(const L3Snapshot& snapshot) {
        if (instrument_id_ != 0 && snapshot.instrument_id != 0 &&
            snapshot.instrument_id != instrument_id_) {
            return OrderBookStatus::InstrumentMismatch;
        }

        clear();
        for (const auto& order : snapshot.orders) {
            auto status = add_order(order);
            if (status != OrderBookStatus::Success) {
                return status;
            }
        }
        return OrderBookStatus::Success;
    }

    /**
     * @brief Export complete L3 resting order state.
     */
    [[nodiscard]] L3Snapshot to_l3_snapshot(SequenceNumber seq = 0,
                                            Timestamp ts = 0) const noexcept {
        L3Snapshot snap{
            .instrument_id = instrument_id_,
            .sequence_number = seq,
            .timestamp_ns = ts,
            .orders = {},
        };
        snap.orders.reserve(order_index_.size());
        for (const auto& [price, level] : bids_) {
            (void)price;
            for (const auto& ord : level.orders()) {
                snap.orders.push_back(ord);
            }
        }
        for (const auto& [price, level] : asks_) {
            (void)price;
            for (const auto& ord : level.orders()) {
                snap.orders.push_back(ord);
            }
        }
        return snap;
    }

    // -------------------------------------------------------------------------
    // Clear & Validation
    // -------------------------------------------------------------------------

    void clear() noexcept {
        bids_.clear();
        asks_.clear();
        order_index_.clear();
    }

    /**
     * @brief Comprehensive internal invariant validation.
     */
    [[nodiscard]] ValidationResult validate() const {
        // Invariant 1: Bids strictly descending
        Price prev_bid = 0;
        bool first_bid = true;
        for (const auto& [price, level] : bids_) {
            if (price <= 0) {
                return ValidationResult{false, "Bid price <= 0"};
            }
            if (!first_bid && price >= prev_bid) {
                return ValidationResult{false, "Bid levels not strictly descending"};
            }
            prev_bid = price;
            first_bid = false;

            if (level.is_empty()) {
                return ValidationResult{false, "Empty bid level present in map"};
            }
            if (level.total_quantity() == 0) {
                return ValidationResult{false, "Bid level has 0 total quantity"};
            }

            if (!level.is_l2_aggregate_only()) {
                Quantity sum_qty = 0;
                for (const auto& ord : level.orders()) {
                    if (ord.side != Side::Buy) {
                        return ValidationResult{false, "Non-buy order in bid level"};
                    }
                    if (ord.price != price) {
                        return ValidationResult{false, "Order price mismatch in bid level"};
                    }
                    if (ord.remaining_quantity == 0) {
                        return ValidationResult{false, "Order has 0 remaining quantity"};
                    }
                    if (instrument_id_ != 0 && ord.instrument_id != 0 &&
                        ord.instrument_id != instrument_id_) {
                        return ValidationResult{false, "Order instrument mismatch"};
                    }
                    auto idx_it = order_index_.find(ord.order_id);
                    if (idx_it == order_index_.end()) {
                        return ValidationResult{false, "Resting order missing from index"};
                    }
                    if (idx_it->second.price != price || idx_it->second.side != Side::Buy) {
                        return ValidationResult{false, "Index location mismatch for bid order"};
                    }
                    sum_qty += ord.remaining_quantity;
                }
                if (sum_qty != level.total_quantity()) {
                    return ValidationResult{false, "Bid level quantity sum mismatch"};
                }
                if (level.orders().size() != level.order_count()) {
                    return ValidationResult{false, "Bid level order count mismatch"};
                }
            }
        }

        // Invariant 2: Asks strictly ascending
        Price prev_ask = 0;
        bool first_ask = true;
        for (const auto& [price, level] : asks_) {
            if (price <= 0) {
                return ValidationResult{false, "Ask price <= 0"};
            }
            if (!first_ask && price <= prev_ask) {
                return ValidationResult{false, "Ask levels not strictly ascending"};
            }
            prev_ask = price;
            first_ask = false;

            if (level.is_empty()) {
                return ValidationResult{false, "Empty ask level present in map"};
            }
            if (level.total_quantity() == 0) {
                return ValidationResult{false, "Ask level has 0 total quantity"};
            }

            if (!level.is_l2_aggregate_only()) {
                Quantity sum_qty = 0;
                for (const auto& ord : level.orders()) {
                    if (ord.side != Side::Sell) {
                        return ValidationResult{false, "Non-sell order in ask level"};
                    }
                    if (ord.price != price) {
                        return ValidationResult{false, "Order price mismatch in ask level"};
                    }
                    if (ord.remaining_quantity == 0) {
                        return ValidationResult{false, "Order has 0 remaining quantity"};
                    }
                    if (instrument_id_ != 0 && ord.instrument_id != 0 &&
                        ord.instrument_id != instrument_id_) {
                        return ValidationResult{false, "Order instrument mismatch"};
                    }
                    auto idx_it = order_index_.find(ord.order_id);
                    if (idx_it == order_index_.end()) {
                        return ValidationResult{false, "Resting order missing from index"};
                    }
                    if (idx_it->second.price != price || idx_it->second.side != Side::Sell) {
                        return ValidationResult{false, "Index location mismatch for ask order"};
                    }
                    sum_qty += ord.remaining_quantity;
                }
                if (sum_qty != level.total_quantity()) {
                    return ValidationResult{false, "Ask level quantity sum mismatch"};
                }
                if (level.orders().size() != level.order_count()) {
                    return ValidationResult{false, "Ask level order count mismatch"};
                }
            }
        }

        // Invariant 3: Total indexed orders equals count of active L3 orders
        size_t total_l3_orders = 0;
        for (const auto& [price, level] : bids_) {
            (void)price;
            if (!level.is_l2_aggregate_only()) {
                total_l3_orders += level.order_count();
            }
        }
        for (const auto& [price, level] : asks_) {
            (void)price;
            if (!level.is_l2_aggregate_only()) {
                total_l3_orders += level.order_count();
            }
        }
        if (total_l3_orders != order_index_.size()) {
            return ValidationResult{false, "Total L3 orders does not match order_index size"};
        }

        // Invariant 4: Crossed market check in Reject policy
        if (policy_ == CrossedBookPolicy::Reject && !bids_.empty() && !asks_.empty()) {
            if (bids_.begin()->first >= asks_.begin()->first) {
                return ValidationResult{false, "Crossed market in Reject policy"};
            }
        }

        return ValidationResult{true, ""};
    }

private:
    struct OrderLocation {
        Side side{Side::Buy};
        Price price{0};
        PriceLevel::OrderIterator order_it{};
    };

    void rebuild_order_index() {
        order_index_.clear();
        for (auto& [price, level] : bids_) {
            for (auto it = level.orders().begin(); it != level.orders().end(); ++it) {
                order_index_[it->order_id] = OrderLocation{Side::Buy, price, it};
            }
        }
        for (auto& [price, level] : asks_) {
            for (auto it = level.orders().begin(); it != level.orders().end(); ++it) {
                order_index_[it->order_id] = OrderLocation{Side::Sell, price, it};
            }
        }
    }

    InstrumentId instrument_id_{0};
    CrossedBookPolicy policy_{CrossedBookPolicy::Reject};
    BidMap bids_{};
    AskMap asks_{};
    std::unordered_map<OrderId, OrderLocation> order_index_{};
};

}  // namespace rexi::order_book
