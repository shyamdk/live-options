from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from app.db import sqlite as db
from app.services import turtle
from app.services.app_auth import require_auth

router = APIRouter(prefix="/define-turtle", tags=["define-turtle"])


@router.get("/state", dependencies=[Depends(require_auth)])
async def state() -> dict[str, Any]:
    return await turtle.state()


@router.get("/config", dependencies=[Depends(require_auth)])
async def config() -> dict[str, Any]:
    return turtle.get_config()


@router.put("/config", dependencies=[Depends(require_auth)])
async def update_config(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return turtle.update_config(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades() -> dict[str, Any]:
    return {"trades": turtle.list_trades()}


@router.post("/enter", dependencies=[Depends(require_auth)])
async def enter_now() -> dict[str, Any]:
    return await turtle.enter("manual")


@router.post("/trades/{trade_id}/close", dependencies=[Depends(require_auth)])
async def close(trade_id: int) -> dict[str, Any]:
    return await turtle.close_now(trade_id)


@router.get("/alarms", dependencies=[Depends(require_auth)])
async def alarms() -> dict[str, Any]:
    return {"alarms": db.list_turtle_alarms()}


@router.post("/alarms/{alarm_id}/ack", dependencies=[Depends(require_auth)])
async def acknowledge(alarm_id: int) -> dict[str, Any]:
    if not db.acknowledge_turtle_alarm(alarm_id):
        raise HTTPException(status_code=404, detail="Alarm not found or already acknowledged.")
    return {"status": "acknowledged"}
