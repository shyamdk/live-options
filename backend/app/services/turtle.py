"""Define Turtle -- NIFTY P&F RSI + Turtle Follow-Through, paper trading.

Spec: define-turtle.md. Every completed 1-minute NIFTY candle the P&F chart
(0.03% log boxes, 3-box reversal) is rebuilt from ~30 trading days of 1-min
closes plus today's. A Turtle Follow-Through Bullish printed on the latest
close with P&F RSI(14) > 50 opens a next-week put credit spread (sell ATM put
rounded to 100, buy 300 lower) if none is open. Exits: 75% premium decay,
RSI < 50 on a minute close, or <= 3 calendar days to expiry -- the calendar
exit raises an unmissable alarm on the page plus Telegram.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.timeutil import now_ist
from app.db import sqlite as db
from app.services import turtle_engine as engine
from app.services import varaha
from app.services.charges import option_order_charges
from app.services.dhan import DhanService
from app.services.telegram import TelegramNotifier

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
INDEX_SEGMENT = "IDX_I"
OPTION_SEGMENT = "NSE_FNO"
LOT_SIZE = 65
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
POLL_SECONDS = 20
SIGNAL_MAX_AGE_SECONDS = 120
HISTORY_CALENDAR_DAYS = 45
_lock = asyncio.Lock()
_history: dict[str, Any] = {"date": None, "candles": []}
_expiry_cache: tuple[float, list[date]] | None = None
_last_state: dict[str, Any] = {}

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "capital": 1_000_000.0,
    "capitalPerLot": 150_000.0,
    "boxPercent": 0.03,
    "reversal": 3,
    "turtleLookback": 5,
    "rsiPeriod": 14,
    "rsiThreshold": 50.0,
    "spreadWidth": 300.0,
    "strikeRounding": 100.0,
    "profitDecayPercent": 75.0,
    "calendarExitDays": 3,
}


# ---------------------------------------------------------------- config


def get_config() -> dict[str, Any]:
    config = {}
    for key, default in DEFAULTS.items():
        raw = db.get_turtle_setting(key)
        if raw is None:
            config[key] = default
        elif isinstance(default, bool):
            config[key] = raw == "1"
        elif isinstance(default, int):
            config[key] = int(float(raw))
        else:
            config[key] = float(raw)
    config["lots"] = max(int(config["capital"] // config["capitalPerLot"]), 0)
    config["lotSize"] = LOT_SIZE
    return config


def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if key not in DEFAULTS or value is None:
            continue
        default = DEFAULTS[key]
        db.set_turtle_setting(key, ("1" if value else "0") if isinstance(default, bool) else str(value))
    return get_config()


# ---------------------------------------------------------------- data


async def _candles(dhan: DhanService) -> list[dict[str, Any]]:
    """~30 trading days of NIFTY 1-min candles (history refreshed once a day)
    plus today's, completed candles only."""
    settings = get_settings()
    today = now_ist().date()
    security = str(settings.dhan_nifty_security_id)
    if _history["date"] != today.isoformat():
        start = (today - timedelta(days=HISTORY_CALENDAR_DAYS)).isoformat()
        yesterday = (today - timedelta(days=1)).isoformat()
        history = await dhan.intraday_candles(security, INDEX_SEGMENT, "INDEX", "1", start, yesterday)
        _history.update(date=today.isoformat(), candles=sorted(history, key=lambda c: c["time"]))
    todays = await dhan.intraday_candles(security, INDEX_SEGMENT, "INDEX", "1", today.isoformat(), today.isoformat())
    cutoff = int(time.time())
    last_history = _history["candles"][-1]["time"] if _history["candles"] else 0
    fresh = [c for c in todays if c["time"] > last_history and int(c["time"]) + 60 <= cutoff]
    return _history["candles"] + sorted(fresh, key=lambda c: c["time"])


async def _expiries(dhan: DhanService) -> list[date]:
    global _expiry_cache
    if _expiry_cache and time.monotonic() - _expiry_cache[0] < 300:
        return _expiry_cache[1]
    raw = await dhan.expiry_list(get_settings().dhan_nifty_security_id, INDEX_SEGMENT)
    expiries = sorted(date.fromisoformat(x) for x in raw)
    _expiry_cache = (time.monotonic(), expiries)
    return expiries


def next_week_expiry(expiries: list[date], today: date) -> date | None:
    """The expiry AFTER the nearest one (define-turtle.md decision 4)."""
    upcoming = [d for d in expiries if d >= today]
    return upcoming[1] if len(upcoming) > 1 else None


