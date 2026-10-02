from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db import sqlite as db
from app.services.app_auth import require_auth
from app.services.simple_crossover_xaut import (
    get_data,
    get_runtime_config,
    list_trades_with_charges,
    set_day_direction_filter_enabled,
    set_entry_gap_filter_enabled,
    set_leverage,
    set_margin_per_trade,
    set_max_entry_gap,
    set_min_entry_gap,
    set_rsi_exit_filter_enabled,
    set_rsi_long_exit_threshold,
    set_rsi_short_exit_threshold,
    set_trade_on_sideways_enabled,
)

router = APIRouter(prefix="/simple-crossover-xaut", tags=["simple-crossover-xaut"])


class CommentIn(BaseModel):
    comment: str


class ConfigIn(BaseModel):
    dayDirectionFilterEnabled: bool | None = None
    tradeOnSideways: bool | None = None
    rsiExitEnabled: bool | None = None
    rsiLongExitThreshold: float | None = None
    rsiShortExitThreshold: float | None = None
    marginPerTrade: float | None = None
    leverage: float | None = None
    entryGapFilterEnabled: bool | None = None
    minEntryGap: float | None = None
    maxEntryGap: float | None = None


@router.get("/config", dependencies=[Depends(require_auth)])
async def config() -> dict[str, Any]:
    return get_runtime_config()


@router.put("/config", dependencies=[Depends(require_auth)])
async def update_config(body: ConfigIn) -> dict[str, Any]:
    if body.dayDirectionFilterEnabled is not None:
        set_day_direction_filter_enabled(body.dayDirectionFilterEnabled)
    if body.tradeOnSideways is not None:
        set_trade_on_sideways_enabled(body.tradeOnSideways)
    if body.rsiExitEnabled is not None:
        set_rsi_exit_filter_enabled(body.rsiExitEnabled)
    if body.rsiLongExitThreshold is not None:
        set_rsi_long_exit_threshold(body.rsiLongExitThreshold)
    if body.rsiShortExitThreshold is not None:
        set_rsi_short_exit_threshold(body.rsiShortExitThreshold)
    if body.marginPerTrade is not None:
        set_margin_per_trade(body.marginPerTrade)
    if body.leverage is not None:
        set_leverage(body.leverage)
    if body.entryGapFilterEnabled is not None:
        set_entry_gap_filter_enabled(body.entryGapFilterEnabled)
    if body.minEntryGap is not None:
        set_min_entry_gap(body.minEntryGap)
    if body.maxEntryGap is not None:
        set_max_entry_gap(body.maxEntryGap)
    return get_runtime_config()


@router.get("/data", dependencies=[Depends(require_auth)])
async def data() -> dict[str, Any]:
    return await get_data()


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades() -> dict[str, Any]:
    return {"trades": list_trades_with_charges()}


@router.put("/trades/{trade_id}/comment", dependencies=[Depends(require_auth)])
async def update_comment(trade_id: int, body: CommentIn) -> dict[str, Any]:
    trade = db.update_simple_crossover_xaut_trade_comment(trade_id, body.comment)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return trade
