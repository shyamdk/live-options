"""Melting Straddles - Gap -- Melting Straddles plus a gap filter (paper only, NIFTY).

Same rules as Melting Straddles (app/services/melting.py, which this module was
generated from), with one more: if NIFTY opens `gapPercent` (0.3%) or more away
from the previous close, the day is braked at setup -- no entries that day.
Nov 2026 backtest, NIFTY Fri/Mon/Tue, Jan 2025 - Oct 2026, 4 lots: as built
-Rs91k (max drawdown -Rs1.33L) vs +Rs35k (-Rs48k) with the filter; every gap
threshold from 0.2% to 0.5% improved both years (backend/data/history/
backtests/melt_filters.py). Sensex is off by default (the filter was tested on
NIFTY only). Runs alongside Melting Straddles with its own settings and trades
(melting_gap_* tables) so the two can be compared on the same days.
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
from app.db import sqlite as _sqlite

PREFIX = "melting_gap"
_PREFIXED = {"melting_update_trade", "get_melting_day", "list_melting_days", "upsert_melting_day", "update_melting_day",
             "list_melting_trades", "get_melting_trade", "list_melting_fills", "list_melting_events", "save_melting_minutes",
             "list_melting_minutes", "get_melting_setting", "set_melting_setting"}


class _DB:
    """The Melting Straddles DB functions, pointed at this module's own tables."""
    def __getattr__(self, name):
        fn = getattr(_sqlite, name)
        return (lambda *a, **k: fn(*a, prefix=PREFIX, **k)) if name in _PREFIXED else fn


db = _DB()
from app.services import melting_engine as engine
from app.services import varaha
from app.services.charges import option_order_charges
from app.services.dhan import DhanService
from app.services.orders import DhanOrderService
from app.services.telegram import TelegramNotifier

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
POLL_SECONDS = 10
TAGS = ("LOWER", "ATM", "HIGHER")
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
INDEXES = {
    "NIFTY": {"scrip": "dhan_nifty_security_id", "segment": "NSE_FNO", "lotSize": 65},
    "SENSEX": {"scrip": "dhan_sensex_security_id", "segment": "BSE_FNO", "lotSize": 20},
}
INDEX_SEGMENT = "IDX_I"

COMMON_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "mode": "paper",
    "boxPercent": 0.5,
    "reversal": 3,
    "lotsPerStraddle": 4,
    "maxOpen": 2,
    "entryStart": "09:30",
    "entryEnd": "13:45",
    "exitTime": "14:00",
    "maxStops": 3,
    "patterns": ",".join(engine.PATTERNS),
    "turtleLookback": 5,
    "anchorLookback": 10,
    "tallMultiple": 2.0,
    "signalMaxAgeMinutes": 2,
    # gap filter: no trading on a day whose open is gapPercent or more away from the previous close
    "gapFilter": True,
    "gapPercent": 0.3,
}
INDEX_DEFAULTS: dict[str, dict[str, Any]] = {
    "NIFTY": {"enabled": True, "tradeDays": "FRI,MON,TUE", "maxDaysToExpiry": 4, "strikeStep": 100.0, "offset": 200.0,
              "stopPoints": 10.0, "stepPoints": 10.0, "brakePoints": 20.0},
    "SENSEX": {"enabled": False, "tradeDays": "WED,THU", "maxDaysToExpiry": 1, "strikeStep": 500.0, "offset": 500.0,
               "stopPoints": 30.0, "stepPoints": 30.0, "brakePoints": 60.0},
}

_lock = asyncio.Lock()
_expiry_cache: dict[str, tuple[float, list[date]]] = {}
_runtime: dict[str, Any] = {"day": None, "lastMinute": 0, "charts": {}, "series": {}, "quotes": {}, "quotesAt": 0}


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
    config: dict[str, Any] = {}
    for key, default in COMMON_DEFAULTS.items():
        raw = db.get_melting_setting(key)
        config[key] = default if raw is None else _coerce(default, raw)
    for name, defaults in INDEX_DEFAULTS.items():
        section = {}
        for key, default in defaults.items():
            raw = db.get_melting_setting(f"{name}.{key}")
            section[key] = default if raw is None else _coerce(default, raw)
        section["lotSize"] = INDEXES[name]["lotSize"]
        config[name] = section
    settings = get_settings()
    config["liveOrdersAllowed"] = False  # paper only
    config["patternList"] = [p.strip() for p in str(config["patterns"]).split(",") if p.strip() in engine.PATTERNS]
    return config


def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if value is None:
            continue
        if key in INDEX_DEFAULTS and isinstance(value, dict):
            for sub, sub_value in value.items():
                if sub in INDEX_DEFAULTS[key] and sub_value is not None:
                    default = INDEX_DEFAULTS[key][sub]
                    _validate(sub, sub_value)
                    db.set_melting_setting(f"{key}.{sub}", ("1" if sub_value else "0") if isinstance(default, bool) else str(sub_value))
            continue
        if key not in COMMON_DEFAULTS:
            continue
        if key == "mode":
            if value not in ("paper", "live"):
                raise ValueError("mode must be paper or live")
            settings = get_settings()
            if value == "live":
                raise ValueError("Melting Straddles - Gap is paper only.")
        _validate(key, value)
        default = COMMON_DEFAULTS[key]
        db.set_melting_setting(key, ("1" if value else "0") if isinstance(default, bool) else str(value))
    return get_config()


