"""Paper-only trading module: watches two signals and simulates a 3-lot,
staged-exit option trade against each entry, purely for offline analysis.
Never places a real order: only reads Dhan's option chain/candles/quotes,
the same read-only footprint pcr_oi.py already has.

"signalVsPrice" is the persistence-gated upgraded engine
(oi_upgraded.get_upgraded_nifty_signal, see upgrade.md) for NIFTY, and the
older oiSkew/PCR read (pcr_oi.enrich_with_signal) for SENSEX -- the
upgrade is NIFTY-only for now. "priceBreakout" is the standalone
price-momentum breakout (paper_trading_engine.compute_breakout_events),
unchanged for both underlyings.

One open paper trade per (underlying, signal_type) at a time -- a signal
that's still active doesn't pyramid into more trades; the next entry for
that pair only opens once the previous one has fully exited.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time
from typing import Any

from app.core.config import Settings, get_settings
from app.core.timeutil import in_time_window, now_ist, now_ist_epoch
from app.db import sqlite as db
from app.services import paper_trading_engine as engine
from app.services.dhan import DhanService
from app.services.ema5_instruments import resolve_atm_option, resolve_nearest_expiry
from app.services.oi_upgraded import get_upgraded_nifty_signal
from app.services.pcr_oi import enrich_with_oi_regime, enrich_with_roc_and_confidence, enrich_with_signal

UNDERLYINGS = ("NIFTY", "SENSEX")
INDEX_SEGMENT = "IDX_I"
# Matches ema5/gamma_blast/theta's own convention for both NIFTY and SENSEX
# option contracts -- not touching that established (if oddly-named) choice.
OPTION_SEGMENT = "NSE_FNO"
STRIKE_STEP = {"NIFTY": 50.0, "SENSEX": 100.0}
CANDLE_INTERVAL_MINUTES = 1


def _security_id(settings: Settings, underlying: str) -> int:
    return settings.dhan_nifty_security_id if underlying == "NIFTY" else settings.dhan_sensex_security_id


def start_paper_trading_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.paper_trading_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_paper_trading_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def _loop() -> None:
    settings = get_settings()
    interval = max(settings.paper_trading_poll_interval_seconds, 30)
    while True:
        try:
            now = now_ist()
            in_hours = in_time_window(
                now.time(), settings.paper_trading_session_start_time, settings.paper_trading_session_end_time
            )
            if in_hours and now.weekday() < 5:
                await _poll_once(settings, now)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(interval)


async def _poll_once(settings: Settings, now: datetime) -> None:
    dhan = DhanService(settings)
    session_date = now.date().isoformat()

    for underlying in UNDERLYINGS:
        try:
            await _maybe_enter_signal_vs_price(dhan, settings, underlying, session_date)
        except Exception:
            pass
        try:
            await _maybe_enter_breakout(dhan, settings, underlying, session_date)
        except Exception:
            pass

    try:
        await _manage_open_trades(dhan, settings, now)
    except Exception:
        pass


async def _maybe_enter_signal_vs_price(dhan: DhanService, settings: Settings, underlying: str, session_date: str) -> None:
    if db.get_open_paper_trade(underlying, "signalVsPrice"):
        return
    # NIFTY's signalVsPrice entry now comes from the upgraded, persistence-
    # gated engine (upgrade.md) instead of the older oiSkew/PCR read --
    # SENSEX stays on the original pipeline since the upgrade is NIFTY-only
    # for now (no VWAP/candle confirmation wired up for SENSEX yet).
    if underlying == "NIFTY":
        enriched = await get_upgraded_nifty_signal(session_date)
        if not enriched:
            return
        signal = enriched[-1].get("signal")
    else:
        snapshots = db.get_pcr_oi_snapshots(session_date)
        points = snapshots.get(underlying, [])
        if not points:
            return
        enriched_old = enrich_with_signal(enrich_with_oi_regime(enrich_with_roc_and_confidence(points)))
        signal = enriched_old[-1].get("signal")
    if signal not in ("buyCe", "buyPe"):
        return
    side = "CE" if signal == "buyCe" else "PE"
    await _open_trade(dhan, settings, underlying, side, "signalVsPrice")


async def _maybe_enter_breakout(dhan: DhanService, settings: Settings, underlying: str, session_date: str) -> None:
    if db.get_open_paper_trade(underlying, "priceBreakout"):
        return
    now_epoch = now_ist_epoch()
    from_date = f"{session_date} 09:15:00"
    to_date = now_ist().strftime("%Y-%m-%d %H:%M:%S")
    try:
        raw = await dhan.intraday_candles(
            security_id=_security_id(settings, underlying),
            exchange_segment=INDEX_SEGMENT,
            instrument="INDEX",
            interval=str(CANDLE_INTERVAL_MINUTES),
            from_date=from_date,
            to_date=to_date,
        )
    except Exception:
        return
    completed = [c for c in raw if c["time"] + CANDLE_INTERVAL_MINUTES * 60 <= now_epoch]
    if len(completed) < engine.BREAKOUT_MIN_OBSERVATIONS + 2:
        return
    events = engine.compute_breakout_events(completed)
    if not events:
        return
    last_event = events[-1]
    # Only act if the newest candle is what triggered this -- otherwise the
    # breakout started earlier and either already has a trade (caught by
    # the guard above) or already ran its course (last event would be an
    # exit), so entering now would be acting on a stale, already-missed cue.
    if last_event["kind"] != "enter" or last_event["time"] != completed[-1]["time"]:
        return
    side = "CE" if last_event["direction"] == "bullish" else "PE"
    await _open_trade(dhan, settings, underlying, side, "priceBreakout")


async def _open_trade(dhan: DhanService, settings: Settings, underlying: str, side: str, signal_type: str) -> None:
    underlying_scrip = _security_id(settings, underlying)
    expiry = await resolve_nearest_expiry(dhan, underlying_scrip)
    if not expiry:
        return
    option = await resolve_atm_option(
        dhan, underlying_scrip=underlying_scrip, expiry=expiry, side=side, strike_step=STRIKE_STEP[underlying]
    )
    if not option or not option.get("ltp"):
        return

    cfg = db.get_paper_trading_settings()
    lots = int(cfg["niftyLots"] if underlying == "NIFTY" else cfg["sensexLots"])
    lot_size = int(cfg["niftyLotSize"] if underlying == "NIFTY" else cfg["sensexLotSize"])
    levels = engine.compute_levels(option["ltp"], cfg["stopLossPercent"], cfg["target1Percent"], cfg["target2Percent"])

    db.create_paper_trade(
        underlying=underlying,
        side=side,
        signal_type=signal_type,
        strike=option["strike"],
        expiry=expiry,
        security_id=option["securityId"],
        exchange_segment=OPTION_SEGMENT,
        entry_time=now_ist_epoch(),
        entry_premium=option["ltp"],
        lots=lots,
        lot_size=lot_size,
        stop_loss_percent=cfg["stopLossPercent"],
        target1_percent=cfg["target1Percent"],
        target2_percent=cfg["target2Percent"],
        trail_percent=cfg["trailPercent"],
        stop_loss_price=levels["stopLoss"],
        target1_price=levels["target1"],
        target2_price=levels["target2"],
    )


async def _manage_open_trades(dhan: DhanService, settings: Settings, now: datetime) -> None:
    open_trades = db.list_open_paper_trades()
    if not open_trades:
        return

    securities_by_segment: dict[str, list[int]] = {}
    for trade in open_trades:
        sid, seg = trade.get("securityId"), trade.get("exchangeSegment")
        if not sid or not seg:
            continue
        try:
            securities_by_segment.setdefault(seg, []).append(int(sid))
        except (TypeError, ValueError):
            continue
    if not securities_by_segment:
        return
    try:
        quotes = await dhan.market_quotes_by_segment(securities_by_segment)
    except Exception:
        return

    is_eod = now.time() >= _parse_hhmm(settings.paper_trading_session_end_time)
    now_epoch = now_ist_epoch()

    for trade in open_trades:
        sid, seg = trade.get("securityId"), trade.get("exchangeSegment")
        if not sid or not seg:
            continue
        quote = (quotes.get(seg) or {}).get(str(sid)) or {}
        current = _number(quote.get("last_price"))
        if current is None:
            continue

        if is_eod:
            _close_remaining(trade, current_premium=current, exit_time=now_epoch)
            continue

        action = engine.evaluate_paper_trade_tick(
            stop_loss=trade["stopLossPrice"],
            target1=trade["target1Price"],
            target2=trade["target2Price"],
            trail_percent=trade["trailPercent"],
            phase=trade["phase"],
            peak_premium=trade.get("peakPremium"),
            current_premium=current,
        )
        if action is not None:
            _apply_action(trade, action, now_epoch)


def _apply_action(trade: dict[str, Any], action: dict[str, Any], now_epoch: int) -> None:
    trade_id = trade["id"]
    lot_size = trade["lotSize"]
    act = action["action"]

    if act == "STOP_ALL":
        _record_exit(trade, lot_number=0, qty=trade["lots"] * lot_size, exit_premium=action["price"], reason="stop_loss", now_epoch=now_epoch)
        _finalize_close(trade_id, now_epoch)
    elif act == "BOOK_LOT1":
        _record_exit(trade, lot_number=1, qty=lot_size, exit_premium=action["price"], reason="target1", now_epoch=now_epoch)
        db.update_paper_trade_progress(trade_id, phase="LOT1_BOOKED", peak_premium=None, remaining_lots=trade["remainingLots"] - 1)
    elif act == "STOP_REMAINING":
        qty = (trade["lots"] - 1) * lot_size
        _record_exit(trade, lot_number=0, qty=qty, exit_premium=action["price"], reason="stop_loss", now_epoch=now_epoch)
        _finalize_close(trade_id, now_epoch)
    elif act == "BOOK_LOT2":
        _record_exit(trade, lot_number=2, qty=lot_size, exit_premium=action["price"], reason="target2", now_epoch=now_epoch)
        db.update_paper_trade_progress(trade_id, phase="LOT2_BOOKED", peak_premium=action["peak"], remaining_lots=trade["remainingLots"] - 1)
    elif act == "EXIT_LOT3":
        qty = trade["remainingLots"] * lot_size
        _record_exit(trade, lot_number=3, qty=qty, exit_premium=action["price"], reason="trail", now_epoch=now_epoch)
        _finalize_close(trade_id, now_epoch)
    elif act == "UPDATE_PEAK":
        db.update_paper_trade_progress(trade_id, phase=trade["phase"], peak_premium=action["peak"], remaining_lots=trade["remainingLots"])


def _close_remaining(trade: dict[str, Any], *, current_premium: float, exit_time: int) -> None:
    remaining = trade["remainingLots"]
    if remaining <= 0:
        return
    _record_exit(
        trade, lot_number=0, qty=remaining * trade["lotSize"], exit_premium=current_premium, reason="eod", now_epoch=exit_time
    )
    _finalize_close(trade["id"], exit_time)


def _record_exit(trade: dict[str, Any], *, lot_number: int, qty: int, exit_premium: float, reason: str, now_epoch: int) -> None:
    pnl_points = exit_premium - trade["entryPremium"]
    db.add_paper_trade_leg(
        trade["id"],
        lot_number=lot_number,
        qty=qty,
        exit_time=now_epoch,
        exit_premium=exit_premium,
        exit_reason=reason,
        pnl_points=pnl_points,
        pnl_amount=pnl_points * qty,
    )


def _finalize_close(trade_id: int, closed_at: int) -> None:
    realized = sum(leg["pnlAmount"] for leg in db.get_paper_trade_legs(trade_id))
    db.close_paper_trade(trade_id, closed_at=closed_at, realized_pnl=realized)


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
