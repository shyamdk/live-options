from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import Settings, get_settings


class OpenAINewsService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def stock_news(self, *, symbol: str, company_name: str | None = None) -> dict[str, Any]:
        api_key = self.settings.resolved_openai_api_key
        if not api_key:
            return _empty_news(symbol, "OPENAI_API_KEY is not configured.")

        prompt = (
            f"Find the latest material news for Indian listed stock {symbol}"
            f"{f' ({company_name})' if company_name else ''}. "
            "Focus on earnings, management commentary, orders, regulation, credit rating, litigation, "
            "sector events, and broker or exchange announcements from the last 14 days when available. "
            "Return compact JSON only with keys: sentiment, summary, headlines, risks, negativeScope, materialNegative, nextResultsDate. "
            "sentiment must be positive, neutral, negative, or mixed. "
            "headlines must be an array of up to 5 objects with title, source, url, date, impact. "
            "negativeScope: where any negative news comes from -- company (governance, fraud, guidance cut, order loss, "
            "regulatory action, downgrade specific to this company), sector, market, or none. "
            "materialNegative: true only if there is company-specific negative news that could change the long-term "
            "investment case, else false. "
            "nextResultsDate: the date of the next quarterly results / board meeting as YYYY-MM-DD if announced, else null."
        )
        body = {
            "model": self.settings.openai_news_model,
            "input": [
                {
                    "role": "developer",
                    "content": (
                        "You are a cautious Indian equity research assistant. "
                        "Do not invent facts. Use citations from web results. "
                        "Return only valid JSON; no markdown."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "tools": [{"type": "web_search_preview"}],
            "max_tool_calls": 5,
            "max_output_tokens": 1400,
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=75) as client:
                response = await client.post(f"{self.settings.openai_base_url}/responses", headers=headers, json=body)
            if response.is_error:
                return _empty_news(symbol, f"OpenAI news request failed: HTTP {response.status_code} {response.text[:180]}")
            payload = response.json()
        except Exception as exc:
            return _empty_news(symbol, f"OpenAI news request failed: {exc}")

        text, annotation_sources = _output_text_and_sources(payload)
        parsed = _parse_json_text(text)
        if not parsed:
            parsed = {
                "sentiment": "neutral",
                "summary": text[:800] if text else "No news summary returned.",
                "headlines": [],
                "risks": [],
            }
        headlines = _normalize_headlines(parsed.get("headlines"), annotation_sources)
        return {
            "symbol": symbol,
            "source": "openai_web_search",
            "sentiment": _sentiment(parsed.get("sentiment")),
            "summary": str(parsed.get("summary") or "No material news summary returned."),
            "headlines": headlines,
            "risks": _string_list(parsed.get("risks")),
            "negativeScope": str(parsed.get("negativeScope") or "none").lower() if str(parsed.get("negativeScope") or "none").lower() in ("company", "sector", "market", "none") else "none",
            "materialNegative": parsed.get("materialNegative") is True or str(parsed.get("materialNegative")).lower() == "true",
            "nextResultsDate": str(parsed.get("nextResultsDate"))[:10] if parsed.get("nextResultsDate") and str(parsed.get("nextResultsDate")).lower() != "null" else None,
            "sources": _sources(headlines, annotation_sources, payload.get("sources")),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "warning": None,
        }


def _empty_news(symbol: str, warning: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "source": "openai_web_search",
        "sentiment": "neutral",
        "summary": "News unavailable.",
        "headlines": [],
        "risks": [],
        "sources": [],
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "warning": warning,
    }


def _output_text_and_sources(payload: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    if payload.get("output_text"):
        return str(payload["output_text"]), []
    texts: list[str] = []
    sources: list[dict[str, str]] = []
    for item in payload.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") != "output_text":
                continue
            texts.append(str(content.get("text") or ""))
            for annotation in content.get("annotations") or []:
                url = annotation.get("url")
                if url:
                    sources.append({"url": str(url), "title": str(annotation.get("title") or url)})
    return "\n".join(texts).strip(), sources


def _parse_json_text(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _normalize_headlines(value: Any, annotation_sources: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = value if isinstance(value, list) else []
    headlines = []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        if not url and annotation_sources:
            url = annotation_sources[min(len(headlines), len(annotation_sources) - 1)].get("url") or ""
        headlines.append(
            {
                "title": title or url or "News item",
                "source": str(row.get("source") or "").strip(),
                "url": url,
                "date": str(row.get("date") or "").strip(),
                "impact": str(row.get("impact") or "").strip(),
            }
        )
    return headlines


def _sources(headlines: list[dict[str, str]], annotation_sources: list[dict[str, str]], raw_sources: Any) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    rows: list[dict[str, Any]] = []
    rows.extend(headlines)
    rows.extend(annotation_sources)
    if isinstance(raw_sources, list):
        rows.extend([row for row in raw_sources if isinstance(row, dict)])
    for row in rows:
        url = str(row.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        result.append({"url": url, "title": str(row.get("title") or row.get("source") or url)})
    return result[:8]


def _sentiment(value: Any) -> str:
    normalized = str(value or "neutral").lower()
    return normalized if normalized in {"positive", "neutral", "negative", "mixed"} else "neutral"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:5]
