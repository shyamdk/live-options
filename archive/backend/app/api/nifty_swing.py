from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.core.config import get_settings
from app.db import sqlite as db
from app.services.app_auth import require_auth
from app.services.crypto_swing import FLIP_CONFIRM_WINDOW_CANDLES, TRAIL_ARM_ATR_MULTIPLE, TRAIL_ATR_MULTIPLE, simulate_trades
from app.services.crypto_swing_live import start_of_today_ist_epoch
from app.services.dhan import DhanService
from app.services.dhan_scrip_master import ScripMasterError
from app.services.nifty_swing import DEFAULT_QUANTITY_PER_TRANCHE, EQUITY_SEGMENT, get_security_id, load_indicators

router = APIRouter(prefix="/nifty-swing", tags=["nifty-swing"])


@router.get("/candles", dependencies=[Depends(require_auth)])
async def candles(resolution: str = Query(default="30m")) -> dict[str, Any]:
    try:
        bundle = await load_indicators(resolution)
    except ScripMasterError as exc:
        return {"error": str(exc), "candles": []}
    except Exception as exc:
        return {"error": str(exc), "candles": []}

    return {
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
    quantity: float = Query(default=DEFAULT_QUANTITY_PER_TRANCHE, ge=1, le=100_000),
    flip_confirm_window: int = Query(default=FLIP_CONFIRM_WINDOW_CANDLES, alias="flipConfirmWindow", ge=0, le=20),
) -> dict[str, Any]:
    try:
        bundle = await load_indicators(resolution)
    except Exception as exc:
        return {
            "trades": [{"status": "error", "error": str(exc)}],
            "trailArm": trail_arm,
            "trailMultiple": trail_multiple,
            "quantity": quantity,
            "flipConfirmWindow": flip_confirm_window,
        }

    all_trades = simulate_trades(
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
        allow_short=False,
        quantity_per_tranche=quantity,
        flip_confirm_window_candles=flip_confirm_window,
    )
    if all_trades and all_trades[-1]["status"] == "open":
        await _with_live_pnl(all_trades[-1])

    all_trades.sort(key=lambda t: t.get("entryTime") or 0, reverse=True)
    return {
        "trades": all_trades,
        "trailArm": trail_arm,
        "trailMultiple": trail_multiple,
        "quantity": quantity,
        "flipConfirmWindow": flip_confirm_window,
    }


async def _with_live_pnl(open_trade: dict[str, Any]) -> None:
    try:
        security_id = await get_security_id()
        quote_map = await DhanService().market_quotes_by_segment({EQUITY_SEGMENT: [security_id]})
        current = float((quote_map.get(EQUITY_SEGMENT) or {}).get(str(security_id), {}).get("last_price") or 0)
        if not current:
            raise ValueError("no LTP")
    except Exception:
        open_trade["currentPrice"] = None
        open_trade["unrealizedPnlPercent"] = None
        open_trade["unrealizedPnlAmount"] = None
        return

    direction = 1 if open_trade["side"] == "long" else -1
    pnl_pct = (current - open_trade["entryPrice"]) / open_trade["entryPrice"] * 100 * direction
    open_trade["currentPrice"] = current
    open_trade["unrealizedPnlPercent"] = pnl_pct
    open_trade["unrealizedPnlAmount"] = pnl_pct / 100 * open_trade["entryPrice"] * open_trade["quantity"]


@router.get("/live-status", dependencies=[Depends(require_auth)])
async def live_status() -> dict[str, Any]:
    settings = get_settings()
    mode = "live" if not settings.nifty_swing_shadow_mode else "shadow"
    return {
        "liveEnabled": settings.nifty_swing_live_enabled,
        "shadowMode": settings.nifty_swing_shadow_mode,
        "mode": mode,
        "quantityPerTranche": settings.nifty_swing_live_quantity_per_tranche,
        "maxCapitalRupees": settings.nifty_swing_live_max_capital_rupees,
        "maxDailyLossRupees": settings.nifty_swing_live_max_daily_loss_rupees,
        "resolution": settings.nifty_swing_live_resolution,
        "productType": settings.nifty_swing_live_product_type,
        "openPositions": db.count_open_nifty_swing_live_trades(mode),
        "todayRealizedPnlInr": db.get_today_realized_pnl_inr(mode, start_of_today_ist_epoch()),
        "trades": db.list_nifty_swing_live_trades(),
    }
