"""Mantra - Theta Gainers -- NIFTY naked short strangle with roll-in adjustments (docs/strategies/mantra.md).

Monthly: the first Monday with the monthly expiry 43-50 days out; weekly:
every Monday on the next-week expiry. 15:00-15:15 IST (holiday Monday ->
Tuesday 09:20). Sells the OTM CE and PE whose LTP is closest to Rs100
(monthly) / Rs40 (weekly). Every minute in market hours:
  target  MTM >= 80% of the initial credit
  stop    MTM <= -initial credit            -> page alarm + Telegram
  time    15:15 on the trading day before expiry
  unstable straddle (imbalance >= 3x near expiry) -> page alarm + Telegram
  roll    at 11/19/33/62% of the credit lost: buy back the winning leg, sell
          the same-side strike priced like the losing leg (reaching the
          losing strike turns it into a straddle -- no more rolls)
MTM = (entry - LTP) of open legs + P&L booked on rolled-out legs.
Paper only: sells at bid, buys at ask.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.db import sqlite as db
from app.services import varaha
from app.services.charges import option_order_charges
from app.services.dhan import DhanService
from app.services.telegram import TelegramNotifier

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
MODES = ("monthly", "weekly")
LOT_SIZE = 65
OPTION_SEGMENT = "NSE_FNO"
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
POLL_SECONDS = 20
_lock = asyncio.Lock()
_expiry_cache: tuple[float, list[date]] | None = None
_last_minute: dict[str, int] = {}

DEFAULTS: dict[str, dict[str, Any]] = {
    "monthly": {
        "enabled": True, "capital": 1_000_000.0, "capitalPerLot": 500_000.0, "targetPremium": 100.0,
        "minDte": 43, "maxDte": 50, "targetPercent": 80.0, "stopPercent": 100.0, "rollLadder": "11,19,33,62",
        "unstableDte": 7, "unstableRatio": 3.0, "maxSpreadPercent": 5.0, "minOiLots": 1000, "gapPercent": 1.5,
    },
    "weekly": {
        "enabled": True, "capital": 1_000_000.0, "capitalPerLot": 500_000.0, "targetPremium": 40.0,
        "minDte": 7, "maxDte": 13, "targetPercent": 80.0, "stopPercent": 100.0, "rollLadder": "11,19,33,62",
        "unstableDte": 2, "unstableRatio": 3.0, "maxSpreadPercent": 5.0, "minOiLots": 1000, "gapPercent": 1.5,
    },
}


# ---------------------------------------------------------------- config


def get_config(mode: str) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for key, default in DEFAULTS[mode].items():
        raw = db.get_mantra_setting(f"{mode}.{key}")
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
    config["mode"] = mode
    config["lots"] = max(int(config["capital"] // config["capitalPerLot"]), 0)
    config["lotSize"] = LOT_SIZE
    config["ladder"] = [float(x) for x in str(config["rollLadder"]).split(",") if x.strip()]
    return config


def update_config(mode: str, updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if key not in DEFAULTS[mode] or value is None:
            continue
        default = DEFAULTS[mode][key]
        if key == "rollLadder":
            [float(x) for x in str(value).split(",")]  # validate
        db.set_mantra_setting(f"{mode}.{key}", ("1" if value else "0") if isinstance(default, bool) else str(value))
    return get_config(mode)


# ---------------------------------------------------------------- pure logic


def fill(quote: dict[str, Any] | None, side: str) -> float | None:
    if not quote:
        return None
    bid, ask = quote.get("bid"), quote.get("ask")
    if bid and ask and ask >= bid > 0:
        return float(ask) if side == "BUY" else float(bid)
    return float(quote["ltp"]) if quote.get("ltp") else None


def pick_strike(quotes: dict[tuple[float, str], dict[str, Any]], spot: float, option_type: str, target: float) -> tuple[float, dict[str, Any]] | None:
    """OTM strike of `option_type` whose LTP is closest to `target`."""
    otm = [
        (k, q) for (k, t), q in quotes.items()
        if t == option_type and q.get("ltp") and ((k > spot) if option_type == "CE" else (k < spot))
    ]
    return min(otm, key=lambda kq: abs(float(kq[1]["ltp"]) - target)) if otm else None


def liquidity_ok(quote: dict[str, Any], config: dict[str, Any]) -> tuple[bool, str]:
    bid, ask, ltp = quote.get("bid"), quote.get("ask"), quote.get("ltp") or 0
    if not (bid and ask):
        return False, "no two-sided quote"
    mid = (bid + ask) / 2
    spread_pct = (ask - bid) / mid * 100 if mid else 999
    oi_lots = (quote.get("oi") or 0) / LOT_SIZE
    if spread_pct > float(config["maxSpreadPercent"]):
        return False, f"spread {ask - bid:.2f} ({spread_pct:.1f}%) > {config['maxSpreadPercent']}%"
    if oi_lots < float(config["minOiLots"]):
        return False, f"OI {oi_lots:,.0f} lots < {config['minOiLots']}"
    return True, f"spread {spread_pct:.1f}%, OI {oi_lots:,.0f} lots"


def matching_strike(
    quotes: dict[tuple[float, str], dict[str, Any]], option_type: str, losing_strike: float, target_price: float, spot: float,
) -> float | None:
    """Same-side strike priced closest to the losing leg, searched outward
    from the losing strike (so it can reach -- never cross -- it)."""
    candidates = [
        k for (k, t), q in quotes.items()
        if t == option_type and q.get("ltp") and ((k >= losing_strike) if option_type == "CE" else (k <= losing_strike))
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda k: abs(float(quotes[(k, option_type)]["ltp"]) - target_price))


def decide(
    *, mtm: float, credit: float, config: dict[str, Any], state: str, rolls: int, days_left: int,
    is_exit_time: bool, open_ltps: list[float],
) -> str | None:
    """Exit reason, 'roll', or None -- in the spec's priority order."""
    if mtm >= float(config["targetPercent"]) / 100 * credit:
        return "target"
    if mtm <= -float(config["stopPercent"]) / 100 * credit:
        return "stop_loss"
    if is_exit_time:
        return "pre_expiry"
    if state == "STRADDLE" and days_left < int(config["unstableDte"]) and len(open_ltps) == 2:
        low = max(min(open_ltps), 0.05)
        if max(open_ltps) / low >= float(config["unstableRatio"]):
            return "unstable_straddle"
    ladder = config["ladder"]
    if state == "STRANGLE" and rolls < len(ladder) and mtm <= -ladder[rolls] / 100 * credit:
        return "roll"
    return None


