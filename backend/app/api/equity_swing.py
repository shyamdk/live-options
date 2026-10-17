from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

import asyncio

from app.services import equity_swing, equity_swing_retro
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


@router.get("/retros", dependencies=[Depends(require_auth)])
async def retros() -> dict[str, Any]:
    return {"running": equity_swing_retro.running(), "retros": equity_swing_retro.list_retros()}


@router.post("/retros", dependencies=[Depends(require_auth)])
async def start_retro() -> dict[str, Any]:
    """Starts a retrospective in the background (a minute or two); poll /retros."""
    if equity_swing_retro.running():
        return {"status": "running", "since": equity_swing_retro.running()}
    asyncio.create_task(equity_swing_retro.run_retro("manual"))
    return {"status": "started"}


@router.post("/retros/{retro_id}/apply", dependencies=[Depends(require_auth)])
async def apply_retro(retro_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return equity_swing_retro.apply(retro_id, str(body.get("label") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
