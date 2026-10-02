from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from app.services import batman
from app.services.app_auth import require_auth

router = APIRouter(prefix="/batman", tags=["batman"])
MODE = Path(pattern="^monthly$")  # weekly is built but switched off


@router.get("/analyze", dependencies=[Depends(require_auth)])
async def analyze(
    expiry: str | None = None,
    baseLots: int = Query(default=3, ge=1, le=50),
    shortRatio: int = Query(default=3, ge=1, le=10),
    outerRatio: int = Query(default=2, ge=0, le=10),
    buyOffset: float | None = Query(default=None, ge=0, le=5000),
    sellGap: float | None = Query(default=None, gt=0, le=5000),
    hedgeGap: float | None = Query(default=None, gt=0, le=5000),
    extraCallLots: int | None = Query(default=None, ge=0, le=50),
    capital: float = Query(default=1_000_000, gt=0),
    balanceMove: float | None = Query(default=None, gt=0, le=5000),
) -> dict[str, Any]:
    """Weekly tab: analysis only, never trades."""
    try:
        return await batman.analyze(
            expiry=expiry, base_lots=baseLots, short_ratio=shortRatio, outer_ratio=outerRatio, buy_offset=buyOffset,
            sell_gap=sellGap, hedge_gap=hedgeGap, extra_call_lots=extraCallLots, capital=capital, balance_move=balanceMove,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Batman analysis failed: {exc}") from exc


@router.get("/{mode}/config", dependencies=[Depends(require_auth)])
async def config(mode: str = MODE) -> dict[str, Any]:
    return batman.get_config(mode)


@router.put("/{mode}/config", dependencies=[Depends(require_auth)])
async def update_config(mode: str = MODE, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return batman.update_config(mode, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{mode}/preview", dependencies=[Depends(require_auth)])
async def preview(mode: str = MODE) -> dict[str, Any]:
    return await batman.preview(mode)


@router.post("/{mode}/enter", dependencies=[Depends(require_auth)])
async def enter_now(mode: str = MODE) -> dict[str, Any]:
    return await batman.enter(mode, "manual")


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades() -> dict[str, Any]:
    return {"trades": batman.list_trades()}


@router.get("/trades/{trade_id}", dependencies=[Depends(require_auth)])
async def trade(trade_id: int) -> dict[str, Any]:
    return await batman.trade_detail(trade_id)


@router.post("/trades/{trade_id}/close", dependencies=[Depends(require_auth)])
async def close(trade_id: int) -> dict[str, Any]:
    return await batman.close_now(trade_id)
