"""Manage Trades: payoff of each tag's open legs and the profit-booking suggestion.

Everything is counted from the start of today: legs opened today from their
fills, carried legs from yesterday's close (Dhan's carry-forward quantity and
the option's previous close), legs closed today at what they realized today.
The open legs are re-priced with Black-Scholes at each NIFTY / Sensex level
in a +-3% band, two ways:
  expiry  -- intrinsic value at expiry
  today   -- value at today's 15:30 close, each leg at its own implied
             volatility (solved from its live LTP)
"Max day profit" is the highest point of the today curve: the most the open
legs can show by today's close if the index sits at the best level for them.
When the tag's current open P&L reaches `thresholdPercent` of it, the page
suggests booking the profit (closing every leg of the tag); nothing is ever
closed without the user accepting. P&L is before charges.
"""

from __future__ import annotations

import math
from datetime import datetime, time as dtime
from typing import Any
from zoneinfo import ZoneInfo

from app.db import sqlite as db
from app.services import varaha_engine as ve

IST = ZoneInfo("Asia/Kolkata")
YEAR_SECONDS = 365 * 24 * 3600
MARKET_CLOSE = dtime(15, 30)
BAND_PERCENT = 3.0
POINTS = 241
DEFAULTS: dict[str, Any] = {"enabled": True, "thresholdPercent": 90.0}


def get_config() -> dict[str, Any]:
    enabled = db.get_manage_setting("suggest.enabled")
    threshold = db.get_manage_setting("suggest.thresholdPercent")
    return {
        "enabled": DEFAULTS["enabled"] if enabled is None else enabled == "1",
        "thresholdPercent": DEFAULTS["thresholdPercent"] if threshold is None else float(threshold),
    }


def update_config(enabled: bool | None, threshold_percent: float | None) -> dict[str, Any]:
    if threshold_percent is not None:
        if not 10 <= threshold_percent <= 100:
            raise ValueError("Threshold must be between 10% and 100%.")
        db.set_manage_setting("suggest.thresholdPercent", str(threshold_percent))
    if enabled is not None:
        db.set_manage_setting("suggest.enabled", "1" if enabled else "0")
    return get_config()


def _years(expiry: str, at: float) -> float:
    try:
        end = datetime.combine(datetime.fromisoformat(expiry[:10]).date(), MARKET_CLOSE, tzinfo=IST).timestamp()
    except ValueError:
        return 0.0
    return max(end - at, 0.0) / YEAR_SECONDS


def _implied_iv(price: float, spot: float, strike: float, years: float, is_call: bool) -> float | None:
    intrinsic = max(spot - strike, 0.0) if is_call else max(strike - spot, 0.0)
    if years <= 0 or price <= intrinsic + 0.05:
        return None
    lo, hi = 0.01, 3.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if ve.bs_price(spot, strike, years, mid, is_call) > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _day_terms(leg: dict[str, Any]) -> tuple[float, int] | str:
    """Today's P&L of a leg at option price V is `n * V + constant`.
    Carried legs start from yesterday's close, today's trades from their
    fill values; without Dhan's carry breakdown, count from the entry price."""
    n = int(leg.get("qty") or 0)
    if leg.get("carryQty") is None:
        realized = float(leg.get("realizedPnl") or 0)
        if not n:
            return realized, 0
        if leg.get("avgPrice") is None:
            return f"{leg.get('tradingSymbol')}: no average price"
        return realized - n * float(leg["avgPrice"]), n
    constant = float(leg["daySellValue"] or 0) - float(leg["dayBuyValue"] or 0)
    carry = int(leg["carryQty"])
    if carry:
        if leg.get("prevClose") is None:
            return f"{leg.get('tradingSymbol')}: no previous close for the carried quantity"
        constant -= carry * float(leg["prevClose"])
    return constant, n


