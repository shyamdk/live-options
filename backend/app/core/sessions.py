"""Special NSE sessions on non-weekdays (e.g. Diwali Muhurat trading).

Real-time "is the market open" gates call `weekday_open(now)` instead of
`now.weekday() < 5`: weekdays as before, plus a listed special date -- but only
inside its window, so a strategy whose own window starts at 09:15 does not wake
up on a Sunday morning with stale prices. Trading-day arithmetic (days to
expiry, exit schedules) is unchanged: a special session is not a trading day.

Settings.special_sessions: "YYYY-MM-DD HH:MM-HH:MM[ nobrokerage], ..." (IST).
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime
from functools import lru_cache

from app.core.config import get_settings


@lru_cache(maxsize=8)
def _parse(raw: str) -> dict[date, tuple[dtime, dtime, bool]]:
    out: dict[date, tuple[dtime, dtime, bool]] = {}
    for token in raw.split(","):
        parts = token.split()
        if len(parts) < 2:
            continue
        try:
            day = date.fromisoformat(parts[0])
            start, end = (dtime.fromisoformat(x) for x in parts[1].split("-"))
        except ValueError:
            continue
        out[day] = (start, end, "nobrokerage" in parts[2:])
    return out


def special_session(day: date) -> tuple[dtime, dtime, bool] | None:
    return _parse(get_settings().special_sessions).get(day)


def weekday_open(now: datetime) -> bool:
    if now.weekday() < 5:
        return True
    window = special_session(now.date())
    return bool(window) and window[0] <= now.time() <= window[1]


def zero_brokerage_today(today: date) -> bool:
    window = special_session(today)
    return bool(window and window[2])
