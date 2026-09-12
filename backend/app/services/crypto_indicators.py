"""EMA/MACD/Supertrend, computed from plain OHLC(V) candle dicts (time,
open, high, low, close[, volume]) in chronological (oldest-first) order.
Each function returns one value per input candle, with None for indices
that don't yet have enough history -- callers zip these back against the
candle list positionally rather than trimming it, matching how ema5's
existing /candles endpoint pairs its own EMA array with its candle array.
"""

from __future__ import annotations

from typing import Any, Literal

Direction = Literal["up", "down"]


def ema(values: list[float | None], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    multiplier = 2 / (period + 1)
    prev: float | None = None
    seed_sum = 0.0
    seed_count = 0
    for i, value in enumerate(values):
        if value is None:
            continue
        if prev is None:
            seed_sum += value
            seed_count += 1
            if seed_count == period:
                prev = seed_sum / period
                result[i] = prev
            continue
        prev = (value - prev) * multiplier + prev
        result[i] = prev
    return result


def macd(
    closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line: list[float | None] = [
        (f - s) if f is not None and s is not None else None for f, s in zip(ema_fast, ema_slow)
    ]
    signal_line = ema(macd_line, signal)
    histogram: list[float | None] = [
        (m - s) if m is not None and s is not None else None for m, s in zip(macd_line, signal_line)
    ]
    return macd_line, signal_line, histogram


def _true_range(candles: list[dict[str, Any]]) -> list[float]:
    tr: list[float] = []
    prev_close: float | None = None
    for c in candles:
        high, low, close = float(c["high"]), float(c["low"]), float(c["close"])
        if prev_close is None:
            tr.append(high - low)
        else:
            tr.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        prev_close = close
    return tr


def supertrend(
    candles: list[dict[str, Any]], period: int = 13, multiplier: float = 4.0
) -> tuple[list[float | None], list[Direction | None]]:
    """Standard Supertrend: Wilder-smoothed ATR bands that trail price,
    flipping direction when close crosses the active band.
    """
    n = len(candles)
    tr = _true_range(candles)
    atr: list[float | None] = [None] * n
    if n >= period:
        atr[period - 1] = sum(tr[:period]) / period
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    values: list[float | None] = [None] * n
    directions: list[Direction | None] = [None] * n
    final_upper: list[float | None] = [None] * n
    final_lower: list[float | None] = [None] * n

    for i in range(n):
        if atr[i] is None:
            continue
        high, low, close = float(candles[i]["high"]), float(candles[i]["low"]), float(candles[i]["close"])
        mid = (high + low) / 2
        basic_upper = mid + multiplier * atr[i]
        basic_lower = mid - multiplier * atr[i]

        prev_final_upper = final_upper[i - 1] if i > 0 else None
        prev_final_lower = final_lower[i - 1] if i > 0 else None
        prev_close = float(candles[i - 1]["close"]) if i > 0 else None

        # The band only "moves toward price" (tightens); it holds its prior
        # value whenever the new basic band would loosen it and price
        # hasn't already broken through -- that's what makes it a trailing
        # stop instead of just redrawing the raw ATR band every candle.
        if prev_final_upper is None:
            final_upper[i] = basic_upper
        elif basic_upper < prev_final_upper or (prev_close is not None and prev_close > prev_final_upper):
            final_upper[i] = basic_upper
        else:
            final_upper[i] = prev_final_upper

        if prev_final_lower is None:
            final_lower[i] = basic_lower
        elif basic_lower > prev_final_lower or (prev_close is not None and prev_close < prev_final_lower):
            final_lower[i] = basic_lower
        else:
            final_lower[i] = prev_final_lower

        prev_direction = directions[i - 1] if i > 0 else None
        if prev_direction is None:
            direction: Direction = "up" if close >= final_lower[i] else "down"
        elif prev_direction == "up":
            direction = "down" if close < final_lower[i] else "up"
        else:
            direction = "up" if close > final_upper[i] else "down"

        directions[i] = direction
        values[i] = final_lower[i] if direction == "up" else final_upper[i]

    return values, directions
