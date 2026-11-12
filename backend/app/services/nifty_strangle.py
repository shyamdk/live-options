"""NIFTY Strangle -- BTC Strangle's rules on NIFTY weekly options, two books.

Entry: at 15:15 IST (window to 15:25) on the trading day before NIFTY's
weekly expiry, sell an OTM CE and an OTM PE at spot +- multiplier x the ATM
straddle (each rounded outward to a listed strike). "As far as possible but
it should make sense": if that strike's bid is under the minimum premium,
step one strike inward at a time until it pays at least that much; if no
strike does, skip that night.

Each short leg on its own:
  STOP     LTP >= entry x (1 + stop%)  -> buy back at ask (checked every
           poll in market hours; an overnight gap can open beyond it)
  EXPIRY   at 15:20 on expiry day: buy back if still worth more than the
           threshold, otherwise let it expire; expiring legs settle at 15:30
           at intrinsic value (0 when out of the money -- no order, no charges).

Books (each with its own settings, trades and P&L):
  plain   the naked strangle. Event-week rider: an entry whose hold (entry
          day .. expiry, inclusive) contains a major scheduled event
          (app/services/market_events.py: Budget, RBI, Fed, election results)
          is skipped and logged as SKIPPED. Live (if ever) via Dhan.
  hedged  the same shorts plus a bought wing `wingDistance` points beyond
          each (CE + W, PE - W), trading through event weeks. A wing is
          bought before its short is sold, and sold right after its short is
          bought back; at expiry it is sold if worth more than the threshold,
          else expires. Live via Zerodha Kite (app/services/kite_broker.py).
Back-test (backend/data/history/backtests/nifty_strangle_hedge_bt.py, Jan
2025 - Oct 2026, 5 lots): plain +Rs2.15L, worst week -Rs78k; hedged with
500-pt wings +Rs1.70L, worst week -Rs37.5k. The event rider changed nothing
in that window (the -Rs78k week was unscheduled news) -- it is insurance.

Charges: Dhan's app model per order (Zerodha's F&O charges are the same Rs20
per order). Paper: sell at bid, buy at ask (LTP if no quote). Live: plain via
Dhan market orders (NIFTY_STRANGLE_LIVE_ORDER_ENABLED); hedged via Kite
marketable LIMIT orders (NIFTY_STRANGLE_KITE_LIVE_ORDER_ENABLED); both also
need LIVE_ORDER_ENABLED and the book's mode set to live. Stops are watched by
this monitor, not resting on the exchange.
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
from app.services import kite_broker, market_events, varaha
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
BOOKS = ("plain", "hedged")

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
    "skipEventWeeks": True,
    "wingDistance": 500.0,
}
BOOK_DEFAULTS = {"plain": {"skipEventWeeks": True, "wingDistance": 0.0}, "hedged": {"skipEventWeeks": False, "wingDistance": 500.0}}

_lock = asyncio.Lock()
_expiry_cache: dict[str, Any] = {"at": 0.0, "expiries": []}
_notified: set[str] = set()


def _book(book: str | None) -> str:
    if book not in (None, *BOOKS):
        raise ValueError("book must be plain or hedged")
    return book or "plain"


def _key(book: str, key: str) -> str:
    return key if book == "plain" else f"{book}.{key}"


# ---------------------------------------------------------------- config


def get_config(book: str | None = "plain") -> dict[str, Any]:
    book = _book(book)
    config: dict[str, Any] = {"book": book}
    for key, default in DEFAULTS.items():
        default = BOOK_DEFAULTS[book].get(key, default)
        raw = db.get_nifty_strangle_setting(_key(book, key))
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
    config["broker"] = "kite" if book == "hedged" else "dhan"
    if book == "hedged":
        config["liveOrdersAllowed"] = bool(settings.nifty_strangle_kite_live_order_enabled and settings.live_order_enabled and kite_broker.configured())
        config["kite"] = kite_broker.status()
    else:
        config["liveOrdersAllowed"] = bool(settings.nifty_strangle_live_order_enabled and settings.live_order_enabled)
    return config


def update_config(updates: dict[str, Any], book: str | None = "plain") -> dict[str, Any]:
    book = _book(book)
    for key, value in updates.items():
        if key not in DEFAULTS or value is None:
            continue
        if key == "mode":
            if value not in ("paper", "live"):
                raise ValueError("mode must be paper or live")
            if value == "live" and not get_config(book)["liveOrdersAllowed"]:
                flag = "NIFTY_STRANGLE_KITE_LIVE_ORDER_ENABLED / KITE_API_KEY" if book == "hedged" else "NIFTY_STRANGLE_LIVE_ORDER_ENABLED"
                raise ValueError(f"Live orders are locked on the server ({flag}).")
        if key in ("entryTime", "entryWindowEnd", "expiryExitTime"):
            datetime.strptime(str(value), "%H:%M")
        if key in ("multiplier", "stopLossPercent", "lots", "minPremium") and float(value) <= 0:
            raise ValueError(f"{key} must be positive")
        if key == "wingDistance" and book == "hedged" and float(value) < 50:
            raise ValueError("wingDistance must be at least 50 points")
        default = DEFAULTS[key]
        db.set_nifty_strangle_setting(_key(book, key), ("1" if value else "0") if isinstance(default, bool) else str(value))
    return get_config(book)


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


def _events(entry: date, expiry: date) -> list[dict[str, Any]]:
    return [{"day": e["day"], "name": e["name"], "kind": e["kind"]} for e in market_events.events_between(entry, expiry)]


async def plan(expiry: date | None = None, *, dhan: DhanService | None = None, book: str | None = "plain") -> dict[str, Any]:
    book = _book(book)
    config = get_config(book)
    dhan = dhan or DhanService(get_settings())
    today = datetime.now(IST).date()
    entry_date = None
    if expiry is None:
        now = datetime.now(IST)
        traded_today = any(t["entry_date"] == today.isoformat() for t in db.list_nifty_strangle_trades(limit=20, book=book))
        after = traded_today or now.time() > _hhmm(config["entryWindowEnd"])
        entry_date, expiry = await next_entry(dhan, today, after_window=after)
        if not expiry:
            return {"config": config, "error": "No upcoming NIFTY expiry listed by Dhan."}
    entry_date = entry_date or entry_day_for(expiry)
    events = _events(entry_date, expiry)
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
        return {"config": config, "expiry": expiry.isoformat(), "entryDate": entry_date.isoformat(), "events": events,
                "error": "NIFTY option chain unavailable."}
    both = [k for k, r in rows.items() if r["CE"] and r["PE"] and r["CE"]["ltp"] and r["PE"]["ltp"]]
    atm = min(both, key=lambda k: abs(k - spot))
    straddle = rows[atm]["CE"]["ltp"] + rows[atm]["PE"]["ltp"]
    distance = float(config["multiplier"]) * straddle
    floor = float(config["minPremium"])
    legs: dict[str, Any] = {}
    wings: dict[str, Any] = {}
    errors = []

    def leg_info(q: dict[str, Any], strike: float) -> dict[str, Any]:
        return {"strike": strike, "securityId": q["securityId"], "ltp": q["ltp"], "bid": q["bid"], "ask": q["ask"], "iv": q["iv"],
                "delta": q["delta"], "oiLots": round((q["oi"] or 0) / LOT_SIZE), "distancePercent": round(abs(strike - spot) / spot * 100, 2)}

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
        legs[side] = {**leg_info(rows[chosen][side], chosen), "formulaStrike": formula, "steppedIn": chosen != formula, "target": round(target, 2)}
        if book == "hedged":
            want = chosen + outward * float(config["wingDistance"])
            beyond = [k for k in listed if (k >= want if outward > 0 else k <= want)]
            wing = beyond[0] if beyond else None
            if wing is None:
                errors.append(f"{side}: no listed wing strike {'≥' if outward > 0 else '≤'} {want:,.0f}")
                continue
            wings[side] = leg_info(rows[wing][side], wing)
    qty = config["quantity"]
    out: dict[str, Any] = {
        "config": config, "entryDate": entry_date.isoformat(), "expiry": expiry.isoformat(),
        "spot": spot, "atmStrike": atm, "straddle": round(straddle, 2), "multiplier": config["multiplier"],
        "distance": round(distance, 2), "legs": legs, "wings": wings, "events": events,
        "eventSkip": bool(events and config["skipEventWeeks"]),
    }
    if errors:
        out["error"] = "; ".join(errors)
        return out
    sl_mult = 1 + float(config["stopLossPercent"]) / 100
    credit = charges = wing_cost = 0.0
    for leg in legs.values():
        fill = leg["bid"] or leg["ltp"]
        leg["sellAt"] = fill
        leg["slPrice"] = round(fill * sl_mult, 2)
        credit += fill * qty
        charges += _charges(fill, qty, "SELL")
    for w in wings.values():
        fill = w["ask"] or w["ltp"]
        w["buyAt"] = fill
        wing_cost += fill * qty
        charges += _charges(fill, qty, "BUY")
    out.update(credit=round(credit, 2), wingCost=round(wing_cost, 2), netCredit=round(credit - wing_cost, 2), sellCharges=round(charges, 2),
               netIfExpire=round(credit - wing_cost - charges, 2), lossIfBothStopped=round(-credit * (sl_mult - 1) - charges * 2, 2))
    if wings:
        widths = [abs(wings[s]["strike"] - legs[s]["strike"]) for s in wings]
        out["maxLossPerSide"] = round(max(widths) * qty - (credit - wing_cost) + charges * 2, 2)
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


async def _execute(security_id: str, side: str, qty: int, mode: str, quote: dict[str, Any] | None, tag: str,
                   *, broker: str = "dhan", symbol: str | None = None) -> dict[str, Any]:
    price = _fill(quote, side)
    if mode != "live":
        return {"ok": price is not None, "price": price, "orderId": None, "note": None if price else "no quote"}
    if broker == "kite":
        if not symbol:
            return {"ok": False, "price": price, "orderId": None, "note": "no Kite symbol"}

        async def requote() -> dict[str, Any] | None:
            return (await _quotes(DhanService(get_settings()), [security_id])).get(str(security_id))

        try:
            return await kite_broker.execute(symbol=symbol, side=side, qty=qty, quote=quote, tag=f"NS{tag}", requote=requote)
        except Exception as exc:
            return {"ok": False, "price": price, "orderId": None, "note": f"Kite: {exc}"}
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


async def enter(trigger: str = "scheduled", *, force: bool = False, book: str | None = "plain") -> dict[str, Any]:
    async with _lock:
        return await _enter(trigger, force=force, book=_book(book))


async def _enter(trigger: str, *, force: bool, book: str) -> dict[str, Any]:
    """Callers hold _lock (the monitor already does when it enters)."""
    config = get_config(book)
    mode = _mode(config)
    broker = config["broker"]
    dhan = DhanService(get_settings())
    today = datetime.now(IST).date()
    entry_date, expiry = await next_entry(dhan, today)
    if not expiry:
        return {"status": "skipped", "message": "No upcoming expiry."}
    if not force and entry_date != today:
        return {"status": "skipped", "message": f"Today isn't an entry day (next: {entry_date:%a %d %b} for the {expiry:%d %b} expiry)."}
    if any(t["expiry"] == expiry.isoformat() for t in db.list_nifty_strangle_trades(status="OPEN", book=book)):
        return {"status": "blocked", "message": f"A strangle on the {expiry:%d %b} expiry is already open."}
    if mode == "live" and broker == "kite" and not kite_broker.access_token():
        await kite_broker.remind_login("strangle entry")
        return {"status": "skipped", "message": "Not logged in to Zerodha today -- open the login link sent on Telegram."}
    p = await plan(expiry, dhan=dhan, book=book)
    label = "NIFTY Strangle" + (" (hedged)" if book == "hedged" else "")
    now = int(time.time())
    if p.get("eventSkip") and not force:
        names = "; ".join(f"{e['name']} ({e['day']})" for e in p["events"])
        db.nifty_strangle_insert("nifty_strangle_trades", {
            "mode": mode, "trigger": "skipped", "entry_date": today.isoformat(), "expiry": expiry.isoformat(), "entry_time": now,
            "spot": p.get("spot") or 0, "atm_strike": p.get("atmStrike") or 0, "straddle": p.get("straddle") or 0,
            "multiplier": config["multiplier"], "distance": p.get("distance") or 0, "stop_loss_percent": config["stopLossPercent"],
            "lots": config["lots"], "lot_size": LOT_SIZE, "status": "SKIPPED", "book": book, "broker": broker,
            "notes": f"Event week skipped: {names}", "closed_at": now,
        })
        await _notify(f"⏸ {label}: {expiry:%d %b} expiry skipped -- event in the hold: {names}")
        return {"status": "skipped", "message": f"Event week: {names}"}
    if p.get("error"):
        return {"status": "skipped", "message": p["error"]}
    qty = config["quantity"]
    notes = [f"{side} stepped in from {leg['formulaStrike']:,.0f} to {leg['strike']:,.0f} (bid under ₹{config['minPremium']:g})"
             for side, leg in p["legs"].items() if leg["steppedIn"]]
    if p["events"]:
        notes.append("event in the hold: " + "; ".join(f"{e['name']} ({e['day']})" for e in p["events"]))
    trade_id = db.nifty_strangle_insert("nifty_strangle_trades", {
        "mode": mode, "trigger": trigger, "entry_date": today.isoformat(), "expiry": expiry.isoformat(), "entry_time": now,
        "spot": p["spot"], "atm_strike": p["atmStrike"], "straddle": p["straddle"], "multiplier": p["multiplier"],
        "distance": p["distance"], "stop_loss_percent": config["stopLossPercent"], "lots": config["lots"], "lot_size": LOT_SIZE,
        "status": "OPEN", "notes": "; ".join(notes) or None, "book": book, "broker": broker,
    })
    ids = [leg["securityId"] for leg in p["legs"].values()] + [w["securityId"] for w in p["wings"].values()]
    quotes = await _quotes(dhan, ids)
    lines = []

    async def place(side: str, info: dict[str, Any], role: str) -> bool:
        q = quotes.get(str(info["securityId"])) or {"ltp": info["ltp"], "bid": info["bid"], "ask": info["ask"]}
        order_side = "SELL" if role == "short" else "BUY"
        symbol, res = None, None
        if mode == "live" and broker == "kite":
            try:
                symbol = await kite_broker.nifty_option_symbol(expiry, info["strike"], side)
            except Exception as exc:
                res = {"ok": False, "price": None, "orderId": None, "note": f"Kite symbol: {exc}"}
        res = res or await _execute(info["securityId"], order_side, qty, mode, q, f"{trade_id}{side}{role[0].upper()}E", broker=broker, symbol=symbol)
        leg_id = db.nifty_strangle_insert("nifty_strangle_legs", {
            "trade_id": trade_id, "option_type": side, "strike": info["strike"], "security_id": str(info["securityId"]),
            "formula_strike": info.get("formulaStrike"), "quantity": qty, "entry_bid": q.get("bid"), "entry_ask": q.get("ask"),
            "status": "PENDING", "role": role, "symbol": symbol,
        })
        if not res["ok"] or not res["price"]:
            db.nifty_strangle_update("nifty_strangle_legs", leg_id, status="NOT_FILLED", error=res["note"])
            lines.append(f"{order_side} {side} {info['strike']:,.0f}{' wing' if role == 'wing' else ''}: NOT FILLED ({res['note']})")
            return False
        price = float(res["price"])
        sl = round(price * (1 + float(config["stopLossPercent"]) / 100), 2) if role == "short" else None
        db.nifty_strangle_update("nifty_strangle_legs", leg_id, entry_price=price, sl_price=sl, status="OPEN",
                                 entry_order_id=res["orderId"], entry_charges=_charges(price, qty, order_side),
                                 last_ltp=q.get("ltp"), last_bid=q.get("bid"), last_ask=q.get("ask"), last_update=now, error=res["note"])
        if role == "short":
            lines.append(f"SELL {config['lots']} lots {info['strike']:,.0f} {side} @ {price:.2f} (SL {sl:.2f}, {info['distancePercent']}% away)")
        else:
            lines.append(f"BUY wing {info['strike']:,.0f} {side} @ {price:.2f}")
        return True

    for side in ("PE", "CE"):
        if book == "hedged":
            # wing first: never leave a short naked in the hedged book
            if not await place(side, p["wings"][side], "wing"):
                lines.append(f"⚠️ {side} short not sold because its wing did not fill")
                continue
        await place(side, p["legs"][side], "short")
    trade = _get(trade_id)
    if not any(l["status"] == "OPEN" and l["role"] == "short" for l in trade["legs"]):
        for leg in trade["legs"]:
            if leg["status"] == "OPEN":  # a lone wing: sell it back
                await _close_leg(trade, leg, "manual", (await _quotes(dhan, [leg["security_id"]])).get(str(leg["security_id"])), notify_close=False)
        db.nifty_strangle_update("nifty_strangle_trades", trade_id, status="FAILED", closed_at=now)
    elif mode == "live" and any(l["status"] == "NOT_FILLED" for l in trade["legs"]):
        lines.append("⚠️ not every leg filled -- check the broker.")
    await _notify(f"🪢 {label} #{trade_id} ({mode}{', Zerodha' if mode == 'live' and broker == 'kite' else ''}) -- expiry {expiry:%a %d %b}, "
                  f"spot {p['spot']:,.0f}, straddle {p['straddle']:.0f} × {p['multiplier']} = {p['distance']:.0f} pts\n" + "\n".join(lines)
                  + (f"\n{'; '.join(notes)}" if notes else ""))
    return {"status": "entered", "tradeId": trade_id}


def _get(trade_id: int) -> dict[str, Any]:
    return next(t for t in db.list_nifty_strangle_trades(limit=1000) if t["id"] == trade_id)


def _leg_pnl(leg: dict[str, Any], mark: float) -> float:
    sign = 1 if (leg.get("role") or "short") == "short" else -1
    return sign * (float(leg["entry_price"]) - mark) * int(leg["quantity"])


async def _close_leg(trade: dict[str, Any], leg: dict[str, Any], reason: str, quote: dict[str, Any] | None,
                     *, settle_price: float | None = None, notify_close: bool = True) -> None:
    now = int(time.time())
    role = leg.get("role") or "short"
    order_side = "BUY" if role == "short" else "SELL"
    broker = trade.get("broker") or "dhan"
    if settle_price is not None:
        price, order_id, note, charges = settle_price, None, "settled at expiry", 0.0
    else:
        res = await _execute(leg["security_id"], order_side, int(leg["quantity"]), trade["mode"], quote, f"{leg['id']}X",
                             broker=broker, symbol=leg.get("symbol"))
        price = res["price"] if res["price"] is not None else float(leg["last_ltp"] or leg["entry_price"])
        order_id, note = res["orderId"], res["note"]
        charges = _charges(price, int(leg["quantity"]), order_side)
        if not res["ok"] and trade["mode"] == "live":
            where = "Zerodha" if broker == "kite" else "Dhan"
            note = f"{'BUY-BACK' if role == 'short' else 'WING SALE'} FAILED ({res['note']}) -- square off {leg['strike']:,.0f} {leg['option_type']} manually in {where}"
            await _notify(f"🚨 NIFTY Strangle #{trade['id']}: {note}")
    db.nifty_strangle_update("nifty_strangle_legs", leg["id"], status="CLOSED", exit_price=price, exit_time=now,
                             exit_reason=reason, exit_order_id=order_id, exit_charges=charges, error=note)
    pnl = _leg_pnl(leg, price)
    label = {"stop_loss": "STOP LOSS", "expiry_buyback": "bought back before expiry", "expired": "expired",
             "manual": "closed manually", "wing_with_stop": "wing sold with its stopped short", "expiry_sold": "wing sold before expiry"}.get(reason, reason)
    what = "wing " if role == "wing" else ""
    if notify_close:
        await _notify(f"{'🛑' if pnl < 0 else '✅'} NIFTY Strangle #{trade['id']} {what}{leg['strike']:,.0f} {leg['option_type']} "
                      f"{label} @ {price:.2f} ({'sold' if role == 'short' else 'bought'} {float(leg['entry_price']):.2f}) · ₹{pnl:,.0f}")
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
    dhan = DhanService(get_settings())
    open_trades = db.list_nifty_strangle_trades(status="OPEN")

    # expired while the server was down: settle at the last known price
    for trade in open_trades:
        if date.fromisoformat(trade["expiry"]) < now.date():
            for leg in trade["legs"]:
                if leg["status"] == "OPEN":
                    await _close_leg(trade, leg, "expired", None, settle_price=float(leg["last_ltp"] or 0))
    open_trades = db.list_nifty_strangle_trades(status="OPEN")

    # a live Zerodha position needs today's Kite login before the market opens
    if any(t["mode"] == "live" and t.get("broker") == "kite" for t in open_trades) and now.time() >= dtime(8, 45):
        await kite_broker.remind_login("open strangle")

    if market_open(now) and open_trades:
        ids = [l["security_id"] for t in open_trades for l in t["legs"] if l["status"] == "OPEN"]
        quotes = await _quotes(dhan, ids)
        spot = None
        for trade in open_trades:
            config = get_config(trade.get("book") or "plain")
            expiry_today = trade["expiry"] == now.date().isoformat()
            legs = sorted(trade["legs"], key=lambda l: (l.get("role") or "short") != "short")  # shorts first
            for leg in legs:
                if leg["status"] != "OPEN":
                    continue
                q = quotes.get(str(leg["security_id"])) or {}
                ltp = q.get("ltp")
                if ltp:
                    db.nifty_strangle_update("nifty_strangle_legs", leg["id"], last_ltp=ltp, last_bid=q.get("bid"),
                                             last_ask=q.get("ask"), last_update=int(time.time()))
                    leg.update(last_ltp=ltp)
                role = leg.get("role") or "short"
                if role == "short" and ltp and leg["sl_price"] and ltp >= float(leg["sl_price"]):
                    await _close_leg(trade, leg, "stop_loss", q)
                    for wing in legs:  # sell this side's wing right after
                        if (wing.get("role") == "wing" and wing["option_type"] == leg["option_type"] and wing["status"] == "OPEN"):
                            await _close_leg(trade, wing, "wing_with_stop", quotes.get(str(wing["security_id"])))
                            wing["status"] = "CLOSED"
                    continue
                if expiry_today and now.time() >= _hhmm(config["expiryExitTime"]):
                    worth = (_fill(q, "BUY") if role == "short" else _fill(q, "SELL")) or ltp or 0
                    if worth > float(config["buybackThreshold"]):
                        await _close_leg(trade, leg, "expiry_buyback" if role == "short" else "expiry_sold", q)
                    elif now.time() >= dtime(15, 29):
                        spot = spot or await _spot(dhan) or 0
                        intrinsic = max(0.0, (spot - leg["strike"]) if leg["option_type"] == "CE" else (leg["strike"] - spot))
                        await _close_leg(trade, leg, "expired", None, settle_price=round(intrinsic, 2))

    # scheduled entries, one per book
    if not market_open(now):
        return
    for book in BOOKS:
        config = get_config(book)
        if not config["enabled"]:
            continue
        if config["broker"] == "kite" and _mode(config) == "live" and now.time() >= dtime(9, 0):
            entry_date, _ = await next_entry(dhan, now.date())
            if entry_date == now.date():
                await kite_broker.remind_login("entry today")
        if not (_hhmm(config["entryTime"]) <= now.time() <= _hhmm(config["entryWindowEnd"])):
            continue
        if db.has_nifty_strangle_trade(now.date().isoformat(), _mode(config), book):
            continue
        entry_date, expiry = await next_entry(dhan, now.date())
        if entry_date != now.date():
            continue
        result = await _enter("scheduled", force=False, book=book)
        if result["status"] == "skipped" and not result["message"].startswith("Event week"):
            key = f"{book}:{now.date()}:{result['message'][:40]}"
            if key not in _notified:
                _notified.add(key)
                await _notify(f"NIFTY Strangle ({book}): no trade yet -- {result['message']} (retrying until {config['entryWindowEnd']})")


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
        role = leg.get("role") or "short"
        l = {
            "id": leg["id"], "role": role, "optionType": leg["option_type"], "strike": leg["strike"], "formulaStrike": leg["formula_strike"],
            "securityId": leg["security_id"], "symbol": leg.get("symbol"), "quantity": leg["quantity"], "entryPrice": leg["entry_price"],
            "entryBid": leg["entry_bid"], "entryAsk": leg["entry_ask"], "slPrice": leg["sl_price"], "status": leg["status"],
            "exitPrice": leg["exit_price"], "exitTime": leg["exit_time"], "exitReason": leg["exit_reason"],
            "entryOrderId": leg["entry_order_id"], "exitOrderId": leg["exit_order_id"], "lastLtp": leg["last_ltp"],
            "lastBid": leg["last_bid"], "lastAsk": leg["last_ask"], "lastUpdate": leg["last_update"], "error": leg["error"],
            "charges": round(float(leg["entry_charges"] or 0) + float(leg["exit_charges"] or 0), 2),
        }
        if leg["entry_price"]:
            mark = leg["exit_price"] if leg["status"] == "CLOSED" else (leg["last_ltp"] or leg["entry_price"])
            l["pnl"] = round(_leg_pnl(leg, float(mark)), 2)
            gross += l["pnl"]
            credit += (1 if role == "short" else -1) * float(leg["entry_price"]) * int(leg["quantity"])
            charges += l["charges"]
        legs.append(l)
    return {
        "id": trade["id"], "book": trade.get("book") or "plain", "broker": trade.get("broker"), "mode": trade["mode"], "trigger": trade["trigger"],
        "entryDate": trade["entry_date"], "expiry": trade["expiry"], "entryTime": trade["entry_time"], "spot": trade["spot"], "atmStrike": trade["atm_strike"],
        "straddle": trade["straddle"], "multiplier": trade["multiplier"], "distance": trade["distance"],
        "stopLossPercent": trade["stop_loss_percent"], "lots": trade["lots"], "lotSize": trade["lot_size"],
        "status": trade["status"], "notes": trade["notes"], "closedAt": trade["closed_at"], "legs": legs,
        "credit": round(credit, 2), "grossPnl": round(gross, 2), "charges": round(charges, 2), "netPnl": round(gross - charges, 2),
    }


def list_trades(book: str | None = "plain") -> list[dict[str, Any]]:
    return [summarize(t) for t in db.list_nifty_strangle_trades(book=_book(book))]


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
