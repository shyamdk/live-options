"""Calm Strangle -- intraday NIFTY short strangle sold only when the market
has settled (docs/strategies/calm-strangle.md).

Every completed minute (10:00-14:30, not on expiry day or the trading day before it): if NIFTY's range
over the last 15 one-minute closes is <= 15% of the ATM straddle, sell the
CE at the first strike >= spot + 1.0 x straddle and the PE at the first
strike <= spot - 1.0 x straddle (credit >= 6 pts).

While open (checked every poll on live quotes):
  MOVE STOP  NIFTY moves 0.6 x straddle (at entry) from the entry spot
  BACKSTOP   combined premium >= credit x 2.5
  TIME       15:15
No profit target. After a stop, the next entry needs the calm test to pass
again. Max 3 entries / 2 stops a day.

Paper: sell at bid, buy at ask (LTP if no quote), Dhan charge model. Live
(mode=live AND CALM_STRANGLE_LIVE_ORDER_ENABLED AND LIVE_ORDER_ENABLED):
INTRADAY market orders for both legs, fills read back from Dhan.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime, time as dtime
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.db import sqlite as db
from app.services import varaha
from app.services import varaha_engine as ve
from app.services.charges import option_order_charges
from app.services.dhan import DhanService
from app.services.orders import DhanOrderService
from app.services.telegram import TelegramNotifier

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
LOT_SIZE = 65
OPTION_SEGMENT = "NSE_FNO"
INDEX_SEGMENT = "IDX_I"
POLL_OFFSETS = (2, 17, 32, 47)
QUOTE_MAX_AGE = 2.0

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "mode": "paper",
    "lots": 5,
    "calmPercent": 15.0,
    "calmWindow": 15,
    "strikeMultiple": 1.0,
    "stopMultiple": 0.6,
    "backstopPercent": 150.0,
    "minCredit": 6.0,
    "entryStart": "10:00",
    "lastEntry": "14:30",
    "exitTime": "15:15",
    "maxEntries": 3,
    "maxStops": 2,
    "skipExpiryDay": True,
    # 16 Oct 2026 backtest: the trading day before expiry produced every loss
    # over Rs6k; skipping it kept the profit (Rs93k vs Rs92.6k) and cut the
    # worst trade from -Rs11.6k to -Rs3.8k (-Rs517 with the 10:00 start).
    "skipDayBeforeExpiry": True,
    # book the trade as soon as the premium reaches what it should be worth at
    # the exit time if NIFTY stayed put, then take no more entries that day
    "earlyExit": True,
    "stopAfterEarlyExit": True,
    # Europe-open guard (optional): if still open at this time and in profit,
    # book it before the European open swing, then no more entries that day.
    "europeGuard": False,
    "europeGuardTime": "12:15",
}

_lock = asyncio.Lock()
_expiry_cache: dict[str, Any] = {"at": 0.0, "expiries": []}
_runtime: dict[str, Any] = {"day": None, "minute": 0, "snapshot": None, "spot": []}


# ---------------------------------------------------------------- config


def get_config() -> dict[str, Any]:
    config: dict[str, Any] = {}
    for key, default in DEFAULTS.items():
        raw = db.get_calm_setting(key)
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
    settings = get_settings()
    config["lotSize"] = LOT_SIZE
    config["quantity"] = int(config["lots"]) * LOT_SIZE
    config["liveOrdersAllowed"] = bool(settings.calm_strangle_live_order_enabled and settings.live_order_enabled)
    return config


def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if key not in DEFAULTS or value is None:
            continue
        if key == "mode":
            if value not in ("paper", "live"):
                raise ValueError("mode must be paper or live")
            settings = get_settings()
            if value == "live" and not (settings.calm_strangle_live_order_enabled and settings.live_order_enabled):
                raise ValueError("Live orders are locked on the server (CALM_STRANGLE_LIVE_ORDER_ENABLED=false).")
        if key in ("entryStart", "lastEntry", "exitTime", "europeGuardTime"):
            datetime.strptime(str(value), "%H:%M")
        elif key not in ("enabled", "mode", "skipExpiryDay", "skipDayBeforeExpiry", "earlyExit", "stopAfterEarlyExit", "europeGuard") and float(value) <= 0:
            raise ValueError(f"{key} must be positive")
        default = DEFAULTS[key]
        db.set_calm_setting(key, ("1" if value else "0") if isinstance(default, bool) else str(value))
    return get_config()


def _hhmm(value: str) -> dtime:
    return datetime.strptime(value, "%H:%M").time()


def _mode(config: dict[str, Any]) -> str:
    return "live" if config["mode"] == "live" and config["liveOrdersAllowed"] else "paper"


def market_open(now: datetime) -> bool:
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)


# ---------------------------------------------------------------- market data


async def _expiry(dhan: DhanService, today: date) -> date | None:
    if not _expiry_cache["expiries"] or time.monotonic() - _expiry_cache["at"] > 1800:
        raw = await dhan.expiry_list(get_settings().dhan_nifty_security_id, INDEX_SEGMENT)
        _expiry_cache.update(at=time.monotonic(), expiries=sorted(date.fromisoformat(x) for x in raw))
    return next((d for d in _expiry_cache["expiries"] if d >= today), None)


async def _spot(dhan: DhanService) -> float | None:
    scrip = get_settings().dhan_nifty_security_id
    data = await dhan.market_quotes_by_segment({INDEX_SEGMENT: [int(scrip)]}, max_age_seconds=QUOTE_MAX_AGE)
    return varaha._number(((data.get(INDEX_SEGMENT) or {}).get(str(scrip)) or {}).get("last_price"))


async def _leg_quotes(dhan: DhanService, ids: list[str]) -> dict[str, dict[str, Any]]:
    data = await dhan.market_quotes_by_segment({OPTION_SEGMENT: [int(x) for x in ids]}, max_age_seconds=QUOTE_MAX_AGE)
    out = {}
    for sec, q in (data.get(OPTION_SEGMENT) or {}).items():
        depth = (q or {}).get("depth") or {}
        buy = (depth.get("buy") or [{}])[0] or {}
        sell = (depth.get("sell") or [{}])[0] or {}
        out[str(sec)] = {"ltp": varaha._number(q.get("last_price")), "bid": varaha._number(buy.get("price")) or None,
                         "ask": varaha._number(sell.get("price")) or None}
    return out


async def _spot_and_legs(dhan: DhanService, ids: list[str]) -> tuple[float | None, dict[str, dict[str, Any]]]:
    """NIFTY spot and the legs' quotes in ONE quote request (rate limit)."""
    scrip = get_settings().dhan_nifty_security_id
    data = await dhan.market_quotes_by_segment({INDEX_SEGMENT: [int(scrip)], OPTION_SEGMENT: [int(x) for x in ids]},
                                               max_age_seconds=QUOTE_MAX_AGE)
    spot = varaha._number(((data.get(INDEX_SEGMENT) or {}).get(str(scrip)) or {}).get("last_price"))
    out = {}
    for sec, q in (data.get(OPTION_SEGMENT) or {}).items():
        depth = (q or {}).get("depth") or {}
        buy = (depth.get("buy") or [{}])[0] or {}
        sell = (depth.get("sell") or [{}])[0] or {}
        out[str(sec)] = {"ltp": varaha._number(q.get("last_price")), "bid": varaha._number(buy.get("price")) or None,
                         "ask": varaha._number(sell.get("price")) or None}
    return spot, out


