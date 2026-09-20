# Delta Exchange Strategies — Current Entry/Exit Rules

*Reference note · describes the code as implemented, not a proposal*

A snapshot of exactly what `pstrategy.py` and `crypto_swing.py` do today, as of 2026‑09‑20. Both are pure, deterministic replays over Delta Exchange candle history — no DB, no persisted state, no live orders from these paths.

---

## pStrategy — XAUTUSD, 5m candles, 50x leverage

Source: `backend/app/services/pstrategy.py`, `backend/app/api/pstrategy.py`

### Entry

1. **Consolidation box** — a run of 3–30 candles where each candle's body stays ≤0.6×ATR(14) and the run's total high-low range stays ≤1.0×ATR(14). A tight, quiet stretch.
2. **Breakout candle** — the candle right after the box closes with a body >0.6×ATR(14), closing above the box's resistance (→ long) or below its support (→ short).
3. **EMA trend filter** (on by default; EMA9/EMA20, both adjustable) — the breakout close must also clear the slow EMA by **≥0.1×ATR(14)** in the trade's direction. A bare tie (close a hair past the EMA) does not count — added after a real case confirmed a long on a 0.007pt margin.
4. Entry price = that breakout candle's close. Only one position at a time; a new signal is skipped while one is still open.

### Exit — EMA filter on (default)

- Held as long as price keeps closing on the favorable side of the slow EMA.
- **ATR trailing stop**, layered on top: once up 1.0×ATR from entry, a Chandelier stop arms at (best close since entry) ∓ 3.0×ATR, ratchets only in the trade's favor, checked intrabar (low/high) → exit reason `trail_stop`.
- Otherwise, exits the moment price closes back across the slow EMA → exit reason `ema_exit`.

### Exit — EMA filter off

Plain fixed stop (opposite box boundary) vs. target (2× that risk) — whichever the candle's high/low touches first; stop wins on a same-candle tie.

### Other

- Leverage: 50x, matching Delta's XAUTUSD perpetual cap. P&L is the % return on margin at that leverage, not the raw price move.
- Charges: Delta's real 0.01%/side taker fee, shown per trade as a separate Charges column — not yet netted into the displayed P&L.

---

## Crypto-Swing — BTCUSD / ETHUSD / XAUTUSD, 5m/15m/30m/1h

Source: `backend/app/services/crypto_swing.py`

### Entry — all three must agree on the same candle close

1. **Supertrend(13, 4)** flips direction from the prior candle (down→up for long, up→down for short).
2. **EMA200** macro filter — close above it for long, below it for short.
3. **MACD(12, 26, 9)** — line, signal, *and* histogram all on the matching side of zero (all >0 for long, all <0 for short).

Entry price = that candle's close; initial stop = Supertrend's value at entry.

### Pyramiding

Fires only on one specific event: Supertrend had flipped *against* the position (see trap logic below) and then flips back in its favor. That's read as a confirmed continuation and adds one more equal-size tranche, capped at 3 total (`MAX_TRANCHES`). Ordinary pullbacks don't trigger it.

### Exit — two independent checks each candle, first to fire wins

- **ATR trailing stop** — once up 2.0×ATR from the blended (weighted-average) entry, a Chandelier stop arms at best close ∓ 1.5×ATR, ratchets only favorably, checked intrabar → exit reason `trail_stop`. These multiples are deliberately different from pStrategy's 1.0/3.0 — that pairing, tested on 30m crypto swings, gave back 62% of a real BTCUSD move and for XAUTUSD never protected any profit at all.
- **Trap-confirmed reversal** — when Supertrend flips against the position, it is *not* closed immediately; it's held as a suspected trap. The highest-volume candle during that counter-move sets a pivot level (its low for a long, high for a short). The position only closes once price closes **both** beyond that pivot **and** beyond EMA200 against it → exit reason `trap_confirmed_reversal`. If Supertrend flips back in favor before that double-break, it's read as a fake-out and becomes the pyramiding add above instead of an exit.

### Other

- No fixed target at all — purely trail/trap-managed, unlike pStrategy's fixed-2R fallback.
- Sizing: illustrative $500 notional per tranche, up to $1,500 across 3 tranches. No real orders placed from this paper-simulation path (a separate `crypto_swing_live.py` exists for real execution, gated behind explicit env flags, and is not what this document describes).

---

## Side-by-side

| | pStrategy | Crypto-Swing |
|---|---|---|
| Instrument | XAUTUSD only | BTCUSD / ETHUSD / XAUTUSD |
| Timeframe | 5m | 5m / 15m / 30m / 1h |
| Entry signal | Consolidation-box breakout | Supertrend flip |
| Trend filter | EMA9/20 (fast/slow), 0.1×ATR clearance | EMA200 |
| Momentum filter | body size vs. ATR | MACD(12,26,9), all three components |
| Trailing stop | arm 1.0×ATR, trail 3.0×ATR | arm 2.0×ATR, trail 1.5×ATR |
| Lagging-exit fallback | EMA cross (or fixed 2R target if EMA off) | trap-confirmed reversal (pivot + EMA200) |
| Pyramiding | none | up to 3 tranches, on trap-reversal only |
| Leverage / P&L basis | 50x, return on margin | 1x notional per tranche |
| Fees modeled | yes (Delta taker, 0.01%/side) | not yet |
