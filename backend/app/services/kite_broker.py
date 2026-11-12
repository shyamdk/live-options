"""Zerodha Kite Connect -- orders for the hedged NIFTY Strangle.

Plan: the free Personal plan (orders, order book, positions, margins). Market
data keeps coming from Dhan, so no paid Kite data subscription is needed.

Login: Kite has no API login; the access token comes from a browser login once
a day (it expires around 06:00 IST the next morning). login_url() is sent on
Telegram; after logging in, Kite redirects to /api/kite/callback with a
request_token, which complete_login() exchanges (checksum = sha256(api_key +
request_token + api_secret)). The token is stored in kite_settings.

Orders: exchange NFO, product NRML (carried overnight), LIMIT priced through
the quote (Kite rejects market orders without market protection), polled until
COMPLETE; an order still open after ~12 s is cancelled and re-priced, up to 3
times. Order endpoints need the server's static IP registered on the Kite
developer console.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import logging
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.core.config import get_settings
from app.db import sqlite as db

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
BASE = "https://api.kite.trade"
LOGIN = "https://kite.zerodha.com/connect/login?v=3&api_key={key}"
_instruments: dict[str, Any] = {"day": None, "rows": {}}


class KiteError(RuntimeError):
    pass


def configured() -> bool:
    s = get_settings()
    return bool(s.kite_api_key and s.kite_api_secret)


def login_url() -> str | None:
    s = get_settings()
    return LOGIN.format(key=s.kite_api_key) if s.kite_api_key else None


def _token_day() -> str:
    """Kite tokens die around 06:00 IST: a token is good for the 'trading day' that starts then."""
    now = datetime.now(IST)
    return (now - timedelta(hours=6)).date().isoformat()


def access_token() -> str | None:
    if db.get_kite_setting("tokenDay") != _token_day():
        return None
    return db.get_kite_setting("accessToken")


def status() -> dict[str, Any]:
    return {"configured": configured(), "connected": bool(access_token()), "loginUrl": login_url(),
            "user": db.get_kite_setting("userName"), "loggedInAt": db.get_kite_setting("loggedInAt")}


async def complete_login(request_token: str) -> dict[str, Any]:
    s = get_settings()
    if not configured():
        raise KiteError("KITE_API_KEY / KITE_API_SECRET are not set on the server.")
    checksum = hashlib.sha256(f"{s.kite_api_key}{request_token}{s.kite_api_secret}".encode()).hexdigest()
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{BASE}/session/token", headers={"X-Kite-Version": "3"},
                              data={"api_key": s.kite_api_key, "request_token": request_token, "checksum": checksum})
    body = r.json() if r.content else {}
    if r.is_error or body.get("status") != "success":
        raise KiteError(f"Kite login failed: {body.get('message') or r.status_code}")
    data = body["data"]
    db.set_kite_setting("accessToken", data["access_token"])
    db.set_kite_setting("tokenDay", _token_day())
    db.set_kite_setting("userName", str(data.get("user_name") or data.get("user_id") or ""))
    db.set_kite_setting("loggedInAt", datetime.now(IST).isoformat(timespec="seconds"))
    return {"user": data.get("user_name") or data.get("user_id")}


async def _call(method: str, path: str, data: dict[str, Any] | None = None, *, raw: bool = False) -> Any:
    token = access_token()
    if not token:
        raise KiteError("Not logged in to Kite today -- open the Zerodha login link.")
    s = get_settings()
    headers = {"X-Kite-Version": "3", "Authorization": f"token {s.kite_api_key}:{token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.request(method, f"{BASE}{path}", headers=headers, data=data)
    if raw:
        if r.is_error:
            raise KiteError(f"Kite {path}: HTTP {r.status_code}")
        return r.text
    body = r.json() if r.content else {}
    if r.status_code == 403 and body.get("error_type") == "TokenException":
        db.set_kite_setting("tokenDay", "")
        raise KiteError("Kite session expired -- log in again.")
    if r.is_error or body.get("status") != "success":
        raise KiteError(f"Kite {method} {path}: {body.get('message') or r.status_code}")
    return body.get("data")


async def margins() -> dict[str, Any]:
    data = await _call("GET", "/user/margins")
    eq = (data or {}).get("equity") or {}
    avail = eq.get("available") or {}
    return {"net": eq.get("net"), "cash": avail.get("live_balance") or avail.get("cash"), "collateral": avail.get("collateral"),
            "used": (eq.get("utilised") or {}).get("debits")}


async def positions() -> list[dict[str, Any]]:
    data = await _call("GET", "/portfolio/positions")
    return (data or {}).get("net") or []


async def _load_instruments() -> dict[tuple[str, float, str], str]:
    today = datetime.now(IST).date().isoformat()
    if _instruments["day"] == today and _instruments["rows"]:
        return _instruments["rows"]
    text = await _call("GET", "/instruments/NFO", raw=True)
    rows: dict[tuple[str, float, str], str] = {}
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("name") == "NIFTY" and r.get("instrument_type") in ("CE", "PE"):
            rows[(r["expiry"], float(r["strike"]), r["instrument_type"])] = r["tradingsymbol"]
    _instruments.update(day=today, rows=rows)
    return rows


async def nifty_option_symbol(expiry: date, strike: float, side: str) -> str:
    rows = await _load_instruments()
    sym = rows.get((expiry.isoformat(), float(strike), side))
    if not sym:
        raise KiteError(f"No Kite NFO symbol for NIFTY {expiry} {strike:g} {side}")
    return sym


def _tick(price: float) -> float:
    return round(round(price / 0.05) * 0.05, 2)


async def place_limit_order(*, symbol: str, side: str, qty: int, price: float, tag: str) -> str:
    data = await _call("POST", "/orders/regular", {
        "tradingsymbol": symbol, "exchange": "NFO", "transaction_type": side, "order_type": "LIMIT", "quantity": qty,
        "product": "NRML", "price": f"{_tick(max(price, 0.05)):.2f}", "validity": "DAY", "tag": tag[:20],
    })
    return str(data["order_id"])


async def order_state(order_id: str) -> dict[str, Any]:
    hist = await _call("GET", f"/orders/{order_id}")
    return (hist or [{}])[-1]


async def cancel(order_id: str) -> None:
    try:
        await _call("DELETE", f"/orders/regular/{order_id}")
    except KiteError as exc:
        logger.warning("kite: cancel %s failed: %s", order_id, exc)


async def execute(*, symbol: str, side: str, qty: int, quote: dict[str, Any] | None, tag: str,
                  requote=None) -> dict[str, Any]:
    """Marketable LIMIT order, re-priced up to 3 times. requote() -> fresh quote dict (bid/ask/ltp)."""
    filled_qty, value, order_ids, note = 0, 0.0, [], None
    for attempt in range(3):
        q = quote if attempt == 0 or requote is None else (await requote() or quote)
        bid, ask, ltp = (q or {}).get("bid"), (q or {}).get("ask"), (q or {}).get("ltp")
        ref = (ask if side == "BUY" else bid) or ltp
        if not ref:
            return {"ok": False, "price": None, "orderId": None, "note": "no quote to price the order"}
        pad = max(0.5, ref * (0.05 + 0.05 * attempt))
        price = ref + pad if side == "BUY" else max(ref - pad, 0.05)
        remaining = qty - filled_qty
        try:
            oid = await place_limit_order(symbol=symbol, side=side, qty=remaining, price=price, tag=f"{tag}{attempt}")
        except KiteError as exc:
            note = str(exc)
            await asyncio.sleep(1)
            continue
        order_ids.append(oid)
        state: dict[str, Any] = {}
        for _ in range(12):
            await asyncio.sleep(1)
            try:
                state = await order_state(oid)
            except KiteError:
                continue
            if state.get("status") in ("COMPLETE", "REJECTED", "CANCELLED"):
                break
        done = int(state.get("filled_quantity") or 0)
        if done:
            filled_qty += done
            value += done * float(state.get("average_price") or price)
        if state.get("status") == "REJECTED":
            note = f"rejected: {state.get('status_message')}"
            break
        if filled_qty >= qty:
            break
        if state.get("status") not in ("COMPLETE", "CANCELLED"):
            await cancel(oid)
            await asyncio.sleep(1)
            try:
                st = await order_state(oid)
                extra = int(st.get("filled_quantity") or 0) - done
                if extra > 0:
                    filled_qty += extra
                    value += extra * float(st.get("average_price") or price)
            except KiteError:
                pass
        if filled_qty >= qty:
            break
    if filled_qty <= 0:
        return {"ok": False, "price": None, "orderId": ",".join(order_ids) or None, "note": note or "not filled"}
    avg = value / filled_qty
    return {"ok": filled_qty >= qty, "price": round(avg, 2), "orderId": ",".join(order_ids), "filledQty": filled_qty,
            "note": None if filled_qty >= qty else f"only {filled_qty}/{qty} filled -- check Kite"}


async def remind_login(reason: str) -> None:
    """Telegram the login link (at most once per hour per reason)."""
    if not configured() or access_token():
        return
    key = f"remind.{reason}.{datetime.now(IST):%Y-%m-%d %H}"
    if db.get_kite_setting(key):
        return
    db.set_kite_setting(key, "1")
    from app.services.telegram import TelegramNotifier

    try:
        await TelegramNotifier().send(f"🔑 Zerodha login needed ({reason}): {login_url()}\nLog in once; the app takes it from there for today.")
    except Exception:
        logger.warning("kite: telegram reminder failed")