def _validate(key: str, value: Any) -> None:
    if key in ("entryStart", "entryEnd", "exitTime"):
        datetime.strptime(str(value), "%H:%M")
    elif key == "tradeDays":
        days = [d.strip().upper() for d in str(value).split(",") if d.strip()]
        if not days or any(d not in WEEKDAYS for d in days):
            raise ValueError("tradeDays must be like FRI,MON,TUE")
    elif key == "patterns":
        if any(p.strip() not in engine.PATTERNS for p in str(value).split(",") if p.strip()):
            raise ValueError(f"patterns must be from {', '.join(engine.PATTERNS)}")
    elif key in ("lotsPerStraddle", "maxOpen", "reversal", "maxStops") and int(float(value)) < 1:
        raise ValueError(f"{key} must be at least 1")
    elif key == "gapPercent" and not 0 < float(value) < 5:
        raise ValueError("gapPercent must be between 0 and 5")


def _hhmm(value: str) -> dtime:
    return datetime.strptime(value, "%H:%M").time()


def _mode(config: dict[str, Any]) -> str:
    return "live" if config["mode"] == "live" and config["liveOrdersAllowed"] else "paper"


# ---------------------------------------------------------------- calendar


async def _expiries(dhan: DhanService, name: str) -> list[date]:
    cached = _expiry_cache.get(name)
    if cached and time.monotonic() - cached[0] < 1800:
        return cached[1]
    scrip = getattr(get_settings(), INDEXES[name]["scrip"])
    expiries = sorted(date.fromisoformat(x) for x in await dhan.expiry_list(scrip, INDEX_SEGMENT))
    _expiry_cache[name] = (time.monotonic(), expiries)
    return expiries


async def pick_index(dhan: DhanService, today: date, config: dict[str, Any]) -> tuple[str | None, date | None, str]:
    """Which index trades today, its nearest expiry, and why."""
    weekday = WEEKDAYS[today.weekday()]
    for name in INDEXES:
        section = config[name]
        days = [d.strip().upper() for d in str(section["tradeDays"]).split(",")]
        if weekday not in days:
            continue
        if not section["enabled"]:
            return None, None, f"{name} trades on {weekday} but is switched off in settings."
        upcoming = [d for d in await _expiries(dhan, name) if d >= today]
        if not upcoming:
            return None, None, f"No {name} expiry listed."
        expiry = upcoming[0]
        dte = (expiry - today).days
        if dte > int(section["maxDaysToExpiry"]):
            return None, expiry, f"{name} nearest expiry {expiry:%a %d %b} is {dte} days away (max {section['maxDaysToExpiry']}) -- no trade."
        return name, expiry, f"{name} day -- expiry {expiry:%a %d %b} ({'expiry day' if dte == 0 else f'{dte} day' + ('s' if dte > 1 else '') + ' to go'})."
    return None, None, f"{weekday} is not a trading day for either index."


def market_open(now: datetime) -> bool:
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)


# ---------------------------------------------------------------- day setup


async def setup_day(dhan: DhanService, today: date, config: dict[str, Any]) -> dict[str, Any] | None:
    existing = db.get_melting_day(today.isoformat())
    if existing:
        return _day_payload(existing)
    name, expiry, why = await pick_index(dhan, today, config)
    if not name or not expiry:
        return None
    settings = get_settings()
    scrip = getattr(settings, INDEXES[name]["scrip"])
    candles = await dhan.intraday_candles(str(scrip), INDEX_SEGMENT, "INDEX", "1", today.isoformat(), today.isoformat())
    candles = sorted(candles, key=lambda c: c["time"])
    if not candles:
        return None
    spot_open = float(candles[0]["open"])
    section = config[name]
    step, offset = float(section["strikeStep"]), float(section["offset"])
    atm = round(spot_open / step) * step
    chain = await dhan.option_chain(scrip, INDEX_SEGMENT, expiry.isoformat())
    oc = chain.get("oc") or {}
    by_strike = {}
    for key, sides in oc.items():
        strike = varaha._number(key)
        if strike is not None and isinstance(sides, dict):
            by_strike[float(strike)] = sides
    straddles = {}
    for tag, strike in (("LOWER", atm - offset), ("ATM", atm), ("HIGHER", atm + offset)):
        sides = by_strike.get(float(strike)) or {}
        ce, pe = varaha._quote(sides.get("ce")), varaha._quote(sides.get("pe"))
        if ce and pe:
            straddles[tag] = {"strike": strike, "ceSecurityId": ce["securityId"], "peSecurityId": pe["securityId"]}
    if not straddles:
        _event(today.isoformat(), None, "setup", f"{name}: no option chain rows for {atm - offset:g}/{atm:g}/{atm + offset:g}.")
        return None
    row = {
        "day": today.isoformat(), "index_name": name, "expiry": expiry.isoformat(), "dte": (expiry - today).days,
        "spot_open": spot_open, "atm": atm, "straddles": json.dumps(straddles), "lot_size": INDEXES[name]["lotSize"],
        "exchange_segment": INDEXES[name]["segment"], "stops": 0, "created_at": int(time.time()),
    }
    if config["gapFilter"]:
        prev_close = await _previous_close(dhan, str(scrip), today)
        if prev_close:
            gap = (spot_open / prev_close - 1) * 100
            row["gap_percent"] = round(gap, 3)
            if abs(gap) >= float(config["gapPercent"]):
                row["braked_at"] = int(time.time())
                row["brake_reason"] = f"gap {gap:+.2f}% (open {spot_open:,.2f} vs previous close {prev_close:,.2f}) -- no trading today"
    db.upsert_melting_day(row)
    if row.get("brake_reason"):
        _event(row["day"], None, "brake", row["brake_reason"])
    text = (f"{name} open {spot_open:,.2f} -> straddles " + " / ".join(f"{t} {s['strike']:g}" for t, s in straddles.items())
            + f" · expiry {expiry:%a %d %b} ({row['dte']}d)")
    _event(row["day"], None, "setup", text)
    await _notify(f"🫠 Melting Straddles - Gap: {text} · {_mode(config).upper()}")
    return _day_payload(row)


