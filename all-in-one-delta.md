# All-in-One Delta — Strategy Note

*Strategy note · reverse-engineered from a mirrored copy-trading feed, not yet implemented*

A reconstruction of the "All-in-One Delta" strategy on mirrorpip.com (1,709 followers, 63% claimed win rate, 726 days live, 24.8% max drawdown) — built from one export of trades it actually mirrored into a live Delta Exchange account, not from any published rulebook. Treat everything below as an approximation, not a spec: we only have fills, never the signal source.

**Export read:** 2026‑09‑12 → 2026‑09‑20, 117 legs across options, crypto perpetuals, gold/silver, and Delta's tokenized US stocks.

---

## 01 — The evidence

### It's not one strategy — it's three sleeves bolted together

| Sleeve | n | Win% | P&L | Verdict |
|---|---:|---:|---:|---|
| Short options (XAUT/BTC/ETH) | 34 | 62.8%* | **+$99.14** | the actual engine |
| Tokenized stocks (long) | 26 | 96.2% | +$51.23 | trend-following, easy hit rate |
| Metals spot/perp (XAUT/PAXG/SLV) | 16 | 75.0% | +$48.05 | trend-following, same family |
| Crypto perps (BTC/ETH/alts, directional) | 32 | 46.9% | **‑$54.96** | net drag, the drawdown source |
| Stray option longs (expired residuals) | 9 | — | ‑$8.41 | not a real strategy leg — see below |

\* win% for the *short* options only; the export's 9 `buy`-side option legs are all worthless-expiry writeoffs (e.g. `P-ETH-2320` bought at 7, expired at 0), not a deliberate long-options play.

**The whole fund's profit is the options-selling sleeve.** +$99.14 of the +$135.04 total came from selling premium; the trend sleeves in stocks and metals add a smaller, steadier contribution; the crypto perpetual directional book is a net loser in this sample and is where the drawdown lives.

### Sleeve 1 — the theta engine: sell very-short-dated, near-the-money options

Measuring each option short against the underlying's spot price at the moment it was sold:

| Underlying | n | Avg \|%OTM\| | Avg days-to-expiry | P&L |
|---|---:|---:|---:|---:|
| XAUT | 23 | **0.39%** | 0.17d | +$32.13 |
| BTC | 6 | 0.46% | 0.56d | +$29.32 |
| ETH | 5 | 2.70% | 0.97d | +$37.69 |
| **All** | **34** | **0.74%** | **0.36d** | +$99.14 |

This is **0DTE/1DTE, near-ATM premium selling** — several strikes were sold literally at the money (XAUT calls/puts at ±0.02%–0.08% OTM, same expiry day). For comparison, your own Theta Book on NIFTY/SENSEX weeklies runs 0.35%–2.4% OTM with a hard floor at 0.35% because that's exactly where a real loss happened. This strategy routinely sells *inside* where Theta Book stops. It survives on raw speed of decay (same-day expiry) rather than distance — high theta, high gamma, no visible stop-loss (every row has `sl=0`).

One loss stands out as the case study: `P-XAUT-4350-140926` sold at 20.1 with spot at 4352.8 (0.06% OTM, effectively ATM) and bought back at 59 for **‑$9.73** — the option nearly tripled against them intraday. That's what "no distance floor" costs when it goes wrong.

**Mechanical pattern, not strategy signal:** 14 near-duplicate fills — same symbol, same price, 0–120 seconds apart (e.g. `C-XAUT-4380-180926` three times at price 11, 26 seconds apart). Read as webhook/order-splitting noise, not 3x deliberate conviction sizing. 12 option legs close at exactly `12:00:00` or `16:00:00` — Delta's daily options-settlement windows, i.e. simple expiry, not an active exit decision.

### Sleeve 2 — long-biased trend following on stocks and metals

96.2% and 75% win rates respectively, with holds of roughly half a day to several days, and no stop-loss field populated. Reads as a simple momentum/breakout long book — conceptually close to what pStrategy already does for XAUTUSD (EMA trend filter + consolidation-breakout entries), just applied to Delta's tokenized-stock perpetuals (`TSLAXUSD`, `NVDAXUSD`, `HOODBUSD`, etc.) and extended to PAXG/SLV. The 96% hit rate over only 26 trades in a nine-day, broadly-rising window is not strong enough evidence of a repeatable edge — it's as consistent with "everything went up that week" as with a real signal.

### Sleeve 3 — crypto perpetual counter-trend book (net loser, drawdown source)

