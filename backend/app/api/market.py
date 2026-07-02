from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.app_auth import require_auth
from app.services.market import MarketService


router = APIRouter(prefix="/market", tags=["market"])


@router.get("/indices", dependencies=[Depends(require_auth)])
async def indices() -> dict:
    try:
        return await MarketService().indices()
    except Exception as exc:
        return {
            "source": "fallback",
            "warning": str(exc),
            "indices": [
                {"name": "Nifty 50", "lastPrice": None, "change": None, "percentChange": None},
                {"name": "Sensex", "lastPrice": None, "change": None, "percentChange": None},
                {"name": "India VIX", "lastPrice": None, "change": None, "percentChange": None},
            ],
        }