async def _chain_quotes(dhan: DhanService, expiry: date) -> tuple[float, dict[tuple[float, str], dict[str, Any]]]:
    chain = await dhan.option_chain(get_settings().dhan_nifty_security_id, INDEX_SEGMENT, expiry.isoformat())
    spot = varaha._number(chain.get("last_price")) or 0.0
    quotes = {}
    for row in varaha._trim_chain(chain, spot):
        for side in ("ce", "pe"):
            if row.get(side):
                quotes[(float(row["strike"]), side.upper())] = row[side]
    return spot, quotes


def _fill(quote: dict[str, Any] | None, side: str) -> float | None:
    if not quote:
        return None
    bid, ask = quote.get("bid"), quote.get("ask")
    if bid and ask and ask >= bid > 0:
        return float(ask) if side == "BUY" else float(bid)
    return float(quote["ltp"]) if quote.get("ltp") else None


# ---------------------------------------------------------------- chart state


def _chart(candles: list[dict[str, Any]], config: dict[str, Any]) -> engine.PointAndFigure:
    return engine.build(
        candles, box_percent=float(config["boxPercent"]), reversal=int(config["reversal"]),
        turtle_lookback=int(config["turtleLookback"]),
    )


def _chart_payload(chart: engine.PointAndFigure, config: dict[str, Any], columns: int = 70) -> dict[str, Any]:
    period = int(config["rsiPeriod"])
    rsi_values = chart.rsi_series(period)
    start = max(0, len(chart.columns) - columns)
    cols = []
    for i in range(start, len(chart.columns)):
        c = chart.columns[i]
        cols.append({
            "index": i, "type": c["type"], "top": c["top"], "bottom": c["bottom"],
            "topPrice": round(chart.price(c["top"]), 2), "bottomPrice": round(chart.price(c["bottom"]), 2),
            "start": c["start"], "end": c["end"], "turtle": c["turtle"], "followThrough": c["followThrough"],
            "rsi": rsi_values[i] if i < len(rsi_values) else None,
        })
    return {
        "columns": cols,
        "signals": [s for s in chart.signals if s["column"] >= start],
        "rsi": chart.rsi(period),
        "boxPoints": round(chart.price(chart.columns[-1]["top"]) * float(config["boxPercent"]) / 100, 2) if chart.columns else None,
    }


async def state() -> dict[str, Any]:
    config = get_config()
    dhan = DhanService()
    payload: dict[str, Any] = {"config": config}
    try:
        candles = await _candles(dhan)
        chart = _chart(candles, config)
        payload["chart"] = _chart_payload(chart, config)
        payload["lastCandle"] = candles[-1] if candles else None
        rsi_now = payload["chart"]["rsi"]
        payload["trend"] = None if rsi_now is None else ("BULLISH" if rsi_now > float(config["rsiThreshold"]) else "NOT_BULLISH")
        follow = [s for s in chart.signals if s["kind"] == "turtle_follow_through"]
        payload["lastFollowThrough"] = follow[-1] if follow else None
        expiries = await _expiries(dhan)
        nxt = next_week_expiry(expiries, now_ist().date())
        payload["nextWeekExpiry"] = nxt.isoformat() if nxt else None
    except Exception as exc:
        payload["error"] = f"Dhan data unavailable: {exc}"
    payload["openTrades"] = [summarize(t) for t in db.list_turtle_trades(status="OPEN", limit=5)]
    payload["alarms"] = db.list_turtle_alarms(unacknowledged_only=True)
    payload["marketOpen"] = _market_open(datetime.now(IST))
    return payload


# ---------------------------------------------------------------- trading


def _market_open(now: datetime) -> bool:
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE


