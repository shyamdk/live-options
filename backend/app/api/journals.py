from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.timeutil import now_ist
from app.db.sqlite import get_daily_trade_summaries, get_journal_insights, get_journals_for_dates, save_journal
from app.services.app_auth import require_auth
from app.services.journal_insights import refresh_journal_insights
from app.services.trades import live_trade_snapshot

router = APIRouter(prefix="/journals", tags=["journals"])

SESSION_DAYS = 7


class JournalIn(BaseModel):
    strategyDetails: str = ""
    howIFelt: str = ""
    whatHappened: str = ""
    lessonsLearnt: str = ""
    comments: str = ""


@router.get("/recent", dependencies=[Depends(require_auth)])
async def recent_sessions() -> dict[str, Any]:
    dates = _last_trading_dates(SESSION_DAYS)
    await live_trade_snapshot()  # opportunistically capture today's summary before reading it back
    summaries = get_daily_trade_summaries(dates)
    journals = get_journals_for_dates(dates)
    sessions = [
        {"tradeDate": trade_date, "summary": summaries.get(trade_date), "journal": journals.get(trade_date) or _empty_journal(trade_date)}
        for trade_date in dates
    ]
    return {"sessions": sessions}


@router.put("/{trade_date}", dependencies=[Depends(require_auth)])
async def update_journal(trade_date: str, payload: JournalIn) -> dict[str, Any]:
    journal = save_journal(
        trade_date,
        strategy_details=payload.strategyDetails,
        how_i_felt=payload.howIFelt,
        what_happened=payload.whatHappened,
        lessons_learnt=payload.lessonsLearnt,
        comments=payload.comments,
    )
    return {"journal": journal}


@router.get("/insights", dependencies=[Depends(require_auth)])
async def insights() -> dict[str, Any]:
    return get_journal_insights() or {"bullets": [], "generatedAt": None}


@router.post("/insights/refresh", dependencies=[Depends(require_auth)])
async def refresh_insights() -> dict[str, Any]:
    result = await refresh_journal_insights()
    if result is None:
        return get_journal_insights() or {"bullets": [], "generatedAt": None}
    return result


def _last_trading_dates(count: int) -> list[str]:
    dates: list[str] = []
    cursor = now_ist().date()
    while len(dates) < count:
        if cursor.weekday() < 5:  # Monday-Friday
            dates.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    return list(reversed(dates))


def _empty_journal(trade_date: str) -> dict[str, Any]:
    return {
        "tradeDate": trade_date,
        "strategyDetails": "",
        "howIFelt": "",
        "whatHappened": "",
        "lessonsLearnt": "",
        "comments": "",
        "createdAt": None,
        "updatedAt": None,
    }
