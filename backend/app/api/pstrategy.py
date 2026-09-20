from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.services.app_auth import require_auth
from app.services.crypto_indicators import ema
from app.services.delta_exchange import DeltaExchangeError, DeltaExchangeService
from app.services.pstrategy import detect_patterns

router = APIRouter(prefix="/pstrategy", tags=["pstrategy"])

SYMBOL = "XAUTUSD"
RESOLUTION_SECONDS = {"1m": 60, "5m": 300, "15m": 900}
EMA_FAST = 9
EMA_SLOW = 20


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
    closes = [float(c["close"]) for c in ordered]
    ema_fast = ema(closes, EMA_FAST)
    ema_slow = ema(closes, EMA_SLOW)

    boxes, breakouts = detect_patterns(ordered)

    # A breakout only counts as a confirmed momentum candle once it also
    # clears the EMA20 side-of-trend filter -- long momentum must close
    # above EMA20, short below, per the strategy review.
    momentum_candles: list[dict[str, Any]] = []
    for b in breakouts:
        idx = b["index"]
        e20 = ema_slow[idx]
        if e20 is None:
            continue
        close_price = float(ordered[idx]["close"])
        if (b["side"] == "long" and close_price > e20) or (b["side"] == "short" and close_price < e20):
            momentum_candles.append({"time": b["time"], "side": b["side"]})

    crossovers: list[dict[str, Any]] = []
    for k in range(1, len(ordered)):
        fast_prev, slow_prev = ema_fast[k - 1], ema_slow[k - 1]
        fast_now, slow_now = ema_fast[k], ema_slow[k]
        if fast_prev is None or slow_prev is None or fast_now is None or slow_now is None:
            continue
        prev_diff = fast_prev - slow_prev
        curr_diff = fast_now - slow_now
        if prev_diff <= 0 < curr_diff:
            crossovers.append({"time": ordered[k]["time"], "direction": "bullish"})
        elif prev_diff >= 0 > curr_diff:
            crossovers.append({"time": ordered[k]["time"], "direction": "bearish"})

    return {
        "symbol": SYMBOL,
        "resolution": resolution,
        "candles": [
            {"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]}
            for c in ordered
        ],
        "consolidations": boxes,
        "momentumCandles": momentum_candles,
        "ema9": ema_fast,
        "ema20": ema_slow,
        "crossovers": crossovers,
    }
