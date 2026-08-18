from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.db import sqlite as db
from app.services.app_auth import require_auth

router = APIRouter(prefix="/paper-trading", tags=["paper-trading"])


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades() -> dict[str, Any]:
    return {"trades": db.list_paper_trades()}


@router.get("/settings", dependencies=[Depends(require_auth)])
async def settings() -> dict[str, Any]:
    return db.get_paper_trading_settings()


class SettingsIn(BaseModel):
    stopLossPercent: float | None = None
    target1Percent: float | None = None
    target2Percent: float | None = None
    trailPercent: float | None = None
    niftyLots: float | None = None
    niftyLotSize: float | None = None
    sensexLots: float | None = None
    sensexLotSize: float | None = None


@router.put("/settings", dependencies=[Depends(require_auth)])
async def update_settings(payload: SettingsIn) -> dict[str, Any]:
    values = {key: value for key, value in payload.model_dump().items() if value is not None}
    return db.save_paper_trading_settings(values)
