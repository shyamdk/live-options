from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.services.app_auth import require_auth
from app.services.crypto_indicators import ema, macd, supertrend
from app.services.crypto_swing import NOTIONAL_PER_TRANCHE, simulate_trades
from app.services.delta_exchange import DeltaExchangeError, DeltaExchangeService

router = APIRouter(prefix="/crypto-swing", tags=["crypto-swing"])

SYMBOLS = ("BTCUSD", "ETHUSD", "XAUTUSD")
RESOLUTION_SECONDS = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600}


class _IndicatorBundle:
    def __init__(self, ordered: list[dict[str, Any]], ema200, macd_line, signal_line, histogram, st_values, st_directions):
        self.ordered = ordered
        self.ema200 = ema200
        self.macd_line = macd_line
        self.signal_line = signal_line
        self.histogram = histogram
        self.st_values = st_values
        self.st_directions = st_directions


async def _load_indicators(symbol: str, resolution: str) -> _IndicatorBundle:
    step = RESOLUTION_SECONDS.get(resolution, 1800)
    # 200 EMA needs 200+ candles of history; fetch a healthy buffer beyond
    # that so the indicator has already stabilized by the earliest candle
    # actually shown/simulated.
    lookback_candles = 400
    end = int(time.time())
    start = end - step * lookback_candles

    raw = await DeltaExchangeService().get_candles(symbol, resolution, start, end)
    ordered = sorted(raw, key=lambda c: c["time"])
    closes = [float(c["close"]) for c in ordered]

    ema200 = ema(closes, 200)
    macd_line, signal_line, histogram = macd(closes)
    st_values, st_directions = supertrend(ordered, period=13, multiplier=4.0)
    return _IndicatorBundle(ordered, ema200, macd_line, signal_line, histogram, st_values, st_directions)


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
    try:
        bundle = await _load_indicators(symbol, resolution)
    except DeltaExchangeError as exc:
        return {"error": str(exc), "candles": []}

    return {
        "symbol": symbol,
        "resolution": resolution,
        "candles": [
            {"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]}
            for c in bundle.ordered
        ],
        "ema200": bundle.ema200,
        "macdLine": bundle.macd_line,
        "signalLine": bundle.signal_line,
        "histogram": bundle.histogram,
        "supertrend": bundle.st_values,
        "supertrendDirection": bundle.st_directions,
    }


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades(resolution: str = Query(default="30m")) -> dict[str, Any]:
    all_trades: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        try:
            bundle = await _load_indicators(symbol, resolution)
        except Exception as exc:
            all_trades.append({"symbol": symbol, "status": "error", "error": str(exc)})
            continue

        symbol_trades = simulate_trades(
            bundle.ordered,
            bundle.ema200,
            bundle.macd_line,
            bundle.signal_line,
            bundle.histogram,
            bundle.st_values,
            bundle.st_directions,
        )
        for trade in symbol_trades:
            trade["symbol"] = symbol
        if symbol_trades and symbol_trades[-1]["status"] == "open":
            await _with_live_pnl(symbol_trades[-1])
        all_trades.extend(symbol_trades)

    all_trades.sort(key=lambda t: t.get("entryTime") or 0, reverse=True)
    return {"trades": all_trades}


async def _with_live_pnl(open_trade: dict[str, Any]) -> None:
    try:
        ticker = await DeltaExchangeService().get_ticker(open_trade["symbol"])
        current = float(ticker["close"])
    except Exception:
        open_trade["currentPrice"] = None
        open_trade["unrealizedPnlPercent"] = None
        open_trade["unrealizedPnlAmount"] = None
        return

    direction = 1 if open_trade["side"] == "long" else -1
    pnl_pct = (current - open_trade["entryPrice"]) / open_trade["entryPrice"] * 100 * direction
    open_trade["currentPrice"] = current
    open_trade["unrealizedPnlPercent"] = pnl_pct
    open_trade["unrealizedPnlAmount"] = pnl_pct / 100 * NOTIONAL_PER_TRANCHE * open_trade["tranches"]
