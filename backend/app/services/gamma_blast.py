"""Gamma Blast orchestration: session lifecycle, signal alerting/throttling,
and the only code path that ever places an order (paper simulation or real
Dhan order) — always behind approve_gamma_blast_signal, which the background
loop only calls itself when PAPER mode has auto-approve on; LIVE mode always
waits for the API-triggered manual click.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

from app.core.config import Settings, get_settings
from app.core.timeutil import in_time_window, now_ist
from app.db import gamma_blast as db
from app.services.dhan import DhanService
from app.services.dhan_ws import DhanWsClient
from app.services.gamma_blast_engine import (
    StrikeState,
    calculate_quantity,
    check_breakouts,
    evaluate_exit,
    find_walls,
    quiet_day_status,
    strike_dicts,
)
from app.services.gamma_blast_instruments import (
    INDEX_SEGMENT,
    expiry_weekday_for,
    fetch_strike_states,
    lot_size_for,
    resolve_todays_expiry,
    strike_step_for,
    underlying_scrip_for,
)
from app.services.orders import DhanOrderService
from app.services.telegram import TelegramNotifier

INDICES = ("NIFTY", "SENSEX")
EXCHANGE_SEGMENT = "NSE_FNO"

_active: dict[str, dict[str, Any]] = {}
_last_alert_at: dict[str, float] = {}
_scheduler_task: asyncio.Task | None = None


def start_gamma_blast_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.gamma_blast_monitor_enabled:
        return None
    return asyncio.create_task(_scheduler_loop())


async def stop_gamma_blast_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    for index_symbol in list(_active.keys()):
        await _end_session(index_symbol)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def _scheduler_loop() -> None:
    settings = get_settings()
    interval = max(settings.gamma_blast_evaluation_interval_seconds, 1)
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
    for index_symbol in INDICES:
        session = _active.get(index_symbol)
        in_hours = in_time_window(now.time(), settings.gamma_blast_session_start_time, settings.gamma_blast_session_end_time)

        if session is None and in_hours:
            await _maybe_start_session(settings, index_symbol, now)
            continue

        if session is not None and not in_hours:
            await _end_session(index_symbol)
            continue

        if session is not None:
            await _evaluate_session(settings, index_symbol, now)


async def _maybe_start_session(settings: Settings, index_symbol: str, now: datetime) -> None:
    if now.weekday() != expiry_weekday_for(index_symbol, settings):
        return

    dhan = DhanService(settings)
    underlying_scrip = underlying_scrip_for(index_symbol, settings)
    expiry = await resolve_todays_expiry(dhan, underlying_scrip, today=now.date())
    if not expiry:
        return

    strike_step = strike_step_for(index_symbol, settings)
    spot, strikes = await fetch_strike_states(
        dhan,
        underlying_scrip=underlying_scrip,
        expiry=expiry,
        strike_step=strike_step,
        strike_range=settings.gamma_blast_strike_range,
    )
    if not strikes or spot <= 0:
        return

    session_id = f"{now.date().isoformat()}:{index_symbol}"
    db.upsert_session(
        session_id,
        session_date=now.date().isoformat(),
        index_symbol=index_symbol,
        mode=settings.gamma_blast_mode,
        status="RUNNING",
        spot_open=spot,
    )
    db.record_event(session_id, "SESSION_START", f"{index_symbol} session started, spot {spot:g}, expiry {expiry}")

    full_mode_instruments = [(EXCHANGE_SEGMENT, s.security_id) for s in strikes]
    quote_mode_instruments = [(INDEX_SEGMENT, str(underlying_scrip))]
    ws_client = DhanWsClient()
    ws_client.start(settings, full_mode_instruments, quote_mode_instruments)

    _active[index_symbol] = {
        "sessionId": session_id,
        "expiry": expiry,
        "sessionOpen": spot,
        "strikes": {s.security_id: s for s in strikes},
        "strikeStep": strike_step,
        "wsClient": ws_client,
        "breakoutSides": set(),
    }


async def _end_session(index_symbol: str) -> None:
    session = _active.pop(index_symbol, None)
    if not session:
        return
    await session["wsClient"].stop()
    db.upsert_session(session["sessionId"], session_date=session["sessionId"].split(":")[0], index_symbol=index_symbol, mode=get_settings().gamma_blast_mode, status="COMPLETED")
    db.record_event(session["sessionId"], "SESSION_END", f"{index_symbol} session ended")
    from app.services.gamma_blast_retrospective import generate_retrospective

    try:
        await generate_retrospective(session["sessionId"])
    except Exception as exc:
        db.record_event(session["sessionId"], "RETROSPECTIVE_FAILED", f"Retrospective generation failed: {exc}")


def _compute_snapshot(settings: Settings, index_symbol: str) -> dict[str, Any] | None:
    session = _active.get(index_symbol)
    if not session:
        return None
    live_state = session["wsClient"].get_all_state()

    strikes: list[StrikeState] = []
    spot = None
    for security_id, strike in session["strikes"].items():
        live = live_state.get(security_id)
        ltp = live["ltp"] if live else strike.ltp
        oi = live["oi"] if live else strike.oi
        strikes.append(
            StrikeState(
                strike.strike,
                strike.option_side,
                security_id,
                ltp,
                oi,
                strike.delta,
                strike.gamma,
                strike.theta,
                strike.vega,
                strike.iv,
            )
        )

    index_live = live_state.get(str(underlying_scrip_for(index_symbol, settings)))
    if index_live and index_live.get("ltp"):
        spot = index_live["ltp"]
    if spot is None:
        return {"spot": None, "walls": None, "quiet": None, "liveState": live_state}

    quiet = quiet_day_status(spot, session["sessionOpen"], settings.gamma_blast_quiet_day_max_percent)
    walls = find_walls(
        strikes,
        spot,
        strike_step=session["strikeStep"],
        strike_range=settings.gamma_blast_strike_range,
        min_oi_threshold=settings.gamma_blast_min_oi_threshold,
    )
    strikes.sort(key=lambda s: (s.strike, s.option_side))
    return {
        "spot": spot,
        "walls": walls,
        "quiet": quiet,
        "liveState": live_state,
        "strikes": strike_dicts(strikes, spot),
    }


async def _maybe_reconcile_greeks(settings: Settings, index_symbol: str, session: dict[str, Any]) -> None:
    """Dhan's WebSocket feed never carries Greeks (only LTP/OI) — periodically
    re-pull the REST option chain (rate-limited to 1 req/3s, enforced in
    DhanService._option_chain_request) to keep delta/gamma/theta/vega fresh.
    WS ticks remain the source of truth for LTP/OI in _compute_snapshot.
    """
    last = session.get("lastReconciliation", 0.0)
    if time.monotonic() - last < settings.gamma_blast_reconciliation_interval_seconds:
        return
    session["lastReconciliation"] = time.monotonic()
    try:
        dhan = DhanService(settings)
        underlying_scrip = underlying_scrip_for(index_symbol, settings)
        _, strikes = await fetch_strike_states(
            dhan,
            underlying_scrip=underlying_scrip,
            expiry=session["expiry"],
            strike_step=session["strikeStep"],
            strike_range=settings.gamma_blast_strike_range,
        )
        for strike in strikes:
            session["strikes"][strike.security_id] = strike
    except Exception:
        pass


async def _evaluate_session(settings: Settings, index_symbol: str, now: datetime) -> None:
    session = _active[index_symbol]
    session_id = session["sessionId"]

    await _maybe_reconcile_greeks(settings, index_symbol, session)

    snapshot = _compute_snapshot(settings, index_symbol)
    if not snapshot or snapshot["spot"] is None:
        return
    session["lastSnapshot"] = snapshot
    spot = snapshot["spot"]
    walls = snapshot["walls"]
    quiet = snapshot["quiet"]
    live_state = snapshot["liveState"]

    await _evaluate_exits(settings, index_symbol, session_id, live_state, now)

    entry_window_ok = in_time_window(now.time(), settings.gamma_blast_entry_window_start, settings.gamma_blast_entry_window_end)
    if quiet["isQuiet"] and entry_window_ok:
        breakouts = check_breakouts(spot, walls["callWall"], walls["putWall"], buffer_points=settings.gamma_blast_wall_buffer_points)
        for breakout in breakouts:
            if breakout["side"] in session["breakoutSides"]:
                continue
            await _raise_entry_signal(settings, index_symbol, session_id, breakout)
            session["breakoutSides"].add(breakout["side"])


async def _raise_entry_signal(settings: Settings, index_symbol: str, session_id: str, breakout: dict[str, Any]) -> None:
    lot_size = lot_size_for(index_symbol, settings)
    premium = _strike_ltp(index_symbol, breakout["securityId"]) or breakout.get("wallLtp") or 0
    qty = calculate_quantity(
        capital_base=settings.gamma_blast_capital_base,
        risk_percent=settings.gamma_blast_risk_percent_per_trade,
        premium=premium,
        lot_size=lot_size,
        max_lots=settings.gamma_blast_max_lots_per_trade,
    )
    signal_id = db.record_signal(
        session_id,
        index_symbol=index_symbol,
        kind=f"ENTRY_{breakout['side']}",
        status="PENDING",
        strike=breakout["strike"],
        option_side=breakout["side"],
        trigger_price=breakout["spotAtTrigger"],
        level=breakout["strike"],
        payload={**breakout, "quantity": qty, "securityId": breakout["securityId"]},
    )
    db.record_event(
        session_id,
        "BREAKOUT",
        f"{index_symbol} {breakout['side']} wall {breakout['strike']:g} broken, spot {breakout['spotAtTrigger']:g} — signal #{signal_id}",
        breakout,
    )
    await _alert_and_maybe_auto_approve(settings, signal_id, session_id, index_symbol, "entry")


async def _evaluate_exits(
    settings: Settings, index_symbol: str, session_id: str, live_state: dict[str, dict[str, Any]], now: datetime
) -> None:
    for trade in db.get_open_trades(session_id):
        if trade["securityId"] is None or trade["entryPrice"] is None or trade["entryAt"] is None:
            continue
        live = live_state.get(str(trade["securityId"]))
        ltp = live["ltp"] if live else None
        if ltp is None:
            continue
        entry_at = datetime.fromisoformat(trade["entryAt"])
        exit_check = evaluate_exit(
            entry_price=trade["entryPrice"],
            ltp=ltp,
            entry_at=entry_at,
            now=now,
            scale_out_percent=settings.gamma_blast_scale_out_percent,
            hard_stop_percent=settings.gamma_blast_hard_stop_percent,
            blast_failed_minutes=settings.gamma_blast_blast_failed_minutes,
            force_exit_time=settings.gamma_blast_force_exit_time,
            already_scaled_out=False,
        )
        if not exit_check:
            continue

        pending = [
            s
            for s in db.get_pending_signals(session_id)
            if s["kind"] == "EXIT" and s["tradeId"] == trade["id"]
        ]
        if pending:
            continue

        signal_id = db.record_signal(
            session_id,
            index_symbol=index_symbol,
            kind="EXIT",
            status="PENDING",
            strike=trade["strike"],
            option_side=trade["optionSide"],
            trigger_price=ltp,
            level=trade["entryPrice"],
            payload={"tradeId": trade["id"], "exitReason": exit_check["reason"], "changePercent": exit_check["changePercent"], "ltp": ltp},
        )
        db.update_signal_status(signal_id, "PENDING", trade_id=trade["id"])
        db.record_event(
            session_id,
            "EXIT_SIGNAL",
            f"{index_symbol} {trade['optionSide']} {trade['strike']:g} exit signal ({exit_check['reason']}, {exit_check['changePercent']:+.1f}%) — signal #{signal_id}",
            exit_check,
        )
        await _alert_and_maybe_auto_approve(settings, signal_id, session_id, index_symbol, "exit")


async def _alert_and_maybe_auto_approve(
    settings: Settings, signal_id: int, session_id: str, index_symbol: str, phase: str
) -> None:
    await _send_alert(settings, signal_id, session_id, index_symbol, phase)
    if settings.gamma_blast_mode == "PAPER" and settings.gamma_blast_paper_auto_approve:
        await approve_gamma_blast_signal(signal_id)


async def _send_alert(settings: Settings, signal_id: int, session_id: str, index_symbol: str, phase: str) -> None:
    key = f"{session_id}:{signal_id}"
    last = _last_alert_at.get(key, 0.0)
    now_monotonic = time.monotonic()
    if now_monotonic - last < settings.gamma_blast_alert_repeat_seconds:
        return
    _last_alert_at[key] = now_monotonic

    signal = db.get_signal(signal_id)
    if not signal:
        return
    label = f"{index_symbol} {signal.get('optionSide') or ''} {signal.get('strike') or ''}".strip()
    lines = [
        f"⚡ Gamma Blast {phase.upper()} signal — approval needed",
        label,
        f"Kind: {signal['kind']}, Level: {signal.get('level')}, Trigger: {signal.get('triggerPrice')}",
        f"Mode: {settings.gamma_blast_mode}",
    ]
    await TelegramNotifier(settings).send("\n".join(lines))


async def approve_gamma_blast_signal(signal_id: int) -> dict[str, Any]:
    settings = get_settings()
    signal = db.get_signal(signal_id)
    if not signal:
        return {"status": "blocked", "message": "Signal not found."}
    if signal["status"] != "PENDING":
        return {"status": "blocked", "message": f"Signal already {signal['status']}."}

    if signal["kind"].startswith("ENTRY_"):
        return await _approve_entry(settings, signal)
    return await _approve_exit(settings, signal)


async def _approve_entry(settings: Settings, signal: dict[str, Any]) -> dict[str, Any]:
    payload = signal["payload"] or {}
    security_id = payload.get("securityId")
    quantity = int(payload.get("quantity") or 0)
    if not security_id or quantity <= 0:
        db.update_signal_status(signal["id"], "REJECTED")
        return {"status": "blocked", "message": "Missing security id or zero sized quantity."}

    order_side = "BUY"
    fill_price, order_status, order_message = await _place_or_simulate(
        settings,
        index_symbol=signal["indexSymbol"],
        transaction_type=order_side,
        security_id=str(security_id),
        quantity=quantity,
        correlation_id=f"GB-ENTRY-{signal['id']}",
    )
    if fill_price is None:
        db.update_signal_status(signal["id"], "FAILED")
        db.record_event(signal["sessionId"], "ENTRY_FAILED", f"Entry order failed: {order_message}")
        return {"status": "failed", "message": order_message}

    trade_id = f"GB-{signal['indexSymbol']}-{signal.get('strike')}-{signal.get('optionSide')}-{signal['id']}"
    db.insert_trade(
        trade_id,
        session_id=signal["sessionId"],
        index_symbol=signal["indexSymbol"],
        strike=signal.get("strike"),
        option_side=signal.get("optionSide"),
        security_id=str(security_id),
        exchange_segment=EXCHANGE_SEGMENT,
        mode=settings.gamma_blast_mode,
        entry_signal_id=signal["id"],
        payload=payload,
    )
    db.record_entry_fill(trade_id, entry_price=fill_price, entry_qty=quantity)
    db.update_signal_status(signal["id"], "APPROVED", trade_id=trade_id)
    db.record_event(signal["sessionId"], "ENTRY_FILLED", f"Entry filled {trade_id} at {fill_price:g} qty {quantity}")
    await TelegramNotifier(settings).send(f"✅ Gamma Blast entry filled: {trade_id} at {fill_price:g} x{quantity} ({order_status})")
    return {"status": order_status, "tradeId": trade_id, "fillPrice": fill_price, "quantity": quantity}


async def _approve_exit(settings: Settings, signal: dict[str, Any]) -> dict[str, Any]:
    trade_id = signal.get("tradeId") or (signal["payload"] or {}).get("tradeId")
    trade = db.get_trade(trade_id) if trade_id else None
    if not trade or trade["status"] != "OPEN":
        db.update_signal_status(signal["id"], "REJECTED")
        return {"status": "blocked", "message": "Trade is not open."}

    quantity = int(trade["entryQty"] or 0)
    fill_price, order_status, order_message = await _place_or_simulate(
        settings,
        index_symbol=signal["indexSymbol"],
        transaction_type="SELL",
        security_id=str(trade["securityId"]),
        quantity=quantity,
        correlation_id=f"GB-EXIT-{signal['id']}",
    )
    if fill_price is None:
        db.update_signal_status(signal["id"], "FAILED")
        db.record_event(signal["sessionId"], "EXIT_FAILED", f"Exit order failed: {order_message}")
        return {"status": "failed", "message": order_message}

    realized_pnl = round((fill_price - (trade["entryPrice"] or 0)) * quantity, 2)
    exit_reason = str((signal["payload"] or {}).get("exitReason") or "MANUAL")
    db.record_exit_fill(trade_id, exit_price=fill_price, exit_qty=quantity, exit_reason=exit_reason, realized_pnl=realized_pnl)
    db.update_signal_status(signal["id"], "APPROVED")
    db.record_event(signal["sessionId"], "EXIT_FILLED", f"Exit filled {trade_id} at {fill_price:g}, P&L {realized_pnl:g} ({exit_reason})")
    await TelegramNotifier(settings).send(f"✅ Gamma Blast exit filled: {trade_id} at {fill_price:g}, P&L {realized_pnl:g} ({exit_reason})")
    return {"status": order_status, "tradeId": trade_id, "fillPrice": fill_price, "realizedPnl": realized_pnl}


async def _place_or_simulate(
    settings: Settings, *, index_symbol: str, transaction_type: str, security_id: str, quantity: int, correlation_id: str
) -> tuple[float | None, str, str | None]:
    ws_client = _get_ws_client(index_symbol)
    live = ws_client.get_state(security_id) if ws_client else None
    ltp = live["ltp"] if live else None

    if settings.gamma_blast_mode == "PAPER":
        if ltp is None:
            return None, "failed", "No live price available to simulate a paper fill."
        return ltp, "sent", None

    order_service = DhanOrderService(settings)
    result = await order_service.place_market_order(
        transaction_type=transaction_type,
        exchange_segment=EXCHANGE_SEGMENT,
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


def _get_ws_client(index_symbol: str) -> DhanWsClient | None:
    session = _active.get(index_symbol)
    return session["wsClient"] if session else None


def _strike_ltp(index_symbol: str, security_id: str) -> float | None:
    ws_client = _get_ws_client(index_symbol)
    live = ws_client.get_state(security_id) if ws_client else None
    return live["ltp"] if live else None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def get_state() -> dict[str, Any]:
    settings = get_settings()
    indices: dict[str, Any] = {}
    for index_symbol in INDICES:
        session = _active.get(index_symbol)
        if not session:
            indices[index_symbol] = {"status": "NOT_STARTED"}
            continue
        snapshot = session.get("lastSnapshot") or {}
        session_id = session["sessionId"]
        now = now_ist()
        indices[index_symbol] = {
            "status": "RUNNING",
            "sessionId": session_id,
            "expiry": session["expiry"],
            "sessionOpen": session["sessionOpen"],
            "wsConnected": session["wsClient"].is_connected(),
            "spot": snapshot.get("spot"),
            "walls": snapshot.get("walls"),
            "quietDay": snapshot.get("quiet"),
            "strikes": snapshot.get("strikes") or [],
            "entryWindowOk": in_time_window(now.time(), settings.gamma_blast_entry_window_start, settings.gamma_blast_entry_window_end),
            "entryWindow": f"{settings.gamma_blast_entry_window_start}-{settings.gamma_blast_entry_window_end}",
            "forceExitTime": settings.gamma_blast_force_exit_time,
            "pendingSignals": db.get_pending_signals(session_id),
            "openTrades": db.get_open_trades(session_id),
            "events": db.get_events_for_session(session_id, limit=100),
        }
    return {"mode": settings.gamma_blast_mode, "indices": indices}


def list_past_sessions(limit: int = 30) -> list[dict[str, Any]]:
    return db.list_sessions(limit=limit)


def get_session_detail(session_id: str) -> dict[str, Any] | None:
    session = db.get_session(session_id)
    if not session:
        return None
    return {
        "session": session,
        "signals": db.get_signals_for_session(session_id),
        "trades": db.get_trades_for_session(session_id),
        "events": db.get_events_for_session(session_id, limit=500),
        "retrospective": db.get_retrospective(session_id),
    }
