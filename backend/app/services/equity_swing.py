"""Equity-Swing -- NIFTY 200 rotation (paper first, Angel One live).

Model (since 11 Nov 2026): alpha + low volatility, rebalanced on the last trading day
of each month -- see equity_swing_engine.rank_alpha_lowvol for the rule and the
back-test. The earlier weekly 1/3-month momentum model is kept as model = "momentum".

Schedule (IST, NSE trading days):
  15:45+  daily      sync daily candles for the 200 stocks + NIFTY (Dhan),
                     record the day's equity
  16:15+  last trading day of the week
                     rank, apply the quality gate (Screener) and the news
                     check (company-specific bad news) to would-be buys, and
                     plan sells/buys for the next session
  09:20+  next trading day
                     execute the plan at the open: sells first, then buys,
                     equal weight (equity / positions)
  market hours, every 5 min: mark open positions to market

Paper fills: the day's open +- slippage, delivery charges. Live (page mode =
live AND EQUITY_SWING_LIVE_ORDER_ENABLED AND LIVE_ORDER_ENABLED): Angel One
CNC market orders, fills read back from the order book.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.market_calendar import holidays_from_settings, is_trading_day
from app.db import sqlite as db
from app.services import equity_swing_engine as engine
from app.services.dhan import DhanService
from app.services.equity_entry import quality_failures
from app.services.telegram import TelegramNotifier

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
UNIVERSE_FILE = Path(__file__).resolve().parents[1] / "data" / "nifty200.json"
NIFTY_KEY = "IDX:13"
HISTORY_DAYS = 2200  # ~6 years: enough to trade (14 months) and to back-test in retrospectives
POLL_SECONDS = 60

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "mode": "paper",
    "capital": 500000.0,
    "model": "alpha_lowvol",  # or "momentum" (the pre-Nov-2026 weekly model)
    "frequency": "monthly",  # or "weekly"
    "positions": 30,
    "buyRank": 15,  # new buys only from the top N
    "fillDepth": 15,  # momentum model: fill slots from ranks down to this
    "exitRank": 45,
    "maxHoldWeeks": 0,  # 0 = no cap
    "cooldownWeeks": 0,
    "lookbacks": "21,63",  # momentum model only
    "requireSma200": False,
    "regimeFilter": False,
    "qualityFilter": False,
    "newsFilter": False,
    "slippagePercent": 0.1,
    "rebalanceAfter": "16:15",
    "executeAt": "09:20",
}

_lock = asyncio.Lock()
_runtime: dict[str, Any] = {"lastMtm": 0.0}


# ---------------------------------------------------------------- config


def get_config() -> dict[str, Any]:
    config: dict[str, Any] = {}
    for key, default in DEFAULTS.items():
        raw = db.get_swing_setting(key)
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
    s = get_settings()
    config["liveOrdersAllowed"] = bool(s.equity_swing_live_order_enabled and s.live_order_enabled)
    config["angelConfigured"] = bool(s.angel_api_key and s.angel_client_id and s.angel_pin and s.angel_totp_secret)
    return config


def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if key not in DEFAULTS or value is None:
            continue
        default = DEFAULTS[key]
        if key == "mode":
            if value not in ("paper", "live"):
                raise ValueError("mode must be paper or live")
            if value == "live" and not get_config()["liveOrdersAllowed"]:
                raise ValueError("Live orders are switched off on the server (EQUITY_SWING_LIVE_ORDER_ENABLED / LIVE_ORDER_ENABLED).")
            if value == "live" and not get_config()["angelConfigured"]:
                raise ValueError("Angel One credentials (ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PIN, ANGEL_TOTP_SECRET) are not on the server.")
        if key == "lookbacks":
            parts = [int(x) for x in str(value).split(",") if x.strip()]
            if not parts or any(p < 5 or p > 250 for p in parts):
                raise ValueError("lookbacks must be trading-day counts between 5 and 250, e.g. 21,63")
            value = ",".join(str(p) for p in parts)
        if key == "model" and value not in ("alpha_lowvol", "momentum"):
            raise ValueError("model must be alpha_lowvol or momentum")
        if key == "frequency" and value not in ("monthly", "weekly"):
            raise ValueError("frequency must be monthly or weekly")
        if key in ("positions", "exitRank", "buyRank") and int(value) < 1:
            raise ValueError(f"{key} must be at least 1")
        if key in ("rebalanceAfter", "executeAt"):
            datetime.strptime(str(value), "%H:%M")
        db.set_swing_setting(key, ("1" if value else "0") if isinstance(default, bool) else str(value))
    return get_config()


MODEL_VERSION = "2"
MODEL_V2_SETTINGS = {"model": "alpha_lowvol", "frequency": "monthly", "positions": "30", "buyRank": "15", "fillDepth": "15", "exitRank": "45",
                     "maxHoldWeeks": "0", "cooldownWeeks": "0", "requireSma200": "0", "regimeFilter": "0", "qualityFilter": "0", "newsFilter": "0"}


def migrate_model() -> bool:
    """One-time switch of saved settings to the alpha + low-vol model (saved values
    would otherwise override the new defaults). Holdings are kept: the next monthly
    rebalance sells any that rank below the exit rank."""
    if db.get_swing_setting("modelVersion") == MODEL_VERSION:
        return False
    for key, value in MODEL_V2_SETTINGS.items():
        db.set_swing_setting(key, value)
    db.set_swing_setting("modelVersion", MODEL_VERSION)
    _event("model", "Model switched to alpha + low volatility, monthly: top 15 buys, up to 30 holdings, sell at rank 45 "
                    "(back-test 2008-2026: 15.1% CAGR, -37.8% max drawdown).")
    return True


def universe() -> list[dict[str, Any]]:
    return json.loads(UNIVERSE_FILE.read_text())["members"]


def _hhmm(value: str) -> dtime:
    return datetime.strptime(value, "%H:%M").time()


def _holidays():
    return holidays_from_settings(get_settings())


def _trading_day(day: date) -> bool:
    return is_trading_day(day, _holidays())


def is_rebalance_day(day: date, frequency: str | None = None) -> bool:
    """Last trading day of the month (monthly) or of the week (weekly)."""
    if not _trading_day(day):
        return False
    frequency = frequency or get_config()["frequency"]
    d = day + timedelta(days=1)
    while (d.month == day.month) if frequency == "monthly" else (d.weekday() < 5):
        if _trading_day(d):
            return False
        d += timedelta(days=1)
    return True


def period_key(now: datetime, frequency: str) -> str:
    return now.strftime("%Y-%m") if frequency == "monthly" else now.strftime("%G-W%V")


def _event(kind: str, text: str, symbol: str | None = None) -> None:
    db.swing_insert("equity_swing_events", {"time": int(time.time()), "kind": kind, "symbol": symbol, "text": text})


async def _notify(text: str) -> None:
    try:
        await TelegramNotifier().send(text)
    except Exception:
        logger.exception("equity_swing: telegram failed")


# ---------------------------------------------------------------- data


async def sync_bars(full: bool = False) -> dict[str, int]:
    """Daily candles for the universe + NIFTY, only what's missing."""
    dhan = DhanService(get_settings())
    today = datetime.now(IST).date()
    jobs = [(m["securityId"], "NSE_EQ", "EQUITY", m["securityId"]) for m in universe()] + [("13", "IDX_I", "INDEX", NIFTY_KEY)]
    fetched = failed = 0
    if db.get_swing_setting("bars.historyDays") != str(HISTORY_DAYS):  # one-time deeper backfill
        full = True
    for sid, segment, instrument, key in jobs:
        row = db.swing_rows("SELECT MAX(ts) AS last FROM equity_swing_bars WHERE security_id = ?", (key,))
        last = row[0]["last"] if row else None
        start = today - timedelta(days=HISTORY_DAYS) if (full or not last) else datetime.fromtimestamp(last, IST).date()
        if start > today:
            continue
        for attempt in range(3):
            await asyncio.sleep(0.35 + attempt * 2)
            try:
                candles = await dhan.historical_daily_candles(sid, segment, instrument, start.isoformat(), (today + timedelta(days=1)).isoformat())
                break
            except Exception as exc:
                if "Rate_Limit" in str(exc) and attempt < 2:
                    continue
                candles = None
                if "Data_Error" not in str(exc):
                    failed += 1
                    logger.warning("equity_swing: candles for %s failed: %s", key, exc)
                break
        if not candles:
            continue
        db.swing_execute_many(
            "INSERT OR REPLACE INTO equity_swing_bars (security_id, ts, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(key, int(c["time"]), c["open"], c["high"], c["low"], c["close"], c.get("volume")) for c in candles],
        )
        fetched += 1
    db.set_swing_setting("bars.syncedFor", today.isoformat())
    if full and not failed:
        db.set_swing_setting("bars.historyDays", str(HISTORY_DAYS))
    return {"series": fetched, "failed": failed}


