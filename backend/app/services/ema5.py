"""ema5 orchestration: daily session lifecycle, candle-close signal detection,
live-tick SL/target/trailing monitoring, and the only code path that ever
places an order (paper simulation or real Dhan order) — always behind
approve_ema5_signal, mirroring gamma_blast.py's manual-approval pattern:
paper auto-approves when EMA5_PAPER_AUTO_APPROVE is on, live always waits
for the API-triggered manual click.

Trade management is index-price-driven (see ema5_engine.py docstring): the
live WebSocket feed (NIFTY spot only, Quote mode) drives SL/target/trailing
checks every tick; the periodic REST candle poll drives alert-candle/entry
detection and the trailing ratchet's candle-close reference.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from datetime import time as dt_time
from typing import Any

from app.core.config import Settings, get_settings
from app.core.timeutil import in_time_window, now_ist
from app.db import ema5 as db
from app.services.dhan import DhanService
from app.services.dhan_ws import DhanWsClient
from app.services.ema5_candles import fetch_today_candles
from app.services.ema5_engine import (
    compute_ema,
    compute_initial_sl,
    compute_levels,
    evaluate_trade_tick,
    filter_completed_candles,
    scan_for_signal,
)
from app.services.ema5_instruments import resolve_atm_option, resolve_nearest_expiry
from app.services.orders import DhanOrderService
from app.services.telegram import TelegramNotifier

SIDES = ("PE", "CE")
EXCHANGE_SEGMENT = "NSE_FNO"
INDEX_SEGMENT = "IDX_I"

_active: dict[str, Any] | None = None
_last_alert_at: dict[str, float] = {}


def start_ema5_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.ema5_monitor_enabled:
        return None
    return asyncio.create_task(_scheduler_loop())


async def stop_ema5_task(task: asyncio.Task | None) -> None:
    if _active is not None:
        await _end_session()
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def _scheduler_loop() -> None:
    settings = get_settings()
    interval = max(settings.ema5_evaluation_interval_seconds, 1)
    while True:
        try:
            await _tick(settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(interval)


async def _tick(settings: Settings) -> None:
    now = now_ist()
    in_hours = in_time_window(now.time(), settings.ema5_session_start_time, settings.ema5_session_end_time)
    is_weekday = now.weekday() < 5

    if _active is None and in_hours and is_weekday:
        await _start_session(settings, now)
        return

    if _active is not None and not in_hours:
        await _end_session()
        return

    if _active is not None:
        await _evaluate_tick(settings, now)


async def _start_session(settings: Settings, now: datetime) -> None:
    global _active
    session_id = now.date().isoformat()
    db.upsert_session(session_id, session_date=session_id, mode=settings.ema5_mode, status="RUNNING")
    db.record_event(session_id, "SESSION_START", f"ema5 session started, mode {settings.ema5_mode}")

    ws_client = DhanWsClient()
    ws_client.start(settings, [], [(INDEX_SEGMENT, str(settings.dhan_nifty_security_id))])

    _active = {
        "sessionId": session_id,
        "wsClient": ws_client,
        "sides": {
            "PE": {"alertCandle": None, "lastEntryCandleTime": None, "lastCandlePollAt": 0.0, "candles": [], "ema": []},
            "CE": {"alertCandle": None, "lastEntryCandleTime": None, "lastCandlePollAt": 0.0, "candles": [], "ema": []},
        },
    }


async def _end_session() -> None:
    global _active
    if not _active:
        return
    session_id = _active["sessionId"]
    await _active["wsClient"].stop()
    db.upsert_session(session_id, session_date=session_id, mode=get_settings().ema5_mode, status="COMPLETED")
    db.record_event(session_id, "SESSION_END", "ema5 session ended")
    _active = None


async def _evaluate_tick(settings: Settings, now: datetime) -> None:
    session_id = _active["sessionId"]
    ws_client = _active["wsClient"]
    spot_state = ws_client.get_state(str(settings.dhan_nifty_security_id))
    spot = spot_state["ltp"] if spot_state else None

    for side in SIDES:
        await _maybe_refresh_candles(settings, side, now)
        await _maybe_raise_entry_signal(settings, session_id, side, now)
        if spot is not None:
            await _evaluate_open_trade(settings, session_id, side, spot, now)


async def _maybe_refresh_candles(settings: Settings, side: str, now: datetime) -> None:
    side_state = _active["sides"][side]
    if time.monotonic() - side_state["lastCandlePollAt"] < settings.ema5_candle_poll_interval_seconds:
        return
    side_state["lastCandlePollAt"] = time.monotonic()
    interval = settings.ema5_pe_interval_minutes if side == "PE" else settings.ema5_ce_interval_minutes
    try:
        dhan = DhanService(settings)
        raw_candles = await fetch_today_candles(
            dhan, str(settings.dhan_nifty_security_id), str(interval), settings.ema5_session_start_time
        )
        completed = filter_completed_candles(raw_candles, interval, int(now.timestamp()))
        side_state["candles"] = completed
        side_state["ema"] = compute_ema([c.close for c in completed], period=settings.ema5_ema_period)
    except Exception:
        pass


async def _maybe_raise_entry_signal(settings: Settings, session_id: str, side: str, now: datetime) -> None:
    side_state = _active["sides"][side]
    candles = side_state["candles"]
    emas = side_state["ema"]
    if len(candles) < settings.ema5_ema_period:
        return

    entry_window_ok = in_time_window(now.time(), settings.ema5_session_start_time, settings.ema5_force_exit_time)
    scan = scan_for_signal(candles, emas, side)
    side_state["alertCandle"] = scan["alertCandle"]
    entry_candle = scan["entryCandle"]
    if entry_candle is None or not entry_window_ok:
        return
    if side_state["lastEntryCandleTime"] == entry_candle.time:
        return
    side_state["lastEntryCandleTime"] = entry_candle.time

    session = db.get_session(session_id)
    halted = session["peHalted"] if side == "PE" else session["ceHalted"]
    trades_count = session["peTradesCount"] if side == "PE" else session["ceTradesCount"]
    if halted:
        db.record_event(session_id, "ENTRY_SKIPPED", f"{side} entry skipped: side halted after consecutive SLs")
        return
    if trades_count >= settings.ema5_max_trades_per_day_per_side:
        db.record_event(session_id, "ENTRY_SKIPPED", f"{side} entry skipped: max trades/day reached")
        return
    if any(t["side"] == side for t in db.get_open_trades(session_id)):
        return

    triggered_alert = scan["triggeredAlertCandle"]
    if triggered_alert is None:
        return
    entry_level = triggered_alert.low if side == "PE" else triggered_alert.high
    initial_sl = compute_initial_sl(triggered_alert, side, settings.ema5_min_sl_points)
    levels = compute_levels(entry_level, initial_sl, side)

    try:
        dhan = DhanService(settings)
        expiry = await resolve_nearest_expiry(dhan, settings.dhan_nifty_security_id)
        option = (
            await resolve_atm_option(
                dhan,
                underlying_scrip=settings.dhan_nifty_security_id,
                expiry=expiry,
                side=side,
                strike_step=settings.ema5_strike_step,
            )
            if expiry
            else None
        )
    except Exception:
        option = None
    if not option:
        db.record_event(session_id, "ENTRY_SKIPPED", f"{side} entry skipped: could not resolve ATM option")
        return

    signal_id = db.record_signal(
        session_id,
        side=side,
        kind="ENTRY",
        status="PENDING",
        strike=option["strike"],
        index_level=entry_level,
        payload={
            "securityId": option["securityId"],
            "strike": option["strike"],
            "estimatedPremium": option["ltp"],
            "entryIndexLevel": entry_level,
            "initialSl": initial_sl,
            "target1": levels["target1"],
            "target2": levels["target2"],
            "target3": levels["target3"],
        },
    )
    db.record_event(
        session_id,
        "ENTRY_SIGNAL",
        f"{side} entry signal: index {entry_level:g}, SL {initial_sl:g}, ATM {option['strike']:g} — signal #{signal_id}",
    )
    await _alert_and_maybe_auto_approve(settings, session_id, signal_id, "entry")


async def _evaluate_open_trade(settings: Settings, session_id: str, side: str, spot: float, now: datetime) -> None:
    trades = [t for t in db.get_open_trades(session_id) if t["side"] == side]
    if not trades:
        return
    trade = trades[0]

    if now.time() >= _parse_hhmm(settings.ema5_force_exit_time):
        await _raise_exit_signal(settings, session_id, trade, action="FORCE_EXIT", price=spot)
        return

    side_state = _active["sides"][side]
    candles = side_state["candles"]
    latest_completed = candles[-1] if candles else None

    result = evaluate_trade_tick(
        side=side,
        entry_price=trade["entryIndexLevel"],
        initial_sl=trade["initialSl"],
        target1=trade["target1"],
        target2=trade["target2"],
        phase=trade["phase"],
        lot3_trail_sl=trade["lot3TrailSl"],
        spot=spot,
        latest_completed_candle=latest_completed,
    )
    if result is None:
        return

    if result["action"] == "TRAIL_SL":
        db.update_trade_phase(trade["id"], trade["phase"], lot3_trail_sl=result["newSl"])
        db.record_event(session_id, "TRAIL_SL", f"{side} {trade['id']} trailing SL moved to {result['newSl']:g}")
        return

    await _raise_exit_signal(settings, session_id, trade, action=result["action"], price=result["price"], new_sl=result.get("newSl"))


async def _raise_exit_signal(
    settings: Settings, session_id: str, trade: dict[str, Any], *, action: str, price: float, new_sl: float | None = None
) -> None:
    pending = [
        s for s in db.get_pending_signals(session_id) if s["kind"] == "EXIT" and s["tradeId"] == trade["id"]
    ]
    if pending:
        return

    lots = _lots_for_action(trade, action)
    if not lots:
        return

    signal_id = db.record_signal(
        session_id,
        side=trade["side"],
        kind="EXIT",
        status="PENDING",
        strike=trade["strike"],
        index_level=price,
        payload={"tradeId": trade["id"], "action": action, "lots": lots, "spotAtSignal": price, "newSl": new_sl},
    )
    db.update_signal_status(signal_id, "PENDING", trade_id=trade["id"])
    db.record_event(
        session_id, "EXIT_SIGNAL", f"{trade['side']} {action} signal for {trade['id']} at index {price:g}, lots {lots} — signal #{signal_id}"
    )
    await _alert_and_maybe_auto_approve(settings, session_id, signal_id, "exit")


def _lots_for_action(trade: dict[str, Any], action: str) -> list[int]:
    open_lots = {leg["lotNumber"] for leg in db.get_trade_legs(trade["id"]) if leg["status"] == "OPEN"}
    if action == "BOOK_LOT1":
        return [1] if 1 in open_lots else []
    if action == "BOOK_LOT2":
        return [2] if 2 in open_lots else []
    if action == "EXIT_LOT3":
        return [3] if 3 in open_lots else []
    if action in ("STOP_ALL", "STOP_REMAINING", "FORCE_EXIT"):
        return sorted(open_lots)
    return []


async def _alert_and_maybe_auto_approve(settings: Settings, session_id: str, signal_id: int, phase: str) -> None:
    await _send_alert(settings, session_id, signal_id, phase)
    if settings.ema5_mode == "PAPER" and settings.ema5_paper_auto_approve:
        await approve_ema5_signal(signal_id)


async def _send_alert(settings: Settings, session_id: str, signal_id: int, phase: str) -> None:
    key = f"{session_id}:{signal_id}"
    last = _last_alert_at.get(key, 0.0)
    now_monotonic = time.monotonic()
    if now_monotonic - last < settings.ema5_alert_repeat_seconds:
        return
    _last_alert_at[key] = now_monotonic

    signal = db.get_signal(signal_id)
    if not signal:
        return
    lines = [
        f"⚡ ema5 {signal['side']} {phase.upper()} signal — approval needed",
        f"Kind: {signal['kind']}, Strike: {signal.get('strike')}, Index level: {signal.get('indexLevel')}",
        f"Mode: {settings.ema5_mode}",
    ]
    await TelegramNotifier(settings).send("\n".join(lines))


async def approve_ema5_signal(signal_id: int) -> dict[str, Any]:
    settings = get_settings()
    signal = db.get_signal(signal_id)
    if not signal:
        return {"status": "blocked", "message": "Signal not found."}
    if signal["status"] != "PENDING":
        return {"status": "blocked", "message": f"Signal already {signal['status']}."}

    if signal["kind"] == "ENTRY":
        return await _approve_entry(settings, signal)
    return await _approve_exit(settings, signal)


async def _approve_entry(settings: Settings, signal: dict[str, Any]) -> dict[str, Any]:
    payload = signal["payload"] or {}
    security_id = payload.get("securityId")
    if not security_id:
        db.update_signal_status(signal["id"], "REJECTED")
        return {"status": "blocked", "message": "Missing security id."}

    quantity = settings.ema5_lots_per_trade * settings.ema5_lot_size
    fill_price, order_status, order_message = await _place_or_simulate(
        settings,
        transaction_type="BUY",
        exchange_segment=EXCHANGE_SEGMENT,
        security_id=str(security_id),
        quantity=quantity,
        correlation_id=f"EMA5-ENTRY-{signal['id']}",
    )
    if fill_price is None:
        db.update_signal_status(signal["id"], "FAILED")
        db.record_event(signal["sessionId"], "ENTRY_FAILED", f"Entry order failed: {order_message}")
        return {"status": "failed", "message": order_message}

    trade_id = f"EMA5-{signal['side']}-{payload.get('strike')}-{signal['id']}"
    db.insert_trade(
        trade_id,
        session_id=signal["sessionId"],
        side=signal["side"],
        strike=payload.get("strike"),
        security_id=str(security_id),
        exchange_segment=EXCHANGE_SEGMENT,
        mode=settings.ema5_mode,
        entry_signal_id=signal["id"],
        entry_index_level=payload["entryIndexLevel"],
        initial_sl=payload["initialSl"],
        target1=payload["target1"],
        target2=payload["target2"],
        target3=payload["target3"],
        payload=payload,
    )
    db.record_entry_fill(trade_id, entry_premium=fill_price, entry_qty=quantity)
    db.insert_trade_legs(trade_id, lot_count=settings.ema5_lots_per_trade, qty_per_lot=settings.ema5_lot_size)
    db.record_trade_entry(signal["sessionId"], signal["side"])
    db.update_signal_status(signal["id"], "APPROVED", trade_id=trade_id)
    db.record_event(signal["sessionId"], "ENTRY_FILLED", f"{signal['side']} entry filled {trade_id} at {fill_price:g} qty {quantity}")
    await TelegramNotifier(settings).send(f"✅ ema5 {signal['side']} entry filled: {trade_id} at {fill_price:g} x{quantity} ({order_status})")
    return {"status": order_status, "tradeId": trade_id, "fillPrice": fill_price, "quantity": quantity}


async def _approve_exit(settings: Settings, signal: dict[str, Any]) -> dict[str, Any]:
    payload = signal["payload"] or {}
    trade_id = signal.get("tradeId") or payload.get("tradeId")
    trade = db.get_trade(trade_id) if trade_id else None
    if not trade or trade["status"] != "OPEN":
        db.update_signal_status(signal["id"], "REJECTED")
        return {"status": "blocked", "message": "Trade is not open."}

    lots = payload.get("lots") or []
    action = str(payload.get("action") or "MANUAL")
    quantity = len(lots) * settings.ema5_lot_size
    if quantity <= 0:
        db.update_signal_status(signal["id"], "REJECTED")
        return {"status": "blocked", "message": "No open lots to exit."}

    fill_price, order_status, order_message = await _place_or_simulate(
        settings,
        transaction_type="SELL",
        exchange_segment=str(trade["exchangeSegment"]),
        security_id=str(trade["securityId"]),
        quantity=quantity,
        correlation_id=f"EMA5-EXIT-{signal['id']}",
    )
    if fill_price is None:
        db.update_signal_status(signal["id"], "FAILED")
        db.record_event(signal["sessionId"], "EXIT_FAILED", f"Exit order failed: {order_message}")
        return {"status": "failed", "message": order_message}

    per_lot_pnl = round((fill_price - (trade["entryPremium"] or 0)) * settings.ema5_lot_size, 2)
    spot_now = payload.get("spotAtSignal") or 0
    for lot_number in lots:
        db.close_trade_leg(
            trade_id, lot_number, exit_index_level=spot_now, exit_premium=fill_price, exit_reason=action, realized_pnl=per_lot_pnl
        )

    remaining_open = [leg for leg in db.get_trade_legs(trade_id) if leg["status"] == "OPEN"]
    if not remaining_open:
        total_pnl = round(sum((leg["realizedPnl"] or 0) for leg in db.get_trade_legs(trade_id)), 2)
        db.close_trade(trade_id, realized_pnl=total_pnl)
        was_sl = action == "STOP_ALL"
        db.record_trade_result(signal["sessionId"], trade["side"], was_sl=was_sl)
        session = db.get_session(signal["sessionId"])
        streak = session["peConsecutiveSl"] if trade["side"] == "PE" else session["ceConsecutiveSl"]
        if streak >= settings.ema5_max_consecutive_sl_per_side:
            db.set_side_halted(signal["sessionId"], trade["side"], True)
            db.record_event(signal["sessionId"], "SIDE_HALTED", f"{trade['side']} halted after {streak} consecutive SLs")
    else:
        new_phase = "LOT1_BOOKED" if action == "BOOK_LOT1" else "LOT2_BOOKED" if action == "BOOK_LOT2" else trade["phase"]
        new_sl = payload.get("newSl") if action == "BOOK_LOT2" else trade["lot3TrailSl"]
        db.update_trade_phase(trade_id, new_phase, lot3_trail_sl=new_sl)

    db.update_signal_status(signal["id"], "APPROVED")
    total_realized = round(per_lot_pnl * len(lots), 2)
    db.record_event(
        signal["sessionId"], "EXIT_FILLED", f"{trade['side']} {action} filled {trade_id} at {fill_price:g}, lots {lots}, P&L {total_realized:g}"
    )
    await TelegramNotifier(settings).send(f"✅ ema5 {trade['side']} {action}: {trade_id} at {fill_price:g}, lots {lots}, P&L {total_realized:g}")
    return {"status": order_status, "tradeId": trade_id, "fillPrice": fill_price, "realizedPnl": total_realized}


async def _place_or_simulate(
    settings: Settings, *, transaction_type: str, exchange_segment: str, security_id: str, quantity: int, correlation_id: str
) -> tuple[float | None, str, str | None]:
    dhan = DhanService(settings)
    ltp: float | None = None
    try:
        quotes = await dhan.market_quotes_by_segment({exchange_segment: [int(security_id)]})
        quote = (quotes.get(exchange_segment) or {}).get(str(security_id)) or {}
        ltp = _number(quote.get("last_price"))
    except Exception:
        ltp = None

    if settings.ema5_mode == "PAPER":
        if ltp is None:
            return None, "failed", "No live price available to simulate a paper fill."
        return ltp, "sent", None

    order_service = DhanOrderService(settings)
    result = await order_service.place_market_order(
        transaction_type=transaction_type,
        exchange_segment=exchange_segment,
        security_id=security_id,
        quantity=quantity,
        correlation_id=correlation_id,
    )
    status = str(result.get("status") or "unknown")
    if status != "sent":
        return None, status, str(result.get("message") or "Order not sent.")
    order = result.get("order") or {}
    fill_price = _number(order.get("price")) or ltp
    if fill_price is None:
        return None, "failed", "Order sent but no fill price available."
    return fill_price, "sent", None


def _parse_hhmm(value: str) -> dt_time:
    hour, minute = value.split(":")
    return dt_time(int(hour), int(minute))


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def get_state() -> dict[str, Any]:
    settings = get_settings()
    if _active is None:
        return {"mode": settings.ema5_mode, "status": "NOT_STARTED"}

    session_id = _active["sessionId"]
    session = db.get_session(session_id) or {}
    all_trades = db.get_trades_for_session(session_id)
    legs_by_trade = db.get_legs_for_trades([t["id"] for t in all_trades])

    open_trades: dict[str, dict[str, Any] | None] = {}
    trades_by_side: dict[str, list[dict[str, Any]]] = {}
    for side in SIDES:
        side_trades = [t for t in all_trades if t["side"] == side]
        trades_by_side[side] = side_trades
        open_trades[side] = next((t for t in side_trades if t["status"] == "OPEN"), None)

    live_premiums = await _fetch_live_premiums(settings, open_trades)

    sides: dict[str, Any] = {}
    for side in SIDES:
        side_state = _active["sides"][side]
        side_trades: list[dict[str, Any]] = []
        open_trade: dict[str, Any] | None = None
        open_trade_legs: list[dict[str, Any]] = []
        for raw_trade in trades_by_side[side]:
            trade = dict(raw_trade)
            legs = legs_by_trade.get(trade["id"], [])
            trade["legs"] = legs
            if trade["status"] == "OPEN":
                current_premium = live_premiums.get(str(trade["securityId"]))
                open_qty = sum(leg["qty"] for leg in legs if leg["status"] == "OPEN")
                entry_premium = trade.get("entryPremium")
                trade["currentPremium"] = current_premium
                trade["unrealizedPnl"] = (
                    round((current_premium - entry_premium) * open_qty, 2)
                    if current_premium is not None and entry_premium is not None and open_qty
                    else None
                )
                open_trade = trade
                open_trade_legs = legs
            side_trades.append(trade)

        sides[side] = {
            "alertCandle": _candle_dict(side_state["alertCandle"]),
            "candles": [_candle_dict(c) for c in side_state["candles"]],
            "ema": side_state["ema"],
            "openTrade": open_trade,
            "legs": open_trade_legs,
            "trades": side_trades,
            "tradesCount": session.get("peTradesCount" if side == "PE" else "ceTradesCount"),
            "consecutiveSl": session.get("peConsecutiveSl" if side == "PE" else "ceConsecutiveSl"),
            "halted": session.get("peHalted" if side == "PE" else "ceHalted"),
        }

    return {
        "mode": settings.ema5_mode,
        "status": "RUNNING",
        "sessionId": session_id,
        "wsConnected": _active["wsClient"].is_connected(),
        "spot": (_active["wsClient"].get_state(str(settings.dhan_nifty_security_id)) or {}).get("ltp"),
        "sides": sides,
        "pendingSignals": db.get_pending_signals(session_id),
        "events": db.get_events_for_session(session_id, limit=100),
    }


async def _fetch_live_premiums(settings: Settings, open_trades: dict[str, dict[str, Any] | None]) -> dict[str, float]:
    securities_by_segment: dict[str, list[int]] = {}
    for trade in open_trades.values():
        if trade is None:
            continue
        try:
            security_id = int(trade["securityId"])
        except (TypeError, ValueError):
            continue
        securities_by_segment.setdefault(str(trade["exchangeSegment"]), []).append(security_id)
    if not securities_by_segment:
        return {}
    try:
        quotes = await DhanService(settings).market_quotes_by_segment(securities_by_segment)
    except Exception:
        return {}
    result: dict[str, float] = {}
    for by_security in quotes.values():
        for security_id, quote in (by_security or {}).items():
            ltp = _number((quote or {}).get("last_price"))
            if ltp is not None:
                result[str(security_id)] = ltp
    return result


def _candle_dict(candle: Any) -> dict[str, Any] | None:
    if candle is None:
        return None
    return {"time": candle.time, "open": candle.open, "high": candle.high, "low": candle.low, "close": candle.close}


def list_past_sessions(limit: int = 30) -> list[dict[str, Any]]:
    return db.list_sessions(limit=limit)


def get_session_detail(session_id: str) -> dict[str, Any] | None:
    session = db.get_session(session_id)
    if not session:
        return None
    trades = db.get_trades_for_session(session_id)
    legs = db.get_legs_for_trades([t["id"] for t in trades])
    for trade in trades:
        trade["legs"] = legs.get(trade["id"], [])
    return {
        "session": session,
        "signals": db.get_signals_for_session(session_id),
        "trades": trades,
        "events": db.get_events_for_session(session_id, limit=500),
    }