async def enter(trigger: str, signal: dict[str, Any] | None = None) -> dict[str, Any]:
    config = get_config()
    if config["lots"] < 1:
        return {"status": "blocked", "message": "Capital is below one lot's allocation."}
    if db.list_turtle_trades(status="OPEN", limit=1):
        return {"status": "blocked", "message": "A spread is already open -- one at a time."}
    dhan = DhanService()
    today = now_ist().date()
    expiry = next_week_expiry(await _expiries(dhan), today)
    if not expiry:
        return {"status": "skipped", "message": "No next-week expiry listed."}
    if (expiry - today).days <= int(config["calendarExitDays"]):
        return {"status": "skipped", "message": f"Next-week expiry {expiry} is within the {config['calendarExitDays']}-day calendar window."}
    spot, quotes = await _chain_quotes(dhan, expiry)
    rounding = float(config["strikeRounding"])
    short_strike = round(spot / rounding) * rounding
    long_strike = short_strike - float(config["spreadWidth"])
    short_q, long_q = quotes.get((short_strike, "PE")), quotes.get((long_strike, "PE"))
    short_fill, long_fill = _fill(short_q, "SELL"), _fill(long_q, "BUY")
    if not short_fill or not long_fill:
        return {"status": "skipped", "message": f"No quote for {short_strike:.0f} / {long_strike:.0f} PE."}
    credit = round(short_fill - long_fill, 2)
    if credit <= 0:
        return {"status": "skipped", "message": "Spread would not be a credit at current quotes."}
    trade_id = db.create_turtle_trade(
        status="OPEN", trigger=trigger, signal_time=(signal or {}).get("time"), signal_rsi=(signal or {}).get("rsi"),
        entry_time=int(time.time()), expiry=expiry.isoformat(), spot=spot, lots=int(config["lots"]), lot_size=LOT_SIZE,
        short_strike=short_strike, long_strike=long_strike,
        short_security_id=(short_q or {}).get("securityId"), long_security_id=(long_q or {}).get("securityId"),
        short_entry=short_fill, long_entry=long_fill, credit_points=credit, last_cost=credit, last_decay=0.0,
        last_rsi=(signal or {}).get("rsi"), last_update=int(time.time()),
    )
    trade = summarize(next(t for t in db.list_turtle_trades(limit=5) if t["id"] == trade_id))
    await _notify(
        f"🐢 Define Turtle #{trade_id} entered (paper, {trigger})\n"
        f"SELL {trade['lots']}L {short_strike:.0f} PE @ {short_fill} / BUY {long_strike:.0f} PE @ {long_fill} -- exp {expiry}\n"
        f"Credit {credit} pts (₹{trade['credit']:,.0f}), max loss ₹{trade['maxLoss']:,.0f}, "
        f"P&F RSI {(signal or {}).get('rsi')}"
    )
    return {"status": "entered", "trade": trade}


def _close(trade: dict[str, Any], quotes: dict[tuple[float, str], dict[str, Any]], reason: str) -> dict[str, Any]:
    short_q = quotes.get((float(trade["shortStrike"]), "PE"))
    long_q = quotes.get((float(trade["longStrike"]), "PE"))
    short_exit = _fill(short_q, "BUY") or float(trade["shortEntry"])
    long_exit = _fill(long_q, "SELL") or float(trade["longEntry"])
    qty = int(trade["lots"]) * int(trade["lotSize"])
    realized = ((float(trade["shortEntry"]) - short_exit) + (long_exit - float(trade["longEntry"]))) * qty
    settings = get_settings()
    charges = sum(
        option_order_charges(premium=p, quantity=qty, side=s, exchange_segment=OPTION_SEGMENT, settings=settings)["total"]
        for p, s in ((trade["shortEntry"], "SELL"), (trade["longEntry"], "BUY"), (short_exit, "BUY"), (long_exit, "SELL"))
    )
    db.update_turtle_trade(
        trade["id"], status="CLOSED", short_exit=short_exit, long_exit=long_exit, exit_time=int(time.time()),
        exit_reason=reason, realized_pnl=round(realized, 2), charges=round(charges, 2),
    )
    return summarize(next(t for t in db.list_turtle_trades(limit=20) if t["id"] == trade["id"]))


async def _manage(dhan: DhanService, trade: dict[str, Any], rsi_now: float | None, config: dict[str, Any]) -> None:
    expiry = date.fromisoformat(trade["expiry"])
    _, quotes = await _chain_quotes(dhan, expiry)
    cost = None
    short_ask, long_bid = _fill(quotes.get((float(trade["shortStrike"]), "PE")), "BUY"), _fill(quotes.get((float(trade["longStrike"]), "PE")), "SELL")
    if short_ask is not None and long_bid is not None:
        cost = round(short_ask - long_bid, 2)
    credit = float(trade["creditPoints"])
    decay = round((credit - cost) / credit * 100, 2) if cost is not None and credit else None
    db.update_turtle_trade(trade["id"], last_cost=cost, last_decay=decay, last_rsi=rsi_now, last_update=int(time.time()))

    days_left = (expiry - now_ist().date()).days
    reason = None
    if days_left <= int(config["calendarExitDays"]):
        reason = "calendar"
    elif decay is not None and decay >= float(config["profitDecayPercent"]):
        reason = "profit_target"
    elif rsi_now is not None and rsi_now < float(config["rsiThreshold"]):
        reason = "trend_flip"
    if not reason:
        return
    closed = _close(trade, quotes, reason)
    label = {"calendar": "3-day calendar rule", "profit_target": "75% decay target", "trend_flip": "P&F RSI below 50"}[reason]
    text = (
        f"🐢 Define Turtle #{closed['id']} closed -- {label}\n"
        f"{closed['shortStrike']:.0f}/{closed['longStrike']:.0f} PE exp {closed['expiry']}: "
        f"gross ₹{closed['grossPnl']:,.0f}, charges ₹{closed['charges']:,.0f}, net ₹{closed['netPnl']:,.0f}"
    )
    if reason == "calendar":
        db.create_turtle_alarm(
            kind="calendar", trade_id=closed["id"],
            title=f"Calendar exit -- {days_left} day(s) to expiry",
            message=text + "\nThe spread was closed under the 3-day rule. Decide whether to re-enter on the next signal.",
        )
        text = "⏰ ALARM\n" + text
    await _notify(text)


