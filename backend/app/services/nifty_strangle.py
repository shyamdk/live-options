"""NIFTY Strangle -- BTC Strangle's rules on NIFTY weekly options.

Entry: at 15:15 IST (window to 15:25) on the trading day before NIFTY's
weekly expiry, sell an OTM CE and an OTM PE at spot +- multiplier x the ATM
straddle (each rounded outward to a listed strike). "As far as possible but
it should make sense": if that strike's bid is under the minimum premium,
step one strike inward at a time until it pays at least that much; if no
strike does, skip that night.

Each leg on its own:
  STOP     LTP >= entry x (1 + stop%)  -> buy back at ask (checked every
           poll in market hours; an overnight gap can open beyond it)
  EXPIRY   at 15:20 on expiry day: buy back if still worth more than the
           threshold, otherwise let it expire; expiring legs settle at 15:30
           at intrinsic value (0 when out of the money -- no buy order, no
           charges).

Charges: Dhan's app model per order (each leg is one order). Paper: sell at
bid, buy at ask (LTP if no quote). Live (mode=live AND
NIFTY_STRANGLE_LIVE_ORDER_ENABLED AND LIVE_ORDER_ENABLED): market orders
(product MARGIN, carried overnight), fills read back from Dhan; stops are
watched by this monitor, not resting on the exchange.
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
from app.db import sqlite as db
from app.services import varaha
from app.services.charges import option_order_charges
from app.services.dhan import DhanService
from app.services.orders import DhanOrderService
from app.services.telegram import TelegramNotifier

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
LOT_SIZE = 65
OPTION_SEGMENT = "NSE_FNO"
INDEX_SEGMENT = "IDX_I"
POLL_SECONDS = 15
QUOTE_MAX_AGE = 2.0
MARKET_OPEN, MARKET_CLOSE = dtime(9, 15), dtime(15, 30)

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "mode": "paper",
    "multiplier": 2.2,
    "stopLossPercent": 100.0,
    "lots": 5,
    "minPremium": 3.0,
    "entryTime": "15:15",
    "entryWindowEnd": "15:25",
    "expiryExitTime": "15:20",
    "buybackThreshold": 1.0,
}

_lock = asyncio.Lock()
_expiry_cache: dict[str, Any] = {"at": 0.0, "expiries": []}
_notified: set[str] = set()


# ---------------------------------------------------------------- config


def get_config() -> dict[str, Any]:
    config: dict[str, Any] = {}
    for key, default in DEFAULTS.items():
        raw = db.get_nifty_strangle_setting(key)
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
    config["liveOrdersAllowed"] = bool(settings.nifty_strangle_live_order_enabled and settings.live_order_enabled)
    return config


def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if key not in DEFAULTS or value is None:
            continue
        if key == "mode":
            if value not in ("paper", "live"):
                raise ValueError("mode must be paper or live")
            settings = get_settings()
            if value == "live" and not (settings.nifty_strangle_live_order_enabled and settings.live_order_enabled):
                raise ValueError("Live orders are locked on the server (NIFTY_STRANGLE_LIVE_ORDER_ENABLED=false).")
        if key in ("entryTime", "entryWindowEnd", "expiryExitTime"):
            datetime.strptime(str(value), "%H:%M")
        if key in ("multiplier", "stopLossPercent", "lots", "minPremium") and float(value) <= 0:
            raise ValueError(f"{key} must be positive")
        default = DEFAULTS[key]
        db.set_nifty_strangle_setting(key, ("1" if value else "0") if isinstance(default, bool) else str(value))
    return get_config()


def _hhmm(value: str) -> dtime:
    return datetime.strptime(value, "%H:%M").time()


def _mode(config: dict[str, Any]) -> str:
    return "live" if config["mode"] == "live" and config["liveOrdersAllowed"] else "paper"


# ---------------------------------------------------------------- calendar


async def _expiries(dhan: DhanService) -> list[date]:
    if _expiry_cache["expiries"] and time.monotonic() - _expiry_cache["at"] < 1800:
        return _expiry_cache["expiries"]
    expiries = sorted(date.fromisoformat(x) for x in await dhan.expiry_list(get_settings().dhan_nifty_security_id, INDEX_SEGMENT))
    _expiry_cache.update(at=time.monotonic(), expiries=expiries)
    return expiries


def entry_day_for(expiry: date) -> date:
    """The weekday before the expiry (holidays aren't known here)."""
    day = expiry - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


async def next_entry(dhan: DhanService, today: date, *, after_window: bool = False) -> tuple[date | None, date | None]:
    """(entry date, expiry) for the next entry on or after today; with
    after_window, today's entry (window already over) is skipped."""
    for expiry in await _expiries(dhan):
        if expiry <= today:
            continue
        entry = entry_day_for(expiry)
        if entry > today or (entry == today and not after_window):
            return entry, expiry
    return None, None


def market_open(now: datetime) -> bool:
    return weekday_open(now) and MARKET_OPEN <= now.time() <= MARKET_CLOSE


# ---------------------------------------------------------------- planning


async def _spot(dhan: DhanService) -> float | None:
    scrip = get_settings().dhan_nifty_security_id
    data = await dhan.market_quotes_by_segment({INDEX_SEGMENT: [int(scrip)]}, max_age_seconds=QUOTE_MAX_AGE)
    return varaha._number(((data.get(INDEX_SEGMENT) or {}).get(str(scrip)) or {}).get("last_price"))


async def plan(expiry: date | None = None, *, dhan: DhanService | None = None) -> dict[str, Any]:
    config = get_config()
    dhan = dhan or DhanService(get_settings())
    today = datetime.now(IST).date()
    entry_date = None
    if expiry is None:
        now = datetime.now(IST)
        traded_today = any(t["entry_date"] == today.isoformat() for t in db.list_nifty_strangle_trades(limit=20))
        after = traded_today or now.time() > _hhmm(config["entryWindowEnd"])
        entry_date, expiry = await next_entry(dhan, today, after_window=after)
        if not expiry:
            return {"config": config, "error": "No upcoming NIFTY expiry listed by Dhan."}
    chain = await dhan.option_chain(get_settings().dhan_nifty_security_id, INDEX_SEGMENT, expiry.isoformat())
    spot = varaha._number(chain.get("last_price"))
    oc = chain.get("oc") or {}
    rows: dict[float, dict[str, Any]] = {}
    for key, sides in oc.items():
        strike = varaha._number(key)
        if strike is None or not isinstance(sides, dict):
            continue
        rows[float(strike)] = {"CE": varaha._quote(sides.get("ce")), "PE": varaha._quote(sides.get("pe"))}
    if not spot or not rows:
        return {"config": config, "expiry": expiry.isoformat(), "error": "NIFTY option chain unavailable."}
    both = [k for k, r in rows.items() if r["CE"] and r["PE"] and r["CE"]["ltp"] and r["PE"]["ltp"]]
    atm = min(both, key=lambda k: abs(k - spot))
    straddle = rows[atm]["CE"]["ltp"] + rows[atm]["PE"]["ltp"]
    distance = float(config["multiplier"]) * straddle
    floor = float(config["minPremium"])
    legs: dict[str, Any] = {}
    errors = []
    for side, target, outward in (("CE", spot + distance, 1), ("PE", spot - distance, -1)):
        listed = sorted((k for k, r in rows.items() if r[side]), reverse=outward < 0)
        # formula strike: the first listed strike at least the distance away
        formula = next((k for k in listed if (k >= target if outward > 0 else k <= target)), None)
        if formula is None:
            errors.append(f"{side}: no listed strike {'≥' if outward > 0 else '≤'} {target:,.0f}")
            continue
        # step inward (toward spot) until the bid pays at least the floor
        inward = [k for k in sorted(rows, reverse=outward > 0) if rows[k][side] and (k <= formula if outward > 0 else k >= formula)
                  and (k > spot if outward > 0 else k < spot)]
        chosen = next((k for k in inward if (rows[k][side]["bid"] or 0) >= floor), None)
        if chosen is None:
            errors.append(f"{side}: no strike between spot and {formula:,.0f} bids ≥ ₹{floor:g}")
            continue
        q = rows[chosen][side]
        legs[side] = {
            "strike": chosen, "formulaStrike": formula, "steppedIn": chosen != formula, "securityId": q["securityId"],
            "ltp": q["ltp"], "bid": q["bid"], "ask": q["ask"], "iv": q["iv"], "delta": q["delta"],
            "oiLots": round((q["oi"] or 0) / LOT_SIZE), "distancePercent": round(abs(chosen - spot) / spot * 100, 2),
            "target": round(target, 2),
        }
    qty = config["quantity"]
    out: dict[str, Any] = {
        "config": config, "entryDate": (entry_date or entry_day_for(expiry)).isoformat(), "expiry": expiry.isoformat(),
        "spot": spot, "atmStrike": atm, "straddle": round(straddle, 2), "multiplier": config["multiplier"],
        "distance": round(distance, 2), "legs": legs,
    }
    if errors:
        out["error"] = "; ".join(errors)
        return out
    sl_mult = 1 + float(config["stopLossPercent"]) / 100
    credit = 0.0
    charges = 0.0
    for leg in legs.values():
        fill = leg["bid"] or leg["ltp"]
        leg["sellAt"] = fill
        leg["slPrice"] = round(fill * sl_mult, 2)
        credit += fill * qty
        charges += _charges(fill, qty, "SELL")
    out.update(credit=round(credit, 2), sellCharges=round(charges, 2), netIfExpire=round(credit - charges, 2),
               lossIfBothStopped=round(-credit * (sl_mult - 1) - charges * 2, 2))
    return out


def _charges(price: float, qty: int, side: str) -> float:
    return float(option_order_charges(premium=price, quantity=qty, side=side, exchange_segment=OPTION_SEGMENT)["total"])


# ---------------------------------------------------------------- orders


def _fill(q: dict[str, Any] | None, side: str) -> float | None:
    if not q:
        return None
    bid, ask, ltp = q.get("bid"), q.get("ask"), q.get("ltp")
    if bid and ask and ask >= bid > 0:
        return float(ask) if side == "BUY" else float(bid)
    return float(ltp) if ltp else None


async def _quotes(dhan: DhanService, security_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not security_ids:
        return {}
    data = await dhan.market_quotes_by_segment({OPTION_SEGMENT: [int(x) for x in security_ids]}, max_age_seconds=QUOTE_MAX_AGE)
    out = {}
    for sec, q in (data.get(OPTION_SEGMENT) or {}).items():
        depth = (q or {}).get("depth") or {}
        buy = (depth.get("buy") or [{}])[0] or {}
        sell = (depth.get("sell") or [{}])[0] or {}
        out[str(sec)] = {"ltp": varaha._number(q.get("last_price")), "bid": varaha._number(buy.get("price")) or None,
                         "ask": varaha._number(sell.get("price")) or None}
    return out


async def _execute(security_id: str, side: str, qty: int, mode: str, quote: dict[str, Any] | None, tag: str) -> dict[str, Any]:
    price = _fill(quote, side)
    if mode != "live":
        return {"ok": price is not None, "price": price, "orderId": None, "note": None if price else "no quote"}
    settings = get_settings()
    orders = DhanOrderService(settings)
    result: dict[str, Any] = {}
    for attempt in range(3):
        result = await orders.place_market_order(
            transaction_type=side, exchange_segment=OPTION_SEGMENT, security_id=security_id, quantity=qty,
            correlation_id=f"NS{tag}{attempt}{int(time.time()) % 100000}",
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
        if status in ("REJECTED", "CANCELLED"):
            return {"ok": False, "price": price, "orderId": order_id, "note": f"order {status.lower()}"}
    return {"ok": True, "price": traded or price, "orderId": order_id, "note": None if traded else "fill price not confirmed -- quote used"}


# ---------------------------------------------------------------- lifecycle


async def enter(trigger: str = "scheduled", *, force: bool = False) -> dict[str, Any]:
    async with _lock:
        return await _enter(trigger, force=force)


async def _enter(trigger: str, *, force: bool) -> dict[str, Any]:
    """Callers hold _lock (the monitor already does when it enters)."""
    config = get_config()
    mode = _mode(config)
    dhan = DhanService(get_settings())
    today = datetime.now(IST).date()
    entry_date, expiry = await next_entry(dhan, today)
    if not expiry:
        return {"status": "skipped", "message": "No upcoming expiry."}
    if not force and entry_date != today:
        return {"status": "skipped", "message": f"Today isn't an entry day (next: {entry_date:%a %d %b} for the {expiry:%d %b} expiry)."}
    if any(t["expiry"] == expiry.isoformat() and t["status"] == "OPEN" for t in db.list_nifty_strangle_trades(status="OPEN")):
        return {"status": "blocked", "message": f"A strangle on the {expiry:%d %b} expiry is already open."}
    p = await plan(expiry, dhan=dhan)
    if p.get("error"):
        return {"status": "skipped", "message": p["error"]}
    qty = config["quantity"]
    now = int(time.time())
    notes = [f"{side} stepped in from {leg['formulaStrike']:,.0f} to {leg['strike']:,.0f} (bid under ₹{config['minPremium']:g})"
             for side, leg in p["legs"].items() if leg["steppedIn"]]
    trade_id = db.nifty_strangle_insert("nifty_strangle_trades", {
        "mode": mode, "trigger": trigger, "entry_date": today.isoformat(), "expiry": expiry.isoformat(), "entry_time": now,
        "spot": p["spot"], "atm_strike": p["atmStrike"], "straddle": p["straddle"], "multiplier": p["multiplier"],
        "distance": p["distance"], "stop_loss_percent": config["stopLossPercent"], "lots": config["lots"], "lot_size": LOT_SIZE,
        "status": "OPEN", "notes": "; ".join(notes) or None,
    })
    quotes = await _quotes(dhan, [leg["securityId"] for leg in p["legs"].values()])
    lines = []
    for side in ("PE", "CE"):
        leg = p["legs"][side]
        q = quotes.get(str(leg["securityId"])) or {"ltp": leg["ltp"], "bid": leg["bid"], "ask": leg["ask"]}
        res = await _execute(leg["securityId"], "SELL", qty, mode, q, f"{trade_id}{side}E")
        leg_id = db.nifty_strangle_insert("nifty_strangle_legs", {
            "trade_id": trade_id, "option_type": side, "strike": leg["strike"], "security_id": str(leg["securityId"]),
            "formula_strike": leg["formulaStrike"], "quantity": qty, "entry_bid": q.get("bid"), "entry_ask": q.get("ask"),
            "status": "PENDING",
        })
        if not res["ok"] or not res["price"]:
            db.nifty_strangle_update("nifty_strangle_legs", leg_id, status="NOT_FILLED", error=res["note"])
            lines.append(f"{side} {leg['strike']:,.0f}: NOT FILLED ({res['note']})")
            continue
        price = float(res["price"])
        sl = round(price * (1 + float(config["stopLossPercent"]) / 100), 2)
        db.nifty_strangle_update("nifty_strangle_legs", leg_id, entry_price=price, sl_price=sl, status="OPEN",
                                 entry_order_id=res["orderId"], entry_charges=_charges(price, qty, "SELL"),
                                 last_ltp=q.get("ltp"), last_bid=q.get("bid"), last_ask=q.get("ask"), last_update=now,
                                 error=res["note"])
        lines.append(f"SELL {config['lots']} lots {leg['strike']:,.0f} {side} @ {price:.2f} (SL {sl:.2f}, {leg['distancePercent']}% away)")
    trade = _get(trade_id)
    if not any(l["status"] == "OPEN" for l in trade["legs"]):
        db.nifty_strangle_update("nifty_strangle_trades", trade_id, status="FAILED", closed_at=now)
    elif mode == "live" and any(l["status"] == "NOT_FILLED" for l in trade["legs"]):
        lines.append("⚠️ only one leg filled -- the other is running alone.")
    await _notify(f"🪢 NIFTY Strangle #{trade_id} ({mode}) -- expiry {expiry:%a %d %b}, spot {p['spot']:,.0f}, "
              f"straddle {p['straddle']:.0f} × {p['multiplier']} = {p['distance']:.0f} pts\n" + "\n".join(lines)
                  + (f"\n{'; '.join(notes)}" if notes else ""))
    return {"status": "entered", "tradeId": trade_id}


def _get(trade_id: int) -> dict[str, Any]:
    return next(t for t in db.list_nifty_strangle_trades(limit=1000) if t["id"] == trade_id)


async def _close_leg(trade: dict[str, Any], leg: dict[str, Any], reason: str, quote: dict[str, Any] | None,
                     *, settle_price: float | None = None) -> None:
    now = int(time.time())
    if settle_price is not None:
        price, order_id, note, charges = settle_price, None, "settled at expiry", 0.0
    else:
        res = await _execute(leg["security_id"], "BUY", int(leg["quantity"]), trade["mode"], quote, f"{leg['id']}X")
        price = res["price"] if res["price"] is not None else float(leg["last_ltp"] or leg["entry_price"])
        order_id, note = res["orderId"], res["note"]
        charges = _charges(price, int(leg["quantity"]), "BUY")
        if not res["ok"] and trade["mode"] == "live":
            note = f"BUY-BACK FAILED ({res['note']}) -- square off {leg['strike']:,.0f} {leg['option_type']} manually in Dhan"
            await _notify(f"🚨 NIFTY Strangle #{trade['id']}: {note}")
    db.nifty_strangle_update("nifty_strangle_legs", leg["id"], status="CLOSED", exit_price=price, exit_time=now,
                             exit_reason=reason, exit_order_id=order_id, exit_charges=charges, error=note)
    pnl = (float(leg["entry_price"]) - price) * int(leg["quantity"])
    label = {"stop_loss": "STOP LOSS", "expiry_buyback": "bought back before expiry", "expired": "expired",
             "manual": "closed manually"}.get(reason, reason)
    await _notify(f"{'🛑' if pnl < 0 else '✅'} NIFTY Strangle #{trade['id']} {leg['strike']:,.0f} {leg['option_type']} "
                  f"{label} @ {price:.2f} (sold {float(leg['entry_price']):.2f}) · ₹{pnl:,.0f}")
    fresh = _get(int(trade["id"]))
    if not any(l["status"] == "OPEN" for l in fresh["legs"]):
        db.nifty_strangle_update("nifty_strangle_trades", int(trade["id"]), status="CLOSED", closed_at=now)
        s = summarize(_get(int(trade["id"])))
        await _notify(f"NIFTY Strangle #{trade['id']} closed · gross ₹{s['grossPnl']:,.0f} · charges ₹{s['charges']:,.0f} · net ₹{s['netPnl']:,.0f}")


async def monitor_once() -> None:
    async with _lock:
        await _monitor()


async def _monitor() -> None:
    now = datetime.now(IST)
    if not weekday_open(now):
        return
    config = get_config()
    dhan = DhanService(get_settings())
    open_trades = db.list_nifty_strangle_trades(status="OPEN")

    # expired while the server was down: settle at the last known price
    for trade in open_trades:
        if date.fromisoformat(trade["expiry"]) < now.date():
            for leg in trade["legs"]:
                if leg["status"] == "OPEN":
                    await _close_leg(trade, leg, "expired", None, settle_price=float(leg["last_ltp"] or 0))
    open_trades = db.list_nifty_strangle_trades(status="OPEN")

    if market_open(now) and open_trades:
        ids = [l["security_id"] for t in open_trades for l in t["legs"] if l["status"] == "OPEN"]
        quotes = await _quotes(dhan, ids)
        spot = None
        for trade in open_trades:
            expiry_today = trade["expiry"] == now.date().isoformat()
            for leg in trade["legs"]:
                if leg["status"] != "OPEN":
                    continue
                q = quotes.get(str(leg["security_id"])) or {}
                ltp = q.get("ltp")
                if ltp:
                    db.nifty_strangle_update("nifty_strangle_legs", leg["id"], last_ltp=ltp, last_bid=q.get("bid"),
                                             last_ask=q.get("ask"), last_update=int(time.time()))
                    leg.update(last_ltp=ltp)
                if ltp and leg["sl_price"] and ltp >= float(leg["sl_price"]):
                    await _close_leg(trade, leg, "stop_loss", q)
                    continue
                if expiry_today and now.time() >= _hhmm(config["expiryExitTime"]):
                    worth = _fill(q, "BUY") or ltp or 0
                    if worth > float(config["buybackThreshold"]):
                        await _close_leg(trade, leg, "expiry_buyback", q)
                    elif now.time() >= dtime(15, 29):
                        spot = spot or await _spot(dhan) or 0
                        intrinsic = max(0.0, (spot - leg["strike"]) if leg["option_type"] == "CE" else (leg["strike"] - spot))
                        await _close_leg(trade, leg, "expired", None, settle_price=round(intrinsic, 2))

    # scheduled entry
    if not config["enabled"] or not market_open(now):
        return
    if not (_hhmm(config["entryTime"]) <= now.time() <= _hhmm(config["entryWindowEnd"])):
        return
    if db.has_nifty_strangle_trade(now.date().isoformat(), _mode(config)):
        return
    entry_date, expiry = await next_entry(dhan, now.date())
    if entry_date != now.date():
        return
    result = await _enter("scheduled", force=False)
    if result["status"] == "skipped":
        key = f"{now.date()}:{result['message'][:40]}"
        if key not in _notified:
            _notified.add(key)
            await _notify(f"NIFTY Strangle: no trade yet -- {result['message']} (retrying until {config['entryWindowEnd']})")


async def close_leg_now(leg_id: int) -> dict[str, Any]:
    async with _lock:
        for trade in db.list_nifty_strangle_trades(status="OPEN"):
            for leg in trade["legs"]:
                if leg["id"] == leg_id and leg["status"] == "OPEN":
                    quotes = await _quotes(DhanService(get_settings()), [leg["security_id"]])
                    await _close_leg(trade, leg, "manual", quotes.get(str(leg["security_id"])))
                    return {"status": "closed"}
    return {"status": "blocked", "message": "Leg is not open."}


# ---------------------------------------------------------------- reporting


def summarize(trade: dict[str, Any]) -> dict[str, Any]:
    legs = []
    gross = charges = credit = 0.0
    for leg in trade["legs"]:
        l = {
            "id": leg["id"], "optionType": leg["option_type"], "strike": leg["strike"], "formulaStrike": leg["formula_strike"],
            "securityId": leg["security_id"], "quantity": leg["quantity"], "entryPrice": leg["entry_price"],
            "entryBid": leg["entry_bid"], "entryAsk": leg["entry_ask"], "slPrice": leg["sl_price"], "status": leg["status"],
            "exitPrice": leg["exit_price"], "exitTime": leg["exit_time"], "exitReason": leg["exit_reason"],
            "entryOrderId": leg["entry_order_id"], "exitOrderId": leg["exit_order_id"], "lastLtp": leg["last_ltp"],
            "lastBid": leg["last_bid"], "lastAsk": leg["last_ask"], "lastUpdate": leg["last_update"], "error": leg["error"],
            "charges": round(float(leg["entry_charges"] or 0) + float(leg["exit_charges"] or 0), 2),
        }
        if leg["entry_price"]:
            mark = leg["exit_price"] if leg["status"] == "CLOSED" else (leg["last_ltp"] or leg["entry_price"])
            l["pnl"] = round((float(leg["entry_price"]) - float(mark)) * int(leg["quantity"]), 2)
            gross += l["pnl"]
            credit += float(leg["entry_price"]) * int(leg["quantity"])
            charges += l["charges"]
        legs.append(l)
    return {
        "id": trade["id"], "mode": trade["mode"], "trigger": trade["trigger"], "entryDate": trade["entry_date"],
        "expiry": trade["expiry"], "entryTime": trade["entry_time"], "spot": trade["spot"], "atmStrike": trade["atm_strike"],
        "straddle": trade["straddle"], "multiplier": trade["multiplier"], "distance": trade["distance"],
        "stopLossPercent": trade["stop_loss_percent"], "lots": trade["lots"], "lotSize": trade["lot_size"],
        "status": trade["status"], "notes": trade["notes"], "closedAt": trade["closed_at"], "legs": legs,
        "credit": round(credit, 2), "grossPnl": round(gross, 2), "charges": round(charges, 2), "netPnl": round(gross - charges, 2),
    }


def list_trades() -> list[dict[str, Any]]:
    return [summarize(t) for t in db.list_nifty_strangle_trades()]


async def spot_chart() -> dict[str, Any]:
    dhan = DhanService(get_settings())
    today = datetime.now(IST).date()
    start = today - timedelta(days=4)
    candles = await dhan.intraday_candles(str(get_settings().dhan_nifty_security_id), INDEX_SEGMENT, "INDEX", "5",
                                          start.isoformat(), today.isoformat())
    return {"candles": sorted(({"time": c["time"], "close": c["close"]} for c in candles), key=lambda c: c["time"])}


async def _notify(text: str) -> None:
    try:
        await TelegramNotifier().send(text)
    except Exception:
        logger.warning("nifty_strangle: telegram send failed")


def start_nifty_strangle_task() -> asyncio.Task | None:
    if not get_settings().nifty_strangle_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_nifty_strangle_task(task: asyncio.Task | None) -> None:
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
            logger.exception("nifty_strangle: monitor iteration failed")
        await asyncio.sleep(POLL_SECONDS)
