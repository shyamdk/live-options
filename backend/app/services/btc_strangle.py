"""BTC Strangle on Delta Exchange India (bitcoin-strangle.pdf).

Every night at the entry time (default 22:30 IST) sell an OTM BTC call and put
on the expiry ~43h out, strikes at spot +- multiplier x ATM straddle (rounded
outward to listed strikes). Each leg gets its own stop loss at
(1 + SL%) x entry price. Near expiry (17:25 IST) legs still worth more than the
buy-back threshold are bought back; the rest expire at the 17:30 IST
settlement.

Paper mode simulates fills from the live order book (sell at bid, buy at ask).
Live mode places real Delta orders and requires BOTH the env kill switch
(BTC_STRANGLE_LIVE_ORDER_ENABLED) and the page's mode set to live:
  - entry: limit sell at best bid, waited on up to the fill timeout, the
    unfilled remainder cancelled;
  - stop loss: an exchange-side stop-market buy (reduce-only, triggered on
    mark price) placed right after each fill, so it protects the leg even if
    this server is down -- if that stop cannot be placed the leg is bought
    straight back rather than left unprotected;
  - every order carries a BTCSS-... client order id and the engine only ever
    acts on orders it placed itself (the Delta account also holds manual
    positions that must never be touched).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, time as dtime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import Settings, get_settings
from app.core.timeutil import now_ist
from app.db import sqlite as db
from app.services import btc_strangle_engine as engine
from app.services.delta_exchange import DeltaExchangeError, DeltaExchangeService
from app.services.telegram import TelegramNotifier

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
SETTLEMENT_GRACE_SECONDS = 120
_lock = asyncio.Lock()
_last_chain: dict[str, Any] = {"at": 0.0, "chain": None}

# key -> (settings attribute, parser)
_RUNTIME_KEYS: dict[str, tuple[str, Any]] = {
    "multiplier": ("btc_strangle_strike_multiplier", float),
    "stopLossPercent": ("btc_strangle_stop_loss_percent", float),
    "contracts": ("btc_strangle_contracts", int),
    "entryTime": ("btc_strangle_entry_time", str),
    "entryWindowEnd": ("btc_strangle_entry_window_end", str),
    "expiryOffset": ("btc_strangle_expiry_offset", int),
    "expiryExitTime": ("btc_strangle_expiry_exit_time", str),
    "buybackThreshold": ("btc_strangle_expiry_buyback_threshold", float),
    "minAvailableBalance": ("btc_strangle_min_available_balance", float),
}


# ---------------------------------------------------------------- config


def get_runtime_config() -> dict[str, Any]:
    settings = get_settings()
    config: dict[str, Any] = {}
    for key, (attr, parse) in _RUNTIME_KEYS.items():
        raw = db.get_btc_strangle_setting(key)
        config[key] = parse(raw) if raw is not None else getattr(settings, attr)
    config["enabled"] = (db.get_btc_strangle_setting("enabled") or "1") == "1"
    config["mode"] = db.get_btc_strangle_setting("mode") or "paper"
    config["useFarthestStrike"] = (db.get_btc_strangle_setting("useFarthestStrike") or "0") == "1"
    # skip | farthest | one_side -- what to do when a formula strike isn't listed
    config["missingStrike"] = db.get_btc_strangle_setting("missingStrike") or ("farthest" if config["useFarthestStrike"] else "skip")
    config["liveOrdersAllowed"] = settings.btc_strangle_live_order_enabled
    config["deltaCredentials"] = bool(settings.delta_exchange_api_key and settings.delta_exchange_api_secret)
    return config


def update_runtime_config(updates: dict[str, Any]) -> dict[str, Any]:
    if "mode" in updates and updates["mode"] not in ("paper", "live"):
        raise ValueError("mode must be paper or live")
    if updates.get("mode") == "live" and not get_settings().btc_strangle_live_order_enabled:
        raise ValueError("Live orders are disabled on the server (BTC_STRANGLE_LIVE_ORDER_ENABLED=false).")
    for key in ("entryTime", "entryWindowEnd", "expiryExitTime"):
        if key in updates:
            _parse_hhmm(str(updates[key]))
    if "missingStrike" in updates:
        if updates["missingStrike"] not in ("skip", "farthest", "one_side"):
            raise ValueError("missingStrike must be skip, farthest or one_side")
        updates = {**updates, "useFarthestStrike": updates["missingStrike"] == "farthest"}
    elif updates.get("useFarthestStrike") is not None:  # older clients still send the checkbox
        updates = {**updates, "missingStrike": "farthest" if updates["useFarthestStrike"] else "skip"}
    for key, value in updates.items():
        if value is None:
            continue
        if key in ("enabled", "useFarthestStrike"):
            db.set_btc_strangle_setting(key, "1" if value else "0")
        elif key in ("mode", "missingStrike") or key in _RUNTIME_KEYS:
            db.set_btc_strangle_setting(key, str(value))
    return get_runtime_config()


def _parse_hhmm(value: str) -> dtime:
    hour, minute = value.split(":")
    return dtime(int(hour), int(minute))


# ---------------------------------------------------------------- market data


async def _chain(max_age_seconds: float = 5.0) -> dict[str, Any]:
    if _last_chain["chain"] and time.monotonic() - _last_chain["at"] < max_age_seconds:
        return _last_chain["chain"]
    tickers = await DeltaExchangeService().get_option_tickers("BTC")
    chain = engine.parse_chain(tickers)
    _last_chain.update(at=time.monotonic(), chain=chain)
    return chain


def _quote_index(chain: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index = {}
    for expiry in chain["expiries"].values():
        for sides in expiry["strikes"].values():
            for quote in sides.values():
                index[quote["symbol"]] = quote
    return index


def _next_entry_epoch(config: dict[str, Any]) -> int:
    """The next scheduled entry moment (today's if still ahead/in the window)."""
    now = datetime.now(IST)
    entry = datetime.combine(now.date(), _parse_hhmm(config["entryTime"]), tzinfo=IST)
    window_end = datetime.combine(now.date(), _parse_hhmm(config["entryWindowEnd"]), tzinfo=IST)
    if now > window_end:
        entry += timedelta(days=1)
    return int(max(entry, now).timestamp())


def _plan(chain: dict[str, Any], config: dict[str, Any], at_epoch: int) -> dict[str, Any]:
    spot = chain.get("spot")
    if not spot:
        return {"error": "BTC spot unavailable from Delta."}
    expiry = engine.pick_expiry(chain, at_epoch, int(config["expiryOffset"]))
    if not expiry:
        target = (datetime.fromtimestamp(at_epoch, IST) + timedelta(days=int(config["expiryOffset"]))).strftime("%d %b")
        return {"error": f"Delta has no BTC option expiry listed for {target} (entry date + {config['expiryOffset']} days)."}
    plan = engine.plan_strangle(expiry, spot, float(config["multiplier"]))
    plan["variant"] = "strangle"
    if "error" in plan and config["missingStrike"] == "farthest":
        fallback = _plan_farthest(expiry, spot, float(config["multiplier"]))
        if fallback:
            plan = {**fallback, "variant": "farthest"}
    elif "error" in plan and config["missingStrike"] == "one_side":
        single = engine.plan_one_side(expiry, spot, float(config["multiplier"]))
        if "error" not in single:
            plan = {**single, "variant": "one_side"}
    if "error" in plan:
        plan["expiryCode"] = expiry["code"]
        return plan
    for option_type, quote in plan["legs"].items():
        entry = quote.get("bid") or quote.get("mark") or 0
        plan.setdefault("preview", {})[option_type] = {
            "entryPrice": entry,
            "slPrice": engine.stop_price(entry, float(config["stopLossPercent"])) if entry else None,
            "distancePercent": round(abs(quote["strike"] - spot) / spot * 100, 2),
        }
    contracts = int(config["contracts"])
    credit = sum(v["entryPrice"] for v in plan["preview"].values())
    plan["contracts"] = contracts
    plan["estimatedCredit"] = round(credit * contracts * engine.CONTRACT_VALUE_BTC, 2)
    plan["hoursToSettlement"] = round((plan["settlement"] - at_epoch) / 3600, 1)
    return plan


def _variant_note(plan: dict[str, Any]) -> str | None:
    if plan.get("variant") == "farthest":
        return "Formula strike not listed -- used farthest listed strike."
    if plan.get("variant") == "one_side":
        side, other = plan["missingSide"], "CE" if plan["missingSide"] == "PE" else "PE"
        return (f"One-sided: {side} formula strike not listed (needed {'<=' if side == 'PE' else '>='} "
                f"{plan['missingTarget']:.0f}, farthest listed {plan['missingFarthestListed'] or 0:.0f}) -- sold the {other} leg only.")
    return None


def _plan_farthest(expiry: dict[str, Any], spot: float, multiplier: float) -> dict[str, Any] | None:
    """Fallback (opt-in): when the formula strike isn't listed, use the
    farthest listed strike on that side and flag it."""
    strikes = expiry["strikes"]
    base = engine.plan_strangle(expiry, spot, 0.0)
    if "error" in base:
        return None
    distance = multiplier * base["straddle"]
    calls = sorted(k for k, s in strikes.items() if "CE" in s and k > spot)
    puts = sorted(k for k, s in strikes.items() if "PE" in s and k < spot)
    if not calls or not puts:
        return None
    call_k = next((k for k in calls if k >= spot + distance), calls[-1])
    put_k = next((k for k in reversed(puts) if k <= spot - distance), puts[0])
    return {
        **base,
        "multiplier": multiplier,
        "distance": round(distance, 2),
        "callTarget": round(spot + distance, 2),
        "putTarget": round(spot - distance, 2),
        "legs": {"CE": strikes[call_k]["CE"], "PE": strikes[put_k]["PE"]},
        "fallback": True,
    }


async def preview() -> dict[str, Any]:
    config = get_runtime_config()
    try:
        chain = await _chain()
    except Exception as exc:
        return {"error": f"Delta option chain unavailable: {exc}", "config": config}
    at = _next_entry_epoch(config)
    plan = _plan(chain, config, at)
    plan["entryAt"] = at
    plan["config"] = config
    return plan


# ---------------------------------------------------------------- live orders


def _client_id(trade_id: int, leg_id: int, purpose: str) -> str:
    return f"BTCSS-{trade_id}-{leg_id}-{purpose}-{int(time.time()) % 100000}"[:32]


async def _wait_for_fill(delta: DeltaExchangeService, order_id: Any, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    order: dict[str, Any] = {}
    while time.monotonic() < deadline:
        order = await delta.get_order(order_id)
        if order.get("state") in ("closed", "cancelled") or float(order.get("unfilled_size") or 0) == 0:
            return order
        await asyncio.sleep(2)
    return order


def _filled(order: dict[str, Any]) -> tuple[int, float | None]:
    size = int(float(order.get("size") or 0))
    unfilled = int(float(order.get("unfilled_size") or 0))
    price = engine._num(order.get("average_fill_price"))
    return max(size - unfilled, 0), price


async def _live_sell_leg(delta: DeltaExchangeService, trade_id: int, leg_id: int, quote: dict[str, Any], contracts: int, settings: Settings) -> dict[str, Any]:
    bid = quote.get("bid")
    if not bid:
        return {"filled": 0, "error": "no bid to sell into"}
    order = await delta.place_order(
        product_id=quote["productId"], size=contracts, side="sell", order_type="limit_order",
        limit_price=str(bid), client_order_id=_client_id(trade_id, leg_id, "E"),
    )
    order_id = order.get("id")
    final = await _wait_for_fill(delta, order_id, settings.btc_strangle_entry_fill_timeout_seconds)
    if final.get("state") not in ("closed", "cancelled"):
        try:
            await delta.cancel_order(order_id, quote["productId"])
        except DeltaExchangeError:
            pass
        final = await delta.get_order(order_id)
    filled, price = _filled(final)
    return {"filled": filled, "price": price, "orderId": str(order_id)}


async def _live_buy_back(delta: DeltaExchangeService, leg: dict[str, Any], purpose: str) -> dict[str, Any]:
    if leg.get("slOrderId"):
        try:
            await delta.cancel_order(leg["slOrderId"], leg["productId"])
        except DeltaExchangeError as exc:
            # Already triggered/filled -- re-read it so we don't double-buy.
            sl = await delta.get_order(leg["slOrderId"])
            filled, price = _filled(sl)
            if filled:
                return {"filled": filled, "price": price, "orderId": str(leg["slOrderId"]), "reason": "stop_loss"}
            logger.warning("btc_strangle: cancel SL %s failed: %s", leg["slOrderId"], exc)
    order = await delta.place_order(
        product_id=leg["productId"], size=int(leg["contracts"]), side="buy", order_type="market_order",
        reduce_only=True, client_order_id=_client_id(leg["tradeId"], leg["id"], purpose),
    )
    final = await _wait_for_fill(delta, order.get("id"), 20)
    filled, price = _filled(final)
    return {"filled": filled, "price": price, "orderId": str(order.get("id"))}


# ---------------------------------------------------------------- entry


async def enter_trade(trigger: str = "scheduled") -> dict[str, Any]:
    settings = get_settings()
    config = get_runtime_config()
    mode = config["mode"]
    async with _lock:
        if mode == "live":
            blocked = await _live_entry_block(settings, config)
            if blocked:
                await _notify_once("live-blocked", f"BTC Strangle: live entry blocked -- {blocked}")
                return {"status": "blocked", "message": blocked}
        chain = await _chain(max_age_seconds=0)
        now = int(time.time())
        plan = _plan(chain, config, now)
        if "error" in plan:
            await _notify_once("no-trade", f"BTC Strangle: no trade yet -- {plan['error']} (retrying until the entry window closes)")
            return {"status": "skipped", "message": plan["error"]}

        session_date = now_ist().date().isoformat()
        trade_id = db.create_btc_strangle_trade(
            mode=mode, session_date=session_date, expiry_code=plan["expiryCode"], settlement_time=plan["settlement"],
            entry_time=now, spot=plan["spot"], atm_strike=plan["atmStrike"], straddle=plan["straddle"],
            multiplier=plan["multiplier"], distance=plan["distance"], stop_loss_percent=config["stopLossPercent"],
            contracts=int(config["contracts"]), status="OPEN", trigger=trigger, variant=plan.get("variant", "strangle"),
            notes=_variant_note(plan),
        )
        delta = DeltaExchangeService(settings)
        results = []
        for option_type in [t for t in ("PE", "CE") if t in plan["legs"]]:
            quote = plan["legs"][option_type]
            leg_id = db.create_btc_strangle_leg(
                trade_id=trade_id, option_type=option_type, symbol=quote["symbol"], product_id=quote["productId"],
                strike=quote["strike"], requested_contracts=int(config["contracts"]), contracts=0, status="PENDING",
            )
            if mode == "paper":
                price = quote.get("bid") or quote.get("mark")
                filled = int(config["contracts"]) if price else 0
                result = {"filled": filled, "price": price, "orderId": None}
            else:
                try:
                    result = await _live_sell_leg(delta, trade_id, leg_id, quote, int(config["contracts"]), settings)
                except Exception as exc:
                    result = {"filled": 0, "error": str(exc)}
            results.append((option_type, leg_id, quote, result))
            await _record_entry(trade_id, leg_id, quote, result, config, plan["spot"], mode, delta, settings)

        legs = db.get_btc_strangle_trade(trade_id)["legs"]
        if not any(leg["status"] == "OPEN" for leg in legs):
            db.update_btc_strangle_trade(trade_id, status="FAILED", closed_at=int(time.time()))
        trade = db.get_btc_strangle_trade(trade_id)
    await _notify(_entry_message(trade, plan))
    return {"status": "entered", "trade": trade}


async def _record_entry(
    trade_id: int, leg_id: int, quote: dict[str, Any], result: dict[str, Any], config: dict[str, Any],
    spot: float, mode: str, delta: DeltaExchangeService, settings: Settings,
) -> None:
    filled, price = int(result.get("filled") or 0), result.get("price")
    if not filled or not price:
        db.update_btc_strangle_leg(leg_id, status="NOT_FILLED", error=result.get("error") or "entry order not filled")
        return
    sl = engine.stop_price(price, float(config["stopLossPercent"]))
    values: dict[str, Any] = dict(
        contracts=filled, entry_price=price, sl_price=sl, status="OPEN", entry_order_id=result.get("orderId"),
        entry_fee=_fee(price, filled, spot, settings), last_mark=quote.get("mark"), last_bid=quote.get("bid"),
        last_ask=quote.get("ask"), last_update=int(time.time()),
    )
    db.update_btc_strangle_leg(leg_id, **values)
    if mode != "live":
        return
    try:
        stop = await delta.place_stop_loss_order(
            product_id=quote["productId"], size=filled, side="buy", stop_price=str(sl),
            client_order_id=_client_id(trade_id, leg_id, "SL"),
        )
        db.update_btc_strangle_leg(leg_id, sl_order_id=str(stop.get("id")))
    except Exception as exc:
        # Never leave a short option without its stop: buy it straight back.
        leg = next(l for l in db.get_btc_strangle_trade(trade_id)["legs"] if l["id"] == leg_id)
        await _notify(f"BTC Strangle: stop loss could not be placed for {quote['symbol']} ({exc}) -- buying the leg back.")
        back = await _live_buy_back(delta, leg, "X")
        _close_leg(leg, back.get("price") or price, "sl_place_failed", back.get("orderId"), spot, settings,
                   error=f"stop order failed: {exc}")


async def _live_entry_block(settings: Settings, config: dict[str, Any]) -> str | None:
    if not settings.btc_strangle_live_order_enabled:
        return "BTC_STRANGLE_LIVE_ORDER_ENABLED is false on the server."
    if not (settings.delta_exchange_api_key and settings.delta_exchange_api_secret):
        return "Delta API credentials are not configured."
    try:
        balances = await DeltaExchangeService(settings).get_wallet_balances()
    except Exception as exc:
        return f"could not read the Delta wallet: {exc}"
    usd = next((row for row in balances if row.get("asset_symbol") == "USD"), None)
    available = engine._num((usd or {}).get("available_balance")) or 0.0
    if available < float(config["minAvailableBalance"]):
        return f"available balance ${available:,.2f} is below the minimum ${float(config['minAvailableBalance']):,.2f}."
    return None


def _fee(price: float, contracts: int, spot: float, settings: Settings) -> float:
    return engine.fee(
        price, contracts, spot, taker_rate=settings.btc_strangle_taker_fee_rate,
        premium_cap=settings.btc_strangle_premium_fee_cap, gst_rate=settings.btc_strangle_gst_rate,
    )


def _close_leg(
    leg: dict[str, Any], price: float, reason: str, order_id: str | None, spot: float, settings: Settings,
    *, error: str | None = None, charge_fee: bool = True,
) -> None:
    db.update_btc_strangle_leg(
        leg["id"], status="CLOSED", exit_price=price, exit_time=int(time.time()), exit_reason=reason,
        exit_order_id=order_id, exit_fee=_fee(price, int(leg["contracts"]), spot, settings) if charge_fee else 0.0,
        error=error,
    )


# ---------------------------------------------------------------- monitoring


async def monitor_once() -> None:
    settings = get_settings()
    config = get_runtime_config()
    async with _lock:
        open_trades = db.list_btc_strangle_trades(status="OPEN", limit=50)
        if open_trades:
            chain = await _chain(max_age_seconds=0)
            quotes = _quote_index(chain)
            spot = chain.get("spot") or 0.0
            delta = DeltaExchangeService(settings)
            for trade in open_trades:
                await _manage_trade(trade, quotes, spot, config, delta, settings)

    now = datetime.now(IST)
    in_window = _parse_hhmm(config["entryTime"]) <= now.time() <= _parse_hhmm(config["entryWindowEnd"])
    if config["enabled"] and in_window and not db.has_btc_strangle_trade_for_session(now.date().isoformat(), config["mode"]):
        await enter_trade("scheduled")


async def _manage_trade(
    trade: dict[str, Any], quotes: dict[str, dict[str, Any]], spot: float, config: dict[str, Any],
    delta: DeltaExchangeService, settings: Settings,
) -> None:
    now = int(time.time())
    settlement = int(trade["settlementTime"])
    exit_at = _expiry_exit_epoch(settlement, config["expiryExitTime"])
    for leg in trade["legs"]:
        if leg["status"] != "OPEN":
            continue
        quote = quotes.get(leg["symbol"]) or {}
        if quote:
            db.update_btc_strangle_leg(
                leg["id"], last_mark=quote.get("mark"), last_bid=quote.get("bid"), last_ask=quote.get("ask"), last_update=now,
            )
        mark = quote.get("mark")

        if now >= settlement + SETTLEMENT_GRACE_SECONDS:
            value = engine.intrinsic(leg["optionType"], float(leg["strike"]), spot)
            if trade["mode"] == "live" and leg.get("slOrderId"):
                sl = await _safe_get_order(delta, leg["slOrderId"])
                filled, price = _filled(sl) if sl else (0, None)
                if filled:
                    _close_leg(leg, price, "stop_loss", leg["slOrderId"], spot, settings)
                    await _notify(f"BTC Strangle: {leg['symbol']} stop loss filled @ {price}")
                    continue
            _close_leg(leg, value, "expired", None, spot, settings, charge_fee=False)
            continue

        if trade["mode"] == "paper":
            if mark is not None and leg["slPrice"] is not None and mark >= float(leg["slPrice"]):
                fill = quote.get("ask") or mark
                _close_leg(leg, fill, "stop_loss", None, spot, settings)
                await _notify(f"BTC Strangle (paper): {leg['symbol']} stop loss hit -- mark {mark:.1f} >= {leg['slPrice']:.1f}, bought back @ {fill:.1f}")
                continue
        else:
            sl = await _safe_get_order(delta, leg["slOrderId"]) if leg.get("slOrderId") else None
            if sl:
                filled, price = _filled(sl)
                if filled and sl.get("state") == "closed":
                    _close_leg(leg, price or mark or 0, "stop_loss", leg["slOrderId"], spot, settings)
                    await _notify(f"BTC Strangle: {leg['symbol']} stop loss filled @ {price}")
                    continue
                if sl.get("state") == "cancelled" and not leg.get("error"):
                    db.update_btc_strangle_leg(leg["id"], error="Stop order was cancelled outside the app -- leg unprotected.")
                    await _notify(f"⚠️ BTC Strangle: stop order for {leg['symbol']} was cancelled on Delta -- the leg has NO stop. Check it now.")

        if exit_at <= now < settlement:
            buyback_value = quote.get("ask") or mark
            if buyback_value is not None and mark is not None and mark > float(config["buybackThreshold"]):
                if trade["mode"] == "paper":
                    _close_leg(leg, buyback_value, "expiry_buyback", None, spot, settings)
                else:
                    back = await _live_buy_back(delta, leg, "XB")
                    _close_leg(leg, back.get("price") or buyback_value, back.get("reason") or "expiry_buyback", back.get("orderId"), spot, settings)
                await _notify(f"BTC Strangle: {leg['symbol']} bought back before expiry @ {buyback_value:.1f} (mark {mark:.1f} > ${config['buybackThreshold']})")

    await _finalize_if_done(int(trade["id"]))


async def _finalize_if_done(trade_id: int) -> None:
    refreshed = db.get_btc_strangle_trade(trade_id)
    if refreshed and refreshed["status"] == "OPEN" and all(leg["status"] != "OPEN" for leg in refreshed["legs"]):
        db.update_btc_strangle_trade(trade_id, status="CLOSED", closed_at=int(time.time()))
        summary = summarize_trade(db.get_btc_strangle_trade(trade_id))
        await _notify(
            f"BTC Strangle #{trade_id} ({summary['mode']}) closed: gross ${summary['grossPnl']:.2f}, "
            f"fees ${summary['fees']:.2f}, net ${summary['netPnl']:.2f}"
        )


async def _safe_get_order(delta: DeltaExchangeService, order_id: Any) -> dict[str, Any] | None:
    try:
        return await delta.get_order(order_id)
    except Exception as exc:
        logger.warning("btc_strangle: get_order %s failed: %s", order_id, exc)
        return None


def _expiry_exit_epoch(settlement: int, exit_time: str) -> int:
    settle_ist = datetime.fromtimestamp(settlement, IST)
    exit_dt = datetime.combine(settle_ist.date(), _parse_hhmm(exit_time), tzinfo=IST)
    return int(exit_dt.timestamp())


async def close_leg_now(leg_id: int) -> dict[str, Any]:
    """Manual buy-back of one leg (paper: at ask; live: cancels its stop
    first, then a reduce-only market buy)."""
    settings = get_settings()
    async with _lock:
        trade = next((t for t in db.list_btc_strangle_trades(status="OPEN", limit=50) if any(l["id"] == leg_id for l in t["legs"])), None)
        if not trade:
            return {"status": "blocked", "message": "Leg is not open."}
        leg = next(l for l in trade["legs"] if l["id"] == leg_id)
        if leg["status"] != "OPEN":
            return {"status": "blocked", "message": "Leg is not open."}
        chain = await _chain(max_age_seconds=0)
        quote = _quote_index(chain).get(leg["symbol"]) or {}
        spot = chain.get("spot") or 0.0
        if trade["mode"] == "paper":
            price = quote.get("ask") or quote.get("mark") or 0
            _close_leg(leg, price, "manual", None, spot, settings)
        else:
            back = await _live_buy_back(DeltaExchangeService(settings), leg, "M")
            price = back.get("price") or quote.get("mark") or 0
            _close_leg(leg, price, back.get("reason") or "manual", back.get("orderId"), spot, settings)
    await _finalize_if_done(int(trade["id"]))
    return {"status": "closed", "price": price}


# ---------------------------------------------------------------- reporting


def summarize_trade(trade: dict[str, Any]) -> dict[str, Any]:
    gross = 0.0
    fees = 0.0
    credit = 0.0
    for leg in trade["legs"]:
        if not leg["entryPrice"] or not leg["contracts"]:
            continue
        contracts = int(leg["contracts"])
        credit += float(leg["entryPrice"]) * contracts * engine.CONTRACT_VALUE_BTC
        if leg["status"] == "CLOSED":
            current = float(leg["exitPrice"] or 0)
            leg["pnl"] = engine.leg_pnl(float(leg["entryPrice"]), current, contracts)
        else:
            current = float(leg["lastAsk"] or leg["lastMark"] or leg["entryPrice"])
            leg["pnl"] = engine.leg_pnl(float(leg["entryPrice"]), current, contracts)
        leg["pnlPercent"] = round((float(leg["entryPrice"]) - current) / float(leg["entryPrice"]) * 100, 1)
        gross += leg["pnl"]
        fees += float(leg["entryFee"] or 0) + float(leg["exitFee"] or 0)
    trade["credit"] = round(credit, 2)
    trade["grossPnl"] = round(gross, 2)
    trade["fees"] = round(fees, 2)
    trade["netPnl"] = round(gross - fees, 2)
    return trade


def list_trades() -> list[dict[str, Any]]:
    return [summarize_trade(t) for t in db.list_btc_strangle_trades(limit=500)]


async def chart(trade_id: int, resolution: str = "5m") -> dict[str, Any]:
    """Combined premium of the trade's legs (mark candles; a closed leg is
    held at its exit price) and its VWAP from traded option volume."""
    trade = db.get_btc_strangle_trade(trade_id)
    if not trade:
        return {"error": "trade not found", "points": []}
    delta = DeltaExchangeService()
    start = int(trade["entryTime"]) - 300
    end = min(int(time.time()), int(trade["settlementTime"]))
    per_leg = []
    for leg in trade["legs"]:
        if not leg["entryPrice"]:
            continue
        marks = await delta.get_candles(f"MARK:{leg['symbol']}", resolution, start, end)
        try:
            trades = await delta.get_candles(leg["symbol"], resolution, start, end)
        except DeltaExchangeError:
            trades = []
        per_leg.append((leg, {int(c["time"]): float(c["close"]) for c in marks}, {int(c["time"]): float(c.get("volume") or 0) for c in trades}))
    times = sorted({t for _, marks, _ in per_leg for t in marks})
    points = []
    cum_pv = cum_v = 0.0
    last: dict[int, float] = {}
    for t in times:
        total, volume = 0.0, 0.0
        for leg, marks, vols in per_leg:
            if leg["exitTime"] and t > int(leg["exitTime"]):
                total += float(leg["exitPrice"] or 0)
                continue
            if t in marks:
                last[leg["id"]] = marks[t]
            total += last.get(leg["id"], float(leg["entryPrice"]))
            volume += vols.get(t, 0.0)
        weight = volume if volume > 0 else 1.0
        cum_pv += total * weight
        cum_v += weight
        points.append({"time": t, "price": round(total, 2), "vwap": round(cum_pv / cum_v, 2)})
    credit = sum(float(l["entryPrice"]) for l, _, _ in per_leg)
    return {"tradeId": trade_id, "points": points, "entryCredit": round(credit, 2)}


SPOT_INDEX_SYMBOL = ".DEXBTUSD"  # Delta's BTC spot index -- what the options settle against
SPOT_CHART_WINDOW_HOURS = {"1m": 6, "5m": 48, "15m": 120, "1h": 336}


async def spot_chart(resolution: str = "5m") -> dict[str, Any]:
    """BTC spot index candles (chronological) plus the short strikes of open
    strangles, for the reference chart at the bottom of the page."""
    end = int(time.time())
    start = end - SPOT_CHART_WINDOW_HOURS.get(resolution, 48) * 3600
    candles = await DeltaExchangeService().get_candles(SPOT_INDEX_SYMBOL, resolution, start, end)
    strikes = [
        {"strike": leg["strike"], "label": f"{leg['strike']:,.0f} {leg['optionType']} (#{trade['id']})", "optionType": leg["optionType"]}
        for trade in db.list_btc_strangle_trades(status="OPEN", limit=20)
        for leg in trade["legs"]
        if leg["status"] == "OPEN"
    ]
    return {
        "symbol": SPOT_INDEX_SYMBOL,
        "candles": sorted(
            ({"time": int(c["time"]), "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]} for c in candles),
            key=lambda c: c["time"],
        ),
        "strikes": strikes,
    }


# ---------------------------------------------------------------- loop / alerts


def _entry_message(trade: dict[str, Any], plan: dict[str, Any]) -> str:
    lines = [
        f"BTC Strangle #{trade['id']} entered ({trade['mode']}) -- expiry {trade['expiryCode']}",
        f"Spot {plan['spot']:.0f}, straddle {plan['straddle']:.0f} x {plan['multiplier']} = {plan['distance']:.0f} pts",
    ]
    for leg in trade["legs"]:
        if leg["status"] == "OPEN":
            lines.append(f"SELL {leg['contracts']} {leg['symbol']} @ {leg['entryPrice']} (SL {leg['slPrice']})")
        else:
            lines.append(f"{leg['symbol']}: {leg['status']} {leg.get('error') or ''}")
    if trade.get("notes"):
        lines.append(trade["notes"])
    return "\n".join(lines)


async def _notify_once(kind: str, text: str) -> None:
    key = f"{now_ist().date().isoformat()}:btc-strangle:{get_runtime_config()['mode']}:{kind}"
    if db.record_alert_once(key, {"text": text}):
        await _notify(text)


async def _notify(text: str) -> None:
    try:
        await TelegramNotifier().send(text)
    except Exception:
        logger.warning("btc_strangle: telegram send failed")


def start_btc_strangle_task() -> asyncio.Task | None:
    if not get_settings().btc_strangle_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_btc_strangle_task(task: asyncio.Task | None) -> None:
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
            logger.exception("btc_strangle: monitor iteration failed")
        await asyncio.sleep(max(get_settings().btc_strangle_poll_interval_seconds, 5))
