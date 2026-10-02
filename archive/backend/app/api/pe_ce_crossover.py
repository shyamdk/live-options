from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.timeutil import now_ist
from app.db import sqlite as db
from app.services.app_auth import require_auth
from app.services.crypto_indicators import adx, ema, rsi
from app.services.dhan import DhanService
from app.services.dhan_scrip_master import ScripMasterError, resolve_lot_size_by_security_id
from app.services.ema5_instruments import resolve_atm_option
from app.services.pe_ce_backtest import run_backtest
from app.services.pe_ce_crossover import (
    ADX_PERIOD,
    EMA_FAST_PERIOD,
    EMA_SLOW_PERIOD,
    OPTION_SEGMENT,
    RSI_PERIOD,
    STRIKE_STEP,
    current_mode,
    get_runtime_config,
    set_premium_expansion_filter_enabled,
    set_spread_filter_enabled,
    underlying_security_id,
)
from app.services.pe_ce_expiry import resolve_expiry_with_dte_policy
from app.services.pe_ce_metrics import compute_trade_metrics

router = APIRouter(prefix="/pe-ce-crossover", tags=["pe-ce-crossover"])


class PeCeConfigIn(BaseModel):
    premiumExpansionFilterEnabled: bool | None = None
    spreadFilterEnabled: bool | None = None


@router.get("/config", dependencies=[Depends(require_auth)])
async def config() -> dict[str, Any]:
    return get_runtime_config()


@router.put("/config", dependencies=[Depends(require_auth)])
async def update_config(body: PeCeConfigIn) -> dict[str, Any]:
    if body.premiumExpansionFilterEnabled is not None:
        set_premium_expansion_filter_enabled(body.premiumExpansionFilterEnabled)
    if body.spreadFilterEnabled is not None:
        set_spread_filter_enabled(body.spreadFilterEnabled)
    return get_runtime_config()


