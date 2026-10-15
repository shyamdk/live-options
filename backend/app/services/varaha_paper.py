"""Varaha paper trading -- trades each 15:00 Varaha decision automatically.

Policy (agreed 15 Oct 2026):
  direction UP    -> CE butterfly      (buy 1 / sell 2 / buy 1 calls)
  direction DOWN  -> PE butterfly
  no direction    -> defined-risk strangle (iron condor: short OTM CE/PE +
                     farther long wings)
The direction is Varaha's effective direction (engine call, or the day's
manual override). The candidate is the AI-ranked top one of that structure
from the recommendation; if the engine didn't build that structure today,
it is generated from the same snapshot and must pass every hard gate.

One position at a time, 5 lots. Exits (first to happen, checked every 30 s
in market hours on live quotes):
  butterflies  target +50% of max profit, stop -50% of the debit
  condor       target +50% of the credit, stop when it costs 2x the credit
               to close
  direction    at the next 15:00 decision, close if the direction flipped
               against the trade (butterfly: opposite direction; condor: any
               direction)
  time         15:15 on the trading day before expiry

Paper: buy at ask, sell at bid (LTP if no quote), app charge model. Live
(mode=live AND VARAHA_LIVE_ORDER_ENABLED AND LIVE_ORDER_ENABLED): market
orders, buys first, product MARGIN (positions are held overnight); a failed
leg unwinds the legs already filled and alerts on Telegram.
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
from app.db import sqlite as db
from app.services import varaha, varaha_engine as ve
from app.services.charges import option_order_charges
from app.services.dhan import DhanService
from app.services.orders import DhanOrderService
from app.services.telegram import TelegramNotifier

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
SEGMENT = "NSE_FNO"
POLL_SECONDS = 30
QUOTE_MAX_AGE = 2.0
STRUCTURE_FOR = {"UP": "CE_BUTTERFLY", "DOWN": "PE_BUTTERFLY", "NO_CLEAR_DIRECTION": "IRON_CONDOR"}
STRUCTURE_NAME = {"CE_BUTTERFLY": "CE butterfly", "PE_BUTTERFLY": "PE butterfly", "IRON_CONDOR": "Defined-risk strangle (iron condor)"}

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "mode": "paper",
    "lots": 5,
    "butterflyTargetPercent": 50.0,
    "butterflyStopPercent": 50.0,
    "condorTargetPercent": 50.0,
    "condorStopMultiple": 2.0,
    "exitTime": "15:15",
    "flipExit": True,
    "maxLossInr": 150000.0,
}

_lock = asyncio.Lock()


# ---------------------------------------------------------------- config


def get_config() -> dict[str, Any]:
    config: dict[str, Any] = {}
    for key, default in DEFAULTS.items():
        raw = db.get_varaha_setting(f"paper.{key}")
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
    config["lotSize"] = settings.varaha_lot_size
    config["decisionTime"] = settings.varaha_decision_time
    config["liveOrdersAllowed"] = bool(settings.varaha_live_order_enabled and settings.live_order_enabled)
    return config


def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if key not in DEFAULTS or value is None:
            continue
        if key == "mode":
            if value not in ("paper", "live"):
                raise ValueError("mode must be paper or live")
            settings = get_settings()
            if value == "live" and not (settings.varaha_live_order_enabled and settings.live_order_enabled):
                raise ValueError("Live orders are locked on the server (VARAHA_LIVE_ORDER_ENABLED=false).")
        elif key == "exitTime":
            datetime.strptime(str(value), "%H:%M")
        elif key not in ("enabled", "flipExit") and float(value) <= 0:
            raise ValueError(f"{key} must be positive")
        default = DEFAULTS[key]
        db.set_varaha_setting(f"paper.{key}", ("1" if value else "0") if isinstance(default, bool) else str(value))
    return get_config()


def _mode(config: dict[str, Any]) -> str:
    return "live" if config["mode"] == "live" and config["liveOrdersAllowed"] else "paper"


def _hhmm(value: str) -> dtime:
    return datetime.strptime(value, "%H:%M").time()


def market_open(now: datetime) -> bool:
    return now.weekday() < 5 and dtime(9, 15) <= now.time() <= dtime(15, 30)


def _exit_by(expiry: str, exit_time: str) -> int:
    day = date.fromisoformat(expiry) - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return int(datetime.combine(day, _hhmm(exit_time), tzinfo=IST).timestamp())


# ---------------------------------------------------------------- choosing the trade


def _effective(result: dict[str, Any]) -> str | None:
    direction = result.get("direction") or {}
    return direction.get("effective") or direction.get("classification")


def choose(rec: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None, str]:
    """(structure, candidate, explanation) for a stored recommendation."""
    result = rec.get("result") or {}
    effective = _effective(result)
    if not effective:
        return None, None, result.get("statusReason") or "No direction in the recommendation (market data unavailable)."
    structure = STRUCTURE_FOR.get(effective)
    if not structure:
        return None, None, f"Unknown direction {effective}."
    ranked = [c for c in result.get("candidates") or [] if c.get("structure") == structure]
    if ranked:
        c = ranked[0]
        why = f"AI rank #{c['aiRank']}" if c.get("aiRank") else f"engine rank #{c.get('fallbackRank', 1)}"
        return structure, c, f"{effective} -> {STRUCTURE_NAME[structure]}: {c.get('variantLabel')} ({why} among {len(ranked)})."
    full = db.get_varaha_recommendation(int(rec["id"]), include_snapshot=True) or {}
    snapshot = full.get("snapshot") or {}
    if not snapshot.get("spot"):
        return structure, None, f"{effective} -> {STRUCTURE_NAME[structure]}, but the snapshot has no market data."
    settings = get_settings()
    move = result.get("move") or {}
    raw = ve.generate_candidates(snapshot, [structure], move.get("expectedMove"))
    evaluated = [ve.evaluate_candidate(c, snapshot, move, settings) for c in raw]
    passed = sorted((c for c in evaluated if c["hardGatesPassed"]), key=lambda c: c["fallbackScore"], reverse=True)
    if not passed:
        return structure, None, f"{effective} -> {STRUCTURE_NAME[structure]}: no candidate passed the hard gates today."
    c = passed[0]
    return structure, c, f"{effective} -> {STRUCTURE_NAME[structure]}: {c.get('variantLabel')} (built for paper trading; best of {len(passed)})."


def _decision_summary(rec: dict[str, Any]) -> dict[str, Any]:
    result = rec.get("result") or {}
    move, direction = result.get("move") or {}, result.get("direction") or {}
    return {
        "recId": rec.get("id"), "trigger": rec.get("trigger"), "status": result.get("status"),
        "moveClass": move.get("classification"), "moveScore": move.get("moveScore"), "maxMoveScore": move.get("maxScore"),
        "expectedMove": move.get("expectedMove"),
        "direction": direction.get("classification"), "effective": _effective(result), "override": direction.get("manualOverride"),
        "bullish": direction.get("bullish"), "bearish": direction.get("bearish"), "neutral": direction.get("neutral"),
        "bullishConfidence": direction.get("bullishConfidence"), "bearishConfidence": direction.get("bearishConfidence"),
        "threshold": direction.get("threshold"),
        "engineStructure": result.get("selectedStructureLabel"),
    }


# ---------------------------------------------------------------- quotes and orders


async def _quotes(ids: list[str]) -> dict[str, dict[str, Any]]:
    data = await DhanService(get_settings()).market_quotes_by_segment({SEGMENT: [int(x) for x in ids]}, max_age_seconds=QUOTE_MAX_AGE)
    out = {}
    for sec, q in (data.get(SEGMENT) or {}).items():
        depth = (q or {}).get("depth") or {}
        buy = (depth.get("buy") or [{}])[0] or {}
        sell = (depth.get("sell") or [{}])[0] or {}
        out[str(sec)] = {"ltp": varaha._number(q.get("last_price")), "bid": varaha._number(buy.get("price")) or None,
                         "ask": varaha._number(sell.get("price")) or None}
    return out


def _fill(q: dict[str, Any] | None, side: str) -> float | None:
    if not q:
        return None
    bid, ask, ltp = q.get("bid"), q.get("ask"), q.get("ltp")
    if bid and ask and ask >= bid > 0:
        return float(ask) if side == "BUY" else float(bid)
    return float(ltp) if ltp else None


async def _order(security_id: str, side: str, qty: int, mode: str, quote: dict[str, Any] | None, tag: str) -> dict[str, Any]:
    price = _fill(quote, side)
    if mode != "live":
        return {"ok": price is not None, "price": price, "orderId": None, "note": None if price else "no quote"}
    orders = DhanOrderService(get_settings())
    result: dict[str, Any] = {}
    for attempt in range(3):
        result = await orders.place_market_order(transaction_type=side, exchange_segment=SEGMENT, security_id=security_id,
                                                 quantity=qty, correlation_id=f"VP{tag}{attempt}{int(time.time()) % 100000}",
                                                 product_type="MARGIN")
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
        traded = varaha._number((info or {}).get("averageTradedPrice"))
        if traded:
            break
    return {"ok": True, "price": traded or price, "orderId": order_id, "note": None if traded else "fill price not confirmed -- quote used"}


def _charges(price: float, qty: int, side: str) -> float:
    return float(option_order_charges(premium=max(price, 0.05), quantity=qty, side=side, exchange_segment=SEGMENT)["total"])


def _sign(action: str) -> int:
    return 1 if action == "BUY" else -1


# ---------------------------------------------------------------- entry / exit


async def _enter(rec: dict[str, Any], config: dict[str, Any], trigger: str) -> dict[str, Any]:
    structure, candidate, why = choose(rec)
    decision = _decision_summary(rec)
    if not candidate:
        _event(None, "no_entry", why)
        return {"status": "skipped", "message": why}
    lots, lot_size = int(config["lots"]), int(config["lotSize"])
    c_mult = int(candidate.get("lots") or 1) * int(candidate.get("lotSize") or lot_size)
    max_loss_pts = abs(float(candidate.get("maxLoss") or 0)) / c_mult if c_mult else None
    if max_loss_pts and max_loss_pts * lots * lot_size > float(config["maxLossInr"]):
        msg = f"{why} Skipped: max loss ₹{max_loss_pts * lots * lot_size:,.0f} at {lots} lots exceeds the ₹{config['maxLossInr']:,.0f} cap."
        _event(None, "no_entry", msg)
        return {"status": "skipped", "message": msg}
    mode = _mode(config)
    legs = candidate["legs"]
    quotes = await _quotes([str(l["securityId"]) for l in legs])
    ordered = sorted(legs, key=lambda l: 0 if l["action"] == "BUY" else 1)  # buys first (margin)
    fills: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for leg in ordered:
        q = quotes.get(str(leg["securityId"])) or {"ltp": leg.get("ltp"), "bid": leg.get("bid"), "ask": leg.get("ask")}
        qty = int(leg["qty"]) * lots * lot_size
        r = await _order(str(leg["securityId"]), leg["action"], qty, mode, q, f"E{leg['optionType'][0]}{int(leg['strike'])}")
        if not r["ok"]:
            if mode == "live":  # unwind whatever is already filled
                for done_leg, done_q, _ in fills:
                    back = "SELL" if done_leg["action"] == "BUY" else "BUY"
                    await _order(str(done_leg["securityId"]), back, int(done_leg["qty"]) * lots * lot_size, mode, done_q, "U")
                await _notify(f"🚨 Varaha paper/live entry failed on {leg['strike']:.0f} {leg['optionType']} ({r['note']}) -- filled legs were unwound. Check Dhan positions.")
            _event(None, "entry_failed", f"{why} Entry failed on {leg['strike']:.0f} {leg['optionType']}: {r['note']}")
            return {"status": "failed", "message": r["note"]}
        fills.append((leg, q, r))
    now = int(time.time())
    entry_value = round(sum(_sign(l["action"]) * int(l["qty"]) * float(r["price"]) for l, _, r in fills), 2)
    debit = entry_value > 0
    if debit:
        max_profit_pts = abs(float(candidate.get("maxProfit") or 0)) / c_mult if c_mult else None
        target = (max_profit_pts or 0) * float(config["butterflyTargetPercent"]) / 100
        stop = -entry_value * float(config["butterflyStopPercent"]) / 100
    else:
        credit = -entry_value
        max_profit_pts = credit
        target = credit * float(config["condorTargetPercent"]) / 100
        stop = -credit * (float(config["condorStopMultiple"]) - 1)
    spot = float(rec.get("result", {}).get("spot") or 0)
    charges = sum(_charges(float(r["price"]), int(l["qty"]) * lots * lot_size, l["action"]) for l, _, r in fills)
    trade_id = db.varaha_paper_insert("varaha_paper_trades", {
        "rec_id": rec.get("id"), "session_date": rec.get("sessionDate"), "mode": mode, "trigger": trigger, "structure": structure,
        "structure_label": STRUCTURE_NAME[structure], "variant_label": candidate.get("variantLabel"), "candidate_id": candidate.get("id"),
        "direction": decision["effective"] or "?", "move_class": decision["moveClass"], "decision": json.dumps({**decision, "why": why}),
        "expiry": candidate["expiry"], "exit_by": _exit_by(candidate["expiry"], config["exitTime"]), "entry_time": now,
        "entry_spot": spot, "lots": lots, "lot_size": lot_size, "entry_value": entry_value,
        "max_profit_points": round(max_profit_pts, 2) if max_profit_pts is not None else None,
        "max_loss_points": round(max_loss_pts, 2) if max_loss_pts is not None else None,
        "breakevens": json.dumps(candidate.get("breakevens") or []), "target_points": round(target, 2), "stop_points": round(stop, 2),
        "status": "OPEN", "charges": round(charges, 2), "last_value": entry_value, "last_spot": spot, "last_update": now,
        "best_points": 0.0, "worst_points": 0.0,
    })
    for leg, q, r in fills:
        db.varaha_paper_insert("varaha_paper_legs", {
            "trade_id": trade_id, "action": leg["action"], "option_type": leg["optionType"], "strike": leg["strike"],
            "ratio": int(leg["qty"]), "quantity": int(leg["qty"]) * lots * lot_size, "security_id": str(leg["securityId"]),
            "entry_price": r["price"], "entry_bid": q.get("bid"), "entry_ask": q.get("ask"), "entry_ltp": q.get("ltp"),
            "entry_order_id": r["orderId"], "last_ltp": q.get("ltp"), "last_bid": q.get("bid"), "last_ask": q.get("ask"),
            "iv": leg.get("iv"), "delta": leg.get("delta"),
        })
    db.add_varaha_paper_mark(trade_id, now, 0.0, spot)
    legs_text = " · ".join(f"{l['action']} {int(l['qty']) * lots}L {l['strike']:.0f}{l['optionType']} @ {float(r['price']):.2f}" for l, _, r in fills)
    kind = f"debit {entry_value:.2f}" if debit else f"credit {-entry_value:.2f}"
    text = (f"#{trade_id} {STRUCTURE_NAME[structure]} ({decision['effective']}, move {decision['moveClass']}) exp {candidate['expiry']} · "
            f"{kind} pts (₹{abs(entry_value) * lots * lot_size:,.0f}) · target +{target:.2f} / stop {stop:.2f} pts · {legs_text}")
    _event(trade_id, "entry", f"{why} {text}")
    await _notify(f"🐗 Varaha {mode.upper()} {text}")
    return {"status": "entered", "tradeId": trade_id}


def _value(trade: dict[str, Any], quotes: dict[str, dict[str, Any]], *, executable: bool) -> float | None:
    total = 0.0
    for leg in trade["legs"]:
        q = quotes.get(str(leg["security_id"])) or {}
        if executable:  # what closing would get/pay: long legs sell at bid, short legs buy at ask
            px = _fill(q, "SELL" if leg["action"] == "BUY" else "BUY")
        else:
            px = q.get("ltp")
        if px is None:
            return None
        total += _sign(leg["action"]) * int(leg["ratio"]) * float(px)
    return round(total, 2)


async def _exit(trade: dict[str, Any], reason: str, quotes: dict[str, dict[str, Any]] | None = None) -> None:
    quotes = quotes or await _quotes([str(l["security_id"]) for l in trade["legs"]])
    now = int(time.time())
    charges = float(trade["charges"])
    exit_value = 0.0
    problems = []
    for leg in sorted(trade["legs"], key=lambda l: 0 if l["action"] == "SELL" else 1):  # buy back shorts first
        q = quotes.get(str(leg["security_id"])) or {"ltp": leg["last_ltp"]}
        side = "SELL" if leg["action"] == "BUY" else "BUY"
        r = await _order(str(leg["security_id"]), side, int(leg["quantity"]), trade["mode"], q, f"X{leg['id']}")
        price = r["price"] if r["price"] is not None else float(leg["last_ltp"] or leg["entry_price"])
        if not r["ok"] and trade["mode"] == "live":
            problems.append(f"{leg['strike']:.0f}{leg['option_type']}: {r['note']}")
        exit_value += _sign(leg["action"]) * int(leg["ratio"]) * float(price)
        charges += _charges(float(price), int(leg["quantity"]), side)
        db.varaha_paper_update("varaha_paper_legs", int(leg["id"]), exit_price=price, exit_bid=q.get("bid"), exit_ask=q.get("ask"),
                               exit_ltp=q.get("ltp"), exit_order_id=r["orderId"])
    spot = trade.get("last_spot")
    pnl_pts = round(exit_value - float(trade["entry_value"]), 2)
    db.varaha_paper_update("varaha_paper_trades", int(trade["id"]), status="CLOSED", exit_time=now, exit_reason=reason,
                           exit_value=round(exit_value, 2), exit_spot=spot, charges=round(charges, 2),
                           needs_attention="; ".join(problems) or None)
    db.add_varaha_paper_mark(int(trade["id"]), now, pnl_pts, spot)
    net = pnl_pts * int(trade["lots"]) * int(trade["lot_size"]) - charges
    text = f"#{trade['id']} {trade['structure_label']} closed ({reason}) · {pnl_pts:+.2f} pts · net ₹{net:,.0f}"
    _event(int(trade["id"]), "exit", text)
    await _notify(f"{'✅' if net >= 0 else '🛑'} Varaha {trade['mode'].upper()} {text}")
    if problems:
        await _notify(f"🚨 Varaha #{trade['id']}: exit legs failed ({'; '.join(problems)}) -- close them manually in Dhan.")


def _flip_reason(trade: dict[str, Any], effective: str | None) -> str | None:
    if not effective:
        return None
    if trade["structure"] == "CE_BUTTERFLY" and effective == "DOWN":
        return "direction flipped to DOWN at the daily decision"
    if trade["structure"] == "PE_BUTTERFLY" and effective == "UP":
        return "direction flipped to UP at the daily decision"
    if trade["structure"] == "IRON_CONDOR" and effective in ("UP", "DOWN"):
        return f"market no longer flat ({effective}) at the daily decision"
    return None


# ---------------------------------------------------------------- monitor


async def monitor_once() -> None:
    async with _lock:
        await _monitor()


async def _monitor() -> None:
    config = get_config()
    now = datetime.now(IST)
    if not market_open(now):
        return
    open_trades = db.list_varaha_paper_trades(status="OPEN")
    for trade in open_trades:
        quotes = await _quotes([str(l["security_id"]) for l in trade["legs"]])
        mark = _value(trade, quotes, executable=False)
        close_value = _value(trade, quotes, executable=True)
        spot = None
        try:
            idx = await DhanService(get_settings()).market_quotes_by_segment({"IDX_I": [int(get_settings().dhan_nifty_security_id)]},
                                                                              max_age_seconds=QUOTE_MAX_AGE)
            spot = varaha._number(((idx.get("IDX_I") or {}).get(str(get_settings().dhan_nifty_security_id)) or {}).get("last_price"))
        except Exception:
            pass
        for leg in trade["legs"]:
            q = quotes.get(str(leg["security_id"])) or {}
            if q.get("ltp"):
                db.varaha_paper_update("varaha_paper_legs", int(leg["id"]), last_ltp=q.get("ltp"), last_bid=q.get("bid"), last_ask=q.get("ask"))
        if mark is not None:
            pnl = round(mark - float(trade["entry_value"]), 2)
            db.varaha_paper_update("varaha_paper_trades", int(trade["id"]), last_value=mark, last_spot=spot or trade["last_spot"],
                                   last_update=int(time.time()), best_points=max(float(trade["best_points"] or 0), pnl),
                                   worst_points=min(float(trade["worst_points"] or 0), pnl))
            db.add_varaha_paper_mark(int(trade["id"]), int(time.time()) // 60 * 60, pnl, spot)
            trade["last_spot"] = spot or trade["last_spot"]
        reason = None
        exec_pnl = (close_value - float(trade["entry_value"])) if close_value is not None else None
        if int(time.time()) >= int(trade["exit_by"]):
            reason = "day-before-expiry exit"
        elif exec_pnl is not None and exec_pnl >= float(trade["target_points"]):
            reason = f"target reached ({exec_pnl:+.2f} pts)"
        elif exec_pnl is not None and exec_pnl <= float(trade["stop_points"]):
            reason = f"stop loss ({exec_pnl:+.2f} pts)"
        if reason:
            await _exit(trade, reason, quotes)

    # the daily decision: re-check the open trade, then enter if flat
    if now.time() < _hhmm(config["decisionTime"]):
        return
    rec = db.get_latest_varaha_recommendation(now.date().isoformat())
    if not rec or rec.get("trigger") == "manual" or str(rec["id"]) == (db.get_varaha_setting("paper.lastRecId") or ""):
        return
    db.set_varaha_setting("paper.lastRecId", str(rec["id"]))
    effective = _effective(rec.get("result") or {})
    for trade in db.list_varaha_paper_trades(status="OPEN"):
        reason = _flip_reason(trade, effective) if config["flipExit"] else None
        if reason:
            await _exit(trade, reason)
        else:
            _event(int(trade["id"]), "recheck", f"Daily decision {effective or '—'}: holding #{trade['id']} {trade['structure_label']}.")
    if config["enabled"] and not db.list_varaha_paper_trades(status="OPEN"):
        await _enter(rec, config, "decision")


async def enter_now() -> dict[str, Any]:
    async with _lock:
        if db.list_varaha_paper_trades(status="OPEN"):
            return {"status": "blocked", "message": "A Varaha paper trade is already open."}
        rec = db.get_latest_varaha_recommendation(datetime.now(IST).date().isoformat()) or db.get_latest_varaha_recommendation()
        if not rec:
            return {"status": "blocked", "message": "No Varaha recommendation yet -- run the daily decision first."}
        return await _enter(rec, get_config(), "manual")


async def close_now(trade_id: int) -> dict[str, Any]:
    async with _lock:
        trade = next((t for t in db.list_varaha_paper_trades(status="OPEN") if t["id"] == trade_id), None)
        if not trade:
            return {"status": "blocked", "message": "Trade is not open."}
        await _exit(trade, "closed manually")
    return {"status": "closed"}


# ---------------------------------------------------------------- reporting


def summarize(t: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
    mult = int(t["lots"]) * int(t["lot_size"])
    closed = t["status"] == "CLOSED"
    value = float(t["exit_value"] if closed and t["exit_value"] is not None else (t["last_value"] if t["last_value"] is not None else t["entry_value"]))
    pnl_pts = round(value - float(t["entry_value"]), 2)
    gross = pnl_pts * mult
    out = {
        "id": t["id"], "recId": t["rec_id"], "sessionDate": t["session_date"], "mode": t["mode"], "trigger": t["trigger"],
        "structure": t["structure"], "structureLabel": t["structure_label"], "variantLabel": t["variant_label"],
        "direction": t["direction"], "moveClass": t["move_class"], "decision": json.loads(t["decision"] or "{}"),
        "expiry": t["expiry"], "exitBy": t["exit_by"], "entryTime": t["entry_time"], "entrySpot": t["entry_spot"],
        "lots": t["lots"], "lotSize": t["lot_size"], "entryValue": t["entry_value"],
        "premiumType": "DEBIT" if float(t["entry_value"]) > 0 else "CREDIT",
        "maxProfitPoints": t["max_profit_points"], "maxLossPoints": t["max_loss_points"], "breakevens": json.loads(t["breakevens"] or "[]"),
        "targetPoints": t["target_points"], "stopPoints": t["stop_points"], "status": t["status"], "exitTime": t["exit_time"],
        "exitReason": t["exit_reason"], "exitValue": t["exit_value"], "exitSpot": t["exit_spot"], "lastValue": t["last_value"],
        "lastSpot": t["last_spot"], "lastUpdate": t["last_update"], "bestPoints": t["best_points"], "worstPoints": t["worst_points"],
        "needsAttention": t["needs_attention"], "pnlPoints": pnl_pts, "grossPnl": round(gross, 2), "charges": t["charges"],
        "netPnl": round(gross - float(t["charges"]), 2),
        "maxProfit": round(float(t["max_profit_points"] or 0) * mult, 0), "maxLoss": round(float(t["max_loss_points"] or 0) * mult, 0),
        "target": round(float(t["target_points"]) * mult, 0), "stop": round(float(t["stop_points"]) * mult, 0),
        "legs": [{
            "id": l["id"], "action": l["action"], "optionType": l["option_type"], "strike": l["strike"], "ratio": l["ratio"],
            "quantity": l["quantity"], "securityId": l["security_id"], "entryPrice": l["entry_price"], "entryBid": l["entry_bid"],
            "entryAsk": l["entry_ask"], "entryLtp": l["entry_ltp"], "entryOrderId": l["entry_order_id"], "exitPrice": l["exit_price"],
            "exitBid": l["exit_bid"], "exitAsk": l["exit_ask"], "exitLtp": l["exit_ltp"], "exitOrderId": l["exit_order_id"],
            "lastLtp": l["last_ltp"], "lastBid": l["last_bid"], "lastAsk": l["last_ask"], "iv": l["iv"], "delta": l["delta"],
            "pnl": round(_sign(l["action"]) * ((l["exit_price"] if closed and l["exit_price"] is not None else (l["last_ltp"] or l["entry_price"])) - l["entry_price"]) * l["quantity"], 2)
                   if l["entry_price"] is not None else None,
        } for l in t["legs"]],
    }
    if detail:
        out["marks"] = db.list_varaha_paper_marks(int(t["id"]))
        out["events"] = db.list_varaha_paper_events(int(t["id"]))
        spot = float(t["last_spot"] or t["entry_spot"] or 0)
        if spot:
            legs = [{"action": l["action"], "qty": l["ratio"], "optionType": l["option_type"], "strike": l["strike"],
                     "price": l["entry_price"], "iv": l["iv"]} for l in t["legs"]]
            years = varaha._years_until_expiry(date.fromisoformat(t["expiry"]))
            strikes = [l["strike"] for l in t["legs"]]
            lo, hi = min(min(strikes), spot) * 0.97, max(max(strikes), spot) * 1.03
            out["payoff"] = [{"price": round(lo + (hi - lo) * i / 160, 1),
                              "expiry": round(ve.expiry_pnl_points(legs, lo + (hi - lo) * i / 160) * mult),
                              "today": round(ve.today_pnl_points(legs, lo + (hi - lo) * i / 160, years) * mult)} for i in range(161)]
    return out


def state() -> dict[str, Any]:
    config = get_config()
    rec = db.get_latest_varaha_recommendation(datetime.now(IST).date().isoformat()) or db.get_latest_varaha_recommendation()
    preview = None
    if rec:
        structure, candidate, why = choose(rec)
        preview = {"decision": _decision_summary(rec), "sessionDate": rec.get("sessionDate"), "structure": structure,
                   "structureLabel": STRUCTURE_NAME.get(structure or ""), "why": why,
                   "candidate": {k: candidate.get(k) for k in ("id", "variantLabel", "expiry", "legs", "netPremiumPoints", "premiumType",
                                                               "maxProfit", "maxLoss", "breakevens", "lots", "lotSize", "rewardRisk")} if candidate else None}
    open_rows = db.list_varaha_paper_trades(status="OPEN")
    return {
        "config": config, "now": int(time.time()), "marketOpen": market_open(datetime.now(IST)), "mode": _mode(config),
        "preview": preview, "openTrade": summarize(open_rows[0], detail=True) if open_rows else None,
        "events": [{"time": e["time"], "kind": e["kind"], "text": e["text"], "tradeId": e["trade_id"]} for e in db.list_varaha_paper_events(limit=100)],
    }


async def spot_chart(days: int = 10) -> dict[str, Any]:
    """NIFTY 5-min closes covering the last `days` days (or back to the oldest
    open/recent trade), for the entry/exit chart."""
    today = datetime.now(IST).date()
    start = today - timedelta(days=max(1, min(days, 60)))
    candles = await DhanService(get_settings()).intraday_candles(
        str(get_settings().dhan_nifty_security_id), "IDX_I", "INDEX", "5", start.isoformat(), today.isoformat())
    return {"candles": sorted(({"time": int(c["time"]), "close": float(c["close"])} for c in candles), key=lambda c: c["time"])}


def list_trades() -> list[dict[str, Any]]:
    return [summarize(t) for t in db.list_varaha_paper_trades()]


def trade_detail(trade_id: int) -> dict[str, Any] | None:
    row = next((t for t in db.list_varaha_paper_trades() if t["id"] == trade_id), None)
    return summarize(row, detail=True) if row else None


def _event(trade_id: int | None, kind: str, text: str) -> None:
    db.varaha_paper_insert("varaha_paper_events", {"trade_id": trade_id, "time": int(time.time()), "kind": kind, "text": text})


async def _notify(text: str) -> None:
    try:
        await TelegramNotifier().send(text)
    except Exception:
        logger.warning("varaha_paper: telegram send failed")


def start_varaha_paper_task() -> asyncio.Task | None:
    if not get_settings().varaha_paper_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_varaha_paper_task(task: asyncio.Task | None) -> None:
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
            logger.exception("varaha_paper: monitor iteration failed")
        await asyncio.sleep(POLL_SECONDS)
