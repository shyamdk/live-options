"""Pure computation for the upgraded OI signal engine (see upgrade.md).
No I/O -- takes an already-fetched PCR/OI snapshot series plus 1-minute
index candles, returns an enriched series with a persistence-gated
BUY CE / BUY PE / NO TRADE call per point. Same discipline as
paper_trading_engine.py: plain data in, plain data out.

Covers upgrade.md phases 1-3 (rolling windows, PCR/OI classification,
VWAP + price confirmation, premium confirmation, scoring, persistence,
per-point explanation). Deliberately does NOT yet implement phase 4
(formal state machine / hysteresis-with-different-hold-thresholds /
cooldown-after-exit) or phase 5 (backtesting harness, signal history
storage, old-vs-new comparison) -- those need a working scored signal to
observe first, per the doc's own phased rollout.

All thresholds below are first-pass heuristics sized to the magnitudes
observed in this app's real NIFTY data (PCR ~0.6-1.2, OI-change deltas in
the tens of lakhs, VIX ~10-12, IV ~9-12%) -- upgrade.md itself says these
need validation against historical/paper-trading data before being
trusted live; nothing here should be read as tuned/backtested yet.
"""

from __future__ import annotations

from typing import Any, Literal

PCR_EPS = 0.02
OI_MOMENTUM_EPS = 500_000.0  # 5 lakh contracts moved in a window to count as "meaningful"
PREMIUM_FLAT_EPS = 0.5  # rupees
PRICE_TREND_EPS = 5.0  # NIFTY points over 5 minutes
VIX_SPIKE_EPS = 0.3  # VIX points in 6 minutes
IV_MODERATE_MAX = 0.5  # percentage points -- above this it's a "spike", not "moderate"
IV_SPIKE_EPS = 1.0

# Loosened from the doc's literal 3/8/8 defaults after backtesting against a
# real full NIFTY session: persistence=3 required 3 STRICTLY CONSECUTIVE
# 3-minute polls (the doc's "~6 minutes" framing assumed a 2-minute poll
# cadence, not this app's actual 3-minute one -- 3 reads here is closer to
# 9 minutes, stricter than intended) and produced zero confirmed signals
# all day despite the raw CE score reaching 8-10 eight separate times.
# persistence=2 + entry score 7 reproduced 3 real, distinct signal events
# that day instead of 0. MIN_SCORE_DIFFERENCE=3 was left untouched -- the
# same backtest showed it never actually bound (CE/PE scores are naturally
# mutually exclusive in practice), so loosening it wouldn't add anything.
SIGNAL_PERSISTENCE = 2
CE_ENTRY_SCORE = 7
PE_ENTRY_SCORE = 7
MIN_SCORE_DIFFERENCE = 3

PcrState = Literal["bullish", "neutral", "bearish"]
OiState = Literal["bullish", "bearish", "mixed", "unwinding", "buildingBoth"]
PriceState = Literal["bullish", "neutral", "bearish"]
IvState = Literal["supportive", "neutral", "risky"]
VixState = Literal["supportive", "neutral", "risky"]
Signal = Literal["buyCe", "buyPe", "noTrade"]


def _value_before(points: list[dict[str, Any]], idx: int, target_time: int, key: str) -> float | None:
    """Last non-null value at or before target_time, scanning back from idx."""
    for j in range(idx, -1, -1):
        if points[j]["time"] <= target_time:
            value = points[j].get(key)
            return float(value) if value is not None else None
    return None


def _window_change(points: list[dict[str, Any]], idx: int, minutes: int, key: str) -> float | None:
    now_value = points[idx].get(key)
    if now_value is None:
        return None
    past_value = _value_before(points, idx, points[idx]["time"] - minutes * 60, key)
    if past_value is None:
        return None
    return float(now_value) - past_value