async def _spot_minutes(dhan: DhanService, today: date) -> list[dict[str, Any]]:
    scrip = str(get_settings().dhan_nifty_security_id)
    candles = await dhan.intraday_candles(scrip, INDEX_SEGMENT, "INDEX", "1", today.isoformat(), today.isoformat())
    cutoff = int(time.time()) - 60
    return sorted(({"time": int(c["time"]), "close": float(c["close"])} for c in candles if int(c["time"]) <= cutoff), key=lambda c: c["time"])


async def snapshot(dhan: DhanService, config: dict[str, Any], today: date) -> dict[str, Any]:
    """The calm test and the strangle it would sell right now."""
    expiry = await _expiry(dhan, today)
    if not expiry:
        return {"error": "No NIFTY expiry listed."}
    minutes = await _spot_minutes(dhan, today)
    _runtime["spot"] = minutes
    chain = await dhan.option_chain(get_settings().dhan_nifty_security_id, INDEX_SEGMENT, expiry.isoformat())
    spot = varaha._number(chain.get("last_price"))
    rows: dict[float, dict[str, Any]] = {}
    for key, sides in (chain.get("oc") or {}).items():
        strike = varaha._number(key)
        if strike is not None and isinstance(sides, dict):
            rows[float(strike)] = {"CE": varaha._quote(sides.get("ce")), "PE": varaha._quote(sides.get("pe"))}
    both = [k for k, r in rows.items() if r["CE"] and r["PE"] and r["CE"]["ltp"] and r["PE"]["ltp"]]
    if not spot or not both:
        return {"error": "NIFTY option chain unavailable.", "expiry": expiry.isoformat()}
    atm = min(both, key=lambda k: abs(k - spot))
    straddle = rows[atm]["CE"]["ltp"] + rows[atm]["PE"]["ltp"]
    window = [m["close"] for m in minutes[-int(config["calmWindow"]):]]
    calm_range = (max(window) - min(window)) if len(window) >= int(config["calmWindow"]) else None
    threshold = straddle * float(config["calmPercent"]) / 100
    distance = straddle * float(config["strikeMultiple"])
    ce_k = min((k for k, r in rows.items() if r["CE"] and k >= spot + distance), default=None)
    pe_k = max((k for k, r in rows.items() if r["PE"] and k <= spot - distance), default=None)
    legs = {}
    for side, k in (("CE", ce_k), ("PE", pe_k)):
        if k is not None:
            q = rows[k][side]
            legs[side] = {"strike": k, "securityId": q["securityId"], "ltp": q["ltp"], "bid": q["bid"], "ask": q["ask"],
                          "delta": q["delta"], "distancePercent": round(abs(k - spot) / spot * 100, 2)}
    credit = sum((leg["bid"] or leg["ltp"] or 0) for leg in legs.values()) if len(legs) == 2 else None
    return {
        "time": int(time.time()), "expiry": expiry.isoformat(), "dte": (expiry - today).days,
        "tradingDte": varaha._trading_days_until(today, expiry), "spot": spot, "atmStrike": atm,
        "straddle": round(straddle, 2), "calmRange": round(calm_range, 2) if calm_range is not None else None,
        "calmThreshold": round(threshold, 2), "calm": calm_range is not None and calm_range <= threshold,
        "windowMinutes": len(window), "legs": legs, "credit": round(credit, 2) if credit else None,
        "stopBand": round(straddle * float(config["stopMultiple"]), 2),
    }


