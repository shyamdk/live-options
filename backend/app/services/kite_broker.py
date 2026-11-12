"""Zerodha Kite Connect -- orders for the hedged NIFTY Strangle.

Plan: the free Personal plan (orders, order book, positions, margins). Market
data keeps coming from Dhan, so no paid Kite data subscription is needed.

Login: Kite has no API login; the access token comes from a browser login once
a day (it expires around 06:00 IST the next morning). With KITE_USER_ID /
KITE_PASSWORD / KITE_TOTP_SECRET set, auto_login() does that login in headless
Chromium (Playwright) every weekday morning -- Zerodha says the daily login
should be manual; the user chose to automate it anyway. Otherwise (or if it
fails) login_url() is sent on Telegram; after logging in, Kite redirects to /api/kite/callback with a
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
            "user": db.get_kite_setting("userName"), "loggedInAt": db.get_kite_setting("loggedInAt"),
            "autoLogin": auto_login_configured(), "autoLoginResult": db.get_kite_setting("auto.lastResult")}


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
    """Get today's token: automated login first, else Telegram the link (at most once an hour per reason)."""
    if not configured() or access_token():
        return
    if auto_login_configured():
        result = await auto_login(reason)
        if result.get("ok"):
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


# ---------------------------------------------------------------- automated daily login (Playwright)

_auto_lock = asyncio.Lock()


def auto_login_configured() -> bool:
    s = get_settings()
    return configured() and bool(s.kite_user_id and s.kite_password and s.kite_totp_secret)


async def auto_login(reason: str = "scheduled") -> dict[str, Any]:
    """Log in to Kite in headless Chromium: user id + password, then the TOTP, then (first
    time only) Authorize; the redirect's request_token is caught before it leaves the
    browser and exchanged here. At most one attempt per 3 minutes."""
    async with _auto_lock:
        if access_token():
            return {"ok": True, "note": "already logged in"}
        fail_key = f"auto.failures.{datetime.now(IST).date()}"
        if int(db.get_kite_setting(fail_key) or 0) >= 3:
            return {"ok": False, "note": "stopped after 3 failed attempts today (avoids a Zerodha lockout)"}
        last = db.get_kite_setting("auto.lastAttempt")
        if last and (datetime.now(IST) - datetime.fromisoformat(last)).total_seconds() < 180:
            return {"ok": False, "note": "last attempt under 3 minutes ago"}
        db.set_kite_setting("auto.lastAttempt", datetime.now(IST).isoformat(timespec="seconds"))
        try:
            token = await _browser_login()
            who = await complete_login(token)
        except Exception as exc:
            msg = f"{type(exc).__name__}: {str(exc)[:200]}"
            db.set_kite_setting("auto.lastResult", f"failed {datetime.now(IST):%d %b %H:%M} -- {msg}")
            failures = int(db.get_kite_setting(fail_key) or 0) + 1
            db.set_kite_setting(fail_key, str(failures))
            logger.warning("kite: auto login (%s) failed (%s today): %s", reason, failures, msg)
            if failures >= 3:
                from app.services.telegram import TelegramNotifier

                try:
                    await TelegramNotifier().send(f"🚨 Zerodha auto-login failed 3 times today ({msg}); stopped retrying. Log in manually: {login_url()}")
                except Exception:
                    pass
            return {"ok": False, "note": msg}
        db.set_kite_setting("auto.lastResult", f"ok {datetime.now(IST):%d %b %H:%M}")
        logger.info("kite: auto login (%s) ok", reason)
        return {"ok": True, "user": who.get("user")}


async def _browser_login() -> str:
    import os

    import pyotp

    s = get_settings()
    if s.playwright_browsers_path and os.path.isdir(s.playwright_browsers_path):
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", s.playwright_browsers_path)
    from playwright.async_api import async_playwright

    captured: dict[str, str] = {}

    async def catch(route) -> None:
        url = httpx.URL(route.request.url)
        captured["token"] = url.params.get("request_token") or ""
        captured["status"] = url.params.get("status") or ""
        await route.fulfill(status=200, content_type="text/html", body="ok")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.route("**/api/kite/callback*", catch)
            await page.goto(login_url(), timeout=30000)
            await page.fill("#userid", s.kite_user_id)
            await page.fill("#password", s.kite_password)
            await page.click("button[type=submit]")
            otp = page.locator("input[type=number], input[maxlength='6'], input[autocomplete='one-time-code']").first
            await otp.wait_for(state="visible", timeout=20000)
            totp = pyotp.TOTP(s.kite_totp_secret.replace(" ", ""))
            if totp.interval - (int(datetime.now().timestamp()) % totp.interval) < 4:
                await asyncio.sleep(5)  # don't type a code that is about to roll over
            await otp.fill(totp.now())
            submit = page.locator("button[type=submit]")
            if await submit.count() and await submit.first.is_enabled():
                try:
                    await submit.first.click(timeout=3000)
                except Exception:
                    pass  # Kite usually submits by itself after 6 digits
            for _ in range(40):
                if captured.get("token"):
                    break
                auth = page.get_by_role("button", name="Authorize")
                if await auth.count():
                    await auth.first.click()
                err = page.locator(".error, .su-message.error, .text-red")
                if await err.count() and (await err.first.inner_text()).strip():
                    raise KiteError(f"Kite login page says: {(await err.first.inner_text()).strip()[:150]}")
                await asyncio.sleep(0.5)
        finally:
            await browser.close()
    if captured.get("status") not in ("", "success") or not captured.get("token"):
        raise KiteError("no request_token after login (Kite page layout may have changed)")
    return captured["token"]


async def _loop() -> None:
    """Weekday mornings at kite_auto_login_time IST (and on start-up during market hours)."""
    from app.core.sessions import weekday_open

    while True:
        try:
            now = datetime.now(IST)
            start = datetime.strptime(get_settings().kite_auto_login_time, "%H:%M").time()
            if (auto_login_configured() and weekday_open(now) and start <= now.time() <= datetime.strptime("15:30", "%H:%M").time()
                    and not access_token()):
                await auto_login("scheduled")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("kite: auto-login loop failed")
        await asyncio.sleep(60)


def start_kite_task() -> asyncio.Task | None:
    return asyncio.create_task(_loop())


async def stop_kite_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return
