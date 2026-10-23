# REXI Market Making Engine Architecture

## 1. Executive Summary

Phase 12 establishes the canonical **Market Making Engine** for REXI. Operating under the quantitative research framework established in Phases 08, 09, 10, and 11, this phase delivers:
1. **Strongly-Typed Market Making Domain Models** (`research/market_making/types.py`):
   - Validated data models for market quote snapshots, inventory states, quote intents, and comprehensive quote decisions.
   - Fine-grained `QuoteSuppressionReason` taxonomy distinguishing market data invalidity, crossed/locked books, stale quotes, excessive spreads, insufficient depth, volatility spikes, microstructure toxic flows (OFI/VPIN), and inventory/notional limits.
   - Comprehensive `MarketMakingConfig` encapsulating Avellaneda-Stoikov parameters, inventory limits, and adverse-selection guard thresholds.
2. **Quantitative Reservation-Price and Optimal Spread Models** (`research/market_making/model.py`):
   - Canonical Avellaneda-Stoikov (2008) reservation-price formulation:
     $$r(s, q, \tau) = s - q \cdot \gamma \cdot \sigma^2 \cdot \tau$$
   - Rigorous dimensional analysis ensuring all parameter units are mathematically consistent.
   - Inventory directional skew invariants: long inventory ($q > 0$) lowers reservation price ($r < s$), making the ask more competitive and the bid less aggressive; short inventory ($q < 0$) raises reservation price ($r > s$), making the bid more aggressive and the ask less competitive.
   - Tick-size-aware quote rounding preserving queue priority: bids round down, asks round up, with strict anti-crossing invariants ($p_{\text{bid}} < p_{\text{ask}}$).
3. **Adverse-Selection & Market-Quality Guards** (`research/market_making/guards.py`):
   - Modular, configurable guard hierarchy (`StaleQuoteGuard`, `SpreadGuard`, `DepthGuard`, `VolatilityGuard`, `MicrostructureGuard`, `InventoryLimitGuard`).
   - Integration with Phase 10 microstructure features (Order Flow Imbalance, Level 2 Depth Imbalance, and VPIN).
   - Asymmetric risk-mitigation: quotes that demonstrably reduce inventory risk are never suppressed solely because the portfolio is at or near an inventory limit.
4. **Strategy Lifecycle & Phase 11 Integration** (`research/market_making/engine.py`):
   - `MarketMakingStrategy` inheriting from `BaseStrategy`, providing both streaming evaluation (`on_quote`, `on_features`, `on_fill`) and table-based signal generation (`generate_signals`).
   - Generation of passive `OrderIntent` objects (`order_type=OrderType.LIMIT`, `is_post_only=True`) adhering strictly to the 5-point temporal coordinate chain ($T_{\text{event}} \le T_{\text{available}} \le T_{\text{decision}} \le T_{\text{actionable}} \le T_{\text{fill}}$).

---

## 2. Quantitative Model & Dimensional Analysis

### Reservation Price Formulation
Following Avellaneda & Stoikov (2008) (*"High-frequency trading in a limit order book"*), the market maker's reservation price $r$ is the indifference price at which the agent is neutral between holding current inventory $q$ and trading one marginal share:

$$r(s, q, \tau) = s - q \cdot \gamma \cdot \sigma^2 \cdot \tau$$

where:
- $s$: Prevailing mid-price in dollars ($\$ / \text{share}$).
- $q$: Current inventory in shares ($q > 0$ for long, $q < 0$ for short, $0$ for flat).
- $\gamma$: Absolute risk-aversion parameter ($1 / (\$ \cdot \text{shares})$).
- $\sigma$: Price volatility ($\$ / \sqrt{\text{unit\_time}}$).
- $\sigma^2$: Price variance per unit time ($\$^2 / \text{unit\_time}$).
- $\tau$: Remaining investment horizon in $\text{unit\_time}$.

### Dimensional Consistency
$$\text{Penalty Unit} = [\text{shares}] \times \left[\frac{1}{\$ \cdot \text{shares}}\right] \times \left[\frac{\$^2}{\text{unit\_time}}\right] \times [\text{unit\_time}] = [\$]$$
The penalty term has exact units of dollars ($\$$), matching mid-price $s$.

