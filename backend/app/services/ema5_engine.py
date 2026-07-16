"""Pure 5-EMA scalping strategy logic (per ema5.txt): EMA calculation,
rolling alert-candle detection, entry triggers, R-multiple levels, and the
3-lot partial-exit/trailing-SL state machine. No I/O — takes plain data in,
returns plain data out, so it's unit-testable without any Dhan/DB dependency.

Trade management is index-price-driven, not option-premium-driven: every
SL/target/trail level here is a NIFTY index price. The option (ATM CE/PE) is
just the instrument bought/sold when an index-level event fires.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Side = Literal["CE", "PE"]
Phase = Literal["OPEN_ALL", "LOT1_BOOKED", "LOT2_BOOKED"]


@dataclass(frozen=True)
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float


def filter_completed_candles(candles: list[Candle], interval_minutes: int, now_epoch: int) -> list[Candle]:
    """Dhan's intraday endpoint includes the currently-forming bar as the last
    element when toDate is "now" (confirmed live: a single-tick OHLC where
    open=high=low=close). The strategy is defined on CLOSED candles only —
    evaluating an alert-candle or entry trigger against a still-forming bar
    would fire early on partial data. A candle at epoch `time` covers
    [time, time + interval*60); it's complete once that window has passed.
    """
    interval_seconds = interval_minutes * 60
    return [c for c in candles if c.time + interval_seconds <= now_epoch]


def compute_ema(closes: list[float], period: int = 5) -> list[float | None]:
    """Standard EMA, seeded with an SMA of the first `period` closes. Returns
    a list the same length as `closes`, with None for the warmup indices.
    """
    if len(closes) < period:
        return [None] * len(closes)
    multiplier = 2 / (period + 1)
    emas: list[float | None] = [None] * (period - 1)
    seed = sum(closes[:period]) / period
    emas.append(seed)
    prev = seed
    for close in closes[period:]:
        value = (close - prev) * multiplier + prev
        emas.append(value)
        prev = value
    return emas


def scan_for_signal(candles: list[Candle], emas: list[float | None], side: Side) -> dict[str, Any]:
    """Replays candles oldest-to-newest, tracking the rolling alert-candle
    per the doc's rule (a later qualifying candle replaces the earlier one
    if the entry trigger hasn't fired yet). Returns the alert-candle state as
    of the LAST candle, whether that last candle was itself an entry trigger
    (entryCandle is only non-None when the newest candle triggered), and — if
    so — the specific alert candle it triggered against (needed to compute
    SL, since `alertCandle` is cleared back to None once consumed).
    """
    alert: Candle | None = None
    entry_candle: Candle | None = None
    triggered_alert: Candle | None = None
    for candle, ema in zip(candles, emas):
        entry_candle = None
        triggered_alert = None
        if ema is None:
            continue
        if alert is not None:
            if side == "PE" and candle.low < alert.low:
                entry_candle = candle
                triggered_alert = alert
                alert = None
                continue
            if side == "CE" and candle.high > alert.high:
                entry_candle = candle
                triggered_alert = alert
                alert = None
                continue
        if side == "PE" and candle.close > ema and candle.low > ema:
            alert = candle
        elif side == "CE" and candle.close < ema and candle.high < ema:
            alert = candle
    return {"alertCandle": alert, "entryCandle": entry_candle, "triggeredAlertCandle": triggered_alert}


def compute_initial_sl(alert_candle: Candle, side: Side, min_sl_points: float) -> float:
    """SL at the alert candle's high (PE) / low (CE), floored at a minimum
    point distance from the trigger level so a very small alert candle
    doesn't produce an unrealistically tight stop.
    """
    trigger_level = alert_candle.low if side == "PE" else alert_candle.high
    raw_sl = alert_candle.high if side == "PE" else alert_candle.low
    distance = abs(trigger_level - raw_sl)
    if distance >= min_sl_points:
        return raw_sl
    return trigger_level + min_sl_points if side == "PE" else trigger_level - min_sl_points


def compute_levels(entry_price: float, sl_price: float, side: Side) -> dict[str, float]:
    risk = abs(entry_price - sl_price)
    direction = 1 if side == "CE" else -1
    return {
        "risk": risk,
        "target1": entry_price + direction * risk * 1.0,
        "target2": entry_price + direction * risk * 2.0,
        "target3": entry_price + direction * risk * 3.0,
    }


def evaluate_trade_tick(
    *,
    side: Side,
    entry_price: float,
    initial_sl: float,
    target1: float,
    target2: float,
    phase: Phase,
    lot3_trail_sl: float | None,
    spot: float,
    latest_completed_candle: Candle | None,
) -> dict[str, Any] | None:
    """One decision per call, evaluated against current spot (SL/target
    breach — needs live tick granularity) and the latest completed candle
    (trailing ratchet — a candle-close concept). Returns None if nothing
    should happen this tick.
    """
    is_ce = side == "CE"

    def favorable(level: float) -> bool:
        return spot >= level if is_ce else spot <= level

    def unfavorable(level: float) -> bool:
        return spot <= level if is_ce else spot >= level

    if phase == "OPEN_ALL":
        if unfavorable(initial_sl):
            return {"action": "STOP_ALL", "price": initial_sl}
        if favorable(target1):
            return {"action": "BOOK_LOT1", "price": target1, "newSl": entry_price}
        return None

    if phase == "LOT1_BOOKED":
        if unfavorable(entry_price):
            return {"action": "STOP_REMAINING", "price": entry_price}
        if favorable(target2):
            return {"action": "BOOK_LOT2", "price": target2, "newSl": target1}
        return None

    if phase == "LOT2_BOOKED":
        current_sl = lot3_trail_sl if lot3_trail_sl is not None else target1
        if unfavorable(current_sl):
            return {"action": "EXIT_LOT3", "price": current_sl}
        if latest_completed_candle is not None:
            candidate = latest_completed_candle.low if is_ce else latest_completed_candle.high
            if is_ce and candidate > current_sl:
                return {"action": "TRAIL_SL", "newSl": candidate}
            if not is_ce and candidate < current_sl:
                return {"action": "TRAIL_SL", "newSl": candidate}
        return None

    return None
