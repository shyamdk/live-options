"""Define Turtle - Filtered -- the Define Turtle rules with three filters, paper only.

Back-test (data/history/backtests/turtle_grid.py + turtle_grid2.py, Jan 2025 - Oct 2026, 6 lots):
the original rules lose (-Rs1.18L, 2026 -Rs2.48L); of 25 variants the only one positive in both
years was this combination -- +Rs48k over 32 trades (2025 +35k / 2026 +12k), max drawdown -Rs33k.
It was picked after seeing all 25, so treat it as a hypothesis this paper book is testing.

Entry (on a Turtle Follow-Through, as Define Turtle):
  TREND   yesterday's NIFTY close above its 50-day SMA (bull) / below it (bear)
  RSI     P&F RSI(14) > 60 (bull) / < 40 (bear)
  STRIKE  bull: sell PE 200 pts below ATM (rounded to 100), buy 300 lower;
          bear (on by default, can be switched off): sell CE 200 above ATM, buy 300 higher
Exits as Define Turtle: 75% premium decay, P&F RSI back through 50 (trend flip), or <= 3
calendar days to expiry. One open spread per side. Uses the bearish signal added to
turtle_engine (turtle_follow_through_bearish).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.sessions import weekday_open
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

PREFIX = "turtle_f"
KINDS = {"bull": "turtle_follow_through", "bear": "turtle_follow_through_bearish"}
OPT = {"bull": "PE", "bear": "CE"}
_daily: dict[str, Any] = {"date": None, "closes": []}

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "entryRsi": 60.0,
    "trendSmaDays": 50,
    "shortOtmPoints": 200.0,
    "bearish": True,
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
        raw = db.get_turtle_setting(key, PREFIX)
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
        db.set_turtle_setting(key, ("1" if value else "0") if isinstance(default, bool) else str(value), PREFIX)
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
    """The expiry AFTER the nearest one (docs/strategies/define-turtle.md decision 4)."""
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


async def trend(dhan: DhanService) -> dict[str, Any]:
    """Yesterday's NIFTY close vs its N-day SMA (daily closes, refreshed once a day)."""
    config = get_config()
    n = int(config["trendSmaDays"])
    today = now_ist().date()
    if _daily["date"] != today.isoformat():
        start = (today - timedelta(days=int(n * 1.6) + 20)).isoformat()
        rows = await dhan.historical_daily_candles(str(get_settings().dhan_nifty_security_id), INDEX_SEGMENT, "INDEX", start, today.isoformat())
        closes = [float(r["close"]) for r in sorted(rows, key=lambda r: r["time"])
                  if datetime.fromtimestamp(int(r["time"]), IST).date() < today]
        _daily.update(date=today.isoformat(), closes=closes)
    closes = _daily["closes"]
    if len(closes) < n + 1:
        return {"sma": None, "close": closes[-1] if closes else None, "bull": False, "bear": False}
    sma = sum(closes[-n - 1:-1]) / n  # SMA of the n closes before yesterday's, as in the back-test
    last = closes[-1]
    return {"sma": round(sma, 2), "close": last, "bull": last > sma, "bear": last < sma, "days": n}


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
        follow = [s for s in chart.signals if s["kind"] in (KINDS["bull"], KINDS["bear"])]
        payload["lastFollowThrough"] = follow[-1] if follow else None
        payload["trendFilter"] = await trend(dhan)
        expiries = await _expiries(dhan)
        nxt = next_week_expiry(expiries, now_ist().date())
        payload["nextWeekExpiry"] = nxt.isoformat() if nxt else None
    except Exception as exc:
        payload["error"] = f"Dhan data unavailable: {exc}"
    payload["openTrades"] = [summarize(t) for t in db.list_turtle_trades(status="OPEN", limit=5, prefix=PREFIX)]
    payload["alarms"] = db.list_turtle_alarms(unacknowledged_only=True, prefix=PREFIX)
    payload["marketOpen"] = _market_open(datetime.now(IST))
    return payload


# ---------------------------------------------------------------- trading


def _market_open(now: datetime) -> bool:
    return weekday_open(now) and MARKET_OPEN <= now.time() <= MARKET_CLOSE


