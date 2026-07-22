from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.services.app_auth import require_auth
from app.services.credit_spread import (
    approve_credit_spread_signal,
    evaluate_now,
    get_state,
    request_manual_exit,
)

router = APIRouter(prefix="/credit-spread", tags=["credit-spread"])


@router.get("/state", dependencies=[Depends(require_auth)])
async def state() -> dict[str, Any]:
    return get_state()


@router.post("/signals/{signal_id}/approve", dependencies=[Depends(require_auth)])
async def approve_signal(signal_id: int) -> dict[str, Any]:
    return await approve_credit_spread_signal(signal_id)


@router.post("/evaluate", dependencies=[Depends(require_auth)])
async def evaluate() -> dict[str, Any]:
    return await evaluate_now()


@router.post("/exit", dependencies=[Depends(require_auth)])
async def manual_exit() -> dict[str, Any]:
    return await request_manual_exit()
