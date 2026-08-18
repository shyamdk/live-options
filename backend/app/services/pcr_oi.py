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
from datetime import date, datetime, time
from typing import Any

from app.core.config import Settings, get_settings
from app.core.timeutil import epoch_to_ist_time, in_time_window, now_ist, now_ist_epoch
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
    # One market-wide value, not per-underlying -- fetched once and stamped
    # onto both underlyings' rows at this poll's epoch (see the module
    # docstring: the schema is keyed per underlying, VIX just isn't).
    india_vix = await _fetch_india_vix(dhan, settings)

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
            india_vix=india_vix,
        )


async def _fetch_india_vix(dhan: DhanService, settings: Settings) -> float | None:
    if not settings.dhan_india_vix_security_id:
        return None
    try:
        data = await dhan.market_quotes_by_segment({INDEX_SEGMENT: [int(settings.dhan_india_vix_security_id)]})
        quote = (data.get(INDEX_SEGMENT) or {}).get(str(settings.dhan_india_vix_security_id)) or {}
        return _number(quote.get("last_price"))
    except Exception:
        return None


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
OI_SKEW_SMOOTHING_WINDOW = 5

# Guards signal generation against any pcr_oi_snapshots rows outside real
# NSE/BSE hours -- the table isn't otherwise guaranteed to only contain
# live-session polls (e.g. a dev/test run left the monitor on outside
# market hours), and stale/closed-market reads produce meaningless
# oscillating spot prices that can otherwise fire spurious signals.
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)

