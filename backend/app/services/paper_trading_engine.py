"""Pure paper-trading logic: premium-percentage SL/target/trail state machine
and the standalone price-momentum breakout detector. No I/O -- takes plain
data in, returns plain data out, matching ema5_engine.py's discipline.

Unlike ema5 (index-price-driven, R-multiples off an alert candle), every
level here is a percentage of the OPTION PREMIUM itself, since that's what
the user specified (stop loss %, target %, trail %) and it's simpler: a
bought option's P&L only has one direction to reason about (premium up =
favorable), no CE/PE branching needed the way index-level moves require.
"""

from __future__ import annotations

from typing import Any, Literal

Phase = Literal["OPEN_ALL", "LOT1_BOOKED", "LOT2_BOOKED"]


def compute_levels(entry_premium: float, stop_loss_percent: float, target1_percent: float, target2_percent: float) -> dict[str, float]:
    return {
        "stopLoss": entry_premium * (1 - stop_loss_percent / 100),
        "target1": entry_premium * (1 + target1_percent / 100),
        "target2": entry_premium * (1 + target2_percent / 100),
    }


def evaluate_paper_trade_tick(
    *,
    stop_loss: float,
    target1: float,
    target2: float,
    trail_percent: float,
    phase: Phase,
    peak_premium: float | None,
    current_premium: float,
) -> dict[str, Any] | None:
    """One decision per call. All exits fill at `current_premium` (the
    observed poll value), not the theoretical level -- with periodic
    polling (not tick data) a real fill would rarely land exactly on the
    level, and using the observed price is the honest simulation for
    "future analysis" rather than an optimistic idealized one.
    """
    if phase == "OPEN_ALL":
        if current_premium <= stop_loss:
            return {"action": "STOP_ALL", "price": current_premium}
        if current_premium >= target1:
            return {"action": "BOOK_LOT1", "price": current_premium}
        return None

    if phase == "LOT1_BOOKED":
        if current_premium <= stop_loss:
            return {"action": "STOP_REMAINING", "price": current_premium}
        if current_premium >= target2:
            return {"action": "BOOK_LOT2", "price": current_premium, "peak": current_premium}
        return None

    if phase == "LOT2_BOOKED":
        peak = max(peak_premium or target2, current_premium)
        trail_sl = peak * (1 - trail_percent / 100)
        floor = max(trail_sl, stop_loss)  # the original SL still applies as a hard floor
        if current_premium <= floor:
            return {"action": "EXIT_LOT3", "price": current_premium, "peak": peak}
        if peak > (peak_premium or 0):
            return {"action": "UPDATE_PEAK", "peak": peak}
        return None

    return None


BREAKOUT_MIN_OBSERVATIONS = 10
BREAKOUT_Z_THRESHOLD = 2.0


def compute_breakout_events(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Port of the frontend's computeBreakoutEvents (PcrOiPanel.tsx) so the
    same pure price-momentum breakout can drive a server-side paper entry,
    not just a chart marker. Keep these two in sync if the algorithm changes.
    """
    events: list[dict[str, Any]] = []
    delta_history: list[float] = []
    active: str | None = None
    prev_dir: str | None = None

    for i in range(1, len(candles)):
        delta = candles[i]["close"] - candles[i - 1]["close"]
        delta_history.append(delta)
        direction: str | None = None
        if len(delta_history) >= BREAKOUT_MIN_OBSERVATIONS:
            mean = sum(delta_history) / len(delta_history)
            variance = sum((v - mean) ** 2 for v in delta_history) / len(delta_history)
            stdev = variance**0.5
            z = 0.0 if stdev == 0 else (delta - mean) / stdev
            if abs(z) >= BREAKOUT_Z_THRESHOLD:
                direction = "bullish" if delta > 0 else "bearish"

        if active is None:
            if direction is not None and direction == prev_dir:
                active = direction
                events.append({"time": candles[i]["time"], "kind": "enter", "direction": direction})
        elif direction != active:
            events.append({"time": candles[i]["time"], "kind": "exit", "direction": active})
            active = None
        prev_dir = direction

    return events
