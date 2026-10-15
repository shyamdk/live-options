from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from app.services import varaha_paper
from app.services.app_auth import require_auth

router = APIRouter(prefix="/varaha/paper", tags=["varaha-paper"])


@router.get("/state", dependencies=[Depends(require_auth)])
async def state() -> dict[str, Any]:
    return varaha_paper.state()


@router.put("/config", dependencies=[Depends(require_auth)])
async def update_config(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return varaha_paper.update_config(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades() -> dict[str, Any]:
    return {"trades": varaha_paper.list_trades()}


@router.get("/trades/{trade_id}", dependencies=[Depends(require_auth)])
async def trade(trade_id: int) -> dict[str, Any]:
    detail = varaha_paper.trade_detail(trade_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Trade not found.")
    return detail


@router.get("/spot-chart", dependencies=[Depends(require_auth)])
async def spot_chart(days: int = 10) -> dict[str, Any]:
    try:
        return await varaha_paper.spot_chart(days)
    except Exception as exc:
        return {"candles": [], "error": str(exc)}


@router.post("/enter", dependencies=[Depends(require_auth)])
async def enter() -> dict[str, Any]:
    return await varaha_paper.enter_now()


@router.post("/trades/{trade_id}/close", dependencies=[Depends(require_auth)])
async def close(trade_id: int) -> dict[str, Any]:
    return await varaha_paper.close_now(trade_id)
