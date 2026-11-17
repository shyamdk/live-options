"""Index Runway -- paper forward test of the NIFTY "40 points in 2 minutes" trigger study.

Backtest (backend/data/history/backtests/index_runway/, Jan 2025 - Oct 2026, 1-min data; write-up in
docs/strategies/index-runway.md and docs/guides/Index-Runway-Backtest.pdf): NIFTY moved 40+ points
within 2 minutes 761 times (0.6% of minutes). The minute before such a move (the "trigger minute",
bar T-1 -> bar T) shows a bigger index move, higher VIX, faster ATM IV change and more OI churn, but
the direction of the trigger minute only matched the move about half the time. The default rule
below (|trigger| >= 15 pts, VIX >= 14, |ATM IV change| >= 0.15) hit 40 pts in 6.2% of 2026 minutes
it flagged (vs 0.6% for any minute), about 7 signals a day.

Every completed 1-min bar this module:
  1. snapshots the NIFTY candle, India VIX and the nearest-weekly option chain (ATM +-10 strikes);
  2. computes the trigger-minute features against the previous minute (ATM CE/PE Greeks, cluster
     OI ATM+-1, wide cluster ATM+-3, chain OI ATM+-10, VIX) and logs them in index_runway_minutes,
     later scoring each minute with the actual next-2-minute move (so the rule's hit rate can be
     re-measured on live data);
  3. on a rule match opens a paper trade at the snapshot prices -- a long ATM straddle by default,
     or the ATM option in the trigger direction ("follow") -- and closes it holdMinutes later.
Times are 1-min bar START times, as in the backtest: a trigger "10:01->10:02" compares the 10:01 and
10:02 bar closes, the trade enters at the 10:02 close and exits at the 10:04 close. Paper only: no orders are sent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from datetime import date, datetime, time as dtime
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.sessions import weekday_open
from app.core.timeutil import now_ist
from app.db import sqlite as db
from app.services.charges import option_order_charges
from app.services.dhan import DhanService
from app.services.telegram import TelegramNotifier

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
INDEX_SEGMENT = "IDX_I"
OPTION_SEGMENT = "NSE_FNO"
LOT_SIZE = 65
STEP = 50.0
RATE = 0.06
CHAIN_WIDTH = 10
MOVE_PTS = 40.0
POLL_SECONDS = 2
READY_AFTER_SECONDS = 3      # wait this long after a minute closes before fetching
GIVE_UP_AFTER_SECONDS = 45   # skip the minute if Dhan has not published the candle by then
RETRY_SECONDS = 6
FORCE_EXIT = dtime(15, 25)

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "minAbsTrigPts": 15.0,
    "minVix": 14.0,
    "minAbsIvChg": 0.15,
    "minRange5": 0.0,
    "tradeMode": "straddle",
    "lots": 1,
    "holdMinutes": 2,
    "maxOpen": 1,
    "entryStart": "09:16",
    "entryEnd": "15:15",
    "notify": False,
}
TRADE_MODES = ("straddle", "follow")

# Backtest of the default rule, by |trigger-minute move|: (low, high, median |move|, p75 |move|, % reaching 40 pts).
ESTIMATES: list[tuple[float, float, float, float, float]] = [
    (15.0, 20.0, 12.0, 19.1, 3.7),
    (20.0, 30.0, 13.5, 22.8, 6.2),
    (30.0, 50.0, 17.5, 26.8, 10.0),
    (50.0, math.inf, 25.0, 50.5, 31.4),
]

_lock = asyncio.Lock()
_expiry_cache: tuple[float, list[date]] | None = None
_snaps: dict[int, dict[str, Any]] = {}
_runtime: dict[str, Any] = {"lastMinute": 0, "lastCheck": None, "lastFeatures": None, "lastReasons": [], "lastMatched": False,
                            "error": None, "skipped": None, "lastAttempt": 0.0}


# ---------------------------------------------------------------- config


def _coerce(default: Any, raw: str) -> Any:
    if isinstance(default, bool):
        return raw == "1"
    if isinstance(default, int):
        return int(float(raw))
    if isinstance(default, float):
        return float(raw)
    return raw


def get_config() -> dict[str, Any]:
    config = {}
    for key, default in DEFAULTS.items():
        raw = db.get_index_runway_setting(key)
        config[key] = default if raw is None else _coerce(default, raw)
    config["lotSize"] = LOT_SIZE
    config["estimates"] = [{"from": lo, "to": None if hi == math.inf else hi, "median": med, "p75": p75, "hit40": hit}
                           for lo, hi, med, p75, hit in ESTIMATES]
    return config


def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if key not in DEFAULTS or value is None:
            continue
        default = DEFAULTS[key]
        if key in ("entryStart", "entryEnd"):
            datetime.strptime(str(value), "%H:%M")
        elif key == "tradeMode" and value not in TRADE_MODES:
            raise ValueError(f"tradeMode must be one of {', '.join(TRADE_MODES)}")
        elif key in ("lots", "holdMinutes", "maxOpen") and not 1 <= int(float(value)) <= 50:
            raise ValueError(f"{key} must be between 1 and 50")
        elif isinstance(default, float) and float(value) < 0:
            raise ValueError(f"{key} cannot be negative")
        db.set_index_runway_setting(key, ("1" if value else "0") if isinstance(default, bool) else str(value))
    return get_config()


# ---------------------------------------------------------------- maths


def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_greeks(spot: float, strike: float, minutes_left: float, iv_percent: float, is_call: bool) -> dict[str, float] | None:
    """Black-Scholes as in the backtest: theta per calendar day, vega per vol point, rho per 1% rate."""
    if not spot or not strike or not iv_percent or iv_percent <= 0:
        return None
    t = max(minutes_left, 1.0) / (365 * 24 * 60)
    sig = iv_percent / 100
    sq = math.sqrt(t)
    d1 = (math.log(spot / strike) + (RATE + 0.5 * sig * sig) * t) / (sig * sq)
    d2 = d1 - sig * sq
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)
    disc = math.exp(-RATE * t)
    if is_call:
        delta = _ncdf(d1)
        theta = -spot * pdf * sig / (2 * sq) - RATE * strike * disc * _ncdf(d2)
        rho = strike * t * disc * _ncdf(d2)
    else:
        delta = _ncdf(d1) - 1
        theta = -spot * pdf * sig / (2 * sq) + RATE * strike * disc * _ncdf(-d2)
        rho = -strike * t * disc * _ncdf(-d2)
    return {"delta": delta, "gamma": pdf / (spot * sig * sq), "theta": theta / 365, "vega": spot * pdf * sq / 100, "rho": rho / 100}


def estimate(abs_trig: float | None) -> dict[str, float] | None:
    if abs_trig is None:
        return None
    for lo, hi, med, p75, hit in ESTIMATES:
        if lo <= abs_trig < hi:
            return {"median": med, "p75": p75, "hit40": hit}
    return None


def _num(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n else None


# ---------------------------------------------------------------- market data


async def _expiries(dhan: DhanService) -> list[date]:
    global _expiry_cache
    if _expiry_cache and time.monotonic() - _expiry_cache[0] < 900:
        return _expiry_cache[1]
    raw = await dhan.expiry_list(get_settings().dhan_nifty_security_id, INDEX_SEGMENT)
    _expiry_cache = (time.monotonic(), sorted(date.fromisoformat(x) for x in raw))
    return _expiry_cache[1]


async def _vix(dhan: DhanService) -> float | None:
    sid = get_settings().dhan_india_vix_security_id
    if not sid:
        return None
    try:
        data = await dhan.market_quotes_by_segment({INDEX_SEGMENT: [int(sid)]}, max_age_seconds=20)
        return _num(((data.get(INDEX_SEGMENT) or {}).get(str(sid)) or {}).get("last_price"))
    except Exception:
        return None


def _chain_rows(chain: dict[str, Any]) -> dict[float, dict[str, Any]]:
    rows: dict[float, dict[str, Any]] = {}
    for key, sides in (chain.get("oc") or {}).items():
        strike = _num(key)
        if strike is None or not isinstance(sides, dict):
            continue
        row = {}
        for side, name in (("ce", "CE"), ("pe", "PE")):
            q = sides.get(side)
            if isinstance(q, dict) and q.get("security_id"):
                row[name] = {"securityId": str(q["security_id"]), "ltp": _num(q.get("last_price")), "oi": _num(q.get("oi")),
                             "iv": _num(q.get("implied_volatility"))}
        if row:
            rows[float(strike)] = row
    return rows


# ---------------------------------------------------------------- features


def _oi_sum(snap: dict[str, Any], strikes: list[float], side: str) -> float | None:
    total = 0.0
    for k in strikes:
        q = snap["chain"].get(k, {}).get(side)
        if not q or q.get("oi") is None:
            return None
        total += q["oi"]
    return total


def compute_features(prev: dict[str, Any], now: dict[str, Any], back3: dict[str, Any] | None, closes: list[float]) -> dict[str, Any]:
    """Trigger-minute features, prev = bar T-1 snapshot, now = bar T snapshot (same definitions as the backtest)."""
    atm = round(prev["spot"] / STEP) * STEP
    f: dict[str, Any] = {"atmStrike": atm, "spotPrev": prev["spot"], "spotNow": now["spot"], "trigPts": now["spot"] - prev["spot"],
                         "vixPrev": prev.get("vix"), "vixNow": now.get("vix"), "dteMinutes": now["dteMinutes"]}
    f["vixChg"] = None if f["vixPrev"] is None or f["vixNow"] is None else f["vixNow"] - f["vixPrev"]
    tail = closes[-6:]
    diffs = [abs(b - a) for a, b in zip(tail, tail[1:])]
    f["range5"] = sum(diffs) if diffs else None

    for side in ("CE", "PE"):
        p, n = prev["chain"].get(atm, {}).get(side), now["chain"].get(atm, {}).get(side)
        if not p or not n:
            continue
        gp = bs_greeks(prev["spot"], atm, now["dteMinutes"] + 1, p.get("iv") or 0, side == "CE")
        gn = bs_greeks(now["spot"], atm, now["dteMinutes"], n.get("iv") or 0, side == "CE")
        vals = {"iv": (p.get("iv"), n.get("iv")), "ltp": (p.get("ltp"), n.get("ltp"))}
        for g in ("delta", "gamma", "theta", "vega", "rho"):
            vals[g] = (gp and gp[g], gn and gn[g])
        for name, (a, b) in vals.items():
            f[f"{side}_{name}_prev"], f[f"{side}_{name}_now"] = a, b
            f[f"{side}_{name}_chg"] = None if a is None or b is None else b - a
        f[f"{side}_securityId"] = n["securityId"]

    ivs = [f.get("CE_iv_chg"), f.get("PE_iv_chg")]
    f["ivChgAvg"] = None if None in ivs else sum(ivs) / 2

    common = sorted(set(prev["chain"]) & set(now["chain"]))
    groups = {
        "cl": [atm - STEP, atm, atm + STEP],
        "cl3": [atm + k * STEP for k in range(-3, 4)],
        "chain": [k for k in common if abs(k - atm) <= CHAIN_WIDTH * STEP + 0.1],
    }
    for name, strikes in groups.items():
        for side in ("CE", "PE"):
            a, b = _oi_sum(prev, strikes, side), _oi_sum(now, strikes, side)
            f[f"{name}_{side}_oi_prev"], f[f"{name}_{side}_oi_now"] = a, b
            f[f"{name}_{side}_oi_chg"] = None if a is None or b is None else b - a
            f[f"{name}_{side}_oi_roc_pct"] = None if not a or b is None else 100 * (b - a) / a
            c = _oi_sum(back3, strikes, side) if back3 else None
            f[f"{name}_{side}_oi_roc3_pct"] = None if not c or b is None else 100 * (b - c) / c
        ce, pe = f[f"{name}_CE_oi_now"], f[f"{name}_PE_oi_now"]
        f[f"{name}_pcr"] = pe / ce if ce and pe is not None else None
    f["oiUpdated"] = bool(f.get("chain_CE_oi_chg") or f.get("chain_PE_oi_chg"))
    return f


def evaluate(f: dict[str, Any], config: dict[str, Any]) -> tuple[bool, list[str]]:
    """All enabled conditions must hold. Returns (matched, one line per condition)."""
    checks = []
    trig = abs(f["trigPts"])
    checks.append((trig >= config["minAbsTrigPts"], f"|trigger| {trig:.1f} pts vs {config['minAbsTrigPts']:g}"))
    if config["minVix"] > 0:
        v = f.get("vixNow")
        checks.append((v is not None and v >= config["minVix"], f"VIX {v if v is not None else '—'} vs {config['minVix']:g}"))
    if config["minAbsIvChg"] > 0:
        iv = f.get("ivChgAvg")
        checks.append((iv is not None and abs(iv) >= config["minAbsIvChg"],
                       f"|ATM IV chg| {abs(iv):.2f} vs {config['minAbsIvChg']:g}" if iv is not None else "ATM IV change unavailable"))
    if config["minRange5"] > 0:
        r = f.get("range5")
        checks.append((r is not None and r >= config["minRange5"], f"5-min range {r:.1f} vs {config['minRange5']:g}" if r is not None else "5-min range unavailable"))
    return all(ok for ok, _ in checks), [("✓ " if ok else "✗ ") + text for ok, text in checks]


# ---------------------------------------------------------------- monitor


def _bar_start(epoch: float) -> int:
    return int(epoch // 60 * 60)


def _ist_time(epoch: int) -> dtime:
    return datetime.fromtimestamp(epoch, IST).time()


async def monitor_once() -> None:
    now_epoch = time.time()
    now = now_ist()
    if not (weekday_open(now) and dtime(9, 16) <= now.time() <= dtime(15, 31)):
        return
    bar = _bar_start(now_epoch) - 60  # the bar that just closed
    since_close = now_epoch - (bar + 60)
    if bar <= _runtime["lastMinute"] or since_close < READY_AFTER_SECONDS or now_epoch - _runtime["lastAttempt"] < RETRY_SECONDS:
        return
    async with _lock:
        if bar <= _runtime["lastMinute"]:
            return
        _runtime["lastAttempt"] = now_epoch
        done = await _process_bar(bar)
        if done or since_close > GIVE_UP_AFTER_SECONDS:
            if not done:
                _runtime["skipped"] = f"{_ist_time(bar):%H:%M} skipped: market data not available in time"
            _runtime["lastMinute"] = bar


async def _process_bar(bar: int) -> bool:
    settings = get_settings()
    dhan = DhanService()
    today = now_ist().date()
    try:
        candles = await dhan.intraday_candles(str(settings.dhan_nifty_security_id), INDEX_SEGMENT, "INDEX", "1", today.isoformat(), today.isoformat())
    except Exception as exc:
        _runtime["error"] = f"candles: {exc}"
        return False
    candles = sorted((c for c in candles if int(c["time"]) <= bar), key=lambda c: c["time"])
    if not candles or int(candles[-1]["time"]) != bar:
        return False
    expiry = next((d for d in await _expiries(dhan) if d >= today), None)
    if not expiry:
        _runtime["error"] = "no NIFTY expiry listed"
        return False
    try:
        chain = await dhan.option_chain(settings.dhan_nifty_security_id, INDEX_SEGMENT, expiry.isoformat())
    except Exception as exc:
        _runtime["error"] = f"option chain: {exc}"
        return False
    rows = _chain_rows(chain)
    if not rows:
        _runtime["error"] = "empty option chain"
        return False
    vix = await _vix(dhan)
    _runtime["error"] = None

    last = candles[-1]
    expiry_close = datetime.combine(expiry, dtime(15, 30), IST).timestamp()
    snap = {"ts": bar, "spot": float(last["close"]), "vix": vix, "expiry": expiry.isoformat(), "chain": rows,
            "dteMinutes": max((expiry_close - (bar + 60)) / 60, 1.0)}
    _snaps[bar] = snap
    for old in [k for k in _snaps if k < bar - 600]:
        _snaps.pop(old, None)

    closes = [float(c["close"]) for c in candles]
    config = get_config()
    prev, back3 = _snaps.get(bar - 60), _snaps.get(bar - 180)
    frozen = len(candles) >= 2 and last["high"] == last["low"] and last["close"] == candles[-2]["close"]
    features, matched, reasons = None, False, []
    if prev and prev.get("expiry") == snap["expiry"] and not frozen:
        features = compute_features(prev, snap, back3, closes)
        matched, reasons = evaluate(features, config)
        est = estimate(abs(features["trigPts"]))
        features["estimate"] = est
    elif frozen:
        reasons = ["index bar is flat (frozen feed) -- skipped"]
    else:
        reasons = ["waiting for the previous minute's snapshot"]
    db.save_index_runway_minute({
        "ts": bar, "day": today.isoformat(), "close": snap["spot"], "trig_pts": features and features["trigPts"],
        "rng5": features and features.get("range5"), "vix": vix, "matched": int(matched), "reasons": json.dumps(reasons),
        "features": json.dumps(features) if features else None,
    })
    _runtime.update(lastCheck=bar, lastFeatures=features, lastReasons=reasons, lastMatched=matched)

    _score_minutes(today, bar, candles)
    await _close_due(snap, candles, config)
    if matched and features:
        await _maybe_open(snap, features, config)
    return True


def _forward_move(candles: list[dict[str, Any]], ts: int) -> tuple[float, int] | None:
    by_time = {int(c["time"]): float(c["close"]) for c in candles}
    if ts not in by_time:
        return None
    base, best = by_time[ts], None
    for k in (1, 2):
        nxt = by_time.get(ts + 60 * k)
        if nxt is not None and (best is None or abs(nxt - base) > abs(best[0])):
            best = (nxt - base, k)
    return best


def _score_minutes(today: date, bar: int, candles: list[dict[str, Any]]) -> None:
    for row in db.index_runway_minutes_missing_outcome(today.isoformat(), bar - 120):
        fw = _forward_move(candles, int(row["ts"]))
        if fw:
            db.set_index_runway_minute_outcome(int(row["ts"]), round(fw[0], 2), fw[1], int(abs(fw[0]) >= MOVE_PTS))


async def _maybe_open(snap: dict[str, Any], f: dict[str, Any], config: dict[str, Any]) -> None:
    t = _ist_time(snap["ts"] + 60)
    if not config["enabled"]:
        return
    if not (datetime.strptime(config["entryStart"], "%H:%M").time() <= t <= datetime.strptime(config["entryEnd"], "%H:%M").time()):
        return
    if len(db.list_index_runway_trades(status="OPEN")) >= int(config["maxOpen"]):
        return
    atm = f["atmStrike"]
    sides = ["CE", "PE"] if config["tradeMode"] == "straddle" else ["CE" if f["trigPts"] > 0 else "PE"]
    legs = []
    for side in sides:
        q = snap["chain"].get(atm, {}).get(side)
        if not q or not q.get("ltp"):
            logger.info("index_runway: no %s quote at %s, signal not traded", side, atm)
            return
        legs.append({"option": side, "strike": atm, "securityId": q["securityId"], "entry": q["ltp"], "exit": None})
    qty = int(config["lots"]) * LOT_SIZE
    est = f.get("estimate") or {}
    trade_id = db.insert_index_runway_trade({
        "day": datetime.fromtimestamp(snap["ts"], IST).date().isoformat(), "signal_ts": snap["ts"], "mode": config["tradeMode"],
        "direction": "UP" if f["trigPts"] > 0 else "DOWN", "status": "OPEN", "expiry": snap["expiry"], "atm_strike": atm,
        "lots": int(config["lots"]), "quantity": qty, "legs": json.dumps(legs), "entry_time": snap["ts"],
        "exit_due": snap["ts"] + 60 * int(config["holdMinutes"]), "spot_entry": snap["spot"], "trig_pts": f["trigPts"],
        "est_move": est.get("median"), "est_p75": est.get("p75"), "est_hit40": est.get("hit40"), "features": json.dumps(f),
    })
    if config["notify"]:
        what = " + ".join(f"{l['strike']:g} {l['option']} @ {l['entry']:.2f}" for l in legs)
        await _notify(f"Index Runway #{trade_id} (paper): trigger {f['trigPts']:+.1f} pts, VIX {f.get('vixNow')}, "
                      f"bought {what}. Est. move {est.get('median', '—')}-{est.get('p75', '—')} pts in {config['holdMinutes']} min.")


async def _close_due(snap: dict[str, Any], candles: list[dict[str, Any]], config: dict[str, Any]) -> None:
    force = _ist_time(snap["ts"] + 60) >= FORCE_EXIT
    for t in db.list_index_runway_trades(status="OPEN"):
        if snap["ts"] < int(t["exit_due"]) and not force:
            continue
        legs = json.loads(t["legs"])
        if snap.get("expiry") != t["expiry"]:
            continue
        prices = [snap["chain"].get(float(l["strike"]), {}).get(l["option"], {}).get("ltp") for l in legs]
        if any(p is None for p in prices):
            continue  # try again next minute
        _close(t, legs, prices, snap, "time" if snap["ts"] >= int(t["exit_due"]) else "eod", candles)


def _close(t: dict[str, Any], legs: list[dict[str, Any]], prices: list[float], snap: dict[str, Any] | None, reason: str,
           candles: list[dict[str, Any]] | None = None) -> None:
    qty = int(t["quantity"])
    gross = charges = 0.0
    for leg, price in zip(legs, prices):
        leg["exit"] = price
        gross += (price - float(leg["entry"])) * qty
        charges += option_order_charges(premium=float(leg["entry"]), quantity=qty, side="BUY", exchange_segment=OPTION_SEGMENT)["total"]
        charges += option_order_charges(premium=price, quantity=qty, side="SELL", exchange_segment=OPTION_SEGMENT)["total"]
    fw = _forward_move(candles or [], int(t["signal_ts"])) if candles else None
    db.update_index_runway_trade(int(t["id"]), {
        "status": "CLOSED", "legs": json.dumps(legs), "exit_time": snap["ts"] if snap else int(time.time()), "exit_reason": reason,
        "spot_exit": snap["spot"] if snap else None, "actual_move": round(fw[0], 2) if fw else None,
        "hit40": int(abs(fw[0]) >= MOVE_PTS) if fw else None,
        "gross_pnl": round(gross, 2), "charges": round(charges, 2), "net_pnl": round(gross - charges, 2),
    })


async def close_now(trade_id: int) -> dict[str, Any]:
    trade = next((t for t in db.list_index_runway_trades(status="OPEN") if int(t["id"]) == trade_id), None)
    if not trade:
        return {"status": "not_open"}
    latest = _snaps[max(_snaps)] if _snaps else None
    legs = json.loads(trade["legs"])
    prices = [latest and latest["chain"].get(float(l["strike"]), {}).get(l["option"], {}).get("ltp") for l in legs] if latest else []
    if not latest or any(p is None for p in prices):
        return {"status": "no_price", "message": "No fresh option prices yet; it will close at its scheduled minute."}
    _close(trade, legs, prices, latest, "manual")
    return {"status": "closed"}


# ---------------------------------------------------------------- read side


def _trade_payload(t: dict[str, Any]) -> dict[str, Any]:
    features = json.loads(t["features"]) if t.get("features") else {}
    return {
        "id": t["id"], "day": t["day"], "signalTime": t["signal_ts"], "mode": t["mode"], "direction": t["direction"], "status": t["status"],
        "expiry": t["expiry"], "atmStrike": t["atm_strike"], "lots": t["lots"], "quantity": t["quantity"], "legs": json.loads(t["legs"]),
        "entryTime": t["entry_time"], "exitDue": t["exit_due"], "exitTime": t["exit_time"], "exitReason": t["exit_reason"],
        "spotEntry": t["spot_entry"], "spotExit": t["spot_exit"], "trigPts": t["trig_pts"], "estMove": t["est_move"], "estP75": t["est_p75"],
        "estHit40": t["est_hit40"], "actualMove": t["actual_move"], "hit40": None if t["hit40"] is None else bool(t["hit40"]),
        "grossPnl": t["gross_pnl"], "charges": t["charges"], "netPnl": t["net_pnl"],
        "vix": features.get("vixNow"), "vixChg": features.get("vixChg"), "ivChg": features.get("ivChgAvg"),
        "features": features,
    }


def list_trades() -> list[dict[str, Any]]:
    return [_trade_payload(t) for t in db.list_index_runway_trades()]


def list_signals(day: str | None = None) -> list[dict[str, Any]]:
    out = []
    for r in db.list_index_runway_minutes(day=day, matched_only=True, limit=500):
        f = json.loads(r["features"]) if r.get("features") else {}
        out.append({"time": r["ts"], "day": r["day"], "close": r["close"], "trigPts": r["trig_pts"], "range5": r["rng5"], "vix": r["vix"],
                    "vixChg": f.get("vixChg"), "ivChg": f.get("ivChgAvg"), "clCeRoc3": f.get("cl_CE_oi_roc3_pct"),
                    "clPeRoc3": f.get("cl_PE_oi_roc3_pct"), "estimate": f.get("estimate"), "fwdMove": r["fwd_move"],
                    "fwdMinutes": r["fwd_minutes"], "hit40": None if r["hit40"] is None else bool(r["hit40"]), "features": f})
    return out


def market_open(now: datetime) -> bool:
    return weekday_open(now) and dtime(9, 15) <= now.time() <= dtime(15, 30)


async def state() -> dict[str, Any]:
    stats = db.index_runway_minute_stats()
    return {
        "config": get_config(),
        "marketOpen": market_open(now_ist()),
        "monitorEnabled": get_settings().index_runway_monitor_enabled,
        "lastCheck": _runtime["lastCheck"],
        "lastFeatures": _runtime["lastFeatures"],
        "lastReasons": _runtime["lastReasons"],
        "lastMatched": _runtime["lastMatched"],
        "skipped": _runtime["skipped"],
        "error": _runtime["error"],
        "openTrades": [_trade_payload(t) for t in db.list_index_runway_trades(status="OPEN")],
        "stats": {
            "days": stats.get("days") or 0,
            "minutes": stats.get("minutes") or 0,
            "scored": stats.get("scored") or 0,
            "hits": stats.get("hits") or 0,
            "signals": stats.get("signals") or 0,
            "signalsScored": stats.get("signals_scored") or 0,
            "signalHits": stats.get("signal_hits") or 0,
        },
    }


# ---------------------------------------------------------------- task


async def _notify(text: str) -> None:
    try:
        await TelegramNotifier().send(text)
    except Exception:
        logger.warning("index_runway: telegram send failed")


def start_index_runway_task() -> asyncio.Task | None:
    if not get_settings().index_runway_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_index_runway_task(task: asyncio.Task | None) -> None:
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
            logger.exception("index_runway: monitor iteration failed")
        await asyncio.sleep(POLL_SECONDS)
