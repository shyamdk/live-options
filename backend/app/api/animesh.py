from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import get_settings
from app.core.timeutil import now_ist
from app.services.animesh import approve_animesh_signal, get_session_detail, get_state, list_past_sessions
from app.services.animesh_candles import fetch_today_candles
from app.services.animesh_engine import compute_ema_band, compute_macd, filter_completed_candles
from app.services.app_auth import require_auth
from app.services.dhan import DhanService

router = APIRouter(prefix="/animesh", tags=["animesh"])


@router.get("/state", dependencies=[Depends(require_auth)])
async def state() -> dict[str, Any]:
    return await get_state()


@router.get("/candles", dependencies=[Depends(require_auth)])
async def candles(side: Literal["PE", "CE"]) -> dict[str, Any]:
    settings = get_settings()
    dhan = DhanService(settings)
    raw = await fetch_today_candles(
        dhan, str(settings.dhan_nifty_security_id), str(settings.animesh_execution_interval_minutes), settings.animesh_session_start_time
    )
    now = now_ist()
    completed = filter_completed_candles(raw, settings.animesh_execution_interval_minutes, int(now.timestamp()))
    macd_result = compute_macd(
        [c.close for c in completed], fast=settings.animesh_macd_fast, slow=settings.animesh_macd_slow, signal=settings.animesh_macd_signal
    )
    band = compute_ema_band(completed, period=settings.animesh_ema_band_period)
    return {
        "side": side,
        "intervalMinutes": settings.animesh_execution_interval_minutes,
        "candles": [{"time": c.time, "open": c.open, "high": c.high, "low": c.low, "close": c.close} for c in completed],
        "macd": macd_result["macd"],
        "signal": macd_result["signal"],
        "histogram": macd_result["histogram"],
        "bandHigh": band["high"],
        "bandLow": band["low"],
        "bandMedian": band["median"],
    }


@router.post("/signals/{signal_id}/approve", dependencies=[Depends(require_auth)])
async def approve_signal(signal_id: int) -> dict[str, Any]:
    return await approve_animesh_signal(signal_id)


@router.get("/sessions", dependencies=[Depends(require_auth)])
async def sessions() -> dict[str, Any]:
    return {"sessions": list_past_sessions()}


@router.get("/sessions/{session_id}", dependencies=[Depends(require_auth)])
async def session_detail(session_id: str) -> dict[str, Any]:
    detail = get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Session not found.")
    return detail
