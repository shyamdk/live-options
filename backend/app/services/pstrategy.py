"""XAUTUSD (gold) consolidation + momentum-breakout detection for the
pStrategy page.

Stage 1 marked a fixed 4-candle window as "consolidation" whenever no
candle in it had an oversized body. This generalizes that to a
variable-length run: starting from any candle, keep extending the range
while each new candle stays within a tight band (relative to recent
ATR) and doesn't itself have an oversized body. The first candle that
breaks out of that band with a genuinely large body is a momentum
candle -- tagged "long" if it closes above the run's resistance, "short"
if it closes below the run's support.

The EMA20 side-of-trend filter ("long momentum must close above EMA20,
short below") is applied by the caller, which owns the EMA series --
this module only owns the consolidation/breakout geometry.
"""

from __future__ import annotations

from typing import Any, Literal

from app.services.crypto_indicators import atr

MIN_RUN = 3
MAX_RUN = 30
ATR_LOOKBACK = 14
# A candle's body above this fraction of the run's reference ATR
# disqualifies it from extending (or seeding) a consolidation run -- and,
# for the candle right after a run ends, is what makes it a candidate
# momentum/breakout candle rather than just a slightly bigger candle.
BODY_ATR_RATIO = 0.6
# The run's own high-low range must also stay tight relative to ATR --
# small bodies alone don't rule out a choppy run wandering across a wide
# band via wicks/gaps between candles.
RANGE_ATR_RATIO = 1.0

Side = Literal["long", "short"]


def detect_patterns(candles: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (boxes, breakouts). `breakouts` entries are
    {time, index, side} -- `index` lets the caller look up that candle's
    EMA20 value to apply the side-of-trend filter before treating it as a
    confirmed momentum candle.
    """
    n = len(candles)
    atr_values = atr(candles, ATR_LOOKBACK)
    boxes: list[dict[str, Any]] = []
    breakouts: list[dict[str, Any]] = []

    i = ATR_LOOKBACK
    while i < n:
        ref_atr = atr_values[i - 1]
        if ref_atr is None or ref_atr <= 0:
            i += 1
            continue

        seed_body = abs(float(candles[i]["close"]) - float(candles[i]["open"]))
        if seed_body > BODY_ATR_RATIO * ref_atr:
            i += 1
            continue

        start = i
        support = float(candles[i]["low"])
        resistance = float(candles[i]["high"])
        j = i
        while j + 1 < n and (j - start + 1) < MAX_RUN:
            nxt = candles[j + 1]
            nxt_body = abs(float(nxt["close"]) - float(nxt["open"]))
            new_support = min(support, float(nxt["low"]))
            new_resistance = max(resistance, float(nxt["high"]))
            still_narrow = (new_resistance - new_support) <= RANGE_ATR_RATIO * ref_atr
            if still_narrow and nxt_body <= BODY_ATR_RATIO * ref_atr:
                support, resistance, j = new_support, new_resistance, j + 1
            else:
                break

        run_length = j - start + 1
        if run_length < MIN_RUN:
            i += 1
            continue

        boxes.append(
            {
                "startTime": candles[start]["time"],
                "endTime": candles[j]["time"],
                "support": support,
                "resistance": resistance,
            }
        )

        if j + 1 < n:
            breakout = candles[j + 1]
            b_close = float(breakout["close"])
            b_body = abs(b_close - float(breakout["open"]))
            if b_body > BODY_ATR_RATIO * ref_atr:
                side: Side | None = "long" if b_close > resistance else "short" if b_close < support else None
                if side:
                    breakouts.append({"time": breakout["time"], "index": j + 1, "side": side})

        i = j + 2  # resume past the breakout candle -- if there wasn't one, j+2 still safely exceeds n and ends the loop

    return boxes, breakouts
