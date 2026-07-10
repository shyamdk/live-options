"""Distills all trade-journal entries into a short list of reminder bullets via
OpenAI, refreshed automatically once a day. Mirrors the gamma-blast
retrospective service's shape but runs off the whole journal history rather
than a single session.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.core.config import Settings, get_settings
from app.core.timeutil import in_time_window, now_ist
from app.db.sqlite import get_journal_insights, get_journals_with_content, save_journal_insights

SYSTEM_PROMPT = (
    "You distill a trader's journal entries into a short list of reminders they "
    "should see every time they open their trading dashboard. Read every entry "
    "(Strategy, How I felt, What happened, Lessons Learnt, Comments) across all "
    "days provided. Return the recurring, concrete lessons worth remembering — "
    "not a summary of each day. Merge duplicates, drop one-off trivia, keep each "
    "bullet under 15 words, imperative voice (e.g. 'Cut losers within 10 minutes "
    "of a failed breakout', not 'The trader noticed losers should be cut'). "
    "Return 3-8 bullets, fewer if there isn't enough material. Respond with a "
    "JSON object: {\"bullets\": [\"...\", \"...\"]}."
)

_task: asyncio.Task | None = None


def start_journal_insights_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.journal_insights_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_journal_insights_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def _loop() -> None:
    settings = get_settings()
    interval = max(settings.journal_insights_check_interval_seconds, 60)
    while True:
        try:
            await _maybe_refresh(settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(interval)


async def _maybe_refresh(settings: Settings) -> None:
    now = now_ist()
    if not in_time_window(now.time(), settings.journal_insights_refresh_time, "23:59"):
        return
    existing = get_journal_insights()
    if existing and (existing.get("generatedAt") or "")[:10] == now.date().isoformat():
        return
    await refresh_journal_insights()


async def refresh_journal_insights() -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    journals = get_journals_with_content()
    if not journals:
        return None
    bullets = await _call_openai(settings.openai_api_key, settings.openai_model, journals)
    if bullets is None:
        return None
    save_journal_insights(bullets)
    return {"bullets": bullets}


async def _call_openai(api_key: str, model: str, journals: list[dict[str, Any]]) -> list[str] | None:
    from openai import AsyncOpenAI

    entries = [
        {
            "date": j["tradeDate"],
            "strategy": j["strategyDetails"],
            "howIFelt": j["howIFelt"],
            "whatHappened": j["whatHappened"],
            "lessonsLearnt": j["lessonsLearnt"],
            "comments": j["comments"],
        }
        for j in journals
    ]
    client = AsyncOpenAI(api_key=api_key)
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(entries, default=str)},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
    except Exception:
        return None
    choice = response.choices[0] if response.choices else None
    if not choice or not choice.message or not choice.message.content:
        return None
    try:
        parsed = json.loads(choice.message.content)
    except (TypeError, ValueError):
        return None
    bullets = parsed.get("bullets") if isinstance(parsed, dict) else None
    if not isinstance(bullets, list):
        return None
    return [str(b) for b in bullets if str(b).strip()]
