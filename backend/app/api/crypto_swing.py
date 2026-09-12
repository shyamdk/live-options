from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.services.app_auth import require_auth
from app.services.crypto_indicators import ema, macd, supertrend
from app.services.delta_exchange import DeltaExchangeError, DeltaExchangeService

router = APIRouter(prefix="/crypto-swing", tags=["crypto-swing"])

SYMBOLS = {"BTCUSD", "ETHUSD"}
RESOLUTION_SECONDS = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600}


@router.get("/wallet", dependencies=[Depends(require_auth)])
async def wallet() -> dict[str, Any]:
    service = DeltaExchangeService()
    try:
        balances = await service.get_wallet_balances()
    except DeltaExchangeError as exc:
        return {"connected": False, "error": str(exc), "balances": []}
    return {"connected": True, "error": None, "balances": balances}


@router.get("/candles", dependencies=[Depends(require_auth)])
async def candles(
    symbol: str = Query(default="BTCUSD"),
    resolution: str = Query(default="30m"),
) -> dict[str, Any]:
    if symbol not in SYMBOLS:
        return {"error": f"Unsupported symbol {symbol!r}", "candles": []}
    step = RESOLUTION_SECONDS.get(resolution, 1800)
    # 200 EMA needs 200+ candles of history; fetch a healthy buffer beyond
    # that so the indicator has already stabilized by the earliest candle
    # actually shown on the chart.
    lookback_candles = 400
    end = int(time.time())
    start = end - step * lookback_candles

    service = DeltaExchangeService()
    try:
        raw = await service.get_candles(symbol, resolution, start, end)
    except DeltaExchangeError as exc:
        return {"error": str(exc), "candles": []}

    ordered = sorted(raw, key=lambda c: c["time"])
    closes = [float(c["close"]) for c in ordered]

    ema200 = ema(closes, 200)
    macd_line, signal_line, histogram = macd(closes)
    st_values, st_directions = supertrend(ordered, period=13, multiplier=4.0)

    return {
        "symbol": symbol,
        "resolution": resolution,
        "candles": [
            {"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]}
            for c in ordered
        ],
        "ema200": ema200,
        "macdLine": macd_line,
        "signalLine": signal_line,
        "histogram": histogram,
        "supertrend": st_values,
        "supertrendDirection": st_directions,
    }
