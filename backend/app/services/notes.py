"""Notes -- free-form trading notes / learnings by date, plus a summary on top.

The summary has two parts: plain counts computed here (notes, days, months,
tags) and an AI digest (OpenAI, same key as Trade Journals) that is generated
only when the user presses Refresh and then stored, so opening the page never
costs an API call. The digest is told to use only what the notes say.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from app.core.ai_gate import PAUSED_MESSAGE, ai_allowed
from app.core.config import get_settings
from app.db import sqlite as db

MAX_PROMPT_CHARS = 60_000  # newest notes first; older ones are dropped beyond this

SYSTEM_PROMPT = """You summarise a trader's personal notes and learnings.
Use ONLY what the notes say -- do not describe the trader or their markets beyond what the notes mention, and do not add generic trading advice or invent facts. Quote numbers and dates from the notes where they matter.
Return a JSON object with these keys:
- "overview": 2-3 sentences on what the notes are mostly about and how the thinking has evolved over time.
- "keyLearnings": up to 8 short bullets, the most important lessons, newest-relevant first, each ending with the date(s) in brackets.
- "rules": up to 6 short bullets, rules or habits the trader has written down for themself (or that the notes clearly imply).
- "recurringMistakes": up to 5 short bullets, mistakes or problems that show up more than once (empty list if none).
- "openQuestions": up to 5 short bullets, things the notes say to check, test or decide later (empty list if none).
Keep every bullet under 30 words."""


def stats(notes: list[dict[str, Any]]) -> dict[str, Any]:
    days = sorted({n["day"] for n in notes})
    months = Counter(n["day"][:7] for n in notes)
    tags = Counter(t for n in notes for t in n["tags"])
    return {
        "notes": len(notes),
        "days": len(days),
        "first": days[0] if days else None,
        "last": days[-1] if days else None,
        "byMonth": [{"month": m, "count": c} for m, c in sorted(months.items(), reverse=True)],
        "topTags": [{"tag": t, "count": c} for t, c in tags.most_common(12)],
    }


def summary() -> dict[str, Any]:
    notes = db.list_notes()
    digest = db.get_notes_summary()
    if digest:
        digest["stale"] = digest.get("noteCount") != len(notes) or digest.get("lastUpdated") != max((n["updatedAt"] for n in notes), default=None)
    return {"stats": stats(notes), "digest": digest, "aiAvailable": bool(get_settings().openai_api_key) and ai_allowed("notes_digest"), "aiPausedMessage": None if ai_allowed("notes_digest") else PAUSED_MESSAGE}


async def refresh_digest() -> dict[str, Any]:
    settings = get_settings()
    if not ai_allowed("notes_digest"):
        raise ValueError(PAUSED_MESSAGE)
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set on the server.")
    notes = db.list_notes()
    if not notes:
        raise ValueError("Add a note first.")
    entries, size = [], 0
    for n in notes:  # newest first
        entry = {"date": n["day"], "title": n["title"], "tags": n["tags"], "note": n["body"]}
        size += len(json.dumps(entry))
        if size > MAX_PROMPT_CHARS:
            break
        entries.append(entry)

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": json.dumps(entries, ensure_ascii=False)}],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content if response.choices else None
    parsed = json.loads(content or "{}")
    as_list = lambda key: [str(x) for x in (parsed.get(key) or []) if str(x).strip()]
    payload = {
        "overview": str(parsed.get("overview") or ""),
        "keyLearnings": as_list("keyLearnings"),
        "rules": as_list("rules"),
        "recurringMistakes": as_list("recurringMistakes"),
        "openQuestions": as_list("openQuestions"),
        "noteCount": len(notes),
        "notesUsed": len(entries),
        "lastUpdated": max(n["updatedAt"] for n in notes),
        "model": settings.openai_model,
    }
    db.save_notes_summary(payload)
    return summary()
