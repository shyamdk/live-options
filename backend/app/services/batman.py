"""Batman -- NIFTY 1:3:2 double ratio spread, paper trading.

Monthly follows batman-option-strategy-guide.pdf:
  - entry on the LAST Friday before the current month's monthly expiry, at
    15:16 IST, on the NEXT month's series (the backtest dates only work that
    way: enter 24 Jan, exit 3 Feb = the Feb series);
  - 1:3:2 call + put ratio spreads, 3/9/6 base, 50-strike shift, Filter 1
    (credit <= 6% of capital, shift buy strikes outward 100 pts at a time,
    gaps kept), Filter 2 (extra outer calls until T+0 at +-500 balances);
  - zero adjustments; exit ALL legs at +2% MTM, -2.5% MTM, or after the max
    hold (15 calendar days).
Weekly is a research-based variant (paper): same structure with distances in
expected-move units, entry Friday 15:16 on the expiry ~11 days out,
+1.5% / -1.5%, hard exit the Friday before expiry week (15:15).

Percentages are of the configured capital (default Rs 10L). Fills are
simulated from the live Dhan chain: buys at ask, sells at bid.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.timeutil import now_ist
from app.db import sqlite as db
from app.services import batman_engine as engine
from app.services import varaha
from app.services import varaha_engine as ve
from app.services.charges import option_order_charges
from app.services.dhan import DhanService
from app.services.telegram import TelegramNotifier

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
MODES = ("monthly", "weekly")
# Weekly runs as a second paper book (switched on 15 Oct 2026 after the
# Apr-Oct backtest; defaults below are the backtest's most balanced setting).
ACTIVE_MODES = ("monthly", "weekly")
LOT_SIZE = 65
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
ENTRY_WINDOW_END = dtime(15, 25)
TIME_EXIT_AT = dtime(15, 15)
POLL_SECONDS = 60
OPTION_SEGMENT = "NSE_FNO"
_lock = asyncio.Lock()

DEFAULTS: dict[str, dict[str, Any]] = {
    "monthly": {
        "enabled": True, "capital": 1_000_000.0, "baseLots": 3, "entryTime": "15:16",
        "buyOffset": 400.0, "sellGap": 200.0, "hedgeGap": 800.0,
        "creditCapPercent": 6.0, "shiftStep": 100.0, "maxShifts": 6,
        "balanceMove": 500.0, "overHedge": True, "maxExtraCallLots": 9,
        "targetPercent": 2.0, "stopPercent": 2.5, "maxHoldDays": 15,
    },
    "weekly": {
        "enabled": True, "capital": 1_000_000.0, "baseLots": 3, "entryTime": "15:16",
        "buyEm": 0.6, "sellEm": 0.25, "hedgeEm": 1.2,
        "creditCapPercent": 4.0, "shiftStep": 50.0, "maxShifts": 6,
        "balanceEm": 0.67, "overHedge": True, "maxExtraCallLots": 9,
        # backtest Apr-Oct 2026, 23 Friday entries: +Rs44.9k, 70% wins,
        # worst trade -Rs28k; exit 3 days before expiry = the Friday before
        # expiry week at 15:15, one minute before the next entry
        "targetPercent": 1.5, "stopPercent": 1.5, "minDte": 8, "exitDaysBeforeExpiry": 3,
    },
}


# ---------------------------------------------------------------- config


def get_config(mode: str) -> dict[str, Any]:
    config = {}
    for key, default in DEFAULTS[mode].items():
        raw = db.get_batman_setting(f"{mode}.{key}")
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
    config["lotSize"] = LOT_SIZE
    return config


def update_config(mode: str, updates: dict[str, Any]) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError("mode must be monthly or weekly")
    for key, value in updates.items():
        if key not in DEFAULTS[mode] or value is None:
            continue
        default = DEFAULTS[mode][key]
        if key == "entryTime":
            _parse_hhmm(str(value))
        stored = ("1" if value else "0") if isinstance(default, bool) else str(value)
        db.set_batman_setting(f"{mode}.{key}", stored)
    return get_config(mode)


def _parse_hhmm(value: str) -> dtime:
    hour, minute = value.split(":")
    return dtime(int(hour), int(minute))


# ---------------------------------------------------------------- calendar


async def _expiries(dhan: DhanService) -> list[date]:
    raw = await dhan.expiry_list(get_settings().dhan_nifty_security_id, varaha.INDEX_SEGMENT)
    out = []
    for value in raw:
        try:
            out.append(date.fromisoformat(value))
        except ValueError:
            continue
    return sorted(out)


def monthly_expiries(expiries: list[date]) -> list[date]:
    """Last listed expiry of each calendar month (NIFTY monthly = last
    Tuesday, or the trading day before it on a holiday)."""
    by_month: dict[tuple[int, int], date] = {}
    for d in expiries:
        key = (d.year, d.month)
        by_month[key] = max(by_month.get(key, d), d)
    return sorted(by_month.values())


def last_friday_before(day: date) -> date:
    d = day - timedelta(days=1)
    while d.weekday() != 4:
        d -= timedelta(days=1)
    return d


def schedule(mode: str, expiries: list[date], today: date) -> dict[str, Any]:
    """{entryDate, series} for the next scheduled entry on/after today."""
    if mode == "monthly":
        monthlies = monthly_expiries(expiries)
        for i, current in enumerate(monthlies):
            entry = last_friday_before(current)
            if entry >= today and i + 1 < len(monthlies):
                return {"entryDate": entry, "series": monthlies[i + 1], "currentMonthly": current}
        return {"error": "No upcoming monthly series listed."}
    config = get_config("weekly")
    friday = today + timedelta(days=(4 - today.weekday()) % 7)
    series = next((d for d in expiries if (d - friday).days >= int(config["minDte"])), None)
    if not series:
        return {"error": "No weekly expiry far enough out."}
    return {"entryDate": friday, "series": series}


def _exit_by(mode: str, config: dict[str, Any], entry_at: datetime, series: date) -> int:
    if mode == "monthly":
        exit_day = entry_at.date() + timedelta(days=int(config["maxHoldDays"]))
        # never hold into the last 2 days of the series either
        exit_day = min(exit_day, series - timedelta(days=2))
    else:
        exit_day = series - timedelta(days=int(config["exitDaysBeforeExpiry"]))
    while exit_day.weekday() >= 5:  # never schedule an exit on a weekend
        exit_day -= timedelta(days=1)
    return int(datetime.combine(exit_day, TIME_EXIT_AT, tzinfo=IST).timestamp())


# ---------------------------------------------------------------- planning


async def _chain(dhan: DhanService, series: date) -> tuple[float, list[dict[str, Any]]]:
    chain = await dhan.option_chain(get_settings().dhan_nifty_security_id, varaha.INDEX_SEGMENT, series.isoformat())
    spot = varaha._number(chain.get("last_price"))
    if not spot:
        raise RuntimeError(f"Option chain for {series} has no spot.")
    return spot, varaha._trim_chain(chain, spot)


def _construct(mode: str, config: dict[str, Any], spot: float, rows: list[dict[str, Any]], series: date) -> dict[str, Any]:
    years = varaha._years_until_expiry(series)
    common = dict(
        years=years, lot_size=LOT_SIZE, capital=float(config["capital"]), base_lots=int(config["baseLots"]),
        credit_cap_percent=float(config["creditCapPercent"]), shift_step=float(config["shiftStep"]),
        max_shifts=int(config["maxShifts"]), over_hedge=bool(config["overHedge"]),
        max_extra_call_lots=int(config["maxExtraCallLots"]),
    )
    if mode == "monthly":
        plan = engine.construct(
            rows, spot, buy_offset=float(config["buyOffset"]), sell_gap=float(config["sellGap"]),
            hedge_gap=float(config["hedgeGap"]), balance_move=float(config["balanceMove"]), **common,
        )
    else:
        straddle = ve.atm_straddle({"chain": rows}, spot)
        if not straddle:
            return {"error": "No ATM straddle to size the weekly distances."}
        em = straddle["expectedMove"]
        buy, sell, hedge = engine.weekly_distances(em, float(config["buyEm"]), float(config["sellEm"]), float(config["hedgeEm"]))
        plan = engine.construct(
            rows, spot, buy_offset=buy, sell_gap=sell, hedge_gap=hedge, balance_move=round(em * float(config["balanceEm"])),
            **common,
        )
        plan["expectedMove"] = round(em, 1)
    if "error" not in plan:
        plan["payoff"] = engine.payoff_points(plan["legs"], spot, years, plan["forwardRatio"], LOT_SIZE)
        plan["targetAmount"] = round(float(config["capital"]) * float(config["targetPercent"]) / 100)
        plan["stopAmount"] = round(float(config["capital"]) * float(config["stopPercent"]) / 100)
    return plan


async def preview(mode: str) -> dict[str, Any]:
    config = get_config(mode)
    dhan = DhanService()
    try:
        expiries = await _expiries(dhan)
        sched = schedule(mode, expiries, now_ist().date())
        if "error" in sched:
            return {"error": sched["error"], "config": config}
        spot, rows = await _chain(dhan, sched["series"])
    except Exception as exc:
        return {"error": f"Dhan data unavailable: {exc}", "config": config}
    plan = _construct(mode, config, spot, rows, sched["series"])
    entry_at = datetime.combine(sched["entryDate"], _parse_hhmm(config["entryTime"]), tzinfo=IST)
    plan.update(
        config=config,
        entryDate=sched["entryDate"].isoformat(),
        entryAt=int(entry_at.timestamp()),
        series=sched["series"].isoformat(),
        currentMonthly=sched.get("currentMonthly").isoformat() if sched.get("currentMonthly") else None,
        exitBy=_exit_by(mode, config, entry_at, sched["series"]),
        daysToExpiryAtEntry=(sched["series"] - sched["entryDate"]).days,
    )
    plan["events"] = _event_warnings()
    return plan


def _event_warnings() -> list[str]:
    calendar = db.get_market_calendar() or {}
    return [item.get("headline", "") for item in calendar.get("items") or [] if item.get("impact") == "high"]


# ---------------------------------------------------------------- entry


async def _market_traded_today(dhan: DhanService) -> bool:
    today = now_ist().date().isoformat()
    try:
        candles = await dhan.intraday_candles(str(get_settings().dhan_nifty_security_id), varaha.INDEX_SEGMENT, "INDEX", "1", today, today)
    except Exception:
        return False
    return bool(candles)


async def enter(mode: str, trigger: str = "scheduled") -> dict[str, Any]:
    if mode not in ACTIVE_MODES:
        raise ValueError(f"mode must be one of {ACTIVE_MODES}")
    config = get_config(mode)
    dhan = DhanService()
    async with _lock:
        if db.list_batman_trades(mode=mode, status="OPEN", limit=1):
            return {"status": "blocked", "message": f"A {mode} Batman is already open -- one at a time."}
        expiries = await _expiries(dhan)
        today = now_ist().date()
        sched = schedule(mode, expiries, today)
        if "error" in sched:
            return {"status": "skipped", "message": sched["error"]}
        if trigger == "scheduled" and sched["entryDate"] != today:
            return {"status": "skipped", "message": "Not the entry day."}
        spot, rows = await _chain(dhan, sched["series"])
        plan = _construct(mode, config, spot, rows, sched["series"])
        if "error" in plan:
            await _notify(f"Batman {mode}: no entry -- {plan['error']}")
            return {"status": "skipped", "message": plan["error"]}
        if not plan["creditOk"]:
            note = f"Credit {plan['creditPercent']}% still above the {config['creditCapPercent']}% cap after {plan['creditShifts']} shifts"
            await _notify(f"Batman {mode}: no entry -- {note}")
            return {"status": "skipped", "message": note}
        now = datetime.now(IST)
        trade_id = db.create_batman_trade(
            plan["legs"],
            mode=mode, session_date=today.isoformat(), trigger=trigger, expiry=sched["series"].isoformat(),
            entry_time=int(now.timestamp()), spot=spot, capital=float(config["capital"]), lot_size=LOT_SIZE,
            base_lots=int(config["baseLots"]), buy_offset=plan["buyOffset"], sell_gap=plan["sellGap"],
            hedge_gap=plan["hedgeGap"], extra_call_lots=plan["extraCallLots"], credit=plan["credit"],
            credit_percent=plan["creditPercent"], target_percent=float(config["targetPercent"]),
            stop_percent=float(config["stopPercent"]), exit_by=_exit_by(mode, config, now, sched["series"]),
            status="OPEN", last_mtm=0.0, last_update=int(now.timestamp()),
            plan_json=json.dumps({k: plan[k] for k in ("t0Down", "t0Up", "t0DownPercent", "t0UpPercent", "balanceMove",
                                                       "breakevens", "expiryMaxProfit", "expiryMaxLoss", "creditShifts")}),
            notes=("High-impact events on the calendar: " + "; ".join(_event_warnings())) if _event_warnings() else None,
        )
    trade = next(t for t in db.list_batman_trades(mode=mode, limit=5) if t["id"] == trade_id)
    await _notify(_entry_message(trade, plan))
    return {"status": "entered", "trade": summarize(trade)}


# ---------------------------------------------------------------- monitoring


def _mtm(trade: dict[str, Any], quotes: dict[tuple[float, str], dict[str, Any]]) -> tuple[float, float]:
    """(MTM at LTP, value if exited now at bid/ask) in rupees."""
    lot = int(trade["lotSize"])
    mtm = exit_value = 0.0
    for leg in trade["legs"]:
        quote = quotes.get((float(leg["strike"]), leg["optionType"])) or {}
        ltp = quote.get("ltp") or leg["lastLtp"] or leg["entryPrice"]
        sign = 1 if leg["action"] == "BUY" else -1
        mtm += sign * (float(ltp) - float(leg["entryPrice"])) * int(leg["lots"]) * lot
        fill = (quote.get("bid") if sign > 0 else quote.get("ask")) or ltp
        exit_value += sign * (float(fill) - float(leg["entryPrice"])) * int(leg["lots"]) * lot
    return round(mtm, 2), round(exit_value, 2)


def _quote_map(rows: list[dict[str, Any]]) -> dict[tuple[float, str], dict[str, Any]]:
    out = {}
    for row in rows:
        for option_type in ("CE", "PE"):
            quote = row.get(option_type.lower())
            if quote:
                out[(float(row["strike"]), option_type)] = quote
    return out


def _market_open(now: datetime) -> bool:
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE


async def monitor_once() -> None:
    now = datetime.now(IST)
    if not _market_open(now):
        return
    dhan = DhanService()
    async with _lock:
        for trade in db.list_batman_trades(status="OPEN", limit=10):
            try:
                await _manage(dhan, trade, now)
            except Exception:
                logger.exception("batman: manage trade #%s failed", trade["id"])

    if ENTRY_WINDOW_END >= now.time():
        for mode in ACTIVE_MODES:
            config = get_config(mode)
            if not config["enabled"] or now.time() < _parse_hhmm(config["entryTime"]):
                continue
            if db.has_batman_trade_for_session(mode, now.date().isoformat()):
                continue
            expiries = await _expiries(dhan)
            sched = schedule(mode, expiries, now.date())
            if sched.get("entryDate") != now.date():
                continue
            if not await _market_traded_today(dhan):
                continue  # exchange holiday -- the chain would be stale
            await enter(mode, "scheduled")


async def _manage(dhan: DhanService, trade: dict[str, Any], now: datetime) -> None:
    spot, rows = await _chain(dhan, date.fromisoformat(trade["expiry"]))
    quotes = _quote_map(rows)
    mtm, exit_value = _mtm(trade, quotes)
    stamp = int(now.timestamp())
    for leg in trade["legs"]:
        quote = quotes.get((float(leg["strike"]), leg["optionType"])) or {}
        if quote:
            db.update_batman_leg(leg["id"], last_ltp=quote.get("ltp"), last_bid=quote.get("bid"), last_ask=quote.get("ask"))
    db.update_batman_trade(trade["id"], last_mtm=mtm, last_update=stamp)
    db.record_batman_mtm(trade["id"], stamp, mtm, spot)

    capital = float(trade["capital"])
    reason = None
    if mtm >= capital * float(trade["targetPercent"]) / 100:
        reason = "target"
    elif mtm <= -capital * float(trade["stopPercent"]) / 100:
        reason = "stop_loss"
    elif stamp >= int(trade["exitBy"]):
        reason = "time_exit"
    if reason:
        _close(trade, quotes, reason, stamp)
        closed = next(t for t in db.list_batman_trades(mode=trade["mode"], limit=10) if t["id"] == trade["id"])
        await _notify(_exit_message(summarize(closed)))


def _close(trade: dict[str, Any], quotes: dict[tuple[float, str], dict[str, Any]], reason: str, stamp: int) -> None:
    lot = int(trade["lotSize"])
    settings = get_settings()
    realized = 0.0
    charges = 0.0
    for leg in trade["legs"]:
        quote = quotes.get((float(leg["strike"]), leg["optionType"])) or {}
        ltp = quote.get("ltp") or leg["lastLtp"] or leg["entryPrice"]
        sign = 1 if leg["action"] == "BUY" else -1
        price = float((quote.get("bid") if sign > 0 else quote.get("ask")) or ltp)
        qty = int(leg["lots"]) * lot
        realized += sign * (price - float(leg["entryPrice"])) * qty
        for fill_price, side in ((float(leg["entryPrice"]), leg["action"]), (price, "SELL" if sign > 0 else "BUY")):
            charges += option_order_charges(premium=fill_price, quantity=qty, side=side, exchange_segment=OPTION_SEGMENT, settings=settings)["total"]
        db.update_batman_leg(leg["id"], exit_price=price)
    db.update_batman_trade(
        trade["id"], status="CLOSED", exit_time=stamp, exit_reason=reason, realized_pnl=round(realized, 2),
        charges=round(charges, 2),
    )


async def close_now(trade_id: int) -> dict[str, Any]:
    async with _lock:
        trade = next((t for t in db.list_batman_trades(status="OPEN", limit=10) if t["id"] == trade_id), None)
        if not trade:
            return {"status": "blocked", "message": "Trade is not open."}
        _, rows = await _chain(DhanService(), date.fromisoformat(trade["expiry"]))
        _close(trade, _quote_map(rows), "manual", int(time.time()))
    closed = next(t for t in db.list_batman_trades(limit=20) if t["id"] == trade_id)
    await _notify(_exit_message(summarize(closed)))
    return {"status": "closed", "trade": summarize(closed)}


# ---------------------------------------------------------------- reporting


def summarize(trade: dict[str, Any]) -> dict[str, Any]:
    capital = float(trade["capital"])
    lot = int(trade["lotSize"])
    if trade["status"] == "CLOSED":
        gross = float(trade["realizedPnl"] or 0)
        charges = float(trade["charges"] or 0)
    else:
        gross = float(trade["lastMtm"] or 0)
        settings = get_settings()
        charges = sum(
            option_order_charges(premium=float(l["entryPrice"]), quantity=int(l["lots"]) * lot, side=l["action"],
                                 exchange_segment=OPTION_SEGMENT, settings=settings)["total"] * 2
            for l in trade["legs"]
        )
    trade["grossPnl"] = round(gross, 2)
    trade["estimatedCharges"] = round(charges, 2)
    trade["netPnl"] = round(gross - charges, 2)
    trade["returnPercent"] = round(gross / capital * 100, 2)
    trade["targetAmount"] = round(capital * float(trade["targetPercent"]) / 100)
    trade["stopAmount"] = round(capital * float(trade["stopPercent"]) / 100)
    return trade


def list_trades(mode: str | None = None) -> list[dict[str, Any]]:
    return [summarize(t) for t in db.list_batman_trades(mode=mode, limit=300)]


async def trade_detail(trade_id: int) -> dict[str, Any]:
    trade = next((t for t in db.list_batman_trades(limit=300) if t["id"] == trade_id), None)
    if not trade:
        return {"error": "trade not found"}
    trade = summarize(trade)
    trade["mtmHistory"] = db.list_batman_mtm(trade_id)
    spot = (trade["mtmHistory"][-1]["spot"] if trade["mtmHistory"] else None) or float(trade["spot"])
    legs = [
        {"action": l["action"], "qty": l["lots"], "optionType": l["optionType"], "strike": l["strike"],
         "price": l["entryPrice"], "iv": l["iv"]}
        for l in trade["legs"]
    ]
    years = varaha._years_until_expiry(date.fromisoformat(trade["expiry"]))
    trade["currentSpot"] = spot
    trade["payoff"] = engine.payoff_points(legs, spot, years, 1.0, int(trade["lotSize"]))
    trade["breakevens"] = ve._breakevens(legs, spot * 0.5, spot * 1.5)
    return trade


# ---------------------------------------------------------------- weekly analyzer
#
# Batman -> Weekly tab: an interactive builder for any NIFTY expiry. Pure
# analysis -- it never creates trades. Chains are cached briefly so moving the
# controls doesn't hammer Dhan's rate-limited option-chain endpoint.

ANALYZER_CHAIN_CACHE_SECONDS = 30
ANALYZER_EXPIRY_CACHE_SECONDS = 300
_analyzer_chains: dict[str, tuple[float, float, list[dict[str, Any]]]] = {}
_analyzer_expiries: tuple[float, list[date]] | None = None


async def _cached_expiries(dhan: DhanService) -> list[date]:
    global _analyzer_expiries
    if _analyzer_expiries and time.monotonic() - _analyzer_expiries[0] < ANALYZER_EXPIRY_CACHE_SECONDS:
        return _analyzer_expiries[1]
    expiries = await _expiries(dhan)
    _analyzer_expiries = (time.monotonic(), expiries)
    return expiries


async def _cached_chain(dhan: DhanService, series: date) -> tuple[float, list[dict[str, Any]]]:
    cached = _analyzer_chains.get(series.isoformat())
    if cached and time.monotonic() - cached[0] < ANALYZER_CHAIN_CACHE_SECONDS:
        return cached[1], cached[2]
    spot, rows = await _chain(dhan, series)
    _analyzer_chains[series.isoformat()] = (time.monotonic(), spot, rows)
    return spot, rows


async def analyze(
    *, expiry: str | None, base_lots: int, short_ratio: int, outer_ratio: int, buy_offset: float | None,
    sell_gap: float | None, hedge_gap: float | None, extra_call_lots: int | None, capital: float,
    balance_move: float | None, max_extra_call_lots: int = 12,
) -> dict[str, Any]:
    dhan = DhanService()
    today = now_ist().date()
    expiries = [d for d in await _cached_expiries(dhan) if d >= today]
    if not expiries:
        return {"error": "No NIFTY expiries listed."}
    # Default to the weekly ~8+ days out (a Batman needs time; the last few
    # days are pure gamma). Any listed expiry can still be picked.
    default = next((d for d in expiries if (d - today).days >= 8), expiries[0])
    series = next((d for d in expiries if d.isoformat() == expiry), default)
    spot, rows = await _cached_chain(dhan, series)

    straddle = ve.atm_straddle({"chain": rows}, spot)
    em = straddle["expectedMove"] if straddle else None
    suggested = None
    if em:
        b, sg, hg = engine.weekly_distances(em, 0.6, 0.25, 1.2)
        suggested = {"buyOffset": b, "sellGap": sg, "hedgeGap": hg, "balanceMove": engine._round_to_step(em * 0.67)}
    buy_offset = buy_offset if buy_offset is not None else (suggested or {}).get("buyOffset", 400.0)
    sell_gap = sell_gap if sell_gap is not None else (suggested or {}).get("sellGap", 200.0)
    hedge_gap = hedge_gap if hedge_gap is not None else (suggested or {}).get("hedgeGap", 800.0)
    balance_move = balance_move if balance_move is not None else (suggested or {}).get("balanceMove", 500.0)

    plan = engine.construct(
        rows, spot, years=varaha._years_until_expiry(series), lot_size=LOT_SIZE, capital=capital,
        base_lots=base_lots, buy_offset=buy_offset, sell_gap=sell_gap, hedge_gap=hedge_gap,
        credit_cap_percent=1000.0, shift_step=50.0, max_shifts=0, balance_move=balance_move,
        over_hedge=True, max_extra_call_lots=max_extra_call_lots, short_ratio=short_ratio,
        outer_ratio=outer_ratio, fixed_extra_call_lots=extra_call_lots,
    )
    expiry_list = [
        {"expiry": d.isoformat(), "dte": (d - today).days, "monthly": d in monthly_expiries(expiries)}
        for d in expiries
        if (d - today).days <= 60
    ]
    if "error" in plan:
        return {**plan, "expiries": expiry_list, "series": series.isoformat(), "suggested": suggested}
    plan["payoff"] = engine.payoff_points(plan["legs"], spot, plan["years"], plan["forwardRatio"], LOT_SIZE)
    plan.update(
        series=series.isoformat(),
        dte=(series - today).days,
        expiries=expiry_list,
        expectedMove=round(em, 1) if em else None,
        atmIv=straddle["atmIv"] if straddle else None,
        suggested=suggested,
        inputs={
            "baseLots": base_lots, "shortRatio": short_ratio, "outerRatio": outer_ratio, "buyOffset": buy_offset,
            "sellGap": sell_gap, "hedgeGap": hedge_gap, "extraCallLots": extra_call_lots, "capital": capital,
            "balanceMove": balance_move,
        },
        autoExtraCallLots=extra_call_lots is None,
    )
    return plan


# ---------------------------------------------------------------- loop / alerts


def _leg_text(leg: dict[str, Any]) -> str:
    return f"{leg['action']} {leg.get('qty', leg.get('lots'))}L {leg['strike']:.0f}{leg['optionType']} @ {leg.get('price', leg.get('entryPrice'))}"


def _entry_message(trade: dict[str, Any], plan: dict[str, Any]) -> str:
    lines = [
        f"🦇 Batman {trade['mode']} #{trade['id']} entered (paper) -- series {trade['expiry']}",
        f"Spot {plan['spot']:.0f}, buy offset ±{plan['buyOffset']:.0f}, credit ₹{plan['credit']:,.0f} ({plan['creditPercent']}%), "
        f"+{plan['extraCallLots']} outer CE (T+0 ±{plan['balanceMove']:.0f}: {plan['t0DownPercent']}% / {plan['t0UpPercent']}%)",
        *[_leg_text(l) for l in plan["legs"]],
        f"Target +₹{plan['targetAmount']:,} / stop -₹{plan['stopAmount']:,}; exit by {datetime.fromtimestamp(trade['exitBy'], IST):%d %b %H:%M}",
    ]
    return "\n".join(lines)


def _exit_message(trade: dict[str, Any]) -> str:
    return (
        f"🦇 Batman {trade['mode']} #{trade['id']} closed ({trade['exitReason']}): gross ₹{trade['grossPnl']:,.0f} "
        f"({trade['returnPercent']}%), charges ₹{trade['estimatedCharges']:,.0f}, net ₹{trade['netPnl']:,.0f}"
    )


async def _notify(text: str) -> None:
    try:
        await TelegramNotifier().send(text)
    except Exception:
        logger.warning("batman: telegram send failed")


def start_batman_task() -> asyncio.Task | None:
    if not get_settings().batman_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_batman_task(task: asyncio.Task | None) -> None:
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
            logger.exception("batman: monitor iteration failed")
        await asyncio.sleep(POLL_SECONDS)
