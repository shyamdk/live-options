"""Daily REST bootstrap for Gamma Blast: resolves today's expiry and the
strike/security-id list to subscribe on the WebSocket. Dhan rate-limits
/optionchain and /optionchain/expirylist to one request per 3 seconds
(enforced in DhanService._option_chain_request) — this module is meant to be
called once per session start plus an occasional reconciliation poll, never
in a tight loop.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.config import Settings
from app.services.dhan import DhanService
from app.services.gamma_blast_engine import StrikeState

INDEX_SEGMENT = "IDX_I"


async def resolve_todays_expiry(dhan: DhanService, underlying_scrip: int, today: date | None = None) -> str | None:
    today = today or date.today()
    expiries = await dhan.expiry_list(underlying_scrip, INDEX_SEGMENT)
    today_str = today.isoformat()
    return today_str if today_str in expiries else None


async def fetch_strike_states(
    dhan: DhanService,
    *,
    underlying_scrip: int,
    expiry: str,
    strike_step: float,
    strike_range: int,
) -> tuple[float, list[StrikeState]]:
    """Returns (spot_price, strikes_within_range)."""
    chain = await dhan.option_chain(underlying_scrip, INDEX_SEGMENT, expiry)
    spot = float(chain.get("last_price") or 0)
    oc = chain.get("oc") or {}
    max_distance = strike_step * strike_range
    strikes: list[StrikeState] = []
    for strike_key, sides in oc.items():
        try:
            strike_price = float(strike_key)
        except (TypeError, ValueError):
            continue
        if abs(strike_price - spot) > max_distance:
            continue
        if not isinstance(sides, dict):
            continue
        ce = sides.get("ce")
        pe = sides.get("pe")
        if isinstance(ce, dict) and ce.get("security_id"):
            strikes.append(_strike_from_payload(strike_price, "CE", ce))
        if isinstance(pe, dict) and pe.get("security_id"):
            strikes.append(_strike_from_payload(strike_price, "PE", pe))
    return spot, strikes


def _strike_from_payload(strike: float, side: str, payload: dict[str, Any]) -> StrikeState:
    return StrikeState(
        strike=strike,
        option_side=side,
        security_id=str(payload.get("security_id")),
        ltp=_number(payload.get("last_price")),
        oi=_number(payload.get("oi")),
    )


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def strike_step_for(index_symbol: str, settings: Settings) -> float:
    return settings.gamma_blast_nifty_strike_step if index_symbol == "NIFTY" else settings.gamma_blast_sensex_strike_step


def lot_size_for(index_symbol: str, settings: Settings) -> int:
    return settings.gamma_blast_nifty_lot_size if index_symbol == "NIFTY" else settings.gamma_blast_sensex_lot_size


def underlying_scrip_for(index_symbol: str, settings: Settings) -> int:
    return settings.dhan_nifty_security_id if index_symbol == "NIFTY" else settings.dhan_sensex_security_id


def expiry_weekday_for(index_symbol: str, settings: Settings) -> int:
    return (
        settings.gamma_blast_nifty_expiry_weekday
        if index_symbol == "NIFTY"
        else settings.gamma_blast_sensex_expiry_weekday
    )
