"""Premium expansion + liquidity/spread gates for PE-CE Crossover (spec
Section 6). Each check is a pure function returning pass/fail plus a
human-readable reason, so a blocked signal is always explainable -- spec:
"Show why a trade is blocked; do not hide rejected signals."
"""

from __future__ import annotations

from typing import Any


def premium_expansion_percent(closes: list[float], lookback_bars: int) -> float | None:
    """% change from `lookback_bars` completed candles ago to the latest
    completed close. None if there isn't enough history yet.
    """
    if len(closes) <= lookback_bars:
        return None
    prior = closes[-1 - lookback_bars]
    if not prior:
        return None
    latest = closes[-1]
    return (latest - prior) / prior * 100


def check_premium_expansion(closes: list[float], lookback_bars: int, min_expansion_percent: float) -> dict[str, Any]:
    expansion = premium_expansion_percent(closes, lookback_bars)
    if expansion is None:
        return {"passed": False, "reason": "insufficient candle history for premium expansion check", "value": None}
    passed = expansion >= min_expansion_percent
    return {
        "passed": passed,
        "reason": None if passed else f"premium expansion {expansion:.1f}% below {min_expansion_percent:.1f}% minimum",
        "value": round(expansion, 2),
    }


def check_spread(bid: float | None, ask: float | None, max_spread_percent: float) -> dict[str, Any]:
    if not bid or not ask or ask <= 0:
        return {"passed": False, "reason": "bid/ask unavailable", "value": None}
    mid = (bid + ask) / 2
    if mid <= 0:
        return {"passed": False, "reason": "bid/ask unavailable", "value": None}
    spread_percent = (ask - bid) / mid * 100
    passed = spread_percent <= max_spread_percent
    return {
        "passed": passed,
        "reason": None if passed else f"spread {spread_percent:.1f}% exceeds {max_spread_percent:.1f}% maximum",
        "value": round(spread_percent, 2),
    }


def check_quote_freshness(quote_epoch: int | None, now_epoch: int, max_age_seconds: int) -> dict[str, Any]:
    if quote_epoch is None:
        return {"passed": False, "reason": "no quote timestamp available", "value": None}
    age = now_epoch - quote_epoch
    passed = 0 <= age <= max_age_seconds
    return {
        "passed": passed,
        "reason": None if passed else f"quote is {age}s old, exceeds {max_age_seconds}s maximum",
        "value": age,
    }


def check_positive_ema_fast_slope(ema_fast_values: list[float | None], bars: int) -> dict[str, Any]:
    """Positive EMA8 slope over `bars` completed bars (spec Section 6)."""
    recent = [v for v in ema_fast_values[-(bars + 1):] if v is not None]
    if len(recent) < 2:
        return {"passed": False, "reason": "insufficient EMA history for slope check", "value": None}
    slope = recent[-1] - recent[0]
    passed = slope > 0
    return {"passed": passed, "reason": None if passed else "EMA8 slope is flat/negative", "value": round(slope, 4)}
