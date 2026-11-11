from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from app.services import choch
from app.services.app_auth import require_auth

router = APIRouter(prefix="/choch", tags=["choch"])


@router.get("/state", dependencies=[Depends(require_auth)])
async def state() -> dict[str, Any]:
    return await choch.state()


@router.get("/candles", dependencies=[Depends(require_auth)])
async def candles() -> dict[str, Any]:
    try:
        return {"candles": await choch.candles()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Dhan data unavailable: {exc}") from exc


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades() -> dict[str, Any]:
    return {"trades": choch.list_trades()}


@router.put("/config", dependencies=[Depends(require_auth)])
async def update_config(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return choch.update_config(body)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
