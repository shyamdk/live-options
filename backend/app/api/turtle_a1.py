from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from app.services import turtle_a1 as turtle
from app.services.app_auth import require_auth

router = APIRouter(prefix="/define-turtle-a1", tags=["define-turtle-a1"])


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


@router.get("/broker-book", dependencies=[Depends(require_auth)])
async def broker_book() -> dict[str, Any]:
    return await turtle.broker_book()


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
    return {"alarms": turtle.db.list_turtle_alarms()}


@router.post("/alarms/{alarm_id}/ack", dependencies=[Depends(require_auth)])
async def acknowledge(alarm_id: int) -> dict[str, Any]:
    if not turtle.db.acknowledge_turtle_alarm(alarm_id):
        raise HTTPException(status_code=404, detail="Alarm not found or already acknowledged.")
    return {"status": "acknowledged"}
