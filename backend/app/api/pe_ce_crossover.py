from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.core.config import get_settings
from app.core.timeutil import now_ist
from app.db import sqlite as db
from app.services.app_auth import require_auth
from app.services.crypto_indicators import ema
from app.services.dhan import DhanService
from app.services.dhan_scrip_master import ScripMasterError, resolve_lot_size_by_security_id
from app.services.ema5_instruments import resolve_atm_option
from app.services.pe_ce_backtest import run_backtest
from app.services.pe_ce_crossover import EMA_FAST_PERIOD, EMA_SLOW_PERIOD, OPTION_SEGMENT, STRIKE_STEP, underlying_security_id
from app.services.pe_ce_expiry import resolve_expiry_with_dte_policy

router = APIRouter(prefix="/pe-ce-crossover", tags=["pe-ce-crossover"])


@router.get("/candles", dependencies=[Depends(require_auth)])
async def candles(underlying: str = Query(default="NIFTY"), side: str = Query(default="CE")) -> dict[str, Any]:
    if side not in ("CE", "PE"):
        return {"error": f"Unsupported side {side!r}", "candles": []}

    settings = get_settings()
    dhan = DhanService()
    expiry_info = await resolve_expiry_with_dte_policy(
        dhan, underlying_security_id(settings, underlying), override=settings.pe_ce_crossover_expiry_policy_override
    )
    if not expiry_info:
        return {"error": "no valid expiry available", "candles": []}

    option = await resolve_atm_option(
        dhan,
        underlying_scrip=underlying_security_id(settings, underlying),
        expiry=expiry_info["expiry"],
        side=side,
        strike_step=STRIKE_STEP.get(underlying, 50.0),
    )
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
        "openPositions": len(db.list_open_pe_ce_crossover_trades()),
        "todayRealizedPnl": db.get_today_realized_pnl_pe_ce_crossover(int(start_of_day.timestamp())),
        "trades": db.list_pe_ce_crossover_trades(),
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
