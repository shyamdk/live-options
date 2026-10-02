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
# Delta's published taker commission for the XAUTUSD perpetual -- confirmed
# live via GET /v2/products/XAUTUSD (taker_commission_rate: 0.0001; maker is
# the same). These paper trades always fill at a stop/target/trail level or
# an EMA-cross close, i.e. market fills, so both legs are charged at the
# taker rate -- there's no maker-fill case to model here.
TAKER_COMMISSION_RATE = 0.0001
# Chandelier-style trailing stop (see build_paper_trades): armed once a
# trade is up by this many ATRs, then trails the best close seen since
# entry by this many ATRs -- standard breakout-trading guidance for
# letting profits run without giving most of them back to a lagging
# trend-line exit.
TRAIL_ARM_ATR_MULTIPLE = 1.0
TRAIL_ATR_MULTIPLE = 3.0
# The EMA side-of-trend filter needs the close to genuinely clear the slow
# EMA, not just tick a hair past it -- a bare `close > ema_slow` was
# confirming longs on margins as thin as 0.0072 on XAUT (real case: close
# 4375.27 vs EMA20 4375.2628), which is noise, not trend confirmation.
# Scales with ATR rather than a fixed point value so it stays meaningful
# across volatility regimes.
EMA_CONFIRM_ATR_BUFFER = 0.1
# Book profits outright once RSI reaches a genuinely overbought/oversold
# extreme, regardless of what the trailing stop/EMA-hold would otherwise
# allow -- this is a deliberate profit-taking rule, not a risk stop, so it's
# checked ahead of (can fire before) the trailing stop below. Same RSI(14)
# series already computed for the chart, not a separate calculation.
RSI_PERIOD = 14
RSI_LONG_EXIT = 90.0
RSI_SHORT_EXIT = 20.0

Side = Literal["long", "short"]


def stop_fill_price(side: Side, level: float, open_price: float) -> float:
    # A stop order fills the instant price touches it intrabar, not only at
    # the candle's close -- and if the candle gapped straight past the
    # level, the fill is the open (can't get a better price than what the
    # market opened at), not the level itself.
    if side == "long":
        return min(open_price, level) if open_price <= level else level
    return max(open_price, level) if open_price >= level else level


