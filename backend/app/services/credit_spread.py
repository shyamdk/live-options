"""Bank Nifty monthly credit-spread orchestration: series tracking, entry on
the first trading day of the new monthly series, half-cycle time exit, and the
only code path that places orders (paper simulation or real Dhan orders) —
always behind approve_credit_spread_signal. PAPER mode may auto-approve;
LIVE mode always waits for the API-triggered manual click.

Leg-safety invariants for LIVE orders:
  - entry places the BUY hedge before the SELL leg (never naked short),
  - exit buys back the SELL leg before selling the hedge,
  - a partial fill raises a CRITICAL event + Telegram alert for manual action.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime
from typing import Any

from app.core.config import Settings, get_settings
from app.core.market_calendar import (
    holidays_from_settings,
    is_trading_day,
    planned_exit_date,
    trading_days_after,
)
from app.core.timeutil import in_time_window, now_ist
from app.db import credit_spread as db
from app.services.credit_spread_engine import (
    entry_blockers,
    evaluate_exit,
    leg,
    mark_to_market,
    parse_chain,
    select_spread,
)
from app.services.dhan import DhanService
from app.services.orders import DhanOrderService
from app.services.telegram import TelegramNotifier

INDEX_SEGMENT = "IDX_I"
EXCHANGE_SEGMENT = "NSE_FNO"
STRATEGY_LABEL = "BankNifty Credit Spread"

_runtime: dict[str, Any] = {
    "frontExpiry": None,
    "frontExpiryFetchedAt": 0.0,
    "lastChainAt": 0.0,
    "lastEvaluation": None,
    "lastMtm": None,
    "lastError": None,
}
_scheduler_task: asyncio.Task | None = None


def start_credit_spread_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.credit_spread_monitor_enabled:
        return None
    return asyncio.create_task(_scheduler_loop())


async def stop_credit_spread_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def _scheduler_loop() -> None:
    settings = get_settings()
    interval = max(settings.credit_spread_evaluation_interval_seconds, 5)
    while True:
        try:
            await _tick(settings)
            _runtime["lastError"] = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # keep the loop alive; surface via state API
            _runtime["lastError"] = f"{type(exc).__name__}: {exc}"
        await asyncio.sleep(interval)


async def _tick(settings: Settings) -> None:
    now = now_ist()
    holidays = holidays_from_settings(settings)
    if not is_trading_day(now.date(), holidays):
        return
    if not in_time_window(now.time(), settings.credit_spread_session_start_time, settings.credit_spread_session_end_time):
        return

    front_expiry = await _front_expiry(settings, now.date())
    if front_expiry:
        _track_series(front_expiry, now.date())

    _expire_stale_entry_signals(settings, now)

    open_position = db.get_open_position()
    if open_position:
        await _monitor_open_position(settings, now, holidays, open_position)
    elif front_expiry:
        await _maybe_enter(settings, now, holidays, front_expiry)


async def _front_expiry(settings: Settings, today: date) -> str | None:
    cached = _runtime.get("frontExpiry")
    fresh = time.monotonic() - _runtime.get("frontExpiryFetchedAt", 0.0) < settings.credit_spread_expiry_refresh_seconds
    if cached and fresh and cached >= today.isoformat():
        return cached
    dhan = DhanService(settings)
    expiries = await dhan.expiry_list(settings.dhan_banknifty_security_id, INDEX_SEGMENT)
    today_str = today.isoformat()
    upcoming = sorted(e for e in expiries if isinstance(e, str) and e >= today_str)
    front = upcoming[0] if upcoming else None
    if front:
        _runtime["frontExpiry"] = front
        _runtime["frontExpiryFetchedAt"] = time.monotonic()
    return front


def _track_series(front_expiry: str, today: date) -> None:
    stored = db.get_meta("front_expiry")
    if stored == front_expiry:
        return
    db.set_meta("front_expiry", front_expiry)
    db.set_meta("series_start_date", today.isoformat())
    db.record_event(
        "SERIES_START",
        f"New monthly series detected: front expiry {front_expiry}, first seen {today.isoformat()}.",
    )


def _expire_stale_entry_signals(settings: Settings, now: datetime) -> None:
    for signal in db.get_pending_signals():
        if signal["kind"] != "ENTRY":
            continue
        payload = signal.get("payload") or {}
        signal_day = str(payload.get("signalDay") or "")
        window_closed = now.time().strftime("%H:%M") > settings.credit_spread_entry_window_end
        if signal_day != now.date().isoformat() or window_closed:
            db.update_signal_status(signal["id"], "EXPIRED")
            db.record_event("SIGNAL_EXPIRED", f"Entry signal #{signal['id']} expired unapproved.")


async def _maybe_enter(settings: Settings, now: datetime, holidays: frozenset[date], front_expiry: str) -> None:
    today = now.date()
    if db.get_position_for_expiry(front_expiry):
        return  # one spread per series, ever — matches the record
    if any(s["kind"] == "ENTRY" for s in db.get_pending_signals()):
        return
    if not in_time_window(now.time(), settings.credit_spread_entry_time, settings.credit_spread_entry_window_end):
        return

    if today.isoformat() in _skip_dates(settings):
        _record_once(f"skip_date_{today.isoformat()}", "ENTRY_SKIPPED", f"{today.isoformat()} is a configured skip date (event day).")
        return

    expiry_date = date.fromisoformat(front_expiry)
    remaining = trading_days_after(today, expiry_date, holidays)
    series_start = db.get_meta("series_start_date")
    if remaining < settings.credit_spread_min_entry_trading_days_left:
        _record_once(
            f"too_late_{front_expiry}",
            "ENTRY_SKIPPED",
            f"Only {remaining} trading days left to {front_expiry} — below the {settings.credit_spread_min_entry_trading_days_left}-day minimum, series skipped.",
        )
        return
    if series_start != today.isoformat() and not settings.credit_spread_allow_late_entry:
        return

    if time.monotonic() - _runtime.get("lastChainAt", 0.0) < settings.credit_spread_chain_poll_interval_seconds:
        return

    evaluation = await _evaluate_entry(settings, front_expiry)
    if evaluation is None:
        return
    blockers = evaluation["blockers"]
    if blockers:
        _record_once(
            f"blocked_{today.isoformat()}",
            "ENTRY_BLOCKED",
            "Entry conditions not met today: " + " | ".join(blockers),
            payload=evaluation["selection"],
        )
        return

    selection = evaluation["selection"]
    qty = settings.credit_spread_lot_size * settings.credit_spread_lots
    exit_day = planned_exit_date(expiry_date, settings.credit_spread_exit_trading_days_before_expiry, holidays)
    payload = {
        "signalDay": today.isoformat(),
        "expiry": front_expiry,
        "qty": qty,
        "sell": selection["sell"],
        "hedge": selection["hedge"],
        "netCredit": selection["netCredit"],
        "width": selection["width"],
        "creditPercentOfWidth": selection["creditPercentOfWidth"],
        "spot": selection["spot"],
        "syntheticFuture": selection["syntheticFuture"],
        "vix": evaluation["vix"],
        "plannedExitDate": exit_day.isoformat() if exit_day else None,
        "remainingTradingDays": remaining,
    }
    signal_id = db.record_signal(kind="ENTRY", status="PENDING", payload=payload)
    db.record_event(
        "ENTRY_SIGNAL",
        f"Entry signal #{signal_id}: SELL {selection['sell']['strike']:g} CE @ {selection['sell']['price']:.2f}, "
        f"BUY {selection['hedge']['strike']:g} CE @ {selection['hedge']['price']:.2f}, "
        f"credit {selection['netCredit']:.2f}, expiry {front_expiry}.",
        payload=payload,
    )
    await _notify(
        settings,
        f"🧾 {STRATEGY_LABEL} ENTRY signal #{signal_id} ({settings.credit_spread_mode})\n"
        f"SELL {selection['sell']['strike']:g} CE @ {selection['sell']['price']:.2f}\n"
        f"BUY  {selection['hedge']['strike']:g} CE @ {selection['hedge']['price']:.2f}\n"
        f"Credit {selection['netCredit']:.2f} x qty {qty} | expiry {front_expiry}\n"
        f"Planned exit: {payload['plannedExitDate']} 09:20",
    )
    if settings.credit_spread_mode == "PAPER" and settings.credit_spread_paper_auto_approve:
        await approve_credit_spread_signal(signal_id)


async def _evaluate_entry(settings: Settings, expiry: str) -> dict[str, Any] | None:
    dhan = DhanService(settings)
    chain = await dhan.option_chain(settings.dhan_banknifty_security_id, INDEX_SEGMENT, expiry)
    _runtime["lastChainAt"] = time.monotonic()
    spot, strikes = parse_chain(chain)
    if spot is None or not strikes:
        db.record_event("CHAIN_EMPTY", f"Option chain for {expiry} returned no usable data.")
        return None
    selection = select_spread(spot, strikes, hedge_premium_target=settings.credit_spread_hedge_premium_target)
    if selection is None:
        db.record_event("CHAIN_EMPTY", f"Could not construct a spread from the {expiry} chain.")
        return None
    vix = await _fetch_vix(settings)
    blockers = entry_blockers(
        selection,
        min_net_credit=settings.credit_spread_min_net_credit,
        min_credit_width_percent=settings.credit_spread_min_credit_width_percent,
        max_entry_vix=settings.credit_spread_max_entry_vix,
        vix=vix,
    )
    evaluation = {
        "at": now_ist().isoformat(timespec="seconds"),
        "expiry": expiry,
        "selection": selection,
        "vix": vix,
        "blockers": blockers,
    }
    _runtime["lastEvaluation"] = evaluation
    return evaluation


async def _monitor_open_position(
    settings: Settings, now: datetime, holidays: frozenset[date], position: dict[str, Any]
) -> None:
    expiry_date = date.fromisoformat(position["expiry"])
    remaining = trading_days_after(now.date(), expiry_date, holidays)
    is_exit_day = remaining <= settings.credit_spread_exit_trading_days_before_expiry

    # Poll faster near the 09:20 exit so the time exit fires promptly.
    poll_interval = 20 if is_exit_day else settings.credit_spread_chain_poll_interval_seconds
    if time.monotonic() - _runtime.get("lastChainAt", 0.0) < poll_interval:
        return

    dhan = DhanService(settings)
    chain = await dhan.option_chain(settings.dhan_banknifty_security_id, INDEX_SEGMENT, position["expiry"])
    _runtime["lastChainAt"] = time.monotonic()
    spot, strikes = parse_chain(chain)
    sell_leg = leg(strikes, float(position["sellStrike"]), "ce")
    hedge_leg = leg(strikes, float(position["hedgeStrike"]), "ce") if position.get("hedgeStrike") else None
    mtm = mark_to_market(position, sell_leg["price"] if sell_leg else None, hedge_leg["price"] if hedge_leg else None)
    if mtm:
        _runtime["lastMtm"] = {**mtm, "at": now_ist().isoformat(timespec="seconds"), "spot": spot, "remainingTradingDays": remaining}

    if any(s["kind"] == "EXIT" for s in db.get_pending_signals()):
        return

    decision = evaluate_exit(
        remaining_trading_days_after_today=remaining,
        exit_days_threshold=settings.credit_spread_exit_trading_days_before_expiry,
        now_hhmm=now.time().strftime("%H:%M"),
        exit_time=settings.credit_spread_exit_time,
        mtm=mtm,
        profit_target_percent=settings.credit_spread_profit_target_percent,
        hard_stop_credit_multiple=settings.credit_spread_hard_stop_credit_multiple,
    )
    if not decision:
        return

    payload = {
        "positionId": position["id"],
        "reason": decision["reason"],
        "detail": decision["detail"],
        "sellLtp": sell_leg["price"] if sell_leg else None,
        "hedgeLtp": hedge_leg["price"] if hedge_leg else None,
        "unrealizedPnl": (mtm or {}).get("unrealizedPnl"),
    }
    signal_id = db.record_signal(kind="EXIT", status="PENDING", position_id=position["id"], payload=payload)
    db.record_event(
        "EXIT_SIGNAL",
        f"Exit signal #{signal_id} for {position['id']}: {decision['reason']} — {decision['detail']}",
        position_id=position["id"],
        payload=payload,
    )
    await _notify(
        settings,
        f"🚪 {STRATEGY_LABEL} EXIT signal #{signal_id} ({decision['reason']})\n"
        f"{decision['detail']}\nUnrealized P&L: {payload['unrealizedPnl']}",
    )
    if settings.credit_spread_mode == "PAPER" and settings.credit_spread_paper_auto_approve:
        await approve_credit_spread_signal(signal_id)


async def approve_credit_spread_signal(signal_id: int) -> dict[str, Any]:
    settings = get_settings()
    signal = db.get_signal(signal_id)
    if not signal:
        return {"status": "blocked", "message": "Signal not found."}
    if signal["status"] != "PENDING":
        return {"status": "blocked", "message": f"Signal already {signal['status']}."}
    if signal["kind"] == "ENTRY":
        return await _approve_entry(settings, signal)
    if signal["kind"] == "EXIT":
        return await _approve_exit(settings, signal)
    return {"status": "blocked", "message": f"Unknown signal kind {signal['kind']}."}


async def _approve_entry(settings: Settings, signal: dict[str, Any]) -> dict[str, Any]:
    payload = signal.get("payload") or {}
    expiry = str(payload.get("expiry") or "")
    sell = payload.get("sell") or {}
    hedge = payload.get("hedge") or {}
    qty = int(payload.get("qty") or 0)
    if not expiry or not sell.get("securityId") or not hedge.get("securityId") or qty <= 0:
        db.update_signal_status(signal["id"], "REJECTED")
        return {"status": "blocked", "message": "Signal payload incomplete."}
    if db.get_open_position():
        db.update_signal_status(signal["id"], "REJECTED")
        return {"status": "blocked", "message": "A position is already open."}

    sell_price, hedge_price = await _refresh_leg_prices(settings, expiry, sell, hedge)

    if settings.credit_spread_mode == "PAPER":
        hedge_fill, sell_fill = hedge_price, sell_price
    else:
        orders = DhanOrderService(settings)
        hedge_fill, message = await _live_fill(orders, "BUY", hedge["securityId"], qty, f"CS-HEDGE-{signal['id']}", hedge_price)
        if hedge_fill is None:
            db.update_signal_status(signal["id"], "FAILED")
            db.record_event("ENTRY_FAILED", f"Hedge BUY failed, nothing opened: {message}")
            return {"status": "failed", "message": message}
        sell_fill, message = await _live_fill(orders, "SELL", sell["securityId"], qty, f"CS-SELL-{signal['id']}", sell_price)
        if sell_fill is None:
            db.update_signal_status(signal["id"], "FAILED")
            db.record_event(
                "CRITICAL",
                f"Hedge filled but SELL leg failed — long {hedge['strike']:g} CE x{qty} is open unhedged by design intent. "
                f"Close or complete manually. Reason: {message}",
            )
            await _notify(settings, f"🚨 {STRATEGY_LABEL}: SELL leg failed after hedge fill. MANUAL ACTION NEEDED. {message}")
            return {"status": "failed", "message": f"Sell leg failed after hedge fill: {message}"}

    net_credit = round(sell_fill - hedge_fill, 2)
    position_id = f"CS-{expiry}"
    db.insert_position(
        position_id,
        expiry=expiry,
        mode=settings.credit_spread_mode,
        qty=qty,
        sell_strike=float(sell["strike"]),
        sell_security_id=str(sell["securityId"]),
        sell_entry_price=sell_fill,
        hedge_strike=float(hedge["strike"]),
        hedge_security_id=str(hedge["securityId"]),
        hedge_entry_price=hedge_fill,
        net_credit=net_credit,
        entry_spot=payload.get("spot"),
        entry_synthetic_future=payload.get("syntheticFuture"),
        entry_vix=payload.get("vix"),
        planned_exit_date=payload.get("plannedExitDate"),
        entry_signal_id=signal["id"],
        payload=payload,
    )
    db.update_signal_status(signal["id"], "APPROVED", position_id=position_id)
    db.record_event(
        "ENTRY_FILLED",
        f"{position_id} opened ({settings.credit_spread_mode}): SELL {sell['strike']:g} CE @ {sell_fill:.2f}, "
        f"BUY {hedge['strike']:g} CE @ {hedge_fill:.2f}, credit {net_credit:.2f} x{qty}.",
        position_id=position_id,
    )
    await _notify(
        settings,
        f"✅ {STRATEGY_LABEL} entry filled ({settings.credit_spread_mode}): credit {net_credit:.2f} x{qty}, "
        f"max profit ₹{net_credit * qty:,.0f}, planned exit {payload.get('plannedExitDate')} 09:20.",
    )
    _runtime["lastMtm"] = None
    return {"status": "sent", "positionId": position_id, "netCredit": net_credit, "qty": qty}


async def _approve_exit(settings: Settings, signal: dict[str, Any]) -> dict[str, Any]:
    payload = signal.get("payload") or {}
    position = db.get_position(str(payload.get("positionId") or signal.get("positionId") or ""))
    if not position or position["status"] != "OPEN":
        db.update_signal_status(signal["id"], "REJECTED")
        return {"status": "blocked", "message": "Position is not open."}

    qty = int(position["qty"] or 0)
    sell_stub = {"securityId": position["sellSecurityId"], "strike": position["sellStrike"], "price": payload.get("sellLtp")}
    hedge_stub = {"securityId": position["hedgeSecurityId"], "strike": position["hedgeStrike"], "price": payload.get("hedgeLtp")}
    sell_price, hedge_price = await _refresh_leg_prices(settings, position["expiry"], sell_stub, hedge_stub)
    if sell_price is None:
        db.update_signal_status(signal["id"], "FAILED")
        db.record_event("EXIT_FAILED", "No price available for the short leg — cannot close.", position_id=position["id"])
        return {"status": "failed", "message": "No price available for the short leg."}

    if settings.credit_spread_mode == "PAPER":
        sell_exit, hedge_exit = sell_price, hedge_price
    else:
        orders = DhanOrderService(settings)
        sell_exit, message = await _live_fill(orders, "BUY", position["sellSecurityId"], qty, f"CS-CLOSE-{signal['id']}", sell_price)
        if sell_exit is None:
            db.update_signal_status(signal["id"], "FAILED")
            db.record_event("EXIT_FAILED", f"Buy-back of short leg failed: {message}", position_id=position["id"])
            await _notify(settings, f"🚨 {STRATEGY_LABEL}: exit buy-back FAILED, position still open. {message}")
            return {"status": "failed", "message": message}
        hedge_exit, message = await _live_fill(orders, "SELL", position["hedgeSecurityId"], qty, f"CS-UNWIND-{signal['id']}", hedge_price)
        if hedge_exit is None:
            db.record_event(
                "CRITICAL",
                f"Short leg closed but hedge SELL failed — long {position['hedgeStrike']:g} CE x{qty} still open. "
                f"Sell it manually. Reason: {message}",
                position_id=position["id"],
            )
            await _notify(settings, f"🚨 {STRATEGY_LABEL}: hedge unwind failed after closing short leg. MANUAL ACTION NEEDED.")
            hedge_exit = 0.0

    realized = round(
        ((position["sellEntryPrice"] - sell_exit) + ((hedge_exit or 0.0) - (position["hedgeEntryPrice"] or 0.0))) * qty,
        2,
    )
    reason = str(payload.get("reason") or "MANUAL")
    db.close_position(position["id"], sell_exit_price=sell_exit, hedge_exit_price=hedge_exit, exit_reason=reason, realized_pnl=realized)
    db.update_signal_status(signal["id"], "APPROVED", position_id=position["id"])
    db.record_event(
        "EXIT_FILLED",
        f"{position['id']} closed ({reason}): buy-back {sell_exit:.2f}, hedge out {hedge_exit if hedge_exit is not None else 0:.2f}, "
        f"realized P&L ₹{realized:,.2f}.",
        position_id=position["id"],
    )
    await _notify(settings, f"✅ {STRATEGY_LABEL} closed ({reason}). Realized P&L: ₹{realized:,.2f}")
    _runtime["lastMtm"] = None
    return {"status": "sent", "positionId": position["id"], "realizedPnl": realized}


async def request_manual_exit() -> dict[str, Any]:
    position = db.get_open_position()
    if not position:
        return {"status": "blocked", "message": "No open position."}
    for signal in db.get_pending_signals():
        if signal["kind"] == "EXIT":
            return {"status": "blocked", "message": f"Exit signal #{signal['id']} is already pending approval."}
    settings = get_settings()
    payload = {"positionId": position["id"], "reason": "MANUAL", "detail": "Manual exit requested from the dashboard."}
    signal_id = db.record_signal(kind="EXIT", status="PENDING", position_id=position["id"], payload=payload)
    db.record_event("EXIT_SIGNAL", f"Manual exit signal #{signal_id} created.", position_id=position["id"])
    return await approve_credit_spread_signal(signal_id) | {"signalId": signal_id, "mode": settings.credit_spread_mode}


async def evaluate_now() -> dict[str, Any]:
    """Force a fresh evaluation for the dashboard 'Evaluate now' button."""
    settings = get_settings()
    now = now_ist()
    front = await _front_expiry(settings, now.date())
    if not front:
        return {"status": "failed", "message": "No upcoming expiry available from Dhan."}
    open_position = db.get_open_position()
    if open_position:
        holidays = holidays_from_settings(settings)
        _runtime["lastChainAt"] = 0.0
        await _monitor_open_position(settings, now, holidays, open_position)
        return {"status": "ok", "mtm": _runtime.get("lastMtm")}
    evaluation = await _evaluate_entry(settings, front)
    if evaluation is None:
        return {"status": "failed", "message": "Option chain unavailable."}
    return {"status": "ok", "evaluation": evaluation}


async def _refresh_leg_prices(
    settings: Settings, expiry: str, sell: dict[str, Any], hedge: dict[str, Any]
) -> tuple[float | None, float | None]:
    """Fresh chain prices for fills; falls back to the prices carried on the signal."""
    sell_price = _number(sell.get("price"))
    hedge_price = _number(hedge.get("price"))
    try:
        dhan = DhanService(settings)
        chain = await dhan.option_chain(settings.dhan_banknifty_security_id, INDEX_SEGMENT, expiry)
        _runtime["lastChainAt"] = time.monotonic()
        _, strikes = parse_chain(chain)
        fresh_sell = leg(strikes, float(sell["strike"]), "ce") if sell.get("strike") is not None else None
        fresh_hedge = leg(strikes, float(hedge["strike"]), "ce") if hedge.get("strike") is not None else None
        if fresh_sell:
            sell_price = fresh_sell["price"]
        if fresh_hedge:
            hedge_price = fresh_hedge["price"]
    except Exception:
        pass
    return sell_price, hedge_price


async def _live_fill(
    orders: DhanOrderService, transaction_type: str, security_id: str, qty: int, correlation_id: str, fallback_price: float | None
) -> tuple[float | None, str]:
    result = await orders.place_market_order(
        transaction_type=transaction_type,
        exchange_segment=EXCHANGE_SEGMENT,
        security_id=str(security_id),
        quantity=qty,
        correlation_id=correlation_id,
    )
    status = str(result.get("status") or "unknown")
    if status != "sent":
        return None, str(result.get("message") or "Order not sent.")
    order = result.get("order") or {}
    fill = _number(order.get("price")) or fallback_price
    if fill is None:
        return None, "Order sent but no fill price available."
    return fill, ""


async def _fetch_vix(settings: Settings) -> float | None:
    if not settings.dhan_india_vix_security_id:
        return None
    try:
        dhan = DhanService(settings)
        data = await dhan.market_quotes_by_segment({INDEX_SEGMENT: [int(settings.dhan_india_vix_security_id)]})
        segment = data.get(INDEX_SEGMENT) or {}
        quote = segment.get(str(settings.dhan_india_vix_security_id)) or {}
        return _number(quote.get("last_price"))
    except Exception:
        return None


def _skip_dates(settings: Settings) -> set[str]:
    return {token.strip() for token in settings.credit_spread_skip_dates.split(",") if token.strip()}


def _record_once(meta_key: str, event_type: str, message: str, *, payload: dict[str, Any] | None = None) -> None:
    if db.get_meta(f"once_{meta_key}"):
        return
    db.set_meta(f"once_{meta_key}", now_ist().isoformat(timespec="seconds"))
    db.record_event(event_type, message, payload=payload)


async def _notify(settings: Settings, text: str) -> None:
    try:
        await TelegramNotifier(settings).send(text)
    except Exception:
        pass


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def get_state() -> dict[str, Any]:
    settings = get_settings()
    now = now_ist()
    holidays = holidays_from_settings(settings)
    front = _runtime.get("frontExpiry")
    open_position = db.get_open_position()

    remaining = None
    planned_exit = None
    reference_expiry = (open_position or {}).get("expiry") or front
    if reference_expiry:
        expiry_date = date.fromisoformat(reference_expiry)
        remaining = trading_days_after(now.date(), expiry_date, holidays)
        exit_day = planned_exit_date(expiry_date, settings.credit_spread_exit_trading_days_before_expiry, holidays)
        planned_exit = exit_day.isoformat() if exit_day else None

    return {
        "strategy": STRATEGY_LABEL,
        "mode": settings.credit_spread_mode,
        "monitorEnabled": settings.credit_spread_monitor_enabled,
        "now": now.isoformat(timespec="seconds"),
        "isTradingDay": is_trading_day(now.date(), holidays),
        "frontExpiry": front,
        "seriesStartDate": db.get_meta("series_start_date"),
        "remainingTradingDays": remaining,
        "plannedExitDate": (open_position or {}).get("plannedExitDate") or planned_exit,
        "openPosition": open_position,
        "mtm": _runtime.get("lastMtm"),
        "lastEvaluation": _runtime.get("lastEvaluation"),
        "lastError": _runtime.get("lastError"),
        "pendingSignals": db.get_pending_signals(),
        "positions": db.list_positions(limit=40),
        "events": db.list_events(limit=80),
        "config": {
            "lotSize": settings.credit_spread_lot_size,
            "lots": settings.credit_spread_lots,
            "capitalBase": settings.credit_spread_capital_base,
            "entryTime": settings.credit_spread_entry_time,
            "entryWindowEnd": settings.credit_spread_entry_window_end,
            "exitTime": settings.credit_spread_exit_time,
            "exitTradingDaysBeforeExpiry": settings.credit_spread_exit_trading_days_before_expiry,
            "hedgePremiumTarget": settings.credit_spread_hedge_premium_target,
            "minNetCredit": settings.credit_spread_min_net_credit,
            "minCreditWidthPercent": settings.credit_spread_min_credit_width_percent,
            "maxEntryVix": settings.credit_spread_max_entry_vix,
            "profitTargetPercent": settings.credit_spread_profit_target_percent,
            "hardStopCreditMultiple": settings.credit_spread_hard_stop_credit_multiple,
            "allowLateEntry": settings.credit_spread_allow_late_entry,
            "minEntryTradingDaysLeft": settings.credit_spread_min_entry_trading_days_left,
            "skipDates": sorted(_skip_dates(settings)),
            "paperAutoApprove": settings.credit_spread_paper_auto_approve,
            "liveOrderEnabled": settings.live_order_enabled,
        },
    }
