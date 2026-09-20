from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.core.config import get_settings
from app.core.timeutil import now_ist
from app.db import sqlite as db
from app.services.app_auth import require_auth
from app.services.charges import option_order_charges
from app.services.crypto_indicators import atr as compute_atr
from app.services.crypto_indicators import ema, resample_ohlc
from app.services.dhan import DhanService
from app.services.pstrategy import ATR_LOOKBACK, confirm_momentum, detect_patterns
from app.services.pstrategy_nifty import INDEX_INSTRUMENT, INDEX_SEGMENT

router = APIRouter(prefix="/pstrategy-nifty", tags=["pstrategy-nifty"])

EMA_SLOW_PERIOD = 20


@router.get("/candles", dependencies=[Depends(require_auth)])
async def candles(resolution: str = Query(default="1m")) -> dict[str, Any]:
    if resolution not in ("1m", "3m"):
        return {"error": f"Unsupported resolution {resolution!r}", "candles": []}

    dhan = DhanService()
    today = now_ist().date().isoformat()
    try:
        raw = await dhan.intraday_candles(
            str(_nifty_security_id()), INDEX_SEGMENT, INDEX_INSTRUMENT, "1", today, today
        )
    except Exception as exc:
        return {"error": str(exc), "candles": []}

    ordered = sorted(raw, key=lambda c: c["time"])
    if resolution == "3m":
        ordered = resample_ohlc(ordered, 3)

    closes = [float(c["close"]) for c in ordered]
    ema_slow = ema(closes, EMA_SLOW_PERIOD)
    atr_values = compute_atr(ordered, ATR_LOOKBACK)
    boxes, breakouts = detect_patterns(ordered)
    confirmed = confirm_momentum(breakouts, ordered, ema_slow, atr_values)
    momentum_candles = [{"time": ordered[b["index"]]["time"], "side": b["side"]} for b in confirmed]

    return {
        "resolution": resolution,
        "candles": [
            {"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]}
            for c in ordered
        ],
        "consolidations": boxes,
        "momentumCandles": momentum_candles,
        "emaSlowValues": ema_slow,
    }


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades(resolution: str = Query(default="1m")) -> dict[str, Any]:
    if resolution not in ("1m", "3m"):
        return {"error": f"Unsupported resolution {resolution!r}", "trades": []}

    rows = db.list_pstrategy_nifty_trades(resolution)
    quotes_cache: dict[str, Any] | None = None

    for row in rows:
        qty = row["lots"] * row["lotSize"]
        entry_charges = option_order_charges(
            premium=row["entryPremium"], quantity=qty, side="BUY", exchange_segment=row["exchangeSegment"]
        )
        if row["status"] == "open":
            if quotes_cache is None:
                quotes_cache = await _fetch_open_quotes(rows)
            current = (quotes_cache.get(row["exchangeSegment"]) or {}).get(str(row["securityId"]))
            row["currentPremium"] = current
            if current:
                exit_charges = option_order_charges(
                    premium=current, quantity=qty, side="SELL", exchange_segment=row["exchangeSegment"]
                )
                gross = (current - row["entryPremium"]) * qty
                row["unrealizedPnl"] = gross
                row["charges"] = round(entry_charges["total"] + exit_charges["total"], 2)
                row["netUnrealizedPnl"] = round(gross - row["charges"], 2)
            else:
                row["unrealizedPnl"] = None
                row["charges"] = None
                row["netUnrealizedPnl"] = None
        else:
            exit_charges = option_order_charges(
                premium=row["exitPremium"] or 0, quantity=qty, side="SELL", exchange_segment=row["exchangeSegment"]
            )
            row["charges"] = round(entry_charges["total"] + exit_charges["total"], 2)
            row["netRealizedPnl"] = round((row["realizedPnl"] or 0) - row["charges"], 2)

    return {"trades": rows, "resolution": resolution}


async def _fetch_open_quotes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    securities_by_segment: dict[str, list[int]] = {}
    for row in rows:
        if row["status"] != "open":
            continue
        try:
            securities_by_segment.setdefault(row["exchangeSegment"], []).append(int(row["securityId"]))
        except (TypeError, ValueError):
            continue
    if not securities_by_segment:
        return {}
    try:
        raw = await DhanService().market_quotes_by_segment(securities_by_segment)
    except Exception:
        return {}
    return {
        segment: {sid: float((quote or {}).get("last_price") or 0) for sid, quote in (segment_quotes or {}).items()}
        for segment, segment_quotes in raw.items()
    }


def _nifty_security_id() -> int:
    return get_settings().dhan_nifty_security_id
