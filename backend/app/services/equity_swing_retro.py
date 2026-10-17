"""Equity-Swing retrospective: review what happened, re-test the settings on
the latest data, and suggest changes only when the evidence holds.

  review     real (paper/live) trades: P&L, win rate, average win/loss, holding
             time, by exit reason / sector / entry rank; equity vs NIFTY
  benchmark  back-test of the current settings vs random NIFTY 200 picks
             (same machinery, 10 seeds) over the full stored history
  retest     one-setting-at-a-time variants around the current config on the
             full history AND the last ~6 months; a variant is suggested only
             if it beats the current setting on BOTH by a margin
Nothing is applied automatically: each suggestion has an Apply action.
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
import time
from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.db import sqlite as db
from app.services import equity_swing as swing
from app.services import equity_swing_backtest as bt
from app.services.telegram import TelegramNotifier

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
RECENT_DAYS = 126  # ~6 months of trading days
MIN_GAIN_FULL = 2.0  # CAGR points a variant must add on the full history ...
MIN_GAIN_RECENT = 2.0  # ... and on the recent window (annualised)
_running: dict[str, Any] = {"since": None}


def _variants(cfg: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []

    def add(key: str, values: list[Any], fmt=lambda v: v) -> None:
        for v in values:
            if str(v) != str(cfg[key]):
                out.append((f"{key} = {fmt(v)}", {key: v}))

    add("positions", [6, 10])
    add("exitRank", [15, 30])
    add("maxHoldWeeks", [0, 6, 10], lambda v: "no cap" if v == 0 else f"{v} weeks")
    add("lookbacks", ["21", "63", "42,84", "21,63,126"])
    add("regimeFilter", [not cfg["regimeFilter"]])
    add("fillDepth", [int(cfg["positions"]), int(cfg["positions"]) + 8])
    return out


def _load_data() -> dict[str, Any]:
    bars = {}
    for m in swing.universe():
        rows = db.swing_rows("SELECT ts, open, close FROM equity_swing_bars WHERE security_id = ? ORDER BY ts", (m["securityId"],))
        if rows:
            bars[m["symbol"]] = rows
    nifty = db.swing_rows("SELECT ts, open, close FROM equity_swing_bars WHERE security_id = ? ORDER BY ts", (swing.NIFTY_KEY,))
    return bt.prepare(bars, nifty)


def review() -> dict[str, Any]:
    trades = db.swing_rows("SELECT * FROM equity_swing_trades WHERE status IN ('OPEN', 'PENDING_EXIT', 'CLOSED') ORDER BY entry_time")
    closed = [t for t in trades if t["status"] == "CLOSED"]
    wins = [t["pnl"] for t in closed if (t["pnl"] or 0) > 0]
    losses = [t["pnl"] for t in closed if (t["pnl"] or 0) <= 0]

    def group(key) -> dict[str, dict[str, Any]]:
        g: dict[str, list[float]] = defaultdict(list)
        for t in closed:
            g[str(key(t))].append(t["pnl"] or 0)
        return {k: {"trades": len(v), "pnl": round(sum(v)), "winRate": round(sum(x > 0 for x in v) / len(v) * 100)} for k, v in g.items()}

    curve = db.swing_rows("SELECT * FROM equity_swing_equity ORDER BY day")
    since = None
    if len(curve) >= 2 and curve[0]["nifty"] and curve[-1]["nifty"]:
        since = {
            "from": curve[0]["day"], "to": curve[-1]["day"],
            "strategy": round((curve[-1]["equity"] / curve[0]["equity"] - 1) * 100, 2),
            "nifty": round((curve[-1]["nifty"] / curve[0]["nifty"] - 1) * 100, 2),
        }
    holds = [(t["exit_time"] - t["entry_time"]) / (7 * 86400) for t in closed if t["exit_time"] and t["entry_time"]]
    return {
        "openPositions": sum(1 for t in trades if t["status"] != "CLOSED"),
        "closedTrades": len(closed),
        "realized": round(sum(t["pnl"] or 0 for t in closed)),
        "winRate": round(len(wins) / len(closed) * 100, 1) if closed else None,
        "avgWin": round(statistics.mean(wins)) if wins else None,
        "avgLoss": round(statistics.mean(losses)) if losses else None,
        "medianHoldWeeks": round(statistics.median(holds), 1) if holds else None,
        "byExit": group(lambda t: "time cap" if "held" in (t["exit_reason"] or "") else "rank drop"),
        "bySector": group(lambda t: t["industry"] or "?"),
        "byEntryRank": group(lambda t: "rank 1-4" if (t["entry_rank"] or 99) <= 4 else "rank 5-8" if (t["entry_rank"] or 99) <= 8 else "rank 9+"),
        "sinceStart": since,
    }


def _compute(cfg: dict[str, Any]) -> dict[str, Any]:
    data = _load_data()
    n = len(data["dates"])
    start = 260
    if n - start < 120:
        return {"error": f"Only {n} days of NIFTY history stored -- the back-test needs at least {start + 120}. Sync prices first."}
    recent_start = max(start, n - 1 - RECENT_DAYS)
    current_full = bt.run(data, cfg, start)
    current_recent = bt.run(data, cfg, recent_start)
    randoms = [bt.run(data, cfg, start, picker="random", seed=s)["cagr"] for s in range(10)]
    variants = []
    for label, change in _variants(cfg):
        v = {**cfg, **change}
        full, recent = bt.run(data, v, start), bt.run(data, v, recent_start)
        gain_full, gain_recent = full["cagr"] - current_full["cagr"], recent["cagr"] - current_recent["cagr"]
        variants.append({
            "label": label, "change": change, "full": full, "recent": recent,
            "gainFull": round(gain_full, 2), "gainRecent": round(gain_recent, 2),
            "suggest": gain_full >= MIN_GAIN_FULL and gain_recent >= MIN_GAIN_RECENT and full["maxDrawdown"] >= current_full["maxDrawdown"] - 5,
        })
    variants.sort(key=lambda x: (not x["suggest"], -(x["gainFull"] + x["gainRecent"])))
    dates = data["dates"]
    regime_days = sum(1 for i in range(recent_start, n) if data["nifty200"][i] and data["nifty"][i] <= data["nifty200"][i])
    recent_note = None
    if current_recent["trades"] == 0:
        recent_note = (f"No trades in the last ~6 months under the current settings -- NIFTY was below its SMA200 on "
                       f"{regime_days} of {n - recent_start} days, so the market filter blocked new buys. The recent check can't separate the variants.")
    return {
        "recentNote": recent_note,
        "window": {"from": datetime.fromtimestamp(dates[start], IST).date().isoformat(), "to": datetime.fromtimestamp(dates[-1], IST).date().isoformat(),
                   "recentFrom": datetime.fromtimestamp(dates[recent_start], IST).date().isoformat()},
        "current": {"full": current_full, "recent": current_recent},
        "random": {"median": round(statistics.median(randoms), 2), "min": min(randoms), "max": max(randoms)},
        "variants": variants,
    }


async def run_retro(trigger: str = "manual") -> dict[str, Any]:
    if _running["since"]:
        return {"status": "running", "since": _running["since"]}
    _running["since"] = int(time.time())
    try:
        cfg = swing.get_config()
        settings_used = {k: cfg[k] for k in swing.DEFAULTS if k not in ("enabled", "mode")}
        retest = await asyncio.to_thread(_compute, settings_used)
        payload = {"trigger": trigger, "settings": settings_used, "review": review(), "retest": retest, "decisions": []}
        retro_id = db.swing_insert("equity_swing_retros", {"created_at": int(time.time()), "trigger": trigger, "payload": json.dumps(payload)})
        await TelegramNotifier().send(_telegram(retro_id, payload))
        return {"status": "done", "id": retro_id}
    finally:
        _running["since"] = None


def _telegram(retro_id: int, p: dict[str, Any]) -> str:
    r, t = p["review"], p["retest"]
    lines = [f"🔁 Equity-Swing retrospective #{retro_id} ({p['trigger']})"]
    if r["closedTrades"]:
        lines.append(f"Trades: {r['closedTrades']} closed, {r['winRate']}% winners, realized ₹{r['realized']:,}")
    if r["sinceStart"]:
        lines.append(f"Since {r['sinceStart']['from']}: strategy {r['sinceStart']['strategy']:+.1f}% vs NIFTY {r['sinceStart']['nifty']:+.1f}%")
    if t.get("error"):
        lines.append(t["error"])
        return "\n".join(lines)
    c = t["current"]
    lines.append(f"Back-test now: {c['full']['cagr']:.1f}% a year (last 6 months {c['recent']['cagr']:.1f}% annualised), random picks {t['random']['median']:.1f}%")
    if t.get("recentNote"):
        lines.append(t["recentNote"])
    sug = [v for v in t["variants"] if v["suggest"]]
    lines += [f"Suggest {v['label']}: +{v['gainFull']:.1f} pts full, +{v['gainRecent']:.1f} pts recent" for v in sug] or ["No change recommended."]
    lines.append("Open Equity-Swing to review and apply.")
    return "\n".join(lines)


def list_retros(limit: int = 24) -> list[dict[str, Any]]:
    rows = db.swing_rows("SELECT * FROM equity_swing_retros ORDER BY id DESC LIMIT ?", (limit,))
    return [{"id": r["id"], "createdAt": r["created_at"], "trigger": r["trigger"], **json.loads(r["payload"])} for r in rows]


def apply(retro_id: int, label: str) -> dict[str, Any]:
    row = db.swing_rows("SELECT * FROM equity_swing_retros WHERE id = ?", (retro_id,))
    if not row:
        raise ValueError("Retrospective not found.")
    payload = json.loads(row[0]["payload"])
    variant = next((v for v in payload["retest"].get("variants", []) if v["label"] == label), None)
    if not variant:
        raise ValueError("That variant isn't in this retrospective.")
    config = swing.update_config(variant["change"])
    payload["decisions"].append({"at": int(time.time()), "applied": label})
    db.swing_update("equity_swing_retros", retro_id, {"payload": json.dumps(payload)})
    swing._event("settings", f"Retrospective #{retro_id}: applied {label}")
    return config


def running() -> int | None:
    return _running["since"]


async def maybe_monthly(now: datetime) -> None:
    """First trading day of the month, after prices are synced."""
    month = now.strftime("%Y-%m")
    if db.get_swing_setting("retro.lastMonth") == month:
        return
    first = now.date().replace(day=1)
    while not swing._trading_day(first):
        first = first.replace(day=first.day + 1)
    if now.date() < first or db.get_swing_setting("bars.syncedFor") != now.date().isoformat():
        return
    db.set_swing_setting("retro.lastMonth", month)
    await run_retro("monthly")