async def enter(trigger: str, signal: dict[str, Any] | None = None, side: str = "bull") -> dict[str, Any]:
    config = get_config()
    opt = OPT[side]
    if config["lots"] < 1:
        return {"status": "blocked", "message": "Capital is below one lot's allocation."}
    if any(t.get("side", "bull") == side for t in db.list_turtle_trades(status="OPEN", limit=5, prefix=PREFIX)):
        return {"status": "blocked", "message": f"A {side} spread is already open -- one per side."}
    dhan = DhanService()
    today = now_ist().date()
    expiry = next_week_expiry(await _expiries(dhan), today)
    if not expiry:
        return {"status": "skipped", "message": "No next-week expiry listed."}
    if (expiry - today).days <= int(config["calendarExitDays"]):
        return {"status": "skipped", "message": f"Next-week expiry {expiry} is within the {config['calendarExitDays']}-day calendar window."}
    spot, quotes = await _chain_quotes(dhan, expiry)
    rounding = float(config["strikeRounding"])
    atm = round(spot / rounding) * rounding
    otm, width = float(config["shortOtmPoints"]), float(config["spreadWidth"])
    short_strike = atm - otm if side == "bull" else atm + otm
    long_strike = short_strike - width if side == "bull" else short_strike + width
    short_q, long_q = quotes.get((short_strike, opt)), quotes.get((long_strike, opt))
    short_fill, long_fill = _fill(short_q, "SELL"), _fill(long_q, "BUY")
    if not short_fill or not long_fill:
        return {"status": "skipped", "message": f"No quote for {short_strike:.0f} / {long_strike:.0f} {opt}."}
    credit = round(short_fill - long_fill, 2)
    if credit <= 0:
        return {"status": "skipped", "message": "Spread would not be a credit at current quotes."}
    trade_id = db.create_turtle_trade(
        PREFIX,
        status="OPEN", trigger=trigger, signal_time=(signal or {}).get("time"), signal_rsi=(signal or {}).get("rsi"),
        entry_time=int(time.time()), expiry=expiry.isoformat(), spot=spot, lots=int(config["lots"]), lot_size=LOT_SIZE,
        short_strike=short_strike, long_strike=long_strike,
        short_security_id=(short_q or {}).get("securityId"), long_security_id=(long_q or {}).get("securityId"),
        short_entry=short_fill, long_entry=long_fill, credit_points=credit, last_cost=credit, last_decay=0.0,
        last_rsi=(signal or {}).get("rsi"), last_update=int(time.time()), side=side,
    )
    trade = summarize(next(t for t in db.list_turtle_trades(limit=5, prefix=PREFIX) if t["id"] == trade_id))
    await _notify(
        f"🐢 Define Turtle Filtered #{trade_id} entered ({side}, paper, {trigger})\n"
        f"SELL {trade['lots']}L {short_strike:.0f} {opt} @ {short_fill} / BUY {long_strike:.0f} {opt} @ {long_fill} -- exp {expiry}\n"
        f"Credit {credit} pts (₹{trade['credit']:,.0f}), max loss ₹{trade['maxLoss']:,.0f}, "
        f"P&F RSI {(signal or {}).get('rsi')}"
    )
    return {"status": "entered", "trade": trade}


def _close(trade: dict[str, Any], quotes: dict[tuple[float, str], dict[str, Any]], reason: str) -> dict[str, Any]:
    opt = OPT[trade.get("side") or "bull"]
    short_q = quotes.get((float(trade["shortStrike"]), opt))
    long_q = quotes.get((float(trade["longStrike"]), opt))
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
        trade["id"], PREFIX, status="CLOSED", short_exit=short_exit, long_exit=long_exit, exit_time=int(time.time()),
        exit_reason=reason, realized_pnl=round(realized, 2), charges=round(charges, 2),
    )
    return summarize(next(t for t in db.list_turtle_trades(limit=20, prefix=PREFIX) if t["id"] == trade["id"]))


