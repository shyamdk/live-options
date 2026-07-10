"""Pure gamma-blast strategy logic: wall detection, quiet-day gate, breakout and
exit signal evaluation. No I/O — takes plain data in, returns plain data out, so
it can be unit-tested without any Dhan/DB/network dependency (the one exception
is now_ist(), a thin clock read shared by the orchestration and DB layers).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    """Naive datetime whose fields are IST wall-clock time, regardless of the
    host server's own system timezone (OCI runs GMT). Deliberately returned as
    naive (tzinfo stripped) so it arithmetics cleanly against timestamps stored
    via isoformat() elsewhere in this module without any aware/naive mixing.
    """
    return datetime.now(_IST).replace(tzinfo=None)


@dataclass(frozen=True)
class StrikeState:
    strike: float
    option_side: str  # "CE" | "PE"
    security_id: str
    ltp: float | None
    oi: float | None


def find_walls(
    strikes: list[StrikeState],
    spot: float,
    *,
    strike_step: float,
    strike_range: int,
    min_oi_threshold: float,
) -> dict[str, dict[str, Any] | None]:
    """Highest-OI CE strike above spot (within range) = call wall; highest-OI PE
    strike below spot (within range) = put wall.
    """
    max_distance = strike_step * strike_range
    call_candidates = [
        s
        for s in strikes
        if s.option_side == "CE"
        and s.oi is not None
        and s.oi >= min_oi_threshold
        and spot < s.strike <= spot + max_distance
    ]
    put_candidates = [
        s
        for s in strikes
        if s.option_side == "PE"
        and s.oi is not None
        and s.oi >= min_oi_threshold
        and spot - max_distance <= s.strike < spot
    ]
    call_wall = max(call_candidates, key=lambda s: s.oi or 0) if call_candidates else None
    put_wall = max(put_candidates, key=lambda s: s.oi or 0) if put_candidates else None
    return {
        "callWall": _strike_dict(call_wall),
        "putWall": _strike_dict(put_wall),
    }


def _strike_dict(strike: StrikeState | None) -> dict[str, Any] | None:
    if strike is None:
        return None
    return {
        "strike": strike.strike,
        "optionSide": strike.option_side,
        "securityId": strike.security_id,
        "ltp": strike.ltp,
        "oi": strike.oi,
    }


def quiet_day_status(spot: float, session_open: float, max_percent: float) -> dict[str, Any]:
    if session_open <= 0:
        return {"isQuiet": False, "movePercent": None}
    move_percent = abs(spot - session_open) / session_open * 100
    return {"isQuiet": move_percent < max_percent, "movePercent": round(move_percent, 3)}


def in_time_window(now: time, start: str, end: str) -> bool:
    start_time = _parse_time(start)
    end_time = _parse_time(end)
    return start_time <= now <= end_time


def _parse_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def check_breakouts(
    spot: float,
    call_wall: dict[str, Any] | None,
    put_wall: dict[str, Any] | None,
    *,
    buffer_points: float,
) -> list[dict[str, Any]]:
    """Both-sides: independently check the call-wall and put-wall breakout —
    either, neither, or (rarely) both can fire.
    """
    breakouts: list[dict[str, Any]] = []
    if call_wall is not None and spot >= call_wall["strike"] + buffer_points:
        breakouts.append(
            {
                "side": "CE",
                "strike": call_wall["strike"],
                "securityId": call_wall["securityId"],
                "wallOi": call_wall["oi"],
                "spotAtTrigger": spot,
            }
        )
    if put_wall is not None and spot <= put_wall["strike"] - buffer_points:
        breakouts.append(
            {
                "side": "PE",
                "strike": put_wall["strike"],
                "securityId": put_wall["securityId"],
                "wallOi": put_wall["oi"],
                "spotAtTrigger": spot,
            }
        )
    return breakouts


def evaluate_exit(
    *,
    entry_price: float,
    ltp: float,
    entry_at: datetime,
    now: datetime,
    scale_out_percent: float,
    hard_stop_percent: float,
    blast_failed_minutes: int,
    force_exit_time: str,
    already_scaled_out: bool,
) -> dict[str, Any] | None:
    """Priority: forced time-exit > hard stop (protect capital) > scale-out
    (lock profit) > blast-failed time-stop (cut a dead trade). Returns None if
    no exit condition is met yet.
    """
    if entry_price <= 0:
        return None
    change_percent = (ltp - entry_price) / entry_price * 100

    if in_time_window(now.time(), force_exit_time, "23:59"):
        return {"reason": "FORCED", "changePercent": round(change_percent, 2)}

    if change_percent <= hard_stop_percent:
        return {"reason": "HARD_STOP", "changePercent": round(change_percent, 2)}

    if not already_scaled_out and change_percent >= scale_out_percent:
        return {"reason": "SCALE_OUT", "changePercent": round(change_percent, 2)}

    minutes_open = (now - entry_at).total_seconds() / 60
    if minutes_open >= blast_failed_minutes and change_percent < scale_out_percent / 3:
        return {"reason": "BLAST_FAILED", "changePercent": round(change_percent, 2)}

    return None


def calculate_quantity(
    *,
    capital_base: float,
    risk_percent: float,
    premium: float,
    lot_size: int,
    max_lots: int,
) -> int:
    if premium <= 0 or lot_size <= 0:
        return 0
    risk_amount = capital_base * risk_percent / 100
    affordable_lots = int(risk_amount / (premium * lot_size))
    lots = max(0, min(affordable_lots, max_lots))
    return lots * lot_size
