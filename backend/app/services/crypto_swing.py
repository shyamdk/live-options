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
"""

from __future__ import annotations

from typing import Any, Literal

Side = Literal["long", "short"]

MAX_TRANCHES = 3
NOTIONAL_PER_TRANCHE = 500.0


def simulate_trades(
    candles: list[dict[str, Any]],
    ema200: list[float | None],
    macd_line: list[float | None],
    signal_line: list[float | None],
    histogram: list[float | None],
    st_values: list[float | None],
    st_directions: list[str | None],
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

    def flat_pnl_percent(exit_price: float) -> float:
        avg_entry = sum(p * q for p, q in fills) / sum(q for _, q in fills)
        direction = 1 if position == "long" else -1
        return (exit_price - avg_entry) / avg_entry * 100 * direction

    def close_position(i: int, reason: str) -> None:
        nonlocal position, entry_time, fills, trap_active, pivot_level, pivot_volume
        exit_price = float(candles[i]["close"])
        total_qty = sum(q for _, q in fills)
        avg_entry = sum(p * q for p, q in fills) / total_qty
        pnl_pct = flat_pnl_percent(exit_price)
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
            }
        )
        position, entry_time, fills = None, None, []
        trap_active, pivot_level, pivot_volume = False, 0.0, -1.0

    for i in range(n):
        close = float(candles[i]["close"])
        low, high = float(candles[i]["low"]), float(candles[i]["high"])
        volume = float(candles[i].get("volume") or 0.0)
        ema = ema200[i]
        macd_v, signal_v, hist_v = macd_line[i], signal_line[i], histogram[i]
        direction = st_directions[i]
        prev_direction = st_directions[i - 1] if i > 0 else None

        if ema is None or macd_v is None or signal_v is None or hist_v is None or direction is None:
            continue

        if position is None:
            flipped_up = direction == "up" and prev_direction == "down"
            flipped_down = direction == "down" and prev_direction == "up"
            if flipped_up and close > ema and macd_v > 0 and signal_v > 0 and hist_v > 0:
                position, entry_time, fills = "long", candles[i]["time"], [(close, 1.0)]
                stop = st_values[i] or close
            elif flipped_down and close < ema and macd_v < 0 and signal_v < 0 and hist_v < 0:
                position, entry_time, fills = "short", candles[i]["time"], [(close, 1.0)]
                stop = st_values[i] or close
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
            close_position(i, "trap_confirmed_reversal")

    if position is not None:
        total_qty = sum(q for _, q in fills)
        avg_entry = sum(p * q for p, q in fills) / total_qty
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
                "pnlPercent": None,
                "pnlAmount": None,
            }
        )

    return trades
