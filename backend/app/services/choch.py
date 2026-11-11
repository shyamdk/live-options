"""1-Min CHoCH -- paper trading of Mukesh Jha's 1-minute NIFTY CHoCH reversal.

Rules live in app/services/choch_engine.py (shared with the backtest). Every 20 s in
market hours the monitor fetches today's completed NIFTY 1-min candles from Dhan and
replays them through the engine with the day's settings; every trade the replay
produces is recorded once (keyed by its entry minute), exits are filled in when the
replay closes them, and entries / exits go to Telegram. Because the replay is the
backtest itself, the paper book is exactly what the backtest would have done today.

Paper P&L is in NIFTY futures points (the backtest's basis): points x lot size x lots,
less `costPoints` per round trip (slippage + charges). Settings changed during a
session apply from the next session, so a day is never replayed under two settings.
Paper only -- there is no order code here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, time as dtime
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.sessions import weekday_open
from app.db import sqlite as db
from app.services import choch_engine as engine
from app.services.dhan import DhanService
from app.services.telegram import TelegramNotifier

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
POLL_SECONDS = 20
LOT_SIZE = 65

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "swing": 65.0,
    "stop": 10.0,
    "target": 60.0,
    "maxTrades": 2,
    "start": "09:45",
    "lastEntry": "15:00",
    "flat": "15:15",
    "lots": 1,
    "costPoints": 1.5,
}
BACKTEST = {
    "period": "Jan 2025 - Oct 2026, NIFTY 1-min",
    "rows": [
        {"label": "Transcript settings (swing 15-30, stop 10, target 30)", "result": "-27 to -70 pts/month", "win": "24-26%"},
        {"label": "Swing 60, stop 10, target 60, max 2/day", "result": "+666 pts (2025 +266 / 2026 +400)", "win": "23%"},
        {"label": "Swing 65, stop 10, target 60, max 2/day (default)", "result": "+894 pts (2025 +311 / 2026 +584)", "win": "24%"},
    ],
    "notes": "143 / 117 trades (6.5 / 5.3 a month); losing runs up to 10-13; still positive at 4.5 pts cost per trade.",
}
_lock = asyncio.Lock()
_last: dict[str, Any] = {}


def _hhmm(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 100 + int(m)


def get_config() -> dict[str, Any]:
    config: dict[str, Any] = {}
    for key, default in DEFAULTS.items():
        raw = db.choch_get_setting(key)
        if raw is None:
            config[key] = default
        elif isinstance(default, bool):
            config[key] = raw == "1"
        elif isinstance(default, int):
            config[key] = int(float(raw))
        elif isinstance(default, float):
            config[key] = float(raw)
        else:
            config[key] = raw
    config["lotSize"] = LOT_SIZE
    return config


def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if key not in DEFAULTS or value is None:
            continue
        default = DEFAULTS[key]
        if key in ("start", "lastEntry", "flat"):
            _hhmm(str(value))
        if key in ("swing", "stop", "target") and not 1 <= float(value) <= 500:
            raise ValueError(f"{key} must be 1-500 points")
        if key in ("maxTrades", "lots") and not 1 <= int(float(value)) <= 50:
            raise ValueError(f"{key} must be 1-50")
        db.choch_set_setting(key, ("1" if value else "0") if isinstance(default, bool) else str(value))
    return get_config()


def _day_params(day: str) -> dict[str, Any]:
    """Settings frozen for a session the first time it is processed."""
    raw = db.choch_get_setting(f"params.{day}")
    if raw:
        return json.loads(raw)
    c = get_config()
    params = {"swing": c["swing"], "stop": c["stop"], "target": c["target"], "max_trades": c["maxTrades"],
              "start": _hhmm(c["start"]), "last_entry": _hhmm(c["lastEntry"]), "flat": _hhmm(c["flat"]),
              "lots": c["lots"], "costPoints": c["costPoints"]}
    db.choch_set_setting(f"params.{day}", json.dumps(params))
    return params


async def _today_bars() -> list[dict[str, Any]]:
    today = datetime.now(IST).date().isoformat()
    candles = await DhanService().intraday_candles(str(get_settings().dhan_nifty_security_id), "IDX_I", "INDEX", "1", today, today)
    cutoff = time.time()
    return sorted((c for c in candles if int(c["time"]) + 60 <= cutoff), key=lambda c: int(c["time"]))


def _market_open(now: datetime) -> bool:
    return weekday_open(now) and dtime(9, 15) <= now.time() <= dtime(15, 31)


async def monitor_once() -> None:
    now = datetime.now(IST)
    if not _market_open(now):
        return
    config = get_config()
    async with _lock:
        bars = await _today_bars()
        if not bars:
            return
        day = now.date().isoformat()
        params = _day_params(day)
        rep = engine.run_day(bars, swing=params["swing"], stop=params["stop"], target=params["target"], max_trades=params["max_trades"],
                             start=params["start"], last_entry=params["last_entry"], flat=params["flat"], close_open=False)
        _last.update(day=day, state=rep["state"], lastBar=bars[-1], params=params)
        if not config["enabled"]:
            return
        # the paper book starts when the page goes live: signals from before that are not back-filled
        active_from = int(db.choch_get_setting("activeFrom") or 0)
        if not active_from:
            active_from = int(time.time())
            db.choch_set_setting("activeFrom", str(active_from))
        recorded = {t["entry_time"]: t for t in db.choch_list_trades(day=day)}
        last_price = bars[-1]["close"]
        for t in rep["trades"] + ([rep["open"]] if rep["open"] else []):
            row = recorded.get(t["entryTime"])
            if row is None and t["entryTime"] < active_from:
                continue
            if row is None:
                db.choch_insert_trade({
                    "day": day, "side": t["side"], "status": "OPEN", "entry_time": t["entryTime"], "entry": t["entry"], "stop": t["sl"], "target": t["tp"],
                    "lots": params["lots"], "lot_size": LOT_SIZE, "cost_points": params["costPoints"], "params": json.dumps(params), "last_price": last_price,
                })
                row = {r["entry_time"]: r for r in db.choch_list_trades(day=day)}[t["entryTime"]]
                await _notify(f"🔁 1-Min CHoCH {'LONG' if t['side'] == 1 else 'SHORT'} NIFTY @ {t['entry']:,.2f} (paper) -- stop {t['sl']:,.2f}, target {t['tp']:,.2f}")
            if "exit" in t and row["status"] == "OPEN":
                net_pts = t["pts"] - row["cost_points"]
                db.choch_update_trade(row["id"], status="CLOSED", exit_time=t["exitTime"], exit=t["exit"], exit_reason=t["reason"], points=round(t["pts"], 2), last_price=t["exit"])
                await _notify(f"🔁 1-Min CHoCH {t['reason'].upper()} -- {'long' if t['side'] == 1 else 'short'} @ {t['entry']:,.2f} -> {t['exit']:,.2f}: "
                              f"{t['pts']:+.1f} pts, net ₹{net_pts * row['lot_size'] * row['lots']:,.0f}")
            elif "exit" not in t:
                db.choch_update_trade(row["id"], last_price=last_price)


def summarize(t: dict[str, Any]) -> dict[str, Any]:
    qty = t["lot_size"] * t["lots"]
    if t["status"] == "CLOSED":
        gross = (t["points"] or 0) * qty
    else:
        gross = ((t["last_price"] or t["entry"]) - t["entry"]) * t["side"] * qty
    charges = t["cost_points"] * qty
    return {
        "id": t["id"], "day": t["day"], "side": t["side"], "status": t["status"], "entryTime": t["entry_time"], "entry": t["entry"],
        "stop": t["stop"], "target": t["target"], "exitTime": t["exit_time"], "exit": t["exit"], "exitReason": t["exit_reason"],
        "points": t["points"] if t["status"] == "CLOSED" else round(((t["last_price"] or t["entry"]) - t["entry"]) * t["side"], 2),
        "lots": t["lots"], "lotSize": t["lot_size"], "lastPrice": t["last_price"],
        "grossPnl": round(gross, 2), "charges": round(charges, 2), "netPnl": round(gross - charges, 2), "params": json.loads(t["params"]),
    }


async def state() -> dict[str, Any]:
    now = datetime.now(IST)
    payload: dict[str, Any] = {"config": get_config(), "marketOpen": _market_open(now), "backtest": BACKTEST}
    day = now.date().isoformat()
    if _last.get("day") == day:
        payload.update(structure=_last["state"], lastBar=_last["lastBar"], dayParams=_last["params"])
    else:
        try:
            bars = await _today_bars()
            if bars:
                p = _day_params(day)
                rep = engine.run_day(bars, swing=p["swing"], stop=p["stop"], target=p["target"], max_trades=p["max_trades"],
                                     start=p["start"], last_entry=p["last_entry"], flat=p["flat"], close_open=False)
                payload.update(structure=rep["state"], lastBar=bars[-1], dayParams=p)
        except Exception as exc:
            payload["error"] = f"Dhan data unavailable: {exc}"
    payload["today"] = [summarize(t) for t in db.choch_list_trades(day=day)]
    payload["open"] = [summarize(t) for t in db.choch_list_trades(status="OPEN")]
    return payload


async def candles() -> list[dict[str, Any]]:
    return await _today_bars()


def list_trades() -> list[dict[str, Any]]:
    return [summarize(t) for t in db.choch_list_trades()]


async def _notify(text: str) -> None:
    try:
        await TelegramNotifier().send(text)
    except Exception:
        logger.warning("choch: telegram send failed")


def start_choch_task() -> asyncio.Task | None:
    if not get_settings().choch_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_choch_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def _loop() -> None:
    while True:
        try:
            await monitor_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("choch: monitor iteration failed")
        await asyncio.sleep(POLL_SECONDS)
