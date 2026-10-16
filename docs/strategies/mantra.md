# Mantra - Theta Gainers — NIFTY Short Strangle (monthly + weekly), paper trading

Spec for the "Mantra - Theta Gainers" page (`/mantra-theta-gainers`), from `mantra.docx` ("Algorithmic Specification: Nifty Short
Strangle Strategy"). Review date: 6 Oct 2026. Paper trading only.

## 1. What the document says

Non-directional naked short strangle on NIFTY monthly options, entered 43–50 days to expiry,
sold at ~₹100 premium per side (≈16–20 delta). Mechanical roll-in adjustments when MTM loss
crosses steps; repeated rolls can convert it into a short straddle; hard 1:1 global stop;
sizing by the "Rule of 3" (~₹5L capital per lot, ~35% margin utilisation).

## 2. Decisions (doc rules + recommendations adopted)

| Topic | Rule used |
|---|---|
| Entry | **Monthly:** the first Monday with the monthly expiry 43–50 days away, 15:00–15:15 IST. **Weekly:** every Monday 15:00–15:15 on the next-week Tuesday expiry (≥ 7 days). Holiday Monday → Tuesday 09:20 (doc fallback). |
| Strikes | OTM CE and OTM PE whose LTP is closest to **₹100 (monthly)** / **₹40 (weekly)**. ₹40 = ₹100 × √(8/46), i.e. the same delta (~0.15–0.20) on an 8-day expiry. |
| Liquidity | Doc's "< ₹1 spread, OI > 1,00,000" doesn't fit real far-dated quotes (today: ₹9.80 / ₹4.25 spreads). Used: **spread ≤ 5% of premium and OI ≥ 1,000 lots** per leg; retried each minute in the window. |
| Target | **80% of the initial credit** (100% can't be reached before the day-before-expiry exit). |
| Global stop | MTM loss ≥ **initial credit** (1:1), fixed — not raised by roll credits. MTM includes booked P&L from rolls. |
| Roll ladder | Loss of **11% / 19% / 33% / 62% of the initial credit** (≈ the doc's ₹1.4k / 2.5k / 4.3k / 8k on ₹13k): buy back the winning leg, sell the strike on the same side whose LTP matches the losing leg (never past the losing strike). Max 4 rolls. |
| Straddle | Reaching the losing leg's strike converts to a straddle: no more rolls. **Unstable exit:** premium imbalance ≥ 3× with < 7 days (monthly) / < 2 days (weekly) to expiry. |
| Time exit | Square off at **15:15 on the trading day before expiry**. |
| Gap protocol | If NIFTY opens > 1.5% away from the previous close, no evaluation before **09:17**. |
| Sizing | Lots = capital ÷ ₹5L (₹10L → 2 lots). |
| Alerts | Telegram for every entry, roll and exit. **Stop-loss and unstable-straddle exits also raise the full-screen page alarm** (sound + notification) until acknowledged. |
| Mode | Paper: sell at bid, buy at ask (LTP if no quote), app charge model. |

## 3. Backtest (15 Sep 2025 – 1 Oct 2026, per lot, modelled prices)

Black-Scholes with ATM IV from India VIX and a moneyness skew fitted from real NIFTY chains;
0.5-pt slippage per leg per fill + charges.

| | Monthly (80%) | Monthly (100%) | Weekly (80%) |
|---|---|---|---|
| Trades | 12 | 12 | 55 |
| Win rate | 67% | 58% | 69% |
| Net / lot | +₹26,054 (+5.2% on ₹5L) | +₹30,684 (+6.1%) | **+₹88,982 (+17.8%)** |
| Max drawdown | −₹42,127 | −₹45,943 | −₹18,669 |
| Avg hold | 23.5 d | 31.6 d | 5.5 d |

Caveats: modelled premiums (no skew blow-outs, no real bid/ask), likely flattering to short
premium; no >3% gap occurred in the sample, but one would jump past the stop.
