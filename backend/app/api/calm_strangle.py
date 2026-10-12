from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from app.services import calm_strangle
from app.services.app_auth import require_auth

router = APIRouter(prefix="/calm-strangle", tags=["calm-strangle"])


@router.get("/state", dependencies=[Depends(require_auth)])
async def state() -> dict[str, Any]:
    return await calm_strangle.state()


@router.put("/config", dependencies=[Depends(require_auth)])
async def update_config(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return calm_strangle.update_config(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades() -> dict[str, Any]:
    return {"trades": calm_strangle.list_trades()}


@router.post("/enter", dependencies=[Depends(require_auth)])
async def enter() -> dict[str, Any]:
    return await calm_strangle.enter_now()


@router.post("/trades/{trade_id}/close", dependencies=[Depends(require_auth)])
async def close(trade_id: int) -> dict[str, Any]:
    return await calm_strangle.close_now(trade_id)
