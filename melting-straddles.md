# Melting Straddles — intraday NIFTY / Sensex straddle decay (paper)

Spec from `mastering_intraday_options_straddles_algo_spec.docx` ("Mastering Intraday Options
Straddles", Dr. Subhendu Ganguly's ATM straddle-decay method). Review date: 7 Oct 2026.

## 1. What the document says

Sell intraday straddles only on DTE 2–0 days, using three straddles fixed at the open (ATM and
±200 NIFTY / ±500 Sensex). Signals come from a Point & Figure chart of each straddle's combined
premium (CE + PE) on 1-minute data, with VWAP of the combined premium: sell only below VWAP on a
P&F sell pattern. Hard stop 10 pts NIFTY / 30 Sensex, exit on a VWAP cross, book 25% at every
10 / 20 / 30 pts of decay while trailing the stop, runner out at reversal / VWAP / 14:00.
Capital in two 50% tranches; ₹2–2.5L per lot. Claimed: 10 pts/day NIFTY, 30 pts/day Sensex.

Review notes: the return figures are internally inconsistent (10 pts/day × 3 days ≠ 50 pts/wk),
no P&L/drawdown/cost statistics are given, the box size is ambiguous (0.05% gives 130–190 columns
a day — noise), the stops are ~3–4% of premium (inside 1-min noise), and costs/slippage are ~10%
of the 10-pt target. A 6-day sanity check on live data (5–7 Oct 2026) lost on the one true
strategy day (Sensex DTE1, 7 Oct: −31 to −81 pts across variants while the ATM straddle decayed
118 pts); most losers were VWAP-cross exits within 1–3 minutes of entry.

## 2. Decisions

| # | Topic | Rule used |
|---|---|---|
| 1 | Instruments / calendar | **NIFTY on Fri, Mon, Tue** (Tuesday weekly expiry). **Sensex on Wed, Thu** (Thursday weekly expiry). The other index is ignored that day. |
| 2 | Straddles | From the index's first 1-min open (09:15): ATM = nearest 100 (NIFTY) / 500 (Sensex); Lower = ATM − 200 / −500; Higher = ATM + 200 / +500. Fixed for the day. |
| 3 | P&F chart | Combined premium CE + PE on **1-min closes, 0.5% logarithmic box, 3-box reversal** (setting). |
| 4 | VWAP | **VWAP(CE) + VWAP(PE)**, each cumulative from 09:15 on typical price × volume. |
| 5 | Sell patterns | Fire on the 1-min close that prints the box: **Double Bottom Sell** (O column below the previous O column's low); **Turtle Sell** (O column below the lows of the previous 5 columns); **Anchor Follow-Through** (O column breaks below an earlier O column at least 2× the day's median column height); **High Pole Follow-Through** (an X column at least 2× the median height, then the next O column retraces more than 50% of it). |
| 6 | Entry | Pattern fires **and** premium < VWAP **and** VWAP − premium ≤ hard stop (proximity). Window **09:30–13:45**. |
| 7 | Sizing (paper) | **4 lots per straddle** (so 25% = 1 lot). **Max 2 straddles open** (tranche A, tranche B), whichever signals first; one position per straddle at a time. |
| 8 | Stop | Hard stop entry + **10 pts NIFTY / 30 pts Sensex** on combined premium. **VWAP exit:** 1-min close of combined premium ≥ VWAP closes the straddle. |
| 9 | Profit booking | At **+10 / +20 / +30** decay (Sensex +30 / +60 / +90): buy back 1 lot each; trail the stop to cost / +10 / +20 (Sensex cost / +30 / +60). The last lot runs until a P&F X-column reversal (3 boxes), VWAP cross or 14:00. |
| 10 | Time exit | **Everything flat at 14:00 every day.** |
| 11 | Daily brakes | No new entries after **3 stop-outs** or a day's net loss of **20 pts NIFTY / 60 pts Sensex** (per lot equivalent). |
| 12 | Index context | Camarilla (S3/S4/R3/R4/R5), previous day high/low, index VWAP, Supertrend — **display only**. |
| 13 | Mode | **Paper.** Sell at bid, buy at ask (LTP if no quote), app charge model. Telegram on every entry, partial and exit. |
| 14 | Backtest | **Before building**: 3–6 months of real DTE 0–2 days from Dhan's expired-options 1-min data, to settle box size and the VWAP exit. |

## 3. Backtest (1 Apr – 7 Oct 2026, real 1-min data, 4 lots per straddle)

Dhan expired-options 1-min data (ATM±10 rolling strikes rebuilt into the day's fixed straddles),
81 NIFTY days (DTE 0–2) and 54 Sensex days (DTE 0–1). All rules above, 1 pt (NIFTY) / 3 pts
(Sensex) slippage per round trip, app charge model.

| Variant | NIFTY net | NIFTY pts/day | Sensex net | Sensex pts/day |
|---|---|---|---|---|
| **0.5% box, VWAP exit on close (as built)** | −₹25,893 | +2.8 | −₹59,381 | −0.4 |
| 0.5% box, VWAP exit on P&F value | −₹10,896 | +3.4 | −₹39,860 | +3.9 |
| 0.5% box, no VWAP exit | +₹47,830 | +5.8 | −₹16,094 | +7.6 |
| 0.25% box, no VWAP exit | +₹94,518 | +8.7 | −₹81,397 | −7.3 |
| 1.0% box, VWAP exit on close | −₹2,168 | +2.2 | −₹66,476 | −5.9 |

Charges are ₹48k–111k per index over the period, larger than the gross edge in most variants.
No variant reaches the document's 10 pts/day; Sensex loses in every variant. Picking the best
of nine variants on the same data is in-sample, so paper trading decides before going live.
