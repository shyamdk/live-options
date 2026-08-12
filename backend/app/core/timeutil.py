"""Shared IST wall-clock helper. The OCI host's system clock is GMT (confirmed
via timedatectl), so any feature that reasons about Indian market hours or
trading dates must go through here rather than bare datetime.now().
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    """Naive datetime whose fields are IST wall-clock time, regardless of the
    host server's own system timezone. Deliberately returned as naive (tzinfo
    stripped) so it arithmetics cleanly against timestamps stored via
    isoformat() elsewhere without any aware/naive mixing.

    Do NOT call .timestamp() on this value -- a naive datetime's .timestamp()
    is interpreted using the HOST's own system timezone (GMT on OCI), not
    IST, so it silently produces an epoch off by the UTC-IST offset (5.5h).
    Use now_ist_epoch() instead whenever a true Unix epoch is needed.
    """
    return datetime.now(_IST).replace(tzinfo=None)


def now_ist_epoch() -> int:
    """True Unix epoch (UTC-based) for the current moment. Safe to compare
    directly against Dhan candle `time` fields or anything else stored as a
    real epoch -- unlike now_ist().timestamp(), which is wrong whenever the
    host's system timezone isn't IST (see now_ist()'s docstring).
    """
    return int(datetime.now(_IST).timestamp())


def today_ist() -> str:
    return now_ist().date().isoformat()


def in_time_window(now: time, start: str, end: str) -> bool:
    return _parse_time(start) <= now <= _parse_time(end)


def _parse_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))