# ---------------------------------------------------------------- execution


def _fill(q: dict[str, Any] | None, side: str) -> float | None:
    if not q:
        return None
    bid, ask, ltp = q.get("bid"), q.get("ask"), q.get("ltp")
    if bid and ask and ask >= bid > 0:
        return float(ask) if side == "BUY" else float(bid)
    return float(ltp) if ltp else None


def _charges(price: float, qty: int, side: str) -> float:
    return float(option_order_charges(premium=max(price, 0.05), quantity=qty, side=side, exchange_segment=OPTION_SEGMENT)["total"])


async def _execute(security_id: str, side: str, qty: int, mode: str, quote: dict[str, Any] | None, tag: str) -> dict[str, Any]:
    price = _fill(quote, side)
    if mode != "live":
        return {"ok": price is not None, "price": price, "orderId": None, "note": None if price else "no quote"}
    orders = DhanOrderService(get_settings())
    result: dict[str, Any] = {}
    for attempt in range(3):
        result = await orders.place_market_order(
            transaction_type=side, exchange_segment=OPTION_SEGMENT, security_id=security_id, quantity=qty,
            correlation_id=f"CS{tag}{attempt}{int(time.time()) % 100000}", product_type="INTRADAY",
        )
        if result.get("status") == "sent":
            break
        await asyncio.sleep(0.6)
    if result.get("status") != "sent":
        return {"ok": False, "price": price, "orderId": None, "note": f"{result.get('status')}: {result.get('message')}"}
    order = result.get("order") or {}
    order_id = str(order.get("orderId") or (order.get("data") or {}).get("orderId") or "") or None
    traded = None
    for _ in range(8):
        await asyncio.sleep(1)
        info = await orders.get_order(order_id) if order_id else None
        status = str((info or {}).get("orderStatus") or "").upper()
        traded = varaha._number((info or {}).get("averageTradedPrice"))
        if status in ("TRADED", "PART_TRADED") and traded:
            break
    return {"ok": True, "price": traded or price, "orderId": order_id, "note": None if traded else "fill price not confirmed -- quote used"}


