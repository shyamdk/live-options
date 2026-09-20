from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.services.app_auth import require_auth
from app.services.crypto_indicators import ema, rsi
from app.services.delta_exchange import DeltaExchangeError, DeltaExchangeService
from app.services.pstrategy import LEVERAGE, build_paper_trades, detect_patterns

router = APIRouter(prefix="/pstrategy", tags=["pstrategy"])

SYMBOL = "XAUTUSD"
RESOLUTION_SECONDS = {"1m": 60, "5m": 300, "15m": 900}
DEFAULT_EMA_FAST = 9
DEFAULT_EMA_SLOW = 20


@router.get("/candles", dependencies=[Depends(require_auth)])
async def candles(
    resolution: str = Query(default="5m"),
    ema_enabled: bool = Query(default=True, alias="emaEnabled"),
    ema_fast_period: int = Query(default=DEFAULT_EMA_FAST, alias="emaFast", ge=2, le=200),
    ema_slow_period: int = Query(default=DEFAULT_EMA_SLOW, alias="emaSlow", ge=2, le=200),
) -> dict[str, Any]:
    if resolution not in RESOLUTION_SECONDS:
        return {"error": f"Unsupported resolution {resolution!r}", "candles": []}
    if ema_fast_period >= ema_slow_period:
        ema_fast_period, ema_slow_period = DEFAULT_EMA_FAST, DEFAULT_EMA_SLOW

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
    rsi_values = rsi(closes)
    boxes, breakouts = detect_patterns(ordered)

    # The EMA side-of-trend filter (long momentum must close above the
    # slow EMA, short below) and the crossover markers are both gated by
    # the same enable flag -- when off, a breakout counts as momentum on
    # body+direction alone, and no EMA series/crossovers are computed.
    ema_fast: list[float | None] = []
    ema_slow: list[float | None] = []
    crossovers: list[dict[str, Any]] = []

    if ema_enabled:
        ema_fast = ema(closes, ema_fast_period)
        ema_slow = ema(closes, ema_slow_period)

        confirmed = []
        for b in breakouts:
            idx = b["index"]
            slow_value = ema_slow[idx]
            if slow_value is None:
                continue
            close_price = float(ordered[idx]["close"])
            if (b["side"] == "long" and close_price > slow_value) or (b["side"] == "short" and close_price < slow_value):
                confirmed.append(b)

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
    else:
        confirmed = breakouts

    momentum_candles = [{"time": b["time"], "side": b["side"]} for b in confirmed]
    trades = build_paper_trades(ordered, boxes, confirmed, ema_fast, ema_slow, ema_enabled)
    if trades and trades[-1]["status"] == "open":
        await _with_live_pnl(trades[-1])

    return {
        "symbol": SYMBOL,
        "resolution": resolution,
        "emaEnabled": ema_enabled,
        "emaFast": ema_fast_period,
        "emaSlow": ema_slow_period,
        "candles": [
            {"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]}
            for c in ordered
        ],
        "consolidations": boxes,
        "momentumCandles": momentum_candles,
        "trades": trades,
        "leverage": LEVERAGE,
        "rsi": rsi_values,
        "emaFastValues": ema_fast,
        "emaSlowValues": ema_slow,
        "crossovers": crossovers,
    }


async def _with_live_pnl(open_trade: dict[str, Any]) -> None:
    try:
        ticker = await DeltaExchangeService().get_ticker(SYMBOL)
        current = float(ticker["close"])
    except Exception:
        open_trade["currentPrice"] = None
        open_trade["unrealizedPnlPercent"] = None
        return
    direction = 1 if open_trade["side"] == "long" else -1
    open_trade["currentPrice"] = current
    open_trade["unrealizedPnlPercent"] = (current - open_trade["entryPrice"]) / open_trade["entryPrice"] * 100 * direction * LEVERAGE
