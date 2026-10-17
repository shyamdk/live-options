"""Price alerts and date reminders, shown as a portal-wide alarm and sent on
Telegram.

  price     symbol + direction (below / above) + price -- checked every 30 s
            in market hours against live Dhan quotes (LTP)
  reminder  remind_at (epoch) + note -- checked every 30 s, any time

Lifecycle: active -> triggered (Telegram sent, portal alarm until it is
acknowledged) -> acknowledged. Dismissed alerts are switched off by hand.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.market_calendar import holidays_from_settings, is_trading_day
from app.db import sqlite as db
from app.services.dhan import DhanService
from app.services.telegram import TelegramNotifier

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
POLL_SECONDS = 30


def _ist(epoch: int | None) -> str:
    return datetime.fromtimestamp(epoch, IST).strftime("%d %b %Y %H:%M") if epoch else "—"


def summarize(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"], "kind": row["kind"], "symbol": row["symbol"], "securityId": row["security_id"],
        "segment": row["segment"], "direction": row["direction"], "price": row["price"], "remindAt": row["remind_at"],
        "note": row["note"], "source": row["source"], "status": row["status"], "createdAt": row["created_at"],
        "triggeredAt": row["triggered_at"], "triggerPrice": row["trigger_price"],
        "telegramSent": None if row["telegram_sent"] is None else bool(row["telegram_sent"]),
        "acknowledgedAt": row["acknowledged_at"],
    }


def list_all() -> dict[str, Any]:
    rows = [summarize(r) for r in db.list_alerts()]
    return {
        "active": [r for r in rows if r["status"] == "active"],
        "pending": [r for r in rows if r["status"] == "triggered"],  # triggered, not yet acknowledged
        "history": [r for r in rows if r["status"] in ("acknowledged", "dismissed")][:100],
    }


def create(payload: dict[str, Any]) -> dict[str, Any]:
    kind = payload.get("kind")
    now = int(time.time())
    note = (payload.get("note") or "").strip()[:500] or None
    if kind == "price":
        price = float(payload.get("price") or 0)
        direction = payload.get("direction")
        if price <= 0 or direction not in ("below", "above"):
            raise ValueError("A price alert needs a positive price and direction below/above.")
        if not payload.get("securityId") or not payload.get("symbol"):
            raise ValueError("Pick a stock for the price alert.")
        alert_id = db.create_alert(kind="price", symbol=str(payload["symbol"]).upper(), security_id=str(payload["securityId"]),
                                   segment=payload.get("segment") or "NSE_EQ", direction=direction, price=price, note=note,
                                   source=payload.get("source") or "manual", status="active", created_at=now)
    elif kind == "reminder":
        remind_at = int(payload.get("remindAt") or 0)
        if remind_at <= 0 or not note:
            raise ValueError("A reminder needs a date/time and a message.")
        alert_id = db.create_alert(kind="reminder", symbol=(payload.get("symbol") or None), remind_at=remind_at, note=note,
                                   source=payload.get("source") or "manual", status="active", created_at=now)
    else:
        raise ValueError("kind must be price or reminder")
    return summarize(next(r for r in db.list_alerts() if r["id"] == alert_id))


def set_status(alert_id: int, action: str) -> dict[str, Any]:
    row = next((r for r in db.list_alerts() if r["id"] == alert_id), None)
    if not row:
        raise ValueError("Alert not found.")
    now = int(time.time())
    if action == "acknowledge":
        db.update_alert(alert_id, status="acknowledged", acknowledged_at=now)
    elif action == "dismiss":
        db.update_alert(alert_id, status="dismissed", acknowledged_at=now)
    elif action == "rearm":
        db.update_alert(alert_id, status="active", triggered_at=None, trigger_price=None, telegram_sent=None, acknowledged_at=None)
    else:
        raise ValueError("action must be acknowledge, dismiss or rearm")
    return summarize(next(r for r in db.list_alerts() if r["id"] == alert_id))


def _market_open(now: datetime) -> bool:
    minutes = now.hour * 60 + now.minute
    return is_trading_day(now.date(), holidays_from_settings(get_settings())) and 9 * 60 + 15 <= minutes <= 15 * 60 + 30


def _message(row: dict[str, Any], ltp: float | None) -> str:
    if row["kind"] == "price":
        arrow = "≤" if row["direction"] == "below" else "≥"
        text = f"🔔 Price alert: {row['symbol']} at {ltp:,.2f} ({arrow} {row['price']:,.2f})"
    else:
        text = f"⏰ Reminder ({_ist(row['remind_at'])})" + (f" -- {row['symbol']}" if row["symbol"] else "")
    if row["note"]:
        text += f"\n{row['note']}"
    return text


async def _trigger(row: dict[str, Any], ltp: float | None) -> None:
    now = int(time.time())
    db.update_alert(row["id"], status="triggered", triggered_at=now, trigger_price=ltp)
    sent = await TelegramNotifier().send(_message(row, ltp))
    db.update_alert(row["id"], telegram_sent=1 if sent else 0)
    logger.warning("alerts: #%s %s triggered (telegram %s)", row["id"], row["kind"], "sent" if sent else "NOT sent")


async def check_once() -> list[int]:
    active = db.list_alerts(status="active")
    if not active:
        return []
    now = datetime.now(IST)
    fired = []
    for row in active:
        if row["kind"] == "reminder" and row["remind_at"] and row["remind_at"] <= now.timestamp():
            await _trigger(row, None)
            fired.append(row["id"])
    prices = [r for r in active if r["kind"] == "price"]
    if prices and _market_open(now):
        by_segment: dict[str, list[int]] = {}
        for r in prices:
            by_segment.setdefault(r["segment"] or "NSE_EQ", []).append(int(r["security_id"]))
        quotes = await DhanService(get_settings()).market_quotes_by_segment({k: sorted(set(v)) for k, v in by_segment.items()})
        for r in prices:
            q = (quotes.get(r["segment"] or "NSE_EQ") or {}).get(str(r["security_id"])) or {}
            ltp = q.get("last_price")
            if not ltp:
                continue
            ltp = float(ltp)
            if (r["direction"] == "below" and ltp <= r["price"]) or (r["direction"] == "above" and ltp >= r["price"]):
                await _trigger(r, ltp)
                fired.append(r["id"])
    return fired


async def _loop() -> None:
    while True:
        try:
            await check_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("alerts: check failed")
        await asyncio.sleep(POLL_SECONDS)


def start_alerts_task() -> asyncio.Task | None:
    if not get_settings().alerts_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_alerts_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return
