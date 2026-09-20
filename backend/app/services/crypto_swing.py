"""Crypto-Swing paper-trading simulation -- a pure, deterministic replay
of the 3-way confirmation strategy (crypto-swing-trading.md) over a
candle+indicator history. No DB, no background task: every call
recomputes the full trade sequence from Delta's own candle history, so
there's no persisted state that can drift or corrupt -- the trade list
*is* what the strategy would have done, always reproducible from Delta's
data alone.

Resolved ambiguities from the strategy doc (confirmed with the user):
- Section 4 (trap detection) overrides Section 6's blanket "exit on any
  Supertrend flip" -- a counter-trend flip only closes the position once
  price actually closes beyond both the pivot level AND the 200 EMA.
  Until then it's held as a suspected trap. This doubles as Section 6.3's
  "volume exit confirmation" -- they're the same check, not two.
- Pyramiding (Section 5) fires only on the specific re-entry event
  Section 4 names (Supertrend flips back in the position's favor after a
  counter-trend excursion), not on every pullback touch -- otherwise
  adds would be unbounded. Capped at max_tranches regardless.
- Position sizing is illustrative paper notional per tranche (not real
  capital), since no live orders are placed yet.
- An ATR trailing stop (same mechanism as pStrategy's, added for the
  same reason) runs alongside the trap-detection hold: since holding
  through a suspected trap is itself a lagging exit, once a position is
  up TRAIL_ARM_ATR_MULTIPLE x ATR it arms a Chandelier-style stop that
  trails the best close by TRAIL_ATR_MULTIPLE x ATR and can exit even
  while a counter-move is still being held as a trap. Checked intrabar
  (low/high), with the fill capped at the candle's open on a gap
  through the level, matching how a real stop order actually fills.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from app.services.crypto_indicators import atr as compute_atr
from app.services.crypto_indicators import ema, macd, supertrend
from app.services.delta_exchange import DeltaExchangeService

Side = Literal["long", "short"]

MAX_TRANCHES = 3
NOTIONAL_PER_TRANCHE = 500.0
ATR_LOOKBACK = 14
# Chandelier-style trailing stop (see simulate_trades): armed once a
# position is up by this many ATRs, then trails the best close seen
# since entry by this many ATRs -- same mechanism as pStrategy's, added
# for the same reason: the trap-detection hold is a lagging exit, so a
# sharp reversal can round-trip most of an open gain before it fires.
#
# These are NOT pStrategy's 1.0/3.0 -- that pairing was tuned for 5m
# gold candles and, tested against this 30m/multi-day context, actively
# hurt: it gave back 62% of a real BTCUSD move, and for XAUTUSD the trail
# distance (3x ATR) exceeded the entire favorable excursion, so the
# "trailing stop" never protected any profit at all and let a winning
# trade round-trip into a loss. Widening the arm threshold (so it only
# engages once there's a real cushion) and tightening the trail once
# armed fixed both cases when tested against the same live data --
# though with only one closed trade per symbol in the fetched history,
# that's a single data point per symbol, not a real backtest. Both are
# configurable (see the /trades endpoint's query params) precisely
# because this needs more data to validate properly.
TRAIL_ARM_ATR_MULTIPLE = 2.0
TRAIL_ATR_MULTIPLE = 1.5

SYMBOLS = ("BTCUSD", "ETHUSD", "XAUTUSD")
RESOLUTION_SECONDS = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600}


class IndicatorBundle:
    def __init__(
        self,
        ordered: list[dict[str, Any]],
        ema200: list[float | None],
        macd_line: list[float | None],
        signal_line: list[float | None],
        histogram: list[float | None],
        st_values: list[float | None],
        st_directions: list[str | None],
        atr_values: list[float | None],
    ) -> None:
        self.ordered = ordered
        self.ema200 = ema200
        self.macd_line = macd_line
        self.signal_line = signal_line
        self.histogram = histogram
        self.st_values = st_values
        self.st_directions = st_directions
        self.atr_values = atr_values


async def load_indicators(symbol: str, resolution: str) -> IndicatorBundle:
    """Shared by the paper-trading API (per-request replay) and the live
    engine (per-poll state diff) so both always agree on what the strategy
    is currently doing -- one implementation, not two that could drift.
    """
    step = RESOLUTION_SECONDS.get(resolution, 1800)
    # 200 EMA needs 200+ candles of history; fetch a healthy buffer beyond
    # that so the indicator has already stabilized by the earliest candle
    # actually shown/simulated.
    lookback_candles = 400
    end = int(time.time())
    start = end - step * lookback_candles

    raw = await DeltaExchangeService().get_candles(symbol, resolution, start, end)
    ordered = sorted(raw, key=lambda c: c["time"])
    closes = [float(c["close"]) for c in ordered]

    ema200 = ema(closes, 200)
    macd_line, signal_line, histogram = macd(closes)
    st_values, st_directions = supertrend(ordered, period=13, multiplier=4.0)
    atr_values = compute_atr(ordered, ATR_LOOKBACK)
    return IndicatorBundle(ordered, ema200, macd_line, signal_line, histogram, st_values, st_directions, atr_values)


def simulate_trades(
    candles: list[dict[str, Any]],
    ema200: list[float | None],
    macd_line: list[float | None],
    signal_line: list[float | None],
    histogram: list[float | None],
    st_values: list[float | None],
    st_directions: list[str | None],
    atr_values: list[float | None],
    trail_arm_atr_multiple: float = TRAIL_ARM_ATR_MULTIPLE,
    trail_atr_multiple: float = TRAIL_ATR_MULTIPLE,
) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    n = len(candles)

    position: Side | None = None
    entry_time: int | None = None
    fills: list[tuple[float, float]] = []  # (price, quantity) per tranche, for a weighted avg entry
    stop = 0.0
    trap_active = False
    pivot_level = 0.0
    pivot_volume = -1.0
    best_close = 0.0
    trail_stop: float | None = None

    def avg_entry_price() -> float:
        return sum(p * q for p, q in fills) / sum(q for _, q in fills)

    def stop_fill_price(level: float, open_i: float) -> float:
        # A stop fills the instant price touches it intrabar, not only at
        # the candle's close -- and if the candle gapped straight past
        # the level, the fill is the open (can't get a better price than
        # what the market opened at), not the level itself.
        if position == "long":
            return min(open_i, level) if open_i <= level else level
        return max(open_i, level) if open_i >= level else level

    def close_position(i: int, reason: str, exit_price: float) -> None:
        nonlocal position, entry_time, fills, trap_active, pivot_level, pivot_volume, best_close, trail_stop
        total_qty = sum(q for _, q in fills)
        avg_entry = avg_entry_price()
        direction = 1 if position == "long" else -1
        pnl_pct = (exit_price - avg_entry) / avg_entry * 100 * direction
        trades.append(
            {
                "side": position,
                "status": "closed",
                "entryTime": entry_time,
                "entryPrice": avg_entry,
                "tranches": len(fills),
                "quantity": total_qty,
                "exitTime": candles[i]["time"],
                "exitPrice": exit_price,
                "exitReason": reason,
                "pnlPercent": pnl_pct,
                "pnlAmount": pnl_pct / 100 * NOTIONAL_PER_TRANCHE * len(fills),
                "peakPrice": best_close,
                "trailStop": trail_stop,
            }
        )
        position, entry_time, fills = None, None, []
        trap_active, pivot_level, pivot_volume = False, 0.0, -1.0
        best_close, trail_stop = 0.0, None

    for i in range(n):
        close = float(candles[i]["close"])
        open_i = float(candles[i]["open"])
        low, high = float(candles[i]["low"]), float(candles[i]["high"])
        volume = float(candles[i].get("volume") or 0.0)
        ema = ema200[i]
        macd_v, signal_v, hist_v = macd_line[i], signal_line[i], histogram[i]
        direction = st_directions[i]
        prev_direction = st_directions[i - 1] if i > 0 else None
        atr_i = atr_values[i]

        if ema is None or macd_v is None or signal_v is None or hist_v is None or direction is None:
            continue

        if position is None:
            flipped_up = direction == "up" and prev_direction == "down"
            flipped_down = direction == "down" and prev_direction == "up"
            if flipped_up and close > ema and macd_v > 0 and signal_v > 0 and hist_v > 0:
                position, entry_time, fills = "long", candles[i]["time"], [(close, 1.0)]
                stop = st_values[i] or close
                best_close, trail_stop = close, None
            elif flipped_down and close < ema and macd_v < 0 and signal_v < 0 and hist_v < 0:
                position, entry_time, fills = "short", candles[i]["time"], [(close, 1.0)]
                stop = st_values[i] or close
                best_close, trail_stop = close, None
            continue

        best_close = max(best_close, close) if position == "long" else min(best_close, close)

        # ATR trailing stop -- checked every candle, ahead of the trap
        # logic below, so it can exit even while a counter-move is still
        # being held as a suspected trap. Armed once up TRAIL_ARM_ATR_MULTIPLE
        # x ATR from the (blended) entry; from there, trails best_close by
        # TRAIL_ATR_MULTIPLE x ATR, ratcheting only in the position's favor.
        # Checked against intrabar low/high, not just the close, since a
        # sharp reversal can happen within a single candle.
        if atr_i:
            avg_entry = avg_entry_price()
            favorable_move = (best_close - avg_entry) if position == "long" else (avg_entry - best_close)
            if trail_stop is not None or favorable_move >= trail_arm_atr_multiple * atr_i:
                candidate = best_close - trail_atr_multiple * atr_i if position == "long" else best_close + trail_atr_multiple * atr_i
                trail_stop = candidate if trail_stop is None else (max(trail_stop, candidate) if position == "long" else min(trail_stop, candidate))
        if trail_stop is not None:
            hit_trail = (position == "long" and low <= trail_stop) or (position == "short" and high >= trail_stop)
            if hit_trail:
                close_position(i, "trail_stop", stop_fill_price(trail_stop, open_i))
                continue

        stop = st_values[i] or stop
        against_position = (position == "long" and direction == "down") or (position == "short" and direction == "up")

        if not against_position:
            if trap_active:
                # Supertrend flipped back in our favor -- the counter-move
                # was a trap; treat this as a high-probability continuation
                # and scale in (Section 5), then drop the trap state.
                if len(fills) < MAX_TRANCHES:
                    fills.append((close, 1.0))
                trap_active, pivot_level, pivot_volume = False, 0.0, -1.0
            continue

        # Against the position: track the highest-volume candle of this
        # counter-move and use ITS low/high as the pivot (Section 4), not
        # just the raw min/max -- a real reversal shows conviction volume.
        if not trap_active:
            trap_active, pivot_volume = True, volume
            pivot_level = low if position == "long" else high
        elif volume > pivot_volume:
            pivot_volume = volume
            pivot_level = low if position == "long" else high

        broke_pivot = close < pivot_level if position == "long" else close > pivot_level
        broke_ema = close < ema if position == "long" else close > ema
        if broke_pivot and broke_ema:
            close_position(i, "trap_confirmed_reversal", close)

    if position is not None:
        total_qty = sum(q for _, q in fills)
        avg_entry = avg_entry_price()
        trades.append(
            {
                "side": position,
                "status": "open",
                "entryTime": entry_time,
                "entryPrice": avg_entry,
                "tranches": len(fills),
                "quantity": total_qty,
                "exitTime": None,
                "exitPrice": None,
                "exitReason": None,
                "stopLoss": stop,
                "peakPrice": best_close,
                "trailStop": trail_stop,
                "pnlPercent": None,
                "pnlAmount": None,
            }
        )

    return trades
