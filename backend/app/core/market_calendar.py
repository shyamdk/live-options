"""NSE trading-day arithmetic for positional strategies.

The holiday list comes from Settings.nse_holidays (env override NSE_HOLIDAYS).
A stale list only shifts trading-day counts by one, but for rules like
"exit when exactly N trading days remain" that is a real slippage — keep the
list synced with the NSE holiday circular.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

from app.core.config import Settings


@lru_cache(maxsize=8)
def _holiday_set(raw: str) -> frozenset[date]:
    holidays: set[date] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            holidays.add(date.fromisoformat(token))
        except ValueError:
            continue
    return frozenset(holidays)


def holidays_from_settings(settings: Settings) -> frozenset[date]:
    return _holiday_set(settings.nse_holidays)


def is_trading_day(day: date, holidays: frozenset[date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def next_trading_day(day: date, holidays: frozenset[date]) -> date:
    candidate = day + timedelta(days=1)
    while not is_trading_day(candidate, holidays):
        candidate += timedelta(days=1)
    return candidate


def trading_days_after(day: date, until: date, holidays: frozenset[date]) -> int:
    """Trading days strictly after `day` up to and including `until`.

    Matches the decoded exit rule: on the correct exit day, exactly N trading
    days remain after it (the exit day itself is not counted).
    """
    if until <= day:
        return 0
    count = 0
    candidate = day + timedelta(days=1)
    while candidate <= until:
        if is_trading_day(candidate, holidays):
            count += 1
        candidate += timedelta(days=1)
    return count


def planned_exit_date(expiry: date, remaining_after_exit: int, holidays: frozenset[date]) -> date | None:
    """First trading day on which `trading_days_after(day, expiry)` <= target."""
    candidate = expiry
    # Walk backwards to the first day that leaves at most `remaining_after_exit`
    # trading days after it, then forward to a trading day if needed.
    for _ in range(120):
        candidate -= timedelta(days=1)
        if not is_trading_day(candidate, holidays):
            continue
        if trading_days_after(candidate, expiry, holidays) >= remaining_after_exit:
            return candidate
    return None