async def monitor_once() -> None:
    now = datetime.now(IST)
    if not _market_open(now):
        return
    config = get_config()
    dhan = DhanService()
    async with _lock:
        candles = await _candles(dhan)
        if not candles:
            return
        last_time = int(candles[-1]["time"])
        if _last_state.get("lastCandle") == last_time:
            return  # act once per completed minute
        _last_state["lastCandle"] = last_time
        chart = _chart(candles, config)
        rsi_now = chart.rsi(int(config["rsiPeriod"]))

        for trade in db.list_turtle_trades(status="OPEN", limit=5):
            try:
                await _manage(dhan, trade, rsi_now, config)
            except Exception:
                logger.exception("turtle: manage trade #%s failed", trade["id"])

        if not config["enabled"]:
            return
        handled = int(db.get_turtle_setting("lastHandledSignal") or 0)
        fresh = [
            s for s in chart.signals
            if s["kind"] == "turtle_follow_through" and s["time"] > handled
            and s["time"] >= int(time.time()) - SIGNAL_MAX_AGE_SECONDS
        ]
        if not fresh:
            return
        signal = fresh[-1]
        db.set_turtle_setting("lastHandledSignal", str(signal["time"]))
        if signal["rsi"] is None or signal["rsi"] <= float(config["rsiThreshold"]):
            await _notify(f"🐢 Define Turtle: Follow-Through at {signal['price']:.0f} ignored -- P&F RSI {signal['rsi']} is not above {config['rsiThreshold']:.0f}.")
            return
        result = await enter("signal", signal)
        if result["status"] != "entered":
            await _notify(f"🐢 Define Turtle: Follow-Through signal not traded -- {result.get('message')}")


async def close_now(trade_id: int) -> dict[str, Any]:
    async with _lock:
        trade = next((t for t in db.list_turtle_trades(status="OPEN", limit=5) if t["id"] == trade_id), None)
        if not trade:
            return {"status": "blocked", "message": "Trade is not open."}
        _, quotes = await _chain_quotes(DhanService(), date.fromisoformat(trade["expiry"]))
        closed = _close(trade, quotes, "manual")
    await _notify(f"🐢 Define Turtle #{trade_id} closed manually: net ₹{closed['netPnl']:,.0f}")
    return {"status": "closed", "trade": closed}


# ---------------------------------------------------------------- reporting


def summarize(trade: dict[str, Any]) -> dict[str, Any]:
    qty = int(trade["lots"]) * int(trade["lotSize"])
    credit = float(trade["creditPoints"])
    trade["credit"] = round(credit * qty, 2)
    trade["maxLoss"] = round((float(trade["shortStrike"]) - float(trade["longStrike"]) - credit) * qty, 2)
    trade["daysToExpiry"] = (date.fromisoformat(trade["expiry"]) - now_ist().date()).days
    if trade["status"] == "CLOSED":
        trade["grossPnl"] = float(trade["realizedPnl"] or 0)
        trade["charges"] = float(trade["charges"] or 0)
    else:
        cost = trade["lastCost"] if trade["lastCost"] is not None else credit
        trade["grossPnl"] = round((credit - float(cost)) * qty, 2)
        settings = get_settings()
        trade["charges"] = round(sum(
            option_order_charges(premium=p, quantity=qty, side=s, exchange_segment=OPTION_SEGMENT, settings=settings)["total"]
            for p, s in ((trade["shortEntry"], "SELL"), (trade["longEntry"], "BUY"), (trade["shortEntry"], "BUY"), (trade["longEntry"], "SELL"))
        ), 2)
    trade["netPnl"] = round(trade["grossPnl"] - trade["charges"], 2)
    return trade


def list_trades() -> list[dict[str, Any]]:
    return [summarize(t) for t in db.list_turtle_trades()]


async def _notify(text: str) -> None:
    try:
        await TelegramNotifier().send(text)
    except Exception:
        logger.warning("turtle: telegram send failed")


def start_turtle_task() -> asyncio.Task | None:
    if not get_settings().turtle_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_turtle_task(task: asyncio.Task | None) -> None:
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
            logger.exception("turtle: monitor iteration failed")
        await asyncio.sleep(POLL_SECONDS)
