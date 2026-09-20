"""pStrategy-Nifty: a live, persisted paper-trading engine -- NOT a
stateless replay like pStrategy/Crypto-Swing. Those work by recomputing a
trade sequence fresh from candle history on every request, which only
works because a perpetual's price history alone determines the whole
trade. An ATM option's premium can't be reconstructed after the fact
(Dhan's option chain is a live snapshot, not queryable historically), so
this instead polls continuously and persists trades as they happen (see
pstrategy_nifty_trades in sqlite.py), same shape as paper_trading.py's
existing NIFTY early-signal engine but on its own dedicated table.

Watches NIFTY spot at 1m and 3m independently for a pStrategy-style
consolidation-breakout momentum signal (same detect_patterns/
confirm_momentum geometry and EMA9/20 trend filter as pStrategy itself --
3m is built by resampling 1m bars, since Dhan's intraday endpoint has no
native "3" interval). On a fresh confirmed breakout, buys 1 lot of ATM CE
(bullish momentum) or ATM PE (bearish momentum) -- paper only, never a
real order.

Exit is whichever fires first: pStrategy's own EMA-hold/ATR-Chandelier-
trail rule (check_ema_trail_exit), evaluated against NIFTY's own price --
or a hard stop-loss on the option premium itself
(pstrategy_nifty_stop_loss_percent), since a held position can mask fast
option decay that the underlying's rule alone wouldn't catch. Force-closed
at end of day regardless.

New entries are held back until pstrategy_nifty_entry_delay_minutes after
session start (default 15) -- the opening minutes of NSE trading are
known to whipsaw, and a 1m/3m breakout is exactly the kind of fast, noisy
signal most exposed to it. Already-open positions are still managed (and
can still exit) through that window; only fresh entries wait.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time
from typing import Any

from app.core.config import Settings, get_settings
from app.core.timeutil import add_minutes, in_time_window, now_ist, now_ist_epoch
from app.db import sqlite as db
from app.services.crypto_indicators import atr as compute_atr
from app.services.crypto_indicators import ema, resample_ohlc
from app.services.dhan import DhanService
from app.services.ema5_instruments import resolve_atm_option, resolve_next_expiry
from app.services.pstrategy import ATR_LOOKBACK, check_ema_trail_exit, confirm_momentum, detect_patterns

INDEX_SEGMENT = "IDX_I"
INDEX_INSTRUMENT = "INDEX"
# Matches ema5/gamma_blast/theta/paper_trading's own convention for NIFTY
# option contracts.
OPTION_SEGMENT = "NSE_FNO"
STRIKE_STEP = 50.0
EMA_SLOW_PERIOD = 20
RESOLUTIONS = ("1m", "3m")

# In-memory freshness guard, reset daily -- resets on process restart too,
# which just means the engine may re-scan today's already-seen breakouts
# once after a restart; get_open_pstrategy_nifty_trade still prevents
# actually double-entering since an open trade blocks a new one regardless.
_handled_breakout_time: dict[str, int | None] = {r: None for r in RESOLUTIONS}
_handled_date: str | None = None


def start_pstrategy_nifty_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.pstrategy_nifty_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_pstrategy_nifty_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def _loop() -> None:
    settings = get_settings()
    interval = max(settings.pstrategy_nifty_poll_interval_seconds, 15)
    while True:
        try:
            now = now_ist()
            in_hours = in_time_window(
                now.time(), settings.pstrategy_nifty_session_start_time, settings.pstrategy_nifty_session_end_time
            )
            if in_hours and now.weekday() < 5:
                await _poll_once(settings, now)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(interval)


async def _poll_once(settings: Settings, now: datetime) -> None:
    global _handled_date
    today = now.date().isoformat()
    if _handled_date != today:
        _handled_date = today
        for r in RESOLUTIONS:
            _handled_breakout_time[r] = None

    dhan = DhanService(settings)
    now_epoch = now_ist_epoch()

    try:
        raw_1m = await dhan.intraday_candles(
            str(settings.dhan_nifty_security_id), INDEX_SEGMENT, INDEX_INSTRUMENT, "1", today, today
        )
    except Exception:
        return

    candles_1m = sorted(raw_1m, key=lambda c: c["time"])
    completed_1m = [c for c in candles_1m if c["time"] + 60 <= now_epoch]
    if len(completed_1m) < ATR_LOOKBACK + 5:
        return

    completed_3m = resample_ohlc(completed_1m, 3)

    for resolution, series in (("1m", completed_1m), ("3m", completed_3m)):
        try:
            await _evaluate_resolution(dhan, settings, resolution, series, now_epoch)
        except Exception:
            pass


async def _evaluate_resolution(
    dhan: DhanService, settings: Settings, resolution: str, candles: list[dict[str, Any]], now_epoch: int
) -> None:
    is_eod = now_ist().time() >= _parse_hhmm(settings.pstrategy_nifty_session_end_time)

    open_trade = db.get_open_pstrategy_nifty_trade(resolution)
    if open_trade:
        await _manage_open_trade(dhan, open_trade, candles, now_epoch, is_eod)
        return

    if is_eod:
        return

    entries_open_from = add_minutes(settings.pstrategy_nifty_session_start_time, settings.pstrategy_nifty_entry_delay_minutes)
    if now_ist().time() < entries_open_from:
        return

    closes = [float(c["close"]) for c in candles]
    ema_slow = ema(closes, EMA_SLOW_PERIOD)
    atr_values = compute_atr(candles, ATR_LOOKBACK)
    _, breakouts = detect_patterns(candles)
    confirmed = confirm_momentum(breakouts, candles, ema_slow, atr_values)
    if not confirmed:
        return

    latest = confirmed[-1]
    # Only a breakout within the last few candles counts as "fresh" --
    # otherwise a stale breakout from earlier today would keep re-firing
    # every poll once its own trade has already closed.
    if latest["index"] < len(candles) - 3:
        return
    breakout_time = candles[latest["index"]]["time"]
    if _handled_breakout_time[resolution] == breakout_time:
        return

    await _open_trade(dhan, settings, resolution, latest, candles)
    _handled_breakout_time[resolution] = breakout_time


async def _open_trade(
    dhan: DhanService, settings: Settings, resolution: str, breakout: dict[str, Any], candles: list[dict[str, Any]]
) -> None:
    side = "CE" if breakout["side"] == "long" else "PE"
    expiry = await resolve_next_expiry(dhan, settings.dhan_nifty_security_id)
    if not expiry:
        return
    option = await resolve_atm_option(
        dhan, underlying_scrip=settings.dhan_nifty_security_id, expiry=expiry, side=side, strike_step=STRIKE_STEP
    )
    if not option or not option.get("ltp"):
        return

    entry_underlying_price = float(candles[breakout["index"]]["close"])
    db.create_pstrategy_nifty_trade(
        resolution=resolution,
        side=side,
        strike=option["strike"],
        expiry=expiry,
        security_id=option["securityId"],
        exchange_segment=OPTION_SEGMENT,
        lots=settings.pstrategy_nifty_lots,
        lot_size=settings.pstrategy_nifty_lot_size,
        entry_time=now_ist_epoch(),
        entry_premium=option["ltp"],
        entry_underlying_price=entry_underlying_price,
        stop_loss_percent=settings.pstrategy_nifty_stop_loss_percent,
    )


async def _manage_open_trade(
    dhan: DhanService, trade: dict[str, Any], candles: list[dict[str, Any]], now_epoch: int, is_eod: bool
) -> None:
    try:
        quotes = await dhan.market_quotes_by_segment({trade["exchangeSegment"]: [int(trade["securityId"])]})
        current_premium = float(
            (quotes.get(trade["exchangeSegment"]) or {}).get(str(trade["securityId"]), {}).get("last_price") or 0
        )
    except Exception:
        return
    if not current_premium:
        return

    if is_eod:
        _close(trade, exit_time=now_epoch, exit_premium=current_premium, exit_reason="eod")
        return

    # Premium stop-loss backstop -- always checked, independent of the
    # underlying-price rule below (a held position can mask fast option
    # decay that EMA-hold on the underlying alone wouldn't catch).
    floor = trade["entryPremium"] * (1 - trade["stopLossPercent"] / 100)
    if current_premium <= floor:
        _close(trade, exit_time=now_epoch, exit_premium=current_premium, exit_reason="premium_stop_loss")
        return

    side = "long" if trade["side"] == "CE" else "short"
    latest = candles[-1]
    ema_slow_series = ema([float(c["close"]) for c in candles], EMA_SLOW_PERIOD)
    atr_series = compute_atr(candles, ATR_LOOKBACK)
    result = check_ema_trail_exit(
        side=side,
        entry_price=trade["entryUnderlyingPrice"],
        best_close=trade["bestUnderlyingClose"],
        close=float(latest["close"]),
        high=float(latest["high"]),
        low=float(latest["low"]),
        open_price=float(latest["open"]),
        ema_slow_value=ema_slow_series[-1],
        atr_value=atr_series[-1],
        trail_stop=trade["trailStopUnderlying"],
    )
    db.update_pstrategy_nifty_trade_progress(
        trade["id"],
        peak_premium=max(trade["peakPremium"] or current_premium, current_premium),
        best_underlying_close=result["bestClose"],
        trail_stop_underlying=result["trailStop"],
    )
    if result["exit"]:
        reason = "underlying_" + (result["reason"] or "exit")
        _close(trade, exit_time=now_epoch, exit_premium=current_premium, exit_reason=reason)


def _close(trade: dict[str, Any], *, exit_time: int, exit_premium: float, exit_reason: str) -> None:
    qty = trade["lots"] * trade["lotSize"]
    realized_pnl = (exit_premium - trade["entryPremium"]) * qty
    db.close_pstrategy_nifty_trade(
        trade["id"], exit_time=exit_time, exit_premium=exit_premium, exit_reason=exit_reason, realized_pnl=realized_pnl
    )


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))
