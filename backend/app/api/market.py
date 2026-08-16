from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.core.config import get_settings
from app.core.timeutil import now_ist, now_ist_epoch
from app.db.sqlite import get_market_calendar, get_market_news, get_pcr_oi_session_dates, get_pcr_oi_snapshots
from app.services.app_auth import require_auth
from app.services.dhan import DhanService
from app.services.market import MarketService
from app.services.market_news import refresh_market_calendar, refresh_market_news
from app.services.pcr_oi import enrich_with_oi_regime, enrich_with_roc_and_confidence, enrich_with_signal


router = APIRouter(prefix="/market", tags=["market"])


@router.get("/candles", dependencies=[Depends(require_auth)])
async def candles(
    security_id: str = Query(alias="securityId"),
    exchange_segment: str = Query(alias="exchangeSegment"),
    instrument: str = Query(alias="instrument"),
    interval: str = Query(default="5", alias="interval"),
    session_date: str | None = Query(default=None, alias="date"),
) -> dict[str, Any]:
    """Session candles for an arbitrary tradable instrument (an option
    strike, an index, anything Dhan's /charts/intraday accepts) — unlike
    ema5_candles.py / animesh_candles.py, which hardcode the NIFTY index,
    this is a thin generic pass-through for on-demand chart views (e.g.
    Manage Trades' per-position chart). Defaults to today; an explicit
    `date` fetches a past, already-completed session instead (e.g. the
    PCR/OI panel's "Signal vs Price" chart when reviewing a prior day).
    """
    settings = get_settings()
    dhan = DhanService(settings)
    now = now_ist()
    today = now.date().isoformat()
    target_date = session_date or today
    from_date = f"{target_date} 09:15:00"
    to_date = now.strftime("%Y-%m-%d %H:%M:%S") if target_date == today else f"{target_date} 15:30:00"
    raw = await dhan.intraday_candles(
        security_id=security_id,
        exchange_segment=exchange_segment,
        instrument=instrument,
        interval=interval,
        from_date=from_date,
        to_date=to_date,
    )
    interval_minutes = int(interval)
    now_epoch = now_ist_epoch()
    completed = [c for c in raw if c["time"] + interval_minutes * 60 <= now_epoch]
    return {"candles": completed, "intervalMinutes": interval_minutes}


@router.get("/news", dependencies=[Depends(require_auth)])
async def news() -> dict[str, Any]:
    return _merged_news_payload()


@router.post("/news/refresh", dependencies=[Depends(require_auth)])
async def refresh_news() -> dict[str, Any]:
    await refresh_market_calendar()
    await refresh_market_news()
    return _merged_news_payload()


def _merged_news_payload() -> dict[str, Any]:
    """Scheduled macro events (Fed/CPI/jobs, from the calendar loop) take
    priority over reactive RSS-derived headlines, since they're the
    forward-looking gap the RSS feeds alone don't cover — reactive news
    fills whatever slots remain up to market_news_max_items total.
    """
    settings = get_settings()
    calendar_payload = get_market_calendar() or {}
    reactive_payload = get_market_news() or {}
    calendar = calendar_payload.get("items", [])
    reactive = reactive_payload.get("items", [])
    remaining = max(settings.market_news_max_items - len(calendar), 0)
    items = [*calendar, *reactive[:remaining]]
    generated_at = max((v for v in (calendar_payload.get("generatedAt"), reactive_payload.get("generatedAt")) if v), default=None)
    return {"items": items, "generatedAt": generated_at}


@router.get("/pcr-oi", dependencies=[Depends(require_auth)])
async def pcr_oi(session_date: str | None = Query(default=None, alias="date")) -> dict[str, Any]:
    resolved_date = session_date or now_ist().date().isoformat()
    snapshots = get_pcr_oi_snapshots(resolved_date)

    def _pipeline(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # oi_regime must run before signal now -- enrich_with_signal reads
        # oiRegime as an alternate trigger path (see its docstring).
        with_regime = enrich_with_oi_regime(enrich_with_roc_and_confidence(points))
        return enrich_with_signal(with_regime)

    return {
        "sessionDate": resolved_date,
        "NIFTY": _pipeline(snapshots.get("NIFTY", [])),
        "SENSEX": _pipeline(snapshots.get("SENSEX", [])),
    }


@router.get("/pcr-oi/sessions", dependencies=[Depends(require_auth)])
async def pcr_oi_sessions() -> dict[str, Any]:
    return {"dates": get_pcr_oi_session_dates()}


@router.get("/indices", dependencies=[Depends(require_auth)])
async def indices() -> dict:
    try:
        return await MarketService().indices()
    except Exception as exc:
        return {
            "source": "fallback",
            "stale": True,
            "warning": str(exc),
            "indices": [
                {"name": "Nifty 50", "lastPrice": None, "change": None, "percentChange": None},
                {"name": "Bank Nifty", "lastPrice": None, "change": None, "percentChange": None},
                {"name": "Sensex", "lastPrice": None, "change": None, "percentChange": None},
                {"name": "India VIX", "lastPrice": None, "change": None, "percentChange": None},
            ],
        }
