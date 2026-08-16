"""Tracks NIFTY/SENSEX Put-Call Ratio and change-in-OI as a continuous
intraday time series for Manage Trades' PCR/OI panel. Purely observational
— no signals, no approval flow, unlike the trading strategies in this
codebase.

DhanService.option_chain() returns both `oi` (current) and `previous_oi`
(previous session's close) per strike per side, so both PCR and "change in
OI" (matching the standard Sensibull/Opstra "Chg in OI" convention) are
computable from a single chain fetch each poll — no separate baseline needs
to be stored.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any

from app.core.config import Settings, get_settings
from app.core.timeutil import in_time_window, now_ist, now_ist_epoch
from app.db.sqlite import record_pcr_oi_snapshot
from app.services.dhan import DhanService

UNDERLYINGS = ("NIFTY", "SENSEX")
INDEX_SEGMENT = "IDX_I"

_expiries: dict[str, str | None] = {}
_expiry_date: date | None = None


def start_pcr_oi_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.pcr_oi_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_pcr_oi_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def _loop() -> None:
    settings = get_settings()
    interval = max(settings.pcr_oi_poll_interval_seconds, 30)
    while True:
        try:
            now = now_ist()
            in_hours = in_time_window(now.time(), settings.pcr_oi_session_start_time, settings.pcr_oi_session_end_time)
            if in_hours and now.weekday() < 5:
                await _poll_once(settings, now)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(interval)


def _security_id(settings: Settings, underlying: str) -> int:
    return settings.dhan_nifty_security_id if underlying == "NIFTY" else settings.dhan_sensex_security_id


async def _resolve_expiries(dhan: DhanService, settings: Settings, today: date) -> dict[str, str | None]:
    global _expiries, _expiry_date
    if _expiry_date == today and _expiries:
        return _expiries
    resolved: dict[str, str | None] = {}
    for underlying in UNDERLYINGS:
        try:
            expiry_list = await dhan.expiry_list(_security_id(settings, underlying), INDEX_SEGMENT)
            resolved[underlying] = expiry_list[0] if expiry_list else None
        except Exception:
            resolved[underlying] = None
    _expiries = resolved
    _expiry_date = today
    return resolved


async def _poll_once(settings: Settings, now: datetime) -> None:
    dhan = DhanService(settings)
    session_date = now.date().isoformat()
    epoch = now_ist_epoch()
    expiries = await _resolve_expiries(dhan, settings, now.date())

    for underlying in UNDERLYINGS:
        expiry = expiries.get(underlying)
        if not expiry:
            continue
        try:
            chain = await dhan.option_chain(_security_id(settings, underlying), INDEX_SEGMENT, expiry)
            snapshot = _summarize_chain(chain)
        except Exception:
            continue
        record_pcr_oi_snapshot(
            session_date=session_date,
            underlying=underlying,
            epoch=epoch,
            spot=snapshot["spot"],
            pcr=snapshot["pcr"],
            ce_oi=snapshot["ce_oi"],
            pe_oi=snapshot["pe_oi"],
            ce_oi_change=snapshot["ce_oi_change"],
            pe_oi_change=snapshot["pe_oi_change"],
            atm_strike=snapshot["atm_strike"],
            ce_premium=snapshot["ce_premium"],
            ce_iv=snapshot["ce_iv"],
            ce_delta=snapshot["ce_delta"],
            ce_vega=snapshot["ce_vega"],
            pe_premium=snapshot["pe_premium"],
            pe_iv=snapshot["pe_iv"],
            pe_delta=snapshot["pe_delta"],
            pe_vega=snapshot["pe_vega"],
        )


def _summarize_chain(chain: dict[str, Any]) -> dict[str, Any]:
    oc = chain.get("oc") or {}
    spot = _number(chain.get("last_price"))
    ce_oi = pe_oi = ce_prev_oi = pe_prev_oi = 0
    atm_strike: float | None = None
    atm_distance: float | None = None
    ce_atm: dict[str, Any] = {}
    pe_atm: dict[str, Any] = {}

    for strike_key, strike_data in oc.items():
        ce = (strike_data or {}).get("ce") or {}
        pe = (strike_data or {}).get("pe") or {}
        ce_oi += int(ce.get("oi") or 0)
        pe_oi += int(pe.get("oi") or 0)
        ce_prev_oi += int(ce.get("previous_oi") or 0)
        pe_prev_oi += int(pe.get("previous_oi") or 0)

        if spot:
            try:
                strike_price = float(strike_key)
            except (TypeError, ValueError):
                continue
            distance = abs(strike_price - spot)
            if atm_distance is None or distance < atm_distance:
                atm_distance = distance
                atm_strike = strike_price
                ce_atm = ce
                pe_atm = pe

    pcr = (pe_oi / ce_oi) if ce_oi else None
    return {
        "spot": spot,
        "pcr": round(pcr, 4) if pcr is not None else None,
        "ce_oi": ce_oi,
        "pe_oi": pe_oi,
        "ce_oi_change": ce_oi - ce_prev_oi,
        "pe_oi_change": pe_oi - pe_prev_oi,
        "atm_strike": atm_strike,
        "ce_premium": _number(ce_atm.get("last_price")),
        "ce_iv": _number(ce_atm.get("implied_volatility")),
        "ce_delta": _number((ce_atm.get("greeks") or {}).get("delta")),
        "ce_vega": _number((ce_atm.get("greeks") or {}).get("vega")),
        "pe_premium": _number(pe_atm.get("last_price")),
        "pe_iv": _number(pe_atm.get("implied_volatility")),
        "pe_delta": _number((pe_atm.get("greeks") or {}).get("delta")),
        "pe_vega": _number((pe_atm.get("greeks") or {}).get("vega")),
    }


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


MIN_ROC_OBSERVATIONS = 5
CONFIDENCE_THRESHOLDS = (1.0, 2.0, 3.0)  # |z| boundaries for low/medium/high/extreme


def enrich_with_roc_and_confidence(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adds, per point, the per-minute rate of change of ceOiChange/peOiChange
    and a confidence label scoring how unusual that pace is against today's
    own expanding distribution so far (mean/stdev of every rate-of-change
    observation from session start up to and including this point). Pure
    function over the already-stored snapshot list -- no I/O, nothing
    persisted; cheap enough (~130 points/day at the default poll interval)
    to recompute on every read.
    """
    ce_rocs: list[float] = []
    pe_rocs: list[float] = []
    enriched: list[dict[str, Any]] = []
    prev: dict[str, Any] | None = None

    for point in points:
        out = dict(point)
        ce_roc = pe_roc = None
        if prev is not None:
            minutes = (point["time"] - prev["time"]) / 60.0
            if minutes > 0:
                ce_roc = _roc(prev.get("ceOiChange"), point.get("ceOiChange"), minutes)
                pe_roc = _roc(prev.get("peOiChange"), point.get("peOiChange"), minutes)
        if ce_roc is not None:
            ce_rocs.append(ce_roc)
        if pe_roc is not None:
            pe_rocs.append(pe_roc)

        ce_score = _score(ce_rocs, ce_roc)
        pe_score = _score(pe_rocs, pe_roc)

        out["ceRoc"] = round(ce_roc, 2) if ce_roc is not None else None
        out["peRoc"] = round(pe_roc, 2) if pe_roc is not None else None
        out["ceZScore"] = ce_score["zScore"]
        out["peZScore"] = pe_score["zScore"]
        out["ceConfidence"] = ce_score["confidence"]
        out["peConfidence"] = pe_score["confidence"]
        out["ceRocBandUpper"] = ce_score["upper"]
        out["ceRocBandLower"] = ce_score["lower"]
        out["peRocBandUpper"] = pe_score["upper"]
        out["peRocBandLower"] = pe_score["lower"]
        enriched.append(out)
        prev = point

    return enriched


