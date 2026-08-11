"""Distills market-moving headlines from free RSS feeds into a short,
strictly-filtered list via OpenAI, refreshed on a background loop and cached
in SQLite. Mirrors journal_insights.py's shape (periodic asyncio loop ->
OpenAI JSON-object call -> single-row cache), swapping "journal entries" for
"today's RSS headlines" and "reminders" for "headlines worth surfacing on
the dashboard ticker".

Also runs a second, slower-cadence loop for SCHEDULED macro events (Fed
meetings, CPI, jobs numbers, RBI policy) that RSS feeds often don't cover
until after the fact -- this one uses OpenAI's `web_search` tool (Responses
API) to look up the live economic calendar, since a plain chat-completion
call has no way to know what's scheduled for tonight. `web_search` can't be
combined with strict JSON mode, so the prompt asks hard for raw JSON and the
caller extracts the outer `{...}` defensively.
"""

from __future__ import annotations

import asyncio
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.timeutil import now_ist
from app.db.sqlite import save_market_calendar, save_market_news

SYSTEM_PROMPT = (
    "You pick market-moving headlines for a dashboard ticker watched by an "
    "Indian index-options trader (Nifty, Bank Nifty, Sensex). From the "
    "candidate headlines given, return ONLY the ones that would plausibly "
    "move Nifty or Sensex in today's or the next session — RBI/Fed/central "
    "bank decisions, major macro data (inflation, GDP, jobs), crude oil "
    "shocks, major geopolitical events, large FII/DII flow news, "
    "index-heavyweight earnings or guidance surprises, budget/policy "
    "announcements, or a sharp move in US/global markets overnight. "
    "Ordinary single-company news, routine market-report/wrap-up articles, "
    "opinion pieces, and anything not clearly index-moving do NOT qualify. "
    "Return 0-3 items — returning fewer than 3, or zero, is correct and "
    "expected when nothing meets the bar; do not pad the list. "
    "Respond with a JSON object: {\"items\": [{\"headline\": \"<rewritten, "
    "under 90 chars>\", \"impact\": \"high\"|\"medium\", \"link\": "
    "\"<the article's original url, copied exactly from the candidate>\"}]}. "
    "\"high\" impact means it would likely move the index today; \"medium\" "
    "means it's worth knowing but the move is less certain/immediate."
)

CALENDAR_PROMPT_TEMPLATE = (
    "Today is {today} (IST). Search for the most important SCHEDULED macro "
    "economic events or data releases in the next {horizon_hours} hours — US "
    "and India — that could move Nifty or Sensex: US CPI/PPI/jobs/payrolls "
    "data, Fed (FOMC) meetings or speeches, RBI monetary policy, India "
    "CPI/IIP/GDP/trade data, and comparable central-bank or major macro "
    "releases. Ignore anything routine or unlikely to move an index. Return "
    "at most {max_items} — fewer, or zero if nothing qualifies, is correct "
    "and expected; do not pad the list.\n\n"
    "Respond with ONLY a raw JSON object — no markdown fences, no prose "
    "before or after: {{\"items\": [{{\"headline\": \"<what it is + when, "
    "e.g. 'US CPI due tonight ~6:30pm IST', under 90 chars>\", \"impact\": "
    "\"high\"|\"medium\"}}]}}"
)

_task: asyncio.Task | None = None


def start_market_news_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.market_news_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_market_news_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


def start_market_calendar_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.market_calendar_monitor_enabled:
        return None
    return asyncio.create_task(_calendar_loop())