def _vwap_and_trend(candles: list[dict[str, Any]], at_time: int) -> tuple[float | None, float | None, float | None]:
    """Returns (spot, vwap, 5-candle trend) as of the last candle at/before at_time."""
    idx = -1
    for i, candle in enumerate(candles):
        if candle["time"] <= at_time:
            idx = i
        else:
            break
    if idx < 0:
        return None, None, None

    cum_pv = 0.0
    cum_vol = 0.0
    for candle in candles[: idx + 1]:
        vol = candle.get("volume") or 0.0
        cum_pv += candle["close"] * vol
        cum_vol += vol
    vwap = (cum_pv / cum_vol) if cum_vol else None

    spot = candles[idx]["close"]
    trend5m = (candles[idx]["close"] - candles[idx - 5]["close"]) if idx >= 5 else None
    return spot, vwap, trend5m


def enrich_with_upgraded_signal(points: list[dict[str, Any]], candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    prev_raw: Signal = "noTrade"
    prev_persistence = 0

    for idx, point in enumerate(points):
        out = dict(point)
        t = point["time"]

        pcr_change_6m = _window_change(points, idx, 6, "pcr")
        pcr_change_12m = _window_change(points, idx, 12, "pcr")
        if pcr_change_6m is not None and pcr_change_12m is not None and pcr_change_6m > PCR_EPS and pcr_change_12m > PCR_EPS:
            pcr_state: PcrState = "bullish"
        elif pcr_change_6m is not None and pcr_change_12m is not None and pcr_change_6m < -PCR_EPS and pcr_change_12m < -PCR_EPS:
            pcr_state = "bearish"
        else:
            pcr_state = "neutral"

        ce_oi_6m = _window_change(points, idx, 6, "ceOiChange")
        pe_oi_6m = _window_change(points, idx, 6, "peOiChange")
        ce_premium_6m = _window_change(points, idx, 6, "cePremium")
        pe_premium_6m = _window_change(points, idx, 6, "pePremium")

        ce_unwind = ce_oi_6m is not None and ce_oi_6m < -OI_MOMENTUM_EPS
        ce_writing = ce_oi_6m is not None and ce_oi_6m > OI_MOMENTUM_EPS and (ce_premium_6m is None or ce_premium_6m <= PREMIUM_FLAT_EPS)
        pe_unwind = pe_oi_6m is not None and pe_oi_6m < -OI_MOMENTUM_EPS
        pe_writing = pe_oi_6m is not None and pe_oi_6m > OI_MOMENTUM_EPS and (pe_premium_6m is None or pe_premium_6m <= PREMIUM_FLAT_EPS)
        ce_building = ce_oi_6m is not None and ce_oi_6m > OI_MOMENTUM_EPS
        pe_building = pe_oi_6m is not None and pe_oi_6m > OI_MOMENTUM_EPS

        bullish_oi = ce_unwind or pe_writing
        bearish_oi = ce_writing or pe_unwind
        if ce_unwind and pe_unwind:
            oi_state: OiState = "unwinding"
        elif ce_building and pe_building:
            oi_state = "buildingBoth"
        elif bullish_oi and bearish_oi:
            oi_state = "mixed"
        elif bullish_oi:
            oi_state = "bullish"
        elif bearish_oi:
            oi_state = "bearish"
        else:
            oi_state = "mixed"

        spot, vwap, trend5m = _vwap_and_trend(candles, t)
        above_vwap = spot is not None and vwap is not None and spot > vwap
        below_vwap = spot is not None and vwap is not None and spot < vwap
        trend_bullish = trend5m is not None and trend5m > PRICE_TREND_EPS
        trend_bearish = trend5m is not None and trend5m < -PRICE_TREND_EPS
        if above_vwap and trend_bullish:
            price_state: PriceState = "bullish"
        elif below_vwap and trend_bearish:
            price_state = "bearish"
        else:
            price_state = "neutral"

        ce_premium_rising = ce_premium_6m is not None and ce_premium_6m > PREMIUM_FLAT_EPS
        pe_premium_rising = pe_premium_6m is not None and pe_premium_6m > PREMIUM_FLAT_EPS

        vix_change_6m = _window_change(points, idx, 6, "indiaVix")
        vix_now = point.get("indiaVix")
        session_vix_values = [p.get("indiaVix") for p in points[: idx + 1] if p.get("indiaVix") is not None]
        vix_session_avg = sum(session_vix_values) / len(session_vix_values) if session_vix_values else None
        if vix_change_6m is not None and vix_change_6m > VIX_SPIKE_EPS:
            vix_state: VixState = "risky"
        elif vix_now is not None and vix_session_avg is not None and vix_now <= vix_session_avg:
            vix_state = "supportive"
        else:
            vix_state = "neutral"

        ce_iv_6m = _window_change(points, idx, 6, "ceIv")
        pe_iv_6m = _window_change(points, idx, 6, "peIv")
        ce_iv_state: IvState = (
            "risky" if ce_iv_6m is not None and ce_iv_6m > IV_SPIKE_EPS
            else "supportive" if ce_iv_6m is not None and 0 < ce_iv_6m <= IV_MODERATE_MAX and ce_premium_rising
            else "neutral"
        )
        pe_iv_state: IvState = (
            "risky" if pe_iv_6m is not None and pe_iv_6m > IV_SPIKE_EPS
            else "supportive" if pe_iv_6m is not None and 0 < pe_iv_6m <= IV_MODERATE_MAX and pe_premium_rising
            else "neutral"
        )

        ce_score = (
            (1 if pcr_state == "bullish" else 0)
            + (2 if ce_unwind else 0)
            + (2 if pe_writing else 0)
            + (2 if above_vwap else 0)
            + (1 if trend_bullish else 0)
            + (1 if ce_premium_rising else 0)
            + (1 if ce_iv_state == "supportive" else 0)
        )
        pe_score = (
            (1 if pcr_state == "bearish" else 0)
            + (2 if pe_unwind else 0)
            + (2 if ce_writing else 0)
            + (2 if below_vwap else 0)
            + (1 if trend_bearish else 0)
            + (1 if pe_premium_rising else 0)
            + (1 if pe_iv_state == "supportive" else 0)
        )

        raw_ce_ok = (
            ce_score >= CE_ENTRY_SCORE
            and (ce_score - pe_score) >= MIN_SCORE_DIFFERENCE
            and pcr_state != "bearish"
            and oi_state != "bearish"
            and price_state == "bullish"
            and ce_premium_rising
        )
        raw_pe_ok = (
            pe_score >= PE_ENTRY_SCORE
            and (pe_score - ce_score) >= MIN_SCORE_DIFFERENCE
            and pcr_state != "bullish"
            and oi_state != "bullish"
            and price_state == "bearish"
            and pe_premium_rising
        )
        raw_signal: Signal = "buyCe" if raw_ce_ok else "buyPe" if raw_pe_ok else "noTrade"

        if raw_signal != "noTrade" and raw_signal == prev_raw:
            persistence = prev_persistence + 1
        elif raw_signal != "noTrade":
            persistence = 1
        else:
            persistence = 0

        signal: Signal = raw_signal if (raw_signal != "noTrade" and persistence >= SIGNAL_PERSISTENCE) else "noTrade"

        out.update(
            {
                "pcrChange6m": pcr_change_6m,
                "pcrChange12m": pcr_change_12m,
                "pcrState": pcr_state,
                "ceOiMomentum6m": ce_oi_6m,
                "peOiMomentum6m": pe_oi_6m,
                "oiState": oi_state,
                "niftyPrice": spot,
                "vwap": vwap,
                "priceTrend5m": trend5m,
                "priceState": price_state,
                "cePremiumRising": ce_premium_rising,
                "pePremiumRising": pe_premium_rising,
                "vixState": vix_state,
                "ceIvState": ce_iv_state,
                "peIvState": pe_iv_state,
                "ceScore": ce_score,
                "peScore": pe_score,
                "rawSignal": raw_signal,
                "persistence": persistence,
                "signal": signal,
                "reasons": _build_reasons(
                    signal=signal,
                    pcr_state=pcr_state,
                    oi_state=oi_state,
                    above_vwap=above_vwap,
                    below_vwap=below_vwap,
                    trend_bullish=trend_bullish,
                    trend_bearish=trend_bearish,
                    ce_premium_rising=ce_premium_rising,
                    pe_premium_rising=pe_premium_rising,
                    ce_iv_state=ce_iv_state,
                    pe_iv_state=pe_iv_state,
                    persistence=persistence,
                ),
            }
        )
        enriched.append(out)
        prev_raw = raw_signal
        prev_persistence = persistence

    return enriched


def _build_reasons(
    *,
    signal: Signal,
    pcr_state: PcrState,
    oi_state: OiState,
    above_vwap: bool,
    below_vwap: bool,
    trend_bullish: bool,
    trend_bearish: bool,
    ce_premium_rising: bool,
    pe_premium_rising: bool,
    ce_iv_state: IvState,
    pe_iv_state: IvState,
    persistence: int,
) -> list[dict[str, Any]]:
    bullish_side = signal == "buyCe"
    bearish_side = signal == "buyPe"
    side = "ce" if bullish_side else "pe" if bearish_side else None

    items = [
        {"label": "PCR trend", "met": (pcr_state == "bullish") if bullish_side else (pcr_state == "bearish") if bearish_side else pcr_state != "neutral", "value": pcr_state},
        {"label": "OI positioning", "met": (oi_state == "bullish") if bullish_side else (oi_state == "bearish") if bearish_side else False, "value": oi_state},
        {"label": "NIFTY vs VWAP", "met": above_vwap if bullish_side else below_vwap if bearish_side else above_vwap or below_vwap, "value": "above" if above_vwap else "below" if below_vwap else "at"},
        {"label": "5m trend", "met": trend_bullish if bullish_side else trend_bearish if bearish_side else False, "value": "bullish" if trend_bullish else "bearish" if trend_bearish else "flat"},
        {"label": "Option premium", "met": ce_premium_rising if bullish_side else pe_premium_rising if bearish_side else False, "value": "rising" if (ce_premium_rising if bullish_side else pe_premium_rising) else "flat/falling"},
        {"label": "IV", "met": (ce_iv_state == "supportive") if bullish_side else (pe_iv_state == "supportive") if bearish_side else False, "value": (ce_iv_state if bullish_side else pe_iv_state if bearish_side else None)},
        {"label": "Persistence", "met": persistence >= SIGNAL_PERSISTENCE, "value": f"{min(persistence, SIGNAL_PERSISTENCE)}/{SIGNAL_PERSISTENCE}"},
    ]
    if side is None:
        # NO TRADE: keep the same checklist shape but judged against whichever
        # side currently looks more favored isn't well-defined -- show neutral
        # framing instead so the list doesn't silently imply a direction.
        items = [
            {"label": "PCR trend", "met": pcr_state != "neutral", "value": pcr_state},
            {"label": "OI positioning", "met": oi_state in ("bullish", "bearish"), "value": oi_state},
            {"label": "NIFTY vs VWAP", "met": above_vwap or below_vwap, "value": "above" if above_vwap else "below" if below_vwap else "at"},
            {"label": "5m trend", "met": trend_bullish or trend_bearish, "value": "bullish" if trend_bullish else "bearish" if trend_bearish else "flat"},
            {"label": "Persistence", "met": persistence >= SIGNAL_PERSISTENCE, "value": f"{min(persistence, SIGNAL_PERSISTENCE)}/{SIGNAL_PERSISTENCE}"},
        ]
    return items
