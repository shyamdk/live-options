from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from app.services import pf_lab
from app.services.app_auth import require_auth

router = APIRouter(prefix="/pf-lab", tags=["pf-lab"])


def _check(market: str, horizon: str) -> tuple[str, str]:
    market, horizon = market.upper(), horizon.lower()
    if market not in pf_lab.MARKETS or horizon not in pf_lab.HORIZONS:
        raise HTTPException(status_code=404, detail="Unknown market or horizon.")
    return market, horizon


@router.get("/overview", dependencies=[Depends(require_auth)])
async def overview() -> dict[str, Any]:
    return pf_lab.overview()


@router.get("/{market}/{horizon}/state", dependencies=[Depends(require_auth)])
async def state(market: str, horizon: str) -> dict[str, Any]:
    return pf_lab.state(*_check(market, horizon))


@router.put("/{market}/{horizon}/config", dependencies=[Depends(require_auth)])
async def update_config(market: str, horizon: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        return pf_lab.update_config(*_check(market, horizon), body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{market}/run", dependencies=[Depends(require_auth)])
async def run(market: str) -> dict[str, Any]:
    market = market.upper()
    if market not in pf_lab.MARKETS:
        raise HTTPException(status_code=404, detail="Unknown market.")
    try:
        return await pf_lab.run_market(market, trigger="manual")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Run failed: {exc}") from exc


@router.post("/trades/{trade_id}/close", dependencies=[Depends(require_auth)])
async def close(trade_id: int) -> dict[str, Any]:
    return await pf_lab.close_now(trade_id)