# ---------------------------------------------------------------- calendar / data


async def _expiries(dhan: DhanService) -> list[date]:
    global _expiry_cache
    if _expiry_cache and time.monotonic() - _expiry_cache[0] < 300:
        return _expiry_cache[1]
    raw = await dhan.expiry_list(get_settings().dhan_nifty_security_id, varaha.INDEX_SEGMENT)
    expiries = sorted(date.fromisoformat(x) for x in raw)
    _expiry_cache = (time.monotonic(), expiries)
    return expiries


def monthly_expiries(expiries: list[date]) -> list[date]:
    by_month: dict[tuple[int, int], date] = {}
    for d in expiries:
        by_month[(d.year, d.month)] = max(by_month.get((d.year, d.month), d), d)
    return sorted(by_month.values())


def series_for(mode: str, expiries: list[date], monday: date, config: dict[str, Any]) -> date | None:
    """The series a Monday entry trades (dte counted from that Monday)."""
    pool = monthly_expiries(expiries) if mode == "monthly" else expiries
    for exp in pool:
        dte = (exp - monday).days
        if int(config["minDte"]) <= dte <= int(config["maxDte"]):
            return exp
    return None


def day_before_expiry(expiry: date) -> date:
    d = expiry - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


async def _chain(dhan: DhanService, expiry: date) -> tuple[float, dict[tuple[float, str], dict[str, Any]]]:
    chain = await dhan.option_chain(get_settings().dhan_nifty_security_id, varaha.INDEX_SEGMENT, expiry.isoformat())
    spot = varaha._number(chain.get("last_price")) or 0.0
    quotes = {}
    for row in varaha._trim_chain(chain, spot):
        for side in ("ce", "pe"):
            if row.get(side):
                quotes[(float(row["strike"]), side.upper())] = row[side]
    return spot, quotes


async def _traded_today(dhan: DhanService, day: date) -> bool:
    try:
        rows = await dhan.intraday_candles(str(get_settings().dhan_nifty_security_id), varaha.INDEX_SEGMENT, "INDEX", "1", day.isoformat(), day.isoformat())
    except Exception:
        return False
    return bool(rows)


