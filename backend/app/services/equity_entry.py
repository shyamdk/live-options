"""Equity entry signal -- "is now a good time to buy/add?", kept separate from
the long-term recommendation ("should I own it?").

Back-test (17 Oct 2026, the user's 23 stocks, Jan 2021 - Oct 2026 daily
closes, 6-month forward return vs buying the same stock on any day):
  trend confirmed (SMA20 > SMA50 & close > SMA200)   +0.4% / -2.1%  (two halves)
  RSI(14) < 30                                       +5.2% / +7.3%
  close 5%+ below a falling SMA200                    +6.2% / +3.5%
Quality names bought when out of favour did better, with smaller dips after
entry. The sample is survivorship-biased (stocks still held), so the zone
only counts for names that pass the quality gates, and company-specific
negative news blocks it.

States: BUY_ZONE / ADD_ZONE (in the zone, no blocks), BLOCKED (in the zone
but a block applies), NEUTRAL (no edge now), NOT_QUALITY (fails the quality
gates), NO_DATA.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.services.equity_recommendations import _number, _valuation_reasonable

ZONE_BELOW_SMA200 = 0.95  # 5% under SMA200
DEEP_BELOW_SMA200 = 0.90
RSI_ZONE = 30.0
RSI_DEEP = 25.0
EXPOSURE_CAP_PERCENT = 8.0
MIN_DAYS_BETWEEN_BUYS = 14
ADD_STEP = 0.92  # next add at least 8% below the last buy
RESULTS_BLACKOUT_DAYS = 7  # calendar days (~5 trading days)
ETF_PATTERN = re.compile(r"BEES|ETF", re.I)


def _days_until(value: str | None, today: date) -> int | None:
    if not value:
        return None
    try:
        return (date.fromisoformat(str(value)[:10]) - today).days
    except ValueError:
        return None


def build_entry_signal(
    *,
    holding: dict[str, Any],
    fundamentals: dict[str, Any] | None,
    technicals: dict[str, Any] | None,
    news: dict[str, Any] | None,
    last_buy: dict[str, Any] | None,
    today: date | None = None,
) -> dict[str, Any]:
    fundamentals, technicals, news = fundamentals or {}, technicals or {}, news or {}
    today = today or date.today()
    symbol = str(holding.get("symbol") or "")
    close = _number(holding.get("ltp")) or _number(technicals.get("close"))
    sma200 = _number(technicals.get("sma200"))
    rsi = _number(technicals.get("rsi14"))
    sma200_rising = technicals.get("sma200Rising")
    out: dict[str, Any] = {"state": "NO_DATA", "label": "No data", "reasons": [], "blocks": [], "rsi": rsi,
                           "sma200": sma200, "buyBelow": None, "distanceToSma200Percent": None, "lastBuy": last_buy,
                           "nextAddBelow": None, "deep": False}
    if close is None or sma200 is None or rsi is None:
        out["reasons"].append("Not enough price history for RSI(14) / SMA200.")
        return out

    buy_below = round(sma200 * ZONE_BELOW_SMA200, 2)
    distance = (close / sma200 - 1) * 100
    out.update(buyBelow=buy_below, distanceToSma200Percent=round(distance, 1))
    in_zone = rsi < RSI_ZONE or close <= buy_below
    deep = rsi < RSI_DEEP or close <= sma200 * DEEP_BELOW_SMA200
    out["deep"] = deep

    # --- quality (should I own it at all?) -- ETFs are exempt
    is_etf = bool(ETF_PATTERN.search(symbol))
    if not is_etf:
        failed = quality_failures(fundamentals)
        if failed:
            out.update(state="NOT_QUALITY", label="Fails quality")
            out["reasons"].append(
                f"Quality gate not passed -- {'; '.join(failed)}: weakness here may be a value trap, so no entry signal."
                + (" It is in the price zone now." if in_zone else "")
            )
            return out

    # --- where is the price?
    zone_why = []
    if rsi < RSI_ZONE:
        zone_why.append(f"RSI(14) {rsi:.0f} is below {RSI_ZONE:.0f}")
    if close <= buy_below:
        zone_why.append(f"price {close:,.2f} is {abs(distance):.1f}% below SMA200 {sma200:,.2f}")
    if not in_zone:
        out.update(state="NEUTRAL", label="No edge now")
        out["reasons"].append(
            f"Price {close:,.2f} is {distance:+.1f}% vs SMA200, RSI {rsi:.0f}: no timing edge. "
            f"Buy zone starts below {buy_below:,.2f} (5% under SMA200) or RSI under {RSI_ZONE:.0f}."
        )
        if last_buy and _number(last_buy.get("price")):
            out["nextAddBelow"] = round(float(last_buy["price"]) * ADD_STEP, 2)
        return out
    out["reasons"].append(("Deep in the zone: " if deep else "In the buy zone: ") + "; ".join(zone_why) + ".")
    if sma200_rising is False:
        out["reasons"].append("SMA200 is falling -- in the back-test that was still a better entry than buying strength, but stagger buys.")

    # --- blocks
    blocks = out["blocks"]
    exposure = _number(holding.get("exposurePercent"))
    if exposure is not None and exposure > EXPOSURE_CAP_PERCENT:
        blocks.append(f"Already {exposure:.1f}% of the portfolio (cap {EXPOSURE_CAP_PERCENT:.0f}%).")
    if news.get("materialNegative") and str(news.get("negativeScope") or "") == "company":
        blocks.append("Material company-specific negative news -- read it before buying the dip.")
    elif str(news.get("sentiment") or "") == "negative" and not news.get("negativeScope"):
        blocks.append("News sentiment is negative and its cause isn't classified yet -- refresh News and review.")
    results_in = _days_until(news.get("nextResultsDate"), today)
    if results_in is not None and 0 <= results_in <= RESULTS_BLACKOUT_DAYS:
        blocks.append(f"Results due {news['nextResultsDate']} ({results_in} days) -- wait until after.")
    if last_buy and last_buy.get("date"):
        since = _days_until(str(last_buy["date"]), today)
        since = -since if since is not None else None
        price = _number(last_buy.get("price"))
        if since is not None and since < MIN_DAYS_BETWEEN_BUYS:
            blocks.append(f"Last bought {since} days ago -- at least {MIN_DAYS_BETWEEN_BUYS} days between buys.")
        if price:
            out["nextAddBelow"] = round(price * ADD_STEP, 2)
            if close > price * ADD_STEP:
                blocks.append(f"Within 8% of the last buy at {price:,.2f} -- next add below {price * ADD_STEP:,.2f}.")

    if blocks:
        out.update(state="BLOCKED", label="In zone, blocked")
    elif last_buy:
        out.update(state="ADD_ZONE", label="Add zone" + (" (deep)" if deep else ""))
        out["reasons"].append("Add one tranche (about a third of the planned position), not all at once.")
    else:
        out.update(state="BUY_ZONE", label="Buy zone" + (" (deep)" if deep else ""))
        out["reasons"].append("Start with one tranche (about a third of the planned position).")
    return out


def quality_failures(f: dict[str, Any], include_valuation: bool = True) -> list[str]:
    """Long-term quality gates for the entry signal. Lenders (debt/equity
    above 2.5 with an ROE) are judged on ROE and pledge: ROCE and leverage
    describe their business model, not their risk."""
    pe, median_pe, industry_pe = _number(f.get("pe")), _number(f.get("medianPe")), _number(f.get("industryPe"))
    roce, roe, debt, pledge = _number(f.get("roce")), _number(f.get("roe")), _number(f.get("debtToEquity")), _number(f.get("pledge"))
    growth = [v for v in (_number(f.get("salesGrowth3y")), _number(f.get("profitGrowth3y"))) if v is not None]
    lender = debt is not None and debt > 2.5 and roe is not None
    failed = []
    if lender:
        if roe < 12:
            failed.append(f"Quality (lender ROE {roe:.1f}% < 12%)")
    elif not (roce is not None and roce >= 15 and (roe is None or roe >= 10)):
        failed.append(f"Quality (ROCE {roce if roce is not None else '—'}% < 15%)")
    if pledge is not None and pledge > 5:
        failed.append(f"Pledge {pledge:.1f}%")
    if not lender and not (debt is not None and debt <= 1):
        failed.append(f"Leverage (debt/equity {debt if debt is not None else '—'})")
    if any(v < 0 for v in growth):
        failed.append("Growth (negative 3Y growth)")
    if include_valuation and not _valuation_reasonable(pe, median_pe, industry_pe):
        failed.append(f"Valuation (PE {pe if pe is not None else '—'} vs 3Y {median_pe if median_pe is not None else '—'})")
    return failed


def last_buys(transactions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Latest BUY per security id: {"date": iso, "price": float}."""
    out: dict[str, dict[str, Any]] = {}
    for row in transactions:
        if str(row.get("transactionType") or "").upper() != "BUY":
            continue
        when = str(row.get("exchangeTime") or row.get("updateTime") or row.get("createTime") or "")
        key = str(row.get("securityId") or "")
        if not key or not when:
            continue
        if key not in out or when > out[key]["date"]:
            out[key] = {"date": when[:10], "price": _number(row.get("price")), "time": when}
    return out


def rsi14(closes: list[float]) -> float | None:
    """Wilder RSI(14) of the last close."""
    if len(closes) < 15:
        return None
    gain = loss = 0.0
    for i in range(1, 15):
        change = closes[i] - closes[i - 1]
        gain += max(change, 0)
        loss += max(-change, 0)
    gain, loss = gain / 14, loss / 14
    for i in range(15, len(closes)):
        change = closes[i] - closes[i - 1]
        gain = (gain * 13 + max(change, 0)) / 14
        loss = (loss * 13 + max(-change, 0)) / 14
    if loss == 0:
        return 100.0
    return round(100 - 100 / (1 + gain / loss), 2)


def summarize(holdings: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for h in holdings:
        state = str((h.get("entrySignal") or {}).get("state") or "NO_DATA")
        counts[state] = counts.get(state, 0) + 1
    return counts

