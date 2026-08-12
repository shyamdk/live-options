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
from app.core.timeutil import in_time_window, now_ist, now_ist_epoch
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
    epoch = now_ist_epoch()
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


MIN_ROC_OBSERVATIONS = 5
CONFIDENCE_THRESHOLDS = (1.0, 2.0, 3.0)  # |z| boundaries for low/medium/high/extreme


def enrich_with_roc_and_confidence(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adds, per point, the per-minute rate of change of ceOiChange/peOiChange
    and a confidence label scoring how unusual that pace is against today's
    own expanding distribution so far (mean/stdev of every rate-of-change
    observation from session start up to and including this point). Pure
    function over the already-stored snapshot list -- no I/O, nothing
    persisted; cheap enough (~130 points/day at the default poll interval)
    to recompute on every read.
    """
    ce_rocs: list[float] = []
    pe_rocs: list[float] = []
    enriched: list[dict[str, Any]] = []
    prev: dict[str, Any] | None = None

    for point in points:
        out = dict(point)
        ce_roc = pe_roc = None
        if prev is not None:
            minutes = (point["time"] - prev["time"]) / 60.0
            if minutes > 0:
                ce_roc = _roc(prev.get("ceOiChange"), point.get("ceOiChange"), minutes)
                pe_roc = _roc(prev.get("peOiChange"), point.get("peOiChange"), minutes)
        if ce_roc is not None:
            ce_rocs.append(ce_roc)
        if pe_roc is not None:
            pe_rocs.append(pe_roc)

        ce_score = _score(ce_rocs, ce_roc)
        pe_score = _score(pe_rocs, pe_roc)

        out["ceRoc"] = round(ce_roc, 2) if ce_roc is not None else None
        out["peRoc"] = round(pe_roc, 2) if pe_roc is not None else None
        out["ceZScore"] = ce_score["zScore"]
        out["peZScore"] = pe_score["zScore"]
        out["ceConfidence"] = ce_score["confidence"]
        out["peConfidence"] = pe_score["confidence"]
        out["ceRocBandUpper"] = ce_score["upper"]
        out["ceRocBandLower"] = ce_score["lower"]
        out["peRocBandUpper"] = pe_score["upper"]
        out["peRocBandLower"] = pe_score["lower"]
        enriched.append(out)
        prev = point

    return enriched


def _roc(prev_value: Any, current_value: Any, minutes: float) -> float | None:
    if prev_value is None or current_value is None:
        return None
    return (float(current_value) - float(prev_value)) / minutes


def _score(history: list[float], current: float | None) -> dict[str, Any]:
    empty = {"zScore": None, "confidence": None, "upper": None, "lower": None}
    if current is None or len(history) < MIN_ROC_OBSERVATIONS:
        return empty
    mean = sum(history) / len(history)
    variance = sum((v - mean) ** 2 for v in history) / len(history)
    stdev = variance**0.5
    upper = round(mean + stdev, 2)
    lower = round(mean - stdev, 2)
    if stdev == 0:
        return {"zScore": 0.0, "confidence": "low", "upper": upper, "lower": lower}
    z = (current - mean) / stdev
    az = abs(z)
    low, medium, high = CONFIDENCE_THRESHOLDS
    if az < low:
        label = "low"
    elif az < medium:
        label = "medium"
    elif az < high:
        label = "high"
    else:
        label = "extreme"
    return {"zScore": round(z, 2), "confidence": label, "upper": upper, "lower": lower}