Four failed attempts to fade the BTC rally from ~76.4k to ~80.9k between Sept 17–19: short at 76,394 (stopped, ‑$14.39 / ‑$36.81 across two legs), short again at 78,032 into the continued run to 80,921 (**‑$66.46, the single worst trade in the file**), short once more at 80,623→80,921 (‑$6.87), before finally flipping long at 81,100→81,898 for +$18.35. This is a mean-reversion model getting run over by a trending market, and it lines up with the dashboard's 24.8% max drawdown figure. **This sleeve is not worth recreating as-is** — reconstructing it faithfully would just import a currently-losing counter-trend crypto model.

### What the export can't tell us

- The actual entry trigger for *when* during the day to sell a given strike, or *when* to buy a given stock/metal — we only see fills, not the signal.
- Any stop-loss or target logic — every row has `sl=0, target=0`; whatever risk control exists (if any) isn't visible in this feed.
- Position sizing formula — clip sizes are mostly fixed per instrument (XAUT/PAXG at 0.25, BTC perp at ~0.023, ETH options at 0.65) but vary for 13 of 61 symbols with no visible pattern tied to volatility or account equity. Looks like static per-instrument clips, occasionally hand-adjusted, not a formula.
- Whether the ~63%/24.8% headline numbers (726 days) hold up outside this nine-day, generally bullish window — this sample is far too short to check.

---

## 02 — Can we recreate this?

**Structurally, yes, in two of the three sleeves — as an approximation, not a clone:**

1. **Trend sleeve (stocks + metals)** — buildable today with what already exists. It's the same shape as pStrategy's EMA-trend + consolidation-breakout engine, just pointed at more instruments (tokenized stocks, PAXG, SLV). No new data source needed beyond candles Delta already serves.

2. **Options-selling sleeve** — buildable, but needs new infrastructure first: `delta_exchange.py` has no options-chain support today (no strikes, expiries, greeks, IV) — only spot/perp candles and tickers. This would need a new Delta options-chain client before any strategy logic could sit on top of it. Once that exists, the rule shape itself is simple to state (see below) — the real design questions are the distance floor and the exit discipline, since the source data shows none.

3. **Crypto counter-trend sleeve** — recommend **not** recreating this one. In this sample it's net-negative and is the whole drawdown story; cloning it would just reproduce a losing model rather than the profitable part of the strategy.

### Forward guidance, if we build sleeve 2 (options-selling)

Grounded in the measured distances above, and modeled on the distance-floor logic already validated in Theta Book:

- **Strike selection**: near-the-money, same-day or next-day expiry — XAUT ~0.3–0.5% OTM, BTC ~0.4–0.5% OTM, ETH wider at ~2.5–3% OTM (the export's only asset showing real cushion).
- **Hard floor, by analogy to Theta Book's 0.35% line**: since this feed shows *no* floor (some strikes sold at 0.02% OTM) and it produced the one clear loss (‑$9.73 on a near-ATM XAUT put), any recreation should impose a floor rather than copy the observed laxity — e.g. don't sell tighter than ~0.3% OTM on XAUT/BTC, ~1.5% on ETH, until real data says otherwise.
- **Expiry**: same-day or next-day only — this is what the data actually shows; going further out changes the risk profile entirely and isn't supported by the export.
- **Exit**: the export shows no stop-loss field populated anywhere. Recommend defining one before running real size — e.g. a premium multiple stop (buy back if cost exceeds ~2–2.5× entry, same shape as Theta Book §05) rather than inheriting "no stop" from the source.
- **Sizing**: fixed lot per instrument (mirrors what's observed) rather than attempting to reverse-engineer a formula that may not exist.

---

## 03 — Open questions

1. Is it worth building the Delta options-chain client at all just for this, or should sleeve 2 wait until there's a second use case for it (e.g. a Delta-side theta book of your own)?
2. For the trend sleeve, do you want it as a new page (à la pStrategy/Crypto-Swing) trading Delta's tokenized stocks + metals, or folded into an existing one?
3. Given sleeve 3 is a net loser here, should we skip it entirely, or is there value in building it anyway just to paper-trade and see if it's a small sample fluke versus a structurally bad model?
4. Do you want this run as **paper trades only** (like pStrategy/Crypto-Swing today) before anything touches real size, given the no-stop-loss pattern in the source data?

---

*Source: one CSV export of mirrored Delta Exchange fills, 2026‑09‑12 to 2026‑09‑20, 117 legs, cross-referenced against concurrent spot/perp prices in the same export to back out strike distance and days-to-expiry.*
