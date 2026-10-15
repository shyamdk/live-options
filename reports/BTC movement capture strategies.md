# Keep selling BTC calm, and buy movement only around catalysts

Don't make a systematic BTC long straddle or strangle your core strategy. On average, BTC options have been priced above the volatility that followed, so the buyer starts behind every day. The academic estimate is an annualized variance risk premium of about **0.14 (roughly 85% implied vs 76% realized vol)**. Practitioner data shows 30-day implied above subsequent realized vol **about 70% of the time** ([Almeida et al.](https://arxiv.org/abs/2410.15195); [Amberdata/Deribit](https://insights.deribit.com/industry/bitcoin-options-finding-edge-in-four-years-of-volatility-regimes/)). The premium persisted in 2026 even at record-low volatility: 7-day implied vol was about 23% against 19% realized in August 2026 ([Block Scholes](https://blockscholesresearch.substack.com/p/bitcoins-short-dated-implied-volatility)). Delta Exchange India adds about **5% of premium in round-trip friction** on an ATM daily straddle. Movement capture is still worth adopting in three narrow forms, ranked by evidence and fit with your two short-strangle books:

1. **Price-breakout trend sleeve on the BTC perpetual.** Closing-price Donchian breakouts with a ratcheting midline stop have the best-documented "catch big moves" evidence in BTC, with a Sharpe of about 1.3 to 1.6 from 2015 to 2025 ([Concretum](https://concretumgroup.com/catching-crypto-trends-a-tactical-approach-for-bitcoin-and-altcoins/)).
2. **Event straddle around US CPI and FOMC.** These are the one place where realized moves are scheduled and concentrated.
3. **Gated evening long straddle.** It buys only when the option is cheap against recent realized volatility, and only through the 18:00–02:30 IST window when BTC actually moves.

Long volatility in BTC has historically been a losing trade on average. Its main value to you is as a hedge and as a source of "don't sell today" filters, not as a stand-alone profit engine.

## BTC options overpay their sellers most of the time

The evidence on implied versus realized volatility is consistent across academic and practitioner sources. Almeida, Grith, Miftachov and Wang used 7.8 million Deribit trades from 2017 to 2022. They found one-month risk-neutral variance averaged **0.72 against 0.58 realized**, a variance risk premium about seven times the S&P 500's ([arXiv 2410.15195](https://arxiv.org/abs/2410.15195)). Two details from that paper matter directly to a movement buyer:

- **The premium is larger in the calm regime:** 0.17, roughly 68% implied vs 54% realized vol, against 0.12 in the high-vol regime. So "IV looks cheap" periods have, on average, still been bad for buyers.
- **Unlike equities, the BTC premium is driven by upside states.** The market overpays most for rallies, not crashes.

Amberdata's 2019–2022 study found the term structure in contango **77.5% of hours**, with a mean premium of about **+15 vol points**. Backwardation shocks lasted only about 85 hours on average. Its summary verdict was that long vol "performs poorly systematically" ([Deribit Insights](https://insights.deribit.com/industry/bitcoin-options-finding-edge-in-four-years-of-volatility-regimes/)).

The cleanest public short-dated evidence is Cryptarbitrage's Deribit weekend backtest. It sold a 0.35-delta strangle every Friday at 21:30 IST, expiring Sunday at 13:30 IST, and charged 5% slippage. From 2020 to April 2025 it made **247 trades with about an 82% win rate and a 29.7% APR** ([Deribit Insights](https://insights.deribit.com/education/option-backtest-selling-weekend-vol-revisited/)). The same study holds a warning for anyone hoping the reverse trade works:

- Selling **Sunday-entry** strangles into Monday's TradFi reopen lost heavily, at **−17.7% APR**.
- *Buying* those same Sunday strangles earned only **about 2.1% APR**.

The author's point is that a losing short side does not create a profitable long side, because friction is paid twice.

Delta Exchange's own featured algorithm sells, rather than buys, the BTC daily straddle. It shows a **66.5% win rate over 723 trades from 2022 to 2023** ([Delta blog](https://www.delta.exchange/blog/the-algo-trading-strategy-which-made-2860-returns-in-the-past-2-years)). The mirror-image buyer wins only about one day in three and must collect outsized moves on those days.

Two caveats keep the case for buyers open:

- **Losses for sellers cluster in trending rallies.** In those rallies each new short is opened against a market already moving away. Anchorage found that unfiltered 20-delta call overwriting roughly broke even over October 2021 to April 2026 (profit factor 1.00) despite a 4.38:1 win/loss ratio. It also found 7–14 day tenors had the **widest downside tails** ([Anchorage Digital](https://cdn.prod.website-files.com/64b0dcb6fecf02d30d8dd905/6a15dc7a499b7b4150c162ef_synthetic-yield-on-bitcoin-whitepaper.pdf)).
- **Absolute volatility is now historically cheap.** DVOL fell to a record low near 34 in September 2025. Institutional call overwriting pushed 30-day IV from about 70% to 45% during 2025 ([CoinDesk](https://www.coindesk.com/markets/2025/12/31/bitcoin-market-calmed-in-2025-thanks-to-yield-hungry-institutions)).

Cheap in absolute terms is not cheap relative to what is realized, though. One 2026 reading had 30-day realized vol at **21.8% while 30-day IV sat near 36%** ([ByteFederal](https://www.bytefederal.com/news/why-bitcoin-options-stay-expensive-as-volatility-hits-2026-lows/41092), secondary source). Your existing short-strangle books are on the side the evidence favours.

## BTC's movement arrives in the IST evening and around US data

The movement BTC does deliver is highly predictable in clock time, and that is the lever a buyer can actually pull. Hansen, Kim and Kimbrough found volatility peaks around **16:00 UTC (21:30 IST)** and in the **00:00 UTC hour (05:30 IST)**, and bottoms near **05:00 UTC (10:30 IST)**. They also found Monday's first UTC hour unusually volatile, and Saturday the quietest day ([arXiv 2109.12142](https://arxiv.org/abs/2109.12142)). Since the spot ETFs launched, the activity has shifted further toward US hours:

- More than **55% of BTC-USD volume traded in US hours in 2025**, up from 39% in 2020.
- The 3–4 pm New York benchmark-fix hour rose to **more than 6.7% of weekday volume** ([Kaiko](https://www.kaiko.com/resources/btc-etfs-impact-on-spot-market-structure)).
- The weekend share of volume fell from 28% in 2019 to **16% in 2024** ([The Block](https://www.theblock.co/post/302705/bitcoin-sees-all-time-low-weekend-trading-levels-following-etf-approvals-kaiko)).

| Window (IST, US summer time / US winter time) | What happens |
|---|---|
| 09:30–17:30 | BTC's quietest stretch, with the trough near 10:30. This is when sellers collect theta. |
| 17:30 | Delta India settlement for **all** BTC option expiries: a 30-minute TWAP of the `.DEXBTUSD` index ([Delta guide](https://guides.delta.exchange/delta-exchange-india-user-guide/derivatives-guide/options-guide)). |
| 18:00 / 19:00 | US CPI, PCE and payrolls releases. |
| 19:00 / 20:00 | US equity open. Peak volume is roughly 19:30–21:30. |
| 21:30–22:30 | Hansen et al.'s volatility peak, which coincides with a funding time. |
| 23:30 / 00:30 | FOMC statement. |
| 00:30–02:30 | US close and ETF benchmark fix. |
| 02:30–04:30 | Historically BTC's strongest drift hours, at 21:00–23:00 UTC ([Quantpedia](https://quantpedia.com/are-there-seasonal-intraday-or-overnight-anomalies-in-bitcoin/)). |
| ~04:30 Mon | Asia open, where trend models make their best returns ([Concretum](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/)). |

Delta's 17:30 IST settlement creates a structural feature no public study covers, because Deribit and Binance expire at 13:30 IST:

- A Delta daily bought just after the 17:30 settlement spends its **first nine hours in BTC's busiest window**. It then spends its last eleven hours decaying through the quietest one.
- A buyer who exits around 02:30 IST keeps the high-variance part of the day and sells the quiet morning back to the market.
- If Delta's market makers spread implied variance evenly across the clock, that exit gives the buyer a structural tilt. If they price the clock correctly, it does not. This is directly measurable from your local 1-minute spot and option-mark data, and it is the first thing to test.

The 17:30 settlement also falls **30 minutes before US CPI** under US summer time. The same-day daily therefore cannot capture CPI, and the event trade has to use the next day's expiry.

Scheduled macro events are the other concentration of movement:

- **CPI.** Block Scholes estimates that over 2020–2026 a 1-percentage-point CPI surprise moved BTC about **−5.5% in the first hour**. Over the 12 releases to June 2026 the sensitivity fell to −3.2% per point, but with an R² near 80%. On 14 July 2026, CPI came in below expectations and BTC rose 2.9% on the day ([Block Scholes](https://www.blockscholes.com/institutional-research/is-bitcoin-showing-greater-sensitivity-to-us-cpi-releases-again)).
- **CPI vs FOMC timing.** A 2020–2025 daily event study found CPI volatility builds on days −2 and −1, peaks on day 0 and fades by day +1. FOMC volatility spikes about 1.0 percentage point on day 0 and **stays elevated on days +1 and +2** ([Nazaruk, KSE thesis](https://kse.ua/wp-content/uploads/2026/05/illia-nazaruk_268722_assignsubmission_file_nazaruk_final_thesis.pdf), not peer-reviewed).
- **The market prices this in.** One CPI window was priced at a **1.98% move**, with event IV of 37.9% against 34.8% afterward, an event premium of about 3 vol points ([KuCoin flash](https://www.kucoin.com/news/flash/bitcoin-options-price-1-98-move-ahead-of-us-cpi-report), aggregator).
- **Events do not always deliver.** Deribit's own December 2025 reports, which had called long straddles "appealing" ahead of CPI, later noted that FOMC and a subdued CPI "failed to ignite substantial market movements" ([Deribit Week 51 2025](https://insights.deribit.com/industry/crypto-derivatives-analytics-report-week-51-2025/)).
- **The only published long-vol event test is too small to rely on.** It bought ATM calls seven days before FOMC or CPI and exited the day before. It was positive, but on fewer than 15 trades per event type ([Amberdata/Deribit](https://insights.deribit.com/industry/bitcoin-options-finding-edge-in-four-years-of-volatility-regimes/)).

## Delta India friction costs about 5% of a daily straddle per round trip

On an ATM daily straddle, friction takes about one-twentieth of the premium. Fees for the actual trading pattern are confirmed from Delta India's live API. Spreads come from a single snapshot taken in the Asian morning, so treat them as indicative.

| Cost item | Value (BTC ≈ $81,200) | Source |
|---|---|---|
| Option fee | 0.01% of underlying notional, capped at 3.5% of premium, plus 18% GST. That is about **$9.58 per BTC per leg per side**. | [Delta API](https://api.india.delta.exchange/v2/products/C-BTC-81000-161026), [support](https://www.delta.exchange/support/solutions/articles/80001177864-fees-on-options-and-futures-trading) |
| ATM daily spread | About $11–26 per BTC: 2.5–5% of premium for same-day (0DTE), 2.4–2.8% for next-day (1DTE). | [Delta API tickers](https://api.india.delta.exchange/v2/tickers?contract_types=call_options,put_options&underlying_asset_symbols=BTC) |
| OTM wings | Small in dollars but **10–25% of premium**, with the largest open interest (retail lottery demand). | same |
| ATM 1DTE straddle round trip | About **$80 on a ~$1,650 straddle, roughly 5%** (fees about 2.3% plus spread). | derived from the above |
| Perpetual taker / maker | 0.05% / 0.02% plus GST: a **0.118%** round trip taker, 0.047% maker. | [Delta API BTCUSD](https://api.india.delta.exchange/v2/products/BTCUSD) |
| Funding | 8-hourly at 05:30, 13:30 and 21:30 IST. Mostly at the +0.01% per 8h baseline (about 10.95% annualized, paid by longs). About 10% of hours were negative in the last 60 days. | [Delta funding history](https://api.india.delta.exchange/v2/history/candles?resolution=1h&symbol=FUNDING:BTCUSD) |
| Settlement | "Taker fees" charged on open contracts at settlement. Whether this applies to options expiring out of the money is unconfirmed. | [Delta fees page](https://www.delta.exchange/fees) |

These numbers have four consequences:

- **The straddle needs about 5% more volatility than it pays for.** A held-to-expiry ATM straddle pays the average absolute move, about 0.8σ√t under a normal distribution. So realized vol must exceed implied by roughly 5% just to cover friction. *(This is our inference.)* BTC's fat tails also put more of the variance into rare days, which lowers the typical absolute move for a given volatility. That hurts a buyer holding to expiry more than it hurts a buyer who hedges.
- **Gamma scalping does not change the sign of the edge.** It changes the path of P&L, not its expected sign, which is still roughly ½Γ(ΔS² − σ²S²Δt). Short-dated ATM option spreads of **200–300 bp dwarf perpetual hedge costs of 1–5 bp** ([Panoptic × Block Scholes](https://panoptic.xyz/research/panoptic-block-scholes-research-gamma-scalping)). The one published BTC gamma-scalp simulation netted about +12% against +105% for holding the coin, and volatile days triggered up to 66 re-hedges.
- **The perpetual is the cheap instrument for capturing movement.** A taker round trip is about 0.118%, roughly 5.6% of a one-standard-deviation daily move at 40% IV. Posting post-only maker orders cuts that by 60%.
- **Tax treatment depends on an unsettled ruling.** Delta's position is that INR-settled crypto F&O is not a "virtual digital asset" (VDA) and is taxed at slab rates without the 30% flat tax or 1% TDS ([Delta support](https://www.delta.exchange/support/solutions/articles/80001132761-is-there-30-vda-tax-applicable-on-trading-profits-)). The CBDT has not settled this, so treat it as a regulatory risk for any high-turnover strategy.

## Trend breakouts on the perpetual beat buying options for capturing moves

For capturing moves in either direction, a price-based breakout on the perpetual has better evidence than any long-option rule. Zarattini, Pagani and Barbon (Concretum, 2015 to March 2025) tested a simple rule:

- **Entry:** go long on a daily close at the n-day high.
- **Exit:** a trailing stop at the Donchian midline that only moves in the trade's favor.
- **Sizing:** min(25% / 3-month realized vol, 2x).

A nine-lookback ensemble returned **30% CAGR, Sharpe about 1.56 net of 10 bp costs, and a 19% maximum drawdown**. Short lookbacks of 5–30 days won only **40–49% of trades, with gain:loss ratios of 3.7–6.7x** ([Concretum PDF](https://concretumgroup.com/wp-content/uploads/2026/02/Catching-Crypto-Trends.pdf)). The long-short version had near-zero beta but a lower Sharpe, **1.05–1.31**, because the BTC short side is weaker. Costs matter: at 50 bp per trade the 5-day model's CAGR fell from 34% to 18%.

The broader academic evidence is split:

- Han, Kang and Ryu find time-series momentum "strong" in crypto, but many portfolios are wiped out by realistic costs ([SSRN 4675565](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4675565)).
- Arefev finds weekly time-series momentum went **from 1.74% per week before July 2020 to negative afterwards** ([SSRN 7405060](https://papers.ssrn.com/sol3/Delivery.cfm/7405060.pdf?abstractid=7405060&mirid=1), abstract-level).

Breakouts with stops are a different design from sign-of-return momentum, but expect decay.

Shorter-horizon breakouts have mostly failed recently:

- **NY-open 30-minute opening-range breakout.** Run on BTC from June 2025 to June 2026 with 0.05% fees per side, it lost **−44.8% with a profit factor of 0.65** over 417 trades ([Secuora](https://secuora.net/strategy/opening-range-breakout)).
- **Larry Williams k=0.5 volatility breakout.** An independent Upbit replay made +199.8% CAGR in 2019–2021, then **−41.3% in 2022–2024 and −50.1% in 2025–2026**. Its profit factor fell below 1 even as costs stayed the same ([GitHub replay](https://github.com/seungjae3908-source/seungjae20260713/pull/1504)).
- **Bollinger/Keltner squeeze.** The evidence is vendor content or in-sample optimisation. One example picked the best of 243 parameter combinations on spot ([PyQuantLab](https://pyquantlab.medium.com/optimizing-the-bollinger-band-keltner-channel-squeeze-strategy-volatility-breakout-trading-in-70b49101cb30)).

What has survived is session timing used as a filter, not as a trigger. Intraday first-half-hour momentum is strongest in high-volume sessions ([Shen, Urquhart & Wang](https://onlinelibrary.wiley.com/doi/10.1111/fire.12290)). Trend returns are also stronger from the Monday Asia open ([Concretum](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/)).

On perpetuals, longs held for days pay funding: about **14% per year on Binance historically** ([Elm Wealth](https://elmwealth.com/perpetual-futures/)), and about 11% at Delta's baseline. Shorts usually collect it, which partly offsets their weaker hit rate.

## Six rule sets, each testable on local 1-minute spot and Delta marks

The rule sets below run on your local 1-minute BTC spot data and Delta daily-option marks from April to October 2026. They follow the conventions of your BTC Calm Strangle backtest: Delta 1-minute marks on a strike grid with interpolated IV, slippage at 4% of premium each way, and the Delta fee model (`btc-calm-strangle.md`). Model marks overstate what a buyer can achieve, because untraded strikes bias results ([Wen & Zhang, SSRN 7327512](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7327512)). Buyers should therefore pay ask, or mark plus half the spread plus 4%, and stress-test at 6–8%.

One structural limit applies to all of them. April to October 2026 holds roughly **190 daily expiries, about six CPI releases and four FOMC meetings**. That is enough to reject a rule, but not to prove one. Split the window into April–July and July–October, as you did for the calm strangle, and require both halves to be positive.

**Rule set 0: the variance clock (diagnostic, run first).** Two measurements, compared hour by hour:

- **Realized side:** from the 1-minute spot data, compute realized variance for each IST hour-of-day and weekday as a share of the 24-hour total.
- **Implied side:** from the marks, compute the implied variance used up per hour. Use the drop in the ATM straddle's implied variance from 17:35 IST to settlement, holding IV fixed.
- **Ratios to tabulate:**
  - by entry and exit window: realized over implied variance for 17:35→02:30, 17:35→settlement, and 22:00→06:00 (your calm-strangle window);
  - by weekday;
  - on event days against all other days.

Any window with a realized/implied ratio **above about 1.10** (5% friction on each side) is a candidate buying window. Windows well below 1 confirm your selling windows. This single table answers "should I buy movement at all?" with your own data, and the published literature cannot.

**Rule set 1: CPI/FOMC event straddle (top recommendation for options).**

| Element | Rule |
|---|---|
| Events | US CPI. FOMC as a separate test. |
| Instrument | ATM straddle (the strike nearest spot) on the daily expiring **T+1 at 17:30 IST**. The same-day expiry settles before the release. |
| Entry | 17:35–17:45 IST on event day, at ask plus slippage. Variant: T−1 17:35 IST, to capture the pre-release vol build. |
| Exit grid | (a) 2h after release: 20:00 IST for CPI under US summer time; (b) 02:30 IST; (c) expiry. FOMC: (b) or (c) only. |
| Stop | None. The debit is the maximum loss. |
| Metric | Implied move (straddle ÷ spot) vs realized move, and net P&L per event. |
| Fit with the short books | If realized does not reliably exceed implied, still use the **calendar as a no-sell filter**: skip the 2-day and calm strangles on CPI day and on FOMC days 0 to +2. |

**Rule set 2: Donchian breakout ensemble on the BTCUSD perpetual (top recommendation for movement capture).**

| Element | Rule |
|---|---|
| Bar | Daily close at 05:30 IST (00:00 UTC). Variant: 4-hour bars with lookbacks of 30–180 bars, if daily history is too short. |
| Signal | Long when close = max of the last n closes. Short when close = min of the last n closes. n ∈ {5, 10, 20, 30}, equal-weighted. |
| Exit | Trailing stop = max(prior stop, Donchian midline) for longs, and the mirror for shorts. Checked on closes only. |
| Sizing | Weight = min(target vol / 90-day realized vol, 2), with a 20% no-trade band on resizing. |
| Execution | Next 1-minute open after the signal close. Taker 0.059% per side including GST. Maker variant at 0.024%. |
| Funding | Charge the actual Delta funding history at 05:30, 13:30 and 21:30 IST: longs pay, shorts receive. |
| Data note | Six months gives a 20-day system only a handful of trades. Extend daily history from [Delta's candles API](https://api.india.delta.exchange/v2/history/candles?resolution=1h&symbol=FUNDING:BTCUSD) (symbol BTCUSD, daily resolution) back several years, and use the 1-minute data only for execution realism. |

**Rule set 3: gated evening long straddle (third, speculative).** Buy only when options look cheap against recent realized vol, and hold only through the busy hours.

| Element | Rule |
|---|---|
| Instrument | ATM straddle on the next-day daily, bought 17:35–18:00 IST. |
| Gate A (cheapness) | Straddle-implied vol ≤ 1.0 × trailing 7-day realized vol from 1-minute data, measured over the same 17:30→02:30 window. |
| Gate B (compression) | Trailing 24h high-low range in the bottom 20% of the last 30 days. Test A alone, B alone, and A+B. |
| Skip | Saturday entries (the quietest day). |
| Exit grid | 02:30 IST (after the US close and benchmark fix); straddle +50% / +100%; expiry. Keep the grid this small. |
| Variants | (i) Sunday 17:35 IST entry held through the ~04:30 IST Monday Asia open. (ii) Gamma-scalp: hedge with post-only perpetual orders at every ±1% move; report hedge fees separately. |

**Deprioritised (test only if 1–3 show promise).** These are the NY-open opening-range breakout, the Williams k-range breakout and unfiltered daily long straddles. All three have recent negative published results. Gamma scalping is folded into rule set 3 as a variant.

## Conclusion

The question is less "buy or sell volatility?" than **when your strangles are short the moves BTC reliably makes**. Your overnight calm strangle already sits in BTC's quietest hours. Your 2-day strangle is exposed to exactly the windows where sellers lose: CPI evenings, FOMC nights and Sunday-to-Monday. The highest-value step is therefore defensive. Build the variance-clock table, then use it and the event calendar to stop selling into scheduled movement. Avoiding a concentrated loss is the cheapest long-volatility position available.

Run the Donchian perpetual sleeve next, as a separate, low-correlation book. It is the one direction-agnostic system with a decade of BTC evidence, and it pays most in trending markets, which hurt short strangles most. If that holds up, run the event straddle as a small hedge.

The caveat: every rigorous public study since 2017 has found BTC options overpriced on average, most of all in calm regimes. The long side of short-dated BTC options has no published, cost-inclusive, positive-expectancy rule. Six months of Delta data cannot overturn that. Treat any long-straddle result from this backtest as a hypothesis to paper-trade, not as an edge.
