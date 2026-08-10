"""Theta Book pure logic — day-type classification, distance-band selection,
strike picking, scale-in/exit rules. No I/O, no Dhan calls, no DB access;
see services/theta.py for the orchestration that wires this to live data,
mirroring the ema5_engine.py / animesh_engine.py separation used by the
other two strategies.

The rules encoded here come directly from selling_data/theta-book-strategy.md
(sections 02-05), calibrated against the user's own 28-30 Jul trade logs.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

DayType = Literal["expiry", "t1", "t2", "too_far"]


def trading_days_to_expiry(today: date, expiry: date) -> int:
    """Calendar days between today and expiry, skipping Saturdays/Sundays.
    NSE market holidays are not modeled (known v1 gap — see plan notes).
    """
    if expiry < today:
        return -1
    days = 0
    cursor = today
    while cursor < expiry:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days += 1
    return days


def classify_day_type(days_to_expiry: int) -> DayType:
    if days_to_expiry == 0:
        return "expiry"
    if days_to_expiry == 1:
        return "t1"
    if days_to_expiry == 2:
        return "t2"
    return "too_far"


def distance_band_for(
    day_type: DayType,
    confirmed_flat: bool,
    *,
    wide_min_pct: float,
    wide_max_pct: float,
    morning_min_pct: float,
    morning_max_pct: float,
    tight_min_pct: float,
    tight_max_pct: float,
) -> tuple[float, float] | None:
    if day_type in ("t1", "t2"):
        return (wide_min_pct, wide_max_pct)
    if day_type == "expiry":
        return (tight_min_pct, tight_max_pct) if confirmed_flat else (morning_min_pct, morning_max_pct)
    return None


def is_flat_market(
    *,
    opening_range_pct: float,
    range_so_far_pct: float,
    historical_range_low_pct: float,
    vix_now: float | None,
    vix_avg_5d: float | None,
    opening_range_threshold_pct: float,
) -> bool:
    """All three mechanically-checkable conditions from Section 03 of the
    note ('no pending catalyst' is handled by the caller — auto-passed in
    paper mode per the user's explicit instruction, not evaluated here).
    """
    if opening_range_pct > opening_range_threshold_pct:
        return False
    if range_so_far_pct >= historical_range_low_pct:
        return False
    if vix_now is not None and vix_avg_5d is not None and vix_now > vix_avg_5d:
        return False
    return True


def select_strike_for_band(
    chain: dict[str, Any], spot: float, side: str, min_pct: float, max_pct: float, hard_floor_pct: float
) -> dict[str, Any] | None:
    """Picks the richest (highest-premium) strike on `side` whose distance
    from spot falls within [min_pct, max_pct] — never below hard_floor_pct.
    Falls back to the closest-to-band candidate above the hard floor if
    nothing sits inside the band (chain strikes are discrete, so an exact
    band hit isn't guaranteed).
    """
    if not spot:
        return None
    oc = chain.get("oc") or {}
    key = "ce" if side == "CE" else "pe"
    in_band: list[tuple[float, float, dict[str, Any]]] = []
    above_floor: list[tuple[float, float, dict[str, Any]]] = []
    for strike_key, sides in oc.items():
        try:
            strike_price = float(strike_key)
        except (TypeError, ValueError):
            continue
        payload = (sides or {}).get(key)
        if not isinstance(payload, dict) or not payload.get("security_id"):
            continue
        premium = float(payload.get("last_price") or 0)
        if premium <= 0:
            continue
        distance_pct = abs(strike_price - spot) / spot * 100
        if distance_pct < hard_floor_pct:
            continue
        entry = (distance_pct, premium, {"strike": strike_price, "securityId": str(payload.get("security_id")), "premium": premium, "distancePct": distance_pct})
        above_floor.append(entry)
        if min_pct <= distance_pct <= max_pct:
            in_band.append(entry)

    pool = in_band or above_floor
    if not pool:
        return None
    best = max(pool, key=lambda item: item[1])
    return best[2]


def should_add_tranche(
    *,
    avg_entry_premium: float,
    live_premium: float,
    live_distance_pct: float,
    band_floor_pct: float,
    last_tranche_distance_pct: float,
    add_trigger_pct: float,
    tranche_count: int,
    max_tranches: int,
) -> bool:
    if tranche_count >= max_tranches:
        return False
    if live_premium < avg_entry_premium * (1 + add_trigger_pct / 100):
        return False
    if live_distance_pct < band_floor_pct:
        return False
    if live_distance_pct < last_tranche_distance_pct:
        return False
    return True


def should_exit_position(
    *,
    live_distance_pct: float,
    live_premium: float,
    avg_entry_premium: float,
    minutes_left: float,
    distance_stop_pct: float,
    distance_stop_min_minutes_left: float,
    premium_stop_multiple: float,
) -> tuple[bool, str | None]:
    if live_distance_pct < distance_stop_pct and minutes_left > distance_stop_min_minutes_left:
        return True, "DISTANCE_STOP"
    if live_premium > avg_entry_premium * premium_stop_multiple:
        return True, "PREMIUM_STOP"
    return False, None


def weighted_avg_premium(existing_qty: int, existing_avg: float | None, add_qty: int, add_premium: float) -> float:
    if not existing_qty or existing_avg is None:
        return add_premium
    new_qty = existing_qty + add_qty
    return ((existing_avg * existing_qty) + (add_premium * add_qty)) / new_qty


def estimate_margin(qty: int, lot_size: int, margin_per_lot: float) -> float:
    if lot_size <= 0:
        return 0.0
    lots = qty / lot_size
    return lots * margin_per_lot
