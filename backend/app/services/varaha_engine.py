"""Varaha: pure decision engine for the NIFTY Adaptive Daily Strategy
(varaha/NIFTY_Adaptive_Daily_Strategy_Consolidated.md).

Everything here is deterministic and I/O-free so it can run against a stored
snapshot: the daily T-30 snapshot is saved once, and a manual direction
override re-runs selection -> candidates -> payoff -> checks on that same
snapshot instead of re-fetching the market. varaha.py does the fetching,
AI ranking and persistence.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from app.core.config import Settings
from app.services.charges import option_order_charges
from app.services.crypto_indicators import adx, atr, ema, rsi

MoveClass = Literal["BIG_MOVE", "WATCH", "LOW"]
Direction = Literal["UP", "DOWN", "NO_CLEAR_DIRECTION"]
Structure = Literal["CE_BUTTERFLY", "PE_BUTTERFLY", "FULL_BUTTERFLY", "IRON_CONDOR"]

OPTION_SEGMENT = "NSE_FNO"
STRIKE_STEP = 50.0
PAYOFF_RANGE_PERCENT = 12.0
PAYOFF_POINTS = 241

OVERRIDE_TO_DIRECTION: dict[str, Direction] = {"UP": "UP", "DOWN": "DOWN", "NO_DIRECTION": "NO_CLEAR_DIRECTION"}

# Strike geometry variants (spec Section 18A). "delta" is the spec's own
# delta bands; "wide" is the cheap-debit shape from the supplied screenshots
# (near-ATM long, short leg ~1.25x the expected move away).
BUTTERFLY_VARIANTS: list[dict[str, Any]] = [
    {"name": "delta", "label": "Delta-based", "longDelta": 0.60, "shortDelta": 0.25},
    {"name": "moderate", "label": "Moderate", "longDelta": 0.475, "shortDelta": 0.15},
    {"name": "wide", "label": "Wide / cheap debit", "longDelta": 0.40, "shortEmMultiple": 1.25},
]
CONDOR_VARIANTS: list[dict[str, Any]] = [
    {"name": "delta20", "label": "Short Δ 0.20", "shortDelta": 0.20, "hedgeDelta": 0.07},
    {"name": "delta15", "label": "Short Δ 0.15", "shortDelta": 0.15, "hedgeDelta": 0.05},
    {"name": "outsideEm", "label": "Shorts outside expected move", "shortEmMultiple": 1.0, "hedgeDelta": 0.05},
]
TARGET_WING_RATIO = 0.70
WING_RATIO_MIN = 0.60
WING_RATIO_MAX = 0.80

STRUCTURE_LABEL: dict[str, str] = {
    "CE_BUTTERFLY": "CE Butterfly",
    "PE_BUTTERFLY": "PE Butterfly",
    "FULL_BUTTERFLY": "Full Butterfly",
    "IRON_CONDOR": "Defined-risk Neutral (Iron Condor)",
}


# ---------------------------------------------------------------- math utils


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(spot: float, strike: float, years: float, iv: float | None, is_call: bool) -> float:
    """Black-Scholes with r=0. iv is a decimal (0.14 = 14%)."""
    intrinsic = max(spot - strike, 0.0) if is_call else max(strike - spot, 0.0)
    if years <= 0 or not iv or iv <= 0:
        return intrinsic
    vol_t = iv * math.sqrt(years)
    d1 = (math.log(spot / strike) + 0.5 * vol_t * vol_t) / vol_t
    d2 = d1 - vol_t
    if is_call:
        return spot * _norm_cdf(d1) - strike * _norm_cdf(d2)
    return strike * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def bs_delta(spot: float, strike: float, years: float, iv: float | None, is_call: bool) -> float | None:
    if years <= 0 or not iv or iv <= 0:
        return None
    vol_t = iv * math.sqrt(years)
    d1 = (math.log(spot / strike) + 0.5 * vol_t * vol_t) / vol_t
    return _norm_cdf(d1) if is_call else _norm_cdf(d1) - 1


def iv_decimal(value: float | None) -> float | None:
    """Dhan reports IV in percent (13.5); accept decimals too."""
    if value is None or value <= 0:
        return None
    return value / 100 if value > 3 else value


def _realized_vol(closes: list[float], window: int) -> float | None:
    if len(closes) < window + 1:
        return None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - window, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1)
    return math.sqrt(var) * math.sqrt(252)


# ------------------------------------------------------------ chain helpers


def primary_expiry(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    expiries = snapshot.get("expiries") or []
    return expiries[0] if expiries else None


def _leg_quote(expiry: dict[str, Any], strike: float, option_type: str) -> dict[str, Any] | None:
    for row in expiry.get("chain") or []:
        if float(row["strike"]) == float(strike):
            quote = row.get(option_type.lower())
            return quote if quote and (quote.get("ltp") or 0) > 0 else None
    return None


def _abs_delta(quote: dict[str, Any], forward: float, strike: float, years: float, is_call: bool) -> float | None:
    delta = quote.get("delta")
    if delta is None:
        delta = bs_delta(forward, strike, years, iv_decimal(quote.get("iv")), is_call)
    return abs(delta) if delta is not None else None


def _strikes_for(expiry: dict[str, Any], option_type: str) -> list[float]:
    key = option_type.lower()
    return sorted(
        float(row["strike"]) for row in expiry.get("chain") or []
        if row.get(key) and (row[key].get("ltp") or 0) > 0
    )


def _strike_by_delta(expiry: dict[str, Any], spot: float, option_type: str, target: float) -> float | None:
    is_call = option_type == "CE"
    forward = spot * forward_ratio(expiry, spot)
    best: tuple[float, float] | None = None
    for strike in _strikes_for(expiry, option_type):
        quote = _leg_quote(expiry, strike, option_type)
        if not quote:
            continue
        delta = _abs_delta(quote, forward, strike, expiry["years"], is_call)
        if delta is None:
            continue
        gap = abs(delta - target)
        if best is None or gap < best[0]:
            best = (gap, strike)
    return best[1] if best else None


def _nearest_strike(expiry: dict[str, Any], option_type: str, target: float) -> float | None:
    strikes = _strikes_for(expiry, option_type)
    return min(strikes, key=lambda s: abs(s - target)) if strikes else None


def atm_straddle(expiry: dict[str, Any], spot: float) -> dict[str, Any] | None:
    best_row = None
    for row in expiry.get("chain") or []:
        if not (row.get("ce") and row.get("pe")):
            continue
        if (row["ce"].get("ltp") or 0) <= 0 or (row["pe"].get("ltp") or 0) <= 0:
            continue
        if best_row is None or abs(float(row["strike"]) - spot) < abs(float(best_row["strike"]) - spot):
            best_row = row
    if not best_row:
        return None
    ivs = [iv_decimal(best_row[k].get("iv")) for k in ("ce", "pe")]
    ivs = [v for v in ivs if v]
    return {
        "strike": float(best_row["strike"]),
        "cePremium": float(best_row["ce"]["ltp"]),
        "pePremium": float(best_row["pe"]["ltp"]),
        "expectedMove": float(best_row["ce"]["ltp"]) + float(best_row["pe"]["ltp"]),
        "atmIv": sum(ivs) / len(ivs) if ivs else None,
    }


def forward_ratio(expiry: dict[str, Any], spot: float) -> float:
    """Forward / spot implied by ATM put-call parity (F = K + C - P).
    Dhan's IVs are quoted against the forward (carry makes it sit well above
    spot even a week out), so pricing with the bare spot and r=0 misprices
    calls high and puts low. Everything theoretical prices off spot x ratio.
    """
    straddle = atm_straddle(expiry, spot)
    if not straddle or not spot:
        return 1.0
    forward = straddle["strike"] + straddle["cePremium"] - straddle["pePremium"]
    ratio = forward / spot
    return ratio if 0.97 < ratio < 1.03 else 1.0


# ------------------------------------------------------------ move score


def move_assessment(snapshot: dict[str, Any], settings: Settings) -> dict[str, Any]:
    spot = float(snapshot["spot"])
    daily = snapshot.get("daily") or []
    today = snapshot.get("today")
    components: list[dict[str, Any]] = []

    # Event score (0-3) from the AI-maintained macro calendar.
    events = snapshot.get("events") or []
    high = sum(1 for e in events if e.get("impact") == "high")
    medium = sum(1 for e in events if e.get("impact") == "medium")
    event_score = 3 if high >= 2 else 2 if high == 1 else 1 if medium else 0
    components.append({
        "key": "event", "label": "Event score", "score": event_score, "max": 3,
        "value": f"{high} high / {medium} medium impact",
        "detail": "; ".join(e.get("headline", "") for e in events[:4]) or "No scheduled high/medium-impact events found",
    })

    # Expected move vs ATR14. The straddle covers the whole holding period,
    # ATR is one day -- compare per-day (straddle / sqrt(trading days)).
    expiry = primary_expiry(snapshot)
    straddle = atm_straddle(expiry, spot) if expiry else None
    atr14 = None
    if len(daily) >= 15:
        atr_series = atr(daily, 14)
        atr14 = atr_series[-1]
    em = straddle["expectedMove"] if straddle else None
    em_ratio = None
    if em and atr14 and expiry:
        em_ratio = (em / math.sqrt(max(expiry["tradingDte"], 1))) / atr14
    em_score = _band_score(em_ratio, settings.varaha_em_atr_normal, settings.varaha_em_atr_elevated)
    components.append({
        "key": "expectedMove", "label": "Expected move / ATR14", "score": em_score, "max": 2,
        "value": _fmt_ratio(em_ratio),
        "detail": (
            f"ATM straddle ±{em:.0f} over {expiry['tradingDte']} trading days vs ATR14 {atr14:.0f}"
            if em and atr14 and expiry else "Insufficient data"
        ),
    })

    # IV expansion: India VIX change vs previous close, plus VIX percentile.
    vix = snapshot.get("vix") or {}
    vix_now, vix_prev = vix.get("current"), vix.get("prevClose")
    history = [v for v in vix.get("history") or [] if v]
    vix_change_pct = ((vix_now - vix_prev) / vix_prev * 100) if vix_now and vix_prev else None
    vix_percentile = (
        sum(1 for v in history if v <= vix_now) / len(history) * 100 if vix_now and len(history) >= 20 else None
    )
    if vix_change_pct is None:
        iv_score = 0
    elif vix_change_pct > settings.varaha_vix_sharp_rise_percent or (vix_percentile or 0) > 70:
        iv_score = 2
    elif vix_change_pct > 0:
        iv_score = 1
    else:
        iv_score = 0
    components.append({
        "key": "ivExpansion", "label": "IV expansion (India VIX)", "score": iv_score, "max": 2,
        "value": f"{vix_change_pct:+.1f}%" if vix_change_pct is not None else "—",
        "detail": (
            f"VIX {vix_now:.2f} vs prev close {vix_prev:.2f}; 1y percentile {vix_percentile:.0f}"
            if vix_now and vix_prev and vix_percentile is not None
            else (f"VIX {vix_now:.2f} vs prev close {vix_prev:.2f}" if vix_now and vix_prev else "VIX unavailable")
        ),
    })

    # Realized volatility: 5-day vs 20-day.
    closes = [float(c["close"]) for c in daily]
    if today:
        closes = closes + [float(today["close"])]
    rv5, rv20 = _realized_vol(closes, 5), _realized_vol(closes, 20)
    rv_ratio = rv5 / rv20 if rv5 and rv20 else None
    rv_score = _band_score(rv_ratio, 0.9, 1.2)
    components.append({
        "key": "realizedVol", "label": "Realized vol (5d / 20d)", "score": rv_score, "max": 2,
        "value": _fmt_ratio(rv_ratio),
        "detail": f"RV5 {rv5 * 100:.1f}% vs RV20 {rv20 * 100:.1f}%" if rv5 and rv20 else "Insufficient data",
    })

    # Range expansion: today's range vs 10-day average daily range.
    ranges = [float(c["high"]) - float(c["low"]) for c in daily[-10:]]
    avg_range = sum(ranges) / len(ranges) if ranges else None
    today_range = float(today["high"]) - float(today["low"]) if today else None
    range_ratio = today_range / avg_range if today_range and avg_range else None
    range_score = _band_score(range_ratio, 0.9, 1.3)
    components.append({
        "key": "rangeExpansion", "label": "Range expansion (today / 10d avg)", "score": range_score, "max": 2,
        "value": _fmt_ratio(range_ratio),
        "detail": f"Today {today_range:.0f} pts vs 10d avg {avg_range:.0f}" if today_range and avg_range else "Insufficient data",
    })

    total = sum(c["score"] for c in components)
    if total >= settings.varaha_big_move_score:
        classification: MoveClass = "BIG_MOVE"
    elif total >= settings.varaha_watch_score:
        classification = "WATCH"
    else:
        classification = "LOW"
    return {
        "components": components,
        "moveScore": total,
        "maxScore": sum(c["max"] for c in components),
        "classification": classification,
        "bigMoveScore": settings.varaha_big_move_score,
        "watchScore": settings.varaha_watch_score,
        "expectedMove": em,
        "atmIv": straddle["atmIv"] if straddle else None,
        "atr14": atr14,
        "emAtrRatio": em_ratio,
        "vix": vix_now,
        "vixPercentile": vix_percentile,
    }


def _band_score(value: float | None, normal: float, elevated: float) -> int:
    if value is None:
        return 0
    return 2 if value > elevated else 1 if value >= normal else 0


def _fmt_ratio(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "—"


# ------------------------------------------------------------ direction


def direction_assessment(snapshot: dict[str, Any], settings: Settings) -> dict[str, Any]:
    daily = snapshot.get("daily") or []
    today = snapshot.get("today")
    candles = list(daily) + ([today] if today else [])
    closes = [float(c["close"]) for c in candles]
    last = closes[-1] if closes else None
    signals: list[dict[str, Any]] = []

    def add(key: str, label: str, vote: int | None, detail: str) -> None:
        signals.append({"key": key, "label": label, "vote": vote, "detail": detail})

    if last and len(closes) >= 50:
        ema20 = ema(closes, 20)[-1]
        ema50 = ema(closes, 50)[-1]
        add("ema20", "Price vs EMA20", 1 if last > ema20 else -1, f"{last:.0f} vs {ema20:.0f}")
        add("ema50", "Price vs EMA50", 1 if last > ema50 else -1, f"{last:.0f} vs {ema50:.0f}")
        add("trend", "EMA20 vs EMA50 (trend structure)", 1 if ema20 > ema50 else -1, f"{ema20:.0f} vs {ema50:.0f}")
    else:
        for key, label in (("ema20", "Price vs EMA20"), ("ema50", "Price vs EMA50"), ("trend", "EMA20 vs EMA50 (trend structure)")):
            add(key, label, None, "Insufficient daily history")

    if last and len(closes) >= 6:
        change = (last - closes[-6]) / closes[-6] * 100
        add("momentum", "5-day momentum", 1 if change > 0.5 else -1 if change < -0.5 else 0, f"{change:+.2f}%")
    else:
        add("momentum", "5-day momentum", None, "Insufficient data")

    rsi_values = rsi(closes, 14) if len(closes) >= 15 else []
    rsi_now = rsi_values[-1] if rsi_values else None
    if rsi_now is not None:
        add("rsi", "RSI(14) daily", 1 if rsi_now > 55 else -1 if rsi_now < 45 else 0, f"{rsi_now:.1f}")
    else:
        add("rsi", "RSI(14) daily", None, "Insufficient data")

    adx_values = adx(candles, 14) if len(candles) >= 30 else []
    adx_now = adx_values[-1] if adx_values else None
    if adx_now is not None and len(closes) >= 11:
        slope = closes[-1] - closes[-11]
        vote = (1 if slope > 0 else -1) if adx_now >= 20 else 0
        add("adx", "ADX trend confirmation", vote, f"ADX {adx_now:.1f}, 10-day slope {slope:+.0f} pts")
    else:
        add("adx", "ADX trend confirmation", None, "Insufficient data")

    pcr = snapshot.get("pcr")
    if pcr is not None:
        add("pcr", "Put-call ratio (OI)", 1 if pcr > 1.1 else -1 if pcr < 0.8 else 0, f"{pcr:.2f}")
    else:
        add("pcr", "Put-call ratio (OI)", None, "PCR snapshot unavailable")

    if today and float(today["open"]):
        day_change = (float(today["close"]) - float(today["open"])) / float(today["open"]) * 100
        add("intraday", "Today's move from open", 1 if day_change > 0.3 else -1 if day_change < -0.3 else 0, f"{day_change:+.2f}%")
    else:
        add("intraday", "Today's move from open", None, "Intraday data unavailable")

    counted = [s for s in signals if s["vote"] is not None]
    bullish = sum(1 for s in counted if s["vote"] > 0)
    bearish = sum(1 for s in counted if s["vote"] < 0)
    neutral = sum(1 for s in counted if s["vote"] == 0)
    total = len(counted) or 1
    bull_conf = bullish / total * 100
    bear_conf = bearish / total * 100
    threshold = settings.varaha_direction_confidence_percent
    classification: Direction = (
        "UP" if bull_conf >= threshold else "DOWN" if bear_conf >= threshold else "NO_CLEAR_DIRECTION"
    )
    return {
        "signals": signals,
        "bullish": bullish,
        "bearish": bearish,
        "neutral": neutral,
        "bullishConfidence": round(bull_conf, 1),
        "bearishConfidence": round(bear_conf, 1),
        "threshold": threshold,
        "classification": classification,
    }


# ------------------------------------------------------------ selection


def select_structures(move_class: MoveClass, direction: Direction) -> tuple[list[Structure], str | None]:
    """Returns (structures to generate candidates for, headline strategy)."""
    if move_class == "BIG_MOVE":
        structure: Structure = (
            "CE_BUTTERFLY" if direction == "UP" else "PE_BUTTERFLY" if direction == "DOWN" else "FULL_BUTTERFLY"
        )
        return [structure], structure
    if move_class == "WATCH":
        return ["CE_BUTTERFLY", "PE_BUTTERFLY", "FULL_BUTTERFLY", "IRON_CONDOR"], None
    return ["IRON_CONDOR"], "IRON_CONDOR"


# ------------------------------------------------------------ candidates


def _leg(expiry: dict[str, Any], strike: float, option_type: str, action: str, qty: int, spot: float) -> dict[str, Any] | None:
    quote = _leg_quote(expiry, strike, option_type)
    if not quote:
        return None
    is_call = option_type == "CE"
    bid, ask, ltp = quote.get("bid"), quote.get("ask"), float(quote["ltp"])
    # Conservative fill: pay the ask on buys, hit the bid on sells, when a
    # usable two-sided quote exists; otherwise fall back to LTP.
    price = ltp
    if bid and ask and ask >= bid > 0:
        price = float(ask) if action == "BUY" else float(bid)
    delta = quote.get("delta")
    if delta is None:
        delta = bs_delta(spot * forward_ratio(expiry, spot), strike, expiry["years"], iv_decimal(quote.get("iv")), is_call)
    return {
        "action": action,
        "qty": qty,
        "optionType": option_type,
        "strike": strike,
        "price": round(price, 2),
        "ltp": ltp,
        "bid": bid,
        "ask": ask,
        "iv": quote.get("iv"),
        "delta": delta,
        "oi": quote.get("oi"),
        "volume": quote.get("volume"),
        "securityId": quote.get("securityId"),
    }


def _butterfly_strikes(
    expiry: dict[str, Any], spot: float, option_type: str, variant: dict[str, Any], em: float | None
) -> tuple[float, float, float] | None:
    direction = 1 if option_type == "CE" else -1
    near = _strike_by_delta(expiry, spot, option_type, variant["longDelta"])
    if near is None:
        return None
    if "shortEmMultiple" in variant:
        if not em:
            return None
        short = _nearest_strike(expiry, option_type, spot + direction * variant["shortEmMultiple"] * em)
    else:
        short = _strike_by_delta(expiry, spot, option_type, variant["shortDelta"])
    if short is None or (short - near) * direction <= 0:
        return None
    inner = abs(short - near)
    strikes = _strikes_for(expiry, option_type)
    beyond = [s for s in strikes if (s - short) * direction > 0]
    if not beyond:
        return None
    # Prefer a far strike whose wing ratio lands in 0.60-0.80, closest to 0.70.
    far = min(beyond, key=lambda s: abs(abs(s - short) / inner - TARGET_WING_RATIO))
    return near, short, far


def _butterfly_legs(expiry: dict[str, Any], spot: float, option_type: str, strikes: tuple[float, float, float]) -> list[dict[str, Any]] | None:
    near, short, far = strikes
    legs = [
        _leg(expiry, near, option_type, "BUY", 1, spot),
        _leg(expiry, short, option_type, "SELL", 2, spot),
        _leg(expiry, far, option_type, "BUY", 1, spot),
    ]
    return legs if all(legs) else None  # type: ignore[return-value]


def _condor_legs(expiry: dict[str, Any], spot: float, variant: dict[str, Any], em: float | None) -> list[dict[str, Any]] | None:
    legs: list[dict[str, Any]] = []
    for option_type, direction in (("PE", -1), ("CE", 1)):
        if "shortEmMultiple" in variant:
            if not em:
                return None
            short = _nearest_strike(expiry, option_type, spot + direction * variant["shortEmMultiple"] * em)
        else:
            short = _strike_by_delta(expiry, spot, option_type, variant["shortDelta"])
        hedge = _strike_by_delta(expiry, spot, option_type, variant["hedgeDelta"])
        if short is None or hedge is None:
            return None
        if (hedge - short) * direction <= 0:
            outer = [s for s in _strikes_for(expiry, option_type) if (s - short) * direction > 0]
            if not outer:
                return None
            hedge = min(outer, key=lambda s: abs(s - short))
        sell = _leg(expiry, short, option_type, "SELL", 1, spot)
        buy = _leg(expiry, hedge, option_type, "BUY", 1, spot)
        if not sell or not buy:
            return None
        legs.extend([buy, sell] if option_type == "PE" else [sell, buy])
    return legs


def generate_candidates(snapshot: dict[str, Any], structures: list[Structure], em: float | None) -> list[dict[str, Any]]:
    spot = float(snapshot["spot"])
    candidates: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for expiry in snapshot.get("expiries") or []:
        exp_tag = expiry["expiry"]
        for structure in structures:
            variants = CONDOR_VARIANTS if structure == "IRON_CONDOR" else BUTTERFLY_VARIANTS
            for variant in variants:
                legs: list[dict[str, Any]] | None
                if structure == "IRON_CONDOR":
                    legs = _condor_legs(expiry, spot, variant, em)
                elif structure == "FULL_BUTTERFLY":
                    pe = _butterfly_strikes(expiry, spot, "PE", variant, em)
                    ce = _butterfly_strikes(expiry, spot, "CE", variant, em)
                    pe_legs = _butterfly_legs(expiry, spot, "PE", pe) if pe else None
                    ce_legs = _butterfly_legs(expiry, spot, "CE", ce) if ce else None
                    legs = pe_legs + ce_legs if pe_legs and ce_legs else None
                else:
                    option_type = "CE" if structure == "CE_BUTTERFLY" else "PE"
                    strikes = _butterfly_strikes(expiry, spot, option_type, variant, em)
                    legs = _butterfly_legs(expiry, spot, option_type, strikes) if strikes else None
                if not legs:
                    continue
                key = (structure, exp_tag, tuple((l["action"], l["optionType"], l["strike"], l["qty"]) for l in legs))
                if key in seen:
                    continue
                seen.add(key)
                candidates.append({
                    "id": f"{structure}-{variant['name']}-{exp_tag}",
                    "structure": structure,
                    "structureLabel": STRUCTURE_LABEL[structure],
                    "variant": variant["name"],
                    "variantLabel": variant["label"],
                    "expiry": exp_tag,
                    "dte": expiry["dte"],
                    "tradingDte": expiry["tradingDte"],
                    "years": expiry["years"],
                    "forwardRatio": forward_ratio(expiry, spot),
                    "legs": legs,
                })
    return candidates


# ------------------------------------------------------------ payoff


def _leg_sign(leg: dict[str, Any]) -> int:
    return 1 if leg["action"] == "BUY" else -1


def expiry_pnl_points(legs: list[dict[str, Any]], price: float) -> float:
    total = 0.0
    for leg in legs:
        intrinsic = max(price - leg["strike"], 0.0) if leg["optionType"] == "CE" else max(leg["strike"] - price, 0.0)
        total += _leg_sign(leg) * leg["qty"] * (intrinsic - leg["price"])
    return total


def today_pnl_points(legs: list[dict[str, Any]], price: float, years: float, forward_ratio_value: float = 1.0) -> float:
    forward = price * forward_ratio_value
    total = 0.0
    for leg in legs:
        value = bs_price(forward, leg["strike"], years, iv_decimal(leg.get("iv")), leg["optionType"] == "CE")
        total += _leg_sign(leg) * leg["qty"] * (value - leg["price"])
    return total


def payoff_curve(
    candidate: dict[str, Any], spot: float, lot_size: int, lots: int, expected_move: float | None = None
) -> list[dict[str, float]]:
    # Frame the chart on the structure itself: every strike plus +-2x the
    # expected move, with a margin -- a fixed +-12% squashed a butterfly into
    # a thin spike.
    strikes = [leg["strike"] for leg in candidate["legs"]]
    em = expected_move or spot * 0.02
    low = min(min(strikes), spot - 2 * em)
    high = max(max(strikes), spot + 2 * em)
    margin = (high - low) * 0.15
    low = max(low - margin, spot * (1 - PAYOFF_RANGE_PERCENT / 100))
    high = min(high + margin, spot * (1 + PAYOFF_RANGE_PERCENT / 100))
    step = (high - low) / (PAYOFF_POINTS - 1)
    multiplier = lot_size * lots
    points = []
    for i in range(PAYOFF_POINTS):
        price = low + i * step
        points.append({
            "price": round(price, 1),
            "expiry": round(expiry_pnl_points(candidate["legs"], price) * multiplier, 0),
            "today": round(
                today_pnl_points(candidate["legs"], price, candidate["years"], candidate.get("forwardRatio", 1.0)) * multiplier, 0
            ),
        })
    return points


def _breakevens(legs: list[dict[str, Any]], low: float, high: float) -> list[float]:
    # Payoff is piecewise-linear with kinks only at strikes -- evaluate at
    # every kink plus the range edges and interpolate zero crossings exactly.
    xs = sorted({low, high, *[leg["strike"] for leg in legs if low < leg["strike"] < high]})
    values = [expiry_pnl_points(legs, x) for x in xs]
    result: list[float] = []
    for i in range(1, len(xs)):
        a, b = values[i - 1], values[i]
        if a == 0 and (not result or result[-1] != xs[i - 1]):
            result.append(xs[i - 1])
        elif a * b < 0:
            result.append(xs[i - 1] + (xs[i] - xs[i - 1]) * (-a) / (b - a))
    return [round(x, 1) for x in result]


def _payoff_zones(legs: list[dict[str, Any]], breakevens: list[float], low: float, high: float) -> list[dict[str, Any]]:
    """Expiry profit/loss regions between breakevens; open-ended tails get
    None bounds. Given to the AI verbatim so it can't misread which side of
    the market a structure loses on."""
    edges = [low, *breakevens, high]
    zones: list[dict[str, Any]] = []
    for i in range(1, len(edges)):
        a, b = edges[i - 1], edges[i]
        kind = "profit" if expiry_pnl_points(legs, (a + b) / 2) > 0 else "loss"
        start = None if i == 1 else round(a, 1)
        end = None if i == len(edges) - 1 else round(b, 1)
        if zones and zones[-1]["type"] == kind:
            zones[-1]["to"] = end
        else:
            zones.append({"type": kind, "from": start, "to": end})
    return zones


# ------------------------------------------------------------ evaluation


def evaluate_candidate(
    candidate: dict[str, Any], snapshot: dict[str, Any], move: dict[str, Any], settings: Settings
) -> dict[str, Any]:
    spot = float(snapshot["spot"])
    legs = candidate["legs"]
    lot_size, lots = settings.varaha_lot_size, _lots(snapshot, settings)
    multiplier = lot_size * lots
    em = move.get("expectedMove")

    net_points = sum(_leg_sign(l) * l["qty"] * l["price"] for l in legs)  # >0 = debit
    kinks = sorted({l["strike"] for l in legs})
    low, high = min(kinks[0], spot) * 0.5, max(kinks[-1], spot) * 1.5
    probe = [low, high, *kinks]
    values = [expiry_pnl_points(legs, x) for x in probe]
    max_profit_pts, max_loss_pts = max(values), min(values)
    breakevens = _breakevens(legs, low, high)
    call_slope = sum(_leg_sign(l) * l["qty"] for l in legs if l["optionType"] == "CE")
    put_slope = sum(_leg_sign(l) * l["qty"] for l in legs if l["optionType"] == "PE")
    defined_risk = call_slope >= 0 and put_slope >= 0

    charges = sum(
        option_order_charges(
            premium=l["price"], quantity=l["qty"] * multiplier, side=l["action"],
            exchange_segment=OPTION_SEGMENT, settings=settings,
        )["total"]
        for l in legs
    )
    max_profit = max_profit_pts * multiplier
    max_loss = max_loss_pts * multiplier
    reward_risk = (max_profit / abs(max_loss)) if max_loss < 0 else None

    for leg in legs:
        leg["distance"] = round(leg["strike"] - spot, 1)
        leg["distancePercent"] = round((leg["strike"] - spot) / spot * 100, 2)
        leg["emMultiple"] = round((leg["strike"] - spot) / em, 2) if em else None

    net_delta = sum(_leg_sign(l) * l["qty"] * (l["delta"] or 0) for l in legs) * multiplier

    loss_width = None
    loss_width_ratio = None
    if candidate["structure"] == "FULL_BUTTERFLY":
        below = [b for b in breakevens if b <= spot]
        above = [b for b in breakevens if b >= spot]
        if below and above:
            loss_width = round(min(above) - max(below), 1)
            loss_width_ratio = loss_width / em if em else None

    zones = _payoff_zones(legs, breakevens, low, high)

    checks = _checks(candidate, snapshot, settings, legs, spot, em, defined_risk, max_loss, reward_risk,
                     breakevens, loss_width_ratio)
    hard_fail = [c for c in checks if c["hard"] and c["status"] == "FAIL"]
    watch = [c for c in checks if c["status"] == "WATCH"]
    result = {
        **candidate,
        "lots": lots,
        "lotSize": lot_size,
        "netPremiumPoints": round(net_points, 2),
        "netPremium": round(net_points * multiplier, 2),
        "premiumType": "DEBIT" if net_points > 0 else "CREDIT",
        "maxProfit": round(max_profit, 0),
        "maxLoss": round(max_loss, 0),
        "rewardRisk": round(reward_risk, 2) if reward_risk is not None else None,
        "breakevens": breakevens,
        "zones": zones,
        "charges": round(charges, 2),
        "netDelta": round(net_delta, 1),
        "definedRisk": defined_risk,
        "centralLossWidth": loss_width,
        "lossWidthEmRatio": round(loss_width_ratio, 2) if loss_width_ratio is not None else None,
        "checks": checks,
        "hardGatesPassed": not hard_fail,
        "watchItems": [c["key"] for c in watch],
    }
    result["fallbackScore"] = _fallback_score(result)
    return result


def _lots(snapshot: dict[str, Any], settings: Settings) -> int:
    return int((snapshot.get("config") or {}).get("lots") or settings.varaha_lots)


def _max_loss_limit(snapshot: dict[str, Any], settings: Settings) -> float:
    return float((snapshot.get("config") or {}).get("maxLossInr") or settings.varaha_max_loss_inr)


def _check(key: str, label: str, status: str, hard: bool, detail: str) -> dict[str, Any]:
    return {"key": key, "label": label, "status": status, "hard": hard, "detail": detail}


def _checks(
    candidate: dict[str, Any], snapshot: dict[str, Any], settings: Settings, legs: list[dict[str, Any]], spot: float,
    em: float | None, defined_risk: bool, max_loss: float, reward_risk: float | None, breakevens: list[float],
    loss_width_ratio: float | None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    structure = candidate["structure"]
    market_open = bool(snapshot.get("marketOpen"))

    # ---- hard gates
    dte_ok = settings.varaha_min_dte <= candidate["dte"] <= settings.varaha_max_dte and candidate["tradingDte"] >= 2
    checks.append(_check("expiry", "Expiry / DTE", "PASS" if dte_ok else "FAIL", True,
                         f"{candidate['expiry']} · {candidate['dte']} days ({candidate['tradingDte']} trading)"))

    expected_types = {"CE_BUTTERFLY": {"CE"}, "PE_BUTTERFLY": {"PE"}}.get(structure, {"CE", "PE"})
    types_ok = {l["optionType"] for l in legs} == expected_types
    checks.append(_check("optionType", "Option types", "PASS" if types_ok else "FAIL", True,
                         ", ".join(sorted(expected_types))))

    ratio_ok = _ratio_ok(structure, legs)
    checks.append(_check("structure", "Quantity ratio", "PASS" if ratio_ok else "FAIL", True,
                         "1:2:1 per side" if structure != "IRON_CONDOR" else "1:1 per side"))

    checks.append(_check("definedRisk", "Defined risk", "PASS" if defined_risk else "FAIL", True,
                         "Both tails capped" if defined_risk else "Open-ended loss on one tail"))

    illiquid = []
    for leg in legs:
        bid, ask = leg.get("bid"), leg.get("ask")
        if not (bid and ask):
            illiquid.append(f"{leg['strike']:.0f}{leg['optionType']} no bid/ask")
            continue
        mid = (bid + ask) / 2
        if ask - bid > max(settings.varaha_max_spread_points, mid * settings.varaha_max_spread_percent / 100):
            illiquid.append(f"{leg['strike']:.0f}{leg['optionType']} spread {ask - bid:.2f}")
    if not illiquid:
        checks.append(_check("liquidity", "Liquidity (bid/ask)", "PASS", True, "All legs two-sided, spreads within limits"))
    elif not market_open:
        checks.append(_check("liquidity", "Liquidity (bid/ask)", "WATCH", True,
                             "Market closed -- bid/ask not available, priced at LTP: " + "; ".join(illiquid[:3])))
    else:
        checks.append(_check("liquidity", "Liquidity (bid/ask)", "FAIL", True, "; ".join(illiquid[:3])))

    limit = _max_loss_limit(snapshot, settings)
    checks.append(_check("maxLoss", "Max loss within limit", "PASS" if abs(max_loss) <= limit else "FAIL", True,
                         f"₹{abs(max_loss):,.0f} vs limit ₹{limit:,.0f}"))

    if market_open:
        checks.append(_check("freshQuotes", "Fresh quotes", "PASS", True, "Snapshot taken during market hours"))
    else:
        checks.append(_check("freshQuotes", "Fresh quotes", "WATCH", True, "Snapshot taken outside market hours -- indicative only"))

    priced = all(l["price"] > 0 for l in legs)
    checks.append(_check("payoff", "Payoff constructed", "PASS" if priced else "FAIL", True,
                         "All legs priced" if priced else "One or more legs have no price"))

    # ---- soft checks
    rr_ok = reward_risk is not None and reward_risk >= settings.varaha_min_reward_risk
    checks.append(_check("rewardRisk", "Reward / risk", "PASS" if rr_ok else "WATCH", False,
                         f"{reward_risk:.2f} (min {settings.varaha_min_reward_risk})" if reward_risk is not None else "No capped loss"))

    if em:
        far_be = [b for b in breakevens if abs(b - spot) > 3 * em]
        checks.append(_check("breakevens", "Reasonable breakevens", "WATCH" if far_be else "PASS", False,
                             "Breakeven beyond 3x expected move" if far_be else "All within 3x expected move"))

    if em and structure != "IRON_CONDOR":
        shorts = [l for l in legs if l["action"] == "SELL"]
        multiples = [abs(l["strike"] - spot) / em for l in shorts]
        aligned = all(0.5 <= m <= 2.0 for m in multiples)
        checks.append(_check("emAlignment", "Expected-move alignment", "PASS" if aligned else "WATCH", False,
                             "Short strikes at " + ", ".join(f"{m:.2f}x" for m in multiples) + " EM (target 0.5–2.0x)"))
    if em and structure == "IRON_CONDOR":
        shorts = [l for l in legs if l["action"] == "SELL"]
        outside = all(abs(l["strike"] - spot) >= em for l in shorts)
        checks.append(_check("emAlignment", "Shorts outside expected move", "PASS" if outside else "WATCH", False,
                             ", ".join(f"{l['strike']:.0f}{l['optionType']}" for l in shorts) + f" vs ±{em:.0f}"))

    checks.append(_delta_check(structure, legs))

    if structure != "IRON_CONDOR":
        ratios = _wing_ratios(legs)
        ok = all(WING_RATIO_MIN <= r <= WING_RATIO_MAX for r in ratios)
        checks.append(_check("wingRatio", "Wing ratio", "PASS" if ok else "WATCH", False,
                             ", ".join(f"{r:.2f}" for r in ratios) + f" (target {WING_RATIO_MIN}–{WING_RATIO_MAX})"))

    if structure == "FULL_BUTTERFLY":
        ok = loss_width_ratio is not None and loss_width_ratio <= settings.varaha_loss_width_em_target
        checks.append(_check("lossZone", "Central loss width / EM", "PASS" if ok else "WATCH", False,
                             f"{loss_width_ratio:.2f} (target ≤ {settings.varaha_loss_width_em_target})"
                             if loss_width_ratio is not None else "No central loss zone found"))

    iv_ok = _iv_efficient(legs)
    checks.append(_check("ivSkew", "IV / skew efficiency", "PASS" if iv_ok else "WATCH", False,
                         "Selling equal/higher IV than buying" if iv_ok else "Short legs carry lower IV than the long legs"))
    return checks


def _ratio_ok(structure: str, legs: list[dict[str, Any]]) -> bool:
    for option_type in ("CE", "PE"):
        side = [l for l in legs if l["optionType"] == option_type]
        if not side:
            continue
        buys = sum(l["qty"] for l in side if l["action"] == "BUY")
        sells = sum(l["qty"] for l in side if l["action"] == "SELL")
        if structure == "IRON_CONDOR":
            if buys != 1 or sells != 1:
                return False
        elif buys != 2 or sells != 2:
            return False
    return True


def _wing_ratios(legs: list[dict[str, Any]]) -> list[float]:
    ratios = []
    for option_type in ("PE", "CE"):
        side = sorted((l for l in legs if l["optionType"] == option_type), key=lambda l: l["strike"])
        if len(side) != 3:
            continue
        if option_type == "PE":
            side = side[::-1]
        near, short, far = side
        inner = abs(short["strike"] - near["strike"])
        if inner:
            ratios.append(abs(far["strike"] - short["strike"]) / inner)
    return ratios


def _delta_check(structure: str, legs: list[dict[str, Any]]) -> dict[str, Any]:
    if structure == "IRON_CONDOR":
        bands = {"SELL": (0.15, 0.25), "BUY": (0.05, 0.10)}
        misses = [
            f"{l['strike']:.0f}{l['optionType']} Δ{abs(l['delta']):.2f}"
            for l in legs if l["delta"] is not None and not bands[l["action"]][0] <= abs(l["delta"]) <= bands[l["action"]][1]
        ]
    else:
        misses = []
        for option_type in ("CE", "PE"):
            side = sorted((l for l in legs if l["optionType"] == option_type), key=lambda l: l["strike"])
            if len(side) != 3:
                continue
            if option_type == "PE":
                side = side[::-1]
            for leg, (lo, hi) in zip(side, ((0.55, 0.65), (0.20, 0.30), (0.05, 0.15))):
                if leg["delta"] is not None and not lo <= abs(leg["delta"]) <= hi:
                    misses.append(f"{leg['strike']:.0f}{option_type} Δ{abs(leg['delta']):.2f} (spec {lo}–{hi})")
    return _check("delta", "Delta bands (spec)", "WATCH" if misses else "PASS", False,
                  "; ".join(misses[:4]) if misses else "All legs within spec delta bands")


def _iv_efficient(legs: list[dict[str, Any]]) -> bool:
    buys = [l["iv"] for l in legs if l["action"] == "BUY" and l.get("iv")]
    sells = [l["iv"] for l in legs if l["action"] == "SELL" and l.get("iv")]
    if not buys or not sells:
        return True
    return sum(sells) / len(sells) >= sum(buys) / len(buys)


def _fallback_score(candidate: dict[str, Any]) -> float:
    rr = min(candidate["rewardRisk"] or 0, 4.0)
    aligned = any(c["key"] == "emAlignment" and c["status"] == "PASS" for c in candidate["checks"])
    return round(rr * 2 + (1.0 if aligned else 0.0) - 0.5 * len(candidate["watchItems"]), 3)


# ------------------------------------------------------------ top level


def evaluate(snapshot: dict[str, Any], override: str | None, settings: Settings) -> dict[str, Any]:
    """Full deterministic pass over a snapshot. AI ranking is applied later."""
    if not snapshot.get("spot") or not snapshot.get("expiries"):
        return {
            "status": "NO_TRADE",
            "statusReason": snapshot.get("error") or "Market data unavailable (no spot or no option chain in the DTE range).",
            "move": None,
            "direction": None,
            "candidates": [],
        }
    move = move_assessment(snapshot, settings)
    direction = direction_assessment(snapshot, settings)

    override_applies = move["classification"] == "BIG_MOVE" and override in OVERRIDE_TO_DIRECTION
    effective: Direction = OVERRIDE_TO_DIRECTION[override] if override_applies else direction["classification"]  # type: ignore[index]
    direction["manualOverride"] = override if override_applies else None
    direction["effective"] = effective

    structures, headline = select_structures(move["classification"], effective)
    raw = generate_candidates(snapshot, structures, move.get("expectedMove"))
    evaluated = [evaluate_candidate(c, snapshot, move, settings) for c in raw]
    passed = [c for c in evaluated if c["hardGatesPassed"]]
    rejected = [c for c in evaluated if not c["hardGatesPassed"]]
    passed.sort(key=lambda c: c["fallbackScore"], reverse=True)

    if not passed:
        status, reason = "NO_TRADE", "No candidate passed every hard gate." if evaluated else "Could not build any candidate from the option chain."
    elif move["classification"] == "WATCH":
        status, reason = "WATCH", "Elevated move score but not a confirmed big move -- best options shown for review."
    elif move["classification"] == "LOW":
        status, reason = "VALID", "Low expected movement -- defined-risk neutral structure."
    else:
        status, reason = "VALID", "Big move expected."

    for rank, candidate in enumerate(passed, start=1):
        candidate["fallbackRank"] = rank
    return {
        "status": status,
        "statusReason": reason,
        "move": move,
        "direction": direction,
        "selectedStructure": headline,
        "selectedStructureLabel": STRUCTURE_LABEL.get(headline or "", None),
        "candidates": passed,
        "rejected": [
            {"id": c["id"], "structureLabel": c["structureLabel"], "variantLabel": c["variantLabel"],
             "expiry": c["expiry"], "reasons": [ch["label"] + ": " + ch["detail"] for ch in c["checks"] if ch["hard"] and ch["status"] == "FAIL"]}
            for c in rejected
        ],
    }
