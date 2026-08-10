"""Theta Book orchestration: resolves each underlying's day-type at session
start, scans NIFTY + SENSEX option chains for entry/add candidates within a
safe distance band, monitors open positions for distance/premium stops and
expiry-day force-exit, and enforces the ₹ concurrent-margin cap before ever
raising a signal.

Mirrors services/animesh.py's shape (module-level `_active` state,
`_scheduler_loop`/`_tick` polling, `approve_theta_signal` as the only code
path that ever places an order, PAPER auto-approve). The one structural
departure: this strategy SELLS options to open and BUYS to close (the exact
reverse of animesh/ema5, which buy to open), and manages many concurrent
open strikes per underlying rather than one trade at a time — see
theta_engine.py for the pure day-type/band/stop rules this wires together.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime
from datetime import time as dt_time
from typing import Any

from app.core.config import Settings, get_settings
from app.core.timeutil import in_time_window, now_ist
from app.db import theta as db
from app.services.dhan import DhanService
from app.services.dhan_ws import DhanWsClient
from app.services.orders import DhanOrderService
from app.services.telegram import TelegramNotifier
from app.services.theta_engine import (
    classify_day_type,
    distance_band_for,
    estimate_margin,
    is_flat_market,
    select_strike_for_band,
    should_add_tranche,
    should_exit_position,
    trading_days_to_expiry,
)

UNDERLYINGS = ("NIFTY", "SENSEX")
SIDES = ("CE", "PE")
INDEX_SEGMENT = "IDX_I"
OPTION_SEGMENT = "NSE_FNO"

MAX_CONCURRENT_MARGIN_SETTING_KEY = "max_concurrent_margin"
MAX_DAILY_LOSS_SETTING_KEY = "max_daily_loss"

_active: dict[str, Any] | None = None
_last_alert_at: dict[str, float] = {}


def get_max_concurrent_margin() -> float:
    raw = db.get_setting(MAX_CONCURRENT_MARGIN_SETTING_KEY)
    if raw is not None:
        try:
            return float(raw)
        except ValueError:
            pass
    return get_settings().theta_max_concurrent_margin


def set_max_concurrent_margin(value: float) -> float:
    if value <= 0:
        raise ValueError("Max concurrent margin must be positive.")
    db.set_setting(MAX_CONCURRENT_MARGIN_SETTING_KEY, str(value))
    return value


def get_max_daily_loss() -> float:
    raw = db.get_setting(MAX_DAILY_LOSS_SETTING_KEY)
    if raw is not None:
        try:
            return float(raw)
        except ValueError:
            pass
    return get_settings().theta_max_daily_loss


def set_max_daily_loss(value: float) -> float:
    if value <= 0:
        raise ValueError("Max daily loss must be positive.")
    db.set_setting(MAX_DAILY_LOSS_SETTING_KEY, str(value))
    return value


def get_runtime_config() -> dict[str, Any]:
    return {"maxConcurrentMargin": get_max_concurrent_margin(), "maxDailyLoss": get_max_daily_loss()}


def _security_id(settings: Settings, underlying: str) -> int:
    return settings.dhan_nifty_security_id if underlying == "NIFTY" else settings.dhan_sensex_security_id


def _lot_size(settings: Settings, underlying: str) -> int:
    return settings.theta_nifty_lot_size if underlying == "NIFTY" else settings.theta_sensex_lot_size


def _strike_step(settings: Settings, underlying: str) -> float:
    return settings.theta_nifty_strike_step if underlying == "NIFTY" else settings.theta_sensex_strike_step


def _margin_per_lot(settings: Settings, underlying: str) -> float:
    return settings.theta_estimated_margin_per_lot_nifty if underlying == "NIFTY" else settings.theta_estimated_margin_per_lot_sensex


def start_theta_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.theta_monitor_enabled:
        return None
    return asyncio.create_task(_scheduler_loop())


async def stop_theta_task(task: asyncio.Task | None) -> None:
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
    interval = max(settings.theta_entry_scan_interval_seconds, 1)
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
    in_hours = in_time_window(now.time(), settings.theta_session_start_time, settings.theta_session_end_time)
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
    dhan = DhanService(settings)

    day_types: dict[str, str] = {}
    expiries: dict[str, str | None] = {}
    for underlying in UNDERLYINGS:
        try:
            expiry_list = await dhan.expiry_list(_security_id(settings, underlying), INDEX_SEGMENT)
            expiry = expiry_list[0] if expiry_list else None
            expiries[underlying] = expiry
            days = trading_days_to_expiry(now.date(), date.fromisoformat(expiry)) if expiry else -1
            day_types[underlying] = classify_day_type(days)
        except Exception:
            expiries[underlying] = None
            day_types[underlying] = "too_far"

    db.upsert_session(
        session_id,
        session_date=session_id,
        mode=settings.theta_mode,
        status="RUNNING",
        nifty_day_type=day_types["NIFTY"],
        sensex_day_type=day_types["SENSEX"],
    )
    db.record_event(session_id, "SESSION_START", f"theta session started, mode {settings.theta_mode}, day-types {day_types}")

    ws_client = DhanWsClient()
    ws_client.start(settings, [], [(INDEX_SEGMENT, str(_security_id(settings, u))) for u in UNDERLYINGS])

    _active = {
        "sessionId": session_id,
        "wsClient": ws_client,
        "dayTypes": day_types,
        "expiries": expiries,
        "chains": {u: {} for u in UNDERLYINGS},
        "lastChainPollAt": {u: 0.0 for u in UNDERLYINGS},
        "openingRange": {u: {"high": None, "low": None, "lockedAt": None} for u in UNDERLYINGS},
        "vixHistory": [],
        "lastAddCheckDistance": {},
    }


async def _end_session() -> None:
    global _active
    if not _active:
        return
    session_id = _active["sessionId"]
    await _active["wsClient"].stop()
    db.upsert_session(session_id, session_date=session_id, mode=get_settings().theta_mode, status="COMPLETED")
    db.record_event(session_id, "SESSION_END", "theta session ended")
    _active = None


async def _evaluate_tick(settings: Settings, now: datetime) -> None:
    session_id = _active["sessionId"]
    await _maybe_refresh_chains(settings, now)
    _maybe_lock_opening_range(settings, now)

    session = db.get_session(session_id)
    halted = bool(session["halted"]) if session else False

    for underlying in UNDERLYINGS:
        spot = _spot(settings, underlying)
        if spot is None:
            continue
        await _evaluate_open_positions(settings, session_id, underlying, spot, now)
        if halted:
            continue
        if _active["dayTypes"].get(underlying) == "too_far":
            continue
        if not _entry_window_ok(now.time(), settings):
            continue
        for side in SIDES:
            await _maybe_raise_entry_or_add_signal(settings, session_id, underlying, side, spot, now)


def _spot(settings: Settings, underlying: str) -> float | None:
    state = _active["wsClient"].get_state(str(_security_id(settings, underlying)))
    return state["ltp"] if state else None


def _entry_window_ok(now_time: dt_time, settings: Settings) -> bool:
    return in_time_window(now_time, settings.theta_entry_window_1_start, settings.theta_entry_window_1_end) or in_time_window(
        now_time, settings.theta_entry_window_2_start, settings.theta_entry_window_2_end
    )


async def _maybe_refresh_chains(settings: Settings, now: datetime) -> None:
    for underlying in UNDERLYINGS:
        if time.monotonic() - _active["lastChainPollAt"][underlying] < settings.theta_chain_poll_interval_seconds:
            continue
        expiry = _active["expiries"].get(underlying)
        if not expiry:
            continue
        _active["lastChainPollAt"][underlying] = time.monotonic()
        try:
            dhan = DhanService(settings)
            chain = await dhan.option_chain(_security_id(settings, underlying), INDEX_SEGMENT, expiry)
            _active["chains"][underlying] = chain
        except Exception:
            continue


def _maybe_lock_opening_range(settings: Settings, now: datetime) -> None:
    session_start = _parse_hhmm(settings.theta_session_start_time)
    range_end_minutes = session_start.hour * 60 + session_start.minute + settings.theta_opening_range_minutes
    now_minutes = now.hour * 60 + now.minute
    for underlying in UNDERLYINGS:
        rng = _active["openingRange"][underlying]
        spot = _spot(settings, underlying)
        if spot is None or now_minutes < session_start.hour * 60 + session_start.minute:
            continue
        if now_minutes <= range_end_minutes:
            rng["high"] = spot if rng["high"] is None else max(rng["high"], spot)
            rng["low"] = spot if rng["low"] is None else min(rng["low"], spot)
        elif rng["lockedAt"] is None:
            rng["lockedAt"] = now.isoformat()


def _confirmed_flat(settings: Settings, underlying: str, spot: float) -> bool:
    rng = _active["openingRange"][underlying]
    if rng["high"] is None or rng["low"] is None or spot <= 0:
        return False
    opening_range_pct = (rng["high"] - rng["low"]) / spot * 100
    range_so_far_pct = opening_range_pct
    return is_flat_market(
        opening_range_pct=opening_range_pct,
        range_so_far_pct=range_so_far_pct,
        historical_range_low_pct=0.4,
        vix_now=None,
        vix_avg_5d=None,
        opening_range_threshold_pct=settings.theta_opening_range_pct,
    )


async def _maybe_raise_entry_or_add_signal(settings: Settings, session_id: str, underlying: str, side: str, spot: float, now: datetime) -> None:
    day_type = _active["dayTypes"].get(underlying, "too_far")
    if day_type == "too_far":
        return
    confirmed_flat = _confirmed_flat(settings, underlying, spot)
    band = distance_band_for(
        day_type,
        confirmed_flat,
        wide_min_pct=settings.theta_band_wide_min_pct,
        wide_max_pct=settings.theta_band_wide_max_pct,
        morning_min_pct=settings.theta_band_morning_min_pct,
        morning_max_pct=settings.theta_band_morning_max_pct,
        tight_min_pct=settings.theta_band_tight_min_pct,
        tight_max_pct=settings.theta_band_tight_max_pct,
    )
    if band is None:
        return
    min_pct, max_pct = band

    open_positions = [p for p in db.get_open_positions(session_id, underlying) if p["side"] == side]

    if len(db.get_open_positions(session_id)) >= settings.theta_max_concurrent_positions:
        return

    live_quotes = await _fetch_live_quotes(settings, open_positions)
    for position in open_positions:
        quote = live_quotes.get(str(position["securityId"])) or {}
        live_premium = quote.get("last_price")
        if live_premium is None or position["strike"] is None:
            continue
        live_distance_pct = abs(float(position["strike"]) - spot) / spot * 100
        tranches = db.get_tranches_for_position(position["id"])
        last_tranche_distance = tranches[-1]["distancePctAtEntry"] if tranches else live_distance_pct
        ok = should_add_tranche(
            avg_entry_premium=position["avgEntryPremium"] or live_premium,
            live_premium=float(live_premium),
            live_distance_pct=live_distance_pct,
            band_floor_pct=min_pct,
            last_tranche_distance_pct=last_tranche_distance or 0.0,
            add_trigger_pct=settings.theta_add_trigger_premium_pct,
            tranche_count=position["trancheCount"],
            max_tranches=settings.theta_max_tranches_per_position,
        )
        if not ok:
            continue
        if not await _margin_available(settings, session_id, underlying, settings.theta_lots_per_tranche * _lot_size(settings, underlying)):
            db.record_event(session_id, "MARGIN_BLOCKED", f"ADD blocked for {position['id']}: margin cap would be breached")
            continue
        await _raise_add_signal(settings, session_id, position, live_distance_pct, day_type)
        return

    if open_positions:
        return

    pending_entries = [
        s for s in db.get_pending_signals(session_id) if s["kind"] == "ENTRY" and s["underlying"] == underlying and s["side"] == side
    ]
    if pending_entries:
        return

    chain = _active["chains"].get(underlying) or {}
    pick = select_strike_for_band(chain, spot, side, min_pct, max_pct, settings.theta_hard_floor_pct)
    if not pick:
        return

    qty = settings.theta_lots_per_tranche * _lot_size(settings, underlying)
    if not await _margin_available(settings, session_id, underlying, qty):
        db.record_event(session_id, "MARGIN_BLOCKED", f"ENTRY blocked for {underlying} {side} {pick['strike']:g}: margin cap would be breached")
        return

    expiry = _active["expiries"].get(underlying)
    signal_id = db.record_signal(
        session_id,
        kind="ENTRY",
        status="PENDING",
        underlying=underlying,
        side=side,
        strike=pick["strike"],
        expiry=expiry,
        payload={
            "securityId": pick["securityId"],
            "strike": pick["strike"],
            "estimatedPremium": pick["premium"],
            "distancePct": pick["distancePct"],
            "spot": spot,
            "dayType": day_type,
            "exchangeSegment": OPTION_SEGMENT,
        },
    )
    db.record_event(
        session_id,
        "ENTRY_SIGNAL",
        f"{underlying} {side} entry signal: strike {pick['strike']:g}, distance {pick['distancePct']:.2f}%, day-type {day_type} — signal #{signal_id}",
    )
    await _alert_and_maybe_auto_approve(settings, session_id, signal_id, "entry")


async def _raise_add_signal(settings: Settings, session_id: str, position: dict[str, Any], live_distance_pct: float, day_type: str) -> None:
    pending = [
        s for s in db.get_pending_signals(session_id) if s["kind"] == "ADD" and s["positionId"] == position["id"]
    ]
    if pending:
        return
    signal_id = db.record_signal(
        session_id,
        kind="ADD",
        status="PENDING",
        underlying=position["underlying"],
        side=position["side"],
        strike=position["strike"],
        expiry=position["expiry"],
        position_id=position["id"],
        payload={
            "securityId": position["securityId"],
            "strike": position["strike"],
            "distancePct": live_distance_pct,
            "dayType": day_type,
            "exchangeSegment": position["exchangeSegment"],
        },
    )
    db.record_event(
        session_id, "ADD_SIGNAL", f"{position['underlying']} {position['side']} add signal for {position['id']} — signal #{signal_id}"
    )
    await _alert_and_maybe_auto_approve(settings, session_id, signal_id, "add")


async def _evaluate_open_positions(settings: Settings, session_id: str, underlying: str, spot: float, now: datetime) -> None:
    positions = db.get_open_positions(session_id, underlying)
    if not positions:
        return
    live_quotes = await _fetch_live_quotes(settings, positions)

    day_type = _active["dayTypes"].get(underlying)
    force_exit = day_type == "expiry" and now.time() >= _parse_hhmm(settings.theta_force_exit_time)
    session_end = _parse_hhmm(settings.theta_session_end_time)
    minutes_left = max(0.0, (session_end.hour * 60 + session_end.minute) - (now.hour * 60 + now.minute))

    for position in positions:
        quote = live_quotes.get(str(position["securityId"])) or {}
        live_premium = quote.get("last_price")
        if live_premium is None or position["strike"] is None or position["avgEntryPremium"] is None:
            continue
        live_distance_pct = abs(float(position["strike"]) - spot) / spot * 100

        if force_exit:
            await _raise_exit_signal(settings, session_id, position, reason="FORCE_EXIT", live_premium=float(live_premium))
            continue

        should_exit, reason = should_exit_position(
            live_distance_pct=live_distance_pct,
            live_premium=float(live_premium),
            avg_entry_premium=float(position["avgEntryPremium"]),
            minutes_left=minutes_left,
            distance_stop_pct=settings.theta_distance_stop_pct,
            distance_stop_min_minutes_left=settings.theta_distance_stop_min_minutes_left,
            premium_stop_multiple=settings.theta_premium_stop_multiple,
        )
        if should_exit and reason:
            await _raise_exit_signal(settings, session_id, position, reason=reason, live_premium=float(live_premium))


async def _raise_exit_signal(settings: Settings, session_id: str, position: dict[str, Any], *, reason: str, live_premium: float) -> None:
    pending = [s for s in db.get_pending_signals(session_id) if s["kind"] == "EXIT" and s["positionId"] == position["id"]]
    if pending:
        return
    signal_id = db.record_signal(
        session_id,
        kind="EXIT",
        status="PENDING",
        underlying=position["underlying"],
        side=position["side"],
        strike=position["strike"],
        expiry=position["expiry"],
        position_id=position["id"],
        payload={
            "securityId": position["securityId"],
            "reason": reason,
            "estimatedPremium": live_premium,
            "totalQty": position["totalQty"],
            "exchangeSegment": position["exchangeSegment"],
        },
    )
    db.record_event(session_id, "EXIT_SIGNAL", f"{position['underlying']} {position['side']} {reason} signal for {position['id']} — signal #{signal_id}")
    await _alert_and_maybe_auto_approve(settings, session_id, signal_id, "exit")


async def _margin_available(settings: Settings, session_id: str, underlying: str, additional_qty: int) -> bool:
    open_positions = db.get_open_positions(session_id)
    used = 0.0
    for position in open_positions:
        lot_size = _lot_size(settings, position["underlying"])
        used += estimate_margin(position["totalQty"] or 0, lot_size, _margin_per_lot(settings, position["underlying"]))
    candidate = estimate_margin(additional_qty, _lot_size(settings, underlying), _margin_per_lot(settings, underlying))
    return used + candidate <= get_max_concurrent_margin()


async def _alert_and_maybe_auto_approve(settings: Settings, session_id: str, signal_id: int, phase: str) -> None:
    await _send_alert(settings, session_id, signal_id, phase)
    if settings.theta_mode == "PAPER" and settings.theta_paper_auto_approve:
        await approve_theta_signal(signal_id)


async def _send_alert(settings: Settings, session_id: str, signal_id: int, phase: str) -> None:
    key = f"{session_id}:{signal_id}"
    last = _last_alert_at.get(key, 0.0)
    now_monotonic = time.monotonic()
    if now_monotonic - last < settings.theta_alert_repeat_seconds:
        return
    _last_alert_at[key] = now_monotonic

    signal = db.get_signal(signal_id)
    if not signal:
        return
    lines = [
        f"\U0001f4b0 Theta Book {signal['underlying']} {signal['side']} {phase.upper()} signal — approval needed",
        f"Kind: {signal['kind']}, Strike: {signal.get('strike')}",
        f"Mode: {settings.theta_mode}",
    ]
    await TelegramNotifier(settings).send("\n".join(lines))


async def approve_theta_signal(signal_id: int) -> dict[str, Any]:
    settings = get_settings()
    signal = db.get_signal(signal_id)
    if not signal:
        return {"status": "blocked", "message": "Signal not found."}
    if signal["status"] != "PENDING":
        return {"status": "blocked", "message": f"Signal already {signal['status']}."}

    if signal["kind"] == "ENTRY":
        return await _approve_entry(settings, signal)
    if signal["kind"] == "ADD":
        return await _approve_add(settings, signal)
    return await _approve_exit(settings, signal)


async def reject_theta_signal(signal_id: int) -> dict[str, Any]:
    signal = db.get_signal(signal_id)
    if not signal or signal["status"] != "PENDING":
        return {"status": "blocked", "message": "Signal not found or not pending."}
    db.update_signal_status(signal_id, "REJECTED")
    db.record_event(signal["sessionId"], "SIGNAL_REJECTED", f"Signal #{signal_id} rejected by user")
    return {"status": "rejected"}


async def _approve_entry(settings: Settings, signal: dict[str, Any]) -> dict[str, Any]:
    payload = signal["payload"] or {}
    security_id = payload.get("securityId")
    if not security_id:
        db.update_signal_status(signal["id"], "REJECTED")
        return {"status": "blocked", "message": "Missing security id."}

    lot_size = _lot_size(settings, signal["underlying"])
    quantity = settings.theta_lots_per_tranche * lot_size
    fill_price, order_status, order_message = await _place_or_simulate(
        settings,
        transaction_type="SELL",
        exchange_segment=payload.get("exchangeSegment", OPTION_SEGMENT),
        security_id=str(security_id),
        quantity=quantity,
        correlation_id=f"THETA-ENTRY-{signal['id']}",
    )
    if fill_price is None:
        db.update_signal_status(signal["id"], "FAILED")
        db.record_event(signal["sessionId"], "ENTRY_FAILED", f"Entry order failed: {order_message}")
        return {"status": "failed", "message": order_message}

    position_id = f"THETA-{signal['underlying']}-{payload.get('strike'):g}-{signal['side']}-{signal['id']}"
    db.insert_position(
        position_id,
        session_id=signal["sessionId"],
        underlying=signal["underlying"],
        side=signal["side"],
        strike=payload["strike"],
        expiry=signal["expiry"],
        security_id=str(security_id),
        exchange_segment=payload.get("exchangeSegment", OPTION_SEGMENT),
        mode=settings.theta_mode,
        day_type=payload.get("dayType"),
        entry_spot=payload.get("spot"),
    )
    db.add_tranche(
        position_id,
        qty=quantity,
        premium=fill_price,
        spot_at_entry=payload.get("spot"),
        distance_pct_at_entry=payload.get("distancePct"),
        day_type=payload.get("dayType"),
    )
    db.set_position_margin(position_id, estimate_margin(quantity, lot_size, _margin_per_lot(settings, signal["underlying"])))
    db.update_signal_status(signal["id"], "APPROVED", position_id=position_id)
    db.record_event(signal["sessionId"], "ENTRY_FILLED", f"{signal['underlying']} {signal['side']} entry filled {position_id} at {fill_price:g} qty {quantity}")
    await TelegramNotifier(settings).send(f"✅ Theta Book {signal['underlying']} {signal['side']} SOLD: {position_id} at {fill_price:g} x{quantity} ({order_status})")
    return {"status": order_status, "positionId": position_id, "fillPrice": fill_price, "quantity": quantity}


async def _approve_add(settings: Settings, signal: dict[str, Any]) -> dict[str, Any]:
    payload = signal["payload"] or {}
    position_id = signal.get("positionId")
    position = db.get_position(position_id) if position_id else None
    if not position or position["status"] != "OPEN":
        db.update_signal_status(signal["id"], "REJECTED")
        return {"status": "blocked", "message": "Position is not open."}

    lot_size = _lot_size(settings, signal["underlying"])
    quantity = settings.theta_lots_per_tranche * lot_size
    fill_price, order_status, order_message = await _place_or_simulate(
        settings,
        transaction_type="SELL",
        exchange_segment=payload.get("exchangeSegment", position["exchangeSegment"]),
        security_id=str(position["securityId"]),
        quantity=quantity,
        correlation_id=f"THETA-ADD-{signal['id']}",
    )
    if fill_price is None:
        db.update_signal_status(signal["id"], "FAILED")
        db.record_event(signal["sessionId"], "ADD_FAILED", f"Add order failed: {order_message}")
        return {"status": "failed", "message": order_message}

    db.add_tranche(
        position["id"],
        qty=quantity,
        premium=fill_price,
        spot_at_entry=None,
        distance_pct_at_entry=payload.get("distancePct"),
        day_type=payload.get("dayType"),
    )
    new_total_qty = (position["totalQty"] or 0) + quantity
    db.set_position_margin(position["id"], estimate_margin(new_total_qty, lot_size, _margin_per_lot(settings, signal["underlying"])))
    db.update_signal_status(signal["id"], "APPROVED", position_id=position["id"])
    db.record_event(signal["sessionId"], "ADD_FILLED", f"{signal['underlying']} {signal['side']} add filled {position['id']} at {fill_price:g} qty {quantity}")
    await TelegramNotifier(settings).send(f"✅ Theta Book {signal['underlying']} {signal['side']} ADD: {position['id']} at {fill_price:g} x{quantity} ({order_status})")
    return {"status": order_status, "positionId": position["id"], "fillPrice": fill_price, "quantity": quantity}


async def _approve_exit(settings: Settings, signal: dict[str, Any]) -> dict[str, Any]:
    payload = signal["payload"] or {}
    position_id = signal.get("positionId") or payload.get("positionId")
    position = db.get_position(position_id) if position_id else None
    if not position or position["status"] != "OPEN":
        db.update_signal_status(signal["id"], "REJECTED")
        return {"status": "blocked", "message": "Position is not open."}

    quantity = position["totalQty"] or 0
    if quantity <= 0:
        db.update_signal_status(signal["id"], "REJECTED")
        return {"status": "blocked", "message": "No open quantity to exit."}

    fill_price, order_status, order_message = await _place_or_simulate(
        settings,
        transaction_type="BUY",
        exchange_segment=str(position["exchangeSegment"]),
        security_id=str(position["securityId"]),
        quantity=quantity,
        correlation_id=f"THETA-EXIT-{signal['id']}",
    )
    if fill_price is None:
        db.update_signal_status(signal["id"], "FAILED")
        db.record_event(signal["sessionId"], "EXIT_FAILED", f"Exit order failed: {order_message}")
        return {"status": "failed", "message": order_message}

    realized_pnl = round(((position["avgEntryPremium"] or 0) - fill_price) * quantity, 2)
    reason = str(payload.get("reason") or "MANUAL")
    db.close_position(position["id"], realized_pnl=realized_pnl, close_reason=reason)
    db.record_daily_pnl(signal["sessionId"], realized_pnl)
    db.update_signal_status(signal["id"], "APPROVED")

    session = db.get_session(signal["sessionId"])
    if session and realized_pnl < 0 and abs(session["realizedPnl"]) >= get_max_daily_loss():
        db.set_day_halted(signal["sessionId"], True)
        db.record_event(signal["sessionId"], "DAY_HALTED", f"Daily loss cap breached ({session['realizedPnl']:.0f}); new entries paused for today")

    db.record_event(signal["sessionId"], "EXIT_FILLED", f"{signal['underlying']} {signal['side']} {reason} filled {position['id']} at {fill_price:g}, P&L {realized_pnl:g}")
    await TelegramNotifier(settings).send(f"✅ Theta Book {signal['underlying']} {signal['side']} {reason}: {position['id']} at {fill_price:g}, P&L {realized_pnl:g}")
    return {"status": order_status, "positionId": position["id"], "fillPrice": fill_price, "realizedPnl": realized_pnl}


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

    if settings.theta_mode == "PAPER":
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


async def _fetch_live_quotes(settings: Settings, positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    securities_by_segment: dict[str, list[int]] = {}
    for position in positions:
        try:
            security_id = int(position["securityId"])
        except (TypeError, ValueError):
            continue
        securities_by_segment.setdefault(str(position["exchangeSegment"]), []).append(security_id)
    if not securities_by_segment:
        return {}
    try:
        quotes = await DhanService(settings).market_quotes_by_segment(securities_by_segment)
    except Exception:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for by_security in quotes.values():
        for security_id, quote in (by_security or {}).items():
            result[str(security_id)] = quote or {}
    return result


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
        return {"mode": settings.theta_mode, "status": "NOT_STARTED"}

    session_id = _active["sessionId"]
    session = db.get_session(session_id) or {}
    open_positions = db.get_open_positions(session_id)
    closed_positions = [p for p in db.get_positions_for_session(session_id) if p["status"] == "CLOSED"]
    live_quotes = await _fetch_live_quotes(settings, open_positions)
    tranches_by_position = db.get_tranches_for_positions([p["id"] for p in open_positions + closed_positions])

    used_margin = 0.0
    positions_out: list[dict[str, Any]] = []
    for position in open_positions:
        p = dict(position)
        p["tranches"] = tranches_by_position.get(p["id"], [])
        quote = live_quotes.get(str(p["securityId"])) or {}
        live_premium = _number(quote.get("last_price"))
        spot = _spot(settings, p["underlying"])
        p["currentPremium"] = live_premium
        p["spot"] = spot
        p["distancePct"] = abs(float(p["strike"]) - spot) / spot * 100 if spot and p["strike"] else None
        p["unrealizedPnl"] = (
            round(((p["avgEntryPremium"] or 0) - live_premium) * (p["totalQty"] or 0), 2)
            if live_premium is not None and p["avgEntryPremium"] is not None
            else None
        )
        used_margin += p["estimatedMargin"] or 0.0
        positions_out.append(p)

    closed_out = []
    for position in closed_positions:
        p = dict(position)
        p["tranches"] = tranches_by_position.get(p["id"], [])
        closed_out.append(p)

    underlyings: dict[str, Any] = {}
    for underlying in UNDERLYINGS:
        spot = _spot(settings, underlying)
        rng = _active["openingRange"][underlying]
        underlyings[underlying] = {
            "dayType": _active["dayTypes"].get(underlying),
            "expiry": _active["expiries"].get(underlying),
            "spot": spot,
            "openingRangeHigh": rng["high"],
            "openingRangeLow": rng["low"],
            "confirmedFlat": _confirmed_flat(settings, underlying, spot) if spot else False,
        }

    return {
        "mode": settings.theta_mode,
        "status": "RUNNING",
        "sessionId": session_id,
        "halted": bool(session.get("halted")),
        "realizedPnl": session.get("realizedPnl"),
        "marginUsed": round(used_margin, 2),
        "marginCap": settings.theta_max_concurrent_margin,
        "underlyings": underlyings,
        "wsConnected": _active["wsClient"].is_connected(),
        "openPositions": positions_out,
        "closedPositions": closed_out,
        "pendingSignals": db.get_pending_signals(session_id),
        "events": db.get_events_for_session(session_id, limit=100),
    }


def list_past_sessions(limit: int = 30) -> list[dict[str, Any]]:
    return db.list_sessions(limit=limit)


def get_session_detail(session_id: str) -> dict[str, Any] | None:
    session = db.get_session(session_id)
    if not session:
        return None
    positions = db.get_positions_for_session(session_id)
    tranches = db.get_tranches_for_positions([p["id"] for p in positions])
    for position in positions:
        position["tranches"] = tranches.get(position["id"], [])
    return {
        "session": session,
        "signals": db.get_signals_for_session(session_id),
        "positions": positions,
        "events": db.get_events_for_session(session_id, limit=500),
    }