def _closes(key: str) -> list[float]:
    return [r["close"] for r in db.swing_rows("SELECT close FROM equity_swing_bars WHERE security_id = ? ORDER BY ts", (key,))]


def _series(key: str) -> list[tuple[int, float]]:
    """[(day start ts in IST, close)] -- day-aligned so stocks and NIFTY match by date."""
    out = []
    for r in db.swing_rows("SELECT ts, close FROM equity_swing_bars WHERE security_id = ? ORDER BY ts", (key,)):
        d = datetime.fromtimestamp(int(r["ts"]), IST).date()
        out.append((int(datetime(d.year, d.month, d.day, tzinfo=IST).timestamp()), r["close"]))
    return out


def ranking_now(config: dict[str, Any]) -> list[dict[str, Any]]:
    if config["model"] == "alpha_lowvol":
        return engine.rank_alpha_lowvol({m["symbol"]: _series(m["securityId"]) for m in universe()}, _series(NIFTY_KEY))
    lookbacks = tuple(int(x) for x in str(config["lookbacks"]).split(","))
    return engine.rank(_closes_by_symbol(), lookbacks, bool(config["requireSma200"]))


def _closes_by_symbol() -> dict[str, list[float]]:
    return {m["symbol"]: _closes(m["securityId"]) for m in universe()}


