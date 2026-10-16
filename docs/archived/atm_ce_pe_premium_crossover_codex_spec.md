# ATM CE/PE Premium Crossover Trading System — Codex Specification

## 1. Product goal

Build an intuitive intraday options-trading application focused on identifying and executing **long-only ATM CE and ATM PE trades** using direct option-premium EMA crossovers.

The business objective is positive, sustainable **net profitability after all trading costs**, with controlled drawdown. Profit is not guaranteed. The system must not optimize only for win rate or gross P&L; it must evaluate expectancy, drawdown, tail losses, slippage, and out-of-sample performance.

Initial underlying universe:
- NIFTY
- BANKNIFTY
- SENSEX
- Extensible to additional supported indices through configuration.

The app tracks CE and PE independently and displays their charts side by side. No short option selling and no index-crossover-based entry trigger.

## 2. Core trading concept

- Select the ATM CE and ATM PE for the configured underlying and expiry.
- Calculate EMA 8 and EMA 21 directly on each option's own 1-minute premium candles.
- A bullish crossover on the CE premium can trigger a **long CE** trade if filters/risk checks pass.
- A bullish crossover on the PE premium can trigger a **long PE** trade if filters/risk checks pass.
- CE and PE are independent signal streams. The system may be configured to allow only one open position total (default), or one per side as a later configurable mode.
- Do not infer a PE entry from a bearish index signal. The PE itself must show a valid long-premium setup.

## 3. Expiry / DTE policy

User preference: for DTE 0 and DTE 1 situations, use the next available expiry to reduce exposure to near-expiry theta decay.

Implement an explicit, configurable expiry resolver:
1. Determine the current contract's DTE using exchange calendar/expiry metadata, not a simplistic calendar-day assumption.
2. If the nearest expiry is DTE 0 or DTE 1, select the **next listed eligible expiry**.
3. Otherwise select the nearest eligible expiry, unless the user chooses another policy.
4. Display selected expiry, DTE, and reason in the UI.
5. If next expiry data/contracts are unavailable or stale, block entry; do not silently fall back to same-day expiry.
6. Include a user override for expiry policy, but require explicit confirmation and log it.

Important: selecting the next expiry may reduce immediate expiry-day theta exposure, but does not eliminate theta decay or guarantee better results. Compare expiry policies in backtests, including liquidity and spread differences.

## 4. ATM contract selection

For the selected index:
- Obtain current underlying price and authoritative option-chain/contract-master data.
- Select the nearest listed strike to underlying LTP using the provider's strike metadata/interval.
- Resolve both CE and PE at that strike for the selected expiry.
- Revalidate contract identifiers, expiry, strike, and tradability before every order.
- Load current lot size from the instrument master; never hard-code a permanent lot size.
- Show underlying LTP, ATM strike, CE/PE symbols, expiry, DTE, lot size, quote timestamp, bid/ask, spread, and premium LTP.
- If underlying or option-chain data is stale, missing, or inconsistent, block entries and explain why.
- Re-evaluate ATM selection as the underlying moves. Do not silently change the contract for an open position; retain the actual traded contract until exit. New entries use the latest valid ATM contract.

## 5. Signal indicators and entry rules

### Per-option indicators (1-minute candles)
| Indicator | Default |
|---|---:|
| Fast EMA | 8 |
| Slow EMA | 21 |
| ATR | 14 |
| Premium expansion lookback | 3 completed bars |
| Minimum premium expansion | Configurable; calibrate via backtest |

All parameters must be configurable.

### Long CE entry
On a confirmed 1-minute CE candle:
1. CE EMA 8 crosses above CE EMA 21.
2. CE candle closes above both EMAs.
3. Premium expansion filter passes.
4. Liquidity/spread and quote-freshness checks pass.
5. PCR, OI-change, and IV are available or meet the user's configured data-quality policy. These are context/optional filters initially, not mandatory directional predictors.
6. Risk, session, cooldown, daily-loss, and position limits permit entry.
7. No duplicate entry for the same signal/candle.