def _charge(price: float, qty: int, side: str) -> float:
    return option_order_charges(premium=price, quantity=qty, side=side, exchange_segment=OPTION_SEGMENT, settings=get_settings())["total"]


# ---------------------------------------------------------------- entry


async def plan(mode: str, monday: date | None = None) -> dict[str, Any]:
    """What an entry would sell right now (used by the page and by entry)."""
    config = get_config(mode)
    dhan = DhanService()
    expiries = await _expiries(dhan)
    if monday is None:
        # Next Monday entry that actually has a qualifying series (monthly
        # windows only open about once a month). Today counts until 15:15.
        now = datetime.now(IST)
        first = now.date() + timedelta(days=(7 - now.weekday()) % 7)
        if now.weekday() == 0 and now.time() > dtime(15, 15):
            first += timedelta(days=7)
        monday = next(
            (first + timedelta(weeks=w) for w in range(8) if series_for(mode, expiries, first + timedelta(weeks=w), config)),
            first,
        )
    series = series_for(mode, expiries, monday, config)
    if not series:
        return {"config": config, "monday": monday.isoformat(), "error": f"No {mode} expiry {config['minDte']}-{config['maxDte']} days from {monday:%d %b}."}
    spot, quotes = await _chain(dhan, series)
    legs = {}
    for option_type in ("CE", "PE"):
        picked = pick_strike(quotes, spot, option_type, float(config["targetPremium"]))
        if not picked:
            return {"config": config, "series": series.isoformat(), "error": f"No OTM {option_type} quotes."}
        strike, quote = picked
        ok, why = liquidity_ok(quote, config)
        legs[option_type] = {
            "strike": strike, "ltp": quote.get("ltp"), "bid": quote.get("bid"), "ask": quote.get("ask"),
            "delta": quote.get("delta"), "iv": quote.get("iv"), "oiLots": round((quote.get("oi") or 0) / LOT_SIZE),
            "securityId": quote.get("securityId"), "fill": fill(quote, "SELL"), "liquidityOk": ok, "liquidity": why,
            "distancePercent": round((strike - spot) / spot * 100, 2),
        }
    credit_points = (legs["CE"]["fill"] or 0) + (legs["PE"]["fill"] or 0)
    qty = int(config["lots"]) * LOT_SIZE
    return {
        "config": config, "monday": monday.isoformat(), "series": series.isoformat(), "dte": (series - monday).days,
        "spot": spot, "legs": legs, "creditPoints": round(credit_points, 2), "credit": round(credit_points * qty, 2),
        "target": round(credit_points * qty * float(config["targetPercent"]) / 100, 2),
        "stop": round(credit_points * qty * float(config["stopPercent"]) / 100, 2),
        "rollLevels": [round(credit_points * qty * x / 100, 2) for x in config["ladder"]],
        "exitBy": day_before_expiry(series).isoformat(),
        "liquidityOk": legs["CE"]["liquidityOk"] and legs["PE"]["liquidityOk"],
    }


async def enter(mode: str, trigger: str, monday: date | None = None, *, check_liquidity: bool = True) -> dict[str, Any]:
    config = get_config(mode)
    if config["lots"] < 1:
        return {"status": "blocked", "message": "Capital is below one lot's allocation."}
    p = await plan(mode, monday)
    if "error" in p:
        return {"status": "skipped", "message": p["error"]}
    if any(t["expiry"] == p["series"] for t in db.list_mantra_trades(mode=mode, status="OPEN")):
        return {"status": "blocked", "message": f"A {mode} strangle on {p['series']} is already open."}
    if check_liquidity and not p["liquidityOk"]:
        return {"status": "waiting", "message": f"Liquidity check failed -- CE {p['legs']['CE']['liquidity']}; PE {p['legs']['PE']['liquidity']}"}
    now = int(time.time())
    qty = int(config["lots"]) * LOT_SIZE
    trade_id = db.create_mantra_trade(
        mode=mode, trigger=trigger, status="OPEN", state="STRANGLE", expiry=p["series"], entry_time=now, spot=p["spot"],
        lots=int(config["lots"]), lot_size=LOT_SIZE, credit_points=p["creditPoints"],
        charges=sum(_charge(p["legs"][t]["fill"], qty, "SELL") for t in ("CE", "PE")),
        last_mtm=0.0, last_spot=p["spot"], last_update=now,
    )
    for option_type in ("CE", "PE"):
        leg = p["legs"][option_type]
        db.create_mantra_leg(
            trade_id=trade_id, option_type=option_type, strike=leg["strike"], security_id=leg["securityId"],
            entry=leg["fill"], status="OPEN", opened_at=now, roll_no=0, last_ltp=leg["ltp"], last_bid=leg["bid"], last_ask=leg["ask"],
        )
    text = (
        f"🕉 Mantra - Theta Gainers {mode} #{trade_id} entered (paper, {trigger}) -- exp {p['series']}\n"
        f"SELL {config['lots']}L {p['legs']['CE']['strike']:.0f} CE @ {p['legs']['CE']['fill']} + "
        f"{p['legs']['PE']['strike']:.0f} PE @ {p['legs']['PE']['fill']}\n"
        f"Credit ₹{p['credit']:,.0f} · target ₹{p['target']:,.0f} · stop −₹{p['stop']:,.0f}"
    )
    db.add_mantra_event(trade_id, now, "entry", text.replace("\n", " · "))
    await _notify(text)
    return {"status": "entered", "tradeId": trade_id}


