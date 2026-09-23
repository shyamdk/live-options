"""DTE-aware expiry resolver for PE-CE Crossover (spec Section 3).

Distinct from ema5_instruments.py's resolve_next_expiry, which *always*
skips to the expiry after nearest -- that was built for premium-buying
strategies (ema5, animesh) that specifically avoid the nearest expiry's
sharper theta/gamma at all times. This resolver instead only skips ahead
when the nearest expiry actually IS a DTE 0/1 situation; otherwise it
trades the nearest expiry, matching the spec's literal policy.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.core.timeutil import now_ist
from app.services.dhan import DhanService

INDEX_SEGMENT = "IDX_I"
DTE_AVOID_THRESHOLD = 1  # avoid DTE 0 and DTE 1


def _parse_expiry(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


async def resolve_expiry_with_dte_policy(
    dhan: DhanService, underlying_scrip: int, *, override: str | None = None, today: date | None = None
) -> dict[str, Any] | None:
    """Returns {"expiry", "dte", "usedNext", "reason"} or None if no expiry
    data is available at all (callers must block entry on None, per spec
    Section 3 item 5 -- never silently fall back to same-day expiry).

    `override`, when given, is trusted as-is (an explicit user choice,
    logged by the caller) but its own DTE is still computed and returned
    for display.
    """
    today = today or now_ist().date()
    expiries = await dhan.expiry_list(underlying_scrip, INDEX_SEGMENT)
    if not expiries:
        return None

    if override:
        if override not in expiries:
            return None
        dte = (_parse_expiry(override) - today).days
        return {"expiry": override, "dte": dte, "usedNext": False, "reason": "user override"}

    nearest = expiries[0]
    nearest_dte = (_parse_expiry(nearest) - today).days

    if nearest_dte > DTE_AVOID_THRESHOLD:
        return {"expiry": nearest, "dte": nearest_dte, "usedNext": False, "reason": "nearest expiry, DTE > 1"}

    if len(expiries) < 2:
        # Only one expiry listed at all and it's DTE 0/1 -- nothing to skip
        # to. Spec item 5: block rather than silently trade same-day expiry.
        return None

    next_expiry = expiries[1]
    next_dte = (_parse_expiry(next_expiry) - today).days
    return {
        "expiry": next_expiry,
        "dte": next_dte,
        "usedNext": True,
        "reason": f"nearest expiry is DTE {nearest_dte} -- rolled to next expiry to avoid near-expiry theta/gamma",
    }