def regime() -> dict[str, Any]:
    closes = _closes(NIFTY_KEY)
    sma200 = engine.sma(closes, 200)
    ok = bool(sma200 and closes and closes[-1] > sma200)
    return {"ok": ok, "nifty": closes[-1] if closes else None, "sma200": round(sma200, 2) if sma200 else None}


# ---------------------------------------------------------------- positions / cash


def open_trades() -> list[dict[str, Any]]:
    return db.swing_rows("SELECT * FROM equity_swing_trades WHERE status IN ('OPEN', 'PENDING_EXIT') ORDER BY entry_time")


def cash(config: dict[str, Any]) -> float:
    closed = db.swing_rows("SELECT COALESCE(SUM(pnl), 0) AS p FROM equity_swing_trades WHERE status = 'CLOSED'")[0]["p"]
    invested = sum(t["entry_price"] * t["qty"] + (t["entry_charges"] or 0) for t in open_trades())
    return round(float(config["capital"]) + closed - invested, 2)


def equity_now(config: dict[str, Any]) -> float:
    return cash(config) + sum((t["last_price"] or t["entry_price"]) * t["qty"] for t in open_trades())


def _cooldowns() -> dict[str, int]:
    out = {}
    for row in db.swing_rows("SELECT key, value FROM equity_swing_settings WHERE key LIKE 'cooldown.%'"):
        out[row["key"][9:]] = int(float(row["value"]))
    return out


# ---------------------------------------------------------------- weekly rebalance


