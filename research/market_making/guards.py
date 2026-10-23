"""Adverse-selection, market-quality, and risk guards for Market Making Engine."""

from abc import ABC, abstractmethod
from typing import Any

from research.features.types import MicrostructureFeatureRecord
from research.market_making.types import (
    InventoryState,
    MarketMakingConfig,
    MarketQuoteSnapshot,
    QuoteIntent,
    QuoteSuppressionReason,
)
from research.strategies.types import OrderSide


class BaseMarketGuard(ABC):
    """Abstract interface for market-making risk and market-quality guards."""

    @abstractmethod
    def evaluate(
        self,
        quote_snapshot: MarketQuoteSnapshot,
        inventory_state: InventoryState,
        config: MarketMakingConfig,
        feature_record: MicrostructureFeatureRecord | None = None,
        decision_timestamp_ns: int | None = None,
    ) -> tuple[bool, bool, list[QuoteSuppressionReason]]:
        """Evaluate guard conditions.

        Returns:
        - (bid_allowed, ask_allowed, suppression_reasons)
        """
        ...


class StaleQuoteGuard(BaseMarketGuard):
    """Guard against quoting on stale market data."""

    def evaluate(
        self,
        quote_snapshot: MarketQuoteSnapshot,
        inventory_state: InventoryState,
        config: MarketMakingConfig,
        feature_record: MicrostructureFeatureRecord | None = None,
        decision_timestamp_ns: int | None = None,
    ) -> tuple[bool, bool, list[QuoteSuppressionReason]]:
        if config.stale_quote_timeout_ns <= 0:
            return True, True, []

        eval_ts = (
            decision_timestamp_ns
            if decision_timestamp_ns is not None
            else quote_snapshot.available_timestamp_ns
        )
        elapsed_ns = eval_ts - quote_snapshot.available_timestamp_ns

        if elapsed_ns > config.stale_quote_timeout_ns:
            return False, False, [QuoteSuppressionReason.STALE_MARKET_DATA]

        return True, True, []


class SpreadGuard(BaseMarketGuard):
    """Guard against crossed, locked, or excessively wide market spreads."""

    def evaluate(
        self,
        quote_snapshot: MarketQuoteSnapshot,
        inventory_state: InventoryState,
        config: MarketMakingConfig,
        feature_record: MicrostructureFeatureRecord | None = None,
        decision_timestamp_ns: int | None = None,
    ) -> tuple[bool, bool, list[QuoteSuppressionReason]]:
        # Check crossed or locked book
        if quote_snapshot.is_crossed_or_locked:
            return False, False, [QuoteSuppressionReason.CROSSED_OR_LOCKED_BOOK]

        # Check excessive market spread
        if quote_snapshot.spread_dollars > config.max_market_spread:
            return False, False, [QuoteSuppressionReason.EXCESSIVE_SPREAD]

        return True, True, []


class DepthGuard(BaseMarketGuard):
    """Guard against quoting when displayed book depth is insufficient."""

    def evaluate(
        self,
        quote_snapshot: MarketQuoteSnapshot,
        inventory_state: InventoryState,
        config: MarketMakingConfig,
        feature_record: MicrostructureFeatureRecord | None = None,
        decision_timestamp_ns: int | None = None,
    ) -> tuple[bool, bool, list[QuoteSuppressionReason]]:
        if config.min_displayed_depth <= 0:
            return True, True, []

        if (
            quote_snapshot.best_bid_quantity < config.min_displayed_depth
            or quote_snapshot.best_ask_quantity < config.min_displayed_depth
        ):
            return False, False, [QuoteSuppressionReason.INSUFFICIENT_DEPTH]

        return True, True, []


class VolatilityGuard(BaseMarketGuard):
    """Guard against quoting during periods of extreme short-term market volatility."""

    def evaluate(
        self,
        quote_snapshot: MarketQuoteSnapshot,
        inventory_state: InventoryState,
        config: MarketMakingConfig,
        feature_record: MicrostructureFeatureRecord | None = None,
        decision_timestamp_ns: int | None = None,
    ) -> tuple[bool, bool, list[QuoteSuppressionReason]]:
        if config.max_volatility <= 0.0:
            return True, True, []

        # Check feature record volatility if present, otherwise config volatility
        vol = config.volatility
        if feature_record is not None and feature_record.has_realized_volatility:
            if feature_record.realized_volatility is not None:
                vol = feature_record.realized_volatility

        if vol > config.max_volatility:
            return False, False, [QuoteSuppressionReason.EXCESSIVE_VOLATILITY]

        return True, True, []


