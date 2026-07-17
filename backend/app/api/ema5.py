from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.timeutil import now_ist
from app.services.app_auth import require_auth
from app.services.dhan import DhanService
from app.services.ema5 import (
    approve_ema5_signal,
    get_runtime_config,
    get_session_detail,
    get_state,
    list_past_sessions,
    set_max_trades_per_day_per_side,
)
from app.services.ema5_candles import fetch_today_candles
from app.services.ema5_engine import compute_ema, filter_completed_candles

router = APIRouter(prefix="/ema5", tags=["ema5"])


class Ema5ConfigIn(BaseModel):
    maxTradesPerDaySide: int


@router.get("/state", dependencies=[Depends(require_auth)])
async def state() -> dict[str, Any]:
    return await get_state()


@router.get("/config", dependencies=[Depends(require_auth)])
async def config() -> dict[str, Any]:
    return get_runtime_config()


@router.put("/config", dependencies=[Depends(require_auth)])
async def update_config(body: Ema5ConfigIn) -> dict[str, Any]:
    try:
        set_max_trades_per_day_per_side(body.maxTradesPerDaySide)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return get_runtime_config()


@router.get("/candles", dependencies=[Depends(require_auth)])
async def candles(side: Literal["PE", "CE"]) -> dict[str, Any]:
    settings = get_settings()
    interval = settings.ema5_pe_interval_minutes if side == "PE" else settings.ema5_ce_interval_minutes
    dhan = DhanService(settings)
    raw = await fetch_today_candles(
        dhan, str(settings.dhan_nifty_security_id), str(interval), settings.ema5_session_start_time
    )
    now = now_ist()
    completed = filter_completed_candles(raw, interval, int(now.timestamp()))
    ema = compute_ema([c.close for c in completed], period=settings.ema5_ema_period)
    return {
        "side": side,
        "intervalMinutes": interval,
        "candles": [{"time": c.time, "open": c.open, "high": c.high, "low": c.low, "close": c.close} for c in completed],
        "ema": ema,
    }


@router.post("/signals/{signal_id}/approve", dependencies=[Depends(require_auth)])
async def approve_signal(signal_id: int) -> dict[str, Any]:
    return await approve_ema5_signal(signal_id)


@router.get("/sessions", dependencies=[Depends(require_auth)])
async def sessions() -> dict[str, Any]:
    return {"sessions": list_past_sessions()}


@router.get("/sessions/{session_id}", dependencies=[Depends(require_auth)])
async def session_detail(session_id: str) -> dict[str, Any]:
    detail = get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Session not found.")
    return detail
