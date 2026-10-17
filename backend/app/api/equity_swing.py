from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from app.services import equity_swing
from app.services.app_auth import require_auth

router = APIRouter(prefix="/equity-swing", tags=["equity-swing"])


@router.get("/state", dependencies=[Depends(require_auth)])
async def state() -> dict[str, Any]:
    return equity_swing.state()


@router.put("/config", dependencies=[Depends(require_auth)])
async def update_config(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return equity_swing.update_config(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sync", dependencies=[Depends(require_auth)])
async def sync() -> dict[str, Any]:
    return await equity_swing.sync_bars()


@router.post("/rebalance", dependencies=[Depends(require_auth)])
async def rebalance_now() -> dict[str, Any]:
    """Rank and plan now; the plan executes at the next session's open (or, in
    market hours, on the next poll at the live price)."""
    try:
        return await equity_swing.rebalance("manual")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
