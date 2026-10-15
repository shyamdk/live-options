# Breakout and Momentum Strategies for BTC (Perps / Spot), Both Directions

Scope: documented, backtestable breakout and trend systems for BTC at horizons from intraday to a few days, with published rules and performance. Research date: 2026-10-15. Every number below comes from the cited source. Most sources are in-sample backtests with no separate out-of-sample period; this is flagged per item.

## 1. Donchian / Turtle-style breakouts on BTC

### Takeaway
The best-documented BTC breakout study (Zarattini, Pagani and Barbon / Concretum, 2025) finds that daily-close Donchian breakouts with a Donchian-midline trailing stop work on BTC from 2015 to March 2025. Short lookbacks (5 to 30 days) gave the best risk-adjusted results, and a 9-lookback ensemble had a Sharpe of about 1.3 to 1.6 and a max drawdown of 19%. Win rates are only 34-49% for the short lookbacks, while gain-to-loss ratios are 3 to 7x. Adding shorts reduced the Sharpe compared with long-only.

### Cited Findings
**Zarattini, Pagani, Barbon, "Catching Crypto Trends; A Tactical Approach for Bitcoin and Altcoins" (SSRN 5209907, Apr 2025)** — [Concretum summary](https://concretumgroup.com/catching-crypto-trends-a-tactical-approach-for-bitcoin-and-altcoins/); [PDF](https://concretumgroup.com/wp-content/uploads/2026/02/Catching-Crypto-Trends.pdf); [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5209907)
- Rules:
  - DonchianUp(n) = max of the last n closes. DonchianDown(n) = min of the last n closes. Mid = average of the two.
  - Go long when the close equals the n-day high.
  - Exit on the first close below a trailing stop. The stop is updated daily as max(prior stop, Donchian mid), so it never moves down. The initial stop is the midline.
  - Signals use daily closes.
  - Position size = min(25% / σ, 200%), where σ is 3-month realized vol. This targets 25% annualized vol with a 2x leverage cap.
- Ensemble ("Combo"): an equal-weighted average of the weights from n ∈ {5, 10, 20, 30, 60, 90, 150, 250, 360}.
- Period: 1 Jan 2015 to 19 Mar 2025, using CoinMarketCap data. Table results are gross of costs. In-sample only, with no holdout.
- Long-only BTC results (CAGR / Sharpe / MDD), with BTC passive MDD above 80%:
  - 5d: 36% / 1.66 / 25%
  - 10d: 32% / 1.55 / 27%
  - 20d: 34% / 1.60 / 26%
  - 30d: 34% / 1.61 / 24%
  - 60d: 28% / 1.30 / 19%
  - 90d: 27% / 1.20 / 24%
  - 150d: 21% / 0.99 / 29%
  - 250d: 25% / 1.13 / 33%
  - 360d: 29% / 1.28 / 34%
  - Combo: 30% / 1.58 / 19%, with Sortino 2.03 and alpha 14% per year.
- Long-only trade statistics (trades, win rate, gain:loss ratio):
  - 5d: 292, 41%, 3.7
  - 10d: 156, 40%, 4.5
  - 20d: 78, 47%, 5.2
  - 30d: 49, 49%, 6.7
  - 60d: 28, 46%, 9.2
  - Worst single trade for 5 to 60d: about -5% to -7%. Best trade: 29% to 89%.
- Long-short version: the position goes to -1 on a close at the n-day low, with a mirrored trailing stop (min of prior stop and the midline).
  - CAGR / Sharpe / MDD: 5d 30% / 1.05 / 28%; 20d 32% / 1.15 / 27%; 30d 29% / 1.05 / 27%; Combo 27% / 1.31 / 19%. Beta is close to 0.
  - Win rates: 5d 37% (591 trades), 10d 34%, 20d 41%, 30d 39%. Gain:loss ratios: 2.8 to 4.3.
  - The short side adds trades and lowers the Sharpe compared with long-only.
- Fees:
  - At 50 bps per trade, the 5-day model's CAGR falls from 34% to 18%. Longer lookbacks are hurt less.
  - A 20% rebalance threshold on vol-driven resizing recovered about 100 bps per year.
  - The authors say BTC costs are typically below 5 bps on major exchanges. Their later results use 10 bps plus the threshold. The headline net figure for Combo is 30% CAGR, Sharpe 1.56, MDD 19% ([Concretum Substack](https://concretumgroup.substack.com/p/catching-crypto-trends)).
- Funding is not modeled, since the study uses spot data.

**Padysak and Vojtko (Quantpedia), "Seasonality, Trend-following, and Mean Reversion in Bitcoin" (2022)** — [Quantpedia](https://quantpedia.com/trend-following-and-mean-reversion-in-bitcoin/)
- Rules: buy when BTC makes a new n-day maximum (n = 10 to 50 days, daily data). Gemini data, 26 Nov 2015 to 3 Feb 2022.
- Shorter lookbacks did best, and 10 days was the best.
- A combined version holds long after either a new n-day MAX (trend) or a new n-day MIN (reversion) and is flat otherwise. It returned 98.43% annualized with 47.75% vol, -37.67% MDD and a return/vol ratio of 2.06. BTC over the same period: 74.35% vol and -83.65% MDD.
- Fees are not stated. In-sample. Long-only.
- A follow-up paper, "Revisiting Trend-following and Mean-Reversion Strategies in Bitcoin" (Beluská and Vojtko, SSRN 4955617), extends the test period ([SSRN](https://papers.ssrn.com/sol3/Delivery.cfm/4955617.pdf?abstractid=4955617&mirid=1)). Its PDF returned HTTP 403, so its results are not captured here.

**Coinquant blog: BB(20,2) breakout on ETH/USDT 4h, Nov 2025 to May 2026, 0.1% fees** — [Coinquant](https://www.coinquant.ai/blog/breakout-trading-strategy-does-it-work-on-crypto-backtested)
- 21 trades, 33.3% win rate, PF 2.45, +94.8%, MDD 21.6%.
- This is ETH, not BTC, and the sample is very small. It is low-evidence vendor content.

### Inferences
- For a "capture big moves either way" system on BTC, the evidence favors short daily lookbacks (about 5 to 30 days) on closing prices, with a midline or chandelier-style trailing stop and vol-targeted sizing. Expect win rates around 35-50%, with profits coming from a few large winners at 3 to 7x the average loss.
- The short side of BTC trend has historically been weaker than the long side. A symmetric long/short system should expect a lower Sharpe than long-only, although the long-short version has close to zero beta.
- An ensemble across lookbacks improves the drawdown more than it improves returns.

### Gaps
- I found no rigorous published Donchian backtests on 1h or 4h BTC bars with fees from a credible source. TradingView and vendor results are anecdotal.
- Profit factor is not reported in the Concretum paper. It reports win rate and gain:loss ratio instead.
- The Beluská and Vojtko post-2022 out-of-sample results are not retrieved.

## 2. Opening-range and session breakouts in a 24h market (Asia, London, US open)

### Takeaway
Academic evidence shows intraday time-series momentum in BTC (the first half-hour predicts the last half-hour) and seasonality around equity-market clock times. However, published crypto ORB backtests are thin and mixed. The one independent 12-month BTC test of a NY-open 30-minute ORB lost money after fees. Concretum reports that a high-frequency trend ensemble has its best returns starting at the Sunday Asia open.

### Cited Findings
- **Shen, Urquhart and Wang, "Bitcoin intraday time series momentum", Financial Review (2022)** — [Wiley](https://onlinelibrary.wiley.com/doi/10.1111/fire.12290); [CentAUR](https://centaur.reading.ac.uk/100181/)
  - The first half-hour return positively predicts the last half-hour return. Trading "sessions" are defined using volume as a proxy, since BTC has no official open or close.
  - Sessions with the highest volume or volatility show the strongest predictability.
  - Market timing based on this signal gives economic gains, especially during downturns. The effect is driven by liquidity provision.
  - The full text was blocked, so the exact clock times, costs and Sharpe figures were not retrieved.
- **Concretum, "Seasonality in Bitcoin Intraday Trend Trading"** — [Concretum](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/)
  - Strategy: an ensemble of high-frequency long-short trend-following models at a 20% vol target, over 2018-2025. Rules are proprietary.
  - Sharpe is about 1.6 gross of fees, versus about 0.8 for vol-targeted buy-and-hold.
  - Monday Asia Open Effect: strong trend returns from Sunday 19:00 ET (Tokyo open, which is about 04:30-05:30 IST Monday) through the next 24 hours.
  - US Sunday mornings are choppy and mean-reverting.
  - The effect became stronger after mid-2020.
  - Fees, CAGR and MDD are not disclosed.
- **Quantpedia intraday/overnight study (Gemini hourly, Oct 2015 to Feb 2022)** — [Quantpedia](https://quantpedia.com/are-there-seasonal-intraday-or-overnight-anomalies-in-bitcoin/)
  - The strongest hours are 21:00-23:00 UTC (02:30-04:30 IST), when all major equity exchanges are closed.
  - Buying at 21:00 UTC and selling at 23:00 UTC returned 33% per year, with -22.45% MDD and 20.93% vol. No fees are included.
  - On NYSE days, most BTC gains accrue outside NYSE hours (15:00-21:00 UTC is the "intraday" window).
  - Paperswithbacktest also summarizes this ([summary](https://blog.paperswithbacktest.com/p/bitcoin-never-sleeps-exploiting-seasonality)).
  - This is a directional seasonality effect, not a breakout.
- **NY-open 30-minute ORB on Binance spot, 1 Jun 2025 to 1 Jun 2026** — [Secuora](https://secuora.net/strategy/opening-range-breakout)
  - Rules: range from 9:30 to 10:00 NY. Entry on the first 5-minute close outside the range between 10:00 and 12:00 NY. Stop beyond the last opposing swing. Target 2R. Flat by 12:00. Fees 0.05% per side.
  - BTC: 417 trades, 39.3% win rate, PF 0.65, -44.8% net, -45.9% MDD.
  - ETH: PF 0.80, -26.9%.
  - This is a recent and arguably out-of-sample test, from a lesser-known site.
- **Stoic Research, a subscriber's ORB adapted to crypto** — [Substack](https://stoicresearch.substack.com/p/this-orb-strategy-hit-nearly-1-sharpe)
  - Rules: range from the 14:00-15:00 UTC hour (about 19:30-20:30 IST, around the US cash open). Long or short on a 5-minute close outside the range with volume above the previous three bars. Stop at the opposite range extreme. Target 3R or trail with the 2-minute 21 EMA. Trade window 15:00-17:00 UTC.
  - BTC: CAGR 8.2%, Sharpe 0.51, MDD -17%.
  - Each coin was tested over a different short window (BTC Mar to Jun 2022), which suggests cherry-picking.
  - Fees, win rate and PF are not disclosed. Treat this as weak evidence.

### Inferences
- The US-open window (13:30-14:30 UTC, about 19:00-20:00 IST) is a natural volatility event for BTC. However, a naive ORB on it lost money after realistic fees in the one sizable independent test. Any session-ORB design needs a regime or volume filter and must be validated on our own data.
- The documented edges are about timing: momentum within high-volume sessions, the Asia/Sunday-evening open for trend, and the 21-23 UTC drift. They are not a clean "London-open breakout" effect.

### Gaps
- I found no credible published study of a London-open (about 07:00-08:00 UTC, 12:30-13:30 IST) BTC breakout.
- The clock-time results from Shen et al. are not retrieved.

## 3. Volatility breakout (Larry Williams), Bollinger/Keltner squeeze, ATR breakouts

### Takeaway
The Larry Williams volatility breakout (buy at open + k × prior range, k ≈ 0.5, exit at the session close) was a popular Korean retail strategy that worked strongly in 2019-2021 but failed in 2022-2026 after costs. Squeeze and ATR breakout evidence for BTC comes almost entirely from vendor or TradingView backtests with small samples.

### Cited Findings
- **Williams volatility breakout, independent replay on Upbit 4h data (BTC, ETH, XRP)** — [GitHub PR #1504](https://github.com/seungjae3908-source/seungjae20260713/pull/1504). This is an individual researcher's repo, so its credibility is moderate.
  - Rules: trigger = session open (09:00 KST) + 0.5 × prior session range. Long only. Exit at the next 09:00 KST. No stop and no filters.
  - Costs: 0.15% per side, plus a 1.5x cost stress test.
  - 2019-2021: BTC +199.8% CAGR. Mean PF 1.257. Mean MDD 35.8%.
  - 2022-2024: BTC -41.3% CAGR. Mean PF 1.061. Stressed mean CAGR -25.7%.
  - 2025-2026: BTC -50.1% CAGR. Mean PF 0.859. 0 of 3 coins positive.
  - The author's conclusion: "Strong early-period returns do not generalize."
- Background on the k-range rule as it was popularized for crypto: [Steemit, kangcfa](https://steemit.com/cryptocurrency/@kangcfa/quantitative-crypto-investing-9-volatility-breakout-the-best-crypto-trading-strategy-ever-invented-i); generic rules at [QuantifiedStrategies](https://www.quantifiedstrategies.com/larry-williams-volatility-strategy/).
- **BB squeeze on BTC/USDT 4h** — [Jesse BBSqueezeTrend](https://jesse.trade/strategies/bbsqueezetrend): 11 trades, 45% win rate, -8.9% MDD. The sample is too small to be meaningful.
- Vendor claims put 4h BTC squeeze results at about a 48% win rate and PF 1.61 over 85 trades, rising to PF 1.89 with an ADX filter. These come from search snippets of vendor blogs ([stratbase](https://stratbase.ai/en/blog/bollinger-bands-strategy-guide), [horizontrading](https://www.horizontrading.ai/learn/bollinger-bands-day-trading-strategy)). They were not verified; treat them as marketing.

### Inferences
- Single-day k-range breakouts are cost-sensitive. The 0.3% round trip in the Upbit test is much higher than perp taker fees of about 0.05% per side, but the edge also decayed before costs (mean PF fell below 1 in 2025-26).
- If used at all, the k-range breakout should be tested on perps with low fees, both directions, and a trend or volatility regime filter.

### Gaps
- I found no peer-reviewed or credible quant-blog study of Keltner, ATR-channel or squeeze breakouts on BTC with costs and multi-year samples.

## 4. Time-series momentum / trend-following evidence for BTC; win rates, payoffs, fees and funding

### Takeaway
Academic evidence is split. Large-sample studies with realistic costs find time-series momentum (TSMOM) in crypto "strong" (Han et al., 2013-2023), but several 2024-2026 papers find the simple weekly TSMOM effect decayed after about 2020. Breakout/trend systems on BTC have low win rates (35-50%) with large payoff ratios. They are sensitive to turnover costs, and on perpetuals to funding, which has averaged about 14% per year for longs on Binance.

### Cited Findings
- **Han, Kang and Ryu, "Time-Series and Cross-Sectional Momentum in the Cryptocurrency Market… under Realistic Assumptions"** (SSRN 4675565; sample Dec 2013 to Aug 2023) — [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4675565)
  - TSMOM evidence is strong. Cross-sectional momentum evidence is almost non-existent.
  - After transaction costs and intraperiod liquidations (daily price swings), many momentum portfolios are wiped out, and many statistically significant ones earn insignificant profits.
  - Momentum is concentrated in large winners, while losers often rebound. This matters for the short side.
- **Arefev, "Time-series Momentum in Cryptocurrency: A Published Edge that has Aged" (SSRN 7405060; 30 large-cap coins, 2016-2023)** — [SSRN](https://papers.ssrn.com/sol3/Delivery.cfm/7405060.pdf?abstractid=7405060&mirid=1)
  - Raw TSMOM is 0.90% per week over the full sample, which is not significant.
  - It is 1.74% per week before July 2020, and negative and insignificant afterwards.
  - Source: search snippet; the PDF was not read in full.
- **Rosen and Wang (SSRN 5732803; BTC 2011-2024)** — [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5732803)
  - Past-return (TSMOM) and attention predictors of BTC returns have lost explanatory power in recent years.
  - Source: search snippet.
- **Concretum (Section 1)** found the opposite for Donchian breakout plus trailing stop with vol targeting. It worked through March 2025, and its 2015-2025 Combo was significant. These are different signal designs: breakouts with stops versus plain sign-of-return.
- **Win rate and payoff:** see the Concretum trade tables in Section 1. Short lookbacks win 34-49% of trades with a 2.8 to 6.7x gain:loss ratio. The Williams breakout and ORB tests had PF near or below 1 recently.
- **Fees:** the Concretum 5d model fell from 34% to 18% CAGR at 50 bps; slower models were less affected ([PDF](https://concretumgroup.com/wp-content/uploads/2026/02/Catching-Crypto-Trends.pdf)).
- **Funding:** the average Binance BTC perp funding was about 14% per year over roughly six years, against T-bills at about 3%. That spread is about three times CME BTC futures' financing spread ([Elm Wealth](https://elmwealth.com/perpetual-futures/)). This cost hits long trend positions held over days. Shorts usually receive funding.

### Inferences
- For multi-day long holds on perps, budget roughly 0.04% per day in funding drag on average, with spikes far higher in rallies. This favors short holding periods or spot/CME for the long leg.
- Downside breakouts on perps typically earn funding, which partly offsets the weaker historical short-side performance.

### Gaps
- I found no published BTC breakout backtest that explicitly models perp funding.
- I found no CTA index dedicated to crypto trend with public performance figures. General CTA indices (SG Trend) are not crypto-specific.

## 5. Stops/exits that work and false-breakout filtering

### Takeaway
The best-documented exit is a trailing stop that only ratchets in the trade's favor, at the Donchian midline (Concretum), combined with vol-targeted sizing. Time stops (exit at the session close) are standard in the Williams and ORB variants but performed poorly recently. False-breakout filters (volume, ADX, regime) are recommended mostly by practitioners, with little rigorous evidence.

### Cited Findings
- **Donchian midline trailing stop:** max(prior stop, (n-high + n-low)/2), evaluated on the daily close and never loosened. With this stop, the worst trades for 5-60d lookbacks were only about -5% to -9% portfolio-level, while winners reached 29% to 89% ([Concretum PDF](https://concretumgroup.com/wp-content/uploads/2026/02/Catching-Crypto-Trends.pdf)).
- **Vol targeting:** size = 25% / 3-month realized vol, capped at 2x. Applying a 20% no-trade band to vol-driven rebalances cut fee drag by about 100 bps per year at 50 bps costs (same source).
- **Ensembling lookbacks** acts as a false-breakout filter: Combo MDD was 19%, against 24-34% for single lookbacks (same source).
- **ORB filters:** a volume confirmation filter (breakout bar volume above the previous three bars) plus an EMA/RSI regime filter ([Stoic Research](https://stoicresearch.substack.com/p/this-orb-strategy-hit-nearly-1-sharpe)). This evidence is weak.
- **Regime dependence:** BB mean reversion on BTC 4h had PF 1.62 when ADX < 20 and failed when ADX > 30, per a vendor snippet ([stratbase](https://stratbase.ai/en/blog/bollinger-bands-strategy-guide)). This is unverified, but it shows that breakout and reversion signals depend on the regime.
- **Time-of-week filter:** trend models do well from the Sunday-evening Asia open and are choppy on US Sunday mornings ([Concretum](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/)).

### Inferences
- A practical BTC both-ways design:
  - Use a breakout on closing prices, not intrabar touches, which reduces wick fakeouts.
  - Exit on a ratcheting midline or ATR trail rather than a fixed target.
  - Use vol-targeted sizing.
  - Ensemble 2-4 lookbacks.
  - Avoid fixed small-R targets: the edge comes from the fat right tail, with gain:loss ratios of 3 to 7x.

### Gaps
- I found no rigorous comparison of an ATR chandelier stop against a Donchian midline stop on BTC.
- I found no quantified study of volume or OI filters for false breakouts in BTC perps.
