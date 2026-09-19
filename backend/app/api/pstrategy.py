from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.services.app_auth import require_auth
from app.services.delta_exchange import DeltaExchangeError, DeltaExchangeService
from app.services.pstrategy import detect_consolidations

router = APIRouter(prefix="/pstrategy", tags=["pstrategy"])

SYMBOL = "XAUTUSD"
RESOLUTION_SECONDS = {"1m": 60, "5m": 300, "15m": 900}


@router.get("/candles", dependencies=[Depends(require_auth)])
async def candles(resolution: str = Query(default="5m")) -> dict[str, Any]:
    if resolution not in RESOLUTION_SECONDS:
        return {"error": f"Unsupported resolution {resolution!r}", "candles": []}
    step = RESOLUTION_SECONDS[resolution]
    # Enough history for the ATR warm-up plus a healthy scroll-back window
    # of already-resolved consolidation boxes.
    lookback_candles = 300
    end = int(time.time())
    start = end - step * lookback_candles

    try:
        raw = await DeltaExchangeService().get_candles(SYMBOL, resolution, start, end)
    except DeltaExchangeError as exc:
        return {"error": str(exc), "candles": []}

    ordered = sorted(raw, key=lambda c: c["time"])
    consolidations = detect_consolidations(ordered)

    return {
        "symbol": SYMBOL,
        "resolution": resolution,
        "candles": [
            {"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]}
            for c in ordered
        ],
        "consolidations": consolidations,
    }