async def _previous_close(dhan: DhanService, scrip: str, today: date) -> float | None:
    """The index's last daily close before today (Dhan's to_date is exclusive)."""
    try:
        candles = await dhan.historical_daily_candles(scrip, INDEX_SEGMENT, "INDEX", (today - timedelta(days=10)).isoformat(), today.isoformat())
    except Exception as exc:
        logger.warning("melting_gap: previous close unavailable: %s", exc)
        return None
    rows = [c for c in candles if datetime.fromtimestamp(int(c["time"]), IST).date() < today]
    return float(sorted(rows, key=lambda c: int(c["time"]))[-1]["close"]) if rows else None


def _day_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "day": row["day"], "indexName": row["index_name"], "expiry": row["expiry"], "dte": row["dte"],
        "spotOpen": row["spot_open"], "atm": row["atm"], "straddles": json.loads(row["straddles"]),
        "lotSize": row["lot_size"], "exchangeSegment": row["exchange_segment"], "stops": row["stops"],
        "brakedAt": row.get("braked_at"), "brakeReason": row.get("brake_reason"), "gapPercent": row.get("gap_percent"),
    }


# ---------------------------------------------------------------- market data


async def _quotes(dhan: DhanService, day: dict[str, Any]) -> dict[str, dict[str, Any]]:
    ids = [int(s[k]) for s in day["straddles"].values() for k in ("ceSecurityId", "peSecurityId")]
    data = await dhan.market_quotes_by_segment({day["exchangeSegment"]: ids}, max_age_seconds=2)
    rows = data.get(day["exchangeSegment"]) or {}
    out = {}
    for sec, q in rows.items():
        if not isinstance(q, dict):
            continue
        depth = q.get("depth") or {}
        buy = (depth.get("buy") or [{}])[0] or {}
        sell = (depth.get("sell") or [{}])[0] or {}
        out[str(sec)] = {
            "ltp": varaha._number(q.get("last_price")),
            "bid": varaha._number(buy.get("price")) or None,
            "ask": varaha._number(sell.get("price")) or None,
            "atp": varaha._number(q.get("average_price")),
            "volume": varaha._number(q.get("volume")),
        }
    _runtime["quotes"], _runtime["quotesAt"] = out, int(time.time())
    return out


def _leg_fill(quote: dict[str, Any] | None, side: str) -> float | None:
    if not quote:
        return None
    bid, ask, ltp = quote.get("bid"), quote.get("ask"), quote.get("ltp")
    if bid and ask and ask >= bid > 0:
        return float(ask) if side == "BUY" else float(bid)
    return float(ltp) if ltp else None


async def _series(dhan: DhanService, day: dict[str, Any], today: date) -> dict[str, list[dict[str, Any]]]:
    out = {}
    for tag, s in day["straddles"].items():
        legs = []
        for key in ("ceSecurityId", "peSecurityId"):
            await asyncio.sleep(0.35)
            legs.append(await dhan.intraday_candles(s[key], day["exchangeSegment"], "OPTIDX", "1", today.isoformat(), today.isoformat()))
        cutoff = int(time.time()) - 60
        ce = [c for c in legs[0] if int(c["time"]) <= cutoff]
        pe = [c for c in legs[1] if int(c["time"]) <= cutoff]
        out[tag] = engine.combine(ce, pe)
    return out


# ---------------------------------------------------------------- execution


async def _execute(day: dict[str, Any], straddle: dict[str, Any], side: str, lots: int, *, mode: str,
                   correlation: str, fallback: tuple[float | None, float | None] = (None, None)) -> dict[str, Any]:
    """Fills both legs. Returns ce/pe prices, quotes at the time, order ids, status and a note."""
    dhan = DhanService(get_settings())
    try:
        quotes = await _quotes(dhan, day)
    except Exception:
        quotes = _runtime.get("quotes") or {}
    qce, qpe = quotes.get(str(straddle["ceSecurityId"])), quotes.get(str(straddle["peSecurityId"]))
    qty = lots * int(day["lotSize"])
    result: dict[str, Any] = {
        "ceQuote": qce or {}, "peQuote": qpe or {}, "ce": _leg_fill(qce, side), "pe": _leg_fill(qpe, side),
        "ceOrderId": None, "peOrderId": None, "status": "PAPER", "note": None, "ok": True, "failedLegs": [],
    }
    if mode != "live":
        if result["ce"] is None or result["pe"] is None:
            result.update(ok=False, status="NO_QUOTE", note="No quote for one of the legs.")
        return result

    settings = get_settings()
    orders = DhanOrderService(settings)

    async def leg(security_id: str, suffix: str) -> dict[str, Any]:
        last: dict[str, Any] = {}
        for attempt in range(3):
            last = await orders.place_market_order(
                transaction_type=side, exchange_segment=day["exchangeSegment"], security_id=security_id, quantity=qty,
                correlation_id=f"{correlation}{suffix}{attempt}", product_type=settings.melting_live_order_product_type,
            )
            if last.get("status") == "sent":
                return last
            await asyncio.sleep(0.6)
        return last

    ce_res, pe_res = await asyncio.gather(leg(straddle["ceSecurityId"], "C"), leg(straddle["peSecurityId"], "P"))
    statuses = []
    for name, res in (("ce", ce_res), ("pe", pe_res)):
        order = res.get("order") or {}
        order_id = str(order.get("orderId") or (order.get("data") or {}).get("orderId") or "") or None
        result[f"{name}OrderId"] = order_id
        if res.get("status") != "sent":
            result["failedLegs"].append(name.upper())
            statuses.append(f"{name.upper()} {res.get('status')}: {res.get('message')}")
            continue
        price = await _traded_price(orders, order_id)
        if price:
            result[name] = price
        elif result[name] is None:
            result[name] = fallback[0 if name == "ce" else 1]
        statuses.append(f"{name.upper()} sent" + ("" if price else " (fill price not confirmed -- quote used)"))
    result["status"] = "LIVE" if not result["failedLegs"] else "LIVE-PARTIAL"
    result["note"] = "; ".join(statuses)
    result["ok"] = not result["failedLegs"]
    if result["ok"] and (result["ce"] is None or result["pe"] is None):
        result["note"] += "; NO PRICE for a filled leg -- check Dhan"
        result["ce"] = result["ce"] or 0.0
        result["pe"] = result["pe"] or 0.0
    return result


