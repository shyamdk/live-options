"""Major scheduled market events -- the NIFTY Strangle event-week rider.

The plain (naked) strangle book skips any entry whose hold (entry day ..
expiry day, inclusive) contains one of these days; the hedged book trades
through them with its wings on.

`day` is the IST date the market reacts: an RBI policy is the announcement
day; a US Fed (FOMC) decision lands ~23:30-00:30 IST, so it is stored on the
next IST day. Seeded from official calendars (checked 12 Nov 2026), then
refreshed weekly by OpenAI with web search; anything can be added or deleted
on the page.

Seed sources:
  RBI MPC FY2026-27 schedule (RBI press release, 23 Mar 2026): decisions
    8 Apr, 5 Jun, 5 Aug, 7 Oct, 4 Dec 2026, 5 Feb 2027.
  FOMC 2026-27 (federalreserve.gov): decisions 9 Dec 2026; 27 Jan, 17 Mar,
    28 Apr, 9 Jun, 28 Jul, 15 Sep, 27 Oct, 8 Dec 2027 (US dates).
  Union Budget: 1 Feb 2027 (convention since 2017).
  2027 state elections (UP, Punjab, Uttarakhand, Goa, Manipur ~Feb-Mar;
    Gujarat, Himachal ~Dec): counting dates not announced yet -- the
    OpenAI refresh is expected to add them once the ECI does.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.ai_gate import PAUSED_MESSAGE, ai_allowed
from app.core.config import get_settings
from app.db import sqlite as db

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
KINDS = ("budget", "rbi", "fomc", "election", "other")

SEED: list[tuple[str, str, str]] = [
    ("2026-12-04", "RBI policy decision", "rbi"),
    ("2027-02-05", "RBI policy decision", "rbi"),
    ("2027-02-01", "Union Budget 2027-28", "budget"),
    *[((date.fromisoformat(d) + timedelta(days=1)).isoformat(), f"US Fed (FOMC) decision ({d} US)", "fomc") for d in (
        "2026-12-09", "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08")],
]

PROMPT = (
    "Today is {today} (IST). Search the web and list the MAJOR scheduled events in the next 120 days that could gap "
    "India's NIFTY index: Union Budget / interim budget, RBI monetary policy decision days, US Federal Reserve (FOMC) "
    "rate decisions, Indian general or state assembly election RESULT (counting) days, US presidential election day. "
    "Only include dates that are officially announced (no guesses). For FOMC give the US decision date. "
    "Return ONLY raw JSON: {{\"items\": [{{\"date\": \"YYYY-MM-DD\", \"name\": \"<short name>\", "
    "\"kind\": \"budget|rbi|fomc|election|other\", \"source\": \"<url>\"}}]}}"
)


def seed() -> None:
    have = {(e["day"], e["kind"]) for e in db.list_market_events()}
    for day, name, kind in SEED:
        if (day, kind) not in have:
            db.upsert_market_event(day, name, kind, "seed")


def upcoming(days: int = 180) -> list[dict[str, Any]]:
    today = datetime.now(IST).date()
    return db.list_market_events((today - timedelta(days=7)).isoformat(), (today + timedelta(days=days)).isoformat())


def events_between(start: date, end: date) -> list[dict[str, Any]]:
    return db.list_market_events(start.isoformat(), end.isoformat())


def add(day: str, name: str, kind: str = "other") -> None:
    date.fromisoformat(day)
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if not name.strip():
        raise ValueError("name is required")
    db.upsert_market_event(day, name.strip(), kind, "manual")


async def refresh() -> dict[str, Any]:
    settings = get_settings()
    if not ai_allowed("market_events"):
        return {"added": 0, "error": PAUSED_MESSAGE}
    if not settings.openai_api_key:
        return {"added": 0, "error": "OPENAI_API_KEY is not set"}
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    prompt = PROMPT.format(today=datetime.now(IST).strftime("%A, %d %B %Y"))
    try:
        response = await client.responses.create(model=settings.openai_model, input=prompt, tools=[{"type": "web_search"}])
    except Exception as exc:
        return {"added": 0, "error": f"OpenAI: {exc}"}
    match = re.search(r"\{.*\}", getattr(response, "output_text", "") or "", re.DOTALL)
    try:
        items = json.loads(match.group(0)).get("items") if match else None
    except ValueError:
        items = None
    if not isinstance(items, list):
        return {"added": 0, "error": "OpenAI returned no usable list"}
    today = datetime.now(IST).date()
    added = 0
    have = {(e["day"], e["kind"]) for e in db.list_market_events()}
    for it in items:
        try:
            d = date.fromisoformat(str(it.get("date")))
        except (TypeError, ValueError):
            continue
        kind = str(it.get("kind") or "other").lower()
        kind = kind if kind in KINDS else "other"
        if kind == "fomc":
            d += timedelta(days=1)  # the decision reaches Indian markets the next IST day
        if d < today or d > today + timedelta(days=150):
            continue
        name = str(it.get("name") or kind).strip()[:80]
        if (d.isoformat(), kind) not in have:
            added += 1
        db.upsert_market_event(d.isoformat(), name, kind, "openai", str(it.get("source") or "")[:300] or None)
    db.set_kite_setting("events.refreshedAt", datetime.now(IST).isoformat(timespec="seconds"))
    return {"added": added, "seen": len(items)}


async def _loop() -> None:
    try:
        seed()
    except Exception:
        logger.exception("market_events: seed failed")
    while True:
        try:
            last = db.get_kite_setting("events.refreshedAt")
            if not last or datetime.now(IST) - datetime.fromisoformat(last) > timedelta(days=7):
                result = await refresh()
                logger.info("market_events: refresh %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("market_events: refresh failed")
        await asyncio.sleep(6 * 3600)


def start_market_events_task() -> asyncio.Task | None:
    return asyncio.create_task(_loop())


async def stop_market_events_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return