# ---------------------------------------------------------------- monitoring


def _mtm(trade: dict[str, Any], quotes: dict[tuple[float, str], dict[str, Any]]) -> tuple[float, list[dict[str, Any]], list[float]]:
    qty = int(trade["lots"]) * int(trade["lotSize"])
    open_legs = [l for l in trade["legs"] if l["status"] == "OPEN"]
    ltps = []
    unrealized = 0.0
    for leg in open_legs:
        quote = quotes.get((float(leg["strike"]), leg["optionType"])) or {}
        ltp = float(quote.get("ltp") or leg["lastLtp"] or leg["entry"])
        ltps.append(ltp)
        unrealized += (float(leg["entry"]) - ltp) * qty
    return round(unrealized + float(trade["booked"]), 2), open_legs, ltps


async def _manage(dhan: DhanService, trade: dict[str, Any], config: dict[str, Any], now: datetime) -> None:
    expiry = date.fromisoformat(trade["expiry"])
    spot, quotes = await _chain(dhan, expiry)
    stamp = int(now.timestamp())
    # Gap protocol: a > gap% open vs yesterday's close waits until 09:17.
    prev_close = float(db.get_mantra_setting("lastCloseSpot") or 0)
    if now.time() < dtime(9, 17) and prev_close and abs(spot / prev_close - 1) * 100 > float(config["gapPercent"]):
        return
    mtm, open_legs, ltps = _mtm(trade, quotes)
    for leg in open_legs:
        quote = quotes.get((float(leg["strike"]), leg["optionType"])) or {}
        if quote:
            db.update_mantra_leg(leg["id"], last_ltp=quote.get("ltp"), last_bid=quote.get("bid"), last_ask=quote.get("ask"))
    db.update_mantra_trade(trade["id"], last_mtm=mtm, last_spot=spot, last_update=stamp)
    db.record_mantra_mtm(trade["id"], stamp, mtm, spot)

    qty = int(trade["lots"]) * int(trade["lotSize"])
    credit = float(trade["creditPoints"]) * qty
    action = decide(
        mtm=mtm, credit=credit, config=config, state=trade["state"], rolls=int(trade["rolls"]),
        days_left=(expiry - now.date()).days,
        is_exit_time=now.date() >= day_before_expiry(expiry) and now.time() >= dtime(15, 15),
        open_ltps=ltps,
    )
    if action == "roll":
        await _roll(trade, quotes, ltps, open_legs, spot, stamp)
    elif action:
        await _close(trade, quotes, action, stamp)


