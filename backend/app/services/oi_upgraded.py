"""I/O orchestration for the upgraded signal engine (oi_signal_engine.py):
fetches the already-collected PCR/OI snapshots plus fresh 1-minute index
candles, and returns the enriched series. NIFTY only for this iteration --
see upgrade.md's own "we will do NIFTY only for now" scoping.

Also covers upgrade.md phase 5:
- A background logger (start/stop_oi_upgraded_task) that records each new
  poll's latest computed point to oi_upgraded_signal_log, off by default
  like every other monitor in this codebase.
- backtest_oi_upgraded(), a rough old-vs-new comparison over whatever
  session dates already have stored PCR/OI data. "Rough" because it marks
  entry/exit at the ATM premium observed at the poll where the state
  changes rather than replaying paper_trading_engine's actual staged
  SL/target/trail exits -- good enough to sanity-check whether the new
  engine is directionally better than the old one, not a substitute for
  real paper-trade P&L.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from app.core.config import Settings, get_settings
from app.core.timeutil import in_time_window, now_ist
from app.db.sqlite import get_pcr_oi_session_dates, get_pcr_oi_snapshots, record_oi_upgraded_signal
from app.services.dhan import DhanService
from app.services.oi_signal_engine import enrich_with_upgraded_signal
from app.services.pcr_oi import enrich_with_oi_regime, enrich_with_roc_and_confidence, enrich_with_signal

INDEX_SEGMENT = "IDX_I"
BACKTEST_MAX_DAYS = 10


async def _fetch_points_and_candles(settings: Settings, resolved_date: str, now: datetime) -> tuple[list[dict], list[dict]]:
    points = get_pcr_oi_snapshots(resolved_date).get("NIFTY", [])
    if not points:
        return [], []
    today = now.date().isoformat()
    dhan = DhanService(settings)
    from_date = f"{resolved_date} 09:15:00"
    to_date = now.strftime("%Y-%m-%d %H:%M:%S") if resolved_date == today else f"{resolved_date} 15:30:00"
    try:
        candles = await dhan.intraday_candles(
            security_id=settings.dhan_nifty_security_id,
            exchange_segment=INDEX_SEGMENT,
            instrument="INDEX",
            interval="1",
            from_date=from_date,
            to_date=to_date,
        )
    except Exception:
        candles = []
    return points, candles


async def get_upgraded_nifty_signal(session_date: str | None = None) -> list[dict]:
    settings = get_settings()
    now = now_ist()
    resolved_date = session_date or now.date().isoformat()
    points, candles = await _fetch_points_and_candles(settings, resolved_date, now)
    if not points:
        return []
    return enrich_with_upgraded_signal(points, candles)


def start_oi_upgraded_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.oi_upgraded_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_oi_upgraded_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def _loop() -> None:
    settings = get_settings()
    interval = max(settings.oi_upgraded_poll_interval_seconds, 30)
    while True:
        try:
            now = now_ist()
            in_hours = in_time_window(
                now.time(), settings.oi_upgraded_session_start_time, settings.oi_upgraded_session_end_time
            )
            if in_hours and now.weekday() < 5:
                await _log_latest_point(now)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(interval)


async def _log_latest_point(now: datetime) -> None:
    session_date = now.date().isoformat()
    enriched = await get_upgraded_nifty_signal(session_date)
    if not enriched:
        return
    latest = enriched[-1]
    record_oi_upgraded_signal(
        session_date=session_date,
        epoch=latest["time"],
        state=latest["state"],
        signal=latest["signal"],
        regime=latest["regime"],
        pcr=latest.get("pcr"),
        ce_score=latest["ceScore"],
        pe_score=latest["peScore"],
        persistence=latest["persistence"],
        nifty_price=latest.get("niftyPrice"),
        vwap=latest.get("vwap"),
        ce_premium=latest.get("cePremium"),
        pe_premium=latest.get("pePremium"),
    )


def _new_engine_events(enriched: list[dict]) -> list[dict]:
    """Each BUY trigger through however long HOLD lasts counts as one
    episode -- the closest a pure historical replay can get to "one
    simulated trade" without re-running paper_trading_engine's actual
    staged exits.
    """
    events: list[dict] = []
    i, n = 0, len(enriched)
    while i < n:
        point = enriched[i]
        if point["state"] in ("buyCe", "buyPe"):
            side = point["state"]
            entry_premium = point.get("cePremium") if side == "buyCe" else point.get("pePremium")
            j = i + 1
            while j < n and enriched[j]["state"] in ("holdCe", "holdPe"):
                j += 1
            exit_point = enriched[j - 1]
            exit_premium = exit_point.get("cePremium") if side == "buyCe" else exit_point.get("pePremium")
            events.append(
                {
                    "side": side,
                    "entryTime": point["time"],
                    "entryPremium": entry_premium,
                    "exitTime": exit_point["time"],
                    "exitPremium": exit_premium,
                    "open": j >= n,
                }
            )
            i = j
        else:
            i += 1
    return events


def _old_engine_events(enriched: list[dict]) -> list[dict]:
    """The old pipeline has no hold/exit state of its own -- an "episode"
    here is just a run of consecutive polls reporting the same signal.
    """
    events: list[dict] = []
    i, n = 0, len(enriched)
    while i < n:
        point = enriched[i]
        side = point.get("signal")
        if side in ("buyCe", "buyPe"):
            entry_premium = point.get("cePremium") if side == "buyCe" else point.get("pePremium")
            j = i + 1
            while j < n and enriched[j].get("signal") == side:
                j += 1
            exit_point = enriched[j - 1]
            exit_premium = exit_point.get("cePremium") if side == "buyCe" else exit_point.get("pePremium")
            events.append(
                {
                    "side": side,
                    "entryTime": point["time"],
                    "entryPremium": entry_premium,
                    "exitTime": exit_point["time"],
                    "exitPremium": exit_premium,
                    "open": j >= n,
                }
            )
            i = j
        else:
            i += 1
    return events


def _summarize_events(events: list[dict]) -> dict:
    points_list = [
        e["exitPremium"] - e["entryPremium"] for e in events if e["entryPremium"] is not None and e["exitPremium"] is not None
    ]
    wins = [p for p in points_list if p > 0]
    return {
        "count": len(events),
        "avgPoints": (sum(points_list) / len(points_list)) if points_list else None,
        "winRate": (len(wins) / len(points_list) * 100) if points_list else None,
        "totalPoints": sum(points_list) if points_list else None,
    }


async def backtest_oi_upgraded(dates: list[str] | None = None) -> dict:
    settings = get_settings()
    now = now_ist()
    candidate_dates = sorted(dates or get_pcr_oi_session_dates())[-BACKTEST_MAX_DAYS:]

    days: list[dict] = []
    all_new_events: list[dict] = []
    all_old_events: list[dict] = []
    for date in candidate_dates:
        points, candles = await _fetch_points_and_candles(settings, date, now)
        if not points:
            continue
        new_enriched = enrich_with_upgraded_signal(points, candles)
        old_enriched = enrich_with_signal(enrich_with_oi_regime(enrich_with_roc_and_confidence(points)))
        new_events = _new_engine_events(new_enriched)
        old_events = _old_engine_events(old_enriched)
        all_new_events.extend(new_events)
        all_old_events.extend(old_events)
        days.append({"date": date, "new": _summarize_events(new_events), "old": _summarize_events(old_events)})

    return {
        "days": days,
        "totals": {"new": _summarize_events(all_new_events), "old": _summarize_events(all_old_events)},
    }