async def stop_market_calendar_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def _calendar_loop() -> None:
    settings = get_settings()
    interval = max(settings.market_calendar_check_interval_seconds, 300)
    while True:
        try:
            await refresh_market_calendar(settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(interval)


async def refresh_market_calendar(settings: Settings | None = None) -> dict[str, Any] | None:
    settings = settings or get_settings()
    if not settings.openai_api_key:
        return None
    prompt = CALENDAR_PROMPT_TEMPLATE.format(
        today=now_ist().strftime("%A, %d %B %Y"),
        horizon_hours=settings.market_calendar_horizon_hours,
        max_items=settings.market_calendar_max_items,
    )
    items = await _call_openai_calendar(settings.openai_api_key, settings.openai_model, prompt)
    if items is None:
        return None

    cleaned: list[dict[str, Any]] = []
    for item in items[: settings.market_calendar_max_items]:
        headline = str(item.get("headline") or "").strip()
        impact = str(item.get("impact") or "").strip().lower()
        if not headline or impact not in ("high", "medium"):
            continue
        cleaned.append({"headline": headline, "impact": impact, "link": None})

    save_market_calendar(cleaned)
    return {"items": cleaned}


async def _call_openai_calendar(api_key: str, model: str, prompt: str) -> list[dict[str, Any]] | None:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    try:
        response = await client.responses.create(model=model, input=prompt, tools=[{"type": "web_search"}])
    except Exception:
        return None
    text = getattr(response, "output_text", None)
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except (TypeError, ValueError):
        return None
    items = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        return None
    return [item for item in items if isinstance(item, dict)]


async def _loop() -> None:
    settings = get_settings()
    interval = max(settings.market_news_check_interval_seconds, 60)
    while True:
        try:
            await refresh_market_news(settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(interval)


async def refresh_market_news(settings: Settings | None = None) -> dict[str, Any] | None:
    settings = settings or get_settings()
    candidates = await _collect_candidates(settings)
    if not candidates:
        save_market_news([])
        return {"items": []}

    if not settings.openai_api_key:
        return None

    items = await _call_openai(settings.openai_api_key, settings.openai_model, candidates)
    if items is None:
        return None

    valid_links = {c["link"] for c in candidates}
    cleaned: list[dict[str, Any]] = []
    for item in items[: settings.market_news_max_items]:
        headline = str(item.get("headline") or "").strip()
        link = str(item.get("link") or "").strip()
        impact = str(item.get("impact") or "").strip().lower()
        if not headline or link not in valid_links or impact not in ("high", "medium"):
            continue
        cleaned.append({"headline": headline, "impact": impact, "link": link})

    save_market_news(cleaned)
    return {"items": cleaned}


async def _collect_candidates(settings: Settings) -> list[dict[str, str]]:
    urls = settings.market_news_feed_url_list
    if not urls:
        return []
    async with httpx.AsyncClient(timeout=10) as client:
        results = await asyncio.gather(*(_fetch_feed(client, url) for url in urls), return_exceptions=True)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.market_news_lookback_hours)
    epoch = datetime.fromtimestamp(0, tz=timezone.utc)
    seen_titles: set[str] = set()
    candidates: list[tuple[datetime, dict[str, str]]] = []
    for result in results:
        if isinstance(result, BaseException):
            continue
        for item in result:
            published = item.get("published")
            if published is not None and published < cutoff:
                continue
            key = item["title"].strip().lower()
            if not key or key in seen_titles:
                continue
            seen_titles.add(key)
            candidates.append((published or epoch, {"title": item["title"], "description": item.get("description", ""), "link": item["link"]}))

    candidates.sort(key=lambda c: c[0], reverse=True)
    return [c[1] for c in candidates[:40]]


async def _fetch_feed(client: httpx.AsyncClient, url: str) -> list[dict[str, Any]]:
    response = await client.get(url)
    response.raise_for_status()
    root = ET.fromstring(response.text)
    items: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        description = (item.findtext("description") or "").strip()
        pub_date_raw = item.findtext("pubDate")
        published: datetime | None = None
        if pub_date_raw:
            try:
                published = parsedate_to_datetime(pub_date_raw)
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                published = None
        items.append({"title": title, "link": link, "description": description, "published": published})
    return items


async def _call_openai(api_key: str, model: str, candidates: list[dict[str, str]]) -> list[dict[str, Any]] | None:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(candidates, default=str)},
            ],
            temperature=0.2,
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
    items = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        return None
    return [item for item in items if isinstance(item, dict)]