def tag_payoff(legs: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any] | None:
    """Payoff of a tag counted from today's start, or None when nothing is open.
    `legs` are the tag's open and closed option rows."""
    open_legs = [l for l in legs if int(l.get("qty") or 0) != 0 and l.get("strikePrice") and l.get("optionSide") in ("CE", "PE")]
    if not open_legs:
        return None
    symbols = {str(l.get("symbol") or "").upper() for l in open_legs}
    spot = next((float(l["spotPrice"]) for l in open_legs if l.get("spotPrice")), None)
    if len(symbols) != 1 or not spot:
        return {"error": "Payoff needs the legs of one index with a live spot price."}
    now = now or datetime.now(IST)
    stamp = now.timestamp()
    close_at = max(datetime.combine(now.date(), MARKET_CLOSE, tzinfo=IST).timestamp(), stamp)

    constant = 0.0
    carried = False
    for l in legs:
        terms = _day_terms(l)
        if isinstance(terms, str):
            return {"error": terms}
        constant += terms[0]
        carried = carried or bool(l.get("carryQty"))
    rows = []
    for l in open_legs:
        strike = float(l["strikePrice"])
        is_call = l["optionSide"] == "CE"
        if l.get("ltp") is None:
            return {"error": f"{l.get('tradingSymbol')}: no live price."}
        expiry = str(l.get("expiry") or "")
        rows.append({
            "qty": int(l["qty"]), "strike": strike, "call": is_call, "ltp": float(l["ltp"]),
            "yearsClose": _years(expiry, close_at),
            "iv": _implied_iv(float(l["ltp"]), spot, strike, _years(expiry, stamp), is_call),
        })
    known = sorted(r["iv"] for r in rows if r["iv"])
    fallback = known[len(known) // 2] if known else 0.15
    for r in rows:
        if not r["iv"]:
            r["iv"] = fallback  # deep in the money / no time value left -- price at the tag's typical IV

    current = constant + sum(r["qty"] * r["ltp"] for r in rows)
    low, high = spot * (1 - BAND_PERCENT / 100), spot * (1 + BAND_PERCENT / 100)
    points = []
    for i in range(POINTS):
        price = low + (high - low) * i / (POINTS - 1)
        today = constant + sum(r["qty"] * ve.bs_price(price, r["strike"], r["yearsClose"], r["iv"], r["call"]) for r in rows)
        expiry = constant + sum(r["qty"] * (max(price - r["strike"], 0.0) if r["call"] else max(r["strike"] - price, 0.0)) for r in rows)
        points.append({"price": round(price, 1), "today": round(today, 0), "expiry": round(expiry, 0)})
    best = max(points, key=lambda p: p["today"])
    max_day = float(best["today"])
    capture = round(current / max_day * 100, 1) if max_day > 0 and current > 0 else None
    breakevens = []
    for a, b in zip(points, points[1:]):
        if (a["expiry"] < 0) != (b["expiry"] < 0) and b["expiry"] != a["expiry"]:
            breakevens.append(round(a["price"] + (b["price"] - a["price"]) * (-a["expiry"]) / (b["expiry"] - a["expiry"]), 1))
    return {
        "spot": spot,
        "points": points,
        "breakevens": breakevens,
        "basis": "carried legs from yesterday's close" if carried else "from entry (opened today)",
        "currentPnl": round(current, 2),
        "maxDayProfit": round(max_day, 2),
        "maxDayProfitAt": best["price"],
        "capturePercent": capture,
        "closeAt": int(close_at),
        "ivs": {f"{int(r['strike'])}{'CE' if r['call'] else 'PE'}": round(r["iv"] * 100, 1) for r in rows},
    }


def suggestion(payoff: dict[str, Any] | None, config: dict[str, Any], market_open: bool) -> dict[str, Any] | None:
    if not config["enabled"] or not market_open or not payoff or payoff.get("error"):
        return None
    capture = payoff.get("capturePercent")
    if capture is None or capture < float(config["thresholdPercent"]):
        return None
    return {
        "capturePercent": capture,
        "thresholdPercent": float(config["thresholdPercent"]),
        "currentPnl": payoff["currentPnl"],
        "maxDayProfit": payoff["maxDayProfit"],
        "text": (
            f"Today's P&L on this tag is ₹{payoff['currentPnl']:,.0f}, {capture:.0f}% of the most it can make by today's close "
            f"(₹{payoff['maxDayProfit']:,.0f}, with the index near {payoff['maxDayProfitAt']:,.0f}). Book the profit?"
        ),
    }