### Long PE entry
Same rules, applied independently to the PE premium:
1. PE EMA 8 crosses above PE EMA 21.
2. PE candle closes above both EMAs.
3. PE premium expansion filter passes.
4. Liquidity/spread and quote-freshness checks pass.
5. PCR, OI-change, and IV context/data-quality policy passes.
6. Risk/session/cooldown/daily-loss/position limits permit entry.
7. No duplicate entry for the same signal/candle.

The crossover must be calculated on the option's own premium series—not the underlying index.

## 6. Premium expansion and liquidity filters

Implement separately toggleable, observable gates:
- EMA 8 > EMA 21 after a fresh bullish crossover.
- Positive EMA 8 slope over configurable bars.
- Premium percentage change over configurable completed-bar lookback >= configurable threshold.
- Latest completed candle closes above prior close and above EMA 8.
- Maximum bid/ask spread percentage.
- Minimum traded volume and/or quote depth when provider data supports it.
- Maximum quote/candle age.

Do not use a single LTP spike as confirmation. Do not fabricate missing candles or quote values. Clearly mark unavailable volume/depth fields. Thresholds must be validated by instrument, expiry, and time of day.

## 7. PCR, Change in OI, and IV analytics

Provide a live market-context panel for the selected underlying and expiry.

### PCR (Put-Call Ratio)
- Display PCR based on **open interest** as the default: total PE OI / total CE OI across a clearly defined strike range.
- Make the strike range and expiry scope configurable and visible.
- Optionally display volume PCR separately; never label it simply PCR without specifying the basis.
- Show current value, previous comparable value, absolute change, and percentage change where mathematically valid.
- Explain that PCR is contextual and not a standalone buy/sell signal.

### Change in Open Interest (Change in OI)
For CE and PE separately, display:
- Current OI
- Previous snapshot OI
- Absolute Change in OI = current OI − previous OI
- Percentage Change in OI = (change in OI / previous OI) × 100, only when previous OI > 0
- Snapshot interval and timestamp
- Scope: selected ATM strike, configurable near-ATM band, and/or whole selected-expiry chain. Make scope explicit and selectable.
- Present CE and PE side by side, with clear units and signs.
- If provider supplies exchange-calculated Change in OI, retain source metadata and reconcile/label it distinctly from app-calculated change.
- Do not interpret rising OI as inherently bullish or bearish; pair it with price movement and present as context, not certainty.

### Implied Volatility (IV)
- Display IV for selected ATM CE and PE, plus optional near-ATM chain summary.
- Show IV value, timestamp, source, and whether it is provider-supplied or model-derived.
- If model-derived, document inputs and model assumptions (underlying price, strike, expiry/time-to-expiry, rates, dividends, option price); do not present it as exchange-provided IV.
- Show IV change over configurable intervals if historical snapshots exist.
- Handle missing/invalid IV explicitly; do not substitute zero.
- IV is contextual and can change option premiums independently of underlying direction.

### Data quality
PCR, OI, and IV may be delayed, sampled, or unavailable depending on provider. Display timestamps and freshness. Configure whether stale analytics merely warn or block entries. Never imply these metrics are predictive guarantees.

## 8. Exit and risk management

Long option positions only. Exits operate on the actual purchased option contract.

Configurable:
- Initial stop-loss: percentage from actual fill or ATR-based on option candles; select one mode explicitly.
- Profit target: configurable percentage or R-multiple.
- Optional trailing stop: activates after a configurable favorable move; only tightens.
- Exit on option EMA 8 crossing below EMA 21.
- Optional max-hold/time exit and mandatory intraday square-off time.
- Max risk per trade, max daily loss, max trades/day, cooldown after loss.
- Default one open position total; no pyramiding.
- Quantity in lots; lot size from current instrument master.
- Position sizing must respect max-risk and capital constraints.
- Include brokerage, exchange fees, taxes where applicable, and realistic slippage in backtests.
- Define daily loss based on realized P&L or realized + unrealized P&L; expose the chosen mode.
- When daily loss limit is reached, block new entries and apply the configured open-position management policy.
- Live trading disabled by default. Paper trading is the initial execution mode.

