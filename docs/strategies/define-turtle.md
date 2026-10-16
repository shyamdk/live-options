# Define Turtle — NIFTY P&F RSI + Turtle Follow-Through

Implementation spec for the first strategy from `docs/sources/systematic-options-trading-strategy.pdf`
("Systematic Options Trading Strategy", grounded in Dushyant Thakkar's systematic income
framework / Definedge P&F methodology). Review date: 3 Oct 2026.

## 1. What the PDF says (summary)

- **Goal:** systematic, non-discretionary options income with defined risk.
- **Trade:** defined-risk credit spreads — sell ATM, buy an OTM hedge. Bullish trades
  prioritised (put credit spreads); positions carried overnight.
- **Signals:** "noiseless" Point & Figure / Renko charts built from 1-minute closes, with a
  mandatory 2-step check: a **trend filter** (e.g. P&F RSI(14) > 50) and an **entry
  trigger** (e.g. Turtle Follow-Through).
- **Exits:** 75% decay of the net premium (bullish), trend filter flipping, or the calendar
  rule (never hold within 3 days of expiry).
- **Sizing:** ₹1.5L per lot (≈₹1L pledged collateral + ₹50k cash buffer), sized on maximum
  tolerable loss rather than margin.
- **Published benchmarks** (the source's own, unverified): NIFTY P&F RSI + Turtle
  Follow-Through — avg hold 1.74 days, win rate ~36%, R:R 3.27, ~73 trades/year.

## 2. Decisions

| # | Question | Decision |
|---|---|---|
| 1 | Which strategy | **NIFTY P&F RSI(14) > 50 + Turtle Follow-Through Bullish → next-week put credit spread.** MidSelect Renko and Strike Back later. |
| 2 | Strike Back definition | Working definition below (§4.3) — not built now. |
| 3 | P&F parameters | **0.03% box, 3-box reversal**, RSI(14) on P&F column values, rolling **30 trading days** of 1-min data carried continuously across days. |
| 4 | Strikes / expiry | **Sell ATM put (spot rounded to 100), buy put 300 pts lower.** "Next-week" = the Tuesday expiry *after* the nearest one. |
| 5 | 3-day calendar rule | Close the spread when ≤ 3 calendar days to expiry **and raise an unmissable alarm** (full-screen page alarm with repeating sound + browser notification until acknowledged) **plus a Telegram message.** |
| 6 | Stop loss | **Follow the PDF — no extra hard stop.** Risk is capped by the spread: max loss = (300 − net credit) × lot size × lots. |
| 7 | Trend flip | Exit when P&F RSI(14) drops **below 50**, evaluated on the **1-minute close**. |
| 8 | Sizing / mode | Lots = floor(capital ÷ ₹1.5L) (₹10L → 6 lots). **Paper first**; live later behind a server switch. |
| 9 | Backtest | Not required. |

## 3. Point & Figure construction

- Input: NIFTY 50 index **1-minute closes** (Dhan intraday), oldest → newest, carried across
  sessions (overnight gaps create boxes like any other move).
- **Box size 0.03%, logarithmic** (percentage) boxes: level *n* spans
  `base × 1.0003^n … base × 1.0003^(n+1)` (≈ 7 points at NIFTY 22,400).
- **3-box reversal:** an X column extends while closes reach new box highs; it reverses to an
  O column only when a close falls ≥ 3 boxes below the column top (and vice versa).
- Each column records: type (X/O), top box, bottom box, start/end time.
- **P&F RSI(14):** Wilder RSI over the sequence of column end values (top of an X column,
  bottom of an O column); the forming column uses its current end value.

## 4. Patterns

### 4.1 Bullish Turtle Breakout
An X column whose top rises above the highest top of the **previous 5 columns**
([Definedge](https://www.definedgesecurities.com/library/turtle-breakout-bullish-point-and-figure/)).

### 4.2 Turtle Follow-Through Bullish (entry trigger)
A **Double Top Buy immediately after a Bullish Turtle Breakout**: the X column after the
breakout column (separated by one O column) rises **above the breakout column's top**.
The signal fires on the 1-minute close that prints that box.

### 4.3 Strike Back Bullish (working definition, not built yet)
The PDF calls it a "Bear Trap Pullback pattern". Exact Definedge rules are not published, so:
1. **Bear Trap** — an O column breaks below the previous O column (Double Bottom Sell),
   immediately followed by an X column breaking above the previous X column (Double Top Buy).
2. **Pullback** — the next O column holds above the trap's low (higher low).
3. **Strike Back** — the following X column breaks above the trap X column's top; signal on
   that box. Filter in the PDF: Triple MA (10, 15, 20) rising order.

## 5. Trade rules

**Entry** (once per signal, only when no spread is open, market hours only):
- Trend filter: P&F RSI(14) > 50 at the signal.
- Trigger: Turtle Follow-Through Bullish printed on the latest 1-minute close (signals older
  than 2 minutes are ignored, so a restart never trades a stale signal).
- Expiry: next-week NIFTY expiry; skipped if it is ≤ 3 calendar days away.
- Legs: SELL ATM put (spot rounded to 100), BUY put 300 lower. Lots = floor(capital ÷ 1.5L).
- Paper fills: sell at bid, buy at ask (LTP if no quote).

**Exit** (first to happen, checked on every 1-minute close in market hours):
1. **Profit:** decay ≥ 75% — (entry net credit − current cost to close) ÷ entry net credit.
2. **Trend flip:** P&F RSI(14) < 50.
3. **Calendar:** ≤ 3 calendar days to expiry → close + alarm + Telegram.

No other stop (decision 6). Every entry/exit is also sent to Telegram.

## 6. Out of scope for now

Bearish call spreads (40–50% booking), Bank Nifty / Sensex / MidSelect, Renko strategies,
Strike Back, live orders, backtesting.