async def _roll(trade, quotes, ltps, open_legs, spot, stamp) -> None:
    qty = int(trade["lots"]) * int(trade["lotSize"])
    pnl = [float(l["entry"]) - ltp for l, ltp in zip(open_legs, ltps)]
    win_i = 0 if pnl[0] >= pnl[1] else 1
    winning, losing = open_legs[win_i], open_legs[1 - win_i]
    losing_ltp = ltps[1 - win_i]
    new_strike = matching_strike(quotes, winning["optionType"], float(losing["strike"]), losing_ltp, spot)
    if new_strike is None or new_strike == float(winning["strike"]):
        return
    buy = fill(quotes.get((float(winning["strike"]), winning["optionType"])), "BUY") or ltps[win_i]
    new_quote = quotes.get((new_strike, winning["optionType"]))
    sell = fill(new_quote, "SELL")
    if not sell:
        return
    booked = float(trade["booked"]) + (float(winning["entry"]) - buy) * qty
    roll_no = int(trade["rolls"]) + 1
    db.update_mantra_leg(winning["id"], status="CLOSED", exit=buy, closed_at=stamp)
    db.create_mantra_leg(
        trade_id=trade["id"], option_type=winning["optionType"], strike=new_strike, security_id=(new_quote or {}).get("securityId"),
        entry=sell, status="OPEN", opened_at=stamp, roll_no=roll_no, last_ltp=(new_quote or {}).get("ltp"),
        last_bid=(new_quote or {}).get("bid"), last_ask=(new_quote or {}).get("ask"),
    )
    state = "STRADDLE" if new_strike == float(losing["strike"]) else "STRANGLE"
    db.update_mantra_trade(
        trade["id"], booked=round(booked, 2), rolls=roll_no, state=state,
        charges=float(trade["charges"]) + _charge(buy, qty, "BUY") + _charge(sell, qty, "SELL"),
    )
    text = (
        f"Roll {roll_no}: bought back {winning['strike']:.0f} {winning['optionType']} @ {buy}, sold {new_strike:.0f} "
        f"{winning['optionType']} @ {sell} (losing {losing['strike']:.0f} {losing['optionType']} at {losing_ltp})"
        + (" -- now a STRADDLE" if state == "STRADDLE" else "")
    )
    db.add_mantra_event(trade["id"], stamp, "roll", text)
    await _notify(f"🕉 Mantra - Theta Gainers {trade['mode']} #{trade['id']} {text}")


async def _close(trade, quotes, reason: str, stamp: int) -> None:
    qty = int(trade["lots"]) * int(trade["lotSize"])
    gross = float(trade["booked"])
    charges = float(trade["charges"])
    for leg in [l for l in trade["legs"] if l["status"] == "OPEN"]:
        quote = quotes.get((float(leg["strike"]), leg["optionType"]))
        buy = fill(quote, "BUY") or float(leg["lastLtp"] or leg["entry"])
        gross += (float(leg["entry"]) - buy) * qty
        charges += _charge(buy, qty, "BUY")
        db.update_mantra_leg(leg["id"], status="CLOSED", exit=buy, closed_at=stamp)
    db.update_mantra_trade(trade["id"], status="CLOSED", exit_time=stamp, exit_reason=reason, gross=round(gross, 2), charges=round(charges, 2))
    label = {"target": "80% target", "stop_loss": "GLOBAL STOP LOSS", "pre_expiry": "day-before-expiry exit",
             "unstable_straddle": "unstable straddle", "manual": "closed manually"}.get(reason, reason)
    text = (
        f"🕉 Mantra - Theta Gainers {trade['mode']} #{trade['id']} closed -- {label}\n"
        f"exp {trade['expiry']}, {trade['rolls']} roll(s): gross ₹{gross:,.0f}, charges ₹{charges:,.0f}, net ₹{gross - charges:,.0f}"
    )
    db.add_mantra_event(trade["id"], stamp, "exit", text.replace("\n", " · "))
    if reason in ("stop_loss", "unstable_straddle"):
        db.create_mantra_alarm(kind=reason, trade_id=trade["id"], title=f"Mantra - Theta Gainers {trade['mode']} -- {label}", message=text)
        text = "⏰ ALARM\n" + text
    await _notify(text)


async def monitor_once() -> None:
    now = datetime.now(IST)
    if now.weekday() >= 5 or not (MARKET_OPEN <= now.time() <= MARKET_CLOSE):
        return
    minute = int(now.timestamp()) // 60
    if _last_minute.get("m") == minute:
        return
    _last_minute["m"] = minute
    dhan = DhanService()
    async with _lock:
        for trade in db.list_mantra_trades(status="OPEN", limit=10):
            try:
                await _manage(dhan, trade, get_config(trade["mode"]), now)
            except Exception:
                logger.exception("mantra: manage trade #%s failed", trade["id"])
        if now.time() >= dtime(15, 29):
            try:
                spot, _ = await _chain(dhan, (await _expiries(dhan))[0])
                db.set_mantra_setting("lastCloseSpot", str(spot))
            except Exception:
                pass

        for mode in MODES:
            config = get_config(mode)
            if config["enabled"]:
                await _scheduled_entry(dhan, mode, now)