Never loosen a stop after it has tightened. No overnight holding unless explicitly designed and separately tested.

## 9. UI / page layout

Create a responsive, intuitive dashboard with a **vertical split into two equal primary panels**:

### Left panel — PE
- Header: selected index, PE, ATM strike, expiry, DTE.
- 1-minute PE premium candlestick chart.
- EMA 8 and EMA 21 overlays.
- Entry/exit markers and premium-expansion markers.
- Premium LTP, bid/ask, spread, volume, IV.
- Signal status and filter checklist.
- PE OI / Change in OI metrics.

### Right panel — CE
- Header: selected index, CE, ATM strike, expiry, DTE.
- 1-minute CE premium candlestick chart.
- EMA 8 and EMA 21 overlays.
- Entry/exit markers and premium-expansion markers.
- Premium LTP, bid/ask, spread, volume, IV.
- Signal status and filter checklist.
- CE OI / Change in OI metrics.

Both panels must use the **same selected ATM strike and expiry** for direct comparison. If a new ATM strike is resolved, update both panels together for new signals; preserve chart/position history for contracts already traded.

### Shared top bar
- Index selector: NIFTY / BANKNIFTY / SENSEX / configured indices.
- Expiry policy and selected expiry/DTE.
- Market/session status, data connection/freshness, paper/live mode.
- Underlying LTP and ATM strike.
- Strategy enable/pause control.

### Shared analytics strip
- OI PCR with scope, value, and change.
- CE vs PE Change in OI (absolute and %).
- CE IV vs PE IV and IV change.
- Data timestamps and quality indicators.

### Bottom area
- Open positions/orders, fills, realized/unrealized P&L.
- Risk status: daily P&L, loss budget remaining, trade count.
- Signal/event log including blocked-signal reasons.
- Strategy settings and backtest summary.

### UX requirements
- Clear state labels: `NO SIGNAL`, `CANDIDATE`, `WAITING FOR EXPANSION`, `READY`, `BLOCKED`, `IN POSITION`.
- Show why a trade is blocked; do not hide rejected signals.
- Prominent paper/live badge. Confirm before enabling live orders.
- Stale/disconnected data warnings must be prominent.
- Responsive behavior: stacked panels on narrow screens; preserve PE/CE labels.
- Avoid visual clutter; tooltips explain PCR, OI change, IV, spread, and risk.
- Keyboard accessible and readable at common desktop resolutions.

## 10. Chart library and market data

Use **TradingView Lightweight Charts** for in-app interactive charts, subject to current license/attribution requirements:
- Project: https://github.com/tradingview/lightweight-charts
- Documentation: https://tradingview.github.io/lightweight-charts/

Lightweight Charts is an open-source charting library, not the full proprietary TradingView Charting Library. It does not itself provide market data, option-chain data, indicators, broker connectivity, or order execution.

Use a licensed/authorized broker or market-data provider for:
- Underlying prices
- Option chain and contract master
- Option OHLCV candles and quotes
- OI and Change in OI
- IV (or enough data to calculate it transparently)
- Historical option data for backtesting
- Orders and positions if broker integration is added

Do not scrape TradingView or assume all requested fields are available from every provider. Keep data-provider adapters replaceable and document gaps.

## 11. Architecture and implementation

Propose a maintainable stack before coding. Suggested baseline:
- Frontend: React + TypeScript
- Charts: TradingView Lightweight Charts
- Backend: Python strategy/data/backtest service
- Persistence: SQLite for local prototype, repository abstraction for future PostgreSQL
- Strategy engine independent of UI and broker SDK
- Provider adapters for market data and execution

Separate modules:
- Instrument/expiry resolver
- ATM CE/PE contract resolver
- Candle/quote normalization
- EMA/premium signal engine
- PCR/OI/IV analytics
- Risk and position manager
- Paper execution and broker execution adapter
- Backtest/replay engine
- UI/API layer