def check_ema_trail_exit(
    *,
    side: Side,
    entry_price: float,
    best_close: float,
    close: float,
    high: float,
    low: float,
    open_price: float,
    ema_slow_value: float | None,
    atr_value: float | None,
    trail_stop: float | None,
    rsi_value: float | None = None,
    rsi_long_exit: float = RSI_LONG_EXIT,
    rsi_short_exit: float = RSI_SHORT_EXIT,
    hard_stop: float | None = None,
) -> dict[str, Any]:
    """One tick of pStrategy's EMA-hold + ATR-Chandelier-trail exit rule for
    an already-open position -- shared verbatim between the batch replay
    below (build_paper_trades) and a live per-tick poll loop (see
    pstrategy_nifty.py) so both apply exactly the same rule rather than two
    hand-maintained copies that could drift apart.

    Checked first, ahead of everything else: an RSI extreme (>= rsi_long_exit
    on a long, <= rsi_short_exit on a short) books profit immediately at the
    current close, regardless of where the trailing stop or EMA currently
    sit -- this is a deliberate take-profit rule, not a risk stop, so it
    doesn't wait for either of those to catch up.

    Otherwise, held as long as `close` stays on the favorable side of
    `ema_slow_value`. Layered on top: once up TRAIL_ARM_ATR_MULTIPLE x ATR
    from entry, a Chandelier stop arms at `best_close` -/+
    TRAIL_ATR_MULTIPLE x ATR, ratcheting only in the position's favor,
    checked intrabar (low/high) -- this can exit even while `close` is
    still technically held.

    `hard_stop`, when given, is the entry-time invalidation level (the
    opposite boundary of the box the breakout came from -- see
    build_paper_trades) and is active from the very first tick, unlike the
    ATR trail which only arms once the trade is already favorable. Without
    it, a position that reverses hard before the trail ever arms has no
    price-based protection at all -- only the lagging EMA-close check,
    which can't react until a candle finishes closing (real case: a
    XAUTUSD short on 21 Sep lost -11.66% net because the reversal candle's
    own close was already past the EMA before the trail had armed). Once a
    tighter trail level exists, whichever of the two is more protective
    wins each tick -- the hard stop doesn't get looser just because the
    trail hasn't caught up to it yet, but the trail can supersede it once
    it's tighter.

    Returns {"exit", "bestClose", "trailStop", "exitPrice", "reason"} --
    `bestClose`/`trailStop` are always returned (updated even when not
    exiting) so the caller carries them into the next tick; `exitPrice`/
    `reason` are None unless `exit` is True.
    """
    new_best_close = max(best_close, close) if side == "long" else min(best_close, close)
    new_trail_stop = trail_stop

    if rsi_value is not None and (
        (side == "long" and rsi_value >= rsi_long_exit) or (side == "short" and rsi_value <= rsi_short_exit)
    ):
        return {"exit": True, "bestClose": new_best_close, "trailStop": new_trail_stop, "exitPrice": close, "reason": "rsi_target"}

    if ema_slow_value is None:
        return {"exit": False, "bestClose": new_best_close, "trailStop": new_trail_stop, "exitPrice": None, "reason": None}

    if atr_value:
        favorable_move = (new_best_close - entry_price) if side == "long" else (entry_price - new_best_close)
        if new_trail_stop is not None or favorable_move >= TRAIL_ARM_ATR_MULTIPLE * atr_value:
            candidate = (
                new_best_close - TRAIL_ATR_MULTIPLE * atr_value
                if side == "long"
                else new_best_close + TRAIL_ATR_MULTIPLE * atr_value
            )
            new_trail_stop = (
                candidate
                if new_trail_stop is None
                else (max(new_trail_stop, candidate) if side == "long" else min(new_trail_stop, candidate))
            )

    # The active stop each tick is whichever of the hard invalidation level
    # and the (possibly not-yet-armed) trail is more protective -- i.e.
    # closer to price. Before the trail arms, that's just the hard stop;
    # once armed, the trail can only ever tighten it further, never loosen.
    effective_stop = new_trail_stop
    if hard_stop is not None:
        effective_stop = hard_stop if effective_stop is None else (
            max(effective_stop, hard_stop) if side == "long" else min(effective_stop, hard_stop)
        )

    # Checked intrabar (low/high), not just the close -- a sharp reversal
    # that round-trips within a single candle would otherwise only be
    # caught after the fact, at the close, defeating the point of a stop.
    hit_stop = effective_stop is not None and (
        (side == "long" and low <= effective_stop) or (side == "short" and high >= effective_stop)
    )
    if hit_stop:
        exit_price = stop_fill_price(side, effective_stop, open_price)
        reason = "trail_stop" if new_trail_stop is not None and effective_stop == new_trail_stop else "hard_stop"
        return {"exit": True, "bestClose": new_best_close, "trailStop": new_trail_stop, "exitPrice": exit_price, "reason": reason}

    held = (side == "long" and close > ema_slow_value) or (side == "short" and close < ema_slow_value)
    if held:
        return {"exit": False, "bestClose": new_best_close, "trailStop": new_trail_stop, "exitPrice": None, "reason": None}

    return {"exit": True, "bestClose": new_best_close, "trailStop": new_trail_stop, "exitPrice": close, "reason": "ema_exit"}


def charges_percent_of_margin(entry_price: float, exit_price: float) -> float:
    """Round-trip taker fee, expressed as a percent of margin (same units as
    pnlPercent) so it can be subtracted from it directly.

    Fee is levied on notional traded, not on the price move. At entry, the
    position's notional is LEVERAGE times margin by construction (that's
    what "LEVERAGE x margin" means). The exit leg trades that same
    contract count at exit_price, so its notional as a fraction of margin
    scales by exit_price/entry_price rather than staying at exactly
    LEVERAGE -- e.g. a short that's up 1% has an exit notional 1% smaller
    than its entry notional, and pays a hair less fee on that leg.
    """
    entry_leg = LEVERAGE
    exit_leg = LEVERAGE * (exit_price / entry_price)
    return TAKER_COMMISSION_RATE * 100 * (entry_leg + exit_leg)


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


