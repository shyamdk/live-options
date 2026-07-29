from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.core.config import get_settings
from app.core.timeutil import now_ist
from app.services.app_auth import require_auth
from app.services.dhan import DhanService
from app.services.market import MarketService


router = APIRouter(prefix="/market", tags=["market"])


@router.get("/candles", dependencies=[Depends(require_auth)])
async def candles(
    security_id: str = Query(alias="securityId"),
    exchange_segment: str = Query(alias="exchangeSegment"),
    instrument: str = Query(alias="instrument"),
    interval: str = Query(default="5", alias="interval"),
) -> dict[str, Any]:
    """Today's session candles for an arbitrary tradable instrument (an
    option strike, an index, anything Dhan's /charts/intraday accepts) —
    unlike ema5_candles.py / animesh_candles.py, which hardcode the NIFTY
    index, this is a thin generic pass-through for on-demand chart views
    (e.g. Manage Trades' per-position chart).
    """
    settings = get_settings()
    dhan = DhanService(settings)
    now = now_ist()
    from_date = f"{now.date().isoformat()} 09:15:00"
    to_date = now.strftime("%Y-%m-%d %H:%M:%S")
    raw = await dhan.intraday_candles(
        security_id=security_id,
        exchange_segment=exchange_segment,
        instrument=instrument,
        interval=interval,
        from_date=from_date,
        to_date=to_date,
    )
    interval_minutes = int(interval)
    now_epoch = int(now.timestamp())
    completed = [c for c in raw if c["time"] + interval_minutes * 60 <= now_epoch]
    return {"candles": completed, "intervalMinutes": interval_minutes}


@router.get("/indices", dependencies=[Depends(require_auth)])
async def indices() -> dict:
    try:
        return await MarketService().indices()
    except Exception as exc:
        return {
            "source": "fallback",
            "stale": True,
            "warning": str(exc),
            "indices": [
                {"name": "Nifty 50", "lastPrice": None, "change": None, "percentChange": None},
                {"name": "Bank Nifty", "lastPrice": None, "change": None, "percentChange": None},
                {"name": "Sensex", "lastPrice": None, "change": None, "percentChange": None},
                {"name": "India VIX", "lastPrice": None, "change": None, "percentChange": None},
            ],
        }