# How many polls after its own transition a held oiRegime can still fire
# the Path B alternate trigger in enrich_with_signal -- see that function's
# docstring for why this needs a limit, not just "currently held".
OI_REGIME_FRESHNESS_POLLS = 2


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
    direction to tell writer-driven OI buildup from buyer-driven buildup,
    AND -- same classic 4-quadrant grid as enrich_with_oi_regime, applied
    per-side using that side's own premium as "price" -- unwinding/covering
    moves too, not just buildup) and PCR-trend factors into a single Buy CE
    / Buy PE / Neutral call, plus a delta+vega "working together" flag for
    whichever side the call currently favors. This is a mechanical read of
    the user's own stated OI/PCR heuristic, not a validated strategy -- see
    PcrOiPanel.tsx for the "your rule, not a recommendation" framing shown
    alongside it.

    oiSkew is read off its own rolling average, same as PCR (see
    PCR_SMOOTHING_WINDOW) -- the raw per-poll score whipsaws sign almost
    every poll even during a real, sustained move (verified against actual
    session data: a session where pcrDelta drifted smoothly and consistently
    in one direction for 15+ minutes had raw oiSkew swinging between
    strongly positive and strongly negative on every single poll), so it
    almost never agreed with the much smoother PCR factor -- silently
    missing real moves, not just avoiding noise.

    Second trigger path: oiSkew (CE/PE-chain-specific) and oiRegime
    (combined CE+PE OI vs spot, see enrich_with_oi_regime) are two
    different reads of the same underlying data and don't always agree --
    verified against a real session where a ~250pt SENSEX rally flipped
    oiRegime to shortCovering right at the breakout (its own combined-OI +
    price factors, both smoothed, both confidence-gated), while oiSkew
    stayed near zero and PCR was flat, so the primary path never fired.
    Since oiRegime already cleared its own confidence floor to establish
    that state (see enrich_with_oi_regime's hysteresis), a FRESH
    bullish/bearish oiRegime (within OI_REGIME_FRESHNESS_POLLS of its own
    transition) is used as an alternate path into the same Buy CE/PE call
    whenever the primary path is neutral, gated only by PCR not actively
    pointing the other way (PCR being quiet/absent doesn't veto it -- only
    a confident opposite PCR does).

    The freshness limit is deliberate, found by checking this path against
    a real case: oiRegime's own hysteresis can hold a regime long after
    oiSkew has already started flipping the other way (they're reading the
    same underlying data differently and can legitimately diverge as a
    move matures). Without a freshness limit, this path was reviving an
    already-reversing Buy PE for several extra polls purely because
    oiRegime hadn't caught up yet -- prolonging a call oiSkew was already
    abandoning, not catching a fresh move. Gating to "near the transition"
    keeps the SENSEX rally catch (fired 1 poll after oiRegime's own
    transition) while dropping the stale-extension case.

    Must run AFTER enrich_with_roc_and_confidence (needs ceRoc/peRoc) AND
    enrich_with_oi_regime (needs oiRegime).
    """
    ce_premium_prev = pe_premium_prev = None
    atm_strike_prev: float | None = None
    pcr_history: list[float] = []
    pcr_smoothed_prev: float | None = None
    spot_prev: float | None = None
    ce_iv_prev = pe_iv_prev = None
    oi_skew_history: list[float] = []
    skew_history: list[float] = []
    pcr_delta_history: list[float] = []
    oi_regime_prev: str | None = None
    oi_regime_age = 0  # polls since oiRegime last changed value
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
        atm_strike = point.get("atmStrike")

        # cePremium/pePremium track whichever strike is currently ATM, so a
        # strike roll between polls (spot crossing the midpoint) makes a
        # raw premium diff meaningless -- it'd be comparing two different
        # contracts, not a real price move of the same one. Skip the
        # comparison for that one poll when the strike has changed.
        same_strike = atm_strike is not None and atm_strike_prev is not None and atm_strike == atm_strike_prev
        ce_premium_change = (
            ce_premium - ce_premium_prev if same_strike and ce_premium is not None and ce_premium_prev is not None else None
        )
        pe_premium_change = (
            pe_premium - pe_premium_prev if same_strike and pe_premium is not None and pe_premium_prev is not None else None
        )

        bullish = 0.0
        bearish = 0.0
        if ce_roc is not None and ce_premium_change is not None:
            if ce_roc > 0 and ce_premium_change > 0:
                bullish += abs(ce_roc)  # CE OI up + premium up -> fresh call buying -> bullish
            elif ce_roc > 0 and ce_premium_change < 0:
                bearish += abs(ce_roc)  # CE OI up + premium down -> writer-driven -> bearish
            elif ce_roc < 0 and ce_premium_change < 0:
                bearish += abs(ce_roc)  # CE OI down + premium down -> call buyers unwinding -> mild bearish
            elif ce_roc < 0 and ce_premium_change > 0:
                bullish += abs(ce_roc)  # CE OI down + premium up -> writers covering -> mild bullish
        if pe_roc is not None and pe_premium_change is not None:
            if pe_roc > 0 and pe_premium_change > 0:
                bearish += abs(pe_roc)  # PE OI up + premium up -> fresh put buying (fear) -> bearish
            elif pe_roc > 0 and pe_premium_change < 0:
                bullish += abs(pe_roc)  # PE OI up + premium down -> writer-driven -> bullish
            elif pe_roc < 0 and pe_premium_change < 0:
                bullish += abs(pe_roc)  # PE OI down + premium down -> put buyers unwinding -> mild bullish
            elif pe_roc < 0 and pe_premium_change > 0:
                bearish += abs(pe_roc)  # PE OI down + premium up -> writers covering -> mild bearish

        oi_skew_raw = (bullish - bearish) if (bullish or bearish) else None
        if oi_skew_raw is not None:
            oi_skew_history.append(oi_skew_raw)
        oi_skew = _rolling_mean(oi_skew_history, OI_SKEW_SMOOTHING_WINDOW)
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

        oi_regime = point.get("oiRegime")
        if oi_regime is not None:
            oi_regime_age = 0 if oi_regime != oi_regime_prev else oi_regime_age + 1
            oi_regime_prev = oi_regime

        signal: str | None = None
        signal_confidence: str | None = None
        in_market_hours = MARKET_OPEN <= epoch_to_ist_time(point["time"]) <= MARKET_CLOSE
        if in_market_hours:
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

            # Alternate path: a FRESH oiRegime (already confidence-gated and
            # hysteresis-protected at its own source) can fire the same call
            # when the primary oiSkew+PCR path is neutral/unavailable. PCR
            # still gets a veto if it's confidently pointing the other way,
            # but doesn't need to actively agree -- it was often just quiet
            # in the real missed-move cases this was built to catch. Capped
            # to OI_REGIME_FRESHNESS_POLLS after the regime's own transition
            # so this can't keep reviving a call oiSkew has already moved on
            # from (see docstring).
            if signal in (None, "neutral") and oi_regime_age <= OI_REGIME_FRESHNESS_POLLS:
                pcr_bullish = pcr_delta > 0 if pcr_delta is not None else None
                if oi_regime in ("longBuildup", "shortCovering") and pcr_bullish is not False:
                    signal, signal_confidence = "buyCe", "medium"
                elif oi_regime in ("shortBuildup", "longUnwinding") and pcr_bullish is not True:
                    signal, signal_confidence = "buyPe", "medium"

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
        atm_strike_prev = atm_strike if atm_strike is not None else atm_strike_prev
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
    distribution before a regime is ESTABLISHED. Smoothing alone still
    flipped on almost every poll in practice (spot drifts a few points
    either way constantly); the confidence floor is what actually makes
    this usable as a chart marker instead of one every 1-2 polls.

    Hysteresis: once established, a regime is HELD (kept as the output)
    for as long as the raw sign of both deltas keeps agreeing with it, even
    after the z-score confidence naturally fades back toward "normal" mid-
    trend (a trend that's been running all day stops looking statistically
    unusual against the day's own distribution, even while it's still
    intact) -- without this, a sustained move only ever got a single marker
    at its very start. It's only replaced by a NEW confidently-established
    regime, i.e. a genuine reversal, not by the original regime's confidence
    merely dipping.
    """
    combined_oi_history: list[float] = []
    spot_history: list[float] = []
    combined_oi_smoothed_prev: float | None = None
    spot_smoothed_prev: float | None = None
    oi_delta_history: list[float] = []
    spot_delta_history: list[float] = []
    held_regime: str | None = None
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

        raw_regime: str | None = None
        if oi_delta is not None and spot_delta is not None:
            if oi_delta > 0 and spot_delta > 0:
                raw_regime = "longBuildup"
            elif oi_delta > 0 and spot_delta < 0:
                raw_regime = "shortBuildup"
            elif oi_delta < 0 and spot_delta < 0:
                raw_regime = "longUnwinding"
            elif oi_delta < 0 and spot_delta > 0:
                raw_regime = "shortCovering"

        if raw_regime is not None and raw_regime != held_regime:
            confident_enough = (
                oi_score["confidence"] is not None
                and spot_score["confidence"] is not None
                and _meets_confidence_floor(oi_score["confidence"])
                and _meets_confidence_floor(spot_score["confidence"])
            )
            if confident_enough:
                held_regime = raw_regime
            # else: a disagreeing but unconfirmed reading -- noise, keep holding.

        out["oiRegime"] = held_regime
        enriched.append(out)

        combined_oi_smoothed_prev = combined_oi_smoothed if combined_oi_smoothed is not None else combined_oi_smoothed_prev
        spot_smoothed_prev = spot_smoothed if spot_smoothed is not None else spot_smoothed_prev

    return enriched
