"""LLM-backed conversational assistant, app-wide: live positions/P&L
(trades.py), PCR/OI/VIX/IV for NIFTY + SENSEX (pcr_oi.py's own enrichment
pipeline -- same data /api/market/pcr-oi already returns), and the
upgraded NIFTY signal engine's current call (oi_upgraded.py). Read-only:
answers questions about this live data, never places or modifies an
order -- there is no such code path here, by design, matching every
other "paper"/advisory surface in this codebase.

Context is trimmed to the latest point + a short recent trend per
underlying rather than the full session, to keep prompts small -- the
enrichment pipelines already compute roc/confidence/signal/regime on
each point, so the tail of the array already carries the "how did we
get here" signal without needing the whole day.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.core.config import get_settings
from app.core.timeutil import now_ist
from app.db.sqlite import get_pcr_oi_snapshots
from app.services.oi_upgraded import get_upgraded_nifty_signal
from app.services.pcr_oi import enrich_with_oi_regime, enrich_with_roc_and_confidence, enrich_with_signal
from app.services.trades import live_trade_snapshot

SYSTEM_PROMPT = """You are a read-only trading assistant embedded in "Live Options", a personal Dhan index-options dashboard. You answer questions using ONLY the live JSON context supplied in the next message -- never invent numbers that aren't there, and say so plainly if the context doesn't cover what's being asked.

You can discuss current P&L/positions, and reason about PCR/OI/VIX/IV plus the upgraded NIFTY signal engine's current call (state/score/reasons) for "should I buy/sell CE/PE" style questions.

Ground rules:
- You are advisory only. You cannot and must not claim to place, modify, or close any order -- if asked to actually do something, say the user needs to do that themselves in the app.
- Be concise and concrete: cite the specific numbers from context that support your answer (e.g. "PCR is 0.65 and rising, CE OI is unwinding, NIFTY is above VWAP...").
- If the upgraded engine's NIFTY signal is NO TRADE, say so plainly and explain the strongest reason(s) it isn't confirming, rather than inventing a call it isn't making.
- SENSEX has no upgraded signal engine yet -- only raw PCR/OI/VIX/IV -- so be more hedged on SENSEX calls and say so explicitly.
- Never claim certainty. This is a heuristic read of live data, not a guarantee, and past behavior of these signals is not a promise of future results.
"""

HISTORY_TURN_LIMIT = 10
TREND_POINTS = 8

_SNAPSHOT_FIELDS = (
    "time", "pcr", "ceOiChange", "peOiChange", "atmStrike", "cePremium", "ceIv",
    "pePremium", "peIv", "indiaVix", "signal", "signalConfidence", "oiRegime",
)
_TRADE_FIELDS = (
    "symbol", "tradingSymbol", "optionSide", "strikePrice", "expiry", "side", "qty",
    "avgPrice", "ltp", "openPnl", "realizedPnl", "dayPnl", "status",
)
_UPGRADED_FIELDS = ("state", "signal", "regime", "ceScore", "peScore", "persistence", "niftyPrice", "vwap", "reasons")


def _trim(point: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {k: point.get(k) for k in fields if k in point}


async def _build_context(now: datetime) -> dict[str, Any]:
    session_date = now.date().isoformat()

    positions = await live_trade_snapshot()
    positions_context = {
        "summary": positions.get("summary"),
        "open": [_trim(t, _TRADE_FIELDS) for t in positions.get("groups", {}).get("options", [])],
    }

    snapshots = get_pcr_oi_snapshots(session_date)

    def _pipeline(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with_regime = enrich_with_oi_regime(enrich_with_roc_and_confidence(points))
        return enrich_with_signal(with_regime)

    nifty_points = _pipeline(snapshots.get("NIFTY", []))
    sensex_points = _pipeline(snapshots.get("SENSEX", []))

    try:
        nifty_upgraded = await get_upgraded_nifty_signal(session_date)
    except Exception:
        nifty_upgraded = []

    return {
        "nowIst": now.strftime("%Y-%m-%d %H:%M:%S"),
        "positions": positions_context,
        "nifty": {
            "latest": _trim(nifty_points[-1], _SNAPSHOT_FIELDS) if nifty_points else None,
            "recentTrend": [_trim(p, _SNAPSHOT_FIELDS) for p in nifty_points[-TREND_POINTS:]],
            "upgradedSignal": _trim(nifty_upgraded[-1], _UPGRADED_FIELDS) if nifty_upgraded else None,
        },
        "sensex": {
            "latest": _trim(sensex_points[-1], _SNAPSHOT_FIELDS) if sensex_points else None,
            "recentTrend": [_trim(p, _SNAPSHOT_FIELDS) for p in sensex_points[-TREND_POINTS:]],
        },
    }


async def ask_assistant(question: str, history: list[dict[str, str]]) -> str:
    settings = get_settings()
    if not settings.openai_api_key:
        return "The assistant isn't configured yet -- no OpenAI API key is set on the server."

    from openai import AsyncOpenAI

    context = await _build_context(now_ist())

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Live context (JSON): {json.dumps(context, default=str)}"},
    ]
    messages.extend(history[-HISTORY_TURN_LIMIT:])
    messages.append({"role": "user", "content": question})

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        response = await client.chat.completions.create(model=settings.openai_model, messages=messages, temperature=0.3)
    except Exception as exc:
        return f"Sorry, I couldn't reach the assistant right now ({exc})."

    reply = response.choices[0].message.content
    return reply or "I couldn't generate a response."