async def _gates(symbols: list[str], config: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
    """Quality gate + company-news check for would-be buys -> ({symbol: block reason}, details)."""
    from app.api.equity import _fundamentals_for_holdings, _news_for_holding  # shared caches with the Equity page

    blocked: dict[str, str] = {}
    details: dict[str, Any] = {}
    if config["qualityFilter"] and symbols:
        fundamentals = await _fundamentals_for_holdings([{"symbol": s} for s in symbols], refresh=False)
        for s in symbols:
            f = fundamentals.get(s) or {}
            # no valuation test: momentum leaders trade above their usual PE almost by definition
            failed = quality_failures(f, include_valuation=False) if (f.get("roce") is not None or f.get("roe") is not None) else ["no Screener data"]
            details.setdefault(s, {})["quality"] = failed or "pass"
            if failed:
                blocked[s] = "quality gate: " + "; ".join(failed)
    if config["newsFilter"]:
        for s in symbols:
            if s in blocked:
                continue
            news = await _news_for_holding({"symbol": s, "tradingSymbol": s}, refresh=False)
            if news.get("warning") and "Refresh News" in str(news.get("warning")):
                news = await _news_for_holding({"symbol": s, "tradingSymbol": s}, refresh=True)
            details.setdefault(s, {})["news"] = {k: news.get(k) for k in ("sentiment", "negativeScope", "materialNegative", "summary")}
            if news.get("materialNegative") and news.get("negativeScope") == "company":
                blocked[s] = "material company-specific negative news"
    return blocked, details


async def rebalance(trigger: str = "scheduled") -> dict[str, Any]:
    config = get_config()
    now = int(time.time())
    week = period_key(datetime.now(IST), config["frequency"])
    ranking = ranking_now(config)
    if not ranking:
        raise RuntimeError("No price history yet -- run the data sync first.")
    reg = regime()
    regime_ok = reg["ok"] or not config["regimeFilter"]
    holdings = [{"symbol": t["symbol"], "entryTime": t["entry_time"]} for t in open_trades() if t["status"] == "OPEN"]
    held = {h["symbol"] for h in holdings}
    depth = int(config["buyRank"]) if config["model"] == "alpha_lowvol" else int(config["fillDepth"])
    candidates = [r["symbol"] for r in ranking if r["rank"] and r["rank"] <= depth and r["symbol"] not in held]
    blocked, details = await _gates(candidates, config) if regime_ok else ({}, {})
    max_hold_days = int(config["maxHoldWeeks"]) * 7 if int(config["maxHoldWeeks"]) else None
    the_plan = engine.plan(ranking, holdings, positions=int(config["positions"]), fill_depth=int(config["fillDepth"]),
                           buy_rank=int(config["buyRank"]) if config["model"] == "alpha_lowvol" else None, exit_rank=int(config["exitRank"]),
                           max_hold_days=max_hold_days, cooldown_until=_cooldowns(), now=now, regime_ok=regime_ok, blocked=blocked)
    # cancel any older plan that never ran, then record this one
    for t in db.swing_rows("SELECT id FROM equity_swing_trades WHERE status = 'PLANNED'"):
        db.swing_update("equity_swing_trades", t["id"], {"status": "CANCELLED", "note": "replaced by a newer plan"})
    meta = {m["symbol"]: m for m in universe()}
    for sell in the_plan["sells"]:
        for t in open_trades():
            if t["symbol"] == sell["symbol"] and t["status"] == "OPEN":
                db.swing_update("equity_swing_trades", t["id"], {"status": "PENDING_EXIT", "exit_reason": sell["reason"], "note": sell["kind"]})
    for buy in the_plan["buys"]:
        m = meta[buy["symbol"]]
        db.swing_insert("equity_swing_trades", {
            "symbol": buy["symbol"], "security_id": m["securityId"], "industry": m["industry"], "mode": config["mode"],
            "status": "PLANNED", "qty": 0, "planned_at": now, "entry_reason": buy["reason"], "entry_rank": buy["rank"],
            "entry_score": buy["score"],
        })
    by_symbol = {r["symbol"]: r for r in ranking}
    for t in open_trades():
        r = by_symbol.get(t["symbol"])
        db.swing_update("equity_swing_trades", t["id"], {"last_rank": r["rank"] if r else None})
    db.set_swing_setting("plan.createdAt", str(now))
    payload = {"week": week, "trigger": trigger, "regime": reg, "regimeOk": regime_ok, "plan": the_plan, "gates": details,
               "ranking": ranking[:40], "eligible": sum(1 for r in ranking if r["rank"]), "universe": len(ranking)}
    # a manual plan gets its own key so the period's scheduled rebalance still runs
    key = week if trigger == "scheduled" else f"{week} {trigger} {datetime.now(IST):%Y-%m-%d %H:%M}"
    db.swing_execute_many(
        "INSERT OR REPLACE INTO equity_swing_rankings (week, created_at, payload) VALUES (?, ?, ?)", [(key, now, json.dumps(payload))]
    )
    lines = [f"📈 Equity-Swing {'monthly' if config['frequency'] == 'monthly' else 'weekly'} plan ({week}, {config['mode']}, "
             f"{'alpha + low-vol' if config['model'] == 'alpha_lowvol' else 'momentum'})"]
    lines.append(f"NIFTY {reg['nifty']:,.0f} vs SMA200 {reg['sma200']:,.0f}: {'buys allowed' if regime_ok else 'NO new buys'}" if reg["nifty"] and reg["sma200"] else "NIFTY regime: no data")
    lines += [f"SELL {s['symbol']}: {s['reason']}" for s in the_plan["sells"]] or ["No sells."]
    lines += [f"BUY {b['symbol']}: {b['reason']}" for b in the_plan["buys"]] or ["No buys."]
    lines += [f"skip {s['symbol']} (rank {s['rank']}): {s['reason']}" for s in the_plan["skipped"]]
    lines.append(f"Orders go in at the next session's open (~{config['executeAt']}).")
    _event("plan", " | ".join(lines[1:]))
    await _notify("\n".join(lines))
    return payload


# ---------------------------------------------------------------- execution


async def _opens(security_ids: list[str]) -> dict[str, dict[str, float | None]]:
    if not security_ids:
        return {}
    quotes = await DhanService(get_settings()).market_quotes_by_segment({"NSE_EQ": sorted({int(s) for s in security_ids})})
    out = {}
    for sid, q in (quotes.get("NSE_EQ") or {}).items():
        out[str(sid)] = {"open": float((q.get("ohlc") or {}).get("open") or 0) or None, "ltp": float(q.get("last_price") or 0) or None}
    return out


async def _fill(config: dict[str, Any], t: dict[str, Any], side: str, qty: int, ref: float) -> tuple[float | None, str | None, str]:
    """(price, order id, note). Paper: reference +- slippage. Live: Angel market order."""
    slip = float(config["slippagePercent"]) / 100
    if config["mode"] != "live":
        return round(ref * (1 + slip if side == "BUY" else 1 - slip), 2), None, "paper fill at the open"
    from app.services.angel_broker import AngelBroker

    broker = AngelBroker()
    try:
        order_id = await broker.place_market_order(symbol=t["symbol"], token=t["security_id"], side=side, qty=qty, tag=f"SWING{t['id']}")
    except Exception as exc:  # e.g. AB4036: stock under exchange surveillance -- skip it, don't stop the other orders
        return None, None, f"Angel rejected the order: {exc}"
    for _ in range(10):
        await asyncio.sleep(2)
        info = await broker.order_fill(order_id)
        if info and info["status"] == "complete" and info["avgPrice"]:
            return info["avgPrice"], order_id, "Angel One fill"
        if info and info["status"] in ("rejected", "cancelled"):
            return None, order_id, f"Angel order {info['status']}: {info.get('text')}"
    return None, order_id, "Angel order not filled within 20 s -- check the order book"


SURVEILLANCE = ("AB4036", "cautionary", "surveillance", "ASM", "GSM", "ESM")


def _replacement(failed: dict[str, Any], note: str) -> dict[str, Any] | None:
    """When the exchange blocks a stock (surveillance list), plan the best-ranked stock not already held,
    planned or blocked today, from the latest ranking. Other failures (cash, price) get no replacement."""
    if not any(k.lower() in (note or "").lower() for k in SURVEILLANCE):
        return None
    latest = db.swing_rows("SELECT payload FROM equity_swing_rankings ORDER BY created_at DESC LIMIT 1")
    if not latest:
        return None
    ranking = json.loads(latest[0]["payload"]).get("ranking") or []
    since = int(time.time()) - 86400
    taken = {r["symbol"] for r in db.swing_rows(
        "SELECT symbol FROM equity_swing_trades WHERE status IN ('OPEN', 'PLANNED', 'PENDING_EXIT') OR (status = 'CANCELLED' AND planned_at >= ?)", (since,))}
    taken.add(failed["symbol"])
    meta = {m["symbol"]: m for m in universe()}
    for r in ranking:
        if r.get("rank") and r["symbol"] not in taken and r["symbol"] in meta:
            m = meta[r["symbol"]]
            new_id = db.swing_insert("equity_swing_trades", {
                "symbol": r["symbol"], "security_id": m["securityId"], "industry": m["industry"], "mode": failed["mode"],
                "status": "PLANNED", "qty": 0, "planned_at": int(time.time()), "entry_rank": r["rank"], "entry_score": r["score"],
                "entry_reason": f"rank {r['rank']}: replaces {failed['symbol']} (exchange surveillance block)",
            })
            _event("plan", f"{failed['symbol']} blocked by the exchange -- replaced by {r['symbol']} (rank {r['rank']})", r["symbol"])
            return db.swing_rows("SELECT * FROM equity_swing_trades WHERE id = ?", (new_id,))[0]
    return None


async def execute(trigger: str = "scheduled") -> dict[str, Any]:
    config = get_config()
    exits = [t for t in open_trades() if t["status"] == "PENDING_EXIT"]
    buys = db.swing_rows("SELECT * FROM equity_swing_trades WHERE status = 'PLANNED' ORDER BY entry_rank")
    if not exits and not buys:
        return {"status": "nothing to do"}
    prices = await _opens([t["security_id"] for t in exits + buys])
    now = int(time.time())
    session_open = int(datetime.combine(datetime.now(IST).date(), dtime(9, 15), tzinfo=IST).timestamp())
    # a plan made before today's session fills at the open; one made during it at the live price
    use_open = int(db.get_swing_setting("plan.createdAt") or 0) < session_open
    done = []
    for t in exits:
        p = prices.get(str(t["security_id"])) or {}
        ref = (p.get("open") if use_open else None) or p.get("ltp")
        if not ref:
            _event("error", f"No price for {t['symbol']} -- exit retried next poll", t["symbol"])
            continue
        price, order_id, note = await _fill(config, t, "SELL", int(t["qty"]), ref)
        if price is None:
            _event("error", f"{t['symbol']} exit failed: {note}", t["symbol"])
            await _notify(f"🚨 Equity-Swing: exit of {t['symbol']} failed -- {note}")
            continue
        charges = engine.delivery_charges(price * t["qty"], "SELL")
        pnl = round((price - t["entry_price"]) * t["qty"] - (t["entry_charges"] or 0) - charges, 2)
        db.swing_update("equity_swing_trades", t["id"], {"status": "CLOSED", "exit_time": now, "exit_price": price, "exit_charges": charges,
                                                         "pnl": pnl, "exit_order_id": order_id, "last_price": price})
        if t["note"] == "time" and int(config["cooldownWeeks"]):
            db.set_swing_setting(f"cooldown.{t['symbol']}", str(now + int(config["cooldownWeeks"]) * 7 * 86400))
        _event("exit", f"SOLD {t['qty']} {t['symbol']} @ {price:,.2f} ({note}) -- {t['exit_reason']} -- P&L ₹{pnl:,.0f}", t["symbol"])
        done.append(f"SELL {t['symbol']} {t['qty']} @ {price:,.2f}: ₹{pnl:,.0f} ({t['exit_reason']})")
    equity = equity_now(config)
    target = equity / max(int(config["positions"]), 1)
    replaced = 0
    queue = list(buys)
    while queue:
        t = queue.pop(0)
        p = prices.get(str(t["security_id"])) or {}
        ref = (p.get("open") if use_open else None) or p.get("ltp")
        available = cash(config) - 100
        if not ref:
            _event("error", f"No price for {t['symbol']} -- buy retried next poll", t["symbol"])
            continue
        qty = int(min(target, available) // (ref * (1 + float(config["slippagePercent"]) / 100) * 1.0025))
        if qty < 1:
            db.swing_update("equity_swing_trades", t["id"], {"status": "CANCELLED", "note": f"not enough cash (₹{available:,.0f})"})
            continue
        price, order_id, note = await _fill(config, t, "BUY", qty, ref)
        if price is None:
            db.swing_update("equity_swing_trades", t["id"], {"status": "CANCELLED", "note": note, "entry_order_id": order_id})
            sub = _replacement(t, note) if replaced < 5 else None
            if sub:  # exchange surveillance block: buy the next-ranked stock instead
                replaced += 1
                prices.update(await _opens([sub["security_id"]]))
                queue.append(sub)
            await _notify(f"🚨 Equity-Swing: buy of {t['symbol']} failed -- {note}" + (f"\nBuying the next-ranked stock instead: {sub['symbol']}" if sub else ""))
            continue
        charges = engine.delivery_charges(price * qty, "BUY")
        db.swing_update("equity_swing_trades", t["id"], {"status": "OPEN", "qty": qty, "entry_time": now, "entry_price": price,
                                                         "entry_charges": charges, "entry_order_id": order_id, "last_price": price,
                                                         "last_update": now, "mode": config["mode"]})
        _event("entry", f"BOUGHT {qty} {t['symbol']} @ {price:,.2f} ({note}) -- {t['entry_reason']}", t["symbol"])
        done.append(f"BUY {t['symbol']} {qty} @ {price:,.2f} (₹{price * qty:,.0f})")
    if done:
        await _notify(f"✅ Equity-Swing executed ({config['mode']}):\n" + "\n".join(done) + f"\nCash left ₹{cash(config):,.0f}")
    return {"status": "executed", "orders": done}


# ---------------------------------------------------------------- marking + equity curve


async def mark_to_market() -> None:
    trades = open_trades()
    if not trades:
        return
    prices = await _opens([t["security_id"] for t in trades])
    now = int(time.time())
    for t in trades:
        ltp = (prices.get(str(t["security_id"])) or {}).get("ltp")
        if ltp:
            db.swing_update("equity_swing_trades", t["id"], {"last_price": ltp, "last_update": now})


def record_equity(day: date) -> None:
    config = get_config()
    trades = open_trades()
    holdings_value = sum((t["last_price"] or t["entry_price"]) * t["qty"] for t in trades)
    c = cash(config)
    nifty = _closes(NIFTY_KEY)
    db.swing_execute_many(
        "INSERT OR REPLACE INTO equity_swing_equity (day, cash, holdings, equity, nifty, positions) VALUES (?, ?, ?, ?, ?, ?)",
        [(day.isoformat(), c, round(holdings_value, 2), round(c + holdings_value, 2), nifty[-1] if nifty else None, len(trades))],
    )


# ---------------------------------------------------------------- monitor


async def monitor_once() -> None:
    config = get_config()
    now = datetime.now(IST)
    today = now.date()
    if not _trading_day(today):
        return
    async with _lock:
        market = dtime(9, 15) <= now.time() <= dtime(15, 30)
        if market and time.time() - _runtime["lastMtm"] >= 300:
            _runtime["lastMtm"] = time.time()
            await mark_to_market()
        if now.time() >= _hhmm(config["executeAt"]) and market:
            pending = db.swing_rows(
                "SELECT COUNT(*) AS n FROM equity_swing_trades WHERE status = 'PLANNED' OR status = 'PENDING_EXIT'")[0]["n"]
            if pending and config["enabled"]:
                await execute("scheduled")
        if now.time() >= dtime(15, 45) and db.get_swing_setting("bars.syncedFor") != today.isoformat():
            result = await sync_bars()
            await mark_to_market()
            record_equity(today)
            _event("data", f"Daily candles synced: {result['series']} series, {result['failed']} failed")
        week = period_key(now, config["frequency"])
        if (config["enabled"] and is_rebalance_day(today, config["frequency"]) and now.time() >= _hhmm(config["rebalanceAfter"])
                and db.get_swing_setting("bars.syncedFor") == today.isoformat()
                and not db.swing_rows("SELECT week FROM equity_swing_rankings WHERE week = ?", (week,))):
            await rebalance("scheduled")
        if now.time() >= dtime(16, 30):
            from app.services import equity_swing_retro

            await equity_swing_retro.maybe_monthly(now)


async def _loop() -> None:
    try:
        migrate_model()
    except Exception:
        logger.exception("equity_swing: model migration failed")
    while True:
        try:
            await monitor_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("equity_swing: monitor failed")
        await asyncio.sleep(POLL_SECONDS)


def start_equity_swing_task() -> asyncio.Task | None:
    if not get_settings().equity_swing_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_equity_swing_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


# ---------------------------------------------------------------- reporting


def summarize_trade(t: dict[str, Any]) -> dict[str, Any]:
    price = t["exit_price"] if t["status"] == "CLOSED" else t["last_price"]
    gross = (price - t["entry_price"]) * t["qty"] if price and t["entry_price"] else None
    held_days = ((t["exit_time"] or time.time()) - t["entry_time"]) / 86400 if t["entry_time"] else None
    return {
        "id": t["id"], "symbol": t["symbol"], "securityId": t["security_id"], "industry": t["industry"], "mode": t["mode"],
        "status": t["status"], "qty": t["qty"], "plannedAt": t["planned_at"], "entryTime": t["entry_time"], "entryPrice": t["entry_price"],
        "entryCharges": t["entry_charges"], "entryReason": t["entry_reason"], "entryRank": t["entry_rank"], "entryScore": t["entry_score"],
        "exitTime": t["exit_time"], "exitPrice": t["exit_price"], "exitCharges": t["exit_charges"], "exitReason": t["exit_reason"],
        "pnl": t["pnl"] if t["status"] == "CLOSED" else (round(gross - (t["entry_charges"] or 0), 2) if gross is not None else None),
        "pnlPercent": round((price / t["entry_price"] - 1) * 100, 2) if price and t["entry_price"] else None,
        "lastPrice": t["last_price"], "lastRank": t["last_rank"], "heldWeeks": round(held_days / 7, 1) if held_days is not None else None,
        "note": t["note"],
    }


def state() -> dict[str, Any]:
    config = get_config()
    trades = db.swing_rows("SELECT * FROM equity_swing_trades ORDER BY id DESC LIMIT 400")
    latest = db.swing_rows("SELECT payload FROM equity_swing_rankings ORDER BY created_at DESC LIMIT 1")
    curve = db.swing_rows("SELECT * FROM equity_swing_equity ORDER BY day")
    closed = [t for t in trades if t["status"] == "CLOSED"]
    c = cash(config)
    open_rows = [summarize_trade(t) for t in trades if t["status"] in ("OPEN", "PENDING_EXIT")]
    holdings_value = sum((t["lastPrice"] or t["entryPrice"] or 0) * t["qty"] for t in open_rows)
    eq = c + holdings_value
    now = datetime.now(IST)
    nxt = now.date()
    while not is_rebalance_day(nxt, config["frequency"]):
        nxt += timedelta(days=1)
    return {
        "config": config,
        "summary": {
            "capital": config["capital"], "cash": c, "holdingsValue": round(holdings_value, 2), "equity": round(eq, 2),
            "pnl": round(eq - float(config["capital"]), 2), "pnlPercent": round((eq / float(config["capital"]) - 1) * 100, 2),
            "realized": round(sum(t["pnl"] or 0 for t in closed), 2), "closedTrades": len(closed),
            "winRate": round(sum(1 for t in closed if (t["pnl"] or 0) > 0) / len(closed) * 100, 1) if closed else None,
            "nextRebalance": nxt.isoformat(), "barsSyncedFor": db.get_swing_setting("bars.syncedFor"),
        },
        "regime": regime(),
        "open": open_rows,
        "planned": [summarize_trade(t) for t in trades if t["status"] == "PLANNED"],
        "closed": [summarize_trade(t) for t in closed],
        "latest": json.loads(latest[0]["payload"]) if latest else None,
        "equityCurve": curve,
        "events": db.swing_rows("SELECT * FROM equity_swing_events ORDER BY id DESC LIMIT 60"),
        "universe": len(universe()),
    }