async def _enter(dhan: DhanService, config: dict[str, Any], snap: dict[str, Any], trigger: str) -> dict[str, Any]:
    mode = _mode(config)
    qty = int(config["quantity"])
    legs = snap["legs"]
    quotes = await _leg_quotes(dhan, [legs["CE"]["securityId"], legs["PE"]["securityId"]])
    fills = {}
    for side in ("CE", "PE"):
        q = quotes.get(str(legs[side]["securityId"])) or legs[side]
        fills[side] = (q, await _execute(legs[side]["securityId"], "SELL", qty, mode, q, f"E{side}"))
    if not all(r["ok"] for _, r in fills.values()):
        bad = [s for s, (_, r) in fills.items() if not r["ok"]]
        if mode == "live":
            for side, (q, r) in fills.items():
                if r["ok"]:  # never leave one naked leg
                    await _execute(legs[side]["securityId"], "BUY", qty, mode, q, f"U{side}")
            await _notify(f"🚨 Calm Strangle: entry failed on {bad} -- the other leg was bought back. Check Dhan positions.")
        _event(None, "entry_failed", f"Entry failed ({', '.join(bad)}): " + "; ".join(str(r['note']) for _, r in fills.values()))
        return {"status": "failed"}
    now = int(time.time())
    ce, pe = float(fills["CE"][1]["price"]), float(fills["PE"][1]["price"])
    credit = round(ce + pe, 2)
    spot = float(snap["spot"])
    band = float(snap["straddle"]) * float(config["stopMultiple"])
    today = datetime.now(IST).date()
    trade_id = db.calm_insert("calm_strangle_trades", {
        "day": today.isoformat(), "expiry": snap["expiry"], "dte": snap["dte"], "mode": mode, "trigger": trigger, "entry_time": now,
        "entry_spot": spot, "straddle": snap["straddle"], "calm_range": snap["calmRange"], "atm_strike": snap["atmStrike"],
        "ce_strike": legs["CE"]["strike"], "pe_strike": legs["PE"]["strike"], "ce_security_id": str(legs["CE"]["securityId"]),
        "pe_security_id": str(legs["PE"]["securityId"]), "lots": config["lots"], "lot_size": LOT_SIZE, "entry_ce": ce, "entry_pe": pe,
        "credit": credit, "entry_quotes": json.dumps({s: q for s, (q, _) in fills.items()}),
        "stop_low": round(spot - band, 2), "stop_high": round(spot + band, 2),
        "backstop": round(credit * (1 + float(config["backstopPercent"]) / 100), 2), "status": "OPEN",
        "charges": round(_charges(ce, qty, "SELL") + _charges(pe, qty, "SELL"), 2), "last_ce": ce, "last_pe": pe,
        "last_spot": spot, "last_update": now, "best": credit, "worst": credit,
        "order_ids": json.dumps({s: r["orderId"] for s, (_, r) in fills.items()}),
    })
    text = (f"#{trade_id} SELL {legs['CE']['strike']:,.0f} CE @ {ce:.2f} + {legs['PE']['strike']:,.0f} PE @ {pe:.2f} = {credit:.2f} "
            f"× {config['lots']} lots · NIFTY {spot:,.2f} calm ({snap['calmRange']:.1f} ≤ {snap['calmThreshold']:.1f}) · "
            f"stop if NIFTY < {spot - band:,.0f} or > {spot + band:,.0f}")
    early = _early_target(snap["expiry"], now, spot, legs["CE"]["strike"], ce, legs["PE"]["strike"], pe, config["exitTime"])
    db.calm_update_trade(trade_id, early_target=early)
    db.add_calm_mark(trade_id, now, credit, spot)
    _event(trade_id, "entry", text)
    await _notify(f"🧘 Calm Strangle {mode.upper()} {text}")
    return {"status": "entered", "tradeId": trade_id}


