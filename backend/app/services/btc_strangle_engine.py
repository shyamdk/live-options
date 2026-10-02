"""BTC Strangle -- pure helpers (no I/O) for bitcoin-strangle.pdf.

Delta Exchange India BTC option symbols look like C-BTC-86000-041026 /
P-BTC-86000-041026 (type, underlying, strike, expiry DDMMYY). Every expiry
settles at 12:00 UTC (17:30 IST). One contract = 0.001 BTC; prices are USD
per 1 BTC of underlying, so P&L in USD = price change x contracts x 0.001.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

CONTRACT_VALUE_BTC = 0.001
SETTLEMENT_HOUR_UTC = 12


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def settlement_epoch(expiry_code: str) -> int:
    day, month, year = int(expiry_code[0:2]), int(expiry_code[2:4]), 2000 + int(expiry_code[4:6])
    return int(datetime(year, month, day, SETTLEMENT_HOUR_UTC, tzinfo=timezone.utc).timestamp())


def parse_chain(tickers: list[dict[str, Any]]) -> dict[str, Any]:
    """{spot, expiries: {code: {settlement, strikes: {strike: {"CE": quote, "PE": quote}}}}}"""
    spot = None
    expiries: dict[str, dict[str, Any]] = {}
    for row in tickers:
        symbol = str(row.get("symbol") or "")
        parts = symbol.split("-")
        if len(parts) != 4 or parts[0] not in ("C", "P"):
            continue
        strike = _num(parts[2])
        code = parts[3]
        if strike is None or len(code) != 6:
            continue
        quotes = row.get("quotes") or {}
        greeks = row.get("greeks") or {}
        quote = {
            "symbol": symbol,
            "productId": int(row.get("product_id")),
            "strike": strike,
            "bid": _num(quotes.get("best_bid")),
            "ask": _num(quotes.get("best_ask")),
            "bidSize": _num(quotes.get("bid_size")),
            "askSize": _num(quotes.get("ask_size")),
            "mark": _num(row.get("mark_price")),
            "iv": _num(quotes.get("mark_iv")),
            "delta": _num(greeks.get("delta")),
            "oi": _num(row.get("oi_contracts")),
        }
        spot = spot or _num(row.get("spot_price"))
        bucket = expiries.setdefault(code, {"code": code, "settlement": settlement_epoch(code), "strikes": {}})
        bucket["strikes"].setdefault(strike, {})["CE" if parts[0] == "C" else "PE"] = quote
    return {"spot": spot, "expiries": expiries}


IST = timezone(timedelta(hours=5, minutes=30))


def pick_expiry(chain: dict[str, Any], now_epoch: int, offset: int) -> dict[str, Any] | None:
    """Expiry by IST calendar date: entry date + offset days (offset 2 at the
    10:30 PM entry = the day-after expiry, ~43h away). Exact date only -- if
    it isn't listed there is no trade, rather than rolling into a weekly
    expiry days away."""
    target = (datetime.fromtimestamp(now_epoch, IST) + timedelta(days=max(offset, 1))).date()
    return next(
        (
            e for e in chain["expiries"].values()
            if e["settlement"] > now_epoch + 60 and datetime.fromtimestamp(e["settlement"], IST).date() == target
        ),
        None,
    )


def mid(quote: dict[str, Any] | None) -> float | None:
    if not quote:
        return None
    bid, ask = quote.get("bid"), quote.get("ask")
    if bid and ask and ask >= bid:
        return (bid + ask) / 2
    return quote.get("mark")


def plan_strangle(expiry: dict[str, Any], spot: float, multiplier: float) -> dict[str, Any]:
    """ATM straddle (Jodi Bhav) x multiplier either side of spot; each strike
    rounded OUTWARD to the nearest listed strike at least that far away."""
    strikes = expiry["strikes"]
    both = [k for k, sides in strikes.items() if "CE" in sides and "PE" in sides]
    if not both:
        return {"error": "No strike with both a call and a put quoted for this expiry."}
    atm = min(both, key=lambda k: abs(k - spot))
    ce_mid, pe_mid = mid(strikes[atm]["CE"]), mid(strikes[atm]["PE"])
    if not ce_mid or not pe_mid:
        return {"error": f"ATM {atm:.0f} straddle has no usable price."}
    straddle = ce_mid + pe_mid
    distance = multiplier * straddle
    call_target, put_target = spot + distance, spot - distance
    calls = sorted(k for k, sides in strikes.items() if "CE" in sides and k >= call_target)
    puts = sorted((k for k, sides in strikes.items() if "PE" in sides and k <= put_target), reverse=True)
    if not calls or not puts:
        return {"error": "No listed strike far enough out for the distance -- multiplier too high for this chain."}
    call, put = strikes[calls[0]]["CE"], strikes[puts[0]]["PE"]
    return {
        "expiryCode": expiry["code"],
        "settlement": expiry["settlement"],
        "spot": spot,
        "atmStrike": atm,
        "atmCall": ce_mid,
        "atmPut": pe_mid,
        "straddle": round(straddle, 2),
        "multiplier": multiplier,
        "distance": round(distance, 2),
        "callTarget": round(call_target, 2),
        "putTarget": round(put_target, 2),
        "legs": {"CE": call, "PE": put},
    }


def round_to_tick(price: float, tick: float = 0.1) -> float:
    return round(round(price / tick) * tick, 4)


def stop_price(entry_price: float, stop_loss_percent: float, tick: float = 0.1) -> float:
    """100% stop loss = 2x the selling price."""
    return round_to_tick(entry_price * (1 + stop_loss_percent / 100), tick)


def fee(price: float, contracts: int, spot: float, *, taker_rate: float, premium_cap: float, gst_rate: float) -> float:
    """Delta options commission: min(rate x underlying notional, cap x
    premium), plus GST. USD."""
    qty_btc = contracts * CONTRACT_VALUE_BTC
    commission = min(taker_rate * spot * qty_btc, premium_cap * price * qty_btc)
    return round(commission * (1 + gst_rate), 4)


def leg_pnl(entry_price: float, exit_or_mark: float, contracts: int) -> float:
    """Short leg P&L in USD (positive when the option has decayed)."""
    return round((entry_price - exit_or_mark) * contracts * CONTRACT_VALUE_BTC, 4)


def intrinsic(option_type: str, strike: float, spot: float) -> float:
    return max(spot - strike, 0.0) if option_type == "CE" else max(strike - spot, 0.0)
