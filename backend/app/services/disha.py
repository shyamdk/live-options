"""Disha -- morning context for NIFTY (no predictions).

Research (Nov 2026, backend/data/history/backtests/disha_*.py) found no signal
that predicts NIFTY's next 1/3/5 minutes or the 09:30 -> 10:30/11:00 move
well enough to pay for a debit spread. So Disha shows the morning's facts --
gap, the 09:15-09:30 opening range and its breakout, the first 15 minutes,
India VIX, option OI added since the open -- next to how often each situation
played out historically (app/data/disha_base_rates.json, built by
scripts/disha_base_rates.py with the same classification functions below).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.sessions import weekday_open
from app.core.config import get_settings
from app.core.timeutil import now_ist
from app.db import sqlite as db
from app.services.dhan import DhanService

IST = timezone(timedelta(hours=5, minutes=30))
BASE_RATES_FILE = Path(__file__).resolve().parents[1] / "data" / "disha_base_rates.json"
OPEN_MIN = 9 * 60 + 15
OR_END_MIN = 9 * 60 + 30          # opening range = 09:15-09:29 candles
BREAKOUT_LAST_MIN = 10 * 60 + 30  # a breakout counts if it happens by 10:30
STRONG_OPEN_BPS = 20.0
_cache: dict[str, Any] = {"at": 0.0, "data": None}
CACHE_SECONDS = 20


# ---------------------------------------------------------------- shared classification

def gap_class(gap_bps: float | None) -> str | None:
    if gap_bps is None:
        return None
    if gap_bps >= 50: return "gap_up_big"
    if gap_bps >= 20: return "gap_up"
    if gap_bps <= -50: return "gap_down_big"
    if gap_bps <= -20: return "gap_down"
    return "gap_flat"


def first_move_class(move_bps: float | None) -> str | None:
    if move_bps is None:
        return None
    if move_bps >= STRONG_OPEN_BPS: return "open_strong_up"
    if move_bps <= -STRONG_OPEN_BPS: return "open_strong_down"
    return "open_quiet"


def opening_range(candles: list[dict[str, Any]]) -> dict[str, float] | None:
    """High/low of the 09:15-09:29 one-minute candles (candles carry 'mod' = minute of day)."""
    first = [c for c in candles if OPEN_MIN <= c["mod"] < OR_END_MIN]
    if len(first) < 10:
        return None
    return {"high": max(c["high"] for c in first), "low": min(c["low"] for c in first)}


def find_breakout(candles: list[dict[str, Any]], rng: dict[str, float]) -> dict[str, Any] | None:
    """First candle from 09:30 to 10:30 that trades beyond the opening range."""
    for c in candles:
        if c["mod"] < OR_END_MIN or c["mod"] > BREAKOUT_LAST_MIN:
            continue
        if c["high"] > rng["high"]:
            return {"side": "up", "mod": c["mod"], "time": c["time"], "level": rng["high"]}
        if c["low"] < rng["low"]:
            return {"side": "down", "mod": c["mod"], "time": c["time"], "level": rng["low"]}
    return None


def situation_keys(gap_bps: float | None, move_930_bps: float | None, breakout: dict[str, Any] | None,
                   or_complete: bool, past_breakout_window: bool, narrow: bool | None) -> list[str]:
    keys = []
    if (g := gap_class(gap_bps)): keys.append(g)
    if (m := first_move_class(move_930_bps)): keys.append(m)
    if breakout:
        keys.append(f"breakout_{breakout['side']}")
        if narrow: keys.append(f"breakout_{breakout['side']}_narrow")
    elif or_complete and past_breakout_window:
        keys.append("no_breakout")
    return keys


def load_base_rates() -> dict[str, Any] | None:
    try:
        return json.loads(BASE_RATES_FILE.read_text())
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- live state

def _with_mod(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for c in sorted(candles, key=lambda x: int(x["time"])):
        t = int(c["time"])
        ist = datetime.fromtimestamp(t, IST)
        out.append({"time": t, "mod": ist.hour * 60 + ist.minute, "open": float(c["open"]), "high": float(c["high"]),
                    "low": float(c["low"]), "close": float(c["close"])})
    return out


async def _prev_close(dhan: DhanService, security_id: str, today: str) -> float | None:
    start = (now_ist().date() - timedelta(days=10)).isoformat()
    candles = await dhan.historical_daily_candles(security_id, "IDX_I", "INDEX", start, today)
    rows = [c for c in candles if datetime.fromtimestamp(int(c["time"]), IST).date().isoformat() < today]
    return float(rows[-1]["close"]) if rows else None


def _oi_buildup(today: str) -> dict[str, Any] | None:
    points = (db.get_pcr_oi_snapshots(today) or {}).get("NIFTY") or []
    points = [p for p in points if p.get("ceOi") is not None and p.get("peOi") is not None]
    if len(points) < 2:
        return None
    first, last = points[0], points[-1]
    return {"ceAdded": round((last["ceOi"] - first["ceOi"]) / 1e5, 2), "peAdded": round((last["peOi"] - first["peOi"]) / 1e5, 2),
            "pcrOpen": first.get("pcr"), "pcrNow": last.get("pcr"), "since": first["time"], "asOf": last["time"]}


async def get_state() -> dict[str, Any]:
    if _cache["data"] and time.monotonic() - _cache["at"] < CACHE_SECONDS:
        return _cache["data"]
    settings = get_settings(); dhan = DhanService(settings)
    now = now_ist(); today = now.date().isoformat()
    nifty_id = str(settings.dhan_nifty_security_id); vix_id = str(settings.dhan_india_vix_security_id or 21)
    errors: list[str] = []
    candles: list[dict[str, Any]] = []
    try:
        candles = _with_mod(await dhan.intraday_candles(nifty_id, "IDX_I", "INDEX", "1", today, today))
    except Exception as exc:  # show what we have; the page states the error
        errors.append(f"NIFTY candles: {exc}")
    prev_close = vix_now = vix_prev = None
    try:
        prev_close = await _prev_close(dhan, nifty_id, today)
    except Exception as exc:
        errors.append(f"previous close: {exc}")
    try:
        vix_c = await dhan.intraday_candles(vix_id, "IDX_I", "INDEX", "1", today, today)
        vix_now = float(sorted(vix_c, key=lambda c: int(c["time"]))[-1]["close"]) if vix_c else None
        vix_prev = await _prev_close(dhan, vix_id, today)
    except Exception as exc:
        errors.append(f"India VIX: {exc}")

    day_open = candles[0]["open"] if candles else None
    last = candles[-1]["close"] if candles else None
    gap_bps = (day_open / prev_close - 1) * 1e4 if day_open and prev_close else None
    rng = opening_range(candles)
    or_complete = bool(rng) and any(c["mod"] >= OR_END_MIN for c in candles)
    breakout = find_breakout(candles, rng) if rng and or_complete else None
    c930 = next((c["close"] for c in candles if c["mod"] == OR_END_MIN - 1), None)
    move_930 = (c930 / day_open - 1) * 1e4 if c930 and day_open else None
    rates = load_base_rates()
    width_bps = (rng["high"] - rng["low"]) / day_open * 1e4 if rng and day_open else None
    narrow = (width_bps < rates["orWidthMedianBps"]) if rates and width_bps is not None else None
    past_window = bool(candles) and candles[-1]["mod"] > BREAKOUT_LAST_MIN
    keys = situation_keys(gap_bps, move_930, breakout, or_complete, past_window, narrow)

    data = {
        "asOf": int(time.time()), "day": today, "errors": errors,
        "marketOpen": weekday_open(now) and OPEN_MIN <= now.hour * 60 + now.minute <= 15 * 60 + 30,
        "spot": [{"time": c["time"], "close": c["close"]} for c in candles],
        "last": last, "open": day_open, "prevClose": prev_close,
        "gapPts": round(day_open - prev_close, 2) if day_open and prev_close else None,
        "gapBps": round(gap_bps, 1) if gap_bps is not None else None,
        "fromOpenPts": round(last - day_open, 2) if last and day_open else None,
        "move930Bps": round(move_930, 1) if move_930 is not None else None,
        "openingRange": ({"high": rng["high"], "low": rng["low"], "widthPts": round(rng["high"] - rng["low"], 2),
                          "widthBps": round(width_bps, 1) if width_bps is not None else None, "narrow": narrow, "complete": or_complete}
                         if rng else None),
        "breakout": ({**breakout, "distancePts": round((last - breakout["level"]) * (1 if breakout["side"] == "up" else -1), 2)}
                     if breakout and last else None),
        "vix": {"now": vix_now, "prev": vix_prev, "change": round(vix_now - vix_prev, 2) if vix_now and vix_prev else None},
        "oi": _oi_buildup(today),
        "matches": keys,
        "baseRates": rates,
    }
    _cache.update(at=time.monotonic(), data=data)
    return data
