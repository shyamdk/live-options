"""Pure animesh-scalping strategy logic (per animesh-scalping.txt): a daily
Heikin Ashi bias filter, a modified MACD (8,21,8) crossover trigger gated by
a 21-period EMA high/low/close band, and the SL/R-level rules layered on top
of ema5's already-generic 3-lot partial-exit/trailing-SL state machine.

No I/O — takes plain data in, returns plain data out. `Candle`/`Side`/`Phase`,
`compute_ema`, `filter_completed_candles`, and `evaluate_trade_tick` are
reused directly from `ema5_engine` since none of them are actually
EMA5-specific: they're a plain OHLC record, a period-parameterized EMA, the
"exclude the still-forming candle" filter, and the 3-lot partial-exit/
ratchet-trailing-SL state machine (entry/SL/target1/target2/phase/spot in,
an action out) — none of that logic has any EMA5 concept baked into it.
"""

from __future__ import annotations

from typing import Any

from app.services.ema5_engine import Candle, Phase, Side, compute_ema, evaluate_trade_tick, filter_completed_candles

__all__ = [
    "Candle",
    "Phase",
    "Side",
    "compute_ema",
    "evaluate_trade_tick",
    "filter_completed_candles",
    "heikin_ashi",
    "daily_bias",
    "compute_macd",
    "compute_ema_band",
    "scan_for_crossover_trigger",
    "compute_initial_sl",
    "compute_levels",
]


def heikin_ashi(daily_candles: list[Candle]) -> list[Candle]:
    """Standard recursive Heikin Ashi transform, seeded from the first
    candle (HA_open[0] = avg(open,close) of the first real candle).
    """
    ha: list[Candle] = []
    for i, candle in enumerate(daily_candles):
        ha_close = (candle.open + candle.high + candle.low + candle.close) / 4
        if i == 0:
            ha_open = (candle.open + candle.close) / 2
        else:
            prev = ha[-1]
            ha_open = (prev.open + prev.close) / 2
        ha_high = max(candle.high, ha_open, ha_close)
        ha_low = min(candle.low, ha_open, ha_close)
        ha.append(Candle(time=candle.time, open=ha_open, high=ha_high, low=ha_low, close=ha_close))
    return ha


def daily_bias(daily_candles: list[Candle]) -> Side | None:
    """Returns 'CE' if the most recent complete daily Heikin Ashi candle was
    green (close >= open) -> long/call bias, 'PE' if red -> short/put bias,
    None if there's no daily candle yet to judge.
    """
    if not daily_candles:
        return None
    ha = heikin_ashi(daily_candles)
    last = ha[-1]
    return "CE" if last.close >= last.open else "PE"


def compute_macd(closes: list[float], *, fast: int = 8, slow: int = 21, signal: int = 8) -> dict[str, list[float | None]]:
    """Modified MACD (8,21,8 per the doc, replacing the default 12,26,9):
    macd = EMA(fast) - EMA(slow); signal = EMA(macd, period=signal),
    computed only once the MACD line itself has real (non-None) values;
    histogram = macd - signal.
    """
    ema_fast = compute_ema(closes, period=fast)
    ema_slow = compute_ema(closes, period=slow)
    macd_line: list[float | None] = [
        (f - s) if f is not None and s is not None else None for f, s in zip(ema_fast, ema_slow)
    ]
    warmup = sum(1 for v in macd_line if v is None)
    defined_tail = [v for v in macd_line if v is not None]
    signal_tail = compute_ema(defined_tail, period=signal) if defined_tail else []
    signal_line: list[float | None] = [None] * warmup + signal_tail
    histogram: list[float | None] = [
        (m - s) if m is not None and s is not None else None for m, s in zip(macd_line, signal_line)
    ]
    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def compute_ema_band(candles: list[Candle], *, period: int = 21) -> dict[str, list[float | None]]:
    """21-EMA band: upper = EMA(high), lower = EMA(low), median = EMA(close).
    Price trading inside this band is the doc's "sideways" condition.
    """
    return {
        "high": compute_ema([c.high for c in candles], period=period),
        "low": compute_ema([c.low for c in candles], period=period),
        "median": compute_ema([c.close for c in candles], period=period),
    }


