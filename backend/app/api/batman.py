from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path

from app.services import batman
from app.services.app_auth import require_auth

router = APIRouter(prefix="/batman", tags=["batman"])
MODE = Path(pattern="^monthly$")  # weekly is built but switched off


@router.get("/{mode}/config", dependencies=[Depends(require_auth)])
async def config(mode: str = MODE) -> dict[str, Any]:
    return batman.get_config(mode)


@router.put("/{mode}/config", dependencies=[Depends(require_auth)])
async def update_config(mode: str = MODE, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return batman.update_config(mode, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{mode}/preview", dependencies=[Depends(require_auth)])
async def preview(mode: str = MODE) -> dict[str, Any]:
    return await batman.preview(mode)


@router.post("/{mode}/enter", dependencies=[Depends(require_auth)])
async def enter_now(mode: str = MODE) -> dict[str, Any]:
    return await batman.enter(mode, "manual")


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades() -> dict[str, Any]:
    return {"trades": batman.list_trades()}


@router.get("/trades/{trade_id}", dependencies=[Depends(require_auth)])
async def trade(trade_id: int) -> dict[str, Any]:
    return await batman.trade_detail(trade_id)


@router.post("/trades/{trade_id}/close", dependencies=[Depends(require_auth)])
async def close(trade_id: int) -> dict[str, Any]:
    return await batman.close_now(trade_id)
