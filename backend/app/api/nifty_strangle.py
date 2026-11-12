from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.services import nifty_strangle
from app.services.app_auth import require_auth

router = APIRouter(prefix="/nifty-strangle", tags=["nifty-strangle"])
BOOK = Query("plain", pattern="^(plain|hedged)$")


@router.get("/config", dependencies=[Depends(require_auth)])
async def config(book: str = BOOK) -> dict[str, Any]:
    return nifty_strangle.get_config(book)


@router.put("/config", dependencies=[Depends(require_auth)])
async def update_config(body: dict[str, Any] = Body(...), book: str = BOOK) -> dict[str, Any]:
    try:
        return nifty_strangle.update_config(body, book)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/plan", dependencies=[Depends(require_auth)])
async def plan(book: str = BOOK) -> dict[str, Any]:
    try:
        return await nifty_strangle.plan(book=book)
    except Exception as exc:
        return {"config": nifty_strangle.get_config(book), "error": f"Dhan data unavailable: {exc}"}


@router.post("/enter", dependencies=[Depends(require_auth)])
async def enter(book: str = BOOK) -> dict[str, Any]:
    return await nifty_strangle.enter("manual", force=True, book=book)


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades(book: str = BOOK) -> dict[str, Any]:
    return {"trades": nifty_strangle.list_trades(book)}


@router.post("/legs/{leg_id}/close", dependencies=[Depends(require_auth)])
async def close_leg(leg_id: int) -> dict[str, Any]:
    return await nifty_strangle.close_leg_now(leg_id)


@router.get("/spot-chart", dependencies=[Depends(require_auth)])
async def spot_chart() -> dict[str, Any]:
    try:
        return await nifty_strangle.spot_chart()
    except Exception as exc:
        return {"candles": [], "error": str(exc)}