async def _traded_price(orders: DhanOrderService, order_id: str | None) -> float | None:
    if not order_id:
        return None
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
        if status in ("TRADED", "PART_TRADED") and price:
            return float(price)
        if status in ("REJECTED", "CANCELLED", "EXPIRED"):
            return None
    return None


def _charges(day: dict[str, Any], ce: float, pe: float, lots: int, side: str) -> float:
    qty = lots * int(day["lotSize"])
    total = 0.0
    for price in (ce, pe):
        total += option_order_charges(premium=price, quantity=qty, side=side, exchange_segment=day["exchangeSegment"])["total"]
    return round(total, 2)


# ---------------------------------------------------------------- trade lifecycle


async def open_trade(day: dict[str, Any], tag: str, signal: dict[str, Any], vwap: float, config: dict[str, Any],
                     trigger: str = "signal") -> dict[str, Any]:
    straddle = day["straddles"][tag]
    section = config[day["indexName"]]
    lots = int(config["lotsPerStraddle"])
    mode = _mode(config)
    now = int(time.time())
    last = ((_runtime.get("series") or {}).get(tag) or [{}])[-1]
    fill = await _execute(day, straddle, "SELL", lots, mode=mode, correlation=f"MS{now % 10000000}{tag[0]}E",
                          fallback=(last.get("ce"), last.get("pe")))
    if not fill["ok"]:
        if mode == "live" and len(fill["failedLegs"]) == 1:
            # one leg sold, the other not: never leave a naked leg -- buy it straight back.
            filled = "pe" if fill["failedLegs"] == ["CE"] else "ce"
            undo = await DhanOrderService(get_settings()).place_market_order(
                transaction_type="BUY", exchange_segment=day["exchangeSegment"],
                security_id=straddle[f"{filled}SecurityId"], quantity=lots * int(day["lotSize"]),
                correlation_id=f"MS{tag[0]}UNDO{now % 100000}", product_type=get_settings().melting_live_order_product_type,
            )
            text = f"{tag} entry: {fill['note']} -- bought back the {filled.upper()} leg ({undo.get('status')}). CHECK DHAN POSITIONS."
            _event(day["day"], None, "live_error", text)
            await _notify(f"🚨 Melting Straddles - Gap {text}")
        else:
            _event(day["day"], None, "entry_failed", f"{tag} entry skipped: {fill['note']}")
        return {"status": "failed", "message": fill["note"]}
    entry = round(fill["ce"] + fill["pe"], 2)
    stop = float(section["stopPoints"])
    charges = _charges(day, fill["ce"], fill["pe"], lots, "SELL")
    trade_id = db.melting_insert("melting_gap_trades", {
        "day": day["day"], "index_name": day["indexName"], "expiry": day["expiry"], "dte": day["dte"], "tag": tag,
        "strike": straddle["strike"], "ce_security_id": str(straddle["ceSecurityId"]), "pe_security_id": str(straddle["peSecurityId"]),
        "exchange_segment": day["exchangeSegment"], "mode": mode, "trigger": trigger, "signal": signal["kind"],
        "signal_time": int(signal["time"]), "signal_price": float(signal.get("close") or signal["price"]), "signal_vwap": round(vwap, 2),
        "lot_size": day["lotSize"], "lots": lots, "lots_open": lots, "entry_time": now, "entry_ce": fill["ce"], "entry_pe": fill["pe"],
        "entry_price": entry, "initial_sl": round(entry + stop, 2), "sl": round(entry + stop, 2), "step": float(section["stepPoints"]),
        "hits": 0, "status": "OPEN", "booked_points": 0.0, "charges": charges, "last_ce": fill["ce"], "last_pe": fill["pe"],
        "last_price": entry, "last_vwap": round(vwap, 2), "last_update": now, "best_price": entry, "worst_price": entry,
    })
    reference = float(signal.get("close") or signal["price"])
    _fill_row(trade_id, now, "ENTRY", "SELL", lots, day, fill, entry, reference, round(entry - reference, 2), None, None, charges,
              f"{signal['kind']} below VWAP {vwap:.2f}", mode)
    text = (f"#{trade_id} SELL {tag} {straddle['strike']:g} straddle × {lots} lots @ {entry:.2f} (CE {fill['ce']:.2f} + PE {fill['pe']:.2f}) "
            f"· {signal['kind']} · VWAP {vwap:.2f} · stop {entry + stop:.2f}")
    _event(day["day"], trade_id, "entry", text)
    await _notify(f"🫠 Melting {day['indexName']} {mode.upper()} {text}")
    return {"status": "entered", "tradeId": trade_id}


