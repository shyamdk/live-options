# Archived strategies

Archived 2026-09-24: Crypto-Swing, pStrategy, Nifty-Swing, pStrategy-Nifty, PE-CE Crossover.

Archived 2026-10-02: Simple Cross Over - XAUT (`backend/app/{api,services}/simple_crossover_xaut.py`, `frontend/app/simple-crossover-xaut/`, `frontend/types/simple-crossover-xaut.ts`). Same treatment: page, route, nav entry and background monitor removed; the `simple_crossover_xaut_*` DB tables, `simple_crossover_xaut_*` config settings and the `SIMPLE_CROSSOVER_XAUT_MONITOR_ENABLED` `.env` flag were left in place (dormant). Its `lib/api.ts` helpers were deleted. It still imports `detect_crossovers`, `gap_series`, `gap_trend`, `sma` and the XAUT-only `touched_or_close_to_crossover` from the **active** `backend/app/services/simple_crossover.py` (kept there on purpose so this can move back as-is) and `DeltaExchangeService` from the shared `delta_exchange.py`. The NIFTY Simple Cross Over strategy is unaffected.

Removed from the active app entirely — no page, no route, no nav entry, no background monitor. Not deleted: full working source is here, mirroring the original `backend`/`frontend` tree so it can be moved back with the same relative paths if any of it is reused or reactivated. Database tables and `config.py` settings for these strategies were left in place (dormant) in the active app — historical paper-trade data wasn't touched.

pStrategy-Nifty and PE-CE Crossover both had live background monitors polling Dhan and logging paper trades in production at the time of archiving (`PSTRATEGY_NIFTY_MONITOR_ENABLED=true`, `PE_CE_CROSSOVER_MONITOR_ENABLED=true`); both stopped the moment `main.py` no longer starts their tasks. The `.env` flags themselves were left as-is (harmless no-ops now).

## What's here

- `backend/app/services/`, `backend/app/api/` — service + router files for each strategy.
- `frontend/app/`, `frontend/types/` — pages + type files for each strategy.

## Two units that must move back together, not independently

Confirmed by dependency audit at archive time — these have real cross-imports:

- **Crypto-Swing + Nifty-Swing**: `nifty_swing.py` imports `IndicatorBundle` from `crypto_swing.py`; `nifty_swing_live.py`/`api/nifty_swing.py` import `simulate_trades` from `crypto_swing.py` and `start_of_today_ist_epoch` from `crypto_swing_live.py`.
- **pStrategy + pStrategy-Nifty**: `pstrategy_nifty.py` imports `ATR_LOOKBACK, RSI_PERIOD, check_ema_trail_exit, confirm_momentum, detect_patterns` from `pstrategy.py`.

PE-CE Crossover (`pe_ce_crossover.py` + `pe_ce_backtest.py` + `pe_ce_expiry.py` + `pe_ce_filters.py` + `pe_ce_metrics.py`) is self-contained relative to the other 4.

`frontend/app/nifty-swing/page.tsx` imports a `CryptoSwingTrailSettings` interface that used to live in the active app's `lib/api.ts` — that export was deleted from `lib/api.ts` when this was archived (nothing else there used it). If Nifty-Swing comes back, redefine that interface locally in its own file rather than expecting it from `lib/api.ts`.

## `pstrategy.py` here includes unfinished, untested hard-stop work

`backend/app/services/pstrategy.py` in this archive is **not** identical to what was last deployed. It carries a paused, half-finished guardrail (`check_ema_trail_exit`'s new `hard_stop` parameter, wired through `build_paper_trades`) that was being built in response to a real -11.66% XAUTUSD loss where the ATR trailing stop hadn't armed yet when a reversal hit — the idea is an entry-time invalidation level active from the first tick, independent of the trail. Work was explicitly paused mid-build and never verified or deployed; it's kept here only because it's relevant if pStrategy is ever revived, not because it's ready to use. `pstrategy_nifty.py` (also archived, shares this file) is unaffected either way — `hard_stop` defaults to `None`.

## Deliberately kept in the active app, not moved here

Two files that the dependency audit found were technically only used by this group of 5, but were kept live on purpose because the next planned strategy (an EMA8/21 crossover on NIFTY) will need them:

- `backend/app/services/crypto_indicators.py` — generic ema/rsi/macd/atr/supertrend/adx math, no strategy-specific logic.
- `frontend/components/DailyTotals.tsx` (`DailyTotalsTable`/`groupDailyTotals`) — generic day-wise P&L grouping table.

Everything else these 5 strategies depend on (`dhan.py`, `dhan_scrip_master.py`, `ema5_instruments.py`, `orders.py`, `charges.py`, `telegram.py`, `delta_exchange.py`) is genuinely shared infrastructure still used by other active strategies (theta, credit_spread, animesh, gamma_blast, ema5, market) and was never moved.

## Reusable reference for the next build (nifty 8/21 EMA)

If rebuilding an EMA8/21-crossover strategy on NIFTY, **`pe_ce_crossover.py`** is the closest prior art in this archive: a live-polling engine doing exactly that crossover (on option premium, not the underlying), with guardrails (capital/daily-loss/cooldown/position-mode caps), a signal log for auditability, optional/toggleable filters, and a shadow/live broker-order integration pattern (`_place_order`, `_reconcile_positions` position reconciliation, mode-scoped trade tracking) worth reusing rather than rebuilding from scratch.