@router.get("/candles", dependencies=[Depends(require_auth)])
async def candles(underlying: str = Query(default="NIFTY"), side: str = Query(default="CE")) -> dict[str, Any]:
    if side not in ("CE", "PE"):
        return {"error": f"Unsupported side {side!r}", "candles": []}

    settings = get_settings()
    dhan = DhanService()
    try:
        expiry_info = await resolve_expiry_with_dte_policy(
            dhan, underlying_security_id(settings, underlying), override=settings.pe_ce_crossover_expiry_policy_override
        )
    except Exception as exc:
        return {"error": f"expiry lookup failed: {exc}", "candles": []}
    if not expiry_info:
        return {"error": "no valid expiry available", "candles": []}

    try:
        option = await resolve_atm_option(
            dhan,
            underlying_scrip=underlying_security_id(settings, underlying),
            expiry=expiry_info["expiry"],
            side=side,
            strike_step=STRIKE_STEP.get(underlying, 50.0),
        )
    except Exception as exc:
        return {"error": f"option chain lookup failed: {exc}", "candles": []}
    if not option:
        return {"error": "ATM option chain data unavailable", "candles": []}

    today = now_ist().date().isoformat()
    try:
        raw = await dhan.intraday_candles(option["securityId"], OPTION_SEGMENT, "OPTIDX", "1", today, today)
    except Exception as exc:
        return {"error": str(exc), "candles": []}

    ordered = sorted(raw, key=lambda c: c["time"])
    closes = [float(c["close"]) for c in ordered]
    ema_fast = ema(closes, EMA_FAST_PERIOD)
    ema_slow = ema(closes, EMA_SLOW_PERIOD)
    rsi_values = rsi(closes, RSI_PERIOD)
    adx_values = adx(ordered, ADX_PERIOD)

    trades = db.list_pe_ce_crossover_trades(underlying)
    trades = [t for t in trades if t["side"] == side]

    return {
        "underlying": underlying,
        "side": side,
        "strike": option["strike"],
        "expiry": expiry_info["expiry"],
        "dte": expiry_info["dte"],
        "expiryReason": expiry_info["reason"],
        "bid": option.get("bid"),
        "ask": option.get("ask"),
        "candles": [
            {"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]}
            for c in ordered
        ],
        "emaFastValues": ema_fast,
        "emaSlowValues": ema_slow,
        "rsiValues": rsi_values,
        "adxValues": adx_values,
        "trades": trades,
    }


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades(underlying: str = Query(default="NIFTY")) -> dict[str, Any]:
    return {"trades": db.list_pe_ce_crossover_trades(underlying), "underlying": underlying}


@router.get("/signal-log", dependencies=[Depends(require_auth)])
async def signal_log(underlying: str = Query(default="NIFTY")) -> dict[str, Any]:
    today = now_ist().date().isoformat()
    return {"log": db.list_pe_ce_crossover_signal_log(today, underlying), "sessionDate": today}


@router.get("/status", dependencies=[Depends(require_auth)])
async def status() -> dict[str, Any]:
    settings = get_settings()
    now = now_ist()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    mode = current_mode(settings)
    return {
        "monitorEnabled": settings.pe_ce_crossover_monitor_enabled,
        "underlyings": [u.strip().upper() for u in settings.pe_ce_crossover_underlyings.split(",") if u.strip()],
        "lots": settings.pe_ce_crossover_lots,
        "stopLossPercent": settings.pe_ce_crossover_stop_loss_percent,
        "targetPercent": settings.pe_ce_crossover_target_percent,
        "trailArmPercent": settings.pe_ce_crossover_trail_arm_percent,
        "trailPercent": settings.pe_ce_crossover_trail_percent,
        "maxCapitalRupees": settings.pe_ce_crossover_max_capital_rupees,
        "maxDailyLossRupees": settings.pe_ce_crossover_max_daily_loss_rupees,
        "maxTradesPerDay": settings.pe_ce_crossover_max_trades_per_day,
        "cooldownMinutes": settings.pe_ce_crossover_cooldown_minutes,
        "positionMode": settings.pe_ce_crossover_position_mode,
        # Phase 2: the current decision mode -- "paper" unless liveEnabled is
        # on, in which case shadowMode picks "shadow" (logged, no order sent)
        # or "live" (real orders). A real order additionally still requires
        # the global liveOrderEnabled kill switch -- see orders.py.
        "currentMode": mode,
        "liveEnabled": settings.pe_ce_crossover_live_enabled,
        "shadowMode": settings.pe_ce_crossover_shadow_mode,
        "globalLiveOrderEnabled": settings.live_order_enabled,
        "telegramAlertsEnabled": settings.pe_ce_crossover_telegram_alerts_enabled,
        "openPositions": len(db.list_open_pe_ce_crossover_trades(mode)),
        "todayRealizedPnl": db.get_today_realized_pnl_pe_ce_crossover(int(start_of_day.timestamp()), mode),
        "trades": db.list_pe_ce_crossover_trades(),
    }


@router.get("/report", dependencies=[Depends(require_auth)])
async def report(
    mode: str = Query(default="paper"),
    from_date: str = Query(alias="fromDate"),
    to_date: str = Query(alias="toDate"),
) -> dict[str, Any]:
    if mode not in ("paper", "shadow", "live"):
        return {"error": f"Unsupported mode {mode!r}"}
    try:
        from_epoch = int(datetime.fromisoformat(from_date).replace(hour=0, minute=0, second=0).timestamp())
        to_epoch = int(datetime.fromisoformat(to_date).replace(hour=23, minute=59, second=59).timestamp())
    except ValueError:
        return {"error": "fromDate/toDate must be YYYY-MM-DD"}

    trades = db.list_pe_ce_crossover_trades_for_report(mode, from_epoch, to_epoch)
    metrics = compute_trade_metrics(trades, pnl_key="realizedPnl")
    by_side: dict[str, list[dict[str, Any]]] = {"CE": [], "PE": []}
    by_underlying: dict[str, list[dict[str, Any]]] = {}
    for t in trades:
        by_side.setdefault(t["side"], []).append(t)
        by_underlying.setdefault(t["underlying"], []).append(t)

    return {
        "mode": mode,
        "fromDate": from_date,
        "toDate": to_date,
        "metrics": metrics,
        "metricsBySide": {side: compute_trade_metrics(rows, pnl_key="realizedPnl") for side, rows in by_side.items()},
        "metricsByUnderlying": {u: compute_trade_metrics(rows, pnl_key="realizedPnl") for u, rows in by_underlying.items()},
        "trades": trades,
    }


@router.get("/backtest", dependencies=[Depends(require_auth)])
async def backtest(
    underlying: str = Query(default="NIFTY"),
    side: str = Query(default="CE"),
    from_date: str = Query(alias="fromDate"),
    to_date: str = Query(alias="toDate"),
    expiry: str | None = Query(default=None),
) -> dict[str, Any]:
    if side not in ("CE", "PE"):
        return {"error": f"Unsupported side {side!r}", "trades": []}

    settings = get_settings()
    dhan = DhanService()
    scrip = underlying_security_id(settings, underlying)

    resolved_expiry = expiry
    if not resolved_expiry:
        expiry_info = await resolve_expiry_with_dte_policy(dhan, scrip)
        if not expiry_info:
            return {"error": "no valid expiry available to backtest against", "trades": []}
        resolved_expiry = expiry_info["expiry"]

    # Lot size is uniform across strikes for a given underlying+expiry --
    # resolve it from any current strike on this side rather than
    # hard-coding it (spec: "never hard-code a permanent lot size").
    option = await resolve_atm_option(
        dhan, underlying_scrip=scrip, expiry=resolved_expiry, side=side, strike_step=STRIKE_STEP.get(underlying, 50.0)
    )
    if not option:
        return {"error": "could not resolve any contract on this expiry/side to determine lot size", "trades": []}
    try:
        lot_size = await resolve_lot_size_by_security_id(option["securityId"])
    except ScripMasterError as exc:
        return {"error": str(exc), "trades": []}

    return await run_backtest(
        dhan,
        underlying=underlying,
        underlying_scrip=scrip,
        side=side,
        expiry=resolved_expiry,
        from_date=from_date,
        to_date=to_date,
        lot_size=lot_size * settings.pe_ce_crossover_lots,
        stop_loss_percent=settings.pe_ce_crossover_stop_loss_percent,
        target_percent=settings.pe_ce_crossover_target_percent,
        trail_arm_percent=settings.pe_ce_crossover_trail_arm_percent,
        trail_percent=settings.pe_ce_crossover_trail_percent,
        min_premium_expansion_percent=settings.pe_ce_crossover_min_premium_expansion_percent,
        premium_expansion_lookback_bars=settings.pe_ce_crossover_premium_expansion_lookback_bars,
    )