def scan_for_crossover_trigger(
    candles: list[Candle],
    macd: list[float | None],
    signal: list[float | None],
    band_high: list[float | None],
    band_low: list[float | None],
    side: Side,
) -> dict[str, Any]:
    """Same rolling-trigger-candle shape as ema5_engine.scan_for_signal: a
    crossover candle is flagged when price clears the EMA band on the
    biased side AND the MACD line crosses the signal line in the confirming
    direction on the correct side of zero (hard requirement, per the doc's
    scalping refinement, applied both ways by symmetry). A later candle
    breaking the crossover candle's high (CE) / low (PE) fires the entry;
    the specific crossover candle consumed is returned separately since it's
    needed for the SL calculation (mirrors ema5's `triggeredAlertCandle`).
    """
    crossover: Candle | None = None
    entry_candle: Candle | None = None
    triggered: Candle | None = None
    for i in range(1, len(candles)):
        entry_candle = None
        triggered = None
        m0, m1 = macd[i - 1], macd[i]
        s0, s1 = signal[i - 1], signal[i]
        bh, bl = band_high[i], band_low[i]
        if m0 is None or m1 is None or s0 is None or s1 is None or bh is None or bl is None:
            continue
        candle = candles[i]
        if crossover is not None:
            if side == "CE" and candle.high > crossover.high:
                entry_candle, triggered, crossover = candle, crossover, None
                continue
            if side == "PE" and candle.low < crossover.low:
                entry_candle, triggered, crossover = candle, crossover, None
                continue
        if side == "CE" and candle.close > bh and m0 <= s0 and m1 > s1 and m1 < 0:
            crossover = candle
        elif side == "PE" and candle.close < bl and m0 >= s0 and m1 < s1 and m1 > 0:
            crossover = candle
    return {"crossoverCandle": crossover, "entryCandle": entry_candle, "triggeredCrossoverCandle": triggered}


def compute_initial_sl(
    trigger_candle: Candle,
    side: Side,
    *,
    band_low_at_trigger: float | None,
    band_high_at_trigger: float | None,
    recent_candles: list[Candle],
    large_candle_multiplier: float = 1.5,
) -> float:
    """SL at the 21-EMA band level by default (low band for CE, high band
    for PE). Exception: if the trigger candle's high-low range is
    `large_candle_multiplier`x or more the average range of `recent_candles`
    (the candles immediately before it), use the candle's body midpoint
    instead (the doc's "50% of that candle's body" rule).
    """
    candle_range = trigger_candle.high - trigger_candle.low
    avg_range = sum(c.high - c.low for c in recent_candles) / len(recent_candles) if recent_candles else 0.0
    is_large = avg_range > 0 and candle_range >= large_candle_multiplier * avg_range
    body_mid = (trigger_candle.open + trigger_candle.close) / 2

    if side == "CE":
        if is_large:
            return body_mid
        return band_low_at_trigger if band_low_at_trigger is not None else trigger_candle.low
    if is_large:
        return body_mid
    return band_high_at_trigger if band_high_at_trigger is not None else trigger_candle.high


def compute_levels(entry_price: float, sl_price: float, side: Side) -> dict[str, float]:
    """1R for lot 1, 1.5R for lot 2 (the doc's 1-min scalping RR range of
    1:1 to 1:1.5) — lot 3 has no fixed target, it trails past target2.
    """
    risk = abs(entry_price - sl_price)
    direction = 1 if side == "CE" else -1
    return {
        "risk": risk,
        "target1": entry_price + direction * risk * 1.0,
        "target2": entry_price + direction * risk * 1.5,
    }
