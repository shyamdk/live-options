from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.services.app_auth import require_auth
from app.services.delta_exchange import DeltaExchangeError, DeltaExchangeService

router = APIRouter(prefix="/crypto-swing", tags=["crypto-swing"])


@router.get("/wallet", dependencies=[Depends(require_auth)])
async def wallet() -> dict[str, Any]:
    service = DeltaExchangeService()
    try:
        balances = await service.get_wallet_balances()
    except DeltaExchangeError as exc:
        return {"connected": False, "error": str(exc), "balances": []}
    return {"connected": True, "error": None, "balances": balances}
