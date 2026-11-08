"""P&F Lab -- paper trading of the five P&F pattern systems (app/services/pf_lab_engine.py)
on NIFTY (Dhan option credit spreads), BTC and gold (Delta perpetuals), at three
horizons (0.25 / 1 / 3 % boxes on daily closes): 9 pages, 5 systems each.

Signals: the same replay the backtest uses (backend/data/history/backtests/pf_lab_bt.py).
Every run replays the market's daily closes; each book (market x horizon x system)
is then moved to the replay's current position:
  NIFTY  daily at 15:25 IST with the live index as today's close. Bullish -> sell an
         ATM put spread, bearish -> ATM call spread (1 lot by default), expiry
         >= 7 / 28 / 55 days, width 1.5 / 3 / 5 % of spot; rolled to a fresh ATM spread
         when 5 days are left. Paper fills: sell at bid, buy at ask (Dhan chain).
  BTC / GOLD  daily at 05:35 IST, after the UTC daily close. Charts use Binance
         BTCUSDT / PAXGUSDT daily closes (the backtest's data); paper fills at Delta
         India's BTCUSD / XAUTUSD price, $1,000 notional by default, taker fee
         0.05% + GST per side. Funding is not booked.
When a book first starts it joins the system's current position (trigger "start"),
so long-horizon books are not idle for months; later changes are trigger "signal".
Paper only -- there is no order code here.
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

import httpx

from app.core.sessions import weekday_open
from app.core.config import get_settings
from app.db import sqlite as db
from app.services import pf_lab_engine as P
from app.services import varaha
from app.services.charges import option_order_charges
from app.services.delta_exchange import DeltaExchangeService
from app.services.dhan import DhanService
from app.services.telegram import TelegramNotifier
from app.core.market_calendar import holidays_from_settings, is_trading_day

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
BACKTEST_FILE = Path(__file__).resolve().parents[1] / "data" / "pf_lab_backtest.json"

MARKETS: dict[str, dict[str, Any]] = {
    "NIFTY": {"label": "NIFTY", "venue": "Dhan options", "instrument": "NIFTY credit spread", "start": "2008-01-01"},
    "BTC": {"label": "BTC", "venue": "Delta perpetual", "instrument": "BTCUSD", "binance": "BTCUSDT", "contract": 0.001, "start": "2017-08-17"},
    "GOLD": {"label": "Gold", "venue": "Delta perpetual", "instrument": "XAUTUSD", "binance": "PAXGUSDT", "contract": 0.001, "start": "2020-08-28"},
}
HORIZONS = {"short": "Short term", "medium": "Medium term", "long": "Long term"}
SPREAD_RULES = {"short": (7, 1.5), "medium": (28, 3.0), "long": (55, 5.0)}  # min days to expiry, width % of spot
ROLL_DAYS = 5
LOT = 65
CRYPTO_FEE = 0.0005 * 1.18
NIFTY_RUN_AT = dtime(15, 25)
CRYPTO_RUN_AT = dtime(5, 35)
_lock = asyncio.Lock()
_backtest: dict[str, Any] | None = None


# ---------------------------------------------------------------- settings


def config(market: str, horizon: str) -> dict[str, Any]:
    key = f"{market}.{horizon}"
    get = lambda k, d: db.pf_get_setting(f"{key}.{k}") or d
    return {
        "enabled": get("enabled", "1") == "1",
        "lots": int(float(get("lots", "1"))),
        "notionalUsd": float(get("notionalUsd", "1000")),
        "systems": [s for s in P.SYSTEMS if get(f"system.{s}", "1") == "1"],
        "boxPercent": P.HORIZON_BOX[horizon],
    }


def update_config(market: str, horizon: str, updates: dict[str, Any]) -> dict[str, Any]:
    key = f"{market}.{horizon}"
    if "enabled" in updates:
        db.pf_set_setting(f"{key}.enabled", "1" if updates["enabled"] else "0")
    if "lots" in updates:
        lots = int(float(updates["lots"]))
        if not 1 <= lots <= 10:
            raise ValueError("lots must be 1-10")
        db.pf_set_setting(f"{key}.lots", str(lots))
    if "notionalUsd" in updates:
        n = float(updates["notionalUsd"])
        if not 50 <= n <= 100000:
            raise ValueError("notionalUsd must be 50-100000")
        db.pf_set_setting(f"{key}.notionalUsd", str(n))
    for s, on in (updates.get("systems") or {}).items():
        if s in P.SYSTEMS:
            db.pf_set_setting(f"{key}.system.{s}", "1" if on else "0")
    return config(market, horizon)


def backtest() -> dict[str, Any]:
    global _backtest
    if _backtest is None:
        _backtest = json.loads(BACKTEST_FILE.read_text()) if BACKTEST_FILE.exists() else {"cells": {}, "data": {}}
    return _backtest


# ---------------------------------------------------------------- data


async def sync_bars(market: str) -> int:
    """Completed daily closes into pf_lab_bars (full history the first time)."""
    have = db.pf_list_bars(market)
    since = date.fromisoformat(MARKETS[market]["start"]) if not have else (datetime.fromtimestamp(have[-1]["time"], IST).date() - timedelta(days=10))
    if market == "NIFTY":
        today = datetime.now(IST).date()
        candles = await DhanService().historical_daily_candles(str(get_settings().dhan_nifty_security_id), "IDX_I", "INDEX", since.isoformat(), today.isoformat())
        rows = [(int(c["time"]), float(c["close"])) for c in candles if datetime.fromtimestamp(int(c["time"]), IST).date() < today]
    else:
        rows = []
        start = int(datetime(since.year, since.month, since.day).timestamp() * 1000)
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                r = await client.get("https://api.binance.com/api/v3/klines", params={"symbol": MARKETS[market]["binance"], "interval": "1d", "startTime": start, "limit": 1000})
                data = r.json()
                if not isinstance(data, list) or not data:
                    break
                rows += [(int(k[0]) // 1000, float(k[4])) for k in data if int(k[0]) // 1000 + 86400 <= time.time()]
                if len(data) < 1000:
                    break
                start = int(data[-1][0]) + 86_400_000
    if rows:
        db.pf_save_bars(market, rows)
    return len(rows)


async def nifty_chain(expiry: date) -> tuple[float, dict[tuple[float, str], dict[str, Any]]]:
    chain = await DhanService().option_chain(get_settings().dhan_nifty_security_id, "IDX_I", expiry.isoformat())
    spot = varaha._number(chain.get("last_price")) or 0.0
    quotes = {}
    for row in varaha._trim_chain(chain, spot):
        for side in ("ce", "pe"):
            if row.get(side):
                quotes[(float(row["strike"]), side.upper())] = row[side]
    return spot, quotes


async def nifty_expiries() -> list[date]:
    raw = await DhanService().expiry_list(get_settings().dhan_nifty_security_id, "IDX_I")
    return sorted(date.fromisoformat(x) for x in raw)


def _fill(quote: dict[str, Any] | None, side: str) -> float | None:
    if not quote:
        return None
    bid, ask = quote.get("bid"), quote.get("ask")
    if bid and ask and ask >= bid > 0:
        return float(ask) if side == "BUY" else float(bid)
    return float(quote["ltp"]) if quote.get("ltp") else None


async def crypto_price(market: str) -> float:
    t = await DeltaExchangeService().get_ticker(MARKETS[market]["instrument"])
    return float(t.get("mark_price") or t.get("close") or 0)


# ---------------------------------------------------------------- paper execution


def _open_trade(market: str, horizon: str, system: str) -> dict[str, Any] | None:
    for t in db.pf_list_trades(market=market, horizon=horizon, status="OPEN"):
        if t["system"] == system:
            return t
    return None


def _event(market: str, horizon: str | None, system: str | None, kind: str, text: str) -> None:
    db.pf_add_event(market, horizon, system, kind, text)
    logger.info("pf_lab %s %s %s: %s", market, horizon, system, text)


async def _open_crypto(market: str, horizon: str, system: str, side: int, underlying: float, trigger: str, position_id: int | None = None) -> None:
    cfg = config(market, horizon)
    price = await crypto_price(market)
    contracts = max(1, round(cfg["notionalUsd"] / (price * MARKETS[market]["contract"])))
    qty = round(contracts * MARKETS[market]["contract"], 6)
    tid = db.pf_insert_trade({
        "market": market, "horizon": horizon, "system": system, "position_id": position_id, "side": side, "status": "OPEN", "trigger": trigger,
        "opened_at": int(time.time()), "underlying_entry": underlying, "instrument": MARKETS[market]["instrument"], "qty": qty,
        "entry_price": price, "charges": round(price * qty * CRYPTO_FEE, 4), "last_value": price, "last_pnl": 0.0, "last_update": int(time.time()),
    })
    if position_id is None:
        db.pf_update_trade(tid, position_id=tid)
    _event(market, horizon, system, "entry", f"{'LONG' if side == 1 else 'SHORT'} {contracts} {MARKETS[market]['instrument']} @ {price:,.2f} ({trigger})")


async def _close_crypto(t: dict[str, Any], underlying: float, reason: str) -> None:
    price = await crypto_price(t["market"])
    gross = (price - t["entry_price"]) * t["qty"] * t["side"]
    charges = (t["charges"] or 0) + price * t["qty"] * CRYPTO_FEE
    db.pf_update_trade(t["id"], status="CLOSED", closed_at=int(time.time()), exit_reason=reason, underlying_exit=underlying, exit_price=price,
                       realized=round(gross - charges, 4), charges=round(charges, 4), last_value=price, last_pnl=round(gross - charges, 4), last_update=int(time.time()))
    _event(t["market"], t["horizon"], t["system"], "exit", f"closed {t['instrument']} @ {price:,.2f} ({reason}): ${gross - charges:,.2f}")


def _pick_expiry(expiries: list[date], horizon: str, today: date) -> date | None:
    need = SPREAD_RULES[horizon][0]
    return next((e for e in expiries if (e - today).days >= need), None)


async def _open_spread(horizon: str, system: str, side: int, underlying: float, trigger: str, position_id: int | None = None) -> None:
    cfg = config("NIFTY", horizon)
    today = datetime.now(IST).date()
    expiry = _pick_expiry(await nifty_expiries(), horizon, today)
    if not expiry:
        _event("NIFTY", horizon, system, "skip", "no expiry far enough out")
        return
    spot, quotes = await nifty_chain(expiry)
    short_k = round(spot / 50) * 50
    width = max(100, round(spot * SPREAD_RULES[horizon][1] / 100 / 50) * 50)
    long_k = short_k - width if side == 1 else short_k + width
    kind = "PE" if side == 1 else "CE"
    sq, lq = quotes.get((float(short_k), kind)), quotes.get((float(long_k), kind))
    s_px, l_px = _fill(sq, "SELL"), _fill(lq, "BUY")
    if not s_px or not l_px or s_px <= l_px:
        _event("NIFTY", horizon, system, "skip", f"no usable quotes for {short_k:.0f}/{long_k:.0f} {kind} {expiry}")
        return
    qty = cfg["lots"] * LOT
    charges = sum(option_order_charges(premium=p, quantity=qty, side=sd, exchange_segment="NSE_FNO")["total"] for p, sd in ((s_px, "SELL"), (l_px, "BUY")))
    tid = db.pf_insert_trade({
        "market": "NIFTY", "horizon": horizon, "system": system, "position_id": position_id, "side": side, "status": "OPEN", "trigger": trigger,
        "opened_at": int(time.time()), "underlying_entry": underlying, "instrument": f"NIFTY {short_k:.0f}/{long_k:.0f} {kind}", "qty": qty,
        "expiry": expiry.isoformat(), "short_strike": short_k, "long_strike": long_k,
        "short_security_id": str((sq or {}).get("securityId") or ""), "long_security_id": str((lq or {}).get("securityId") or ""),
        "short_entry": s_px, "long_entry": l_px, "entry_price": round(s_px - l_px, 2), "charges": round(charges, 2),
        "last_value": round(s_px - l_px, 2), "last_pnl": round(-charges, 2), "last_update": int(time.time()),
    })
    if position_id is None:
        db.pf_update_trade(tid, position_id=tid)
    _event("NIFTY", horizon, system, "entry", f"{'BULL put' if side == 1 else 'BEAR call'} spread SELL {short_k:.0f} / BUY {long_k:.0f} {kind} {expiry} for {s_px - l_px:.2f} ({trigger})")


async def _close_spread(t: dict[str, Any], underlying: float, reason: str) -> None:
    spot, quotes = await nifty_chain(date.fromisoformat(t["expiry"]))
    kind = "PE" if t["side"] == 1 else "CE"
    s_px = _fill(quotes.get((float(t["short_strike"]), kind)), "BUY")
    l_px = _fill(quotes.get((float(t["long_strike"]), kind)), "SELL")
    if s_px is None or l_px is None:  # past or illiquid: settle at intrinsic
        s_px = max(0.0, (t["short_strike"] - spot) if kind == "PE" else (spot - t["short_strike"]))
        l_px = max(0.0, (t["long_strike"] - spot) if kind == "PE" else (spot - t["long_strike"]))
    gross = ((t["short_entry"] - s_px) + (l_px - t["long_entry"])) * t["qty"]
    charges = (t["charges"] or 0) + sum(option_order_charges(premium=max(p, 0.05), quantity=t["qty"], side=sd, exchange_segment="NSE_FNO")["total"]
                                        for p, sd in ((s_px, "BUY"), (l_px, "SELL")))
    db.pf_update_trade(t["id"], status="CLOSED", closed_at=int(time.time()), exit_reason=reason, underlying_exit=underlying, short_exit=s_px, long_exit=l_px,
                       exit_price=round(s_px - l_px, 2), realized=round(gross - charges, 2), charges=round(charges, 2),
                       last_value=round(s_px - l_px, 2), last_pnl=round(gross - charges, 2), last_update=int(time.time()))
    _event("NIFTY", t["horizon"], t["system"], "exit", f"closed {t['instrument']} {t['expiry']} at {s_px - l_px:.2f} ({reason}): ₹{gross - charges:,.0f}")


# ---------------------------------------------------------------- daily run


def _bars_with_today(market: str, today_close: float | None) -> list[dict[str, Any]]:
    bars = db.pf_list_bars(market)
    if today_close:
        now = int(time.time())
        if not bars or datetime.fromtimestamp(bars[-1]["time"], IST).date() < datetime.now(IST).date():
            bars = bars + [{"time": now, "close": today_close}]
    return bars


def desired_positions(market: str, horizon: str, bars: list[dict[str, Any]]) -> tuple[dict[str, int], Any]:
    rep = P.replay(bars, P.HORIZON_BOX[horizon])
    return {s: (rep["open"][s]["side"] if rep["open"][s] else 0) for s in P.SYSTEMS}, rep


async def run_market(market: str, trigger: str = "scheduled") -> dict[str, Any]:
    async with _lock:
        await sync_bars(market)
        today_close = None
        if market == "NIFTY":
            exp = await nifty_expiries()
            spot, _ = await nifty_chain(exp[0])
            today_close = spot or None
        bars = _bars_with_today(market, today_close)
        if len(bars) < 300:
            return {"status": "skipped", "message": "not enough history"}
        underlying = bars[-1]["close"]
        done = []
        for horizon in HORIZONS:
            cfg = config(market, horizon)
            want, _ = desired_positions(market, horizon, bars)
            started = db.pf_get_setting(f"{market}.{horizon}.started") == "1"
            for system in P.SYSTEMS:
                t = _open_trade(market, horizon, system)
                cur = t["side"] if t else 0
                desired = want[system] if (cfg["enabled"] and system in cfg["systems"]) else 0
                try:
                    if t and market == "NIFTY" and desired == cur and (date.fromisoformat(t["expiry"]) - datetime.now(IST).date()).days <= ROLL_DAYS:
                        await _close_spread(t, underlying, "roll")
                        await _open_spread(horizon, system, cur, underlying, "roll", position_id=t["position_id"])
                        done.append(f"{horizon}/{system} roll")
                        continue
                    if desired == cur:
                        continue
                    if t:
                        reason = "signal flip" if desired else ("exit signal" if cfg["enabled"] and system in cfg["systems"] else "disabled")
                        await (_close_spread(t, underlying, reason) if market == "NIFTY" else _close_crypto(t, underlying, reason))
                    if desired:
                        how = "signal" if started else "start"
                        await (_open_spread(horizon, system, desired, underlying, how) if market == "NIFTY" else _open_crypto(market, horizon, system, desired, underlying, how))
                    done.append(f"{horizon}/{system} {cur:+d}->{desired:+d}")
                except Exception as exc:
                    logger.exception("pf_lab: %s %s %s failed", market, horizon, system)
                    _event(market, horizon, system, "error", f"{type(exc).__name__}: {exc}")
            if not started:
                db.pf_set_setting(f"{market}.{horizon}.started", "1")
        db.pf_set_setting(f"{market}.lastRun", str(int(time.time())))
        if done:
            await _notify(f"📊 P&F Lab {MARKETS[market]['label']} ({trigger}): " + "; ".join(done))
        return {"status": "ok", "changes": done, "close": underlying}


async def mark_to_market(market: str) -> None:
    trades = db.pf_list_trades(market=market, status="OPEN")
    if not trades:
        return
    if market == "NIFTY":
        chains: dict[str, Any] = {}
        for t in trades:
            if t["expiry"] not in chains:
                chains[t["expiry"]] = await nifty_chain(date.fromisoformat(t["expiry"]))
            _, quotes = chains[t["expiry"]]
            kind = "PE" if t["side"] == 1 else "CE"
            s_px, l_px = _fill(quotes.get((float(t["short_strike"]), kind)), "BUY"), _fill(quotes.get((float(t["long_strike"]), kind)), "SELL")
            if s_px is None or l_px is None:
                continue
            value = s_px - l_px
            db.pf_update_trade(t["id"], last_value=round(value, 2), last_pnl=round((t["entry_price"] - value) * t["qty"] - (t["charges"] or 0), 2), last_update=int(time.time()))
    else:
        price = await crypto_price(market)
        for t in trades:
            db.pf_update_trade(t["id"], last_value=price, last_pnl=round((price - t["entry_price"]) * t["qty"] * t["side"] - (t["charges"] or 0), 4), last_update=int(time.time()))


async def close_now(trade_id: int) -> dict[str, Any]:
    t = next((x for x in db.pf_list_trades(status="OPEN") if x["id"] == trade_id), None)
    if not t:
        return {"status": "blocked", "message": "not open"}
    async with _lock:
        bars = db.pf_list_bars(t["market"])
        underlying = bars[-1]["close"] if bars else 0.0
        await (_close_spread(t, underlying, "manual") if t["market"] == "NIFTY" else _close_crypto(t, underlying, "manual"))
    return {"status": "closed"}


# ---------------------------------------------------------------- page state


def _summ(t: dict[str, Any]) -> dict[str, Any]:
    pnl = t["realized"] if t["status"] == "CLOSED" else t["last_pnl"]
    return {
        "id": t["id"], "positionId": t["position_id"], "system": t["system"], "side": t["side"], "status": t["status"], "trigger": t["trigger"],
        "openedAt": t["opened_at"], "closedAt": t["closed_at"], "exitReason": t["exit_reason"], "underlyingEntry": t["underlying_entry"],
        "underlyingExit": t["underlying_exit"], "instrument": t["instrument"], "qty": t["qty"], "entryPrice": t["entry_price"], "exitPrice": t["exit_price"],
        "expiry": t["expiry"], "lastValue": t["last_value"], "pnl": pnl, "charges": t["charges"], "lastUpdate": t["last_update"],
    }


def state(market: str, horizon: str) -> dict[str, Any]:
    cfg = config(market, horizon)
    bars = db.pf_list_bars(market)
    out: dict[str, Any] = {"market": market, "horizon": horizon, "meta": MARKETS[market], "horizonLabel": HORIZONS[horizon], "config": cfg,
                           "systems": [{"key": s, "label": P.SYSTEM_LABELS[s]} for s in P.SYSTEMS],
                           "lastRun": int(db.pf_get_setting(f"{market}.lastRun") or 0) or None,
                           "currency": "₹" if market == "NIFTY" else "$"}
    if len(bars) >= 300:
        want, rep = desired_positions(market, horizon, bars)
        chart = rep["chart"]
        cols = chart.columns[-60:]
        start = len(chart.columns) - len(cols)
        out["chart"] = {
            "columns": [{"index": start + k, "type": c["type"], "top": c["top"], "bottom": c["bottom"],
                         "topPrice": round(chart.price(c["top"]), 2), "bottomPrice": round(chart.price(c["bottom"]), 2),
                         "start": c["start"], "end": c["end"]} for k, c in enumerate(cols)],
            "ma": chart.ma(), "lastClose": bars[-1]["close"], "lastTime": bars[-1]["time"], "boxPercent": P.HORIZON_BOX[horizon],
        }
        out["signals"] = {s: {"side": want[s], "since": (rep["open"][s] or {}).get("entryTime"), "at": (rep["open"][s] or {}).get("entryPrice"),
                              "lastTrades": [{"side": x["side"], "entryTime": x["entryTime"], "entryPrice": x["entryPrice"], "exitTime": x["exitTime"],
                                              "exitPrice": x["exitPrice"]} for x in rep["trades"][s][-5:]]} for s in P.SYSTEMS}
    trades = [_summ(t) for t in db.pf_list_trades(market=market, horizon=horizon)]
    out["trades"] = trades
    out["totals"] = {s: {"realized": round(sum(t["pnl"] or 0 for t in trades if t["system"] == s and t["status"] == "CLOSED"), 2),
                         "open": round(sum(t["pnl"] or 0 for t in trades if t["system"] == s and t["status"] == "OPEN"), 2),
                         "closedCount": sum(t["system"] == s and t["status"] == "CLOSED" for t in trades)} for s in P.SYSTEMS}
    out["backtest"] = {s: backtest()["cells"].get(f"{market}|{horizon}|{s}") for s in P.SYSTEMS}
    out["backtestData"] = backtest()["data"].get(market)
    out["events"] = db.pf_list_events(market, horizon, limit=60)
    return out


def overview() -> dict[str, Any]:
    trades = db.pf_list_trades()
    books = {}
    for m in MARKETS:
        for h in HORIZONS:
            ts = [t for t in trades if t["market"] == m and t["horizon"] == h]
            books[f"{m}|{h}"] = {
                "open": sum(t["status"] == "OPEN" for t in ts),
                "realized": round(sum(t["realized"] or 0 for t in ts if t["status"] == "CLOSED"), 2),
                "openPnl": round(sum(t["last_pnl"] or 0 for t in ts if t["status"] == "OPEN"), 2),
                "currency": "₹" if m == "NIFTY" else "$",
            }
    return {"backtest": backtest(), "books": books, "markets": MARKETS, "horizons": HORIZONS,
            "systems": [{"key": s, "label": P.SYSTEM_LABELS[s]} for s in P.SYSTEMS]}


# ---------------------------------------------------------------- loop


async def _notify(text: str) -> None:
    try:
        await TelegramNotifier().send(text)
    except Exception:
        logger.warning("pf_lab: telegram send failed")


def _due(market: str, now: datetime) -> bool:
    last = int(db.pf_get_setting(f"{market}.lastRun") or 0)
    last_day = datetime.fromtimestamp(last, IST).date() if last else None
    if market == "NIFTY":
        return (is_trading_day(now.date(), holidays_from_settings(get_settings())) and NIFTY_RUN_AT <= now.time() < dtime(15, 30)
                and last_day != now.date())
    return now.time() >= CRYPTO_RUN_AT and last_day != now.date()


async def _loop() -> None:
    mtm_at = 0.0
    while True:
        try:
            now = datetime.now(IST)
            for market in MARKETS:
                if _due(market, now):
                    try:
                        await run_market(market)
                    except Exception as exc:
                        logger.exception("pf_lab: run %s failed", market)
                        _event(market, None, None, "error", f"run failed: {exc}")
                        db.pf_set_setting(f"{market}.lastRun", str(int(time.time())))  # do not retry every minute
            if time.time() - mtm_at > 300:
                mtm_at = time.time()
                for market in MARKETS:
                    if market == "NIFTY" and not (weekday_open(now) and dtime(9, 15) <= now.time() <= dtime(15, 30)):
                        continue
                    try:
                        await mark_to_market(market)
                    except Exception:
                        logger.warning("pf_lab: mark %s failed", market, exc_info=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("pf_lab: loop iteration failed")
        await asyncio.sleep(60)


def start_pf_lab_task() -> asyncio.Task | None:
    if not get_settings().pf_lab_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_pf_lab_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return
