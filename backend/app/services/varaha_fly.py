"""Varaha -- Full Butterfly builder.

Scans every Full Butterfly (PE 1:2:1 below spot + CE 1:2:1 above spot) that
can be built from the live option chain for one expiry, and ranks them by how
small the central loss "V" is versus reward/risk. Recommendation only.

With both long legs near spot and wing ratios <= 1, the expiry payoff has a
closed form, which is what makes a brute-force scan cheap (D = total net
debit in points):

    central loss zone = [PE long - D, CE long + D]
    V width           = (CE long - PE long) + 2 * D
    max loss          = D                     (flat between the long strikes)
    peak profit       = inner wing - D        (at each short strike)
    outer breakevens  = 2*PE short - PE long + D  /  2*CE short - CE long - D
                        (open-ended if that side's tail credit, inner - outer, exceeds D)

The shortlist is then re-checked with the generic piecewise-linear payoff in
varaha_engine so the numbers shown are exact, not just the formula.
"""

from __future__ import annotations

import math
import time
from datetime import date
from typing import Any

from app.core.config import get_settings
from app.core.timeutil import now_ist
from app.services import varaha
from app.services import varaha_engine as engine
from app.services.charges import option_order_charges
from app.services.dhan import DhanService

STRIKE_STEP = 50.0
LONG_OFFSET_STEPS = 2
SHORT_DISTANCES = [float(d) for d in range(100, 1550, 50)]
WING_RATIOS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
CHAIN_CACHE_SECONDS = 60
EXPIRY_CACHE_SECONDS = 300
MAX_RESULTS = 30
MAX_SCATTER_POINTS = 600

_chain_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_expiry_cache: tuple[float, list[dict[str, Any]]] | None = None


async def _expiries(dhan: DhanService) -> list[dict[str, Any]]:
    global _expiry_cache
    if _expiry_cache and time.monotonic() - _expiry_cache[0] < EXPIRY_CACHE_SECONDS:
        return _expiry_cache[1]
    settings = get_settings()
    today = now_ist().date()
    raw = await dhan.expiry_list(settings.dhan_nifty_security_id, varaha.INDEX_SEGMENT)
    items = []
    for value in raw:
        try:
            expiry = date.fromisoformat(value)
        except ValueError:
            continue
        if expiry < today:
            continue
        # Every listed expiry is selectable (no DTE window here, unlike the
        # daily decision); 0/1-trading-day expiries are flagged in the UI.
        trading_dte = varaha._trading_days_until(today, expiry)
        items.append({"expiry": value, "dte": (expiry - today).days, "tradingDte": trading_dte})
    _expiry_cache = (time.monotonic(), items)
    return items


async def _chain(dhan: DhanService, expiry: str) -> dict[str, Any]:
    cached = _chain_cache.get(expiry)
    if cached and time.monotonic() - cached[0] < CHAIN_CACHE_SECONDS:
        return cached[1]
    settings = get_settings()
    chain = await dhan.option_chain(settings.dhan_nifty_security_id, varaha.INDEX_SEGMENT, expiry)
    spot = varaha._number(chain.get("last_price"))
    if not spot:
        raise RuntimeError(f"Option chain for {expiry} returned no spot price.")
    data = {
        "spot": spot,
        "takenAt": time.time(),
        "rows": varaha._trim_chain(chain, spot),
    }
    _chain_cache[expiry] = (time.monotonic(), data)
    return data


def _quotes_by_strike(rows: list[dict[str, Any]], key: str) -> dict[float, dict[str, Any]]:
    return {
        float(row["strike"]): row[key]
        for row in rows
        if row.get(key) and (row[key].get("ltp") or 0) > 0
    }


def _fill(quote: dict[str, Any], action: str) -> float:
    bid, ask = quote.get("bid"), quote.get("ask")
    if bid and ask and ask >= bid > 0:
        return float(ask) if action == "BUY" else float(bid)
    return float(quote["ltp"])


def _liquid(quote: dict[str, Any], settings: Any) -> bool:
    bid, ask = quote.get("bid"), quote.get("ask")
    if not (bid and ask):
        return False
    mid = (bid + ask) / 2
    return ask - bid <= max(settings.varaha_max_spread_points, mid * settings.varaha_max_spread_percent / 100)


