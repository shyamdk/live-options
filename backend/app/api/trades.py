from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.services.app_auth import require_auth
from app.services.trades import (
    approve_risk_exit,
    close_trade,
    exit_tag_now,
    live_trade_snapshot,
    process_risk_order_check,
    save_tag_levels,
    save_trade_levels,
)


router = APIRouter(prefix="/trades", tags=["trades"])


class TradeLevelsIn(BaseModel):
    stopLoss: float | None = None
    target: float | None = None
    notes: str | None = None
    tag: str | None = None


class TagLevelsIn(BaseModel):
    target: float | None = None
    stopLoss: float | None = None


class CloseTradeIn(BaseModel):
    quantity: int | None = None


@router.get("/live", dependencies=[Depends(require_auth)])
async def live_trades() -> dict[str, Any]:
    return await live_trade_snapshot()


@router.post("/risk/check", dependencies=[Depends(require_auth)])
async def risk_check() -> dict[str, Any]:
    return await process_risk_order_check()


@router.put("/tags/{tag}/levels", dependencies=[Depends(require_auth)])
async def update_tag_levels(tag: str, payload: TagLevelsIn) -> dict[str, Any]:
    try:
        return {"levels": await save_tag_levels(tag, payload.target, payload.stopLoss)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/tags/{tag}/exit", dependencies=[Depends(require_auth)])
async def exit_tag(tag: str) -> dict[str, Any]:
    return await exit_tag_now(tag)


@router.put("/{trade_id}/levels", dependencies=[Depends(require_auth)])
async def update_levels(trade_id: str, payload: TradeLevelsIn) -> dict[str, Any]:
    return {"tradeId": trade_id, "levels": await save_trade_levels(trade_id, payload.model_dump())}


@router.post("/{trade_id}/close", dependencies=[Depends(require_auth)])
async def close(trade_id: str, payload: CloseTradeIn) -> dict[str, Any]:
    return await close_trade(trade_id, payload.quantity)


@router.post("/{trade_id}/risk/approve", dependencies=[Depends(require_auth)])
async def approve_risk(trade_id: str) -> dict[str, Any]:
    return await approve_risk_exit(trade_id)