### Optimal Spread Formulation
When `use_optimal_spread=True`, the engine computes the closed-form Avellaneda-Stoikov half-spread:
$$\delta^*(s) = \frac{1}{\gamma} \ln\left(1 + \frac{\gamma}{\kappa}\right)$$
where $\kappa$ is the empirical order arrival intensity. As risk-neutrality is approached ($\gamma \to 0$):
$$\lim_{\gamma \to 0} \delta^*(s) = \frac{1}{\kappa}$$

---

## 3. Quoting Pipeline & Invariants

```
+-----------------------------------------------------------------------------------+
|                        Incoming Market Quote Snapshot                             |
|          (T_event, T_avail, best_bid, best_ask, bid_qty, ask_qty)                 |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                       Avellaneda-Stoikov Pricing Core                             |
|   1. Mid-Price: s = (p_bid + p_ask) / 2                                           |
|   2. Reservation Price: r = s - q * gamma * sigma^2 * tau                         |
|   3. Half-Spread: delta_half (fixed or optimal AS closed-form)                    |
|   4. Raw Quotes: p_bid_raw = r - delta_half, p_ask_raw = r + delta_half           |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                       Tick-Size Rounding & Queue Passivity                        |
|   - Bid Price: floor(p_bid_raw / tick_size) * tick_size                           |
|   - Ask Price: ceil(p_ask_raw / tick_size) * tick_size                            |
|   - Anti-Crossing Invariant: p_bid_ticks < p_ask_ticks strictly enforced          |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                   Adverse-Selection & Market Quality Guards                       |
|   - StaleQuoteGuard: T_decision - T_avail <= timeout_ns                           |
|   - SpreadGuard: p_ask - p_bid <= max_market_spread, book not crossed/locked      |
|   - DepthGuard: bid_qty >= min_depth and ask_qty >= min_depth                     |
|   - VolatilityGuard: realized_volatility <= max_volatility                        |
|   - MicrostructureGuard: |OFI| <= max_ofi, |depth_imbal| <= max_imbal, VPIN safe  |
|   - InventoryLimitGuard: enforce max long/short bounds, allow risk-reducing quotes|
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                   QuoteDecision & OrderIntent Generation                          |
|   - Emits QuoteDecision with diagnostics and suppression taxonomy                 |
|   - Emits passive Limit OrderIntents (OrderType.LIMIT, is_post_only=True)         |
|   - Enforces 5-point temporal causality: T_event <= T_avail <= T_dec <= T_act     |
+-----------------------------------------------------------------------------------+
```

---

## 4. Adverse-Selection & Risk Guard Taxonomy

| Guard | Condition Evaluated | Failure Trigger | Suppression Action |
| :--- | :--- | :--- | :--- |
| **`StaleQuoteGuard`** | $T_{\text{decision}} - T_{\text{available}} > \tau_{\text{stale}}$ | Stale market data | Suppress both Bid & Ask |
| **`SpreadGuard`** | $P_{\text{bid}} \ge P_{\text{ask}}$ or Spread $> \text{max\_spread}$ | Crossed, locked, or blown-out book | Suppress both Bid & Ask |
| **`DepthGuard`** | $Q_{\text{bid}} < Q_{\text{min}}$ or $Q_{\text{ask}} < Q_{\text{min}}$ | Insufficient book liquidity | Suppress both Bid & Ask |
| **`VolatilityGuard`** | $\sigma_{\text{realized}} > \sigma_{\text{max}}$ | Extreme market turbulence | Suppress both Bid & Ask |
| **`MicrostructureGuard`** | $|\text{OFI}| > \text{OFI}_{\text{max}}$, VPIN $> \text{VPIN}_{\text{max}}$ | Toxic directional order flow | Suppress exposed side (or both) |
| **`InventoryLimitGuard`** | $q \ge q_{\text{max, long}}$ | Long position limit reached | Suppress Bid (Ask remains active) |
| **`InventoryLimitGuard`** | $q \le -q_{\text{max, short}}$ | Short position limit reached | Suppress Ask (Bid remains active) |
| **`InventoryLimitGuard`** | $|q| \cdot s \ge \text{Notional}_{\text{max}}$ | Maximum notional breached | Suppress risk-increasing side |
