"""Resolves the ATM NIFTY option (CE or PE) to trade when an ema5 signal
fires. Reuses DhanService's option-chain endpoints (same ones Gamma Blast
uses), but resolves the NEAREST upcoming expiry rather than requiring today
to BE the expiry date — ema5 trades every day, not just expiry day.
"""

from __future__ import annotations

from typing import Any

from app.services.dhan import DhanService

INDEX_SEGMENT = "IDX_I"


async def resolve_nearest_expiry(dhan: DhanService, underlying_scrip: int) -> str | None:
    expiries = await dhan.expiry_list(underlying_scrip, INDEX_SEGMENT)
    return expiries[0] if expiries else None


async def resolve_atm_option(
    dhan: DhanService, *, underlying_scrip: int, expiry: str, side: str, strike_step: float
) -> dict[str, Any] | None:
    """Returns {strike, securityId, ltp} for the ATM (nearest-strike) option
    on the given side, or None if the chain has no usable data.
    """
    chain = await dhan.option_chain(underlying_scrip, INDEX_SEGMENT, expiry)
    spot = float(chain.get("last_price") or 0)
    oc = chain.get("oc") or {}
    if not spot or not oc:
        return None
    atm_strike = round(spot / strike_step) * strike_step
    key = "ce" if side == "CE" else "pe"
    best: tuple[float, dict[str, Any]] | None = None
    best_distance: float | None = None
    for strike_key, sides in oc.items():
        try:
            strike_price = float(strike_key)
        except (TypeError, ValueError):
            continue
        payload = (sides or {}).get(key)
        if not isinstance(payload, dict) or not payload.get("security_id"):
            continue
        distance = abs(strike_price - atm_strike)
        if best_distance is None or distance < best_distance:
            best = (strike_price, payload)
            best_distance = distance
    if not best:
        return None
    strike_price, payload = best
    return {
        "strike": strike_price,
        "securityId": str(payload.get("security_id")),
        "ltp": float(payload.get("last_price") or 0),
    }
