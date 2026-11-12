"""Market Profile context for NIFTY (context only -- not a signal).

TPO (time-at-price) profile from 1-min candles: 5-pt bins, 30-min periods from 09:15.
POC = bin with the most TPOs; value area = 70% of TPOs grown around the POC.
Initial balance (IB) = 09:15-10:15 range.

Back-test (backend/data/history/backtests/mp_bt.py, Jan 2025 - Oct 2026): the classic
setups traded as ATM weekly option buys all lost (80% rule -Rs53k, IB breakout
-Rs128k, IB breakout with POC bias -Rs42k, open drive -Rs18k, 1 lot). So the page
shows these levels as context for discretionary decisions, never as entries.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.market_calendar import holidays_from_settings, is_trading_day

IST = ZoneInfo("Asia/Kolkata")
BIN = 5.0
_prev_cache: dict[str, Any] = {}


def _mins(ts: int) -> int:
    d = datetime.fromtimestamp(int(ts), IST)
    return d.hour * 60 + d.minute


def profile(bars: list[dict[str, Any]]) -> dict[str, float] | None:
    """{poc, vah, val} of a session's 1-min bars (dicts with time / high / low)."""
    tpo: dict[int, int] = defaultdict(int)
    periods: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for b in bars:
        periods[(_mins(b["time"]) - 555) // 30].append(b)
    for p in periods.values():
        lo, hi = min(b["low"] for b in p), max(b["high"] for b in p)
        for k in range(int(math.floor(lo / BIN)), int(math.floor(hi / BIN)) + 1):
            tpo[k] += 1
    if not tpo:
        return None
    total = sum(tpo.values())
    centre = sum(k * v for k, v in tpo.items()) / total
    poc = max(tpo, key=lambda k: (tpo[k], -abs(k - centre)))
    lo_k = hi_k = poc
    inside = tpo[poc]
    while inside < 0.7 * total:
        up = tpo.get(hi_k + 1, 0) + tpo.get(hi_k + 2, 0)
        dn = tpo.get(lo_k - 1, 0) + tpo.get(lo_k - 2, 0)
        if up == 0 and dn == 0:
            break
        if up >= dn:
            for _ in range(2):
                if inside < 0.7 * total:
                    hi_k += 1
                    inside += tpo.get(hi_k, 0)
        else:
            for _ in range(2):
                if inside < 0.7 * total:
                    lo_k -= 1
                    inside += tpo.get(lo_k, 0)
    return {"poc": (poc + 0.5) * BIN, "vah": (hi_k + 1) * BIN, "val": lo_k * BIN}


def previous_trading_day(day: date) -> date:
    holidays = holidays_from_settings(get_settings())
    d = day - timedelta(days=1)
    while not is_trading_day(d, holidays):
        d -= timedelta(days=1)
    return d


def _where(price: float, low: float, high: float) -> str:
    return "above" if price > high else "below" if price < low else "inside"


async def context(dhan: Any, security_id: str, today: str, candles: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Yesterday's value area + today's open relation, IB and developing profile."""
    prev_day = previous_trading_day(date.fromisoformat(today)).isoformat()
    if _prev_cache.get("day") != prev_day:
        prev_bars = await dhan.intraday_candles(security_id, "IDX_I", "INDEX", "1", prev_day, prev_day)
        prev = profile([{"time": int(c["time"]), "high": float(c["high"]), "low": float(c["low"])} for c in prev_bars])
        if not prev:
            return None
        _prev_cache.update(day=prev_day, profile=prev)
    prev = _prev_cache["profile"]
    out: dict[str, Any] = {"prevDay": prev_day, "prev": prev, "prevWidth": round(prev["vah"] - prev["val"], 1)}
    if not candles:
        return out
    day_open, last = candles[0]["open"], candles[-1]["close"]
    ib = [c for c in candles if _mins(c["time"]) < 615]
    ib_complete = any(_mins(c["time"]) >= 615 for c in candles)
    ib_hi, ib_lo = max(c["high"] for c in ib), min(c["low"] for c in ib)
    today_profile = profile(candles)
    open_rel = _where(day_open, prev["val"], prev["vah"])
    now_rel = _where(last, prev["val"], prev["vah"])
    notes = []
    if open_rel != "inside":
        notes.append(f"Opened {open_rel} yesterday's value ({prev['val']:,.0f}–{prev['vah']:,.0f}): an out-of-balance open.")
        if now_rel == "inside":
            notes.append("Price is back inside yesterday's value -- the classic '80% rule' look (it lost money as an options trade in our back-test).")
        else:
            notes.append(f"Still {now_rel} value -- acceptance away from yesterday so far.")
    else:
        notes.append(f"Opened inside yesterday's value ({prev['val']:,.0f}–{prev['vah']:,.0f}): a balanced open; edges often act as reference levels.")
    if ib_complete:
        ib_rel = _where(last, ib_lo, ib_hi)
        notes.append(f"Initial balance {ib_lo:,.0f}–{ib_hi:,.0f} ({ib_hi - ib_lo:,.0f} pts); price is {ib_rel}" + (" the IB -- range extension." if ib_rel != "inside" else " it."))
    out.update({
        "open": day_open, "last": last, "openVsValue": open_rel, "openVsPoc": "above" if day_open > prev["poc"] else "below",
        "nowVsValue": now_rel, "ib": {"high": ib_hi, "low": ib_lo, "width": round(ib_hi - ib_lo, 1), "complete": ib_complete},
        "today": today_profile, "notes": notes,
    })
    return out