def _roc(prev_value: Any, current_value: Any, minutes: float) -> float | None:
    if prev_value is None or current_value is None:
        return None
    return (float(current_value) - float(prev_value)) / minutes


def _score(history: list[float], current: float | None) -> dict[str, Any]:
    empty = {"zScore": None, "confidence": None, "upper": None, "lower": None}
    if current is None or len(history) < MIN_ROC_OBSERVATIONS:
        return empty
    mean = sum(history) / len(history)
    variance = sum((v - mean) ** 2 for v in history) / len(history)
    stdev = variance**0.5
    upper = round(mean + stdev, 2)
    lower = round(mean - stdev, 2)
    if stdev == 0:
        return {"zScore": 0.0, "confidence": "low", "upper": upper, "lower": lower}
    z = (current - mean) / stdev
    az = abs(z)
    low, medium, high = CONFIDENCE_THRESHOLDS
    if az < low:
        label = "low"
    elif az < medium:
        label = "medium"
    elif az < high:
        label = "high"
    else:
        label = "extreme"
    return {"zScore": round(z, 2), "confidence": label, "upper": upper, "lower": lower}


_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2, "extreme": 3}

# Fewer, more accurate signals (see fine-tune.md options 1+2): a signal only
# fires once both factors clear this confidence floor -- "low" is within 1
# std dev of today's own distribution, i.e. noise by construction -- and
# PCR is read as a smoothed trend (vs. its own recent rolling average)
# rather than a tick-to-tick delta, since PCR moves too smoothly for raw
# deltas to ever produce a strong z-score.
MIN_SIGNAL_CONFIDENCE = "medium"
PCR_SMOOTHING_WINDOW = 5


