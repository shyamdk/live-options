from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.db import sqlite as db
from app.services import varaha_fly
from app.services.app_auth import require_auth
from app.services.varaha import (
    VALID_OVERRIDES,
    get_latest,
    get_override,
    get_runtime_config,
    run_recommendation,
    set_override,
    update_runtime_config,
)

router = APIRouter(prefix="/varaha", tags=["varaha"])


class ConfigIn(BaseModel):
    lots: int | None = Field(default=None, ge=1, le=50)
    maxLossInr: float | None = Field(default=None, gt=0)


class OverrideIn(BaseModel):
    value: str


@router.get("/latest", dependencies=[Depends(require_auth)])
async def latest() -> dict[str, Any]:
    return {"recommendation": get_latest(), "override": get_override(), "config": get_runtime_config()}


@router.post("/run", dependencies=[Depends(require_auth)])
async def run() -> dict[str, Any]:
    return {"recommendation": await run_recommendation("manual"), "override": get_override()}


@router.put("/override", dependencies=[Depends(require_auth)])
async def override(body: OverrideIn) -> dict[str, Any]:
    if body.value not in VALID_OVERRIDES:
        raise HTTPException(status_code=422, detail=f"value must be one of {', '.join(VALID_OVERRIDES)}")
    return {"recommendation": await set_override(body.value), "override": get_override()}


@router.get("/config", dependencies=[Depends(require_auth)])
async def config() -> dict[str, Any]:
    return get_runtime_config()


@router.put("/config", dependencies=[Depends(require_auth)])
async def update_config(body: ConfigIn) -> dict[str, Any]:
    return update_runtime_config(lots=body.lots, max_loss_inr=body.maxLossInr)


@router.get("/history", dependencies=[Depends(require_auth)])
async def history(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    rows = db.list_varaha_daily_history(limit)
    items = []
    for row in rows:
        result = row["result"]
        top = (result.get("candidates") or [None])[0]
        items.append({
            "id": row["id"],
            "sessionDate": row["sessionDate"],
            "trigger": row["trigger"],
            "createdAt": row["createdAt"],
            "status": result.get("status"),
            "spot": result.get("spot"),
            "moveClass": (result.get("move") or {}).get("classification"),
            "moveScore": (result.get("move") or {}).get("moveScore"),
            "engineDirection": (result.get("direction") or {}).get("classification"),
            "manualOverride": (result.get("direction") or {}).get("manualOverride"),
            "topCandidate": {
                "structureLabel": top["structureLabel"], "variantLabel": top["variantLabel"], "expiry": top["expiry"],
                "maxProfit": top["maxProfit"], "maxLoss": top["maxLoss"],
            } if top else None,
            "rankingSource": result.get("rankingSource"),
        })
    return {"items": items}


@router.get("/full-butterfly", dependencies=[Depends(require_auth)])
async def full_butterfly(
    expiry: str | None = None,
    symmetric: bool = False,
    longPlacement: str = Query(default="any", pattern="^(any|adjacent|atm)$"),
    centered: bool = True,
    minShortEm: float | None = Query(default=1.0, ge=0),
    maxShortEm: float | None = Query(default=None, gt=0),
    maxWidth: float | None = Query(default=None, gt=0),
    maxWidthEm: float | None = Query(default=None, gt=0),
    maxLossInr: float | None = Query(default=None, gt=0),
    minRr: float | None = Query(default=None, ge=0),
    minMaxProfitInr: float | None = Query(default=None, ge=0),
    minPop: float | None = Query(default=None, ge=0, le=100),
    wingRatioMin: float = Query(default=0.5, ge=0.5, le=1.0),
    wingRatioMax: float = Query(default=1.0, ge=0.5, le=1.0),
    requireLiquid: bool = True,
    frontierOnly: bool = True,
    sort: str = Query(default="width", pattern="^(width|rr|pop|maxLoss|maxProfit)$"),
) -> dict[str, Any]:
    try:
        return await varaha_fly.scan(
            expiry=expiry, symmetric=symmetric, long_placement=longPlacement, centered=centered,
            min_short_em=minShortEm, max_short_em=maxShortEm, max_width=maxWidth,
            max_width_em=maxWidthEm, max_loss_inr=maxLossInr, min_rr=minRr, min_max_profit_inr=minMaxProfitInr,
            min_pop=minPop, wing_ratio_min=wingRatioMin, wing_ratio_max=wingRatioMax, require_liquid=requireLiquid,
            frontier_only=frontierOnly, sort=sort,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Full Butterfly scan failed: {exc}") from exc
