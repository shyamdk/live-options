from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.services.app_auth import require_auth
from app.services.theta import (
    approve_theta_signal,
    get_runtime_config,
    get_session_detail,
    get_state,
    list_past_sessions,
    reject_theta_signal,
    set_max_concurrent_margin,
    set_max_daily_loss,
)

router = APIRouter(prefix="/theta", tags=["theta"])


class ThetaConfigIn(BaseModel):
    maxConcurrentMargin: float | None = None
    maxDailyLoss: float | None = None


@router.get("/state", dependencies=[Depends(require_auth)])
async def state() -> dict[str, Any]:
    return await get_state()


@router.get("/config", dependencies=[Depends(require_auth)])
async def config() -> dict[str, Any]:
    return get_runtime_config()


@router.put("/config", dependencies=[Depends(require_auth)])
async def update_config(body: ThetaConfigIn) -> dict[str, Any]:
    try:
        if body.maxConcurrentMargin is not None:
            set_max_concurrent_margin(body.maxConcurrentMargin)
        if body.maxDailyLoss is not None:
            set_max_daily_loss(body.maxDailyLoss)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return get_runtime_config()


@router.post("/signals/{signal_id}/approve", dependencies=[Depends(require_auth)])
async def approve_signal(signal_id: int) -> dict[str, Any]:
    return await approve_theta_signal(signal_id)


@router.post("/signals/{signal_id}/reject", dependencies=[Depends(require_auth)])
async def reject_signal(signal_id: int) -> dict[str, Any]:
    return await reject_theta_signal(signal_id)


@router.get("/sessions", dependencies=[Depends(require_auth)])
async def sessions() -> dict[str, Any]:
    return {"sessions": list_past_sessions()}


@router.get("/sessions/{session_id}", dependencies=[Depends(require_auth)])
async def session_detail(session_id: str) -> dict[str, Any]:
    detail = get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Session not found.")
    return detail
