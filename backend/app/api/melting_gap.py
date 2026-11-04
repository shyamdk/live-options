from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path

from app.services import melting_gap as melting
from app.services.app_auth import require_auth

router = APIRouter(prefix="/melting-gap", tags=["melting-gap"])


@router.get("/state", dependencies=[Depends(require_auth)])
async def state() -> dict[str, Any]:
    return await melting.state()


@router.get("/config", dependencies=[Depends(require_auth)])
async def config() -> dict[str, Any]:
    return melting.get_config()


@router.put("/config", dependencies=[Depends(require_auth)])
async def update_config(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return melting.update_config(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades() -> dict[str, Any]:
    return {"trades": melting.list_trades()}


@router.get("/trades/{trade_id}", dependencies=[Depends(require_auth)])
async def trade(trade_id: int) -> dict[str, Any]:
    detail = melting.trade_detail(trade_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Trade not found.")
    return detail


@router.post("/trades/{trade_id}/close", dependencies=[Depends(require_auth)])
async def close(trade_id: int) -> dict[str, Any]:
    return await melting.close_now(trade_id)


@router.post("/square-off", dependencies=[Depends(require_auth)])
async def square_off() -> dict[str, Any]:
    return await melting.square_off_all()


@router.post("/enter/{tag}", dependencies=[Depends(require_auth)])
async def enter(tag: str = Path(pattern="^(LOWER|ATM|HIGHER)$")) -> dict[str, Any]:
    return await melting.enter_now(tag)


@router.get("/days", dependencies=[Depends(require_auth)])
async def days() -> dict[str, Any]:
    return {"days": melting.days_summary()}