class MicrostructureGuard(BaseMarketGuard):
    """Guard against toxic order flow using Phase 10 microstructure features.

    Monitors:
    - Order Flow Imbalance (OFI) magnitude
    - Level 2 Depth Imbalance
    - Volume-Synchronized Probability of Toxicity (VPIN)
    """

    def evaluate(
        self,
        quote_snapshot: MarketQuoteSnapshot,
        inventory_state: InventoryState,
        config: MarketMakingConfig,
        feature_record: MicrostructureFeatureRecord | None = None,
        decision_timestamp_ns: int | None = None,
    ) -> tuple[bool, bool, list[QuoteSuppressionReason]]:
        if feature_record is None:
            return True, True, []

        reasons: list[QuoteSuppressionReason] = []
        bid_allowed = True
        ask_allowed = True

        # OFI Check
        if config.max_ofi_magnitude > 0.0:
            if feature_record.has_rolling_ofi and feature_record.rolling_ofi is not None:
                if abs(feature_record.rolling_ofi) > config.max_ofi_magnitude:
                    reasons.append(QuoteSuppressionReason.MICROSTRUCTURE_IMBALANCE)
                    # Severe positive OFI means heavy aggressive buying; dangerous to quote ask
                    # Severe negative OFI means heavy aggressive selling; dangerous to quote bid
                    if feature_record.rolling_ofi > 0:
                        ask_allowed = False
                    else:
                        bid_allowed = False
            elif config.require_microstructure_validity:
                reasons.append(QuoteSuppressionReason.MICROSTRUCTURE_IMBALANCE)
                return False, False, reasons

        # Depth Imbalance Check
        if config.max_depth_imbalance > 0.0:
            if feature_record.has_depth_imbalance and feature_record.depth_imbalance_k is not None:
                if abs(feature_record.depth_imbalance_k) > config.max_depth_imbalance:
                    reasons.append(QuoteSuppressionReason.MICROSTRUCTURE_IMBALANCE)
                    if feature_record.depth_imbalance_k > 0:
                        ask_allowed = False
                    else:
                        bid_allowed = False
            elif config.require_microstructure_validity:
                reasons.append(QuoteSuppressionReason.MICROSTRUCTURE_IMBALANCE)
                return False, False, reasons

        # VPIN Toxicity Check
        if config.max_vpin > 0.0:
            if feature_record.has_vpin and feature_record.vpin is not None:
                if feature_record.vpin > config.max_vpin:
                    reasons.append(QuoteSuppressionReason.MICROSTRUCTURE_IMBALANCE)
                    bid_allowed = False
                    ask_allowed = False
            elif config.require_microstructure_validity:
                reasons.append(QuoteSuppressionReason.MICROSTRUCTURE_IMBALANCE)
                return False, False, reasons

        return bid_allowed, ask_allowed, reasons


class InventoryLimitGuard(BaseMarketGuard):
    """Guard against breaching long/short inventory limits and maximum notional exposure.

    Crucial Invariant:
    A quote that demonstrably REDUCES inventory risk is NEVER suppressed solely because
    the portfolio is currently at or near an inventory limit.
    """

    def evaluate(
        self,
        quote_snapshot: MarketQuoteSnapshot,
        inventory_state: InventoryState,
        config: MarketMakingConfig,
        feature_record: MicrostructureFeatureRecord | None = None,
        decision_timestamp_ns: int | None = None,
    ) -> tuple[bool, bool, list[QuoteSuppressionReason]]:
        reasons: list[QuoteSuppressionReason] = []
        bid_allowed = True
        ask_allowed = True

        q = inventory_state.inventory
        mid = quote_snapshot.mid_dollars

        # 1. Risk-reduction only mode
        if config.risk_reduction_only:
            reasons.append(QuoteSuppressionReason.RISK_REDUCTION_ONLY)
            if q > 0:
                # Long position: only allow asks (sells) to reduce long inventory
                bid_allowed = False
            elif q < 0:
                # Short position: only allow bids (buys) to cover short inventory
                ask_allowed = False
            else:
                # Flat: no new inventory permitted
                return False, False, reasons

        # 2. Long Inventory Limit (Restricts Bids/Buys)
        if q >= config.max_long_inventory:
            bid_allowed = False
            reasons.append(QuoteSuppressionReason.LONG_INVENTORY_LIMIT)
        elif q + config.quote_size > config.max_long_inventory:
            # If standard quote size would breach limit, suppress or clamp
            bid_allowed = False
            reasons.append(QuoteSuppressionReason.LONG_INVENTORY_LIMIT)

        # 3. Short Inventory Limit (Restricts Asks/Sells)
        if q <= -config.max_short_inventory:
            ask_allowed = False
            reasons.append(QuoteSuppressionReason.SHORT_INVENTORY_LIMIT)
        elif q - config.quote_size < -config.max_short_inventory:
            ask_allowed = False
            reasons.append(QuoteSuppressionReason.SHORT_INVENTORY_LIMIT)

        # 4. Total Notional Exposure Limit
        current_notional = inventory_state.notional_exposure(mid)
        if current_notional >= config.max_notional_exposure:
            reasons.append(QuoteSuppressionReason.MAX_NOTIONAL_EXPOSURE)
            if q > 0:
                # Long: buying adds notional; selling reduces notional
                bid_allowed = False
            elif q < 0:
                # Short: selling adds notional; buying reduces notional
                ask_allowed = False
            else:
                bid_allowed = False
                ask_allowed = False

        return bid_allowed, ask_allowed, reasons


