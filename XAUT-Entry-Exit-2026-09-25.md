# Simple Cross Over - XAUT: Entry/Exit Rules

Reference snapshot as of **2026-09-25**. Source of truth is always the code
(`backend/app/services/simple_crossover_xaut.py`) — this file documents what
that code does today, for quick reference. If the code changes, re-generate
this file rather than trusting it blindly.

## Instrument

- **Symbol:** `XAUTUSD` (Tether Gold perpetual) on **Delta Exchange**.
- **Market hours:** 24/7 — the engine polls continuously, no session window.
- **Candle resolution:** 1-minute closed candles for all decisions. The
  live-updating chart (`get_data()`) keeps the current still-forming candle
  for display; every trade-decision path (entries and exit checks) strips it
  (`drop_forming=True`) so a single in-flight tick can't flip a near-zero
  EMA gap and trigger a false signal.
- **"Today"** = IST calendar day, 00:00:00 IST to now (`start_of_today_ist_epoch()`
  — built from an aware datetime so it's correct regardless of the host
  server's own system timezone).

## Indicators

| Indicator | Period |
|---|---|
| EMA (fast) | 8 |
| EMA (slow) | 21 |
| RSI | 8 |
| RSI SMA (display only) | 5 |

**Day Direction**: `(current_close - day_open) / day_open * 100`, computed
from the day's own 1-minute candles (`ordered[0]["open"]` vs `ordered[-1]["close"]`).
- `>= +0.3%` → **Up**
- `<= -0.3%` → **Down**
- otherwise → **Sideways**

## Entry rules

Checked independently for **long** and **short** every poll tick (default
30s, floor 15s). One open position per side at a time — re-entry allowed
once the prior position on that side has closed.

1. **Day-direction gate** (`dayDirectionFilterEnabled`, default **ON**):
   - Up day → only **long** is evaluated.
   - Down day → only **short** is evaluated.
   - Sideways day → **no entries**, unless `tradeOnSideways` is also on
     (default **OFF**), in which case both long and short are evaluated
     independently, same as with the gate fully off.
   - Gate off entirely → both long and short evaluated every tick regardless
     of direction.

2. **Crossover detection, with lookback** — long wants an **up**-crossover
   (EMA8 crosses above EMA21), short wants a **down**-crossover. Instead of
   only checking the most recent candle pair, the engine scans the last
   **5 candles** (`RECENT_CROSSOVER_LOOKBACK_CANDLES`) for a matching,
   not-yet-acted-on crossover. This recovers from a single missed/failed
   poll without risking entry into a crossover more than ~5 minutes stale.
   Each crossover is only ever acted on once (`_handled_crossover_time`
   dedup, keyed by side + crossover candle timestamp, reset at IST
   midnight).

3. **OHLC-touch confirmation** (`touched_or_close_to_crossover`) — the
   crossover candle's own low/high range must contain the EMA21 level being
   crossed, OR its close must be within **0.5%**
   (`simple_crossover_xaut_max_gap_from_crossover_percent`) of it. Rejects a
   crossover where price already gapped/ran well past the signal level
   before the candle closed — a worse entry than the crossover itself
   implies. Logged as a rejection when it fires.

4. **Entry EMA-gap filter** (`entryGapFilterEnabled`, default **ON** for
   this engine): the current `EMA8 - EMA21` gap (not the gap at the
   crossover candle — the gap as of the latest closed candle, i.e. how much
   separation has developed since the cross) must satisfy
   `minEntryGap <= |gap| <= maxEntryGap`. **Current values: min `0.06`, max
   `0.25`.**
   - Based on this engine's own first 36 trades: gap `< 0.06` was a
     weak/barely-confirmed cross (10–13% win rate); gap `>= 0.25` was
     already-extended/chasing (10–14% win rate); the `0.06–0.15` band won
     64% of the time (see "Evidence" below). Rejected entries are logged
     with the actual gap value.

5. **Position sizing** — `quantity = marginPerTrade * leverage / entry_price`.
   **Current values: margin `$50`, leverage `50x`** (Delta allows up to 50x
   on XAUTUSD). Both are snapshotted onto the trade record at entry time, so
   a later change to these settings never retroactively changes an
   open/closed trade's numbers.

6. **Fill price** — the live ticker price at the moment of entry
   (`delta.get_ticker`), falling back to the crossover candle's own close if
   the ticker call fails.

## Exit rules

Checked every poll tick for every open position, regardless of current day
direction (direction only gates new entries — an open position always rides
to its own exit). Checked in this order, first match wins:

1. **Midnight IST square-off** — on the first tick of a new IST calendar
   day, every still-open position is force-closed at the current price,
   `exitReason = "day_boundary"`.

2. **Confirmed cross-reversal**:
   - Long exits on **cross-under** (`exitReason = "cross_under"`).
   - Short exits on **cross-over** (`exitReason = "cross_over"`).
   - Requires the reversed EMA relationship to hold for **2 consecutive
     closed candles**, not just the latest one — a single-candle flip on a
     near-zero gap was the dominant loss driver in practice (78% of all
     trades exited this way at an 18% win rate before this fix). Can only
     delay a real exit by ~1 minute; never blocks one.

3. **RSI-extreme exit** (`rsiExitEnabled`, default **ON**):
   - Long exits when RSI `>= rsiLongExitThreshold` (**currently 92**),
     `exitReason = "rsi_peak"`.
   - Short exits when RSI `<= rsiShortExitThreshold` (**currently 8**),
     `exitReason = "rsi_trough"`.

No stop-loss, no profit target — exit is purely signal-driven.

## Charges & P&L

- **Fee**: Delta Exchange's published XAUTUSD taker rate, confirmed live via
  `GET /v2/products/XAUTUSD` (`taker_commission_rate: 0.0001` = **0.01%**),
  charged on both the entry and exit legs' notional (`price * quantity`).
- **Realized P&L**: `(exit - entry) * quantity` for long, `(entry - exit) *
  quantity` for short.
- **Net P&L**: realized P&L minus total charges (entry leg + exit leg).
- **Net P&L %**: net P&L as a percentage of the trade's own margin — the
  number that actually shows whether fees are eating returns, since $ P&L
  and $ charges both scale with position size the same way (changing margin
  or leverage changes the dollar amounts but never this ratio).
- Open trades show all of the above as an estimate, as if exiting at the
  current price right now.

## Current live configuration (2026-09-25)

| Setting | Value |
|---|---|
| Day-direction filter | **ON** |
| Trade on Sideways days | **OFF** |
| RSI-extreme exit | **ON** |
| RSI long exit threshold | **92** |
| RSI short exit threshold | **8** |
| Margin per trade | **$50** |
| Leverage | **50x** |
| Entry EMA-gap filter | **ON** |
| Min entry gap | **0.06** |
| Max entry gap | **0.25** |
| Monitor enabled | **ON** (`SIMPLE_CROSSOVER_XAUT_MONITOR_ENABLED=true`) |
| Poll interval | 30s |

All of the above (except monitor enabled/poll interval, which are `.env`
settings requiring a restart) are editable live from the "Entry & exit
conditions" panel on the Simple Cross Over - XAUT page — no redeploy needed.

## Evidence behind the current defaults

From an analysis of this engine's first 36 closed trades (see chat history,
2026-09-25):
- Overall: 33% win rate, 2.3:1 win/loss ratio, net +$4.05 after $15.90 in
  charges (charges were 80% of gross profit — a direct symptom of
  over-trading, not a separate problem).
- `cross_under`/`cross_over` exits were 78% of all trades at an 18% win
  rate → fixed with the 2-candle confirmation above.
- Sideways-day trades were a net loser (-4.6% of margin across 25 trades)
  vs. Down-day trades (+8.0% across 6) → day-direction filter turned back on.
- Entry EMA-gap sweet spot: `0.06–0.15` won 64% of the time; both weaker
  (`<0.06`) and stronger/later (`>=0.25`) gaps lost → entry gap filter added.

Re-run this analysis periodically as more trades accumulate, especially to
validate or retune the `0.06`/`0.25` thresholds with a larger sample.
