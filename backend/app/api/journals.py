from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import get_settings
from app.db.sqlite import get_journal, save_journal
from app.services.app_auth import require_auth
from app.services.trades import live_trade_snapshot


router = APIRouter(prefix="/journals", tags=["journals"])


class JournalIn(BaseModel):
    strategyDetails: str = ""
    lessonsLearnt: str = ""


@router.get("/today", dependencies=[Depends(require_auth)])
async def today_journal(date: str | None = None) -> dict[str, Any]:
    trade_date = date or _today()
    snapshot = await live_trade_snapshot()
    return {"tradeDate": trade_date, "journal": get_journal(trade_date), "summary": snapshot.get("summary"), "snapshot": snapshot}


@router.put("/{trade_date}", dependencies=[Depends(require_auth)])
async def update_journal(trade_date: str, payload: JournalIn) -> dict[str, Any]:
    return {"journal": save_journal(trade_date, payload.strategyDetails, payload.lessonsLearnt)}


def _today() -> str:
    settings = get_settings()
    return datetime.now(ZoneInfo(settings.app_timezone)).date().isoformat()
