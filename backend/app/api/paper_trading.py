from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import get_settings
from app.db import sqlite as db
from app.services.app_auth import require_auth
from app.services.dhan import DhanService

router = APIRouter(prefix="/paper-trading", tags=["paper-trading"])


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades() -> dict[str, Any]:
    return {"trades": await _with_live_pnl(db.list_paper_trades())}


async def _with_live_pnl(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enriches each OPEN trade with a live LTP + current P&L (booked legs'
    realized P&L so far, plus mark-to-market on whatever lots are still
    open) -- closed trades already have their final realizedPnl stored, so
    they're returned unchanged. Uses the same batched, server-cached
    market_quotes_by_segment call _manage_open_trades already relies on for
    exit checks (see paper_trading.py), so polling this endpoint often is
    cheap -- it doesn't add extra live Dhan calls beyond what's already
    happening every poll interval.
    """
    open_trades = [t for t in trades if t["status"] == "open"]
    if not open_trades:
        return trades

    securities_by_segment: dict[str, list[int]] = {}
    for trade in open_trades:
        sid, seg = trade.get("securityId"), trade.get("exchangeSegment")
        if not sid or not seg:
            continue
        try:
            securities_by_segment.setdefault(seg, []).append(int(sid))
        except (TypeError, ValueError):
            continue

    quotes: dict[str, Any] = {}
    if securities_by_segment:
        try:
            dhan = DhanService(get_settings())
            quotes = await dhan.market_quotes_by_segment(securities_by_segment)
        except Exception:
            quotes = {}

    for trade in open_trades:
        sid, seg = trade.get("securityId"), trade.get("exchangeSegment")
        quote = (quotes.get(seg) or {}).get(str(sid)) or {}
        current = quote.get("last_price")
        current = float(current) if current is not None else None
        trade["currentPremium"] = current

        booked_pnl = sum(leg["pnlAmount"] for leg in trade.get("legs", []))
        if trade["remainingLots"] <= 0:
            # Nothing still open to mark-to-market -- booked legs are the
            # whole story, live quote or not.
            trade["unrealizedPnl"] = 0.0
            trade["currentPnl"] = booked_pnl
        elif current is not None:
            unrealized = (current - trade["entryPremium"]) * trade["remainingLots"] * trade["lotSize"]
            trade["unrealizedPnl"] = unrealized
            trade["currentPnl"] = booked_pnl + unrealized
        else:
            # Lots are still open but no live quote came back (e.g. a stale
            # trade referencing an already-expired option contract) -- the
            # total is genuinely UNKNOWN, not zero. Showing 0.00 here would
            # misleadingly read as "flat" for what could be a real loss.
            trade["unrealizedPnl"] = None
            trade["currentPnl"] = None

    return trades


@router.get("/settings", dependencies=[Depends(require_auth)])
async def settings() -> dict[str, Any]:
    return db.get_paper_trading_settings()


class SettingsIn(BaseModel):
    stopLossPercent: float | None = None
    target1Percent: float | None = None
    target2Percent: float | None = None
    trailPercent: float | None = None
    niftyLots: float | None = None
    niftyLotSize: float | None = None
    sensexLots: float | None = None
    sensexLotSize: float | None = None


@router.put("/settings", dependencies=[Depends(require_auth)])
async def update_settings(payload: SettingsIn) -> dict[str, Any]:
    values = {key: value for key, value in payload.model_dump().items() if value is not None}
    return db.save_paper_trading_settings(values)
