from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.db import sqlite as db
from app.services.app_auth import require_auth
from app.services.simple_crossover import (
    get_data,
    get_runtime_config,
    list_trades_with_charges,
    set_day_direction_filter_enabled,
    set_stop_loss_percent,
    set_timeframe_minutes,
    set_trade_on_sideways_enabled,
)

router = APIRouter(prefix="/simple-crossover", tags=["simple-crossover"])


class CommentIn(BaseModel):
    comment: str


class ConfigIn(BaseModel):
    dayDirectionFilterEnabled: bool | None = None
    tradeOnSideways: bool | None = None
    stopLossPercent: float | None = Field(default=None, gt=0, lt=100)
    timeframeMinutes: int | None = Field(default=None, ge=1, le=3)


@router.get("/config", dependencies=[Depends(require_auth)])
async def config() -> dict[str, Any]:
    return get_runtime_config()


@router.put("/config", dependencies=[Depends(require_auth)])
async def update_config(body: ConfigIn) -> dict[str, Any]:
    if body.dayDirectionFilterEnabled is not None:
        set_day_direction_filter_enabled(body.dayDirectionFilterEnabled)
    if body.tradeOnSideways is not None:
        set_trade_on_sideways_enabled(body.tradeOnSideways)
    if body.stopLossPercent is not None:
        set_stop_loss_percent(body.stopLossPercent)
    if body.timeframeMinutes is not None:
        try:
            set_timeframe_minutes(body.timeframeMinutes)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return get_runtime_config()


@router.get("/data", dependencies=[Depends(require_auth)])
async def data(side: str = Query(default="CE")) -> dict[str, Any]:
    if side not in ("CE", "PE"):
        return {"error": f"Unsupported side {side!r}", "candles": []}
    return await get_data(side)  # type: ignore[arg-type]


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades() -> dict[str, Any]:
    return {"trades": list_trades_with_charges()}


@router.put("/trades/{trade_id}/comment", dependencies=[Depends(require_auth)])
async def update_comment(trade_id: int, body: CommentIn) -> dict[str, Any]:
    trade = db.update_simple_crossover_trade_comment(trade_id, body.comment)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return next((item for item in list_trades_with_charges() if item["id"] == trade_id), trade)
