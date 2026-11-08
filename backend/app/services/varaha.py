"""Varaha: NIFTY adaptive daily strategy -- recommendation only.

At the decision time (default 15:00 IST, i.e. T-30) this takes one market
snapshot, runs the deterministic engine (varaha_engine.py), asks OpenAI to
rank the candidates that passed every hard gate, and stores the result.
Nothing here places orders or paper trades; entry and exit are manual for
now (spec: "Scope -- current phase").

A manual direction override re-evaluates the SAME stored snapshot rather
than fetching fresh data, so the recommendation stays tied to the T-30
market state.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, time as dtime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.sessions import weekday_open
from app.core.config import Settings, get_settings
from app.core.timeutil import now_ist, now_ist_epoch
from app.db import sqlite as db
from app.services import varaha_engine as engine
from app.services.dhan import DhanService

logger = logging.getLogger(__name__)

INDEX_SEGMENT = "IDX_I"
IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
SCHEDULED_RETRY_UNTIL = dtime(15, 20)
CHAIN_RANGE_PERCENT = 12.0
DAILY_HISTORY_DAYS = 120
VIX_HISTORY_DAYS = 370
MAX_AI_CANDIDATES = 20

OVERRIDE_SETTING_KEY = "direction_override"
LOTS_SETTING_KEY = "lots"
MAX_LOSS_SETTING_KEY = "max_loss_inr"
VALID_OVERRIDES = ("AUTO", "UP", "DOWN", "NO_DIRECTION")

_run_lock = asyncio.Lock()


# ------------------------------------------------------------ runtime config


def get_runtime_config() -> dict[str, Any]:
    settings = get_settings()
    lots = db.get_varaha_setting(LOTS_SETTING_KEY)
    max_loss = db.get_varaha_setting(MAX_LOSS_SETTING_KEY)
    return {
        "lots": int(lots) if lots else settings.varaha_lots,
        "maxLossInr": float(max_loss) if max_loss else settings.varaha_max_loss_inr,
        "lotSize": settings.varaha_lot_size,
        "decisionTime": settings.varaha_decision_time,
        "minDte": settings.varaha_min_dte,
        "maxDte": settings.varaha_max_dte,
        "bigMoveScore": settings.varaha_big_move_score,
        "watchScore": settings.varaha_watch_score,
        "directionConfidencePercent": settings.varaha_direction_confidence_percent,
        "minRewardRisk": settings.varaha_min_reward_risk,
        "lossWidthEmTarget": settings.varaha_loss_width_em_target,
        "aiEnabled": bool(settings.resolved_openai_api_key),
    }


def update_runtime_config(*, lots: int | None, max_loss_inr: float | None) -> dict[str, Any]:
    if lots is not None:
        db.set_varaha_setting(LOTS_SETTING_KEY, str(lots))
    if max_loss_inr is not None:
        db.set_varaha_setting(MAX_LOSS_SETTING_KEY, str(max_loss_inr))
    return get_runtime_config()


def get_override(session_date: str | None = None) -> str:
    """The override is per trading day: a value saved on an earlier date
    reads back as AUTO (spec Section 11A)."""
    raw = db.get_varaha_setting(OVERRIDE_SETTING_KEY)
    if not raw:
        return "AUTO"
    try:
        stored = json.loads(raw)
    except ValueError:
        return "AUTO"
    today = session_date or now_ist().date().isoformat()
    return stored.get("value", "AUTO") if stored.get("date") == today else "AUTO"


# ------------------------------------------------------------ snapshot


def _trading_days_until(today: date, expiry: date) -> int:
    days, cursor = 0, today
    while cursor < expiry:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days += 1
    return days


def _years_until_expiry(expiry: date) -> float:
    expiry_close = datetime.combine(expiry, MARKET_CLOSE, tzinfo=IST)
    seconds = (expiry_close - datetime.now(IST)).total_seconds()
    return max(seconds, 0.0) / (365 * 24 * 3600)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # drop NaN


def _quote(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or not payload.get("security_id"):
        return None
    greeks = payload.get("greeks") or {}
    return {
        "securityId": str(payload.get("security_id")),
        "ltp": _number(payload.get("last_price")) or 0.0,
        "bid": _number(payload.get("top_bid_price")) or None,
        "ask": _number(payload.get("top_ask_price")) or None,
        "iv": _number(payload.get("implied_volatility")) or None,
        "delta": _number(greeks.get("delta")),
        "oi": _number(payload.get("oi")),
        "volume": _number(payload.get("volume")),
    }


def _trim_chain(chain: dict[str, Any], spot: float) -> list[dict[str, Any]]:
    rows = []
    for strike_key, sides in (chain.get("oc") or {}).items():
        strike = _number(strike_key)
        if strike is None or abs(strike - spot) > spot * CHAIN_RANGE_PERCENT / 100 or not isinstance(sides, dict):
            continue
        rows.append({"strike": strike, "ce": _quote(sides.get("ce")), "pe": _quote(sides.get("pe"))})
    return sorted(rows, key=lambda r: r["strike"])


def _chain_pcr(chain: dict[str, Any]) -> float | None:
    ce_oi = pe_oi = 0.0
    for sides in (chain.get("oc") or {}).values():
        if not isinstance(sides, dict):
            continue
        ce_oi += _number((sides.get("ce") or {}).get("oi")) or 0.0
        pe_oi += _number((sides.get("pe") or {}).get("oi")) or 0.0
    return round(pe_oi / ce_oi, 3) if ce_oi else None


def _ist_date(epoch: int) -> date:
    return datetime.fromtimestamp(epoch, IST).date()


async def collect_snapshot(settings: Settings) -> dict[str, Any]:
    dhan = DhanService(settings)
    now = now_ist()
    today = now.date()
    snapshot: dict[str, Any] = {
        "takenAt": now_ist_epoch(),
        "sessionDate": today.isoformat(),
        "marketOpen": weekday_open(now) and MARKET_OPEN <= now.time() <= MARKET_CLOSE,
        "warnings": [],
    }
    nifty = settings.dhan_nifty_security_id

    # Expiries in the DTE window (spec Section 3): skip 0/1 trading days left.
    try:
        expiry_strings = await dhan.expiry_list(nifty, INDEX_SEGMENT)
    except Exception as exc:
        snapshot["error"] = f"Expiry list unavailable: {exc}"
        return snapshot
    selected: list[dict[str, Any]] = []
    for raw in expiry_strings:
        try:
            expiry = date.fromisoformat(raw)
        except ValueError:
            continue
        dte = (expiry - today).days
        trading_dte = _trading_days_until(today, expiry)
        if trading_dte < 2 or not settings.varaha_min_dte <= dte <= settings.varaha_max_dte:
            continue
        selected.append({"expiry": raw, "dte": dte, "tradingDte": trading_dte})
        if len(selected) >= settings.varaha_max_expiries:
            break

    spot = None
    pcr = None
    expiries = []
    for item in selected:
        try:
            chain = await dhan.option_chain(nifty, INDEX_SEGMENT, item["expiry"])
        except Exception as exc:
            snapshot["warnings"].append(f"Option chain for {item['expiry']} unavailable: {exc}")
            continue
        chain_spot = _number(chain.get("last_price"))
        if not chain_spot:
            continue
        spot = spot or chain_spot
        if pcr is None:
            pcr = _chain_pcr(chain)
        expiries.append({
            **item,
            "years": _years_until_expiry(date.fromisoformat(item["expiry"])),
            "chain": _trim_chain(chain, chain_spot),
        })
    snapshot["spot"] = spot
    snapshot["pcr"] = pcr
    snapshot["expiries"] = expiries
    if not selected:
        snapshot["warnings"].append(
            f"No expiry within {settings.varaha_min_dte}-{settings.varaha_max_dte} days with 2+ trading days left."
        )

    # Daily NIFTY history (excluding today) + today's intraday OHLC.
    from_date = (today - timedelta(days=DAILY_HISTORY_DAYS)).isoformat()
    to_date = (today + timedelta(days=1)).isoformat()
    try:
        daily = await dhan.historical_daily_candles(str(nifty), INDEX_SEGMENT, "INDEX", from_date, to_date)
        snapshot["daily"] = [c for c in daily if _ist_date(c["time"]) < today]
    except Exception as exc:
        snapshot["daily"] = []
        snapshot["warnings"].append(f"Daily NIFTY history unavailable: {exc}")
    try:
        intraday = await dhan.intraday_candles(str(nifty), INDEX_SEGMENT, "INDEX", "1", today.isoformat(), today.isoformat())
        intraday = sorted(intraday, key=lambda c: c["time"])
        if intraday:
            snapshot["today"] = {
                "open": intraday[0]["open"],
                "high": max(c["high"] for c in intraday),
                "low": min(c["low"] for c in intraday),
                "close": intraday[-1]["close"],
            }
    except Exception as exc:
        snapshot["warnings"].append(f"Today's intraday NIFTY data unavailable: {exc}")

    # India VIX: live quote, previous close and ~1y of closes for percentile.
    vix_id = settings.dhan_india_vix_security_id
    if vix_id:
        vix: dict[str, Any] = {}
        try:
            history = await dhan.historical_daily_candles(
                str(vix_id), INDEX_SEGMENT, "INDEX", (today - timedelta(days=VIX_HISTORY_DAYS)).isoformat(), to_date
            )
            past = [c for c in history if _ist_date(c["time"]) < today]
            vix["history"] = [c["close"] for c in past]
            vix["prevClose"] = past[-1]["close"] if past else None
        except Exception as exc:
            snapshot["warnings"].append(f"India VIX history unavailable: {exc}")
        try:
            quotes = await dhan.market_quotes_by_segment({INDEX_SEGMENT: [int(vix_id)]})
            vix["current"] = _number(((quotes.get(INDEX_SEGMENT) or {}).get(str(vix_id)) or {}).get("last_price"))
        except Exception as exc:
            snapshot["warnings"].append(f"India VIX quote unavailable: {exc}")
        snapshot["vix"] = vix

    calendar = db.get_market_calendar()
    snapshot["events"] = (calendar or {}).get("items") or []
    snapshot["eventsGeneratedAt"] = (calendar or {}).get("generatedAt")
    if not calendar:
        snapshot["warnings"].append("Event calendar unavailable -- event score counted as 0.")
    return snapshot


# ------------------------------------------------------------ AI ranking

AI_SYSTEM_PROMPT = (
    "You are the explanation and ranking layer of a deterministic NIFTY options decision engine. "
    "The engine has already classified the expected move and direction, generated candidate structures "
    "(CE Butterfly, PE Butterfly, Full Butterfly = both butterflies together, or a defined-risk iron condor), "
    "and removed every candidate that failed a hard risk gate. Your job: rank the supplied candidates and pick "
    "the best one plus up to two alternatives, then explain. Rules: choose ONLY candidate ids from the list; "
    "never invent strikes, quantities or data; do not override hard gates; treat WATCH items as trade-offs to "
    "weigh, not disqualifiers. If a manual direction override is set, say whether the engine's evidence supports "
    "it -- when overrideContradictsEngine is true, state plainly that the override goes against the engine's "
    "evidence and what that evidence was. Return a ranking with the best candidate plus up to two alternatives (three entries whenever three or more "
    "candidates are supplied). Status WATCH means the move score is elevated but NOT a confirmed big move -- say so. "
    "Use the supplied facts exactly: each candidate's `zones` list says where it makes or loses money at expiry "
    "(null bound = open-ended); expectedMove is the ATM straddle for the whole period to expiry, and "
    "emAtrRatioPerDay already normalises it to one day against ATR14 (<0.9 low, 0.9-1.2 normal, >1.2 elevated) -- "
    "never compare expectedMove to ATR14 directly. Be concise and specific (numbers, strikes). "
    "Respond with a JSON object: "
    "{\"ranking\": [{\"id\": \"<candidate id>\", \"rank\": 1, \"reason\": \"<one sentence>\"}], "
    "\"marketView\": \"...\", \"whyThisStrategy\": \"...\", \"keyStrikes\": \"...\", \"risk\": \"...\", "
    "\"expectedMove\": \"...\", \"whatCouldGoWrong\": \"...\", \"invalidation\": \"...\", "
    "\"alternative\": \"...\", \"overrideComment\": \"<empty string if no override>\"}"
)

AI_SECTION_KEYS = (
    "marketView", "whyThisStrategy", "keyStrikes", "risk", "expectedMove",
    "whatCouldGoWrong", "invalidation", "alternative", "overrideComment",
)


def _ai_payload(snapshot: dict[str, Any], result: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    move, direction = result["move"], result["direction"]
    return {
        "spot": snapshot.get("spot"),
        "decisionTime": datetime.fromtimestamp(snapshot["takenAt"], IST).strftime("%Y-%m-%d %H:%M IST"),
        "marketOpenAtSnapshot": snapshot.get("marketOpen"),
        "events": snapshot.get("events"),
        "dataWarnings": snapshot.get("warnings"),
        "move": {
            "classification": move["classification"],
            "moveScore": move["moveScore"],
            "components": [{k: c[k] for k in ("label", "score", "max", "value", "detail")} for c in move["components"]],
            "expectedMove": move.get("expectedMove"),
            "expectedMovePeriodTradingDays": (snapshot.get("expiries") or [{}])[0].get("tradingDte"),
            "atr14": move.get("atr14"),
            "emAtrRatioPerDay": move.get("emAtrRatio"),
            "vix": move.get("vix"),
            "vixPercentile": move.get("vixPercentile"),
        },
        "direction": {
            "engine": direction["classification"],
            "manualOverride": direction.get("manualOverride"),
            "effective": direction["effective"],
            "overrideContradictsEngine": bool(direction.get("manualOverride")) and direction["effective"] != direction["classification"],
            "bullishConfidence": direction["bullishConfidence"],
            "bearishConfidence": direction["bearishConfidence"],
            "signals": [{k: s[k] for k in ("label", "vote", "detail")} for s in direction["signals"]],
        },
        "status": result["status"],
        "candidates": [
            {
                "id": c["id"],
                "structure": c["structureLabel"],
                "variant": c["variantLabel"],
                "expiry": c["expiry"],
                "dte": c["dte"],
                "legs": [
                    {k: leg.get(k) for k in ("action", "qty", "optionType", "strike", "price", "delta", "iv", "distance", "distancePercent", "emMultiple")}
                    for leg in c["legs"]
                ],
                "premiumType": c["premiumType"],
                "netPremium": c["netPremium"],
                "maxProfit": c["maxProfit"],
                "maxLoss": c["maxLoss"],
                "rewardRisk": c["rewardRisk"],
                "breakevens": c["breakevens"],
                "zones": c["zones"],
                "lossWidthEmRatio": c["lossWidthEmRatio"],
                "charges": c["charges"],
                "watchItems": [f"{ch['label']}: {ch['detail']}" for ch in c["checks"] if ch["status"] == "WATCH"],
            }
            for c in candidates
        ],
    }


async def rank_with_ai(settings: Settings, snapshot: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    candidates = result["candidates"][:MAX_AI_CANDIDATES]
    api_key = settings.resolved_openai_api_key
    if not api_key:
        return {"source": "FALLBACK", "error": "OPENAI_API_KEY is not configured."}
    if not candidates:
        return {"source": "FALLBACK", "error": None}

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, timeout=90)
    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": AI_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(_ai_payload(snapshot, result, candidates), default=str)},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content if response.choices else None
        parsed = json.loads(content or "")
    except Exception as exc:
        logger.warning("varaha: AI ranking failed: %s", exc)
        return {"source": "FALLBACK", "error": f"AI ranking failed: {exc}"}

    valid_ids = {c["id"] for c in candidates}
    ranking = []
    for row in parsed.get("ranking") or []:
        if not isinstance(row, dict) or row.get("id") not in valid_ids or any(r["id"] == row["id"] for r in ranking):
            continue  # picks outside the supplied list are discarded (spec 18A)
        ranking.append({"id": row["id"], "reason": str(row.get("reason") or "").strip()})
    if not ranking:
        return {"source": "FALLBACK", "error": "AI response had no valid candidate ids."}
    return {
        "source": "AI",
        "error": None,
        "model": settings.openai_model,
        "ranking": ranking,
        "sections": {key: str(parsed.get(key) or "").strip() for key in AI_SECTION_KEYS},
    }


def _apply_ranking(result: dict[str, Any], ai: dict[str, Any], snapshot: dict[str, Any], settings: Settings) -> None:
    candidates = result["candidates"]
    by_id = {c["id"]: c for c in candidates}
    ordered: list[dict[str, Any]] = []
    for position, row in enumerate(ai.get("ranking") or [], start=1):
        candidate = by_id.get(row["id"])
        if candidate:
            candidate["aiRank"] = position
            candidate["aiReason"] = row["reason"]
            ordered.append(candidate)
    ordered += [c for c in candidates if c not in ordered]  # rest keep fallback order
    result["candidates"] = ordered
    result["rankingSource"] = ai["source"]
    result["ai"] = {k: ai.get(k) for k in ("source", "error", "model", "sections")}

    top_n = settings.varaha_ai_top_n
    spot = float(snapshot["spot"])
    for candidate in ordered[:top_n]:
        candidate["payoff"] = engine.payoff_curve(
            candidate, spot, candidate["lotSize"], candidate["lots"], (result.get("move") or {}).get("expectedMove")
        )
    result["topIds"] = [c["id"] for c in ordered[:top_n]]


# ------------------------------------------------------------ orchestration


async def _evaluate_and_store(
    settings: Settings, snapshot: dict[str, Any], *, trigger: str, override: str
) -> dict[str, Any]:
    snapshot["config"] = {k: v for k, v in get_runtime_config().items() if k in ("lots", "maxLossInr")}
    result = engine.evaluate(snapshot, None if override == "AUTO" else override, settings)
    if result["candidates"]:
        ai = await rank_with_ai(settings, snapshot, result)
    else:
        ai = {"source": "FALLBACK", "error": None}
    if result.get("move"):
        _apply_ranking(result, ai, snapshot, settings)
    else:
        result["ai"] = {"source": ai["source"], "error": ai.get("error"), "sections": None}
    result["spot"] = snapshot.get("spot")
    result["takenAt"] = snapshot.get("takenAt")
    result["marketOpen"] = snapshot.get("marketOpen")
    result["warnings"] = snapshot.get("warnings") or []
    result["expiries"] = [
        {k: e[k] for k in ("expiry", "dte", "tradingDte")} for e in snapshot.get("expiries") or []
    ]
    result["pcr"] = snapshot.get("pcr")
    result["events"] = snapshot.get("events") or []
    result["requestedOverride"] = override
    row_id = db.save_varaha_recommendation(
        session_date=snapshot["sessionDate"], trigger=trigger,
        manual_override=None if override == "AUTO" else override, snapshot=snapshot, result=result,
    )
    logger.info("varaha: stored recommendation #%s (%s, %s)", row_id, trigger, result["status"])
    return db.get_latest_varaha_recommendation(snapshot["sessionDate"]) or {}


async def run_recommendation(trigger: str = "manual") -> dict[str, Any]:
    """Fresh snapshot + full evaluation. trigger: scheduled | manual."""
    settings = get_settings()
    async with _run_lock:
        snapshot = await collect_snapshot(settings)
        if trigger == "scheduled" and not snapshot.get("spot") and now_ist().time() < SCHEDULED_RETRY_UNTIL:
            # Don't burn the day's scheduled run on a transient Dhan failure;
            # the loop retries every 30s until SCHEDULED_RETRY_UNTIL.
            raise RuntimeError(snapshot.get("error") or "; ".join(snapshot.get("warnings") or []) or "no market data")
        return await _evaluate_and_store(settings, snapshot, trigger=trigger, override=get_override(snapshot["sessionDate"]))


async def set_override(value: str) -> dict[str, Any]:
    """Saves today's override and re-evaluates today's stored snapshot (or
    takes a fresh one if nothing has run today yet)."""
    if value not in VALID_OVERRIDES:
        raise ValueError(f"override must be one of {VALID_OVERRIDES}")
    settings = get_settings()
    today = now_ist().date().isoformat()
    db.set_varaha_setting(OVERRIDE_SETTING_KEY, json.dumps({"date": today, "value": value}))
    async with _run_lock:
        latest = db.get_latest_varaha_recommendation(today, include_snapshot=True)
        if latest and latest.get("snapshot", {}).get("spot"):
            return await _evaluate_and_store(settings, latest["snapshot"], trigger="override", override=value)
        snapshot = await collect_snapshot(settings)
        return await _evaluate_and_store(settings, snapshot, trigger="override", override=value)


def get_latest() -> dict[str, Any] | None:
    today = now_ist().date().isoformat()
    return db.get_latest_varaha_recommendation(today) or db.get_latest_varaha_recommendation()


# ------------------------------------------------------------ scheduler


def start_varaha_task() -> asyncio.Task | None:
    if not get_settings().varaha_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_varaha_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


def _parse_hhmm(value: str) -> dtime:
    hour, minute = value.split(":")
    return dtime(int(hour), int(minute))


async def _loop() -> None:
    while True:
        try:
            settings = get_settings()
            now = now_ist()
            today = now.date().isoformat()
            decision = _parse_hhmm(settings.varaha_decision_time)
            if (
                settings.varaha_monitor_enabled
                and weekday_open(now)
                and decision <= now.time() < MARKET_CLOSE
                and not db.has_varaha_scheduled_run(today)
            ):
                await run_recommendation("scheduled")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("varaha: scheduled run failed")
        await asyncio.sleep(30)
