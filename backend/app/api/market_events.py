from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from app.db import sqlite as db
from app.services import market_events
from app.services.app_auth import require_auth

router = APIRouter(prefix="/market-events", tags=["market-events"])


@router.get("", dependencies=[Depends(require_auth)])
async def upcoming() -> dict[str, Any]:
    return {"events": market_events.upcoming(), "refreshedAt": db.get_kite_setting("events.refreshedAt")}


@router.post("", dependencies=[Depends(require_auth)])
async def add(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        market_events.add(str(body.get("day") or ""), str(body.get("name") or ""), str(body.get("kind") or "other"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"events": market_events.upcoming()}


@router.delete("/{event_id}", dependencies=[Depends(require_auth)])
async def delete(event_id: int) -> dict[str, Any]:
    db.delete_market_event(event_id)
    return {"events": market_events.upcoming()}


@router.post("/refresh", dependencies=[Depends(require_auth)])
async def refresh() -> dict[str, Any]:
    result = await market_events.refresh()
    return {**result, "events": market_events.upcoming()}
