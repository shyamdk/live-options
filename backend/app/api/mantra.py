from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path

from app.db import sqlite as db
from app.services import mantra
from app.services.app_auth import require_auth

router = APIRouter(prefix="/mantra", tags=["mantra"])
MODE = Path(pattern="^(monthly|weekly)$")


@router.get("/{mode}/config", dependencies=[Depends(require_auth)])
async def config(mode: str = MODE) -> dict[str, Any]:
    return mantra.get_config(mode)


@router.put("/{mode}/config", dependencies=[Depends(require_auth)])
async def update_config(mode: str = MODE, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return mantra.update_config(mode, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{mode}/plan", dependencies=[Depends(require_auth)])
async def plan(mode: str = MODE) -> dict[str, Any]:
    try:
        return await mantra.plan(mode)
    except Exception as exc:
        return {"config": mantra.get_config(mode), "error": f"Dhan data unavailable: {exc}"}


@router.post("/{mode}/enter", dependencies=[Depends(require_auth)])
async def enter_now(mode: str = MODE) -> dict[str, Any]:
    return await mantra.enter(mode, "manual", check_liquidity=False)


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades() -> dict[str, Any]:
    return {"trades": mantra.list_trades(), "alarms": db.list_mantra_alarms(unacknowledged_only=True)}


@router.get("/trades/{trade_id}", dependencies=[Depends(require_auth)])
async def trade(trade_id: int) -> dict[str, Any]:
    detail = mantra.trade_detail(trade_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Trade not found.")
    return detail


@router.post("/trades/{trade_id}/close", dependencies=[Depends(require_auth)])
async def close(trade_id: int) -> dict[str, Any]:
    return await mantra.close_now(trade_id)


@router.get("/alarms", dependencies=[Depends(require_auth)])
async def alarms() -> dict[str, Any]:
    return {"alarms": db.list_mantra_alarms()}


@router.post("/alarms/{alarm_id}/ack", dependencies=[Depends(require_auth)])
async def acknowledge(alarm_id: int) -> dict[str, Any]:
    if not db.acknowledge_mantra_alarm(alarm_id):
        raise HTTPException(status_code=404, detail="Alarm not found or already acknowledged.")
    return {"status": "acknowledged"}