def _side_candidates(
    quotes: dict[float, dict[str, Any]], atm: float, option_type: str, settings: Any, ratio_min: float, ratio_max: float,
    spot: float, short_min_pts: float, short_max_pts: float,
) -> list[dict[str, Any]]:
    """Every 1:2:1 on one side: long within +-2 strikes of ATM, short 100-1500
    points further OTM (and short_min..short_max points from spot, i.e. where
    the profit peak sits), hedge at a wing ratio in [ratio_min, ratio_max]."""
    direction = -1 if option_type == "PE" else 1
    sides = []
    for offset in range(-LONG_OFFSET_STEPS, LONG_OFFSET_STEPS + 1):
        long_strike = atm + offset * STRIKE_STEP
        long_q = quotes.get(long_strike)
        if not long_q:
            continue
        for inner in SHORT_DISTANCES:
            short_strike = long_strike + direction * inner
            short_q = quotes.get(short_strike)
            if not short_q or not short_min_pts <= abs(short_strike - spot) <= short_max_pts:
                continue
            seen_outer: set[float] = set()
            for ratio in WING_RATIOS:
                if not ratio_min - 1e-9 <= ratio <= ratio_max + 1e-9:
                    continue
                outer = max(STRIKE_STEP, round(inner * ratio / STRIKE_STEP) * STRIKE_STEP)
                if outer > inner or outer in seen_outer:
                    continue
                seen_outer.add(outer)
                hedge_strike = short_strike + direction * outer
                hedge_q = quotes.get(hedge_strike)
                if not hedge_q:
                    continue
                debit = _fill(long_q, "BUY") - 2 * _fill(short_q, "SELL") + _fill(hedge_q, "BUY")
                sides.append({
                    "long": long_strike,
                    "short": short_strike,
                    "hedge": hedge_strike,
                    "inner": inner,
                    "outer": outer,
                    "debit": debit,
                    "liquid": _liquid(long_q, settings) and _liquid(short_q, settings) and _liquid(hedge_q, settings),
                })
    return sides


def _prob_below(x: float, forward: float, vol_t: float) -> float:
    if x <= 0:
        return 0.0
    if vol_t <= 0:
        return 1.0 if forward < x else 0.0
    return engine._norm_cdf((math.log(x / forward) + 0.5 * vol_t * vol_t) / vol_t)


def _pop(pe: dict[str, Any], ce: dict[str, Any], debit: float, forward: float, vol_t: float) -> float:
    """Probability of expiring in a profit zone, lognormal at ATM IV (no skew)."""
    be_low, be_high = pe["long"] - debit, ce["long"] + debit
    pe_tail_open = pe["inner"] - pe["outer"] > debit
    ce_tail_open = ce["inner"] - ce["outer"] > debit
    left_start = 0.0 if pe_tail_open else 2 * pe["short"] - pe["long"] + debit
    right_end = math.inf if ce_tail_open else 2 * ce["short"] - ce["long"] - debit
    left = max(0.0, _prob_below(be_low, forward, vol_t) - _prob_below(left_start, forward, vol_t))
    right_top = 1.0 if right_end == math.inf else _prob_below(right_end, forward, vol_t)
    right = max(0.0, right_top - _prob_below(be_high, forward, vol_t))
    return left + right


def _legs(pe: dict[str, Any], ce: dict[str, Any], pe_q: dict[float, dict[str, Any]], ce_q: dict[float, dict[str, Any]], spot: float, em: float | None) -> list[dict[str, Any]]:
    legs = []
    for option_type, side, quotes in (("PE", pe, pe_q), ("CE", ce, ce_q)):
        for action, qty, strike in (("BUY", 1, side["long"]), ("SELL", 2, side["short"]), ("BUY", 1, side["hedge"])):
            q = quotes[strike]
            legs.append({
                "action": action,
                "qty": qty,
                "optionType": option_type,
                "strike": strike,
                "price": round(_fill(q, action), 2),
                "ltp": q["ltp"],
                "bid": q.get("bid"),
                "ask": q.get("ask"),
                "iv": q.get("iv"),
                "delta": q.get("delta"),
                "oi": q.get("oi"),
                "distance": round(strike - spot, 1),
                "distancePercent": round((strike - spot) / spot * 100, 2),
                "emMultiple": round((strike - spot) / em, 2) if em else None,
            })
    return legs


def _pareto(combos: list[dict[str, Any]]) -> set[int]:
    """Indices not dominated on (smaller V width, higher reward/risk)."""
    order = sorted(range(len(combos)), key=lambda i: (combos[i]["width"], -combos[i]["rr"]))
    best_rr = -math.inf
    frontier = set()
    for i in order:
        if combos[i]["rr"] > best_rr + 1e-9:
            frontier.add(i)
            best_rr = combos[i]["rr"]
    return frontier


SORT_KEYS = {
    "width": lambda c: (c["width"], -c["rr"]),
    "rr": lambda c: (-c["rr"], c["width"]),
    "pop": lambda c: (-c["pop"], c["width"]),
    "maxLoss": lambda c: (c["debit"], c["width"]),
    "maxProfit": lambda c: (-c["maxProfitPts"], c["width"]),
}


