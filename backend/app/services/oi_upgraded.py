"""I/O orchestration for the upgraded signal engine (oi_signal_engine.py):
fetches the already-collected PCR/OI snapshots plus fresh 1-minute index
candles, and returns the enriched series. NIFTY only for this iteration --
see upgrade.md's own "we will do NIFTY only for now" scoping.

Also covers upgrade.md phase 5:
- A background logger (start/stop_oi_upgraded_task) that records each new
  poll's latest computed point to oi_upgraded_signal_log, off by default
  like every other monitor in this codebase.
- backtest_oi_upgraded(), an old-vs-new comparison over whatever session
  dates already have stored PCR/OI data. The first version of this marked
  "exit" at whatever premium was observed when the signal's own state/
  read changed -- which doesn't reflect reality: paper trading manages
  every position with its OWN staged 15%/10%/20%/5% SL/target/trail
  (paper_trading_engine.py), completely independent of the signal
  engine's hold/exit bookkeeping. That mismatch made the first backtest
  measure something that would never actually happen live. This version
  replays the real staged-exit logic against the premium path following
  each entry, using whatever SL/target/trail % paper trading is actually
  configured with, so the backtest matches what a real paper trade would
  do.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from app.core.config import Settings, get_settings
from app.core.timeutil import in_time_window, now_ist
from app.db.sqlite import get_paper_trading_settings, get_pcr_oi_session_dates, get_pcr_oi_snapshots, record_oi_upgraded_signal
from app.services import paper_trading_engine as pt_engine
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


def _new_engine_entries(enriched: list[dict]) -> list[tuple[int, str]]:
    """state == buyCe/buyPe fires exactly once per confirmed episode (the
    next poll becomes holdCe/holdPe) -- same one-shot trigger paper_trading
    actually watches for, so this naturally matches real entry frequency.
    """
    return [(i, point["state"]) for i, point in enumerate(enriched) if point["state"] in ("buyCe", "buyPe")]


def _old_engine_entries(enriched: list[dict]) -> list[tuple[int, str]]:
    """The old pipeline has no hold state -- an entry is wherever `signal`
    flips INTO buyCe/buyPe from something else.
    """
    entries: list[tuple[int, str]] = []
    prev_signal = None
    for i, point in enumerate(enriched):
        signal = point.get("signal")
        if signal in ("buyCe", "buyPe") and signal != prev_signal:
            entries.append((i, signal))
        prev_signal = signal
    return entries


def _premium_path(points_from_entry: list[dict], side: str) -> list[tuple[int, float]]:
    key = "cePremium" if side == "buyCe" else "pePremium"
    return [(p["time"], p[key]) for p in points_from_entry if p.get(key) is not None]


def _simulate_staged_exit(entry_premium: float, path: list[tuple[int, float]], cfg: dict[str, float]) -> tuple[float, int | None, str]:
    """Replays paper_trading_engine's real 3-lot staged exit (1 lot at
    target1, 1 more at target2, trail the last) against the premium path
    following an entry -- the same mechanism a real paper trade uses,
    not a proxy for it. Returns the blended %-return across all 3 lots.
    """
    levels = pt_engine.compute_levels(entry_premium, cfg["stopLossPercent"], cfg["target1Percent"], cfg["target2Percent"])
    phase: pt_engine.Phase = "OPEN_ALL"
    peak: float | None = None
    pnl_pct = 0.0
    lots_remaining = 3
    last_time = path[-1][0] if path else None

    for t, price in path:
        action = pt_engine.evaluate_paper_trade_tick(
            stop_loss=levels["stopLoss"], target1=levels["target1"], target2=levels["target2"],
            trail_percent=cfg["trailPercent"], phase=phase, peak_premium=peak, current_premium=price,
        )
        if action is None:
            continue
        leg_pct = (price - entry_premium) / entry_premium * 100
        act = action["action"]
        if act == "STOP_ALL":
            return pnl_pct + leg_pct, t, "stop_loss"
        if act == "BOOK_LOT1":
            pnl_pct += leg_pct / 3
            phase, lots_remaining = "LOT1_BOOKED", 2
        elif act == "STOP_REMAINING":
            return pnl_pct + leg_pct * lots_remaining / 3, t, "stop_loss"
        elif act == "BOOK_LOT2":
            pnl_pct += leg_pct / 3
            phase, lots_remaining, peak = "LOT2_BOOKED", 1, action["peak"]
        elif act == "EXIT_LOT3":
            return pnl_pct + leg_pct * lots_remaining / 3, t, "trail"
        elif act == "UPDATE_PEAK":
            peak = action["peak"]

    if path:
        last_price = path[-1][1]
        pnl_pct += (last_price - entry_premium) / entry_premium * 100 * lots_remaining / 3
    return pnl_pct, last_time, "eod"


def _simulate_trades(enriched: list[dict], entries: list[tuple[int, str]], cfg: dict[str, float], date: str) -> list[dict]:
    trades: list[dict] = []
    for idx, side in entries:
        entry_point = enriched[idx]
        entry_premium = entry_point.get("cePremium") if side == "buyCe" else entry_point.get("pePremium")
        if entry_premium is None:
            continue
        path = _premium_path(enriched[idx:], side)
        pnl_pct, exit_time, reason = _simulate_staged_exit(entry_premium, path, cfg)
        trades.append(
            {"date": date, "side": side, "entryTime": entry_point["time"], "exitTime": exit_time, "reason": reason, "pnlPct": pnl_pct}
        )
    return trades


def _breakdown_by(trades: list[dict], key: str) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for trade in trades:
        groups.setdefault(trade[key], []).append(trade)
    return {group_key: _summarize_trades(group_trades) for group_key, group_trades in groups.items()}


def _generate_observations(new_trades: list[dict], old_trades: list[dict]) -> list[str]:
    """Plain factual observations computed from the actual backtested
    trades -- not fitted rules, just what the data currently shows, with
    the sample-size caveat baked into the text since n is always small
    here. Forward-looking, not-yet-implemented ideas belong in the
    frontend's curated list instead -- those are judgment calls, not
    something to compute.
    """
    observations: list[str] = []
    n = len(new_trades)
    if n == 0:
        observations.append("No new-engine trades in the backtested window yet -- too little data to observe anything.")
        return observations

    losers = [t for t in new_trades if t["pnlPct"] <= 0]
    ce_trades = [t for t in new_trades if t["side"] == "buyCe"]
    pe_trades = [t for t in new_trades if t["side"] == "buyPe"]
    if losers and ce_trades and pe_trades and all(t["side"] == "buyPe" for t in losers):
        observations.append(
            f"All {len(losers)} losing trade(s) so far are PE; CE trades have been comparatively better -- "
            f"with only {n} total trades this could easily be small-sample noise, not a real CE/PE asymmetry."
        )

    stop_losses = [t for t in new_trades if t["reason"] == "stop_loss"]
    if stop_losses:
        avg_sl = sum(t["pnlPct"] for t in stop_losses) / len(stop_losses)
        observations.append(
            f"{len(stop_losses)} of {n} trade(s) hit the stop loss (avg {avg_sl:.1f}%), "
            f"vs {n - len(stop_losses)} that reached a target or EOD instead."
        )

    if old_trades:
        observations.append(
            f"The old engine took {len(old_trades)} trades in the same window vs {n} for the new engine -- "
            "the new engine trades quantity for (intended) selectivity via its persistence and score gates."
        )

    return observations


def _summarize_trades(trades: list[dict]) -> dict:
    pcts = [t["pnlPct"] for t in trades]
    wins = [p for p in pcts if p > 0]
    return {
        "count": len(trades),
        "avgPnlPct": (sum(pcts) / len(pcts)) if pcts else None,
        "winRate": (len(wins) / len(pcts) * 100) if pcts else None,
        "totalPnlPct": sum(pcts) if pcts else None,
    }


async def backtest_oi_upgraded(dates: list[str] | None = None) -> dict:
    settings = get_settings()
    now = now_ist()
    cfg = get_paper_trading_settings()
    candidate_dates = sorted(dates or get_pcr_oi_session_dates())[-BACKTEST_MAX_DAYS:]

    days: list[dict] = []
    all_new_trades: list[dict] = []
    all_old_trades: list[dict] = []
    for date in candidate_dates:
        points, candles = await _fetch_points_and_candles(settings, date, now)
        if not points:
            continue
        new_enriched = enrich_with_upgraded_signal(points, candles)
        old_enriched = enrich_with_signal(enrich_with_oi_regime(enrich_with_roc_and_confidence(points)))
        new_trades = _simulate_trades(new_enriched, _new_engine_entries(new_enriched), cfg, date)
        old_trades = _simulate_trades(old_enriched, _old_engine_entries(old_enriched), cfg, date)
        all_new_trades.extend(new_trades)
        all_old_trades.extend(old_trades)
        days.append({"date": date, "new": _summarize_trades(new_trades), "old": _summarize_trades(old_trades)})

    return {
        "days": days,
        "totals": {"new": _summarize_trades(all_new_trades), "old": _summarize_trades(all_old_trades)},
        "newTrades": all_new_trades,
        "breakdowns": {
            "bySide": _breakdown_by(all_new_trades, "side"),
            "byReason": _breakdown_by(all_new_trades, "reason"),
        },
        "observations": _generate_observations(all_new_trades, all_old_trades),
    }