def _fill_row(trade_id: int, now: int, action: str, side: str, lots: int, day: dict[str, Any], fill: dict[str, Any],
              combined: float, reference: float | None, slippage: float | None, points: float | None, pnl: float | None,
              charges: float, reason: str, mode: str) -> None:
    qce, qpe = fill.get("ceQuote") or {}, fill.get("peQuote") or {}
    db.melting_insert("melting_gap_fills", {
        "trade_id": trade_id, "time": now, "action": action, "side": side, "lots": lots, "quantity": lots * int(day["lotSize"]),
        "ce_price": fill["ce"], "pe_price": fill["pe"], "combined": combined,
        "ce_bid": qce.get("bid"), "ce_ask": qce.get("ask"), "ce_ltp": qce.get("ltp"),
        "pe_bid": qpe.get("bid"), "pe_ask": qpe.get("ask"), "pe_ltp": qpe.get("ltp"),
        "reference_price": reference, "slippage": slippage, "points": points, "pnl": pnl, "charges": charges, "reason": reason,
        "mode": mode, "ce_order_id": fill.get("ceOrderId"), "pe_order_id": fill.get("peOrderId"), "order_status": fill.get("status"),
        "note": fill.get("note"),
    })


async def reduce_trade(day: dict[str, Any], trade: dict[str, Any], lots: int, action: str, reason: str,
                       reference: float | None) -> bool:
    """Buys back `lots` of the straddle. Closes the trade when nothing is left."""
    straddle = {"strike": trade["strike"], "ceSecurityId": trade["ce_security_id"], "peSecurityId": trade["pe_security_id"]}
    now = int(time.time())
    fill = await _execute(day, straddle, "BUY", lots, mode=trade["mode"], correlation=f"MS{trade['id']}{action[:5]}{now % 100000}",
                          fallback=(trade.get("last_ce"), trade.get("last_pe")))
    attention = None
    if not fill["ok"]:
        if trade["mode"] == "live":
            # a failed buy-back leg: book it at the quote so the strategy stays consistent, flag it loudly.
            for leg in fill["failedLegs"]:
                q = fill.get(f"{leg.lower()}Quote") or {}
                fill[leg.lower()] = _leg_fill(q, "BUY") or fill.get(leg.lower()) or float(trade[f"last_{leg.lower()}"] or 0)
            attention = f"{action}: {fill['note']} -- square off the {'/'.join(fill['failedLegs'])} leg manually in Dhan."
        else:
            if fill["ce"] is None:
                fill["ce"] = float(trade["last_ce"] or trade["entry_ce"])
            if fill["pe"] is None:
                fill["pe"] = float(trade["last_pe"] or trade["entry_pe"])
            fill["note"] = (fill.get("note") or "") + " -- booked at the last known prices."
    combined = round(fill["ce"] + fill["pe"], 2)
    points = round((float(trade["entry_price"]) - combined) * lots, 2)
    pnl = round(points * int(trade["lot_size"]), 2)
    charges = _charges(day, fill["ce"], fill["pe"], lots, "BUY")
    slippage = round(combined - reference, 2) if reference is not None else None
    _fill_row(trade["id"], now, action, "BUY", lots, day, fill, combined, reference, slippage, points, pnl, charges, reason, trade["mode"])
    lots_open = int(trade["lots_open"]) - lots
    values: dict[str, Any] = {
        "lots_open": lots_open, "booked_points": round(float(trade["booked_points"]) + points, 2),
        "charges": round(float(trade["charges"]) + charges, 2), "last_ce": fill["ce"], "last_pe": fill["pe"],
        "last_price": combined, "last_update": now,
    }
    if attention:
        values["needs_attention"] = ((trade.get("needs_attention") or "") + " | " + attention).strip(" |")
    if lots_open <= 0:
        values.update(status="CLOSED", exit_time=now, exit_reason=reason)
    db.melting_update_trade(trade["id"], **values)
    trade.update(values)
    net = round((values["booked_points"]) * int(trade["lot_size"]) - values["charges"], 2)
    verb = "closed" if lots_open <= 0 else f"booked {lots} lot{'s' if lots > 1 else ''}"
    text = (f"#{trade['id']} {trade['tag']} {trade['strike']:g} {verb} @ {combined:.2f} ({action}, {reason}) · "
            f"{points / lots:+.2f} pts/lot · trade net so far ₹{net:,.0f}" + (f" · stop now {trade['sl']:.2f}" if lots_open > 0 else ""))
    _event(day["day"], trade["id"], action.lower(), text)
    await _notify(f"{'✅' if points >= 0 else '🛑'} Melting {trade['index_name']} {trade['mode'].upper()} {text}")
    if attention:
        _event(day["day"], trade["id"], "live_error", attention)
        await _notify(f"🚨 Melting Straddles - Gap #{trade['id']} {attention}")
    return lots_open <= 0


async def close_trade(day: dict[str, Any], trade: dict[str, Any], reason: str, reference: float | None) -> None:
    lots = int(trade["lots_open"])
    if lots > 0:
        await reduce_trade(day, trade, lots, "EXIT", reason, reference)
    if reason == "hard stop":
        db.update_melting_day(day["day"], stops=int(day.get("stops") or 0) + 1)
        day["stops"] = int(day.get("stops") or 0) + 1


