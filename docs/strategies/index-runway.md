# Index Runway (paper)

Page: `/index-runway` (Paper group). Service: `backend/app/services/index_runway.py`. Tables: `index_runway_minutes`,
`index_runway_trades`, `index_runway_settings`. Switch: `INDEX_RUNWAY_MONITOR_ENABLED` (default on). Paper only.

## The question

> Using backtesting, identify the moves where NIFTY moved 40 points within 2 minutes. Give the date, start and end
> time, start and end index value, and move points. For each occurrence give all the Greeks in the previous minute,
> and the change in all of them: if the move happened 10:02 to 10:04, give the change between 10:01 and 10:02.
> Also give the change and rate of change of OI -- cluster OI (ATM + ITM1 + OTM1, CE and PE, cumulative) and option
> chain OI (full) -- and VIX and change in VIX. Goal: derive conditions for forward testing, with 10:01 -> 10:02 as
> the trigger point, and estimate the tentative move (points) in the next 2 minutes.

## Backtest

Scripts and outputs (git-ignored, ~450 MB with caches): `backend/data/history/backtests/index_runway/`
(`load_data.py`, `backtest.py`, `analyze.py`, `make_report.py`; see its README). Shareable summary:
`docs/guides/Index-Runway-Backtest.pdf`.

Data: 2025-01-01 to 2026-10-19, 1-min NIFTY, India VIX and nearest-weekly options (ATM +-10 strikes) from the
market history store.

Definitions (bar times are bar starts, IST):
- Move: close of bar T to close of bar T+1 or T+2, |move| >= 40. Counted once. Windows touching a frozen
  (flat) index bar are skipped -- from May 2026 the stored feed often freezes in the last minutes and jumps to the close.
- Trigger window: bar T-1 -> bar T.
- Greeks: Black-Scholes on the stored IV, ATM CE and PE, strike fixed at T-1, r = 6%; theta per day, vega per
  vol point, rho per 1% rate.
- OI: cluster = ATM-1..ATM+1, wide cluster = ATM-3..ATM+3, chain = ATM+-10 (the widest stored). Strikes held fixed
  across the two minutes. Before June 2026 OI updates about every 3 minutes, so a 3-minute OI change is also kept.
- Nifty weekly expiry: Thursday until 2025-08-28, Tuesday from 2025-09-02, previous trading day on holidays
  (Diwali Muhurat 2025-10-21 is not an expiry).

Findings:
- 761 moves (374 up, 387 down) on 213 of 445 days; 0.6% of minutes are followed by a 40-pt move.
- Before a move the trigger minute shows a bigger index move (median 7.8 vs 3.5 pts), higher VIX (16.6 vs 13.4),
  faster ATM IV change (0.14 vs 0.05) and more cluster OI churn (7.2% vs 3.2% over 3 minutes).
- Rules set on 2025 and scored on 2026 hold up but stay low: |trigger| >= 15, VIX >= 14 and |ATM IV change| >= 0.15
  hit 40 pts 6.2% of the time (catches 19% of moves, about 7 signals a day). A gradient-boosted model reaches 29%
  in its top 0.1% band but catches 5% of moves.
- Direction: the trigger minute matched the move's direction 55% of the time (59% when it moved 15+ pts).
- Greek changes mostly restate the index move; IV change is the most useful option reading.

## Paper rules (defaults, editable on the page)

Every completed 1-min bar T (about 3 s after it closes): fetch the NIFTY 1-min candles, the nearest-weekly option
chain and India VIX; compute the trigger features against bar T-1 with the backtest definitions; log them; score
earlier minutes with their actual next-2-minute move.

- Signal: |trigger move| >= 15 pts AND VIX >= 14 AND |ATM IV change (CE/PE avg)| >= 0.15. Optional: 5-min range
  (sum of the last five 1-min moves) >= N. A condition set to 0 is off.
- Trade: long ATM straddle (default) or the ATM option in the trigger direction ("follow"), 1 lot, entered at the
  bar-T chain LTP, exited at the chain LTP 2 bars later; one open trade at a time; entries 09:16-15:15; anything
  still open is closed at 15:25. Charges from `option_order_charges`.
- Estimate shown with each signal (backtest of the default rule, by |trigger move|): 15-20 pts median 12 / p75 19
  (3.7% reach 40); 20-30: 13.5 / 23 (6.2%); 30-50: 17.5 / 27 (10%); 50+: 25 / 50 (31%).
- The page tracks the live hit rate of signals and of all minutes against the backtest's 6.2% and 0.6%.

Replay check: a stored day (2026-03-10) replayed through the service with a fake Dhan client matched the backtest's
trigger move and forward move exactly, and IV / Greeks / OI on every minute where both picked the same ATM strike
(4 of 373 minutes differ, where the index sat on a half-strike).

## What to watch before trusting it

- Whether the live signal hit rate stays near 6% and above the all-minute rate.
- Whether straddle P&L after charges is positive at all: a 2-minute straddle needs the move to beat theta,
  spread and about Rs 100 of charges per round trip per lot.
- LTP fills are optimistic; real fills would be at the ask on entry and the bid on exit.