class CompositeMarketGuard:
    """Aggregates all market-making quality and risk guards in deterministic order."""

    def __init__(self, guards: list[BaseMarketGuard] | None = None) -> None:
        self.guards: list[BaseMarketGuard] = guards or [
            StaleQuoteGuard(),
            SpreadGuard(),
            DepthGuard(),
            VolatilityGuard(),
            MicrostructureGuard(),
            InventoryLimitGuard(),
        ]

    def filter_quotes(
        self,
        bid_quote: QuoteIntent,
        ask_quote: QuoteIntent,
        quote_snapshot: MarketQuoteSnapshot,
        inventory_state: InventoryState,
        config: MarketMakingConfig,
        feature_record: MicrostructureFeatureRecord | None = None,
        decision_timestamp_ns: int | None = None,
    ) -> tuple[QuoteIntent, QuoteIntent, list[QuoteSuppressionReason], dict[str, Any]]:
        """Evaluate all guards and apply suppression or size clamping to bid/ask quotes."""
        all_reasons: list[QuoteSuppressionReason] = []
        bid_ok = True
        ask_ok = True
        guard_diagnostics: dict[str, Any] = {}

        for guard in self.guards:
            guard_name = guard.__class__.__name__
            b_allow, a_allow, reasons = guard.evaluate(
                quote_snapshot=quote_snapshot,
                inventory_state=inventory_state,
                config=config,
                feature_record=feature_record,
                decision_timestamp_ns=decision_timestamp_ns,
            )
            guard_diagnostics[guard_name] = {
                "bid_allowed": b_allow,
                "ask_allowed": a_allow,
                "reasons": [r.value for r in reasons],
            }
            if not b_allow:
                bid_ok = False
            if not a_allow:
                ask_ok = False
            all_reasons.extend(reasons)

        # Deduplicate reasons preserving order
        unique_reasons: list[QuoteSuppressionReason] = []
        for r in all_reasons:
            if r not in unique_reasons and r != QuoteSuppressionReason.NONE:
                unique_reasons.append(r)

        # Build output QuoteIntents
        final_bid = bid_quote
        final_ask = ask_quote

        if not bid_ok:
            bid_reason = next(
                (
                    r
                    for r in unique_reasons
                    if r
                    in (
                        QuoteSuppressionReason.LONG_INVENTORY_LIMIT,
                        QuoteSuppressionReason.RISK_REDUCTION_ONLY,
                        QuoteSuppressionReason.MAX_NOTIONAL_EXPOSURE,
                    )
                ),
                unique_reasons[0] if unique_reasons else QuoteSuppressionReason.INVALID_MARKET_DATA,
            )
            final_bid = QuoteIntent(
                side=OrderSide.BUY,
                price_ticks=bid_quote.price_ticks,
                price_dollars=bid_quote.price_dollars,
                quantity=0,
                distance_from_mid=bid_quote.distance_from_mid,
                is_post_only=True,
                is_suppressed=True,
                suppression_reason=bid_reason,
            )

        if not ask_ok:
            ask_reason = next(
                (
                    r
                    for r in unique_reasons
                    if r
                    in (
                        QuoteSuppressionReason.SHORT_INVENTORY_LIMIT,
                        QuoteSuppressionReason.RISK_REDUCTION_ONLY,
                        QuoteSuppressionReason.MAX_NOTIONAL_EXPOSURE,
                    )
                ),
                unique_reasons[0] if unique_reasons else QuoteSuppressionReason.INVALID_MARKET_DATA,
            )
            final_ask = QuoteIntent(
                side=OrderSide.SELL,
                price_ticks=ask_quote.price_ticks,
                price_dollars=ask_quote.price_dollars,
                quantity=0,
                distance_from_mid=ask_quote.distance_from_mid,
                is_post_only=True,
                is_suppressed=True,
                suppression_reason=ask_reason,
            )

        return final_bid, final_ask, unique_reasons, guard_diagnostics