def _weaker_confidence(a: str, b: str) -> str:
    return a if _CONFIDENCE_RANK[a] <= _CONFIDENCE_RANK[b] else b


def _meets_confidence_floor(confidence: str) -> bool:
    return _CONFIDENCE_RANK[confidence] >= _CONFIDENCE_RANK[MIN_SIGNAL_CONFIDENCE]


def _rolling_mean(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def enrich_with_signal(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combines the OI-skew (regime-aware: cross-checks ATM premium
    direction to tell writer-driven OI buildup from buyer-driven buildup)
    and PCR-trend factors into a single Buy CE / Buy PE / Neutral call,
    plus a delta+vega "working together" flag for whichever side the call
    currently favors. This is a mechanical read of the user's own stated
    OI/PCR heuristic, not a validated strategy -- see PcrOiPanel.tsx for
    the "your rule, not a recommendation" framing shown alongside it.

    Must run AFTER enrich_with_roc_and_confidence (needs ceRoc/peRoc).
    """
    ce_premium_prev = pe_premium_prev = None
    pcr_history: list[float] = []
    pcr_smoothed_prev: float | None = None
    spot_prev: float | None = None
    ce_iv_prev = pe_iv_prev = None
    skew_history: list[float] = []
    pcr_delta_history: list[float] = []
    enriched: list[dict[str, Any]] = []

    for point in points:
        out = dict(point)
        ce_roc = point.get("ceRoc")
        pe_roc = point.get("peRoc")
        ce_premium = point.get("cePremium")
        pe_premium = point.get("pePremium")
        pcr = point.get("pcr")
        spot = point.get("spot")
        ce_iv = point.get("ceIv")
        pe_iv = point.get("peIv")

        ce_premium_change = ce_premium - ce_premium_prev if ce_premium is not None and ce_premium_prev is not None else None
        pe_premium_change = pe_premium - pe_premium_prev if pe_premium is not None and pe_premium_prev is not None else None

        bullish = 0.0
        bearish = 0.0
        if ce_roc is not None and ce_roc > 0:
            if ce_premium_change is not None and ce_premium_change > 0:
                bullish += abs(ce_roc)  # CE building + premium rising -> buyer-driven -> bullish
            else:
                bearish += abs(ce_roc)  # CE building + premium flat/falling -> writer-driven -> bearish
        if pe_roc is not None and pe_roc > 0:
            if pe_premium_change is not None and pe_premium_change > 0:
                bearish += abs(pe_roc)  # PE building + premium rising -> buyer-driven (fear) -> bearish
            else:
                bullish += abs(pe_roc)  # PE building + premium flat/falling -> writer-driven -> bullish

        oi_skew = (bullish - bearish) if (bullish or bearish) else None
        if oi_skew is not None:
            skew_history.append(oi_skew)
        skew_score = _score(skew_history, oi_skew)

        if pcr is not None:
            pcr_history.append(pcr)
        pcr_smoothed = _rolling_mean(pcr_history, PCR_SMOOTHING_WINDOW)
        pcr_delta = (
            pcr_smoothed - pcr_smoothed_prev
            if pcr_smoothed is not None and pcr_smoothed_prev is not None
            else None
        )
        if pcr_delta is not None:
            pcr_delta_history.append(pcr_delta)
        pcr_score = _score(pcr_delta_history, pcr_delta)

        signal: str | None = None
        signal_confidence: str | None = None
        skew_conf = skew_score["confidence"]
        pcr_conf = pcr_score["confidence"]
        if oi_skew is not None and pcr_delta is not None and skew_conf and pcr_conf:
            skew_bullish = oi_skew > 0
            pcr_bullish = pcr_delta > 0
            confident_enough = _meets_confidence_floor(skew_conf) and _meets_confidence_floor(pcr_conf)
            if skew_bullish and pcr_bullish and confident_enough:
                signal, signal_confidence = "buyCe", _weaker_confidence(skew_conf, pcr_conf)
            elif not skew_bullish and not pcr_bullish and confident_enough:
                signal, signal_confidence = "buyPe", _weaker_confidence(skew_conf, pcr_conf)
            else:
                signal = "neutral"
        elif oi_skew is not None or pcr_delta is not None:
            signal = "neutral"

        delta_vega_aligned: str | None = None
        if spot is not None and spot_prev is not None:
            spot_change = spot - spot_prev
            if signal == "buyCe":
                ce_delta = point.get("ceDelta")
                ce_vega = point.get("ceVega")
                ce_iv_change = ce_iv - ce_iv_prev if ce_iv is not None and ce_iv_prev is not None else None
                if ce_delta is not None and ce_vega is not None and ce_iv_change is not None:
                    if ce_delta * spot_change > 0 and ce_vega * ce_iv_change > 0:
                        delta_vega_aligned = "CE"
            elif signal == "buyPe":
                pe_delta = point.get("peDelta")
                pe_vega = point.get("peVega")
                pe_iv_change = pe_iv - pe_iv_prev if pe_iv is not None and pe_iv_prev is not None else None
                if pe_delta is not None and pe_vega is not None and pe_iv_change is not None:
                    if pe_delta * spot_change > 0 and pe_vega * pe_iv_change > 0:
                        delta_vega_aligned = "PE"

        out["oiSkew"] = round(oi_skew, 2) if oi_skew is not None else None
        out["pcrDelta"] = round(pcr_delta, 4) if pcr_delta is not None else None
        out["signal"] = signal
        out["signalConfidence"] = signal_confidence
        out["deltaVegaAligned"] = delta_vega_aligned
        enriched.append(out)

        ce_premium_prev = ce_premium if ce_premium is not None else ce_premium_prev
        pe_premium_prev = pe_premium if pe_premium is not None else pe_premium_prev
        pcr_smoothed_prev = pcr_smoothed if pcr_smoothed is not None else pcr_smoothed_prev
        spot_prev = spot if spot is not None else spot_prev
        ce_iv_prev = ce_iv if ce_iv is not None else ce_iv_prev
        pe_iv_prev = pe_iv if pe_iv is not None else pe_iv_prev

    return enriched


OI_REGIME_SMOOTHING_WINDOW = 5


def enrich_with_oi_regime(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classic OI-vs-price read (the textbook 4-quadrant grid: OI up + price
    up = long buildup, OI up + price down = short buildup, OI down + price
    down = long unwinding, OI down + price up = short covering). That grid
    is normally applied to a single FUTURES OI series; this app only has the
    options chain, so "OI" here is combined CE+PE OI (ceOiChange + peOiChange)
    -- the closest available stand-in for total participation. Independent
    of enrich_with_signal's Buy CE/PE call: this labels the *character* of
    each move, not a directional recommendation.

    Both series are read off their own rolling average (same smoothing
    approach as enrich_with_signal's PCR trend) rather than tick-to-tick,
    and -- same "fewer, more accurate" floor as enrich_with_signal -- both
    deltas must also clear a medium+ confidence z-score against today's own
    distribution before a regime is assigned. Smoothing alone still flipped
    on almost every poll in practice (spot drifts a few points either way
    constantly); the confidence floor is what actually makes this usable as
    a chart marker instead of one every 1-2 polls.
    """
    combined_oi_history: list[float] = []
    spot_history: list[float] = []
    combined_oi_smoothed_prev: float | None = None
    spot_smoothed_prev: float | None = None
    oi_delta_history: list[float] = []
    spot_delta_history: list[float] = []
    enriched: list[dict[str, Any]] = []

    for point in points:
        out = dict(point)
        ce_oi_change = point.get("ceOiChange")
        pe_oi_change = point.get("peOiChange")
        spot = point.get("spot")

        combined_oi = (
            ce_oi_change + pe_oi_change if ce_oi_change is not None and pe_oi_change is not None else None
        )
        if combined_oi is not None:
            combined_oi_history.append(combined_oi)
        if spot is not None:
            spot_history.append(spot)

        combined_oi_smoothed = _rolling_mean(combined_oi_history, OI_REGIME_SMOOTHING_WINDOW)
        spot_smoothed = _rolling_mean(spot_history, OI_REGIME_SMOOTHING_WINDOW)

        oi_delta = (
            combined_oi_smoothed - combined_oi_smoothed_prev
            if combined_oi_smoothed is not None and combined_oi_smoothed_prev is not None
            else None
        )
        spot_delta = (
            spot_smoothed - spot_smoothed_prev
            if spot_smoothed is not None and spot_smoothed_prev is not None
            else None
        )
        if oi_delta is not None:
            oi_delta_history.append(oi_delta)
        if spot_delta is not None:
            spot_delta_history.append(spot_delta)
        oi_score = _score(oi_delta_history, oi_delta)
        spot_score = _score(spot_delta_history, spot_delta)

        regime: str | None = None
        if (
            oi_delta is not None
            and spot_delta is not None
            and oi_score["confidence"]
            and spot_score["confidence"]
            and _meets_confidence_floor(oi_score["confidence"])
            and _meets_confidence_floor(spot_score["confidence"])
        ):
            if oi_delta > 0 and spot_delta > 0:
                regime = "longBuildup"
            elif oi_delta > 0 and spot_delta < 0:
                regime = "shortBuildup"
            elif oi_delta < 0 and spot_delta < 0:
                regime = "longUnwinding"
            elif oi_delta < 0 and spot_delta > 0:
                regime = "shortCovering"

        out["oiRegime"] = regime
        enriched.append(out)

        combined_oi_smoothed_prev = combined_oi_smoothed if combined_oi_smoothed is not None else combined_oi_smoothed_prev
        spot_smoothed_prev = spot_smoothed if spot_smoothed is not None else spot_smoothed_prev

    return enriched