async def scan(
    *,
    expiry: str | None = None,
    symmetric: bool = False,
    long_placement: str = "any",
    centered: bool = True,
    min_short_em: float | None = 1.0,
    max_short_em: float | None = None,
    max_width: float | None = None,
    max_width_em: float | None = None,
    max_loss_inr: float | None = None,
    min_rr: float | None = None,
    min_max_profit_inr: float | None = None,
    min_pop: float | None = None,
    wing_ratio_min: float = 0.5,
    wing_ratio_max: float = 1.0,
    require_liquid: bool = True,
    frontier_only: bool = True,
    sort: str = "width",
) -> dict[str, Any]:
    settings = get_settings()
    dhan = DhanService(settings)
    config = varaha.get_runtime_config()
    lots, lot_size = int(config["lots"]), int(config["lotSize"])
    multiplier = lots * lot_size
    loss_limit = float(config["maxLossInr"])

    expiries = await _expiries(dhan)
    if not expiries:
        return {"error": "No NIFTY expiry available.", "expiries": []}
    default = next((e for e in expiries if e["tradingDte"] >= 2), expiries[0])
    chosen = next((e for e in expiries if e["expiry"] == expiry), default)
    chain = await _chain(dhan, chosen["expiry"])
    spot = chain["spot"]
    now = now_ist()
    market_open = now.weekday() < 5 and varaha.MARKET_OPEN <= now.time() <= varaha.MARKET_CLOSE
    expiry_block = {
        **chosen,
        "years": varaha._years_until_expiry(date.fromisoformat(chosen["expiry"])),
        "chain": chain["rows"],
    }
    straddle = engine.atm_straddle(expiry_block, spot)
    em = straddle["expectedMove"] if straddle else None
    atm_iv = straddle["atmIv"] if straddle else None
    ratio = engine.forward_ratio(expiry_block, spot)
    forward = spot * ratio
    vol_t = (atm_iv or 0) * math.sqrt(expiry_block["years"])
    atm = round(spot / STRIKE_STEP) * STRIKE_STEP

    pe_q = _quotes_by_strike(chain["rows"], "pe")
    ce_q = _quotes_by_strike(chain["rows"], "ce")
    short_min_pts = (min_short_em * em) if (min_short_em and em) else 0.0
    short_max_pts = (max_short_em * em) if (max_short_em and em) else math.inf
    pe_sides = _side_candidates(pe_q, atm, "PE", settings, wing_ratio_min, wing_ratio_max, spot, short_min_pts, short_max_pts)
    ce_sides = _side_candidates(ce_q, atm, "CE", settings, wing_ratio_min, wing_ratio_max, spot, short_min_pts, short_max_pts)
    check_liquidity = require_liquid and market_open
    if check_liquidity:
        pe_sides = [s for s in pe_sides if s["liquid"]]
        ce_sides = [s for s in ce_sides if s["liquid"]]

    width_cap = min(
        max_width if max_width else math.inf,
        (max_width_em * em) if (max_width_em and em) else math.inf,
    )
    loss_cap_pts = min(max_loss_inr or math.inf, loss_limit) / multiplier
    ce_by_shape: dict[tuple[float, float], list[dict[str, Any]]] = {}
    for ce in ce_sides:
        ce_by_shape.setdefault((ce["inner"], ce["outer"]), []).append(ce)

    scanned = 0
    combos: list[dict[str, Any]] = []
    for pe in pe_sides:
        partners = ce_by_shape.get((pe["inner"], pe["outer"]), []) if symmetric else ce_sides
        for ce in partners:
            if pe["long"] > ce["long"]:
                continue
            gap = ce["long"] - pe["long"]
            if long_placement == "atm" and not (pe["long"] == atm and ce["long"] == atm):
                continue
            if long_placement == "adjacent" and gap > STRIKE_STEP:
                continue
            scanned += 1
            debit = pe["debit"] + ce["debit"]
            if debit <= 0 or debit >= min(pe["inner"], ce["inner"]):
                continue  # need a real loss zone and a profit peak on both sides
            width = gap + 2 * debit
            if width > width_cap or debit > loss_cap_pts:
                continue
            if centered and not pe["long"] - debit <= spot <= ce["long"] + debit:
                continue  # spot must sit inside the central loss V, as in the classic shape
            max_profit_pts = max(pe["inner"], ce["inner"]) - debit
            rr = max_profit_pts / debit
            if min_rr and rr < min_rr:
                continue
            if min_max_profit_inr and max_profit_pts * multiplier < min_max_profit_inr:
                continue
            combos.append({"pe": pe, "ce": ce, "debit": debit, "width": width, "rr": rr, "maxProfitPts": max_profit_pts})

    for combo in combos:
        combo["pop"] = _pop(combo["pe"], combo["ce"], combo["debit"], forward, vol_t) if vol_t else 0.0
    if min_pop:
        combos = [c for c in combos if c["pop"] * 100 >= min_pop]

    frontier_idx = _pareto(combos)
    for i, combo in enumerate(combos):
        combo["frontier"] = i in frontier_idx
    pool = [c for c in combos if c["frontier"]] if frontier_only else combos
    pool.sort(key=SORT_KEYS.get(sort, SORT_KEYS["width"]))
    shortlisted = pool[:MAX_RESULTS]

    results = []
    for combo in shortlisted:
        results.append(_detail(combo, pe_q, ce_q, spot, em, expiry_block, ratio, multiplier, lots, lot_size, settings))

    step = max(1, len(combos) // MAX_SCATTER_POINTS)
    scatter = [
        {"width": round(c["width"], 1), "rr": round(c["rr"], 3), "frontier": c["frontier"]}
        for i, c in enumerate(combos) if c["frontier"] or i % step == 0
    ]
    warnings = []
    if chosen["tradingDte"] < 2:
        warnings.append(
            "This expiry has less than 2 trading days left -- gamma and theta are extreme and quotes can move fast."
        )
    if not market_open:
        warnings.append("Market closed -- quotes are last traded prices; bid/ask liquidity is not enforced.")
    if not vol_t:
        warnings.append("ATM IV unavailable -- probability of profit not computed.")
    return {
        "spot": spot,
        "forward": round(forward, 1),
        "expectedMove": em,
        "atmIv": atm_iv,
        "expiry": {k: chosen[k] for k in ("expiry", "dte", "tradingDte")},
        "shortRangePoints": [round(short_min_pts, 1), None if short_max_pts == math.inf else round(short_max_pts, 1)],
        "expiries": expiries,
        "quotesAt": chain["takenAt"],
        "marketOpen": market_open,
        "lots": lots,
        "lotSize": lot_size,
        "maxLossLimitInr": loss_limit,
        "scanned": scanned,
        "matched": len(combos),
        "frontierCount": len(frontier_idx),
        "results": results,
        "scatter": scatter,
        "warnings": warnings,
    }


def _detail(
    combo: dict[str, Any], pe_q: dict[float, dict[str, Any]], ce_q: dict[float, dict[str, Any]], spot: float,
    em: float | None, expiry_block: dict[str, Any], ratio: float, multiplier: int, lots: int, lot_size: int, settings: Any,
) -> dict[str, Any]:
    pe, ce = combo["pe"], combo["ce"]
    legs = _legs(pe, ce, pe_q, ce_q, spot, em)
    candidate = {
        "id": f"FB-{pe['hedge']:.0f}-{pe['short']:.0f}-{pe['long']:.0f}-{ce['long']:.0f}-{ce['short']:.0f}-{ce['hedge']:.0f}",
        "structure": "FULL_BUTTERFLY",
        "years": expiry_block["years"],
        "forwardRatio": ratio,
        "legs": legs,
    }
    kinks = sorted({leg["strike"] for leg in legs})
    low, high = min(kinks[0], spot) * 0.5, max(kinks[-1], spot) * 1.5
    breakevens = engine._breakevens(legs, low, high)
    values = [engine.expiry_pnl_points(legs, x) for x in [low, high, *kinks]]
    charges = sum(
        option_order_charges(
            premium=leg["price"], quantity=leg["qty"] * multiplier, side=leg["action"],
            exchange_segment=engine.OPTION_SEGMENT, settings=settings,
        )["total"]
        for leg in legs
    )
    return {
        "id": candidate["id"],
        "legs": legs,
        "netDebit": round(combo["debit"] * multiplier, 0),
        "netDebitPoints": round(combo["debit"], 2),
        "maxProfit": round(max(values) * multiplier, 0),
        "maxLoss": round(min(values) * multiplier, 0),
        "rewardRisk": round(combo["rr"], 2),
        "lossWidth": round(combo["width"], 1),
        "lossWidthEm": round(combo["width"] / em, 2) if em else None,
        "lossZone": [round(pe["long"] - combo["debit"], 1), round(ce["long"] + combo["debit"], 1)],
        "shortDistances": [round(spot - pe["short"], 1), round(ce["short"] - spot, 1)],
        "breakevens": breakevens,
        "zones": engine._payoff_zones(legs, breakevens, low, high),
        "pop": round(combo["pop"] * 100, 1),
        "frontier": combo["frontier"],
        "wingRatios": [round(pe["outer"] / pe["inner"], 2), round(ce["outer"] / ce["inner"], 2)],
        "innerWings": [pe["inner"], ce["inner"]],
        "longGap": ce["long"] - pe["long"],
        "charges": round(charges, 2),
        "lots": lots,
        "lotSize": lot_size,
        "payoff": engine.payoff_curve(candidate, spot, lot_size, lots, em),
    }
