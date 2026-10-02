# Simple Cross Over (NIFTY): Entry/Exit Rules

Reference snapshot as of **2026-09-25**. Source of truth is always the code
(`backend/app/services/simple_crossover.py`) — this file documents what that
code does today, for quick reference. If the code changes, re-generate this
file rather than trusting it blindly.

## Instrument

- **Underlying:** NIFTY. Trades the **ATM CE or PE option's own premium**
  (nearest expiry, strike rounded to the nearest 50) — not the index itself.
  There is no short side: both CE and PE positions are always a plain
  **buy-to-open, sell-to-close** on the option premium (there's no
  "short the option" mode here).
- **Market hours:** NSE session only, **09:15–15:30 IST**, weekdays
  (`now.weekday() < 5`). The engine simply doesn't poll outside this window.
- **Candle resolution:** 1-minute candles for all decisions, fetched fresh
  per poll via Dhan's intraday-candles API for "today" (a date string, not
  an epoch range — no midnight-boundary computation needed here, unlike the
  XAUT engine).

## Indicators

| Indicator | Period |
|---|---|
| EMA (fast) | 8 |
| EMA (slow) | 21 |
| RSI | 8 |
| RSI SMA (display only) | 5 |

**Day Direction**: computed from the **NIFTY index's own** 1-minute candles
(not the option premium) — `(current_close - day_open) / day_open * 100`.
- `>= +0.3%` → **Up**
- `<= -0.3%` → **Down**
- otherwise → **Sideways**

This intentionally does **not** use OI Upgraded's `regime` field — that's a
point-in-time sanity check, not a day-level read, and flickered between
Sideways/trending within a clearly one-directional day.

## Entry rules

Checked independently for **CE** and **PE** every poll tick (default 30s,
floor 15s), only inside the NSE session window. One open position per side
at a time — re-entry allowed once the prior position on that side has
closed.

1. **Day-direction gate** (`dayDirectionFilterEnabled`, default **ON**):
   - Up day → only **CE** is evaluated.
   - Down day → only **PE** is evaluated.
   - Sideways day → **no entries**, unless `tradeOnSideways` is also on
     (default **OFF**), in which case both CE and PE are evaluated
     independently, same as with the gate fully off.
   - Gate off entirely → both CE and PE evaluated every tick regardless of
     direction.

2. **Crossover detection, with lookback** — entry is **always** on an
   **up**-crossover of the option's own premium (EMA8 crosses above EMA21)
   for both CE and PE — there's no down-crossover entry, since both sides
   are always a long-premium buy. Instead of only checking the most recent
   candle pair, the engine scans the last **5 candles**
   (`RECENT_CROSSOVER_LOOKBACK_CANDLES`) for a not-yet-acted-on up-crossover,
   recovering from a single missed/failed poll without risking entry into a
   crossover more than ~5 minutes stale. Each crossover is only ever acted
   on once (`_handled_crossover_time` dedup, keyed by side + crossover
   candle timestamp, reset daily).

3. **OHLC-touch confirmation** (`touched_or_close_to_crossover`) — the
   crossover candle's own low/high range must contain the EMA21 level being
   crossed, OR its close must be within **0.5%**
   (`simple_crossover_max_gap_from_crossover_percent`) of it. Rejects a
   crossover where the premium already gapped/ran well past the signal
   level before the candle closed. Logged as a rejection when it fires.

4. **Entry EMA-gap filter** (`entryGapFilterEnabled`, default **OFF** — see
   below): the current `EMA8 - EMA21` gap (as of the latest closed candle)
   must satisfy `minEntryGap <= |gap| <= maxEntryGap`. **Current values:
   min `0.06`, max `0.25`** (carried over as a starting point from the
   XAUT engine's own analysis — see that engine's reference doc). Off by
   default here because there's no NIFTY-specific trade history yet to
   validate these particular thresholds against this instrument (as of this
   date, this engine has **zero** closed trades). Enable and tune once
   enough trades accumulate.

