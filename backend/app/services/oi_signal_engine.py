"""Pure computation for the upgraded OI signal engine (see upgrade.md).
No I/O -- takes an already-fetched PCR/OI snapshot series plus 1-minute
index candles, returns an enriched series with a persistence-gated
BUY CE / BUY PE / NO TRADE call per point. Same discipline as
paper_trading_engine.py: plain data in, plain data out.

Covers upgrade.md phases 1-4: rolling windows, PCR/OI classification,
VWAP + price confirmation, premium confirmation, scoring, persistence,
per-point explanation (1-3), plus market regime, hysteresis (a looser
"hold" bar than "entry"), exit confirmation, cooldown, and the full
NO_TRADE/WATCH/BUY/HOLD/COOLDOWN state machine (4). Phase 5 (DB-persisted
signal history, a backtesting harness, old-vs-new comparison) lives in
oi_upgraded.py, which wraps this file's pure/replay-from-history design --
exactly what made ad hoc backtesting straightforward during this file's
own threshold tuning -- into a reusable background logger + report.

Regime is informational only -- it is NOT an additional entry gate. Entry
already requires pcr/oi/price to not contradict the trade and price to
actively confirm it (see raw_ce_ok/raw_pe_ok below); layering "must also
be in a TRENDING regime" on top would just re-tighten the persistence/
score loosening this file's thresholds were deliberately tuned for.

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

# Hysteresis: once a side has actually triggered (state == buyCe/buyPe),
# holding it uses a LOWER bar than entering it -- otherwise the display
# would flicker in and out of NO TRADE on every small score wobble even
# while the underlying setup is still basically intact. Exit needs either
# an immediate price-invalidation (no persistence needed -- an emergency
# exit shouldn't wait) or the score staying at/below the exit bar for
# EXIT_CONFIRMATION consecutive polls (so, symmetrically to entry, one
# noisy poll can't kick out an otherwise-fine hold either).
HOLD_SCORE_CE = 6
HOLD_SCORE_PE = 6
EXIT_SCORE_CE = 5
EXIT_SCORE_PE = 5
EXIT_CONFIRMATION = 2

# Cooldown: after an exit, block a fresh signal on the OPPOSITE side for
# this long -- this is specifically what stops CE -> PE -> CE -> PE
# whipsaws right after a position closes. It does NOT block the SAME
# side from re-arming (a continuation is not a reversal). A genuinely
# strong opposite read (>= STRONG_REVERSAL_SCORE) overrides the cooldown,
# since the doc explicitly allows a configurable override rather than a
# hard block -- a real reversal shouldn't be forced to wait out a timer
# built to catch noise, not conviction.
COOLDOWN_MINUTES = 10
STRONG_REVERSAL_SCORE = 9

PcrState = Literal["bullish", "neutral", "bearish"]
OiState = Literal["bullish", "bearish", "mixed", "unwinding", "buildingBoth"]
PriceState = Literal["bullish", "neutral", "bearish"]
IvState = Literal["supportive", "neutral", "risky"]
VixState = Literal["supportive", "neutral", "risky"]
Signal = Literal["buyCe", "buyPe", "noTrade"]
Regime = Literal["trendingBullish", "trendingBearish", "range", "transition"]
State = Literal["noTrade", "bullishWatch", "buyCe", "holdCe", "bearishWatch", "buyPe", "holdPe", "cooldown"]


def _classify_regime(pcr_state: PcrState, oi_state: OiState, price_state: PriceState, ce_score: int, pe_score: int) -> Regime:
    bullish_votes = (pcr_state == "bullish") + (oi_state == "bullish") + (price_state == "bullish")
    bearish_votes = (pcr_state == "bearish") + (oi_state == "bearish") + (price_state == "bearish")
    if bullish_votes >= 2 and bearish_votes == 0 and (ce_score - pe_score) >= MIN_SCORE_DIFFERENCE:
        return "trendingBullish"
    if bearish_votes >= 2 and bullish_votes == 0 and (pe_score - ce_score) >= MIN_SCORE_DIFFERENCE:
        return "trendingBearish"
    if bullish_votes > 0 and bearish_votes > 0:
        return "transition"
    return "range"


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


FRESH_EXTREME_LOOKBACK = 8


def _vwap_and_trend(candles: list[dict[str, Any]], at_time: int) -> tuple[float | None, float | None, float | None, bool, bool]:
    """Returns (spot, vwap, 5-candle trend, freshLow, freshHigh) as of the
    last candle at/before at_time.

    freshLow/freshHigh: is the current close itself the lowest/highest of
    the last FRESH_EXTREME_LOOKBACK candles? The 5-candle trend alone is a
    trailing average that peaks in "bearishness" exactly as a decline is
    ENDING, not while it's still developing -- backtesting against real
    NIFTY sessions found two losing PE entries that fired within 1-2
    points of the exact candle low of the move, immediately before it
    reversed, precisely because trend5m stays negative for a beat after
    price has already stopped falling. Requiring the entry candle to
    itself be a fresh extreme (not already bouncing off one) is a
    concrete confirmation that the move hasn't already reversed underneath
    the lagging trend reading.
    """
    idx = -1
    for i, candle in enumerate(candles):
        if candle["time"] <= at_time:
            idx = i
        else:
            break
    if idx < 0:
        return None, None, None, False, False

    cum_pv = 0.0
    cum_vol = 0.0
    for candle in candles[: idx + 1]:
        vol = candle.get("volume") or 0.0
        cum_pv += candle["close"] * vol
        cum_vol += vol
    vwap = (cum_pv / cum_vol) if cum_vol else None

    spot = candles[idx]["close"]
    trend5m = (candles[idx]["close"] - candles[idx - 5]["close"]) if idx >= 5 else None

    lookback_start = max(0, idx - FRESH_EXTREME_LOOKBACK)
    recent_closes = [c["close"] for c in candles[lookback_start : idx + 1]]
    fresh_low = bool(recent_closes) and spot <= min(recent_closes)
    fresh_high = bool(recent_closes) and spot >= max(recent_closes)
    return spot, vwap, trend5m, fresh_low, fresh_high


def enrich_with_upgraded_signal(points: list[dict[str, Any]], candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    state: State = "noTrade"
    armed_side: Signal | None = None
    persistence = 0
    exit_streak = 0
    cooldown_side: Signal | None = None
    cooldown_until: int | None = None

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

        spot, vwap, trend5m, fresh_low, fresh_high = _vwap_and_trend(candles, t)
        above_vwap = spot is not None and vwap is not None and spot > vwap
        below_vwap = spot is not None and vwap is not None and spot < vwap
        trend_bullish = trend5m is not None and trend5m > PRICE_TREND_EPS
        trend_bearish = trend5m is not None and trend5m < -PRICE_TREND_EPS
        if above_vwap and trend_bullish and fresh_high:
            price_state: PriceState = "bullish"
        elif below_vwap and trend_bearish and fresh_low:
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

        # VIX/IV "risky" (a rapid spike, not a moderate rise) vetoes entry --
        # backtesting against a real losing NIFTY trade found IV flagged
        # "risky" right at entry: a rapid IV spike alongside a sharp price
        # move is a classic capitulation/exhaustion signature, not genuine
        # continuation. upgrade.md itself frames VIX/IV as a caution filter
        # (sections 10-11); this was being scored but never actually gated
        # a trade on it.
        ce_quality_ok = vix_state != "risky" and ce_iv_state != "risky"
        pe_quality_ok = vix_state != "risky" and pe_iv_state != "risky"

        raw_ce_ok = (
            ce_score >= CE_ENTRY_SCORE
            and (ce_score - pe_score) >= MIN_SCORE_DIFFERENCE
            and pcr_state != "bearish"
            and oi_state != "bearish"
            and price_state == "bullish"
            and ce_premium_rising
            and ce_quality_ok
        )
        raw_pe_ok = (
            pe_score >= PE_ENTRY_SCORE
            and (pe_score - ce_score) >= MIN_SCORE_DIFFERENCE
            and pcr_state != "bullish"
            and oi_state != "bullish"
            and price_state == "bearish"
            and pe_premium_rising
            and pe_quality_ok
        )
        raw_signal: Signal = "buyCe" if raw_ce_ok else "buyPe" if raw_pe_ok else "noTrade"
        regime = _classify_regime(pcr_state, oi_state, price_state, ce_score, pe_score)

        holding_ce = state in ("buyCe", "holdCe")
        holding_pe = state in ("buyPe", "holdPe")

        if holding_ce or holding_pe:
            side_score = ce_score if holding_ce else pe_score
            hold_bar = HOLD_SCORE_CE if holding_ce else HOLD_SCORE_PE
            exit_bar = EXIT_SCORE_CE if holding_ce else EXIT_SCORE_PE
            # Price flipping against the held side is an emergency exit --
            # no persistence wait, unlike everything else here (section 15:
            # "do NOT require consecutive readings for an emergency exit").
            invalidated = price_state == ("bearish" if holding_ce else "bullish")
            if invalidated or side_score <= exit_bar:
                exit_streak = 0 if invalidated else exit_streak + 1
                if invalidated or exit_streak >= EXIT_CONFIRMATION:
                    state = "cooldown"
                    cooldown_side = "buyCe" if holding_ce else "buyPe"
                    cooldown_until = t + COOLDOWN_MINUTES * 60
                    exit_streak = 0
                    armed_side = None
                    persistence = 0
                else:
                    state = "holdCe" if holding_ce else "holdPe"
            else:
                exit_streak = 0
                state = "holdCe" if holding_ce else "holdPe"
        else:
            in_cooldown = state == "cooldown" and cooldown_until is not None and t < cooldown_until
            if state == "cooldown" and not in_cooldown:
                cooldown_side = None
                cooldown_until = None

            # Cooldown blocks a fresh signal on the side OPPOSITE whatever
            # just exited (that's the CE->PE->CE whipsaw this exists to
            # stop) -- a strong enough opposite read still overrides it.
            effective_ce_ok = raw_ce_ok
            effective_pe_ok = raw_pe_ok
            if in_cooldown:
                if cooldown_side == "buyCe" and not (raw_pe_ok and pe_score >= STRONG_REVERSAL_SCORE):
                    effective_pe_ok = False
                if cooldown_side == "buyPe" and not (raw_ce_ok and ce_score >= STRONG_REVERSAL_SCORE):
                    effective_ce_ok = False

            gated_signal: Signal = "buyCe" if effective_ce_ok else "buyPe" if effective_pe_ok else "noTrade"

            if gated_signal != "noTrade" and gated_signal == armed_side:
                persistence += 1
            elif gated_signal != "noTrade":
                armed_side = gated_signal
                persistence = 1
            else:
                armed_side = None
                persistence = 0

            if armed_side and persistence >= SIGNAL_PERSISTENCE:
                state = armed_side
                exit_streak = 0
            elif armed_side:
                state = "bullishWatch" if armed_side == "buyCe" else "bearishWatch"
            elif in_cooldown:
                state = "cooldown"
            else:
                state = "noTrade"

        signal: Signal = "buyCe" if state in ("buyCe", "holdCe") else "buyPe" if state in ("buyPe", "holdPe") else "noTrade"

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
                "regime": regime,
                "state": state,
                "persistence": persistence,
                "exitStreak": exit_streak,
                "cooldownUntil": cooldown_until if state == "cooldown" else None,
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
