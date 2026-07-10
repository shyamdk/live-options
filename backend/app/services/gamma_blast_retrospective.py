"""End-of-session retrospective: gathers the day's signals/trades/events and
asks OpenAI to summarize mistakes, lessons, and strategy tweaks worth trying.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.config import get_settings
from app.db import gamma_blast as db

SYSTEM_PROMPT = (
    "You are a disciplined options trading coach reviewing one day's gamma-blast "
    "expiry-day trades. Gamma blast: buy a cheap ATM/1-strike-OTM option when spot "
    "breaks a heavy-OI wall late on expiry day, betting on short-covering. It is a "
    "low-hit-rate, high-payout strategy — most attempts should lose small, a few "
    "should win big. Review the session data and answer plainly, no fluff:\n"
    "1. What happened, in order (walls, signals, entries, exits).\n"
    "2. Any concrete mistakes (bad timing, chasing, ignoring the quiet-day filter, "
    "sizing issues, slow approvals costing entry price, exits held too long/short).\n"
    "3. What to keep doing (whatever worked).\n"
    "4. 1-3 specific, testable changes to try next expiry day (thresholds, "
    "timing windows, or process — not vague advice)."
)


async def generate_retrospective(session_id: str) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.openai_api_key:
        db.record_event(session_id, "RETROSPECTIVE_SKIPPED", "OPENAI_API_KEY not configured.")
        return None

    session = db.get_session(session_id)
    if not session:
        return None
    signals = db.get_signals_for_session(session_id)
    trades = db.get_trades_for_session(session_id)
    events = db.get_events_for_session(session_id)

    bundle = {
        "session": session,
        "signals": signals,
        "trades": trades,
        "events": [{"at": e["createdAt"], "type": e["eventType"], "message": e["message"]} for e in events],
    }

    summary = await _call_openai(settings.openai_api_key, settings.openai_model, bundle)
    if summary is None:
        db.record_event(session_id, "RETROSPECTIVE_FAILED", "OpenAI call did not return a summary.")
        return None

    db.save_retrospective(session_id, session["sessionDate"], summary, {"trades": trades, "signals": signals})
    db.record_event(session_id, "RETROSPECTIVE_READY", "Retrospective generated.")
    return {"sessionId": session_id, "summary": summary}


async def _call_openai(api_key: str, model: str, bundle: dict[str, Any]) -> str | None:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(bundle, default=str)},
            ],
            temperature=0.4,
        )
    except Exception:
        return None
    choice = response.choices[0] if response.choices else None
    return choice.message.content if choice and choice.message else None