async def _exit(dhan: DhanService, trade: dict[str, Any], reason: str, spot: float | None) -> None:
    qty = int(trade["lots"]) * int(trade["lot_size"])
    quotes = await _leg_quotes(dhan, [trade["ce_security_id"], trade["pe_security_id"]])
    out = {}
    for side in ("CE", "PE"):
        q = quotes.get(str(trade[f"{side.lower()}_security_id"])) or {"ltp": trade[f"last_{side.lower()}"]}
        r = await _execute(trade[f"{side.lower()}_security_id"], "BUY", qty, trade["mode"], q, f"X{side}")
        price = r["price"] if r["price"] is not None else float(trade[f"last_{side.lower()}"] or 0)
        if not r["ok"] and trade["mode"] == "live":
            await _notify(f"🚨 Calm Strangle #{trade['id']}: buy-back of the {side} failed ({r['note']}) -- square it off manually in Dhan.")
        out[side] = (q, r, price)
    now = int(time.time())
    ce, pe = out["CE"][2], out["PE"][2]
    charges = float(trade["charges"]) + _charges(ce, qty, "BUY") + _charges(pe, qty, "BUY")
    order_ids = json.loads(trade["order_ids"] or "{}")
    order_ids.update({f"exit{s}": r["orderId"] for s, (_, r, _) in out.items()})
    db.calm_update_trade(trade["id"], status="CLOSED", exit_time=now, exit_reason=reason, exit_ce=ce, exit_pe=pe, exit_spot=spot,
                         exit_quotes=json.dumps({s: q for s, (q, _, _) in out.items()}), charges=round(charges, 2),
                         last_ce=ce, last_pe=pe, order_ids=json.dumps(order_ids))
    db.add_calm_mark(trade["id"], now, round(ce + pe, 2), spot)
    pts = float(trade["credit"]) - (ce + pe)
    net = pts * qty - charges
    text = f"#{trade['id']} closed ({reason}) @ {ce + pe:.2f} (CE {ce:.2f} + PE {pe:.2f}) · {pts:+.2f} pts · net ₹{net:,.0f}"
    _event(trade["id"], "exit", text)
    await _notify(f"{'✅' if net >= 0 else '🛑'} Calm Strangle {text}")


async def monitor_once() -> None:
    async with _lock:
        await _monitor()


