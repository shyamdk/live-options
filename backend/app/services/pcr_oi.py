"""Tracks NIFTY/SENSEX Put-Call Ratio and change-in-OI as a continuous
intraday time series for Manage Trades' PCR/OI panel. Purely observational
— no signals, no approval flow, unlike the trading strategies in this
codebase.

DhanService.option_chain() returns both `oi` (current) and `previous_oi`
(previous session's close) per strike per side, so both PCR and "change in
OI" (matching the standard Sensibull/Opstra "Chg in OI" convention) are
computable from a single chain fetch each poll — no separate baseline needs
to be stored.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any

from app.core.config import Settings, get_settings
from app.core.timeutil import in_time_window, now_ist
from app.db.sqlite import record_pcr_oi_snapshot
from app.services.dhan import DhanService

UNDERLYINGS = ("NIFTY", "SENSEX")
INDEX_SEGMENT = "IDX_I"

_expiries: dict[str, str | None] = {}
_expiry_date: date | None = None


def start_pcr_oi_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.pcr_oi_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_pcr_oi_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def _loop() -> None:
    settings = get_settings()
    interval = max(settings.pcr_oi_poll_interval_seconds, 30)
    while True:
        try:
            now = now_ist()
            in_hours = in_time_window(now.time(), settings.pcr_oi_session_start_time, settings.pcr_oi_session_end_time)
            if in_hours and now.weekday() < 5:
                await _poll_once(settings, now)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(interval)


def _security_id(settings: Settings, underlying: str) -> int:
    return settings.dhan_nifty_security_id if underlying == "NIFTY" else settings.dhan_sensex_security_id


async def _resolve_expiries(dhan: DhanService, settings: Settings, today: date) -> dict[str, str | None]:
    global _expiries, _expiry_date
    if _expiry_date == today and _expiries:
        return _expiries
    resolved: dict[str, str | None] = {}
    for underlying in UNDERLYINGS:
        try:
            expiry_list = await dhan.expiry_list(_security_id(settings, underlying), INDEX_SEGMENT)
            resolved[underlying] = expiry_list[0] if expiry_list else None
        except Exception:
            resolved[underlying] = None
    _expiries = resolved
    _expiry_date = today
    return resolved


async def _poll_once(settings: Settings, now: datetime) -> None:
    dhan = DhanService(settings)
    session_date = now.date().isoformat()
    epoch = int(now.timestamp())
    expiries = await _resolve_expiries(dhan, settings, now.date())

    for underlying in UNDERLYINGS:
        expiry = expiries.get(underlying)
        if not expiry:
            continue
        try:
            chain = await dhan.option_chain(_security_id(settings, underlying), INDEX_SEGMENT, expiry)
            snapshot = _summarize_chain(chain)
        except Exception:
            continue
        record_pcr_oi_snapshot(
            session_date=session_date,
            underlying=underlying,
            epoch=epoch,
            spot=snapshot["spot"],
            pcr=snapshot["pcr"],
            ce_oi=snapshot["ce_oi"],
            pe_oi=snapshot["pe_oi"],
            ce_oi_change=snapshot["ce_oi_change"],
            pe_oi_change=snapshot["pe_oi_change"],
        )


def _summarize_chain(chain: dict[str, Any]) -> dict[str, Any]:
    oc = chain.get("oc") or {}
    ce_oi = pe_oi = ce_prev_oi = pe_prev_oi = 0
    for strike_data in oc.values():
        ce = (strike_data or {}).get("ce") or {}
        pe = (strike_data or {}).get("pe") or {}
        ce_oi += int(ce.get("oi") or 0)
        pe_oi += int(pe.get("oi") or 0)
        ce_prev_oi += int(ce.get("previous_oi") or 0)
        pe_prev_oi += int(pe.get("previous_oi") or 0)

    pcr = (pe_oi / ce_oi) if ce_oi else None
    return {
        "spot": _number(chain.get("last_price")),
        "pcr": round(pcr, 4) if pcr is not None else None,
        "ce_oi": ce_oi,
        "pe_oi": pe_oi,
        "ce_oi_change": ce_oi - ce_prev_oi,
        "pe_oi_change": pe_oi - pe_prev_oi,
    }


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
