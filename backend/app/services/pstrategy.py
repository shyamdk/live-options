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
# Delta Exchange lets XAUTUSD perpetuals go up to 50x -- P&L is reported
# as the return on margin at that leverage, not the raw price move,
# matching how the position would actually be sized on the exchange.
# Entry/stop/target stay pure price levels either way; only the P&L%
# scales.
LEVERAGE = 50

Side = Literal["long", "short"]


def detect_patterns(candles: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (boxes, breakouts). `breakouts` entries are
    {time, index, side, boxIndex} -- `index` lets the caller look up that
    candle's EMA value to apply the side-of-trend filter, and `boxIndex`
    points back into `boxes` so the caller can read the support/resistance
    that stop/target levels get computed from.
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
                    breakouts.append({"time": breakout["time"], "index": j + 1, "side": side, "boxIndex": len(boxes) - 1})

        i = j + 2  # resume past the breakout candle -- if there wasn't one, j+2 still safely exceeds n and ends the loop

    return boxes, breakouts


def build_paper_trades(
    candles: list[dict[str, Any]],
    boxes: list[dict[str, Any]],
    confirmed_momentum: list[dict[str, Any]],
    ema_slow: list[float | None],
    ema_enabled: bool,
) -> list[dict[str, Any]]:
    """Entry/exit rule synthesized from standard breakout-trading practice,
    with an explicit EMA20-hold override the user asked for on top:

    - Entry: at the close of the confirmed momentum candle itself -- the
      same candle already required to close beyond the range with a
      genuinely large body (and, when EMA is on, on the right side of the
      slow EMA). That close *is* the "decisive close beyond the level"
      entry trigger.
    - Stop: the opposite boundary of the consolidation box that was
      broken. Target: 2R off the actual entry price. These are computed
      and shown for reference, but only ever govern the exit when EMA is
      OFF -- see below.
    - Hold rule (when EMA is on): a long is held unconditionally as long
      as price keeps closing above the slow EMA; a short, as long as it
      keeps closing below it. Stop and target are deliberately NOT
      checked while that holds -- this is a trend-following exit, not a
      risk-first one, so a trade can give back more than the nominal
      stop distance before EMA20 catches up. The trade closes exactly on
      the candle whose close crosses to the wrong side of the slow EMA
      (reason "ema_exit").
    - When EMA is off, there's no trend line to hold against, so it
      falls back to the plain stop/target rule.

    A momentum candle near the end of the fetched history may have no
    exit yet -- that trade stays "open" as far as this history shows.

    Returns one dict per trade: {side, status, entryTime, entryPrice,
    stopLoss, exitTime, exitPrice, exitReason, pnlPercent} -- status/exit*
    fields are None while a trade is still open.
    """
    n = len(candles)
    trades: list[dict[str, Any]] = []

    for m in confirmed_momentum:
        idx = m["index"]
        side = m["side"]
        box = boxes[m["boxIndex"]]
        entry_price = float(candles[idx]["close"])
        stop = box["support"] if side == "long" else box["resistance"]
        risk = abs(entry_price - stop)
        target = entry_price + 2 * risk if side == "long" else entry_price - 2 * risk
        direction = 1 if side == "long" else -1

        trade: dict[str, Any] = {
            "side": side,
            "status": "open",
            "entryTime": candles[idx]["time"],
            "entryPrice": entry_price,
            "stopLoss": stop,
            "exitTime": None,
            "exitPrice": None,
            "exitReason": None,
            "pnlPercent": None,
        }

        for k in range(idx + 1, n):
            close_k = float(candles[k]["close"])

            if ema_enabled and ema_slow[k] is not None:
                held = (side == "long" and close_k > ema_slow[k]) or (side == "short" and close_k < ema_slow[k])
                if held:
                    continue
                reason = "ema_exit"
            else:
                hit_stop = (side == "long" and close_k <= stop) or (side == "short" and close_k >= stop)
                hit_target = (side == "long" and close_k >= target) or (side == "short" and close_k <= target)
                if not (hit_stop or hit_target):
                    continue
                reason = "target" if hit_target else "stop"

            trade.update(
                status="closed",
                exitTime=candles[k]["time"],
                exitPrice=close_k,
                exitReason=reason,
                pnlPercent=(close_k - entry_price) / entry_price * 100 * direction * LEVERAGE,
            )
            break

        trades.append(trade)

    return trades
