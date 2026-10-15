# BTC Volatility Evidence: Selling vs Buying Volatility (Implied vs Realized, VRP, Timing of Moves)

Research date: 2026-10-15. IST = UTC + 5:30 (no DST in India). US events shift by one hour in UTC when US daylight saving ends (early Nov to mid Mar). Times below give both conventions where it matters.

## 1. Is the BTC volatility risk premium (implied minus subsequently realized) positive on average? Magnitude, variation, frequency of realized > implied

### Takeaway
Yes. On average BTC implied vol exceeds the realized vol that follows, by roughly 9-15 vol points at the 30-day tenor. 30-day IV was above 30-day RV about 70% of the time in 2019-2022, so realized beats implied about 30% of the time. Those losing episodes cluster in fast trending markets, especially sharp rallies. Since the ETF era (2024 onward), implied vol has been structurally pushed down by call overwriting. Realized vol has also fallen, so the premium still exists, but the absolute levels are much lower: DVOL lows were about 34-36 in 2025-26.

### Cited Findings
- **Academic, unconditional:** For the one-month horizon, risk-neutral variance (squared BVIX) averaged 0.72 and physical realized variance averaged 0.58, an annualized variance risk premium of 0.14. The S&P 500 figure is about 0.02 (Bollerslev-Tauchen-Zhou). Data: Deribit options, 1 Jul 2017 to 17 Dec 2022, 7.83M option trades, average BTC IV 82%. — [Almeida, Grith, Miftachov, Wang, "Risk Premia in the Bitcoin Market", arXiv 2410.15195 v2, Aug 2025](https://arxiv.org/abs/2410.15195)
- **The VRP is larger in the low-volatility regime.** Low-vol cluster: risk-neutral variance 0.46 vs physical 0.29, VRP 0.17. High-vol cluster: 0.86 vs 0.74, VRP 0.12. The authors say BTC investors are "more concerned about variance and upside risk in a low-volatility regime." The BVRP is driven by upside return states, unlike the SPX VRP, which is driven by the downside. — [Almeida et al., arXiv 2410.15195](https://arxiv.org/abs/2410.15195); [SSRN "Option-Implied Risk Premia and Cryptocurrency Market Regimes"](https://ssrn.com/abstract=5374295)
- **Practitioner data, 2019-2022:** 30-day BTC IV exceeded subsequent 30-day RV "nearly 70% of the time" (Apr 2019 to Dec 2022). When the term structure was in contango (77.5% of hours), the mean VRP was about +15 vol points. Backwardation episodes lasted about 85 hours on average, and the front/back ratio peaked around 1.45 in shocks. — [Amberdata via Deribit Insights, "Bitcoin Options: Finding edge in four years of volatility regimes", 24 Jan 2023](https://insights.deribit.com/industry/bitcoin-options-finding-edge-in-four-years-of-volatility-regimes/)
- **Upside VRP, 2024-2026:** 30-day 25-delta call IV minus realized upside vol over the next 21 trading days has averaged about 2-3 times the SPY/QQQ equivalent through the post-2024 window. It occasionally reaches +20 to +30 vol points, with tail events that turn sharply negative when realized upside surprises. January 2026 is the most prominent example. Study window: Oct 2021 to Apr 2026. — [Anchorage Digital (D. Lawant), "Synthetic Yield on Bitcoin" whitepaper, 2026](https://cdn.prod.website-files.com/64b0dcb6fecf02d30d8dd905/6a15dc7a499b7b4150c162ef_synthetic-yield-on-bitcoin-whitepaper.pdf)
- **VRP is positive and highly persistent.** Paper abstract using Deribit BTC options. — [Atanasova, Miao, Segarra, Willeboordse, "What Do Crypto Options Tell Us?", SSRN 6771170](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6771170) (abstract only; the full text was not accessible)
- **Earlier sign-convention conflict:** Alexander and Imeraj built a "Bitcoin VIX" from Deribit options (Mar 2019 to Mar 2020, 15-minute sampling, 1-week to 3-month maturities). A search snippet describes the BTC VRP as "consistently negative and significantly larger than S&P 500". That wording most likely reflects their realized-minus-implied sign convention, but I could not verify it against the full text. Treat the sign with care when citing. — [Alexander & Imeraj, "The Bitcoin VIX and its Variance Risk Premium", SSRN 3383734](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3383734)
- **The VRP is crash-conditional compensation, not free carry.** It appears with comparable magnitude in gold, BTC and ETH (Jun 2026). — [Shehzad Ahmed, "The Variance Risk Premium Across Markets and Regimes", SSRN 7046559](https://papers.ssrn.com/sol3/Delivery.cfm/7046559.pdf?abstractid=7046559&mirid=1) (abstract-level only)
- **Bull-market example, 2024-25:** In early 2024 (BTC $43k to $73k), BVIV rose from 43% to 85% and 30-day RV peaked around 85%. In the Nov 2024 to Jul 2025 rally ($70k to $118k), BVIV fell to about 40% (the lowest since Oct 2023) and 3-month RV fell to about 28%. Institutions, miners and treasury vehicles were overwriting calls. — [CoinDesk, 11 Jul 2025](https://www.coindesk.com/markets/2025/07/11/bitcoin-s-record-rally-from-usd70k-to-usd118k-a-tale-of-transition-from-wild-west-to-wall-street-like-dynamics)
- **2025 full year:** BVIV and DVOL started near 70%, ended near 45%, with a low of about 35% in Sep 2025. Wintermute: ">12.5% of all mined Bitcoin now sits in ETFs + treasuries … overwriting emerged as the dominant flow throughout 2025." Puts traded at a persistent premium to calls through 2025. — [CoinDesk, 31 Dec 2025](https://www.coindesk.com/markets/2025/12/31/bitcoin-market-calmed-in-2025-thanks-to-yield-hungry-institutions)
- **DVOL record low:** 33.8 on 18 Sep 2025. DVOL reached a nine-month low of 36.11% in May 2026. These come from search-result summaries of [Hodlometer](https://hodlometer.com/learn/bitcoin-implied-volatility-dvol/) and the [Bitcoin Volatility Index site](https://bitcoinvolatilityindex.com/), which are secondary sources.
- **After the ETF launch** (Jan 2024), 30-day RV has not exceeded 80%. — [Kaiko, "Bitcoin Booms in Low-Risk Environment"](https://research.kaiko.com/insights/bitcoin-booms-in-low-risk-environment) (via search summary)
- **Recent term structure:** ATM IV of about 29.7% at 1 week, 34.1% at 1 month, 37.0% at 3 months and 37.9% at 6 months, an upward-sloping curve. 7-day ATM IV was about 32% ahead of a CPI week (Oct 2026). — [CryptoSlate](https://cryptoslate.com/bitcoin-traders-brace-for-cpi-shock-with-451-million-in-downside-options-bets/); [Digital Today](https://www.digitaltoday.co.kr/en/view/113628/bitcoin-volatility-expectations-ease-ahead-of-us-cpi-put-bets-build-below-80000)

### Inferences
- Converting Almeida et al.'s variances to vol (my calculation): 84.9% implied vs 76.2% realized, about 8.7 vol points overall. The low-vol regime is 67.8% vs 53.9% (about 14 pts). The high-vol regime is 92.7% vs 86.0% (about 7 pts). In relative terms, the premium is largest when markets are calm. That is when sellers earn the most per unit of IV, and also when an under-priced breakout is most costly.
- "Realized > implied about 30% of the time" (2019-22) implies a seller's hit rate around 70% at the 30-day tenor. Losses are concentrated and autocorrelated, as Anchorage documents for trending rallies.
- Post-2024 supply of overwritten calls has compressed the upside VRP in level terms but not removed it. Buyers now pay much less for convexity in absolute terms (DVOL in the 30s-40s versus 60-80+ before).

### Gaps
- I found no public, regularly updated series of DVOL minus subsequent 30-day RV with year-by-year means for 2023-2026. Glassnode, Amberdata and Laevitas dashboards are paywalled or interactive.
- I could not verify the full text of Alexander & Imeraj or Atanasova et al. for magnitudes.

## 2. Do systematic option sellers or buyers win in BTC, especially for short-dated (daily/weekly, 0DTE/1DTE) options?

### Takeaway
Sellers have won on average, but the returns are negatively skewed and depend heavily on implementation. Delta-hedged weekly straddle selling and Friday-to-Sunday weekend strangles have been profitable from 2019-2020 to 2025. Unfiltered call overwriting roughly broke even across Oct 2021 to Apr 2026, because trending bull runs overran short calls. 7-14 day tenors had the worst tails and the lowest median yields in Anchorage's study. Selling into a quiet Sunday morning before Monday's TradFi reopen has been a strongly losing trade. I found no rigorous public study of BTC 0DTE/1DTE VRP.

### Cited Findings
- **Weekend strangle selling** (Deribit, by Cryptarbitrage, 21 May 2025). Sell a 0.35-delta strangle every Friday at 16:00 UTC (21:30 IST) expiring Sunday 08:00 UTC (13:30 IST). Costs: 0.0003 BTC fee per option plus 5% slippage. Period 1 Jan 2020 to 30 Apr 2025:
  - 247 trades, 202 wins and 45 losses (about 82% win rate)
  - net +1.5477 BTC on a 1 BTC start (+154.8%), APR 29.7%
  - max drawdown 23.8% (0.27 BTC)
  - Sep 2024 to Apr 2025: 32 wins and 2 losses, which the author says is running "above expected value" given the negative skew. — [Deribit Insights, "Option Backtest - Selling Weekend Vol, Revisited"](https://insights.deribit.com/education/option-backtest-selling-weekend-vol-revisited/)
- **Same strategy, other days:**
  - Selling every day at half size: 1,780 trades, +126.5%, APR 23.8%, max drawdown 26.5% (0.45 BTC).
  - **Sunday-only entries were catastrophic:** about 251 trades, -92.24%, APR -17.7%. The author attributes this to selling "on typically low volatility Sunday mornings" ahead of Monday volatility when traditional markets reopen.
  - ETH version: APR 20.3%. — [Deribit Insights, same article](https://insights.deribit.com/education/option-backtest-selling-weekend-vol-revisited/); original version: [Option Backtest - Selling Weekend Vol](https://insights.deribit.com/education/option-backtest-selling-weekend-vol/)
- **Systematic weekly straddle selling with a 2.5% delta-hedge threshold** (Apr 2019 to Dec 2022) produced positive risk-adjusted returns through multiple crashes. The optimal mix was about 90% strategy and 10% spot for weekly maturities. Selling 25-delta risk reversals beat buying them, much more so excluding March 2020. Wing-protected butterflies (±10%) underperformed straddles because of the protection cost. Event-driven long vol before FOMC/CPI showed positive returns, but with fewer than 15 trades each, which is not statistically meaningful. — [Amberdata via Deribit Insights, Jan 2023](https://insights.deribit.com/industry/bitcoin-options-finding-edge-in-four-years-of-volatility-regimes/)
- **Covered calls, Oct 2021 to Apr 2026** (about 37,000 backtests):
  - Unfiltered 20-delta 30-day calls: +5.5% net yield in the last 12 months (vs -19.4% spot), but -0.5% total over the full period. Profit factor was 1.00 despite a 4.38:1 win/loss ratio, with 13 losing outcomes in 70 trades.
  - With a trend filter (not strongly bullish) and an IV filter (IV above its 90-day average), net yield was +23.7% (5.2% annualized). Blended Sharpe rose from 0.20 to 0.30, with the strategy in the market only 44% of the time.
  - **7-day and 14-day tenors had the widest downside tails and lowest medians.** The authors call very short-dated options "structurally disadvantaged on BTC". Results improve from 21 days onward. — [Anchorage Digital whitepaper](https://cdn.prod.website-files.com/64b0dcb6fecf02d30d8dd905/6a15dc7a499b7b4150c162ef_synthetic-yield-on-bitcoin-whitepaper.pdf)
- Anchorage's mechanism for seller losses: autocorrelated, trending moves mean each new short is opened into a market already moving against the last one. — [Anchorage whitepaper](https://cdn.prod.website-files.com/64b0dcb6fecf02d30d8dd905/6a15dc7a499b7b4150c162ef_synthetic-yield-on-bitcoin-whitepaper.pdf)
- Short-dated (7-14 day) BTC options are highly sensitive to intraday spikes that later reverse, so delta expansion within the holding period is frequent. — [Anchorage whitepaper](https://cdn.prod.website-files.com/64b0dcb6fecf02d30d8dd905/6a15dc7a499b7b4150c162ef_synthetic-yield-on-bitcoin-whitepaper.pdf) (via search summary)

### Inferences
- For a daily strangle seller, the evidence says avoid selling into a weekend-close-to-Monday-reopen window. Friday-to-Sunday-morning (before TradFi reopens) has been the sweet spot. Selling into Sunday has been the trap.
- For a movement buyer, edge is most plausible in three places: (a) entering when IV is cheap relative to its own history, especially in the low-vol regime; (b) around scheduled macro events; (c) Sunday-to-Monday.

### Gaps
- I found no published 0DTE/1DTE BTC implied-vs-realized study (Deribit dailies expire 08:00 UTC = 13:30 IST). The Deribit weekend backtest, with a roughly 40-hour hold, is the closest public evidence.
- There are no public post-2025 backtests for daily straddle buying.

## 3. Intraday seasonality: which UTC hours (and IST) have the highest and lowest realized vol and volume

### Takeaway
BTC volatility peaks during US hours and at the 00:00 UTC daily rollover. Hansen et al. find volatility is highest around 16:00 UTC (21:30 IST) and at the 00:00 UTC hour (05:30 IST), and lowest around 05:00 UTC (10:30 IST). The 04:00-12:00 UTC block (09:30-17:30 IST, i.e. Indian market hours) is the quietest. Since the ETFs, volume has concentrated further into US hours: more than 55% of BTC-USD volume in 2025 vs 39% in 2020. The 15:00 UTC hour (20:30 IST) and the US close/benchmark fix are now volume peaks.

### Cited Findings
- **Hansen, Kim, Kimbrough** (Coinbase Pro, Binance, Uniswap; Oct 2020 to May 2021, robust on Jan 2019 to May 2021):
  - Volatility is high around 16:00 UTC and bottoms near 05:00 UTC. There are spikes in volume and volatility at 00:00 and 16:00 UTC, and smaller ones at 08:00 UTC, which match Binance funding times (00/08/16 UTC).
  - "The 1st hour and the hour after 16:00 UTC tend to have the highest level of volatility." The first-hour ratio is especially large on Mondays. The 13th and 15th hours are calmer on Fri/Sat/Sun.
  - Within the hour, the first minute is most volatile, with peaks every 15 minutes and smaller ones every 5 minutes. This is linked to algorithmic trading and perpetual funding times.
  - Coinbase volume is much lower from 05:00 to 12:00 UTC (US night).
  - The patterns have strengthened over the years. — [Hansen, Kim, Kimbrough, "Periodicity in Cryptocurrency Volatility and Liquidity", arXiv 2109.12142](https://arxiv.org/abs/2109.12142)
- Earlier literature cited there: highest activity, highest vol and lowest spreads coincide with US trading hours (Dyhrberg et al. 2018). Crypto liquidity peaks when the US and London stock markets are both open (Aleti & Mizrach 2021). — [arXiv 2109.12142 literature review](https://arxiv.org/abs/2109.12142); see also [Eross et al., Finance Research Letters, "Time-of-day periodicities of trading volume and volatility in Bitcoin exchange"](https://www.sciencedirect.com/science/article/abs/pii/S1544612319301904)
- **Kaiko, ETF era (Q1 2024):**
  - Over $17.6bn of weekday volume traded between 20:00 and 21:00 UTC (3-4pm NY benchmark fix under EST), which is more than 6.7% of all volume, up from 4.5% in Q4 2023.
  - The second most active hour was 15:00 UTC.
  - Binance volume peaks at the US open and declines through the rest of the day.
  - Weekday US-close share was 6.6%, versus just over 4% on weekends. — [Kaiko, "BTC ETFs' Impact on Spot Market Structure"](https://www.kaiko.com/resources/btc-etfs-impact-on-spot-market-structure)
- More than 55% of BTC-USD trading happened during US hours in 2025, up from 39% in 2020. — [Kaiko via search summary](https://research.kaiko.com/insights/bitcoin-booms-in-low-risk-environment); also [Bitget News](https://www.bitget.com/news/detail/12560605322841)
- From 04:00 to 12:00 UTC, displayed depth is typically 2-7% above the daily median, with lower volume and RV. On weekdays, volume and RV peak at 14:00-15:00 UTC. — [QuantumFlow, "Bitcoin Liquidity by Hour"](https://quantumflow.tech/learn/crypto-liquidity-by-hour/) (secondary aggregator; treat as indicative)
- Coinbase $100k-sell slippage rises at the start and end of US market hours (15:00 and 20:00 UTC). — [Kaiko, "Moving Markets: Liquidity and Large Sell Orders"](https://research.kaiko.com/insights/moving-markets-liquidity-and-large-sell-orders)

**IST conversion table:**

| Window | UTC | IST |
|---|---|---|
| Daily rollover / Binance funding / high-vol hour | 00:00-01:00 | 05:30-06:30 |
| Quietest stretch (Asia late morning to EU morning) | ~04:00-12:00, trough ~05:00 | ~09:30-17:30, trough ~10:30 |
| Binance funding | 08:00 | 13:30 |
| Deribit daily/weekly expiry | 08:00 | 13:30 |
| US CPI / NFP / PCE data release | 12:30 under EDT (Mar-Nov), 13:30 under EST | 18:00 EDT / 19:00 EST |
| US equity open | 13:30 EDT / 14:30 EST | 19:00 / 20:00 |
| Peak volume hour | 14:00-16:00 | 19:30-21:30 |
| Hansen et al. vol peak, Binance funding | 16:00-17:00 | 21:30-22:30 |
| FOMC statement (2pm ET) | 18:00 EDT / 19:00 EST | 23:30 / 00:30 next day |
| US close / benchmark fix | 19:00-20:00 EDT, 20:00-21:00 EST | 00:30-01:30 / 01:30-02:30 |

### Inferences
- For an India-based trader, the Indian trading day (09:15-15:30 IST) falls in BTC's quietest window. Seller-friendly decay happens then. The movement window is about 18:00-22:30 IST, plus the US close and FOMC late in the IST night.

### Gaps
- I found no peer-reviewed hour-by-hour RV table for 2024-2026. The post-ETF hourly volatility profile comes mostly from Kaiko's volume and liquidity data, not RV.

## 4. Day-of-week / weekend effects, and behaviour around CPI, FOMC, ETF flows, expiries and funding

### Takeaway
Weekend volatility and volume are lower, Saturday lowest. The weekend volume share fell from 28% in 2019 to 16% in 2024. Thinner weekend liquidity makes stress-driven weekend gaps sharper. Monday's first hour is unusually volatile. CPI produces a sharp one-day, first-hour vol spike. FOMC produces a larger and more persistent effect, with vol elevated for days 0 to +2. Big expiries tend to compress IV into the cut, followed by movement afterwards.

### Cited Findings
- **Day of week:** Both volatility and volume are smaller on weekends, most pronounced on Saturdays, and stable across years (2019-2021 samples). Monday's first UTC hour is particularly volatile. — [Hansen et al., arXiv 2109.12142](https://arxiv.org/abs/2109.12142)
- **Weekend volume:** 28% of BTC volume traded on weekends in 2019, falling to an all-time low of 16% in 2024, with the decline accelerated by spot ETFs (launched 11-12 Jan 2024). — [Kaiko](https://www.kaiko.com/resources/btc-etfs-impact-on-spot-market-structure); [The Block](https://www.theblock.co/post/302705/bitcoin-sees-all-time-low-weekend-trading-levels-following-etf-approvals-kaiko)
- Kaiko warns that thinner weekend liquidity raises the risk of "sharp weekend price swings" under stress. — [Cointelegraph citing Kaiko](https://cointelegraph.com/news/bitcoin-etfs-worsened-liquidity-weekend-price-swings-kaiko)
- **Tuesday in 2025:** Tuesdays were the most volatile weekday YTD in 2025. Over the month to 18 Mar 2025 they averaged RV of about 82, while March 2025 RV of 67 was the highest month since early 2024 (Amberdata). — [CoinDesk, 18 Mar 2025](https://www.coindesk.com/markets/2025/03/18/tuesdays-have-been-bitcoin-s-most-volatile-day-in-2025)
- **Weekend option pricing:** The evidence is indirect but consistent. A 0.35-delta Friday-to-Sunday strangle had an 82% win rate (2020 to Apr 2025), while Sunday-entry strangles lost heavily. This implies weekend-period IV over-prices Saturday's realized moves and under-prices the Sunday-to-Monday transition. — [Deribit Insights, May 2025](https://insights.deribit.com/education/option-backtest-selling-weekend-vol-revisited/)
- **CPI** (8:30 ET = 12:30 UTC EDT / 13:30 UTC EST):
  - Over 2020-2026, a +1pp CPI surprise maps to about -5.5% BTC in the first hour, and the surprise explains about 25% of first-hour return variance.
  - Dec 2021 to Nov 2023 peak: β of about -13%/pp, so a 0.1pp surprise meant about -1.3%.
  - 12-release window to Jun 2026: β of -3.2%/pp with R² near 80% (a record), concentrated at the 1-hour horizon.
  - Example: 14 Jul 2026, CPI 3.5% vs 3.8% expected, BTC +2.9% on the day. — [Block Scholes, "Is Bitcoin showing greater sensitivity to US CPI releases again?"](https://www.blockscholes.com/institutional-research/is-bitcoin-showing-greater-sensitivity-to-us-cpi-releases-again)
- **CPI vs FOMC event study** (daily data, 2020-2025):
  - CPI: volatility builds before the release (about +0.5 to 0.7 pp of daily vol on days -2 to -1), peaks on day 0 (about +0.8 pp), and is back to insignificant by days +1 to +2.
  - FOMC: day-0 spike of about +1.0 pp, and vol stays elevated on days +1 to +2 (about +0.5 to 0.6 pp). Returns show no consistent drift.
  - Master's thesis, not peer reviewed. — [Nazaruk, "Bitcoin's Reaction to U.S. FOMC and CPI Announcements", KSE thesis, 2026](https://kse.ua/wp-content/uploads/2026/05/illia-nazaruk_268722_assignsubmission_file_nazaruk_final_thesis.pdf)
- FOMC-day crypto volatility rises significantly, with intraday fluctuations both before (11 a.m.) and after (3 p.m.) the announcement. — [SCIRP, "Modeling Cryptocurrency Market Volatility during FOMC Announcements"](https://www.scirp.org/journal/paperinformation?paperid=136168) (lower-tier journal)
- **Options expiries:**
  - Deribit noted IV compression of about 6 points into a large quarterly expiry.
  - The commentary pattern is suppressed volatility into the cut and directional moves 24-72 hours after. — [Yahoo Finance / Deribit](https://finance.yahoo.com/news/bitcoins-12b-quarterly-options-expiry-131620451.html); [Bloomberg, 18 Dec 2025](https://www.bloomberg.com/news/articles/2025-12-18/bitcoin-volatility-rises-ahead-of-23-billion-options-expiration)
  - A 2026 Finance Research Letters study reportedly finds intraday BTC price reversals around Deribit expiries, strongest with high ATM open interest and negative dealer gamma (search summary; I did not locate the primary article).
- **Funding times:** The minute-of-hour volatility spikes are strongest at 00/04/08/12/16/20 UTC (except 08h), consistent with perpetual funding schedules (Binance 00/08/16 UTC; BitMEX 04/12/20 UTC). — [Hansen et al., arXiv 2109.12142](https://arxiv.org/abs/2109.12142)
- **ETF flows:** The benchmark-fix hour (3-4pm NY) rose to more than 6.7% of daily volume in Q1 2024 as ETFs create and redeem around the close. — [Kaiko](https://www.kaiko.com/resources/btc-etfs-impact-on-spot-market-structure)

### Inferences
- **CPI** is a short, sharp event, roughly a one-hour effect. It favours a long straddle bought shortly before 12:30/13:30 UTC (18:00/19:00 IST) and exited within hours. A strangle seller holding through CPI faces a concentrated gap risk.
- **FOMC** lands at 23:30/00:30 IST, and its vol persists for 1-2 days. This argues against re-selling vol right after FOMC.

### Gaps
- I found no systematic study quantifying weekend vs weekday IV per day in BTC options, i.e. how many "variance days" the market assigns to Saturday and Sunday.
- I found no quantitative study isolating ETF-flow days (large creations or redemptions) against intraday RV.

## 5. Volatility clustering / regime persistence: does low realized vol predict expansion, and over what horizon?

### Takeaway
BTC volatility clusters strongly, and periodic GARCH models improve forecasts. Both academic and practitioner evidence say the premium is richest in low-vol regimes, while extremely low RV readings historically precede expansions. I found no rigorous public study giving a horizon-specific hit rate for "low RV leads to a squeeze". The evidence for timing is mostly anecdotal.

### Cited Findings
- Adding realized variance and intraday/weekly periodicity to GARCH (pEGARCH-X) improves BTC log-likelihood by about 19 units in-sample and about 34 units out-of-sample, over 2017-2019 in-sample and Jan 2020 to Jul 2021 out-of-sample. Volatility is persistent and forecastable, and the periodic patterns are stable. — [Hansen et al., arXiv 2109.12142](https://arxiv.org/abs/2109.12142)
- RNDs cluster into two regimes. In the low-vol regime, VRP is higher (0.17 vs 0.12) and the upside share of the return premium is larger. Investors fear upside breakouts more when vol is low. — [Almeida et al., arXiv 2410.15195](https://arxiv.org/abs/2410.15195)
- Contango holds about 77.5% of hours. Backwardation (vol shocks) lasts about 85 hours on average, so shock regimes are short-lived relative to calm ones. — [Amberdata / Deribit Insights](https://insights.deribit.com/industry/bitcoin-options-finding-edge-in-four-years-of-volatility-regimes/)
- Trend persistence (autocorrelated rallies) is what defeats short-call sellers across successive expiries. — [Anchorage whitepaper](https://cdn.prod.website-files.com/64b0dcb6fecf02d30d8dd905/6a15dc7a499b7b4150c162ef_synthetic-yield-on-bitcoin-whitepaper.pdf)
- **"Coiled spring" claims:**
  - 30-day RV at about the 1st percentile of history has "preceded every relevant price move".
  - When short-dated RV rises, BTC was higher 90 days later 67% of the time, but RV changes explain only about 14.6% of 90-day return variance.
  - Both are secondary and promotional sources with unclear methodology. — [CCN](https://www.ccn.com/education/crypto/bitcoin-volatility-floor-1-percent-coiled-spring-warning/); [Spark research](https://www.spark.money/research/bitcoin-volatility-compression-institutional-impact)
- **Structural decline:** BTC annualized vol fell from more than 180% (2013) to as low as about 23% (2025). By Aug 2026, 30-day vol briefly fell below the Nasdaq's. — [Spark research](https://www.spark.money/research/bitcoin-volatility-compression-institutional-impact) (secondary); [Fidelity Digital Assets, "A Closer Look at Bitcoin's Volatility"](https://www.fidelitydigitalassets.com/research-and-insights/closer-look-bitcoins-volatility)

### Inferences
- Low RV raises the expected VRP, which favours sellers, and also raises the probability of a breakout, which favours buyers. The honest reading: in low-vol regimes options are expensive relative to recent realized vol but cheap in absolute terms.
- A practical buyer filter is IV percentile, not RV. Anchorage's seller filter was "IV above its 90-day average"; the mirror image, buying when IV is below its average, is the natural buyer condition. I found no published test of that buyer filter.

### Gaps
- I found no peer-reviewed or reproducible study giving P(RV expansion | RV in bottom decile) over 1, 7 or 30 days for BTC in 2020-2026. This is worth computing in-house from Delta/Deribit candles.
