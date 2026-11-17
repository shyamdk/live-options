from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.services import index_runway as runway
from app.services.app_auth import require_auth

router = APIRouter(prefix="/index-runway", tags=["index-runway"])


@router.get("/state", dependencies=[Depends(require_auth)])
async def state() -> dict[str, Any]:
    return await runway.state()


@router.get("/config", dependencies=[Depends(require_auth)])
async def config() -> dict[str, Any]:
    return runway.get_config()


@router.put("/config", dependencies=[Depends(require_auth)])
async def update_config(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return runway.update_config(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades() -> dict[str, Any]:
    return {"trades": runway.list_trades()}


@router.post("/trades/{trade_id}/close", dependencies=[Depends(require_auth)])
async def close(trade_id: int) -> dict[str, Any]:
    return await runway.close_now(trade_id)


@router.get("/signals", dependencies=[Depends(require_auth)])
async def signals(day: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")) -> dict[str, Any]:
    return {"signals": runway.list_signals(day)}