def _day_net(day_key: str) -> float:
    total = 0.0
    for t in db.list_melting_trades(day=day_key):
        live = float(t["booked_points"]) + (float(t["entry_price"]) - float(t["last_price"] or t["entry_price"])) * int(t["lots_open"])
        total += live * int(t["lot_size"]) - float(t["charges"])
    return round(total, 2)


def _check_brake(day: dict[str, Any], config: dict[str, Any]) -> None:
    if day.get("brakedAt"):
        return
    section = config[day["indexName"]]
    lots = int(config["lotsPerStraddle"])
    limit = -float(section["brakePoints"]) * int(day["lotSize"]) * lots
    reason = None
    if int(day.get("stops") or 0) >= int(config["maxStops"]):
        reason = f"{day['stops']} hard stops"
    elif _day_net(day["day"]) <= limit:
        reason = f"day net ≤ ₹{limit:,.0f} ({section['brakePoints']:g} pts × {lots} lots)"
    if reason:
        now = int(time.time())
        db.update_melting_day(day["day"], braked_at=now, brake_reason=reason)
        day.update(brakedAt=now, brakeReason=reason)
        _event(day["day"], None, "brake", f"No more entries today: {reason}.")
        asyncio.create_task(_notify(f"⛔ Melting Straddles - Gap: no more entries today -- {reason}."))


# ---------------------------------------------------------------- monitor


async def monitor_once() -> None:
    async with _lock:
        await _monitor()


