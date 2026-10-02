from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import btc_strangle
from app.services.app_auth import require_auth

router = APIRouter(prefix="/btc-strangle", tags=["btc-strangle"])


class ConfigIn(BaseModel):
    enabled: bool | None = None
    mode: str | None = Field(default=None, pattern="^(paper|live)$")
    multiplier: float | None = Field(default=None, ge=0.5, le=5)
    stopLossPercent: float | None = Field(default=None, gt=0, le=1000)
    contracts: int | None = Field(default=None, ge=1, le=50000)
    entryTime: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    entryWindowEnd: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    expiryOffset: int | None = Field(default=None, ge=1, le=3)
    expiryExitTime: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    buybackThreshold: float | None = Field(default=None, ge=0)
    minAvailableBalance: float | None = Field(default=None, ge=0)
    useFarthestStrike: bool | None = None


@router.get("/config", dependencies=[Depends(require_auth)])
async def config() -> dict[str, Any]:
    return btc_strangle.get_runtime_config()


@router.put("/config", dependencies=[Depends(require_auth)])
async def update_config(body: ConfigIn) -> dict[str, Any]:
    try:
        return btc_strangle.update_runtime_config(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/preview", dependencies=[Depends(require_auth)])
async def preview() -> dict[str, Any]:
    return await btc_strangle.preview()


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades() -> dict[str, Any]:
    return {"trades": btc_strangle.list_trades()}


@router.post("/enter", dependencies=[Depends(require_auth)])
async def enter_now() -> dict[str, Any]:
    return await btc_strangle.enter_trade("manual")


@router.post("/legs/{leg_id}/close", dependencies=[Depends(require_auth)])
async def close_leg(leg_id: int) -> dict[str, Any]:
    return await btc_strangle.close_leg_now(leg_id)


@router.get("/trades/{trade_id}/chart", dependencies=[Depends(require_auth)])
async def chart(trade_id: int, resolution: str = Query(default="5m", pattern="^(1m|3m|5m|15m)$")) -> dict[str, Any]:
    return await btc_strangle.chart(trade_id, resolution)


@router.get("/spot-chart", dependencies=[Depends(require_auth)])
async def spot_chart(resolution: str = Query(default="5m", pattern="^(1m|5m|15m|1h)$")) -> dict[str, Any]:
    return await btc_strangle.spot_chart(resolution)
