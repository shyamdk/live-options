"""Define Turtle -- NIFTY P&F RSI + Turtle Follow-Through, paper trading.

Spec: docs/strategies/define-turtle.md. Every completed 1-minute NIFTY candle the P&F chart
(0.03% log boxes, 3-box reversal) is rebuilt from ~30 trading days of 1-min
closes plus today's. A Turtle Follow-Through Bullish printed on the latest
close with P&F RSI(14) > 50 opens a next-week put credit spread (sell ATM put
rounded to 100, buy 300 lower) if none is open. Exits: 75% premium decay,
RSI < 50 on a minute close, or <= 3 calendar days to expiry -- the calendar
exit raises an unmissable alarm on the page plus Telegram.

Live orders (Nov 2026): with TURTLE_LIVE_ORDER_ENABLED + LIVE_ORDER_ENABLED on the
server and the page's mode set to live, new spreads place real Dhan MARKET orders
(MARGIN product -- held overnight). Entry buys the hedge put first, then sells the
short put; if the short sell fails the hedge is sold straight back. Exit buys the
short back first, then sells the hedge. A leg that fails on exit leaves the trade
OPEN with needs_attention set and is retried every minute; it is marked CLOSED
only when both legs are out. Each trade keeps its own mode, so a paper spread
never sends an order.
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
from app.services.orders import DhanOrderService
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
    "mode": "paper",
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
        elif isinstance(default, str):
            config[key] = raw
        elif isinstance(default, int):
            config[key] = int(float(raw))
        else:
            config[key] = float(raw)
    config["lots"] = max(int(config["capital"] // config["capitalPerLot"]), 0)
    config["lotSize"] = LOT_SIZE
    config["liveOrdersAllowed"] = _live_allowed()
    return config


def _live_allowed() -> bool:
    settings = get_settings()
    return bool(settings.turtle_live_order_enabled and settings.live_order_enabled)


def _mode(config: dict[str, Any]) -> str:
    return "live" if config["mode"] == "live" and config["liveOrdersAllowed"] else "paper"


def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if key not in DEFAULTS or value is None:
            continue
        default = DEFAULTS[key]
        if key == "mode":
            if value not in ("paper", "live"):
                raise ValueError("mode must be paper or live")
            if value == "live" and not _live_allowed():
                raise ValueError("Live orders are switched off on the server (TURTLE_LIVE_ORDER_ENABLED / LIVE_ORDER_ENABLED).")
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


# ---------------------------------------------------------------- live orders


async def _order(side: str, security_id: str | None, qty: int, correlation: str) -> dict[str, Any]:
    """One MARKET order (up to 3 attempts) and its traded price. ok=False if not sent."""
    if not security_id:
        return {"ok": False, "orderId": None, "price": None, "message": "no security id"}
    settings = get_settings()
    orders = DhanOrderService(settings)
    last: dict[str, Any] = {}
    for attempt in range(3):
        last = await orders.place_market_order(
            transaction_type=side, exchange_segment=OPTION_SEGMENT, security_id=security_id, quantity=qty,
            correlation_id=f"{correlation}{attempt}", product_type=settings.turtle_live_order_product_type,
        )
        if last.get("status") == "sent":
            break
        await asyncio.sleep(0.6)
    if last.get("status") != "sent":
        return {"ok": False, "orderId": None, "price": None, "message": f"{last.get('status')}: {last.get('message')}"}
    order = last.get("order") or {}
    order_id = str(order.get("orderId") or (order.get("data") or {}).get("orderId") or "") or None
    price, status = await _traded_price(orders, order_id)
    if status in ("REJECTED", "CANCELLED", "EXPIRED"):
        return {"ok": False, "orderId": order_id, "price": None, "message": f"order {order_id} {status}"}
    return {"ok": True, "orderId": order_id, "price": price, "message": "sent" if price else "sent (fill price not confirmed -- quote used)"}


async def _traded_price(orders: DhanOrderService, order_id: str | None) -> tuple[float | None, str | None]:
    if not order_id:
        return None, None
    status = None
    for _ in range(8):
        await asyncio.sleep(1)
        try:
            order = await orders.get_order(order_id)
        except Exception:
            order = None
        if not order:
            continue
        status = str(order.get("orderStatus") or "").upper()
        price = varaha._number(order.get("averageTradedPrice")) or varaha._number(order.get("tradedPrice"))
        if status == "TRADED" and price:
            return float(price), status
        if status in ("REJECTED", "CANCELLED", "EXPIRED"):
            return None, status
    return None, status


def _attention(trade_id: int, text: str) -> None:
    db.update_turtle_trade(trade_id, needs_attention=text)
    db.create_turtle_alarm(kind="live_error", trade_id=trade_id, title=f"LIVE order problem on #{trade_id}", message=text)


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
    mode = _mode(config)
    qty = int(config["lots"]) * LOT_SIZE
    order_ids: dict[str, str | None] = {"short_order_id": None, "long_order_id": None}
    if mode == "live":
        tag = f"DT{int(time.time()) % 10000000}"
        hedge = await _order("BUY", (long_q or {}).get("securityId"), qty, f"{tag}LE")
        if not hedge["ok"]:
            text = f"LIVE entry skipped: hedge BUY {long_strike:.0f} PE failed ({hedge['message']}). No position taken."
            await _notify(f"🚨 Define Turtle {text}")
            return {"status": "failed", "message": text}
        short = await _order("SELL", (short_q or {}).get("securityId"), qty, f"{tag}SE")
        if not short["ok"]:
            undo = await _order("SELL", (long_q or {}).get("securityId"), qty, f"{tag}LU")
            text = (f"LIVE entry failed: short SELL {short_strike:.0f} PE failed ({short['message']}); "
                    f"hedge sold back: {undo['message']}. CHECK DHAN POSITIONS.")
            db.create_turtle_alarm(kind="live_error", trade_id=None, title="LIVE entry failed", message=text)
            await _notify(f"🚨 Define Turtle {text}")
            return {"status": "failed", "message": text}
        long_fill, short_fill = hedge["price"] or long_fill, short["price"] or short_fill
        credit = round(short_fill - long_fill, 2)
        order_ids = {"short_order_id": short["orderId"], "long_order_id": hedge["orderId"]}
    trade_id = db.create_turtle_trade(
        mode=mode, **order_ids,
        status="OPEN", trigger=trigger, signal_time=(signal or {}).get("time"), signal_rsi=(signal or {}).get("rsi"),
        entry_time=int(time.time()), expiry=expiry.isoformat(), spot=spot, lots=int(config["lots"]), lot_size=LOT_SIZE,
        short_strike=short_strike, long_strike=long_strike,
        short_security_id=(short_q or {}).get("securityId"), long_security_id=(long_q or {}).get("securityId"),
        short_entry=short_fill, long_entry=long_fill, credit_points=credit, last_cost=credit, last_decay=0.0,
        last_rsi=(signal or {}).get("rsi"), last_update=int(time.time()),
    )
    trade = summarize(next(t for t in db.list_turtle_trades(limit=5) if t["id"] == trade_id))
    await _notify(
        f"🐢 Define Turtle #{trade_id} entered ({'LIVE ORDERS' if mode == 'live' else 'paper'}, {trigger})\n"
        f"SELL {trade['lots']}L {short_strike:.0f} PE @ {short_fill} / BUY {long_strike:.0f} PE @ {long_fill} -- exp {expiry}\n"
        f"Credit {credit} pts (₹{trade['credit']:,.0f}), max loss ₹{trade['maxLoss']:,.0f}, "
        f"P&F RSI {(signal or {}).get('rsi')}"
    )
    return {"status": "entered", "trade": trade}


async def _close(trade: dict[str, Any], quotes: dict[tuple[float, str], dict[str, Any]], reason: str) -> dict[str, Any] | None:
    """Close both legs; returns the closed trade, or None if a live leg failed
    (the trade stays OPEN with needs_attention and is retried next minute)."""
    short_q = quotes.get((float(trade["shortStrike"]), "PE"))
    long_q = quotes.get((float(trade["longStrike"]), "PE"))
    short_exit = trade.get("shortExit")
    long_exit = trade.get("longExit")
    qty = int(trade["lots"]) * int(trade["lotSize"])
    if trade.get("mode") == "live":
        tag = f"DT{trade['id']}X{int(time.time()) % 100000}"
        if short_exit is None:  # buy the short back first -- never leave it naked
            res = await _order("BUY", trade.get("shortSecurityId"), qty, f"{tag}S")
            if not res["ok"]:
                text = f"LIVE exit ({reason}): BUY back {trade['shortStrike']:.0f} PE failed ({res['message']}). Retrying every minute -- CHECK DHAN."
                _attention(trade["id"], text)
                await _notify(f"🚨 Define Turtle #{trade['id']} {text}")
                return None
            short_exit = res["price"] or _fill(short_q, "BUY") or float(trade.get("lastCost") or 0) + (_fill(long_q, "SELL") or 0)
            db.update_turtle_trade(trade["id"], short_exit=short_exit, short_exit_order_id=res["orderId"], exit_reason=reason)
        if long_exit is None:
            res = await _order("SELL", trade.get("longSecurityId"), qty, f"{tag}L")
            if not res["ok"]:
                text = f"LIVE exit ({reason}): short is closed, but SELL of the {trade['longStrike']:.0f} PE hedge failed ({res['message']}). Retrying -- CHECK DHAN."
                _attention(trade["id"], text)
                await _notify(f"⚠️ Define Turtle #{trade['id']} {text}")
                return None
            long_exit = res["price"] or _fill(long_q, "SELL") or 0.0
            db.update_turtle_trade(trade["id"], long_exit=long_exit, long_exit_order_id=res["orderId"])
    else:
        short_exit = _fill(short_q, "BUY") or float(trade["shortEntry"])
        long_exit = _fill(long_q, "SELL") or float(trade["longEntry"])
    realized = ((float(trade["shortEntry"]) - short_exit) + (long_exit - float(trade["longEntry"]))) * qty
    settings = get_settings()
    charges = sum(
        option_order_charges(premium=p, quantity=qty, side=s, exchange_segment=OPTION_SEGMENT, settings=settings)["total"]
        for p, s in ((trade["shortEntry"], "SELL"), (trade["longEntry"], "BUY"), (short_exit, "BUY"), (long_exit, "SELL"))
    )
    db.update_turtle_trade(
        trade["id"], status="CLOSED", short_exit=short_exit, long_exit=long_exit, exit_time=int(time.time()),
        exit_reason=trade.get("exitReason") or reason, realized_pnl=round(realized, 2), charges=round(charges, 2),
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
    if trade.get("shortExit") is not None:  # live exit half done -- finish it
        reason = trade.get("exitReason") or "retry"
    elif days_left <= int(config["calendarExitDays"]):
        reason = "calendar"
    elif decay is not None and decay >= float(config["profitDecayPercent"]):
        reason = "profit_target"
    elif rsi_now is not None and rsi_now < float(config["rsiThreshold"]):
        reason = "trend_flip"
    if not reason:
        return
    closed = await _close(trade, quotes, reason)
    if closed is None:
        return
    label = {"calendar": "3-day calendar rule", "profit_target": "75% decay target", "trend_flip": "P&F RSI below 50"}.get(reason, reason)
    text = (
        f"🐢 Define Turtle #{closed['id']} closed{' (LIVE)' if closed.get('mode') == 'live' else ''} -- {label}\n"
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
        closed = await _close(trade, quotes, "manual")
    if closed is None:
        return {"status": "failed", "message": "A live exit order failed -- see the alarm; it will be retried every minute."}
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
