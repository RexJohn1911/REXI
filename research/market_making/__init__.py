"""REXI Market Making Engine (Phase 12).

Provides quantitative reservation pricing, inventory-aware quote construction,
adverse-selection guards, and passive order intent generation.
"""

from research.market_making.engine import MarketMakingStrategy
from research.market_making.guards import (
    BaseMarketGuard,
    CompositeMarketGuard,
    DepthGuard,
    InventoryLimitGuard,
    MicrostructureGuard,
    SpreadGuard,
    StaleQuoteGuard,
    VolatilityGuard,
)
from research.market_making.model import (
    build_raw_quotes,
    compute_optimal_half_spread,
    compute_reservation_price,
    round_to_tick,
)
from research.market_making.types import (
    InventoryState,
    MarketMakingConfig,
    MarketQuoteSnapshot,
    QuoteDecision,
    QuoteIntent,
    QuoteSuppressionReason,
)

__all__ = [
    "BaseMarketGuard",
    "CompositeMarketGuard",
    "DepthGuard",
    "InventoryLimitGuard",
    "InventoryState",
    "MarketMakingConfig",
    "MarketMakingStrategy",
    "MarketQuoteSnapshot",
    "MicrostructureGuard",
    "QuoteDecision",
    "QuoteIntent",
    "QuoteSuppressionReason",
    "SpreadGuard",
    "StaleQuoteGuard",
    "VolatilityGuard",
    "build_raw_quotes",
    "compute_optimal_half_spread",
    "compute_reservation_price",
    "round_to_tick",
]
