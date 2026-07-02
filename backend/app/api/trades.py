from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.trades import close_trade, live_trade_snapshot, save_trade_levels


router = APIRouter(prefix="/trades", tags=["trades"])


class TradeLevelsIn(BaseModel):
    stopLoss: float | None = None
    target: float | None = None
    notes: str | None = None


class CloseTradeIn(BaseModel):
    quantity: int | None = None


@router.get("/live")
async def live_trades() -> dict[str, Any]:
    return await live_trade_snapshot()


@router.put("/{trade_id}/levels")
async def update_levels(trade_id: str, payload: TradeLevelsIn) -> dict[str, Any]:
    return {"tradeId": trade_id, "levels": await save_trade_levels(trade_id, payload.model_dump())}


@router.post("/{trade_id}/close")
async def close(trade_id: str, payload: CloseTradeIn) -> dict[str, Any]:
    return await close_trade(trade_id, payload.quantity)

