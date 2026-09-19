"""XAUTUSD (gold) consolidation + support/resistance detection for the
pStrategy page. Scans a candle history for 4-candle windows where price
was genuinely range-bound -- as a trader would judge it by eye -- and
marks the window's high/low as a support/resistance segment spanning
just those 4 candles (not an infinite ray), per the reviewed strategy
notes (pStrategies.docx).

"Range-bound" is defined as: no candle in the window has a body that's
large relative to recent volatility. A single big-bodied candle inside
an otherwise tight window is a momentum/trend candle, not consolidation,
even if the overall high/low happens to be narrow -- exactly the
distinction the strategy notes called out.
"""

from __future__ import annotations

from typing import Any

from app.services.crypto_indicators import atr

WINDOW = 4
ATR_LOOKBACK = 14
# A candle's body above this fraction of the pre-window ATR disqualifies
# the whole window as containing a momentum candle rather than a
# consolidation candle.
BODY_ATR_RATIO = 0.6
# Small bodies alone aren't enough -- a choppy run of small-bodied candles
# can still wander across a wide band via wicks/gaps between them, which
# isn't a "flat" consolidation by eye. The window's overall high-low range
# must also stay tight relative to recent volatility.
RANGE_ATR_RATIO = 1.0


def detect_consolidations(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    n = len(candles)
    atr_values = atr(candles, ATR_LOOKBACK)
    boxes: list[dict[str, Any]] = []

    i = ATR_LOOKBACK
    while i + WINDOW <= n:
        window = candles[i : i + WINDOW]
        # ATR as of just before the window, so the window's own candles
        # can't inflate the threshold that's judging them.
        ref_atr = atr_values[i - 1]
        if ref_atr is None or ref_atr <= 0:
            i += 1
            continue

        has_momentum_candle = any(abs(float(c["close"]) - float(c["open"])) > BODY_ATR_RATIO * ref_atr for c in window)
        support = min(float(c["low"]) for c in window)
        resistance = max(float(c["high"]) for c in window)
        too_wide = (resistance - support) > RANGE_ATR_RATIO * ref_atr
        if has_momentum_candle or too_wide:
            i += 1
            continue

        boxes.append(
            {
                "startTime": window[0]["time"],
                "endTime": window[-1]["time"],
                "support": support,
                "resistance": resistance,
            }
        )
        # Skip past this box entirely rather than re-scanning overlapping
        # windows inside it -- one box per consolidation, not a cluster of
        # near-duplicates one candle apart.
        i += WINDOW

    return boxes