async def _scheduled_entry(dhan: DhanService, mode: str, now: datetime) -> None:
    """Monday 15:00-15:15 (retrying each minute while the liquidity check
    fails). If Monday was a holiday, or liquidity never passed, the doc's
    fallback runs on Tuesday 09:20-09:30 -- the last minute there enters
    without the liquidity check."""
    if now.weekday() == 0 and dtime(15, 0) <= now.time() <= dtime(15, 15):
        monday, last_try, fallback = now.date(), False, False
    elif now.weekday() == 1 and dtime(9, 20) <= now.time() <= dtime(9, 30):
        monday = now.date() - timedelta(days=1)
        key = f"entry.{mode}.{monday.isoformat()}"
        if db.get_mantra_setting(key) != "deferred" and await _traded_today(dhan, monday):
            return
        last_try, fallback = now.time() >= dtime(9, 29), True
    else:
        return
    key = f"entry.{mode}.{monday.isoformat()}"
    status = db.get_mantra_setting(key)
    if status and status != "deferred":
        return
    if status == "deferred" and not fallback:
        return
    result = await enter(mode, "scheduled" if not fallback else "scheduled-fallback", monday, check_liquidity=not last_try)
    if result["status"] == "waiting":
        if not fallback and now.time() >= dtime(15, 14):
            db.set_mantra_setting(key, "deferred")
            await _notify(f"🕉 Mantra - Theta Gainers {mode}: entry deferred to Tuesday 09:20 -- {result['message']}")
        return
    db.set_mantra_setting(key, result["status"])
    if result["status"] != "entered":
        await _notify(f"🕉 Mantra - Theta Gainers {mode}: no entry for {monday:%d %b} -- {result.get('message')}")


async def close_now(trade_id: int) -> dict[str, Any]:
    async with _lock:
        trade = next((t for t in db.list_mantra_trades(status="OPEN", limit=10) if t["id"] == trade_id), None)
        if not trade:
            return {"status": "blocked", "message": "Trade is not open."}
        _, quotes = await _chain(DhanService(), date.fromisoformat(trade["expiry"]))
        await _close(trade, quotes, "manual", int(time.time()))
    return {"status": "closed"}


# ---------------------------------------------------------------- reporting


def summarize(trade: dict[str, Any]) -> dict[str, Any]:
    qty = int(trade["lots"]) * int(trade["lotSize"])
    credit = float(trade["creditPoints"]) * qty
    config = get_config(trade["mode"])
    trade["credit"] = round(credit, 2)
    trade["target"] = round(credit * float(config["targetPercent"]) / 100, 2)
    trade["stop"] = round(credit * float(config["stopPercent"]) / 100, 2)
    ladder = config["ladder"]
    trade["nextRollAt"] = round(-credit * ladder[int(trade["rolls"])] / 100, 2) if trade["state"] == "STRANGLE" and int(trade["rolls"]) < len(ladder) else None
    trade["grossPnl"] = float(trade["gross"]) if trade["status"] == "CLOSED" else float(trade["lastMtm"] or 0)
    trade["netPnl"] = round(trade["grossPnl"] - float(trade["charges"] or 0), 2)
    trade["daysToExpiry"] = (date.fromisoformat(trade["expiry"]) - datetime.now(IST).date()).days
    trade["exitBy"] = day_before_expiry(date.fromisoformat(trade["expiry"])).isoformat()
    return trade


def list_trades() -> list[dict[str, Any]]:
    return [summarize(t) for t in db.list_mantra_trades()]


def trade_detail(trade_id: int) -> dict[str, Any] | None:
    trade = next((t for t in db.list_mantra_trades() if t["id"] == trade_id), None)
    if not trade:
        return None
    trade = summarize(trade)
    trade["mtmHistory"] = db.list_mantra_mtm(trade_id)
    return trade


async def _notify(text: str) -> None:
    try:
        await TelegramNotifier().send(text)
    except Exception:
        logger.warning("mantra: telegram send failed")


def start_mantra_task() -> asyncio.Task | None:
    if not get_settings().mantra_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_mantra_task(task: asyncio.Task | None) -> None:
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
            logger.exception("mantra: monitor iteration failed")
        await asyncio.sleep(POLL_SECONDS)
