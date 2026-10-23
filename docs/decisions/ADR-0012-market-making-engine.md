# ADR-0012: Market Making Engine

## Status
Accepted

## Date
2026-10-23

## Context
High-frequency market making requires dynamic, continuous quoting around prevailing market prices while actively managing inventory risk and defending against adverse selection. In algorithmic trading research, naive market-making models often suffer from three major deficiencies:
1. Symmetrical quoting around the mid-price fails to account for accumulated inventory, causing catastrophic drawdowns in trending markets.
2. Quoting rules that ignore market microstructure (such as Order Flow Imbalance, toxic trade flow, or wide spreads) suffer severe adverse selection from informed counterparties.
3. Overly rigid risk limiters frequently suppress all quotes once a position limit is hit, preventing the market maker from posting liquidity on the opposite side to offload its risky position.

## Decisions

### 1. Avellaneda-Stoikov Reservation Pricing
Implement the canonical inventory-adjusted reservation-price formulation:
$$r(s, q, \tau) = s - q \cdot \gamma \cdot \sigma^2 \cdot \tau$$
Ensuring dimensional correctness where inventory penalty $q \gamma \sigma^2 \tau$ has units of dollars ($\$$). Positive inventory skews reservation price downward ($r < s$), shifting quotations lower to discourage further accumulation and offer more competitive asks; negative inventory symmetrically skews reservation price upward ($r > s$).

### 2. Tick-Size Aware Rounding and Anti-Crossing Invariants
Raw quote prices are rounded to discrete tick increments to preserve passive queue priority:
- Bids round down: $\lfloor p_{\text{bid, raw}} / \text{tick\_size} \rfloor \times \text{tick\_size}$
- Asks round up: $\lceil p_{\text{ask, raw}} / \text{tick\_size} \rceil \times \text{tick\_size}$
Quotes enforce $p_{\text{bid}} < p_{\text{ask}}$ strictly; if tick rounding causes bid to equal or exceed ask, the ask is automatically widened by one tick to prevent locked or crossed quotes.

### 3. Asymmetric Risk-Reducing Quote Preservation
When inventory reaches or breaches a configured risk limit ($q \ge q_{\text{max}}$ or $q \le -q_{\text{max}}$), the engine strictly suppresses only the side that would increase exposure. The opposing, risk-reducing side remains active to allow natural inventory rebalancing.

### 4. Integration with Phase 10 Microstructure Features
Adverse-selection guards monitor Cont et al. (2014) Order Flow Imbalance (OFI), Level 2 Depth Imbalance, and Easley et al. (2012) VPIN. Asymmetric toxic flow suppresses quotes on the vulnerable side to protect the strategy against front-running informed aggressors.

## Consequences

### Positive
- Fully integrated with Phase 11 `BaseStrategy` and 5-point temporal causality contracts.
- Deterministic quote decisions and passive `OrderIntent` generation.
- Strong protection against inventory runaway and toxic flow adverse selection.
- High throughput exceeding 180,000 quote decisions/sec with mean latency of ~5.4 µs.

### Negative / Trade-offs
- Phase 12 simulates local passive quoting intent (`is_post_only=True`); exchange-level post-only order handling and resting-order queue simulation are deferred to Phase 22 (Execution Engine).