5. **Lot sizing** — `lots` from `simple_crossover_lots` (**currently 1**),
   `lotSize` resolved per-instrument from the Dhan scrip master.

6. **Fill price** — the ATM option's live LTP at the moment of entry.

## Exit rules

Checked every poll tick for every open position, regardless of current day
direction (direction only gates new entries — an open position always rides
to its own exit). Checked in this order, first match wins:

1. **End of session** — on the first tick at/after 15:30 IST, every
   still-open position is force-closed at the current premium,
   `exitReason = "eod"`. This is an addition beyond the original spec: every
   other live engine in this codebase has a mandatory EOD close, since
   carrying an options position overnight unmanaged would be a bug, not a
   feature.

2. **Confirmed cross-under** (`exitReason = "cross_under"`) — both CE and PE
   exit the same way (there's no cross-over exit here, mirroring entry only
   ever being an up-crossover). Requires the reversed EMA relationship
   (`EMA8 < EMA21`) to hold for **2 consecutive closed candles**, not just
   the latest one — same fix applied to the XAUT engine after its own trade
   history showed single-candle flips were the dominant loss driver there;
   applied here proactively since it's the identical crossover logic. Can
   only delay a real exit by ~1 minute; never blocks one.

3. **RSI-extreme exit** (`rsiExitEnabled`, default **ON**):
   - CE exits when its own premium's RSI `>= rsiCeExitThreshold` (**currently
     92**), `exitReason = "rsi_peak"`.
   - PE exits when its own premium's RSI `<= rsiPeExitThreshold` (**currently
     8**), `exitReason = "rsi_trough"`.

No stop-loss, no profit target — exit is purely signal-driven.

## Charges & P&L

- **Fee model**: real NSE options charges (same model used for live trades
  elsewhere in this codebase) — brokerage (₹20/order), STT (0.1% on the sell
  leg), stamp duty (0.003% on the buy leg), SEBI turnover charge, IPFT, NSE
  transaction charge, and 18% GST on brokerage + transaction + SEBI + IPFT.
  Applied to both the buy-to-open and sell-to-close legs.
- **Realized P&L**: `(exit_premium - entry_premium) * lots * lotSize`.
- **Net P&L**: realized P&L minus total charges (entry leg + exit leg).
- Open trades show all of the above as an estimate, as if exiting at the
  current premium right now.

## Current live configuration (2026-09-25)

| Setting | Value |
|---|---|
| Day-direction filter | **ON** |
| Trade on Sideways days | **OFF** |
| RSI-extreme exit | **ON** |
| RSI CE exit threshold | **92** |
| RSI PE exit threshold | **8** |
| Entry EMA-gap filter | **OFF** |
| Min entry gap | **0.06** (inactive until enabled) |
| Max entry gap | **0.25** (inactive until enabled) |
| Lots | **1** |
| Monitor enabled | **ON** (`SIMPLE_CROSSOVER_MONITOR_ENABLED=true`) |
| Poll interval | 30s |
| Session window | 09:15–15:30 IST, weekdays |

All of the above (except monitor enabled/poll interval/session window,
which are `.env` settings requiring a restart) are editable live from the
"Entry & exit conditions" panel on the Simple Cross Over page — no redeploy
needed.

## Relationship to the XAUT engine

This engine and Simple Cross Over - XAUT
(`simple_crossover_xaut.py`) share the same core crossover/lookback/touch-
filter/entry-gap-filter logic (several functions — `detect_crossovers`,
`touched_or_close_to_crossover`, `sma`, `gap_series`, `gap_trend` — are
defined once here and imported by the XAUT engine). The genuine differences:
XAUT trades the instrument itself (long/short both directions) and runs
24/7 with an IST-midnight square-off, while this engine only ever buys an
option premium (never shorts) and only runs during NSE hours with an EOD
close. Since XAUT accumulated real trade history first, its entry-gap
filter is on with tuned thresholds; this engine's is off until its own
trade history can validate (or correct) the same thresholds.