async def _monitor() -> None:
    now = datetime.now(IST)
    today = now.date()
    dhan = DhanService(get_settings())
    open_trades = db.list_calm_trades(status="OPEN")
    for t in open_trades:  # never carried overnight
        if t["day"] != today.isoformat():
            await _exit(dhan, t, "left open from a previous day", None)
    if not market_open(now):
        return
    config = get_config()
    open_trades = db.list_calm_trades(day=today.isoformat(), status="OPEN")

    # refresh the calm test once per completed minute (also while a position is open, for the page)
    minute = (int(time.time()) // 60) * 60 - 60
    fresh_minute = minute > int(_runtime.get("minute") or 0)
    if fresh_minute:
        try:
            snap = await snapshot(dhan, config, today)
            _runtime.update(minute=minute, snapshot=snap, day=today.isoformat())
        except Exception as exc:
            logger.warning("calm_strangle: snapshot failed: %s", exc)
            fresh_minute = False

    if open_trades:
        trade = open_trades[0]
        spot, quotes = await _spot_and_legs(dhan, [trade["ce_security_id"], trade["pe_security_id"]])
        ce = (quotes.get(str(trade["ce_security_id"])) or {}).get("ltp")
        pe = (quotes.get(str(trade["pe_security_id"])) or {}).get("ltp")
        if ce and pe:
            comb = ce + pe
            db.calm_update_trade(trade["id"], last_ce=ce, last_pe=pe, last_spot=spot, last_update=int(time.time()),
                                 best=min(float(trade["best"] or comb), comb), worst=max(float(trade["worst"] or comb), comb))
            db.add_calm_mark(trade["id"], int(time.time()), round(comb, 2), spot)
            trade.update(last_ce=ce, last_pe=pe)
        reason = None
        if now.time() >= _hhmm(config["exitTime"]):
            reason = f"{config['exitTime']} time exit"
        elif spot and (spot <= float(trade["stop_low"]) or spot >= float(trade["stop_high"])):
            reason = f"NIFTY move stop ({spot:,.2f})"
        elif ce and pe and ce + pe >= float(trade["backstop"]):
            reason = f"premium backstop ({ce + pe:.2f})"
        elif (config["europeGuard"] and ce and pe and _hhmm(config["europeGuardTime"]) <= now.time() < dtime(13, 0)
              and ce + pe < float(trade["credit"])):
            reason = f"Europe-open guard: booked in profit at {config['europeGuardTime']} ({ce + pe:.2f} < {float(trade['credit']):.2f})"
        elif config["earlyExit"] and ce and pe:
            early = trade.get("early_target")
            if early is None:  # trades opened before this rule existed
                early = _early_target(trade["expiry"], int(trade["entry_time"]), float(trade["entry_spot"]), float(trade["ce_strike"]),
                                      float(trade["entry_ce"]), float(trade["pe_strike"]), float(trade["entry_pe"]), config["exitTime"])
                db.calm_update_trade(trade["id"], early_target=early)
            if early is not None and ce + pe <= early:
                reason = f"{config['exitTime']} target reached early ({ce + pe:.2f} ≤ {early:.2f})"
        if reason:
            await _exit(dhan, trade, reason, spot)
        return  # one position at a time

    if not fresh_minute:
        return
    snap = _runtime["snapshot"]
    if snap.get("error") or not config["enabled"]:
        return
    if not (_hhmm(config["entryStart"]) <= now.time() < _hhmm(config["lastEntry"])):
        return
    if config["skipExpiryDay"] and snap["dte"] == 0:
        return
    if config["skipDayBeforeExpiry"] and snap.get("tradingDte") == 1:
        return
    today_trades = db.list_calm_trades(day=today.isoformat())
    stops = sum(1 for t in today_trades if t["exit_reason"] and ("stop" in t["exit_reason"] or "backstop" in t["exit_reason"]))
    if len(today_trades) >= int(config["maxEntries"]) or stops >= int(config["maxStops"]):
        return
    if config["stopAfterEarlyExit"] and any("reached early" in (t["exit_reason"] or "") for t in today_trades):
        return
    if any("Europe-open guard" in (t["exit_reason"] or "") for t in today_trades):
        return
    if not snap["calm"] or len(snap["legs"]) < 2 or not snap["credit"] or snap["credit"] < float(config["minCredit"]):
        return
    await _enter(dhan, config, snap, "calm")


async def enter_now() -> dict[str, Any]:
    async with _lock:
        if db.list_calm_trades(day=datetime.now(IST).date().isoformat(), status="OPEN"):
            return {"status": "blocked", "message": "A strangle is already open."}
        dhan = DhanService(get_settings())
        config = get_config()
        snap = await snapshot(dhan, config, datetime.now(IST).date())
        if snap.get("error") or len(snap.get("legs") or {}) < 2:
            return {"status": "blocked", "message": snap.get("error") or "Strikes unavailable."}
        return await _enter(dhan, config, snap, "manual")


async def close_now(trade_id: int) -> dict[str, Any]:
    async with _lock:
        trade = next((t for t in db.list_calm_trades(status="OPEN") if t["id"] == trade_id), None)
        if not trade:
            return {"status": "blocked", "message": "Trade is not open."}
        dhan = DhanService(get_settings())
        await _exit(dhan, trade, "closed manually", await _spot(dhan))
    return {"status": "closed"}


# ---------------------------------------------------------------- reporting


def summarize(t: dict[str, Any]) -> dict[str, Any]:
    qty = int(t["lots"]) * int(t["lot_size"])
    current = (float(t["exit_ce"]) + float(t["exit_pe"])) if t["status"] == "CLOSED" and t["exit_ce"] is not None else (
        float(t["last_ce"] or t["entry_ce"]) + float(t["last_pe"] or t["entry_pe"]))
    points = float(t["credit"]) - current
    gross = points * qty
    out = {
        "id": t["id"], "day": t["day"], "expiry": t["expiry"], "dte": t["dte"], "mode": t["mode"], "trigger": t["trigger"],
        "entryTime": t["entry_time"], "entrySpot": t["entry_spot"], "straddle": t["straddle"], "calmRange": t["calm_range"],
        "atmStrike": t["atm_strike"], "ceStrike": t["ce_strike"], "peStrike": t["pe_strike"], "lots": t["lots"], "lotSize": t["lot_size"],
        "entryCe": t["entry_ce"], "entryPe": t["entry_pe"], "credit": t["credit"], "stopLow": t["stop_low"], "stopHigh": t["stop_high"],
        "backstop": t["backstop"], "status": t["status"], "exitTime": t["exit_time"], "exitReason": t["exit_reason"],
        "exitCe": t["exit_ce"], "exitPe": t["exit_pe"], "exitSpot": t["exit_spot"], "lastCe": t["last_ce"], "lastPe": t["last_pe"],
        "lastSpot": t["last_spot"], "lastUpdate": t["last_update"], "best": t["best"], "worst": t["worst"],
        "entryQuotes": json.loads(t["entry_quotes"] or "{}"), "exitQuotes": json.loads(t["exit_quotes"] or "{}"),
        "orderIds": json.loads(t["order_ids"] or "{}"), "notes": t["notes"], "earlyTarget": t.get("early_target"),
        "current": round(current, 2), "points": round(points, 2), "grossPnl": round(gross, 2), "charges": t["charges"],
        "netPnl": round(gross - float(t["charges"]), 2), "premiumCollected": round(float(t["credit"]) * qty, 2),
        "minutesHeld": round(((t["exit_time"] or int(time.time())) - int(t["entry_time"])) / 60, 1),
    }
    return out


def _early_target(expiry: str, entry_epoch: int, spot: float, ce_strike: float, ce_price: float, pe_strike: float,
                  pe_price: float, exit_time: str) -> float | None:
    """What the strangle should be worth at the exit time if NIFTY stays at
    the entry spot (Black-Scholes with each leg's implied vol at entry)."""
    entry_at = datetime.fromtimestamp(entry_epoch, IST)
    years_entry = _years(expiry, entry_at)
    exit_at = datetime.combine(entry_at.date(), _hhmm(exit_time), tzinfo=IST)
    years_exit = _years(expiry, exit_at)
    if years_entry <= 0:
        return None
    value = 0.0
    for strike, price, is_call in ((ce_strike, ce_price, True), (pe_strike, pe_price, False)):
        iv = _implied_vol(price, spot, strike, years_entry, is_call)
        value += ve.bs_price(spot, strike, years_exit, iv, is_call)
    return round(value, 2)


def _years(expiry: str, at: datetime) -> float:
    close = datetime.combine(date.fromisoformat(expiry), dtime(15, 30), tzinfo=IST)
    return max((close - at).total_seconds(), 0.0) / (365 * 24 * 3600)


def _implied_vol(price: float, spot: float, strike: float, years: float, is_call: bool) -> float:
    lo, hi = 0.01, 3.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if ve.bs_price(spot, strike, years, mid, is_call) > price:
            hi = mid
        else:
            lo = mid
    return round((lo + hi) / 2, 4)


def analytics(summary: dict[str, Any]) -> dict[str, Any]:
    """Payoff curves (at the 15:15 exit and at expiry), what each exit would
    roughly cost/earn right now, and the premium history."""
    qty = int(summary["lots"]) * int(summary["lotSize"])
    entry_at = datetime.fromtimestamp(int(summary["entryTime"]), IST)
    years_entry = max(_years(summary["expiry"], entry_at), 1e-6)
    legs = []
    for side, strike, price in (("PE", summary["peStrike"], summary["entryPe"]), ("CE", summary["ceStrike"], summary["entryCe"])):
        iv = _implied_vol(float(price), float(summary["entrySpot"]), float(strike), years_entry, side == "CE")
        legs.append({"action": "SELL", "qty": 1, "optionType": side, "strike": float(strike), "price": float(price), "iv": iv * 100})
    exit_at = datetime.combine(entry_at.date(), _hhmm(get_config()["exitTime"]), tzinfo=IST)
    years_exit = _years(summary["expiry"], exit_at)
    spot = float(summary["lastSpot"] or summary["entrySpot"])
    lo = min(float(summary["peStrike"]), float(summary["stopLow"])) - 0.6 * float(summary["straddle"])
    hi = max(float(summary["ceStrike"]), float(summary["stopHigh"])) + 0.6 * float(summary["straddle"])
    points = []
    for i in range(161):
        price = lo + (hi - lo) * i / 160
        points.append({"price": round(price, 1), "expiry": round(ve.expiry_pnl_points(legs, price) * qty),
                       "today": round(ve.today_pnl_points(legs, price, years_exit) * qty)})
    now = datetime.now(IST)
    years_now = _years(summary["expiry"], min(now, exit_at)) if summary["status"] == "OPEN" else years_exit

    def pnl_at(level: float) -> float:
        return round(ve.today_pnl_points(legs, level, years_now) * qty - float(summary["charges"]) * 2, 0)

    scenarios = [
        {"kind": "move_low", "label": f"NIFTY falls to {summary['stopLow']:,.0f}", "level": summary["stopLow"],
         "distance": round(spot - float(summary["stopLow"]), 2), "estNet": pnl_at(float(summary["stopLow"]))},
        {"kind": "move_high", "label": f"NIFTY rises to {summary['stopHigh']:,.0f}", "level": summary["stopHigh"],
         "distance": round(float(summary["stopHigh"]) - spot, 2), "estNet": pnl_at(float(summary["stopHigh"]))},
        {"kind": "backstop", "label": f"Premium reaches {summary['backstop']:.2f}", "level": summary["backstop"],
         "distance": round(float(summary["backstop"]) - float(summary["current"]), 2),
         "estNet": round((float(summary["credit"]) - float(summary["backstop"])) * qty - float(summary["charges"]) * 2, 0)},
        *([{"kind": "early", "label": f"Premium falls to {summary['earlyTarget']:.2f} (its {get_config()['exitTime']} value) before then",
             "level": summary["earlyTarget"], "distance": round(float(summary["current"]) - float(summary["earlyTarget"]), 2),
             "estNet": round((float(summary["credit"]) - float(summary["earlyTarget"])) * qty - float(summary["charges"]) * 2, 0)}]
           if summary.get("earlyTarget") is not None and get_config()["earlyExit"] else []),
        *([{"kind": "guard", "label": f"Still open and in profit at {get_config()['europeGuardTime']} (Europe-open guard)",
             "level": None, "distance": max(0, int((datetime.combine(now.date(), _hhmm(get_config()["europeGuardTime"]), tzinfo=IST) - now).total_seconds())),
             "estNet": round(float(summary["grossPnl"]) - float(summary["charges"]) * 2, 0)}]
           if get_config()["europeGuard"] and summary["status"] == "OPEN" and now.time() < dtime(13, 0) else []),
        {"kind": "time", "label": f"Time exit at {get_config()['exitTime']}", "level": None,
         "distance": max(0, int((exit_at - now).total_seconds())) if summary["status"] == "OPEN" else 0,
         "estNet": round(float(summary["grossPnl"]) - float(summary["charges"]) * 2, 0)},
    ]
    return {
        "payoff": points, "breakevens": ve._breakevens(legs, lo, hi), "ivs": {l["optionType"]: l["iv"] for l in legs},
        "scenarios": scenarios, "marks": db.list_calm_marks(int(summary["id"])), "quantity": qty,
    }


def trade_detail(trade_id: int) -> dict[str, Any] | None:
    row = db.get_calm_trade(trade_id)
    if not row:
        return None
    s = summarize(row)
    return {**s, **analytics(s)}


async def state() -> dict[str, Any]:
    config = get_config()
    now = datetime.now(IST)
    today = now.date()
    snap = _runtime.get("snapshot") if _runtime.get("day") == today.isoformat() else None
    if snap is None:
        try:
            snap = await snapshot(DhanService(get_settings()), config, today)
        except Exception as exc:
            snap = {"error": f"Dhan data unavailable: {exc}"}
    trades = [summarize(t) for t in db.list_calm_trades(day=today.isoformat())]
    stops = sum(1 for t in trades if t["exitReason"] and ("stop" in t["exitReason"] or "backstop" in t["exitReason"]))
    return {
        "config": config, "now": int(time.time()), "marketOpen": market_open(now), "mode": _mode(config), "snapshot": snap,
        "spot": _runtime.get("spot") or [], "todayTrades": trades,
        "openTrade": next(({**t, **analytics(t)} for t in trades if t["status"] == "OPEN"), None),
        "entriesToday": len(trades), "stopsToday": stops,
        "events": [{"time": e["time"], "kind": e["kind"], "text": e["text"], "tradeId": e["trade_id"]} for e in db.list_calm_events(today.isoformat())],
    }


def list_trades() -> list[dict[str, Any]]:
    return [summarize(t) for t in db.list_calm_trades()]


def _event(trade_id: int | None, kind: str, text: str) -> None:
    db.calm_insert("calm_strangle_events", {"day": datetime.now(IST).date().isoformat(), "trade_id": trade_id,
                                            "time": int(time.time()), "kind": kind, "text": text})


async def _notify(text: str) -> None:
    try:
        await TelegramNotifier().send(text)
    except Exception:
        logger.warning("calm_strangle: telegram send failed")


def start_calm_strangle_task() -> asyncio.Task | None:
    if not get_settings().calm_strangle_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_calm_strangle_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


def _seconds_to_next_poll(now_epoch: float) -> float:
    second = now_epoch % 60
    for offset in POLL_OFFSETS:
        if second < offset - 0.05:
            return offset - second
    return 60 - second + POLL_OFFSETS[0]


async def _loop() -> None:
    while True:
        try:
            await monitor_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("calm_strangle: monitor iteration failed")
        await asyncio.sleep(_seconds_to_next_poll(time.time()))
