from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.services.app_auth import require_auth
from app.services.gamma_blast import (
    approve_gamma_blast_signal,
    get_session_detail,
    get_state,
    list_past_sessions,
)

router = APIRouter(prefix="/gamma-blast", tags=["gamma-blast"])


@router.get("/state", dependencies=[Depends(require_auth)])
async def state() -> dict[str, Any]:
    return get_state()


@router.post("/signals/{signal_id}/approve", dependencies=[Depends(require_auth)])
async def approve_signal(signal_id: int) -> dict[str, Any]:
    return await approve_gamma_blast_signal(signal_id)


@router.get("/sessions", dependencies=[Depends(require_auth)])
async def sessions() -> dict[str, Any]:
    return {"sessions": list_past_sessions()}


@router.get("/sessions/{session_id}", dependencies=[Depends(require_auth)])
async def session_detail(session_id: str) -> dict[str, Any]:
    detail = get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Session not found.")
    return detail
