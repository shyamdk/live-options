"""Order-flow recorder -- research data collection (no signals, no orders).

There is no historical tick / order-flow data for NIFTY, so this records it live
from Dhan's market feed (Full packets: last trade, cumulative volume, total pending
buy / sell quantity, OI and 5-level depth) for the NIFTY near-month future and the
current weekly ATM +-3 strikes (CE + PE), re-centred when NIFTY moves 150+ points.

Every packet's new volume is classified as buyer- or seller-initiated: traded at or
above the previous best ask = buy, at or below the previous best bid = sell, between
them by the tick rule. Per instrument and minute it stores OHLC of the last trade,
volume, buy / sell volume (delta = buy - sell), the book's total buy / sell quantity,
best bid / ask size, average spread and OI; for the future also a footprint
(buy / sell volume per 1-point price). After a few months this lets us test whether
delta, imbalance or footprint patterns predict NIFTY / option moves -- the part of
"order-flow trading" that cannot be back-tested today.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
import struct
import time
from datetime import date, datetime, time as dtime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.core.config import get_settings
from app.core.sessions import weekday_open
from app.db import sqlite as db
from app.services import varaha
from app.services.dhan import DhanService
from app.services.dhan_auth import get_dhan_access_token

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
WSS_URL = "wss://api-feed.dhan.co"
SCRIP_MASTER = "https://images.dhan.co/api-data/api-scrip-master.csv"
STRIKES_EACH_SIDE = 3
RECENTRE_POINTS = 150
FUT_RE = re.compile(r"^NIFTY-[A-Za-z]{3}\d{4}-FUT$")

_state: dict[str, Any] = {"connected": False, "lastPacket": 0.0, "packets": 0, "instruments": {}, "centre": None, "day": None, "error": None}
_book: dict[str, dict[str, Any]] = {}  # security id -> previous packet + the minute being built
_pending_subs: list[tuple[str, str]] = []


# ---------------------------------------------------------------- instruments


async def _nifty_future() -> tuple[str, str] | None:
    """(security id, trading symbol) of the nearest NIFTY index future."""
    today = datetime.now(IST).date().isoformat()
    async with httpx.AsyncClient(timeout=120) as client:
        text = (await client.get(SCRIP_MASTER)).text
    best = None
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("SEM_EXM_EXCH_ID") == "NSE" and r.get("SEM_INSTRUMENT_NAME") == "FUTIDX" and FUT_RE.match(r.get("SEM_TRADING_SYMBOL", "")):
            exp = r["SEM_EXPIRY_DATE"][:10]
            if exp >= today and (best is None or exp < best[2]):
                best = (r["SEM_SMST_SECURITY_ID"], r["SEM_TRADING_SYMBOL"], exp)
    return (best[0], best[1]) if best else None


async def _atm_options() -> tuple[float, list[tuple[str, str]]]:
    """(spot, [(security id, label)]) for the current weekly ATM +- STRIKES_EACH_SIDE."""
    dhan = DhanService()
    scrip = get_settings().dhan_nifty_security_id
    today = datetime.now(IST).date()
    expiry = sorted(date.fromisoformat(x) for x in await dhan.expiry_list(scrip, "IDX_I") if date.fromisoformat(x) >= today)[0]
    chain = await dhan.option_chain(scrip, "IDX_I", expiry.isoformat())
    spot = varaha._number(chain.get("last_price")) or 0.0
    atm = round(spot / 50) * 50
    wanted = {atm + 50 * k for k in range(-STRIKES_EACH_SIDE, STRIKES_EACH_SIDE + 1)}
    out = []
    for row in varaha._trim_chain(chain, spot):
        if float(row["strike"]) in wanted:
            for side in ("ce", "pe"):
                q = row.get(side) or {}
                if q.get("securityId"):
                    out.append((str(q["securityId"]), f"NIFTY {expiry:%d%b} {float(row['strike']):.0f} {side.upper()}"))
    return spot, out


# ---------------------------------------------------------------- packets -> minutes


def _minute(ts: float) -> int:
    return int(ts // 60 * 60)


def _flush(sid: str, m: dict[str, Any]) -> None:
    inst = _state["instruments"].get(sid, {})
    db.orderflow_save_minute({
        "day": datetime.fromtimestamp(m["minute"], IST).date().isoformat(), "security_id": sid, "label": inst.get("label", sid),
        "kind": inst.get("kind", ""), "minute_ts": m["minute"], "open": m["open"], "high": m["high"], "low": m["low"], "close": m["close"],
        "volume": m["volume"], "buy_vol": m["buy"], "sell_vol": m["sell"], "book_buy": m["bookBuy"], "book_sell": m["bookSell"],
        "bid_qty": m["bidQty"], "ask_qty": m["askQty"], "spread": round(m["spreadSum"] / m["spreadN"], 3) if m["spreadN"] else None,
        "oi": m["oi"], "packets": m["packets"], "footprint": json.dumps(m["fp"]) if m["fp"] else None,
    })


def handle_packet(data: bytes, now: float | None = None) -> None:
    if len(data) < 162:
        return
    code, _len, _seg, security_id = struct.unpack("<BHBI", data[0:8])
    if code != 8:
        return
    now = now or time.time()
    sid = str(security_id)
    ltp, _ltq, _ltt, _atp, volume, total_sell, total_buy, oi = struct.unpack("<fHIfIIII", data[8:38])
    bid_qty, ask_qty, _bo, _ao, bid, ask = struct.unpack("<IIHHff", data[62:82])
    prev = _book.get(sid)
    minute = _minute(now)
    if prev and prev["minute"]["minute"] != minute:
        _flush(sid, prev["minute"])
        prev["minute"] = None
    m = prev["minute"] if prev and prev["minute"] else {
        "minute": minute, "open": ltp, "high": ltp, "low": ltp, "close": ltp, "volume": 0, "buy": 0, "sell": 0, "bookBuy": 0, "bookSell": 0,
        "bidQty": 0, "askQty": 0, "spreadSum": 0.0, "spreadN": 0, "oi": 0, "packets": 0, "fp": {},
    }
    m["high"], m["low"], m["close"] = max(m["high"], ltp), min(m["low"], ltp), ltp
    if prev and volume > prev["volume"]:
        dv = volume - prev["volume"]
        if prev["ask"] and ltp >= prev["ask"]:
            side = 1
        elif prev["bid"] and ltp <= prev["bid"]:
            side = -1
        else:
            side = 1 if ltp > prev["ltp"] else -1 if ltp < prev["ltp"] else prev.get("side", 1)
        m["volume"] += dv
        m["buy" if side == 1 else "sell"] += dv
        if _state["instruments"].get(sid, {}).get("kind") == "FUT":
            level = str(int(round(ltp)))
            cell = m["fp"].setdefault(level, [0, 0])
            cell[0 if side == 1 else 1] += dv
    else:
        side = prev.get("side", 1) if prev else 1
    m["bookBuy"], m["bookSell"], m["bidQty"], m["askQty"], m["oi"] = total_buy, total_sell, bid_qty, ask_qty, oi
    if bid > 0 and ask > 0:
        m["spreadSum"] += ask - bid
        m["spreadN"] += 1
    m["packets"] += 1
    _book[sid] = {"volume": volume, "ltp": ltp, "bid": bid, "ask": ask, "side": side, "minute": m}
    _state["lastPacket"] = now
    _state["packets"] += 1


def flush_stale(now: float | None = None) -> None:
    """Write minutes that have ended even if no new packet arrived for that instrument."""
    now = now or time.time()
    for sid, b in list(_book.items()):
        m = b.get("minute")
        if m and m["minute"] < _minute(now):
            _flush(sid, m)
            b["minute"] = None


# ---------------------------------------------------------------- feed loop


def _recording_window(now: datetime) -> bool:
    return weekday_open(now) and dtime(9, 14) <= now.time() <= dtime(15, 31)


async def _prepare_day() -> list[tuple[str, str]]:
    instruments: dict[str, dict[str, Any]] = {}
    fut = await _nifty_future()
    if fut:
        instruments[fut[0]] = {"label": fut[1], "kind": "FUT"}
    spot, opts = await _atm_options()
    for sid, label in opts:
        instruments[sid] = {"label": label, "kind": label[-2:]}
    _state.update(instruments=instruments, centre=spot, day=datetime.now(IST).date().isoformat())
    return [("NSE_FNO", sid) for sid in instruments]


async def _maybe_recentre() -> None:
    try:
        spot, opts = await _atm_options()
    except Exception:
        return
    if _state["centre"] and abs(spot - _state["centre"]) >= RECENTRE_POINTS:
        new = [(sid, label) for sid, label in opts if sid not in _state["instruments"]]
        for sid, label in new:
            _state["instruments"][sid] = {"label": label, "kind": label[-2:]}
            _pending_subs.append(("NSE_FNO", sid))
        _state["centre"] = spot


async def _subscribe(ws: Any, instruments: list[tuple[str, str]]) -> None:
    for i in range(0, len(instruments), 100):
        batch = instruments[i:i + 100]
        await ws.send(json.dumps({"RequestCode": 21, "InstrumentCount": len(batch),
                                  "InstrumentList": [{"ExchangeSegment": seg, "SecurityId": sid} for seg, sid in batch]}))


async def _session() -> None:
    import websockets

    settings = get_settings()
    subs = await _prepare_day()
    attempt = 0
    while _recording_window(datetime.now(IST)):
        try:
            token = await get_dhan_access_token(settings, force_refresh=attempt > 0)
            url = f"{WSS_URL}?version=2&token={token}&clientId={settings.resolved_dhan_client_id}&authType=2"
            async with websockets.connect(url, ping_interval=20, ping_timeout=10, close_timeout=5, max_size=None) as ws:
                _state.update(connected=True, error=None)
                attempt = 0
                await _subscribe(ws, subs + list(_pending_subs))
                last_flush = last_recentre = time.time()
                while _recording_window(datetime.now(IST)):
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=5)
                        if isinstance(message, bytes):
                            handle_packet(message)
                    except asyncio.TimeoutError:
                        pass
                    if time.time() - last_flush >= 5:
                        flush_stale(); last_flush = time.time()
                    if time.time() - last_recentre >= 600:
                        last_recentre = time.time()
                        await _maybe_recentre()
                        if _pending_subs:
                            await _subscribe(ws, list(_pending_subs))
                            subs += _pending_subs
                            _pending_subs.clear()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _state.update(connected=False, error=f"{type(exc).__name__}: {exc}")
            attempt += 1
            await asyncio.sleep(min(2 ** attempt, 30))
    flush_stale(time.time() + 60)
    _state["connected"] = False


async def _loop() -> None:
    while True:
        try:
            if _recording_window(datetime.now(IST)):
                await _session()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("order_flow: session failed")
            _state.update(connected=False, error=str(exc))
        await asyncio.sleep(30)


def start_order_flow_task() -> asyncio.Task | None:
    if not get_settings().order_flow_recorder_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_order_flow_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


# ---------------------------------------------------------------- page


def state() -> dict[str, Any]:
    today = datetime.now(IST).date().isoformat()
    rows = db.orderflow_minutes(day=today)
    fut = [r for r in rows if r["kind"] == "FUT"]
    cum, curve = 0.0, []
    for r in fut:
        cum += (r["buy_vol"] or 0) - (r["sell_vol"] or 0)
        curve.append({"time": r["minute_ts"], "close": r["close"], "delta": r["buy_vol"] - r["sell_vol"], "cumDelta": cum,
                      "bookImbalance": round((r["book_buy"] - r["book_sell"]) / (r["book_buy"] + r["book_sell"]), 3) if (r["book_buy"] + r["book_sell"]) else None})
    by_kind: dict[str, dict[str, float]] = {}
    for r in rows:
        k = by_kind.setdefault(r["kind"], {"buy": 0.0, "sell": 0.0, "volume": 0.0})
        k["buy"] += r["buy_vol"] or 0; k["sell"] += r["sell_vol"] or 0; k["volume"] += r["volume"] or 0
    return {
        "recording": {k: _state[k] for k in ("connected", "packets", "centre", "day", "error")},
        "secondsSincePacket": round(time.time() - _state["lastPacket"], 1) if _state["lastPacket"] else None,
        "instruments": [{"securityId": sid, **v} for sid, v in _state["instruments"].items()],
        "days": db.orderflow_days(),
        "today": {"minutes": len(rows), "futures": curve[-400:], "byKind": by_kind,
                  "lastFutures": [dict(r) for r in fut[-15:]][::-1]},
    }
