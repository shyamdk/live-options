# Delta Exchange India: Trading Mechanics and Costs for BTC Options and Perpetuals (for Movement-Capture / Long-Vol Strategies)

Research date: 2026-10-15. Several figures below come straight from Delta Exchange India's public REST API (`https://api.india.delta.exchange/v2/...`), queried 2026-10-15 ~03:00 UTC with BTC spot ~$81,170. The API is the most authoritative source because it is what the matching engine bills against. Treat the spread and liquidity numbers as **one snapshot** taken during the Asian morning, not as averages.

API endpoints used (all public, no auth):
- Products / contract specs: [Delta India API – /v2/products/BTCUSD](https://api.india.delta.exchange/v2/products/BTCUSD), [/v2/products/C-BTC-81000-161026](https://api.india.delta.exchange/v2/products/C-BTC-81000-161026)
- Option tickers: [/v2/tickers?contract_types=call_options,put_options&underlying_asset_symbols=BTC](https://api.india.delta.exchange/v2/tickers?contract_types=call_options,put_options&underlying_asset_symbols=BTC)
- Perp ticker / book: [/v2/tickers/BTCUSD](https://api.india.delta.exchange/v2/tickers/BTCUSD), [/v2/l2orderbook/BTCUSD](https://api.india.delta.exchange/v2/l2orderbook/BTCUSD)
- Funding history: [/v2/history/candles?symbol=FUNDING:BTCUSD&resolution=1h](https://api.india.delta.exchange/v2/history/candles?resolution=1h&symbol=FUNDING:BTCUSD)

---

## 1. BTC options contract mechanics (expiry, size, tick, strikes, settlement)

### Takeaway
BTC options on Delta India are European, cash-settled in USD (the account balance is shown in INR). Each contract is 0.001 BTC with a $0.10 premium tick, and premiums are quoted per 1 BTC. **Every expiry (daily, weekly, monthly, quarterly) settles at 12:00 UTC = 17:30 IST** against a 30-minute TWAP of Delta's BTC index. Near-term dailies have $200 strike spacing near the money. Wider spacing appears further out in time and further from the money.

### Cited Findings
- Contract value is 0.001 BTC per option contract and the tick size is 0.1 (USD per BTC of premium). Example: `C-BTC-81000-161026` has contract_value 0.001 and tick_size 0.1 — [Delta India API product spec](https://api.india.delta.exchange/v2/products/C-BTC-81000-161026)
- The minimum order size for BTC contracts (options and futures) is 0.001 BTC — [Delta India support: minimum order size](https://www.delta.exchange/support/solutions/articles/80001177912-what-is-the-minimum-order-size-for-btc-and-eth-contracts-)
- "All options contract settle at 5:30 PM IST." Settlement price is "computed using its strike price and the 30 minute TWAP (Time Weighted Average Price) of the index (i.e. spot) price of the underlying asset" — [Delta India Options Guide](https://guides.delta.exchange/delta-exchange-india-user-guide/derivatives-guide/options-guide)
- API settlement_time confirms 12:00:00Z, for example `2026-10-16T12:00:00Z` — [Delta India API](https://api.india.delta.exchange/v2/products/C-BTC-81000-161026)
- Listed maturities are D1, D2, W1, W2, W3, M1, M2, M3. D1 launches at T-2 and weeklies launch on Friday. Strike difference for BTC by maturity: D1 = 200, D2 = 250, W1–W3 = 1,000, M1 = 1,000, M2 = 2,000, M3 = 5,000. Strikes are launched over roughly a 0.2–0.8 delta range — [Delta India Options Guide](https://guides.delta.exchange/delta-exchange-india-user-guide/derivatives-guide/options-guide)
- Live chain on 2026-10-15 had expiries 15-Oct, 16-Oct, 17-Oct (three dailies), 23-Oct, 30-Oct (weekly/monthly), 27-Nov and 25-Dec. There were 541 BTC option instruments in total:
  - 15-Oct: strikes 78,800–86,400, spacing 200/400
  - 16-Oct (Friday): strikes 76,000–93,000, spacing 100/200/500/1000
  - 17-Oct: strikes 78,000–86,400, spacing 200/400
  - Weeklies: spacing 500/1000
  - Nov/Dec: spacing 1000

  Source: [Delta India API tickers](https://api.india.delta.exchange/v2/tickers?contract_types=call_options,put_options&underlying_asset_symbols=BTC)
- Contracts are "European style and settled in cash". ITM options receive intrinsic value and OTM options expire worthless. Weeklies expire Friday and monthlies expire on the last Friday, all at 12:00 UTC / 5:30 pm IST — [AlgoClear: Delta Exchange options expiry](https://www.algoclear.in/learn/delta-exchange-options-expiry) (third party, updated Sep 2026)
- Quoting and settling asset in the API is "US Dollar" (USD) with an INR_BANKING network, meaning INR is deposited and withdrawn but contracts are USD-denominated — [Delta India API product spec](https://api.india.delta.exchange/v2/products?contract_types=call_options&states=live). One third-party article describes settlement as "in USDT" ([AlgoClear](https://www.algoclear.in/learn/delta-exchange-options-expiry)), which conflicts with the API, where the settling asset is USD. Delta's portfolio-margin guide also refers to "USD settled" contracts ([Margin Explainer](https://guides.delta.exchange/delta-exchange-india-user-guide/trading-guide/margin-explainer)).
- The settlement index is `.DEXBTUSD` ("Bitcoin spot price index quoted in US Dollar"), a composite of `.DEXBTUSDT × .DEUSDTUSD` — [Delta India API product BTCUSD (spot_index)](https://api.india.delta.exchange/v2/products/BTCUSD)
- Delta India's 17:30 IST expiry differs from the global standard of 08:00 UTC (13:30 IST) used by Deribit and Binance, and from Pi42's 13:30 IST — [BestCryptoIndia: BTC expiry time in India](https://bestcryptoindia.com/news/btc-expiry-time-in-india-daily-weekly-crypto-options) (Sep/Oct 2026)
- Option price band in the API is `price_band: 2`. Product specs bound the IV used for marking between min_volatility 0.1 and max_volatility 3, and `vol_calculation_method: orderbook` — [Delta India API](https://api.india.delta.exchange/v2/products?contract_types=call_options&states=live)

### Inferences
- The 17:30 IST / 12:00 UTC expiry means a "daily" bought right after the previous settlement has about 24h to run. That cycle spans the European open and most of the US session up to 08:00 ET. It is offset from Deribit's 08:00 UTC cycle, so Deribit IVs/DVOL for the same calendar day are not directly comparable.
- The 30-minute TWAP settlement smooths pin risk at expiry. It also means a spike in the final minutes is only partly captured.
- Same-day (0DTE) and next-day dailies are the natural instruments for an intraday or overnight movement capture. Three dailies are listed at any time.

### Gaps
- No official page states whether an explicit settlement or exercise fee applies to options held to expiry (see Section 2). The fees page says "Settlement fee applies to all open contracts at the time of settlement (Taker Fees will be charged)", but it is unclear whether this covers options, and whether it applies to OTM options that expire worthless.
- The strike spacing in the Options Guide (D2 = 250) does not match the live chain, where the 16-Oct strikes include 100/500 steps. The guide may be stale, or the Friday daily may double as a weekly.

---

## 2. Fees: options, perpetuals, GST, settlement, funding

### Takeaway
- **Options:** 0.01% of underlying notional for both maker and taker, capped at 3.5% of premium, plus 18% GST. There is no maker discount on options.
- **BTC perpetual (BTCUSD):** 0.02% maker / 0.05% taker on notional, plus 18% GST.
- **Funding:** accrues per minute and is exchanged every 8h (05:30 / 13:30 / 21:30 IST). Over the last 60 days it sat mostly at the +0.01%/8h baseline (about 10.95% annualised).
- Third-party sites quote conflicting options fees (0.015%, 0.03%, 5% cap, 10% cap). The live API is used as ground truth here.

### Cited Findings
- **Options fee (API, live):** `maker_commission_rate: 0.0001`, `taker_commission_rate: 0.0001` (0.01%), and `premium_commission_rate: 0.035` (3.5% cap) on BTC options — [Delta India API product spec](https://api.india.delta.exchange/v2/products/C-BTC-81000-161026)
- **Options fee (official support):** "Taker/Maker Fee: 0.010% of the Notional Size", capped at "3.5% of the premium", whichever is lower. Notional = Spot Price × Qty. Worked example: a $27,000-notional deep OTM option with $45 premium pays $1.575 (3.5% of premium) instead of $2.70 (0.01% of notional) — [Delta India support: Fees on Options and Futures Trading](https://www.delta.exchange/support/solutions/articles/80001177864-fees-on-options-and-futures-trading)
- **Futures/perp fee (official support):** Taker 0.05% and Maker 0.02% of notional — [Delta India support: Fees](https://www.delta.exchange/support/solutions/articles/80001177864-fees-on-options-and-futures-trading). The API confirms BTCUSD `maker_commission_rate 0.0002`, `taker_commission_rate 0.0005` — [Delta India API BTCUSD](https://api.india.delta.exchange/v2/products/BTCUSD)
- **GST:** "An additional 18% GST is applicable on the calculated trading fees for both Options and Futures trades" — [Delta India support: Fees](https://www.delta.exchange/support/solutions/articles/80001177864-fees-on-options-and-futures-trading); "18% GST is applicable on trading fees" — [Delta India fees page](https://www.delta.exchange/fees)
- **Fee-cap conflict:**
  - The official fees page text, as extracted, reads "Option Fee is capped at 3.5% 10% of Option Premium". This could be a strikethrough or old/new rendering, so the current cap is ambiguous on that page — [Delta India fees page](https://www.delta.exchange/fees)
  - Third-party sites variously report 0.015% capped at 10%, 0.010%/0.03% capped at 3.5%, and 0.015% capped at 5% — [search summary incl. Outlook Business](https://www.outlookbusiness.com/spotlight/news-wire/how-delta-exchange-india-makes-crypto-trading-simple-and-affordable), [Plisio](https://plisio.net/profiles/delta-exchange-india)
  - One press piece says options maker and taker are both 0.03% — [Outlook Business (sponsored)](https://www.outlookbusiness.com/spotlight/news-wire/how-delta-exchange-india-makes-crypto-trading-simple-and-affordable)
  - These are likely outdated or promotional. The live API (0.01% / 3.5%) should govern.
- **Settlement fee:** The fees page says "Settlement fee applies to all open contracts at the time of settlement (Taker Fees will be charged)" — [Delta India fees page](https://www.delta.exchange/fees)
- **Promos:** A "Scalper Offer" gives "up to 50% off on Trading Fees across Futures and RWA Tokens" with "Zero closing fees". Options are not listed. Deposits and withdrawals are advertised as zero-fee — [Delta India fees page](https://www.delta.exchange/fees). The API shows INR_BANKING withdrawal fee 0 — [Delta India API](https://api.india.delta.exchange/v2/products?contract_types=call_options&states=live)
- **Funding mechanics:**
  - Funding Rate = Avg Premium + clamp(Interest Rate − Avg Premium, 0.05%, −0.05%). Premium is sampled every minute and an 8h TWAP is used. The funding rate is an 8-hourly rate, although some contracts use 4/2/1h — [Delta India Perpetual Contracts Guide](https://guides.delta.exchange/delta-exchange-india-user-guide/derivatives-guide/docs)
  - BTCUSD funding is exchanged at 5:30 AM, 1:30 PM and 9:30 PM IST. Accrual happens every minute, and ledger entries are made every 2h or when the position is closed — [Delta India support: Update on Funding Exchange Schedule](https://www.delta.exchange/support/solutions/articles/80001183756-update-on-funding-exchange-schedule-for-perpetual-contracts)
  - The API shows BTCUSD `rate_exchange_interval: 28800` (8h), `funding_clamp_value: 0.05`, `funding_method: mark_price` and `annualized_funding: 10.95` — [Delta India API BTCUSD](https://api.india.delta.exchange/v2/products/BTCUSD)
- **Typical BTC funding (API history, last 60 days, hourly samples, n = 1,436):** median 0.01 and mean 0.0073, range −0.0034 to +0.01. About 9.7% of samples were negative. The live ticker showed funding_rate 0.000115 — [Delta India API FUNDING:BTCUSD candles](https://api.india.delta.exchange/v2/history/candles?resolution=1h&symbol=FUNDING:BTCUSD), [ticker](https://api.india.delta.exchange/v2/tickers/BTCUSD). The candle values are interpreted as % per 8h: the 0.01 baseline × 3 × 365 = 10.95%, which matches `annualized_funding`. This unit interpretation is an inference.

### Inferences (worked cost examples at BTC ≈ $81,200, fees incl. 18% GST)
- **Option fee per leg per side:**
  - Raw fee: min(0.01% × $81,200 = $8.12, 3.5% × premium), per 1 BTC of notional (= 1,000 contracts). With GST, the notional-based fee is ≈ **$9.58 per BTC**, or about $0.0096 per 0.001-BTC contract.
  - The cap binds only when premium < ~$232 per BTC. For BTC that means OTM dailies and late-day 0DTE.
  - Example: a 0DTE 85,000 call at ~$1.6–2 premium pays 3.5% × premium ≈ $0.07 per BTC. Fees on cheap wings are negligible, but spreads there are wide in % terms (see Section 4).
- **ATM daily straddle round-trip (buy + sell back before expiry):**
  - Fees: 4 fills × $9.58 ≈ **$38 per BTC**. The 16-Oct ATM straddle cost ~$1,650 (81,200 C + P mid). Fees alone are ≈ 2.3% of the premium.
  - Spread: crossing the ~$20 ATM spread on both legs in and out costs ≈ $40. Total friction is ≈ **$80 per BTC ≈ 5% of straddle premium**.
  - Holding to expiry removes the exit spread. The exit fee may also drop away if no settlement fee applies to options, but that is unconfirmed (see Gaps).
- **Perp round-trip taker:** 2 × 0.05% × 1.18 = **0.118% of notional ≈ $96 per BTC**. At 40% IV, the 1-day 1σ move is ≈ 2.1% (~$1,700), so taker round-trip ≈ 5.6% of a 1σ daily move. Maker-maker round-trip is 0.047% (≈ $38).
- **Funding:** at the 0.01%/8h baseline, holding a long perp for 24h costs ≈ 0.03% (~$24 per BTC). This is small next to taker fees but non-zero, and it is paid by longs at the baseline.

### Gaps
- No official, dated statement was found confirming the options fee cap (3.5% vs 10%). The API figure is the best evidence.
- No source says whether expiring ITM options are charged a taker fee on intrinsic or notional at settlement, or whether expiring OTM options are charged at all.
- No volume-tier (VIP) fee schedule for Delta India was found.

---

## 3. Margin and leverage; order types and API

### Takeaway
- **Long options** require only the premium. **Short options** are risk-margined.
- **Margin modes:** isolated, cross, and portfolio. Portfolio margin uses 29 stress scenarios, plus margin floors that also apply to long options.
- **BTC perpetual:** up to 200x by default, with initial margin 0.5% that scales up with position size.
- **Order types:** limit, market, stop-market, stop-limit, trailing stop and bracket orders, all supported in the UI and API. Bracket triggers use mark price.

### Cited Findings
- **Option margin (API, BTC option):** `initial_margin: 0.5`, `maintenance_margin: 0.25` (percent fields, presumably % of notional for short positions) — [Delta India API C-BTC-81000-161026](https://api.india.delta.exchange/v2/products/C-BTC-81000-161026)
- **Portfolio margin:**
  - Available on USD-settled futures, perpetuals and options on BTC and ETH — [Delta India Margin Explainer](https://guides.delta.exchange/delta-exchange-india-user-guide/trading-guide/margin-explainer)
  - Uses "29 scenarios (including two extreme risk scenarios)" of price and IV shocks — [Delta India Portfolio Margin](https://guides.delta.exchange/delta-exchange-india-user-guide/trading-guide/margin-explainer/portfolio-margin)
  - Margin floor for short options: OM% = Base% + Slope × (Short Options Notional − Base% Notional), with Base% = 0.5% for BTC, capped at 2% (BTC). A similar floor applies to long options — [Delta India Portfolio Margin](https://guides.delta.exchange/delta-exchange-india-user-guide/trading-guide/margin-explainer/portfolio-margin)
  - Liquidation penalty for options: min(50% × premium, 0.25% × notional) — [Delta India Portfolio Margin](https://guides.delta.exchange/delta-exchange-india-user-guide/trading-guide/margin-explainer/portfolio-margin)
  - Unrealised cash flow from long options counts toward available collateral. Buying the long legs first is cheaper on margin when combining long and short options — [Delta India Portfolio Margin (via search summary)](https://guides.delta.exchange/delta-exchange-india-user-guide/trading-guide/margin-explainer/portfolio-margin)
- **BTC perpetual (BTCUSD):**
  - API fields: `default_leverage: 200`, `initial_margin: 0.5`, `maintenance_margin: 0.25`, `initial_margin_scaling_factor: 0.0000025`, `max_leverage_notional: 100000`, `position_notional_limit: 5000000`, `tick_size: 0.5`, `contract_value: 0.001 BTC`, `price_band: 5`
  - The UI leverage slider offers 1/10/25/50/100/150/200
  - `show_bracket_orders: False` appears in this product's ui_config
  - Source: [Delta India API BTCUSD](https://api.india.delta.exchange/v2/products/BTCUSD)
- **Order types (UI guide):**
  - Limit, Market, Stop (stop market, stop limit, trailing stop) and Bracket orders
  - Validity IOC/GTC, plus Maker-only (post-only) and Reduce-only flags
  - "Bracket orders use only Mark Price as the triggering index"
  - Source: [Delta India Order Types guide](https://guides.delta.exchange/delta-exchange-india-user-guide/trading-guide/order-types)
- **Trailing stop:** a stop-market order with a fixed Trail Amount that follows favourable moves — [Delta India support: Trailing-Stop Orders](https://www.delta.exchange/support/solutions/articles/80001177899-trailing-stop-orders)
- **Bracket orders:** OCO take-profit and stop-loss around a position, with an optional trailing stop — [Delta India support: Bracket Orders](https://www.delta.exchange/support/solutions/articles/80001177901-what-are-bracket-orders-and-how-to-use-them-)
- **API:**
  - Production base `https://api.india.delta.exchange` and testnet `https://cdn-ind.testnet.deltaex.org`
  - Order types limit_order / market_order, stop orders (stop_market / stop_limit, stop_loss / take_profit), bracket orders
  - time_in_force gtc / ioc (ioc not allowed in batch create); post_only, reduce_only
  - Rate limit "20000 for a fixed 5 minute window" and 500 operations/sec per contract
  - WebSocket for tickers, L2 book, trades and private events
  - Source: [Delta Exchange API docs](https://docs.delta.exchange/)

### Inferences
- A long straddle or strangle in isolated mode ties up only the premium, so capital efficiency is high and there is no liquidation risk on the option legs. Under portfolio margin, the long-options floor (≥0.5% of notional) could reserve more than premium for cheap OTM wings. This is worth checking before using portfolio margin for wing-buying.
- `show_bracket_orders: False` on BTCUSD suggests bracket orders may be hidden in the UI for the perp, although the API docs list them. This should be verified on testnet.
- Stop and trailing orders on options are possible in principle (generic order types). Mark-price triggers on illiquid options can fire on IV-model marks rather than trades.

### Gaps
- No precise isolated-mode short-option margin formula was found in the guides. The API `initial_margin 0.5` is the only number.
- No minimum balance or eligibility rule for portfolio margin was found.
- The guide does not say whether stop or trailing orders are permitted on option contracts specifically.

---

## 4. Bid-ask spreads and liquidity (snapshot 2026-10-15 ~03:00 UTC, BTC ≈ $81,175)

### Takeaway
ATM BTC dailies are tradable with absolute spreads of ~$11–26 per BTC, which is ~2.5–5% of premium on a 0DTE and ~2.4–2.8% on a 1DTE. Displayed size is large: thousands of contracts, or several BTC. The cheap OTM wings have tiny absolute spreads but are 10–25% wide relative to premium. The BTC perp is very tight: a 0.5 tick spread, ~0.0006%. Delta is the dominant Indian venue, with ~$1.1B 24h perp turnover.

### Cited Findings (all from [Delta India API tickers](https://api.india.delta.exchange/v2/tickers?contract_types=call_options,put_options&underlying_asset_symbols=BTC); prices are USD per 1 BTC; sizes are in 0.001-BTC contracts)

**0DTE (15-Oct, ~9h to expiry):**

| Strike / leg | Bid / ask | Spread | Mid | IV | Notes |
|---|---|---|---|---|---|
| 81,200 put | 414 / 431 | $17 | 4.0% | ~40% | |
| 81,200 call | 406 / 423 | $17 | 4.1% | ~40% | |
| 81,000 put | 322 / 338 | $16 | 4.8% | | OI 68,928 contracts |
| 80,800 call | 656 / 682 | | 3.9% | | |
| 83,000 call (+2.2% OTM) | 30 / 34 | | ~13% | | |
| 84,000 call (+3.5%) | 5.2 / 7 | | ~30% | | OI 364,494 contracts |
| 85,000 call (+4.7%) | 1.6 / 2 | | | | |

Top-of-book sizes on the 0DTE ATM strikes were ~6,000–11,000 contracts (6–11 BTC).

**1DTE (16-Oct):**

| Strike / leg | Bid / ask | Spread | Notes |
|---|---|---|---|
| 81,200 put | 816 / 836 | 2.4% | |
| 81,200 call | 813 / 834 | 2.6% | |
| 83,000 call | 199 / 209 | ~5% | |
| 85,000 call | 36 / 40 | ~10% | |
| 78,000 put (−3.9%) | 155 / 162 | ~4.4% | |

**2DTE (17-Oct):** ATM spreads were $22–25 (2.2–2.8%), with mark IV ~36–38%.

**Weekly / monthly:**

| Expiry | ATM spread | % of premium | Mark IV |
|---|---|---|---|
| 23-Oct | $26–32 | 1.5–2.1% | ~33–35% |
| 30-Oct | $27–31 | 1.1–1.5% | |
| 27-Nov | ~$95 | 2.0–2.9% | |
| 25-Dec | ~$125 | 2.0–2.9% | |

**Volume vs open interest:** 24h volume on dailies is modest relative to OI. For example, the 0DTE 81,000 put traded ~740 contracts on 68,928 OI, and the far OTM wings show the largest OI and volume (e.g. the 85,000 call traded 1,684 contracts on 252,568 OI). Quotes in the far months look market-maker-driven: uniform bid sizes (~5,600–6,500 contracts) and constant ~$95–125 widths across strikes.

**Perpetual (BTCUSD):**
- Ticker best bid / ask 81,173.5 / 81,174, which is one $0.5 tick
- 24h turnover_usd ≈ $1.14B
- OI 757 BTC ≈ $61.5M
- L2 book: ~4,400 contracts (4.4 BTC) within 5 ticks on the bid and ~20,000 contracts (20 BTC) within 5 ticks on the ask
- Sources: [ticker](https://api.india.delta.exchange/v2/tickers/BTCUSD), [L2 book](https://api.india.delta.exchange/v2/l2orderbook/BTCUSD)

**Platform scale:** Delta India was reported processing ~$2.5B daily volume by May 2025, peaking around $4B — [search summary of Outlook Business / Wire press](https://www.outlookbusiness.com/spotlight/news-wire/how-delta-exchange-india-makes-crypto-trading-simple-and-affordable). This is sponsored or press-release material, so treat it as indicative only.

### Inferences
- For an ATM long straddle on a 1DTE daily:
  - Entry spread cost: ~$10 per leg half-spread (~1.2% of the straddle).
  - Entry fee: ~$9.6 per leg (~1.2%).
  - A round trip closing before expiry costs ≈ 5% of premium.
  - The straddle needs BTC to move more than ~1.05× the implied breakeven just to cover friction.
  - The edge must come from realised volatility exceeding IV by a margin larger than this friction.
- The best-quoted, highest-OI area is OTM 0DTE/1DTE wings, which is typical of retail lottery buying. Market makers likely price these rich, so cheap wings are not cheap on a vol basis.
- Daily-option IV (~40%) was above weekly/monthly IV (~32–35%) in this snapshot. Short-dated long-vol pays a term-structure premium.
- Hedging or delta-trading with the perp is cheap on spread but costly on taker fees (0.059% incl. GST). Maker (post-only) execution on the perp cuts this to 0.024% per side.

### Gaps
- No published historical spread or liquidity statistics were found for Delta India options. This is a single snapshot taken during Asian hours, and spreads around US data releases or near the 17:30 IST expiry may differ materially.
- No independent community measurements of slippage on Delta India options were found.

---

## 5. Official strategy content and India-specific rules (KYC, INR, tax)

### Takeaway
- **Strategy content:** Delta India publishes educational content on strangles and lists combo contracts for straddles, strangles and spreads.
- **Delta's tax stance:** F&O profits are not VDA income and are taxed at slab rates, with no 30% flat tax and no 1% TDS. Spot trades on Delta do attract the 30% tax and 1% TDS.
- **Fees on top:** 18% GST is added to all trading fees.

### Cited Findings
- **Delta blog:** "Crypto Option Strangle: How Does the Options Strangle Strategy Work?" — [Delta Exchange blog](https://www.delta.exchange/blog/crypto-option-strangle-how-does-options-strangle-strategy-work). A take-profit / stop-loss guide is also published — [Delta blog](https://www.delta.exchange/blog/crypto-traders-guide-know-when-to-take-profit-know-when-to-cut-losses)
- **Combo contracts:** Delta "lists innovative derivative contracts... including option spread contracts (call spread and put spread), Straddle and strangle contracts" — [search summary citing Delta materials](https://www.delta.exchange/blog/crypto-option-strangle-how-does-options-strangle-strategy-work). Whether these combo contracts are currently live on the India platform was not verified; none appeared in the call/put ticker query.
- **Delta's tax article:**
  - "Trading in Futures and Options contracts on Bitcoin and other Cryptos does not qualify as trading Virtual Digital Assets (VDA); thus 30% VDA tax is not applicable... profits... will be taxed as per your income tax slab" — [Delta India support: Is there 30% VDA tax applicable on trading profits](https://www.delta.exchange/support/solutions/articles/80001132761-is-there-30-vda-tax-applicable-on-trading-profits-)
  - Delta adds that, because you "never really interact with crypto, and your balances and unrealized profits remain in INR... the 1% TDS and 30% flat tax on profits is not applicable", but that the 1% TDS and 30% tax apply if you buy spot on Delta India — [search summary of Delta India guide](https://guides.delta.exchange/delta-exchange-india-user-guide)
- **Tax commentary:**
  - Third-party Indian tax commentary generally agrees with Delta's view: INR-settled crypto F&O is not a "transfer of VDA" under s.115BBH and is taxed as (often speculative or non-speculative) business income at slab rates of 5–30%, with business-expense deductions allowed — [Mudrex Learn](https://mudrex.com/learn/crypto-tax-on-futures-trading-india/), [CoinSwitch](https://coinswitch.co/switch/crypto-futures-derivatives/crypto-futures-options-tax/), [CA in Delhi blog](https://www.caindelhiindia.com/blog/crypto-futures-taxation/)
  - This view is contested and not settled by CBDT guidance. Some advisers argue the 30% VDA treatment should apply, as reflected in titles like "Crypto Futures Taxation: Business Income or 30% VDA Tax?" ([CA in Delhi](https://www.caindelhiindia.com/blog/crypto-futures-taxation/)). Flag this as a regulatory risk.
- **Spot crypto (VDA) rules:** 30% flat tax under s.115BBH and 1% TDS on VDA transfers above ₹10,000, with no loss set-off — [Mudrex Learn](https://mudrex.com/learn/crypto-tax-on-futures-trading-india/)
- **Regulator / KYC:** Delta Exchange India is operated by Excelium Technologies Private Limited and is FIU-registered — [Delta India fees page](https://www.delta.exchange/fees). The API shows INR bank-transfer deposit and withdrawal with zero fee — [Delta India API](https://api.india.delta.exchange/v2/products?contract_types=call_options&states=live)
- **Expiry timing difference:** Delta's 5:30 pm IST expiry is distinct from Pi42's and Deribit/Binance's 1:30 pm IST — [BestCryptoIndia](https://bestcryptoindia.com/news/btc-expiry-time-in-india-daily-weekly-crypto-options)

### Inferences
- If Delta's tax view holds, net returns are taxed at the trader's slab (up to ~30% + surcharge/cess for high earners). Losses may then be offset within business income, subject to speculative vs non-speculative classification. This is much better for a high-turnover, small-edge strategy than the 30% VDA regime, where losses cannot be set off.
- GST at 18% on fees is unrecoverable for individuals and is already included in the cost math in Section 2.

### Gaps
- No primary CBDT or Income Tax Department ruling on crypto-derivative taxation was located. The tax position rests on Delta's and advisers' interpretations.
- Detailed KYC requirements (PAN/Aadhaar, video KYC) and any per-user position or deposit limits were not checked in this pass.
- Whether straddle or strangle combo contracts are currently listed on Delta India, and their fee treatment, was not confirmed.