async def _monitor() -> None:
    now = datetime.now(IST)
    if not market_open(now):
        return
    config = get_config()
    dhan = DhanService(get_settings())
    today = now.date()
    open_trades = db.list_melting_trades(day=None, status="OPEN")
    stale = [t for t in open_trades if t["day"] != today.isoformat()]
    for t in stale:  # never carried overnight -- shouldn't happen, but close anything left over.
        stale_row = db.get_melting_day(t["day"])
        if stale_row:
            await close_trade(_day_payload(stale_row), t, "left open from a previous day", None)
    if now.time() < dtime(9, 16):
        return
    day = await setup_day(dhan, today, config) if config["enabled"] or open_trades else None
    if day is None:
        row = db.get_melting_day(today.isoformat())
        if not row:
            return
        day = _day_payload(row)
    _runtime["day"] = day["day"]

    quotes = await _quotes(dhan, day)
    exit_at = _hhmm(config["exitTime"])
    trades = db.list_melting_trades(day=day["day"], status="OPEN")

    # live risk on every poll: time exit, hard/trailing stop, staggered booking
    for trade in trades:
        ce = (quotes.get(str(trade["ce_security_id"])) or {}).get("ltp")
        pe = (quotes.get(str(trade["pe_security_id"])) or {}).get("ltp")
        if not ce or not pe:
            continue
        live = round(ce + pe, 2)
        db.melting_update_trade(trade["id"], last_ce=ce, last_pe=pe, last_price=live, last_update=int(time.time()),
                                best_price=min(float(trade["best_price"] or live), live),
                                worst_price=max(float(trade["worst_price"] or live), live))
        trade.update(last_ce=ce, last_pe=pe, last_price=live)
        if now.time() >= exit_at:
            await close_trade(day, trade, f"{config['exitTime']} time exit", live)
            continue
        if live >= float(trade["sl"]):
            await close_trade(day, trade, "hard stop" if int(trade["hits"]) == 0 else "trailing stop", live)
            continue
        step = float(trade["step"])
        while int(trade["lots_open"]) > 1 and float(trade["entry_price"]) - live >= (int(trade["hits"]) + 1) * step:
            hits = int(trade["hits"]) + 1
            new_sl = round(float(trade["entry_price"]) - (hits - 1) * step, 2)
            db.melting_update_trade(trade["id"], hits=hits, sl=new_sl)
            trade.update(hits=hits, sl=new_sl)
            await reduce_trade(day, trade, 1, f"BOOK{hits}", f"+{hits * step:g} pts decay", live)

    _check_brake(day, config)

    # minute engine: once per completed minute
    minute = (int(time.time()) // 60) * 60 - 60
    if minute <= int(_runtime.get("lastMinute") or 0) or time.time() - (minute + 60) < 3:
        return
    series = await _series(dhan, day, today)
    _runtime.update(lastMinute=minute, series=series, seriesDay=day["day"])
    rows = []
    charts = {}
    for tag, data in series.items():
        charts[tag] = engine.analyze(data, box_percent=float(config["boxPercent"]), reversal=int(config["reversal"]),
                                     turtle_lookback=int(config["turtleLookback"]), anchor_lookback=int(config["anchorLookback"]),
                                     tall_multiple=float(config["tallMultiple"]))
        rows += [{"day": day["day"], "tag": tag, **r} for r in data[-5:]]
    db.save_melting_minutes(rows)
    _runtime["charts"] = charts
    if now.time() >= exit_at:
        return

    trades = db.list_melting_trades(day=day["day"], status="OPEN")
    for trade in trades:
        data = series.get(trade["tag"]) or []
        if not data:
            continue
        last = data[-1]
        chart = charts[trade["tag"]]
        db.melting_update_trade(trade["id"], last_vwap=last["vwap"])
        if last["vwap"] and last["combined"] >= last["vwap"]:
            await close_trade(day, trade, f"VWAP cross ({last['combined']:.2f} ≥ {last['vwap']:.2f})", last["combined"])
        elif int(trade["lots_open"]) == 1 and int(trade["hits"]) >= 1 and chart.x_starts and chart.x_starts[-1] == last["time"] \
                and last["time"] > int(trade["entry_time"]):
            await close_trade(day, trade, "runner: P&F up-reversal", last["combined"])

    _check_brake(day, config)
    if not config["enabled"] or day.get("brakedAt"):
        return
    if not (_hhmm(config["entryStart"]) <= now.time() < _hhmm(config["entryEnd"])):
        return
    open_now = db.list_melting_trades(day=day["day"], status="OPEN")
    taken = {(t["tag"], int(t["signal_time"])) for t in db.list_melting_trades(day=day["day"])}
    section = config[day["indexName"]]
    max_age = int(config["signalMaxAgeMinutes"]) * 60
    for tag in TAGS:
        if len(open_now) >= int(config["maxOpen"]):
            break
        if tag not in charts or any(t["tag"] == tag for t in open_now):
            continue
        data = series[tag]
        last = data[-1]
        fresh = [s for s in charts[tag].signals if s["kind"] in config["patternList"] and s["time"] >= minute - max_age + 60
                 and (tag, int(s["time"])) not in taken]
        if not fresh or not last["vwap"]:
            continue
        signal = {**fresh[-1], "close": last["combined"]}
        gap = last["vwap"] - last["combined"]
        if gap <= 0 or gap > float(section["stopPoints"]):
            if gap > 0:
                _event(day["day"], None, "skip", f"{tag} {signal['kind']} at {last['combined']:.2f} skipped -- "
                       f"{gap:.2f} below VWAP (proximity limit {section['stopPoints']:g})")
            taken.add((tag, int(signal["time"])))
            continue
        result = await open_trade(day, tag, signal, last["vwap"], config)
        if result["status"] == "entered":
            open_now = db.list_melting_trades(day=day["day"], status="OPEN")


async def close_now(trade_id: int) -> dict[str, Any]:
    async with _lock:
        trade = db.get_melting_trade(trade_id)
        if not trade or trade["status"] != "OPEN":
            return {"status": "blocked", "message": "Trade is not open."}
        row = db.get_melting_day(trade["day"])
        if not row:
            return {"status": "blocked", "message": "Day record missing."}
        await close_trade(_day_payload(row), trade, "closed manually", trade.get("last_price"))
    return {"status": "closed"}


async def square_off_all() -> dict[str, Any]:
    closed = 0
    for trade in db.list_melting_trades(status="OPEN"):
        result = await close_now(int(trade["id"]))
        closed += result["status"] == "closed"
    return {"status": "ok", "closed": closed}


async def enter_now(tag: str) -> dict[str, Any]:
    """Manual entry on one straddle at the current price (no signal needed)."""
    async with _lock:
        config = get_config()
        row = db.get_melting_day(datetime.now(IST).date().isoformat())
        if not row:
            return {"status": "blocked", "message": "No straddles set up today (not a trading day, or before 09:16)."}
        day = _day_payload(row)
        if tag not in day["straddles"]:
            return {"status": "blocked", "message": f"No {tag} straddle today."}
        open_now = db.list_melting_trades(day=day["day"], status="OPEN")
        if any(t["tag"] == tag for t in open_now):
            return {"status": "blocked", "message": f"{tag} straddle is already open."}
        if len(open_now) >= int(config["maxOpen"]):
            return {"status": "blocked", "message": f"{config['maxOpen']} straddles already open."}
        data = (_runtime.get("series") or {}).get(tag) or []
        vwap = data[-1]["vwap"] if data and data[-1]["vwap"] else 0.0
        price = data[-1]["combined"] if data else 0.0
        signal = {"kind": "MANUAL", "time": int(time.time()), "price": price, "close": price}
        return await open_trade(day, tag, signal, vwap, config, trigger="manual")


# ---------------------------------------------------------------- reporting


def _camel(row: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for key, value in row.items():
        parts = key.split("_")
        out[parts[0] + "".join(p.title() for p in parts[1:])] = value
    return out


def summarize(trade: dict[str, Any], fills: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    t = _camel(trade)
    lot_size = int(t["lotSize"])
    last = float(t["lastPrice"] or t["entryPrice"])
    unrealized_points = (float(t["entryPrice"]) - last) * int(t["lotsOpen"]) if t["status"] == "OPEN" else 0.0
    t["realizedPnl"] = round(float(t["bookedPoints"]) * lot_size, 2)
    t["unrealizedPnl"] = round(unrealized_points * lot_size, 2)
    t["grossPnl"] = round(t["realizedPnl"] + t["unrealizedPnl"], 2)
    t["netPnl"] = round(t["grossPnl"] - float(t["charges"]), 2)
    t["pointsPerLot"] = round((float(t["bookedPoints"]) + unrealized_points) / int(t["lots"]), 2)
    t["premiumCollected"] = round(float(t["entryPrice"]) * int(t["lots"]) * lot_size, 2)
    t["decay"] = round(float(t["entryPrice"]) - last, 2)
    t["nextTarget"] = (round(float(t["entryPrice"]) - (int(t["hits"]) + 1) * float(t["step"]), 2)
                       if t["status"] == "OPEN" and int(t["lotsOpen"]) > 1 else None)
    t["mfe"] = round(float(t["entryPrice"]) - float(t["bestPrice"] or t["entryPrice"]), 2)
    t["mae"] = round(float(t["entryPrice"]) - float(t["worstPrice"] or t["entryPrice"]), 2)
    end = t["exitTime"] or int(time.time())
    t["minutesHeld"] = round((end - int(t["entryTime"])) / 60, 1)
    if fills is not None:
        t["fills"] = [_camel(f) for f in fills]
    return t


def list_trades(limit: int = 500) -> list[dict[str, Any]]:
    trades = db.list_melting_trades(limit=limit)
    fills = db.list_melting_fills([int(t["id"]) for t in trades])
    by_trade: dict[int, list[dict[str, Any]]] = {}
    for f in fills:
        by_trade.setdefault(int(f["trade_id"]), []).append(f)
    return [summarize(t, by_trade.get(int(t["id"]), [])) for t in trades]


def trade_detail(trade_id: int) -> dict[str, Any] | None:
    trade = db.get_melting_trade(trade_id)
    if not trade:
        return None
    out = summarize(trade, db.list_melting_fills([trade_id]))
    out["events"] = [_camel(e) for e in db.list_melting_events(trade_id=trade_id)]
    minutes = [m for m in db.list_melting_minutes(trade["day"]) if m["tag"] == trade["tag"]]
    out["minutes"] = [{"time": m["time"], "combined": m["combined"], "vwap": m["vwap"]} for m in minutes]
    return out


def days_summary() -> list[dict[str, Any]]:
    trades = db.list_melting_trades(limit=5000)
    by_day: dict[str, list[dict[str, Any]]] = {}
    for t in trades:
        by_day.setdefault(t["day"], []).append(summarize(t))
    out = []
    for row in db.list_melting_days():
        ts = by_day.get(row["day"], [])
        out.append({
            **_day_payload(row),
            "trades": len(ts), "wins": sum(1 for t in ts if t["netPnl"] > 0),
            "grossPnl": round(sum(t["grossPnl"] for t in ts), 2), "charges": round(sum(float(t["charges"]) for t in ts), 2),
            "netPnl": round(sum(t["netPnl"] for t in ts), 2), "points": round(sum(t["pointsPerLot"] for t in ts), 2),
        })
    return out


async def state() -> dict[str, Any]:
    config = get_config()
    now = datetime.now(IST)
    today = now.date()
    row = db.get_melting_day(today.isoformat())
    day = _day_payload(row) if row else None
    plan_text = None
    if not day:
        try:
            name, expiry, plan_text = await pick_index(DhanService(get_settings()), today, config)
        except Exception as exc:
            plan_text = f"Dhan expiry list unavailable: {exc}"
    straddles = []
    if day:
        series = _runtime.get("series") if _runtime.get("seriesDay") == day["day"] else None
        if not series:
            series = {}
            for m in db.list_melting_minutes(day["day"]):
                series.setdefault(m["tag"], []).append({"time": m["time"], "ce": m["ce"], "pe": m["pe"], "combined": m["combined"], "vwap": m["vwap"]})
        quotes = _runtime.get("quotes") or {}
        for tag in TAGS:
            s = day["straddles"].get(tag)
            if not s:
                continue
            data = series.get(tag) or []
            chart = engine.analyze(data, box_percent=float(config["boxPercent"]), reversal=int(config["reversal"]),
                                   turtle_lookback=int(config["turtleLookback"]), anchor_lookback=int(config["anchorLookback"]),
                                   tall_multiple=float(config["tallMultiple"])) if data else None
            qce, qpe = quotes.get(str(s["ceSecurityId"])) or {}, quotes.get(str(s["peSecurityId"])) or {}
            last = data[-1] if data else None
            atp = (qce.get("atp") or 0) + (qpe.get("atp") or 0) if qce.get("atp") and qpe.get("atp") else None
            straddles.append({
                "tag": tag, "strike": s["strike"], "ceSecurityId": s["ceSecurityId"], "peSecurityId": s["peSecurityId"],
                "combined": last["combined"] if last else None, "vwap": last["vwap"] if last else None,
                "lastMinute": last["time"] if last else None,
                "live": {"ce": qce, "pe": qpe, "combined": round(qce["ltp"] + qpe["ltp"], 2) if qce.get("ltp") and qpe.get("ltp") else None,
                         "exchangeVwap": round(atp, 2) if atp else None},
                "series": [{"time": r["time"], "combined": r["combined"], "vwap": r["vwap"]} for r in data],
                "columns": chart.payload(60) if chart else [],
                "boxPoints": round((chart.price(1) - 1) * (last["combined"] if last else 0), 2) if chart else None,
                "signals": [s2 for s2 in (chart.signals if chart else []) if s2["kind"] in config["patternList"]],
            })
    today_trades = [summarize(t, db.list_melting_fills([int(t["id"])])) for t in db.list_melting_trades(day=today.isoformat())]
    return {
        "config": config,
        "now": int(time.time()),
        "marketOpen": market_open(now),
        "mode": _mode(config),
        "day": day,
        "plan": plan_text,
        "straddles": straddles,
        "todayTrades": today_trades,
        "openTrades": [t for t in today_trades if t["status"] == "OPEN"],
        "dayNet": _day_net(today.isoformat()) if day else 0.0,
        "events": [_camel(e) for e in db.list_melting_events(day=today.isoformat(), limit=200)],
        "attention": [t for t in today_trades if t.get("needsAttention")],
    }


def _event(day: str, trade_id: int | None, kind: str, text: str) -> None:
    db.melting_insert("melting_gap_events", {"day": day, "trade_id": trade_id, "time": int(time.time()), "kind": kind, "text": text})


async def _notify(text: str) -> None:
    try:
        await TelegramNotifier().send(text)
    except Exception:
        logger.warning("melting_gap: telegram send failed")


def start_melting_gap_task() -> asyncio.Task | None:
    if not get_settings().melting_gap_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_melting_gap_task(task: asyncio.Task | None) -> None:
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
            logger.exception("melting_gap: monitor iteration failed")
        await asyncio.sleep(POLL_SECONDS)