def confirm_momentum(
    breakouts: list[dict[str, Any]],
    candles: list[dict[str, Any]],
    ema_slow: list[float | None],
    atr_values: list[float | None],
) -> list[dict[str, Any]]:
    """Applies the EMA20 side-of-trend filter to raw breakouts from
    detect_patterns -- shared between the batch API (api/pstrategy.py) and
    the live poll loop (pstrategy_nifty.py) so both use the identical rule.
    A breakout only counts once its candle's close clears the slow EMA by
    at least EMA_CONFIRM_ATR_BUFFER x ATR in its own direction (see that
    constant's docstring for why a bare `>`/`<` isn't enough).
    """
    confirmed = []
    for b in breakouts:
        idx = b["index"]
        slow_value = ema_slow[idx]
        atr_at_idx = atr_values[idx]
        if slow_value is None or not atr_at_idx:
            continue
        close_price = float(candles[idx]["close"])
        buffer = EMA_CONFIRM_ATR_BUFFER * atr_at_idx
        if (b["side"] == "long" and close_price > slow_value + buffer) or (
            b["side"] == "short" and close_price < slow_value - buffer
        ):
            confirmed.append(b)
    return confirmed


def build_paper_trades(
    candles: list[dict[str, Any]],
    boxes: list[dict[str, Any]],
    confirmed_momentum: list[dict[str, Any]],
    ema_slow: list[float | None],
    ema_enabled: bool,
    atr_values: list[float | None],
    rsi_values: list[float | None] | None = None,
    rsi_long_exit: float = RSI_LONG_EXIT,
    rsi_short_exit: float = RSI_SHORT_EXIT,
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
    - RSI profit-booking, checked ahead of everything else in both modes:
      once RSI(14) reaches rsi_long_exit (long) or rsi_short_exit (short),
      the trade closes immediately at that candle's close (reason
      "rsi_target"), regardless of where the trailing stop/EMA-hold or
      stop/target would otherwise allow it to run.

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
            "chargesPercent": None,
            "netPnlPercent": None,
        }

        best_close = entry_price
        trail_stop: float | None = None

        for k in range(idx + 1, n):
            close_k = float(candles[k]["close"])
            high_k, low_k, open_k = float(candles[k]["high"]), float(candles[k]["low"]), float(candles[k]["open"])
            exit_price = close_k

            rsi_k = rsi_values[k] if rsi_values else None

            if ema_enabled and ema_slow[k] is not None:
                result = check_ema_trail_exit(
                    side=side,
                    entry_price=entry_price,
                    best_close=best_close,
                    close=close_k,
                    high=high_k,
                    low=low_k,
                    open_price=open_k,
                    ema_slow_value=ema_slow[k],
                    atr_value=atr_values[k],
                    trail_stop=trail_stop,
                    rsi_value=rsi_k,
                    rsi_long_exit=rsi_long_exit,
                    rsi_short_exit=rsi_short_exit,
                    hard_stop=stop,
                )
                best_close = result["bestClose"]
                trail_stop = result["trailStop"]
                if not result["exit"]:
                    continue
                exit_price = result["exitPrice"]
                reason = result["reason"]
            else:
                best_close = max(best_close, close_k) if side == "long" else min(best_close, close_k)
                rsi_hit = rsi_k is not None and (
                    (side == "long" and rsi_k >= rsi_long_exit) or (side == "short" and rsi_k <= rsi_short_exit)
                )
                hit_stop = (side == "long" and low_k <= stop) or (side == "short" and high_k >= stop)
                hit_target = (side == "long" and high_k >= target) or (side == "short" and low_k <= target)
                if not (rsi_hit or hit_stop or hit_target):
                    continue
                # RSI profit-booking takes priority (it's the reason to exit
                # at all here, not a risk stop), then stop over target if a
                # single wild candle hits both of those.
                reason = "rsi_target" if rsi_hit else ("stop" if hit_stop else "target")
                exit_price = close_k if rsi_hit else (stop_fill_price(side, stop, open_k) if hit_stop else target)

            pnl_percent = (exit_price - entry_price) / entry_price * 100 * direction * LEVERAGE
            charges_percent = charges_percent_of_margin(entry_price, exit_price)
            trade.update(
                status="closed",
                exitTime=candles[k]["time"],
                exitPrice=exit_price,
                exitReason=reason,
                pnlPercent=pnl_percent,
                chargesPercent=charges_percent,
                netPnlPercent=pnl_percent - charges_percent,
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
