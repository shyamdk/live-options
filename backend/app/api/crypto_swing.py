from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.core.config import get_settings
from app.db import sqlite as db
from app.services.app_auth import require_auth
from app.services.crypto_swing import (
    NOTIONAL_PER_TRANCHE,
    SYMBOLS,
    TRAIL_ARM_ATR_MULTIPLE,
    TRAIL_ATR_MULTIPLE,
    load_indicators,
    simulate_trades,
)
from app.services.crypto_swing_live import start_of_today_ist_epoch
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


@router.get("/candles", dependencies=[Depends(require_auth)])
async def candles(
    symbol: str = Query(default="BTCUSD"),
    resolution: str = Query(default="30m"),
) -> dict[str, Any]:
    if symbol not in SYMBOLS:
        return {"error": f"Unsupported symbol {symbol!r}", "candles": []}
    try:
        bundle = await load_indicators(symbol, resolution)
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
async def trades(
    resolution: str = Query(default="30m"),
    trail_arm: float = Query(default=TRAIL_ARM_ATR_MULTIPLE, alias="trailArm", ge=0.1, le=10),
    trail_multiple: float = Query(default=TRAIL_ATR_MULTIPLE, alias="trailMultiple", ge=0.1, le=10),
) -> dict[str, Any]:
    all_trades: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        try:
            bundle = await load_indicators(symbol, resolution)
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
            bundle.atr_values,
            trail_arm,
            trail_multiple,
        )
        for trade in symbol_trades:
            trade["symbol"] = symbol
        if symbol_trades and symbol_trades[-1]["status"] == "open":
            await _with_live_pnl(symbol_trades[-1])
        all_trades.extend(symbol_trades)

    all_trades.sort(key=lambda t: t.get("entryTime") or 0, reverse=True)
    return {"trades": all_trades, "trailArm": trail_arm, "trailMultiple": trail_multiple}


@router.get("/live-status", dependencies=[Depends(require_auth)])
async def live_status() -> dict[str, Any]:
    settings = get_settings()
    mode = "live" if not settings.crypto_swing_shadow_mode else "shadow"
    return {
        "liveEnabled": settings.crypto_swing_live_enabled,
        "shadowMode": settings.crypto_swing_shadow_mode,
        "mode": mode,
        "riskPercentPerTrade": settings.crypto_swing_risk_percent_per_trade,
        "maxDailyLossPercent": settings.crypto_swing_max_daily_loss_percent,
        "maxConcurrentPositions": settings.crypto_swing_max_concurrent_positions,
        "minMarginBufferPercent": settings.crypto_swing_min_margin_buffer_percent,
        "leverage": settings.crypto_swing_leverage,
        "openPositions": db.count_open_crypto_swing_live_trades(mode),
        "todayRealizedPnlUsd": db.get_today_realized_pnl_usd(mode, start_of_today_ist_epoch()),
        "trades": db.list_crypto_swing_live_trades(),
    }


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
