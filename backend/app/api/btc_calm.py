from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from app.services import btc_calm
from app.services.app_auth import require_auth

router = APIRouter(prefix="/btc-calm", tags=["btc-calm"])


@router.get("/state", dependencies=[Depends(require_auth)])
async def state() -> dict[str, Any]:
    return await btc_calm.state()


@router.put("/config", dependencies=[Depends(require_auth)])
async def update_config(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return btc_calm.update_config(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades() -> dict[str, Any]:
    return {"trades": btc_calm.list_trades()}


@router.get("/trades/{trade_id}", dependencies=[Depends(require_auth)])
async def trade(trade_id: int) -> dict[str, Any]:
    detail = btc_calm.trade_detail(trade_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Trade not found.")
    return detail


@router.post("/enter", dependencies=[Depends(require_auth)])
async def enter() -> dict[str, Any]:
    return await btc_calm.enter_now()


@router.post("/trades/{trade_id}/close", dependencies=[Depends(require_auth)])
async def close(trade_id: int) -> dict[str, Any]:
    return await btc_calm.close_now(trade_id)