Store strategy version/config with every signal and trade. Store timestamps consistently (UTC internally; Asia/Kolkata in UI). Secrets belong in environment variables/secret storage, never source control.

## 12. Backtesting and validation

Backtest the **actual option contracts and premiums**, not merely index signals.

Requirements:
- Historical ATM selection as-of each timestamp, including expiry policy and strike changes.
- Historical option candles/quotes and OI/IV snapshots where available.
- No lookahead in ATM selection, option-chain metrics, or candle confirmation.
- Realistic spread, slippage, fees/taxes, partial fills, and order timing.
- Handle gaps, illiquid contracts, missing data, and expiry transitions conservatively.
- Compare:
  A. EMA 8/21 crossover only on option premium
  B. A + premium expansion
  C. B + spread/liquidity gate
  D. C + PCR/OI/IV context filters (only if data quality supports valid historical tests)
- Test CE and PE separately, and by index, expiry bucket, and time of day.
- Chronological train/validation/test split; out-of-sample and sensitivity analysis.
- Avoid optimizing solely for maximum historical profit.

Report:
- Net P&L after costs
- Profit factor
- Expectancy / average trade
- Maximum drawdown
- Win rate
- Trade count and longest losing streak
- Average win/loss and tail loss
- Cost/slippage contribution
- CE vs PE performance
- Performance by index, expiry policy, time of day, and market regime
- Blocked signals by reason
- Data coverage and limitations

Do not claim profitability unless reproducible results support the claim. Paper trade before live deployment.

## 13. Delivery phases

### Phase 1 — Paper prototype
- Index selector and expiry/ATM resolver
- Side-by-side PE/CE premium charts
- Direct option EMA 8/21 signals
- Premium expansion and spread/freshness gates
- PCR, CE/PE Change in OI, and IV panels
- Paper execution, risk controls, audit/event log
- Historical replay/backtest

### Phase 2 — Broker integration
- Broker order adapter and position reconciliation
- Order lifecycle, partial-fill, timeout, rejection handling
- Explicit live-mode guardrails and integration tests

### Phase 3 — Enhancements
- More indices/providers
- Advanced analytics and execution
- Alerts, configurable multi-position mode, and reporting

## 14. Deliverables

1. Working dashboard with vertically split PE/CE panels.
2. `strategy_engine` with unit tests.
3. Configurable ATM/expiry resolver implementing DTE 0/1 next-expiry rule.
4. Premium crossover/expansion filters.
5. PCR, CE/PE Change in OI, and IV analytics with source/freshness metadata.
6. Paper trading and risk controls.
7. Backtest/replay module with realistic cost assumptions.
8. README, architecture note, setup guide, provider requirements, and test checklist.
9. `.env.example` without secrets.

## 15. Acceptance criteria

- NIFTY works end-to-end in paper mode; BANKNIFTY/SENSEX are configurable.
- ATM CE and PE are resolved at the same strike and selected expiry.
- If nearest expiry is DTE 0 or DTE 1, next eligible expiry is selected by default.
- CE and PE long entries are triggered only by their own confirmed premium EMA 8/21 bullish crossover and enabled filters.
- No short option trades; no pyramiding by default.
- PCR basis/scope, CE/PE Change in OI, IV source, and timestamps are visible.
- Missing/stale critical data blocks entries according to policy and is clearly shown.
- Risk limits, exits, and daily controls are tested.
- Charts use Lightweight Charts with license/attribution compliance.
- Backtest uses historical options data and avoids lookahead.
- Every trade and blocked signal is auditable.
- Live trading remains off by default.

## 16. Codex kickoff prompt

Read this specification and propose a phased implementation plan. Identify provider-specific unknowns before coding: real-time and historical option candles, contract master/expiry calendar, option-chain OI and IV availability, quote depth, broker execution APIs, costs, and licensing. Do not invent endpoints or assume TradingView supplies data or execution. Implement Phase 1 in paper mode first, with tests. Keep strategy parameters configurable, document assumptions, and do not enable live orders by default.