async def _manage(dhan: DhanService, trade: dict[str, Any], rsi_now: float | None, config: dict[str, Any]) -> None:
    expiry = date.fromisoformat(trade["expiry"])
    _, quotes = await _chain_quotes(dhan, expiry)
    cost = None
    side = trade.get("side") or "bull"
    opt = OPT[side]
    short_ask, long_bid = _fill(quotes.get((float(trade["shortStrike"]), opt)), "BUY"), _fill(quotes.get((float(trade["longStrike"]), opt)), "SELL")
    if short_ask is not None and long_bid is not None:
        cost = round(short_ask - long_bid, 2)
    credit = float(trade["creditPoints"])
    decay = round((credit - cost) / credit * 100, 2) if cost is not None and credit else None
    db.update_turtle_trade(trade["id"], PREFIX, last_cost=cost, last_decay=decay, last_rsi=rsi_now, last_update=int(time.time()))

    days_left = (expiry - now_ist().date()).days
    reason = None
    if days_left <= int(config["calendarExitDays"]):
        reason = "calendar"
    elif decay is not None and decay >= float(config["profitDecayPercent"]):
        reason = "profit_target"
    elif rsi_now is not None and (rsi_now < float(config["rsiThreshold"]) if side == "bull" else rsi_now > 100 - float(config["rsiThreshold"])):
        reason = "trend_flip"
    if not reason:
        return
    closed = _close(trade, quotes, reason)
    label = {"calendar": "3-day calendar rule", "profit_target": "75% decay target",
             "trend_flip": "P&F RSI back below 50" if side == "bull" else "P&F RSI back above 50"}[reason]
    text = (
        f"🐢 Define Turtle Filtered #{closed['id']} closed -- {label}\n"
        f"{closed['shortStrike']:.0f}/{closed['longStrike']:.0f} {opt} exp {closed['expiry']}: "
        f"gross ₹{closed['grossPnl']:,.0f}, charges ₹{closed['charges']:,.0f}, net ₹{closed['netPnl']:,.0f}"
    )
    if reason == "calendar":
        db.create_turtle_alarm(
            prefix=PREFIX, kind="calendar", trade_id=closed["id"],
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

        for trade in db.list_turtle_trades(status="OPEN", limit=5, prefix=PREFIX):
            try:
                await _manage(dhan, trade, rsi_now, config)
            except Exception:
                logger.exception("turtle_filtered: manage trade #%s failed", trade["id"])

        if not config["enabled"]:
            return
        handled = int(db.get_turtle_setting("lastHandledSignal", PREFIX) or 0)
        sides = ["bull"] + (["bear"] if config["bearish"] else [])
        fresh = [
            s for s in chart.signals
            if s["kind"] in [KINDS[x] for x in sides] and s["time"] > handled
            and s["time"] >= int(time.time()) - SIGNAL_MAX_AGE_SECONDS
        ]
        if not fresh:
            return
        signal = fresh[-1]
        db.set_turtle_setting("lastHandledSignal", str(signal["time"]), PREFIX)
        side = "bull" if signal["kind"] == KINDS["bull"] else "bear"
        entry_rsi = float(config["entryRsi"])
        rsi_ok = signal["rsi"] is not None and (signal["rsi"] > entry_rsi if side == "bull" else signal["rsi"] < 100 - entry_rsi)
        if not rsi_ok:
            await _notify(f"🐢 Define Turtle Filtered: {side} Follow-Through at {signal['price']:.0f} ignored -- P&F RSI {signal['rsi']} "
                          f"is not {'above' if side == 'bull' else 'below'} {entry_rsi if side == 'bull' else 100 - entry_rsi:.0f}.")
            return
        tr = await trend(dhan)
        if not tr.get(side):
            await _notify(f"🐢 Define Turtle Filtered: {side} Follow-Through at {signal['price']:.0f} ignored -- trend filter: yesterday's close "
                          f"{tr.get('close')} vs {tr.get('days')}-day SMA {tr.get('sma')}.")
            return
        result = await enter("signal", signal, side)
        if result["status"] != "entered":
            await _notify(f"🐢 Define Turtle Filtered: {side} Follow-Through not traded -- {result.get('message')}")


async def close_now(trade_id: int) -> dict[str, Any]:
    async with _lock:
        trade = next((t for t in db.list_turtle_trades(status="OPEN", limit=5, prefix=PREFIX) if t["id"] == trade_id), None)
        if not trade:
            return {"status": "blocked", "message": "Trade is not open."}
        _, quotes = await _chain_quotes(DhanService(), date.fromisoformat(trade["expiry"]))
        closed = _close(trade, quotes, "manual")
    await _notify(f"🐢 Define Turtle Filtered #{trade_id} closed manually: net ₹{closed['netPnl']:,.0f}")
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
    return [summarize(t) for t in db.list_turtle_trades(prefix=PREFIX)]


async def _notify(text: str) -> None:
    try:
        await TelegramNotifier().send(text)
    except Exception:
        logger.warning("turtle_filtered: telegram send failed")


def start_turtle_filtered_task() -> asyncio.Task | None:
    if not get_settings().turtle_monitor_enabled:  # shares Define Turtle's switch
        return None
    return asyncio.create_task(_loop())


async def stop_turtle_filtered_task(task: asyncio.Task | None) -> None:
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
            logger.exception("turtle_filtered: monitor iteration failed")
        await asyncio.sleep(POLL_SECONDS)


# share Define Turtle's 1-min candle and expiry caches (same NIFTY data; halves the Dhan calls)
from app.services import turtle as _base  # noqa: E402

_candles = _base._candles
_expiries = _base._expiries
