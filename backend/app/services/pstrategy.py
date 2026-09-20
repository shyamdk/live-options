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
# Chandelier-style trailing stop (see build_paper_trades): armed once a
# trade is up by this many ATRs, then trails the best close seen since
# entry by this many ATRs -- standard breakout-trading guidance for
# letting profits run without giving most of them back to a lagging
# trend-line exit.
TRAIL_ARM_ATR_MULTIPLE = 1.0
TRAIL_ATR_MULTIPLE = 3.0

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
    atr_values: list[float | None],
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
      stop distance before EMA20 catches up.
    - ATR trailing stop, layered on top: once a trade is up by
      TRAIL_ARM_ATR_MULTIPLE x ATR from entry, a Chandelier-style stop
      arms at (best close since entry) -/+ TRAIL_ATR_MULTIPLE x ATR,
      ratcheting only in the trade's favor. This exists specifically
      because the EMA-hold rule is a lagging exit -- a sharp reversal
      candle can round-trip most of an open gain before price finally
      closes back over/under EMA20. Once armed, a close beyond this
      trail exits immediately (reason "trail_stop"), even though price
      is still technically on the right side of EMA20.
    - When EMA is off, there's no trend line to hold against (or trail
      against), so it falls back to the plain stop/target rule.

    A momentum candle near the end of the fetched history may have no
    exit yet -- that trade stays "open" as far as this history shows.
    Only one position is held at a time: a momentum signal that fires
    before the current position has exited is skipped entirely, rather
    than opening a second "trade" in parallel -- that's not a real
    strategy behavior, it was a bug (seen live: a signal at 16:10 fired
    while a still-open 15:35 short hadn't exited yet, and both showed up
    as separate open trades).

    Returns one dict per trade: {side, status, entryTime, entryPrice,
    stopLoss, peakPrice, trailStop, exitTime, exitPrice, exitReason,
    pnlPercent} -- status/exit* fields are None while a trade is still
    open. peakPrice/trailStop are the running best-close-since-entry and
    current Chandelier trail level (None until armed) -- for a closed
    trade these are the values as of the exit candle; for an open one,
    as of the latest fetched candle.
    """
    n = len(candles)
    trades: list[dict[str, Any]] = []
    next_available_index = 0

    for m in confirmed_momentum:
        idx = m["index"]
        if idx < next_available_index:
            continue
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
            "peakPrice": entry_price,
            "trailStop": None,
            "exitTime": None,
            "exitPrice": None,
            "exitReason": None,
            "pnlPercent": None,
        }

        best_close = entry_price
        trail_stop: float | None = None

        def stop_fill_price(level: float, open_k: float) -> float:
            # A stop order fills the instant price touches it intrabar,
            # not only at the candle's close -- and if the candle gapped
            # straight past the level, the fill is the open (can't get a
            # better price than what the market opened at), not the
            # level itself. Targets, by contrast, are limit orders --
            # filled at the target price even on a favorable gap through
            # it, so they don't need this adjustment.
            if side == "long":
                return min(open_k, level) if open_k <= level else level
            return max(open_k, level) if open_k >= level else level

        for k in range(idx + 1, n):
            close_k = float(candles[k]["close"])
            high_k, low_k, open_k = float(candles[k]["high"]), float(candles[k]["low"]), float(candles[k]["open"])
            best_close = max(best_close, close_k) if side == "long" else min(best_close, close_k)
            exit_price = close_k

            if ema_enabled and ema_slow[k] is not None:
                atr_k = atr_values[k]
                if atr_k:
                    favorable_move = (best_close - entry_price) if side == "long" else (entry_price - best_close)
                    if trail_stop is not None or favorable_move >= TRAIL_ARM_ATR_MULTIPLE * atr_k:
                        candidate = best_close - TRAIL_ATR_MULTIPLE * atr_k if side == "long" else best_close + TRAIL_ATR_MULTIPLE * atr_k
                        trail_stop = candidate if trail_stop is None else (max(trail_stop, candidate) if side == "long" else min(trail_stop, candidate))

                # Checked intrabar (low/high), not just the close -- a
                # sharp reversal that round-trips within a single candle
                # (seen live: a 5m candle that opened 4379.77, dipped to
                # 4378.09, closed 4378.11) would otherwise only be caught
                # after the fact, at the close, defeating the point of a
                # trailing stop.
                hit_trail = trail_stop is not None and ((side == "long" and low_k <= trail_stop) or (side == "short" and high_k >= trail_stop))
                if hit_trail:
                    exit_price = stop_fill_price(trail_stop, open_k)
                held = (side == "long" and close_k > ema_slow[k]) or (side == "short" and close_k < ema_slow[k])
                if not hit_trail and held:
                    continue
                reason = "trail_stop" if hit_trail else "ema_exit"
            else:
                hit_stop = (side == "long" and low_k <= stop) or (side == "short" and high_k >= stop)
                hit_target = (side == "long" and high_k >= target) or (side == "short" and low_k <= target)
                if not (hit_stop or hit_target):
                    continue
                # Stop takes priority if a single wild candle hits both.
                reason = "stop" if hit_stop else "target"
                exit_price = stop_fill_price(stop, open_k) if hit_stop else target

            trade.update(
                status="closed",
                exitTime=candles[k]["time"],
                exitPrice=exit_price,
                exitReason=reason,
                pnlPercent=(exit_price - entry_price) / entry_price * 100 * direction * LEVERAGE,
                peakPrice=best_close,
                trailStop=trail_stop,
            )
            next_available_index = k + 1
            break
        else:
            # Loop ran to the end of history without exiting -- still
            # open, but expose the running peak/trail so it's visible
            # what's currently protecting the position, not just the
            # original box-boundary stop. Blocks every later signal too
            # (next_available_index = n), since we're still in this
            # position through the end of the fetched history.
            trade["peakPrice"] = best_close
            trade["trailStop"] = trail_stop
            next_available_index = n

        trades.append(trade)

    return trades
