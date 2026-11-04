"""BTC Calm Strangle -- Calm Strangle's idea on Delta Exchange BTC daily
options (docs/strategies/btc-calm-strangle.md).

Session = the daily expiry settling at 17:30 IST. Entries only in the
overnight window (22:00-06:00 IST), checked every completed minute: if BTC's
range over the last 15 one-minute closes is <= 15% of the ATM straddle (mark
CE + PE at the strike nearest spot), sell the CE at the first listed strike
>= spot + 1.5 x straddle and the PE at the first <= spot - 1.5 x straddle
(credit >= $20 per BTC).

While open (every poll, live chain):
  MOVE STOP  BTC moves 1.5 x straddle (at entry) from the entry spot
  BACKSTOP   combined premium >= credit x 2.5
  EARLY      premium reaches its value at the exit time (BTC unchanged) ->
             book it, no more entries this session
  TIME       4 h before settlement (13:30 IST)
Max 3 entries / 2 stops per session.

Paper: sell at bid, buy at ask (mark if no quote), Delta fee model. Live
(mode=live AND BTC_CALM_LIVE_ORDER_ENABLED): market orders, fills read back.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, time as dtime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.db import sqlite as db
from app.services import btc_strangle_engine as engine
from app.services import varaha_engine as ve
from app.services.delta_exchange import DeltaExchangeService
from app.services.telegram import TelegramNotifier

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
SPOT_SYMBOL = ".DEXBTUSD"
POLL_OFFSETS = (2, 17, 32, 47)

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "mode": "paper",
    "contracts": 500,
    "calmPercent": 15.0,
    "calmWindow": 15,
    "strikeMultiple": 1.5,
    "stopMultiple": 1.5,
    "backstopPercent": 150.0,
    "minCredit": 20.0,
    "windowStart": "22:00",
    "windowEnd": "06:00",
    "exitBeforeMinutes": 240,
    "maxEntries": 3,
    "maxStops": 2,
    "earlyExit": True,
}

# Two paper books run side by side on the same signal: "standard" holds to
# exitBeforeMinutes (13:30 IST); "early" exits at 06:00 IST (690 minutes
# before the 17:30 settlement) -- ~37% less profit, ~half the drawdown in
# the backtest. Each book has its own trades, session limits and switch.
BOOKS: dict[str, dict[str, Any]] = {
    "standard": {"label": "Hold to 13:30", "exitBeforeMinutes": None},   # uses the global exitBeforeMinutes
    "early": {"label": "Exit 06:00", "exitBeforeMinutes": 690},
}

_lock = asyncio.Lock()
_runtime: dict[str, Any] = {"minute": 0, "snapshot": None, "spot": [], "spotAt": 0}


# ---------------------------------------------------------------- config


def get_config() -> dict[str, Any]:
    config: dict[str, Any] = {}
    for key, default in DEFAULTS.items():
        raw = db.get_btc_calm_setting(key)
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
    books = {}
    for name, spec in BOOKS.items():
        enabled = db.get_btc_calm_setting(f"{name}.enabled")
        exit_before = db.get_btc_calm_setting(f"{name}.exitBeforeMinutes")
        books[name] = {
            "label": spec["label"],
            "enabled": (enabled or "1") == "1",
            "exitBeforeMinutes": int(float(exit_before)) if exit_before else (spec["exitBeforeMinutes"] or int(config["exitBeforeMinutes"])),
        }
    config["books"] = books
    settings = get_settings()
    config["btcPerLeg"] = round(int(config["contracts"]) * engine.CONTRACT_VALUE_BTC, 3)
    config["liveOrdersAllowed"] = bool(settings.btc_calm_live_order_enabled and settings.delta_exchange_api_key)
    return config


def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    for name, sub in (updates.get("books") or {}).items():
        if name in BOOKS and isinstance(sub, dict):
            if sub.get("enabled") is not None:
                db.set_btc_calm_setting(f"{name}.enabled", "1" if sub["enabled"] else "0")
            if sub.get("exitBeforeMinutes") is not None:
                if not 30 <= int(float(sub["exitBeforeMinutes"])) <= 1400:
                    raise ValueError("exitBeforeMinutes must be 30-1400")
                db.set_btc_calm_setting(f"{name}.exitBeforeMinutes", str(int(float(sub["exitBeforeMinutes"]))))
    for key, value in updates.items():
        if key not in DEFAULTS or value is None:
            continue
        if key == "mode":
            if value not in ("paper", "live"):
                raise ValueError("mode must be paper or live")
            if value == "live" and not get_settings().btc_calm_live_order_enabled:
                raise ValueError("Live orders are locked on the server (BTC_CALM_LIVE_ORDER_ENABLED=false).")
        if key in ("windowStart", "windowEnd"):
            datetime.strptime(str(value), "%H:%M")
        elif key not in ("enabled", "mode", "earlyExit") and float(value) <= 0:
            raise ValueError(f"{key} must be positive")
        default = DEFAULTS[key]
        db.set_btc_calm_setting(key, ("1" if value else "0") if isinstance(default, bool) else str(value))
    return get_config()


def _hhmm(value: str) -> dtime:
    return datetime.strptime(value, "%H:%M").time()


def _mode(config: dict[str, Any]) -> str:
    return "live" if config["mode"] == "live" and config["liveOrdersAllowed"] else "paper"


def in_window(now: datetime, config: dict[str, Any]) -> bool:
    a, b, t = _hhmm(config["windowStart"]), _hhmm(config["windowEnd"]), now.time()
    return a <= t < b if a < b else (t >= a or t < b)


# ---------------------------------------------------------------- market data


async def _chain() -> dict[str, Any]:
    return engine.parse_chain(await DeltaExchangeService().get_option_tickers("BTC"))


def _session_expiry(chain: dict[str, Any], now_epoch: int) -> dict[str, Any] | None:
    upcoming = sorted((e for e in chain["expiries"].values() if e["settlement"] > now_epoch), key=lambda e: e["settlement"])
    return upcoming[0] if upcoming else None


async def _spot_minutes(minutes: int = 360) -> list[dict[str, Any]]:
    if _runtime["spot"] and time.time() - _runtime["spotAt"] < 30:
        return _runtime["spot"]
    now = int(time.time())
    candles = await DeltaExchangeService().get_candles(SPOT_SYMBOL, "1m", now - minutes * 60, now)
    out = sorted(({"time": int(c["time"]), "close": float(c["close"])} for c in candles if int(c["time"]) + 60 <= now),
                 key=lambda c: c["time"])
    _runtime.update(spot=out, spotAt=time.time())
    return out


def _price(q: dict[str, Any] | None) -> float | None:
    if not q:
        return None
    return q.get("mark") or engine.mid(q)


def snapshot(chain: dict[str, Any], minutes: list[dict[str, Any]], config: dict[str, Any], now_epoch: int) -> dict[str, Any]:
    expiry = _session_expiry(chain, now_epoch)
    spot = chain.get("spot")
    if not expiry or not spot:
        return {"error": "No BTC daily expiry / spot from Delta."}
    strikes = expiry["strikes"]
    both = [k for k, s in strikes.items() if s.get("CE") and s.get("PE") and _price(s["CE"]) and _price(s["PE"])]
    if not both:
        return {"error": "No ATM quotes.", "expiry": expiry["code"]}
    atm = min(both, key=lambda k: abs(k - spot))
    straddle = _price(strikes[atm]["CE"]) + _price(strikes[atm]["PE"])
    window = [m["close"] for m in minutes[-int(config["calmWindow"]):]]
    calm_range = (max(window) - min(window)) if len(window) >= int(config["calmWindow"]) else None
    threshold = straddle * float(config["calmPercent"]) / 100
    distance = straddle * float(config["strikeMultiple"])
    ce_k = min((k for k, s in strikes.items() if s.get("CE") and k >= spot + distance), default=None)
    pe_k = max((k for k, s in strikes.items() if s.get("PE") and k <= spot - distance), default=None)
    legs = {}
    for side, k in (("CE", ce_k), ("PE", pe_k)):
        if k is not None:
            q = strikes[k][side]
            legs[side] = {**q, "distancePercent": round(abs(k - spot) / spot * 100, 2)}
    credit = sum((l.get("bid") or l.get("mark") or 0) for l in legs.values()) if len(legs) == 2 else None
    exit_by = expiry["settlement"] - int(config["exitBeforeMinutes"]) * 60
    exit_by_books = {n: expiry["settlement"] - int(b["exitBeforeMinutes"]) * 60 for n, b in config["books"].items()}
    return {
        "time": now_epoch, "expiry": expiry["code"], "settlement": expiry["settlement"], "exitBy": exit_by,
        "exitByBooks": exit_by_books, "spot": spot,
        "atmStrike": atm, "straddle": round(straddle, 2), "calmRange": round(calm_range, 2) if calm_range is not None else None,
        "calmThreshold": round(threshold, 2), "calm": calm_range is not None and calm_range <= threshold,
        "legs": legs, "credit": round(credit, 2) if credit else None,
        "stopBand": round(straddle * float(config["stopMultiple"]), 2),
    }


# ---------------------------------------------------------------- pricing helpers


def _years(settlement: int, at_epoch: int) -> float:
    return max(settlement - at_epoch, 0) / (365 * 24 * 3600)


def _implied_vol(price: float, spot: float, strike: float, years: float, is_call: bool) -> float:
    lo, hi = 0.05, 5.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if ve.bs_price(spot, strike, years, mid, is_call) > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _early_target(settlement: int, exit_by: int, entry_epoch: int, spot: float, ce_k: float, ce_px: float, pe_k: float, pe_px: float) -> float | None:
    ye, yx = _years(settlement, entry_epoch), _years(settlement, exit_by)
    if ye <= 0:
        return None
    value = 0.0
    for k, px, call in ((ce_k, ce_px, True), (pe_k, pe_px, False)):
        value += ve.bs_price(spot, k, yx, _implied_vol(px, spot, k, ye, call), call)
    return round(value, 2)


def _fee(price: float, contracts: int, spot: float) -> float:
    s = get_settings()
    return engine.fee(price, contracts, spot, taker_rate=s.btc_strangle_taker_fee_rate,
                      premium_cap=s.btc_strangle_premium_fee_cap, gst_rate=s.btc_strangle_gst_rate)


# ---------------------------------------------------------------- execution


async def _execute(q: dict[str, Any], side: str, contracts: int, mode: str) -> dict[str, Any]:
    if side == "sell":
        price = q.get("bid") or q.get("mark")
    else:
        price = q.get("ask") or q.get("mark")
    if mode != "live":
        return {"ok": price is not None, "price": price, "orderId": None, "note": None if price else "no quote"}
    delta = DeltaExchangeService()
    try:
        order = await delta.place_order(product_id=int(q["productId"]), size=contracts, side=side, order_type="market_order",
                                        reduce_only=side == "buy", client_order_id=f"bcalm{side[0]}{int(time.time())}")
    except Exception as exc:
        return {"ok": False, "price": price, "orderId": None, "note": str(exc)[:200]}
    order_id = order.get("id")
    fill = engine._num(order.get("average_fill_price"))
    for _ in range(6):
        if fill:
            break
        await asyncio.sleep(1)
        try:
            info = await delta.get_order(order_id)
            fill = engine._num(info.get("average_fill_price"))
        except Exception:
            pass
    return {"ok": True, "price": fill or price, "orderId": str(order_id), "note": None if fill else "fill price not confirmed -- quote used"}


async def _enter(config: dict[str, Any], snap: dict[str, Any], trigger: str, book: str = "standard") -> dict[str, Any]:
    mode = _mode(config)
    contracts = int(config["contracts"])
    legs = snap["legs"]
    fills = {s: await _execute(legs[s], "sell", contracts, mode) for s in ("CE", "PE")}
    if not all(f["ok"] for f in fills.values()):
        if mode == "live":
            for s, f in fills.items():
                if f["ok"]:
                    await _execute(legs[s], "buy", contracts, mode)
            await _notify("🚨 BTC Calm Strangle: entry failed on one leg -- the other was bought back. Check Delta positions.")
        _event(snap["expiry"], None, "entry_failed", "; ".join(f"{s}: {f['note']}" for s, f in fills.items()))
        return {"status": "failed"}
    now = int(time.time())
    ce, pe = float(fills["CE"]["price"]), float(fills["PE"]["price"])
    credit = round(ce + pe, 2)
    spot = float(snap["spot"])
    band = float(snap["straddle"]) * float(config["stopMultiple"])
    exit_by = snap["exitByBooks"][book]
    early = _early_target(snap["settlement"], exit_by, now, spot, legs["CE"]["strike"], ce, legs["PE"]["strike"], pe)
    trade_id = db.btc_calm_insert("btc_calm_trades", {
        "expiry_code": snap["expiry"], "settlement": snap["settlement"], "mode": mode, "trigger": trigger, "entry_time": now,
        "entry_spot": spot, "straddle": snap["straddle"], "calm_range": snap["calmRange"], "atm_strike": snap["atmStrike"],
        "ce_strike": legs["CE"]["strike"], "pe_strike": legs["PE"]["strike"], "ce_symbol": legs["CE"]["symbol"],
        "pe_symbol": legs["PE"]["symbol"], "ce_product_id": legs["CE"]["productId"], "pe_product_id": legs["PE"]["productId"],
        "contracts": contracts, "entry_ce": ce, "entry_pe": pe, "credit": credit,
        "entry_quotes": json.dumps({s: {k: legs[s].get(k) for k in ("bid", "ask", "mark", "iv")} for s in ("CE", "PE")}),
        "stop_low": round(spot - band, 2), "stop_high": round(spot + band, 2),
        "backstop": round(credit * (1 + float(config["backstopPercent"]) / 100), 2), "early_target": early,
        "exit_by": exit_by, "book": book, "status": "OPEN", "fees": round(_fee(ce, contracts, spot) + _fee(pe, contracts, spot), 4),
        "last_ce": ce, "last_pe": pe, "last_spot": spot, "last_update": now, "best": credit, "worst": credit,
        "order_ids": json.dumps({s: f["orderId"] for s, f in fills.items()}),
    })
    db.add_btc_calm_mark(trade_id, now, credit, spot)
    usd = credit * contracts * engine.CONTRACT_VALUE_BTC
    text = (f"[{BOOKS[book]['label']}] #{trade_id} SELL {legs['CE']['symbol']} @ {ce:.1f} + {legs['PE']['symbol']} @ {pe:.1f} = {credit:.1f} "
            f"(${usd:,.2f} on {contracts} contracts) · BTC {spot:,.0f} calm ({snap['calmRange']:.0f} ≤ {snap['calmThreshold']:.0f}) · "
            f"stop if BTC < {spot - band:,.0f} or > {spot + band:,.0f}")
    _event(snap["expiry"], trade_id, "entry", text)
    await _notify(f"🧘 BTC Calm Strangle {mode.upper()} {text}")
    return {"status": "entered", "tradeId": trade_id}


async def _exit(trade: dict[str, Any], chain: dict[str, Any] | None, reason: str) -> None:
    contracts = int(trade["contracts"])
    expiry = (chain or {}).get("expiries", {}).get(trade["expiry_code"]) or {"strikes": {}}
    spot = (chain or {}).get("spot") or trade["last_spot"]
    out = {}
    for side in ("CE", "PE"):
        k = float(trade[f"{side.lower()}_strike"])
        q = (expiry["strikes"].get(k) or {}).get(side) or {
            "productId": trade[f"{side.lower()}_product_id"], "mark": trade[f"last_{side.lower()}"]}
        r = await _execute(q, "buy", contracts, trade["mode"])
        price = r["price"] if r["price"] is not None else float(trade[f"last_{side.lower()}"] or 0)
        if not r["ok"] and trade["mode"] == "live":
            await _notify(f"🚨 BTC Calm Strangle #{trade['id']}: buy-back of {side} failed ({r['note']}) -- close it manually on Delta.")
        out[side] = (q, r, price)
    now = int(time.time())
    ce, pe = out["CE"][2], out["PE"][2]
    fees = float(trade["fees"]) + _fee(ce, contracts, float(spot or 0)) + _fee(pe, contracts, float(spot or 0))
    ids = json.loads(trade["order_ids"] or "{}")
    ids.update({f"exit{s}": r["orderId"] for s, (_, r, _) in out.items()})
    db.btc_calm_update_trade(trade["id"], status="CLOSED", exit_time=now, exit_reason=reason, exit_ce=ce, exit_pe=pe,
                             exit_spot=spot, exit_quotes=json.dumps({s: {k: q.get(k) for k in ("bid", "ask", "mark")} for s, (q, _, _) in out.items()}),
                             fees=round(fees, 4), last_ce=ce, last_pe=pe, order_ids=json.dumps(ids))
    db.add_btc_calm_mark(trade["id"], now, round(ce + pe, 2), spot)
    pts = float(trade["credit"]) - (ce + pe)
    net = pts * contracts * engine.CONTRACT_VALUE_BTC - fees
    text = f"[{BOOKS.get(trade.get('book') or 'standard', BOOKS['standard'])['label']}] #{trade['id']} closed ({reason}) @ {ce + pe:.1f} (CE {ce:.1f} + PE {pe:.1f}) · {pts:+.1f} · net ${net:,.2f}"
    _event(trade["expiry_code"], trade["id"], "exit", text)
    await _notify(f"{'✅' if net >= 0 else '🛑'} BTC Calm Strangle {text}")


# ---------------------------------------------------------------- monitor


async def monitor_once() -> None:
    async with _lock:
        await _monitor()


async def _monitor() -> None:
    config = get_config()
    now = datetime.now(IST)
    now_epoch = int(time.time())
    open_trades = db.list_btc_calm_trades(status="OPEN")
    if not open_trades and not config["enabled"]:
        return  # auto entry off and nothing to manage (archived Nov 2026) -- no Delta calls
    minute = (now_epoch // 60) * 60 - 60
    fresh_minute = minute > int(_runtime.get("minute") or 0)
    if not open_trades and not fresh_minute:
        return
    chain = await _chain()

    if fresh_minute:
        try:
            snap = snapshot(chain, await _spot_minutes(), config, now_epoch)
            _runtime.update(minute=minute, snapshot=snap)
        except Exception as exc:
            logger.warning("btc_calm: snapshot failed: %s", exc)
            fresh_minute = False

    for trade in open_trades:
        expiry = chain["expiries"].get(trade["expiry_code"]) or {"strikes": {}}
        ce_q = (expiry["strikes"].get(float(trade["ce_strike"])) or {}).get("CE")
        pe_q = (expiry["strikes"].get(float(trade["pe_strike"])) or {}).get("PE")
        ce, pe, spot = _price(ce_q), _price(pe_q), chain.get("spot")
        if ce and pe:
            comb = ce + pe
            db.btc_calm_update_trade(trade["id"], last_ce=ce, last_pe=pe, last_spot=spot, last_update=now_epoch,
                                     best=min(float(trade["best"] or comb), comb), worst=max(float(trade["worst"] or comb), comb))
            db.add_btc_calm_mark(trade["id"], now_epoch, round(comb, 2), spot)
        reason = None
        if now_epoch >= int(trade["exit_by"]):
            reason = f"time exit ({datetime.fromtimestamp(int(trade['exit_by']), IST):%H:%M} IST)"
        elif spot and (spot <= float(trade["stop_low"]) or spot >= float(trade["stop_high"])):
            reason = f"BTC move stop ({spot:,.0f})"
        elif ce and pe and ce + pe >= float(trade["backstop"]):
            reason = f"premium backstop ({ce + pe:.1f})"
        elif config["earlyExit"] and ce and pe and trade["early_target"] is not None and ce + pe <= float(trade["early_target"]):
            reason = f"exit-time value reached early ({ce + pe:.1f} ≤ {float(trade['early_target']):.1f})"
        if reason:
            await _exit(trade, chain, reason)
    if not fresh_minute:
        return
    snap = _runtime["snapshot"]
    if snap.get("error") or not config["enabled"] or not in_window(now, config):
        return
    if not snap["calm"] or len(snap["legs"]) < 2 or not snap["credit"] or snap["credit"] < float(config["minCredit"]):
        return
    for book, spec in config["books"].items():
        if not spec["enabled"] or db.list_btc_calm_trades(status="OPEN", book=book):
            continue
        if now_epoch >= snap["exitByBooks"][book] - 30 * 60:
            continue
        session = db.list_btc_calm_trades(expiry_code=snap["expiry"], book=book)
        stops = sum(1 for t in session if "stop" in (t["exit_reason"] or "") or "backstop" in (t["exit_reason"] or ""))
        if len(session) >= int(config["maxEntries"]) or stops >= int(config["maxStops"]):
            continue
        if any("reached early" in (t["exit_reason"] or "") for t in session):
            continue
        await _enter(config, snap, "calm", book)


async def enter_now(book: str = "standard") -> dict[str, Any]:
    if book not in BOOKS:
        return {"status": "blocked", "message": "Unknown book."}
    async with _lock:
        if db.list_btc_calm_trades(status="OPEN", book=book):
            return {"status": "blocked", "message": f"{BOOKS[book]['label']}: a strangle is already open."}
        config = get_config()
        snap = snapshot(await _chain(), await _spot_minutes(), config, int(time.time()))
        if snap.get("error") or len(snap.get("legs") or {}) < 2:
            return {"status": "blocked", "message": snap.get("error") or "Strikes unavailable."}
        return await _enter(config, snap, "manual", book)


async def close_now(trade_id: int) -> dict[str, Any]:
    async with _lock:
        trade = next((t for t in db.list_btc_calm_trades(status="OPEN") if t["id"] == trade_id), None)
        if not trade:
            return {"status": "blocked", "message": "Trade is not open."}
        await _exit(trade, await _chain(), "closed manually")
    return {"status": "closed"}


# ---------------------------------------------------------------- reporting


def summarize(t: dict[str, Any]) -> dict[str, Any]:
    btc = int(t["contracts"]) * engine.CONTRACT_VALUE_BTC
    closed = t["status"] == "CLOSED" and t["exit_ce"] is not None
    current = (float(t["exit_ce"]) + float(t["exit_pe"])) if closed else (float(t["last_ce"] or t["entry_ce"]) + float(t["last_pe"] or t["entry_pe"]))
    points = float(t["credit"]) - current
    gross = points * btc
    return {
        "id": t["id"], "book": t.get("book") or "standard", "expiry": t["expiry_code"], "settlement": t["settlement"], "mode": t["mode"], "trigger": t["trigger"],
        "entryTime": t["entry_time"], "entrySpot": t["entry_spot"], "straddle": t["straddle"], "calmRange": t["calm_range"],
        "atmStrike": t["atm_strike"], "ceStrike": t["ce_strike"], "peStrike": t["pe_strike"], "ceSymbol": t["ce_symbol"],
        "peSymbol": t["pe_symbol"], "contracts": t["contracts"], "btcPerLeg": round(btc, 3), "entryCe": t["entry_ce"],
        "entryPe": t["entry_pe"], "credit": t["credit"], "stopLow": t["stop_low"], "stopHigh": t["stop_high"], "backstop": t["backstop"],
        "earlyTarget": t["early_target"], "exitBy": t["exit_by"], "status": t["status"], "exitTime": t["exit_time"],
        "exitReason": t["exit_reason"], "exitCe": t["exit_ce"], "exitPe": t["exit_pe"], "exitSpot": t["exit_spot"],
        "lastCe": t["last_ce"], "lastPe": t["last_pe"], "lastSpot": t["last_spot"], "lastUpdate": t["last_update"],
        "best": t["best"], "worst": t["worst"], "entryQuotes": json.loads(t["entry_quotes"] or "{}"),
        "exitQuotes": json.loads(t["exit_quotes"] or "{}"), "orderIds": json.loads(t["order_ids"] or "{}"),
        "current": round(current, 2), "points": round(points, 2), "grossPnl": round(gross, 2), "fees": round(float(t["fees"]), 2),
        "netPnl": round(gross - float(t["fees"]), 2), "premiumCollected": round(float(t["credit"]) * btc, 2),
        "minutesHeld": round(((t["exit_time"] or int(time.time())) - int(t["entry_time"])) / 60, 1),
    }


def analytics(s: dict[str, Any]) -> dict[str, Any]:
    btc = float(s["btcPerLeg"])
    ye = max(_years(int(s["settlement"]), int(s["entryTime"])), 1e-6)
    legs = []
    for side, k, px in (("PE", s["peStrike"], s["entryPe"]), ("CE", s["ceStrike"], s["entryCe"])):
        iv = _implied_vol(float(px), float(s["entrySpot"]), float(k), ye, side == "CE")
        legs.append({"action": "SELL", "qty": 1, "optionType": side, "strike": float(k), "price": float(px), "iv": iv * 100})
    yx = _years(int(s["settlement"]), int(s["exitBy"]))
    lo = min(float(s["peStrike"]), float(s["stopLow"])) - 0.5 * float(s["straddle"])
    hi = max(float(s["ceStrike"]), float(s["stopHigh"])) + 0.5 * float(s["straddle"])
    points = [{"price": round(lo + (hi - lo) * i / 160, 1),
               "expiry": round(ve.expiry_pnl_points(legs, lo + (hi - lo) * i / 160) * btc, 2),
               "today": round(ve.today_pnl_points(legs, lo + (hi - lo) * i / 160, yx) * btc, 2)} for i in range(161)]
    now = int(time.time())
    yn = _years(int(s["settlement"]), min(now, int(s["exitBy"]))) if s["status"] == "OPEN" else yx
    spot = float(s["lastSpot"] or s["entrySpot"])
    fees2 = float(s["fees"]) * 2

    def at(level: float) -> float:
        return round(ve.today_pnl_points(legs, level, yn) * btc - fees2, 2)

    scenarios = [
        {"kind": "move_low", "label": f"BTC falls to {s['stopLow']:,.0f}", "distance": round(spot - float(s["stopLow"]), 1), "estNet": at(float(s["stopLow"]))},
        {"kind": "move_high", "label": f"BTC rises to {s['stopHigh']:,.0f}", "distance": round(float(s["stopHigh"]) - spot, 1), "estNet": at(float(s["stopHigh"]))},
        {"kind": "backstop", "label": f"Premium reaches {s['backstop']:.1f}", "distance": round(float(s["backstop"]) - float(s["current"]), 1),
         "estNet": round((float(s["credit"]) - float(s["backstop"])) * btc - fees2, 2)},
        *([{"kind": "early", "label": f"Premium falls to {s['earlyTarget']:.1f} (its exit-time value)",
            "distance": round(float(s["current"]) - float(s["earlyTarget"]), 1),
            "estNet": round((float(s["credit"]) - float(s["earlyTarget"])) * btc - fees2, 2)}] if s.get("earlyTarget") is not None else []),
        {"kind": "time", "label": f"Time exit {datetime.fromtimestamp(int(s['exitBy']), IST):%a %H:%M} IST",
         "distance": max(0, int(s["exitBy"]) - now) if s["status"] == "OPEN" else 0, "estNet": round(float(s["grossPnl"]) - fees2, 2)},
    ]
    return {"payoff": points, "breakevens": ve._breakevens(legs, lo, hi), "ivs": {l["optionType"]: round(l["iv"], 1) for l in legs},
            "scenarios": scenarios, "marks": db.list_btc_calm_marks(int(s["id"]))}


def trade_detail(trade_id: int) -> dict[str, Any] | None:
    row = db.get_btc_calm_trade(trade_id)
    if not row:
        return None
    s = summarize(row)
    return {**s, **analytics(s)}


def list_trades() -> list[dict[str, Any]]:
    return [summarize(t) for t in db.list_btc_calm_trades()]


async def state() -> dict[str, Any]:
    config = get_config()
    now = datetime.now(IST)
    snap = _runtime.get("snapshot")
    if snap is None or time.time() - (snap.get("time") or 0) > 120:
        try:
            snap = snapshot(await _chain(), await _spot_minutes(), config, int(time.time()))
        except Exception as exc:
            snap = {"error": f"Delta data unavailable: {exc}"}
    books = {}
    for book, spec in config["books"].items():
        session = [summarize(t) for t in db.list_btc_calm_trades(expiry_code=snap.get("expiry"), book=book)] if snap.get("expiry") else []
        open_row = next(iter(db.list_btc_calm_trades(status="OPEN", book=book)), None)
        open_trade = None
        if open_row:
            s = summarize(open_row)
            open_trade = {**s, **analytics(s)}
        books[book] = {
            **spec, "openTrade": open_trade, "sessionTrades": session, "entriesThisSession": len(session),
            "stopsThisSession": sum(1 for t in session if t["exitReason"] and ("stop" in t["exitReason"] or "backstop" in t["exitReason"])),
            "exitBy": (snap.get("exitByBooks") or {}).get(book),
        }
    try:
        spot_series = await _spot_minutes()
    except Exception:
        spot_series = []
    return {
        "config": config, "now": int(time.time()), "inWindow": in_window(now, config), "mode": _mode(config), "snapshot": snap,
        "spot": spot_series, "books": books,
        "events": [{"time": e["time"], "kind": e["kind"], "text": e["text"]} for e in db.list_btc_calm_events(200)],
    }


def _event(expiry: str | None, trade_id: int | None, kind: str, text: str) -> None:
    db.btc_calm_insert("btc_calm_events", {"expiry_code": expiry, "trade_id": trade_id, "time": int(time.time()), "kind": kind, "text": text})


async def _notify(text: str) -> None:
    try:
        await TelegramNotifier().send(text)
    except Exception:
        logger.warning("btc_calm: telegram send failed")


def start_btc_calm_task() -> asyncio.Task | None:
    if not get_settings().btc_calm_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_btc_calm_task(task: asyncio.Task | None) -> None:
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
            logger.exception("btc_calm: monitor iteration failed")
        await asyncio.sleep(_seconds_to_next_poll(time.time()))
