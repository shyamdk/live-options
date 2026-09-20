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


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder's RSI -- same smoothing style as atr()/supertrend()'s ATR:
    a simple average to seed, then a running Wilder average of gains and
    losses from there.
    """
    n = len(closes)
    result: list[float | None] = [None] * n
    if n <= period:
        return result

    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, n)]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, n)]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result[period] = _rsi_from_averages(avg_gain, avg_loss)

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        result[i + 1] = _rsi_from_averages(avg_gain, avg_loss)

    return result


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


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


def resample_ohlc(candles: list[dict[str, Any]], group_size: int, day_key: Any = None) -> list[dict[str, Any]]:
    """Groups consecutive candles into `group_size`-sized OHLC bars -- for
    building a resolution Dhan doesn't serve natively (e.g. 30m from 15m
    pairs, or 3m from 1m triples; see nifty_swing.py and pstrategy_nifty.py).

    Grouping restarts at each session boundary (`day_key`, e.g. a date
    string) rather than treating the whole series as one continuous run --
    otherwise the overnight gap between two trading days would get folded
    into a single bar. A trailing partial group (fewer than group_size
    candles left at the end of a day) is still emitted as a shorter final
    bar rather than dropped, same as how a live chart's last bar of the day
    is naturally shorter.

    Input must already be chronological (oldest-first) and gap-free within
    a day; `time`/`volume` of the resulting bar come from its first/last
    input candle respectively (`time` is a bar's open time by convention
    elsewhere in this codebase).
    """
    if group_size <= 1:
        return candles

    def key_of(c: dict[str, Any]) -> Any:
        return day_key(c) if day_key is not None else None

    bars: list[dict[str, Any]] = []
    chunk: list[dict[str, Any]] = []
    current_key: Any = None
    for c in candles:
        k = key_of(c)
        if chunk and (k != current_key or len(chunk) >= group_size):
            bars.append(_merge_ohlc(chunk))
            chunk = []
        current_key = k
        chunk.append(c)
    if chunk:
        bars.append(_merge_ohlc(chunk))
    return bars


def _merge_ohlc(chunk: list[dict[str, Any]]) -> dict[str, Any]:
    volumes = [c.get("volume") for c in chunk if c.get("volume") is not None]
    return {
        "time": chunk[0]["time"],
        "open": chunk[0]["open"],
        "high": max(c["high"] for c in chunk),
        "low": min(c["low"] for c in chunk),
        "close": chunk[-1]["close"],
        "volume": sum(volumes) if volumes else None,
    }


def atr(candles: list[dict[str, Any]], period: int = 14) -> list[float | None]:
    """Wilder-smoothed average true range -- the same warm-up/smoothing
    supertrend() uses internally, exposed standalone for callers (like the
    pStrategy consolidation detector) that need a volatility reference
    without computing a full Supertrend.
    """
    tr = _true_range(candles)
    result: list[float | None] = [None] * len(candles)
    if len(candles) >= period:
        result[period - 1] = sum(tr[:period]) / period
        for i in range(period, len(candles)):
            result[i] = (result[i - 1] * (period - 1) + tr[i]) / period
    return result


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
