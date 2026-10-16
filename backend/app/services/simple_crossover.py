"""NIFTY Simple Cross Over paper strategy.

Entries are direction-gated EMA8/EMA21 cross-overs. Three lots scale out at
5% and 10%; the last lot trails in 5% steps. Open lots also have a
configurable fixed stop until trailing starts, a cross-under exit, and a
mandatory 15:30 square-off. This engine is paper-only.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import time as dtime
from typing import Any, Literal

from app.core.config import Settings, get_settings
from app.core.timeutil import in_time_window, now_ist, now_ist_epoch
from app.db import sqlite as db
from app.services.crypto_indicators import ema, rsi
from app.services.charges import option_order_charges
from app.services.dhan import DhanService
from app.services.ema5_instruments import resolve_atm_option, resolve_next_expiry

logger = logging.getLogger(__name__)

OPTION_SEGMENT = "NSE_FNO"
INDEX_SEGMENT = "IDX_I"
STRIKE_STEP = 50.0
EMA_FAST_PERIOD = 8
EMA_SLOW_PERIOD = 21
RSI_PERIOD = 8
RSI_SMA_PERIOD = 5
GAP_TREND_LOOKBACK = 3
# How many candles before the just-closed one _evaluate_entry may still act
# on. 0 = only the just-closed candle.
RECENT_CROSSOVER_LOOKBACK_CANDLES = 0
# 16 Oct 2026: the lookback used to be 5 candles, which let a crossover that
# happened while the day-direction gate was closed (Sideways) be bought
# minutes later when the gate opened -- 3-4 candles late and ~4% higher.
# Now only the just-closed candle can trigger (it is still seen by all four
# polls of its minute), and an entry is skipped if the live price has already
# run more than ENTRY_CHASE_LIMIT_PERCENT above the signal candle's close.
ENTRY_CHASE_LIMIT_PERCENT = 2.0
# Net NIFTY move from today's open beyond this % counts as a trending day;
# inside it is Sideways. This replaced an earlier version that reused OI
# Upgraded's `regime` field -- that's a point-in-time sanity check (its own
# tooltip says as much: "does NOT block a trade by itself"), not a day-level
# read, and flickered between Sideways/trending within the same clearly
# one-directional day. A day's own open-to-now price change is a much more
# direct answer to "is today bearish or bullish."
DAY_DIRECTION_THRESHOLD_PERCENT = 0.3
PAPER_LOTS = 3
NIFTY_LOT_SIZE = 65
FIRST_TARGET_PERCENT = 5.0
SECOND_TARGET_PERCENT = 10.0
TRAIL_STEP_PERCENT = 5.0

Side = Literal["CE", "PE"]
SIDES: tuple[Side, ...] = ("CE", "PE")

# Runtime-toggleable, DB-backed (pe_ce_crossover's filter-toggle pattern),
# editable from the UI without a backend restart. Default ON (unset ==
# enabled) so deploying this doesn't change today's live behavior. When
# off, both CE and PE are evaluated independently every tick -- whichever
# side's own crossover condition is satisfied enters, Sideways days no
# longer block anything either. Day direction is still computed and tagged
# on the trade either way, just not used to gate which side gets checked.
DAY_DIRECTION_FILTER_SETTING_KEY = "day_direction_filter_enabled"

# Only meaningful when the day-direction filter above is ON. Default OFF
# (unset == disabled) so deploying this doesn't change today's live
# behavior -- Sideways days still take no entries unless explicitly turned
# on here, in which case both CE and PE are evaluated independently on
# Sideways days only (Up/Down days still gate to a single side).
TRADE_ON_SIDEWAYS_SETTING_KEY = "trade_on_sideways"

STOP_LOSS_PERCENT_SETTING_KEY = "stop_loss_percent"

# Plain cross over: when ON, trades exit ONLY on the cross-under (or the
# mandatory 15:30 square-off) -- no stop loss, no staged targets, no
# trailing. Entries still follow the day-direction settings. Each trade stores the flag (and a "Plain cross over"
# comment), so changing the setting never changes an open trade's rules.
PLAIN_CROSSOVER_SETTING_KEY = "plain_crossover"
# Plain cross over profit target: book the whole position once the premium is
# this % above entry (0 = off, exit only on the cross-under). Stored on each
# trade at entry. Default 3% from the 16 Oct 2026 review of trades #80-#100.
PLAIN_TARGET_PERCENT_SETTING_KEY = "plain_target_percent"
DEFAULT_PLAIN_TARGET_PERCENT = 3.0

# Candle timeframe for the EMA8/EMA21 crossover. Dhan's intraday API has no
# 3-minute interval, so 3m candles are built from 1m candles, aligned to the
# 09:15 IST session open (09:15-09:18, 09:18-09:21, ...). Each trade stores
# the timeframe it entered on and its cross-under exit keeps using that one,
# even if the setting is changed while it's open.
TIMEFRAME_SETTING_KEY = "timeframe_minutes"
ALLOWED_TIMEFRAMES = (1, 3)
SESSION_OPEN_MINUTE_IST = 9 * 60 + 15
IST_OFFSET_SECONDS = 19800

_handled_crossover_time: dict[Side, int | None] = {}
_handled_date: str | None = None

# Timing: checks run a couple of seconds after each minute closes (and every
# 15 s after that for stops/targets) instead of a free-running 30 s loop.
# The just-closed minute is taken from the live price when Dhan's 1-min
# candle hasn't been published yet, so a crossover is acted on within
# seconds of the candle close rather than one or two candles later.
POLL_OFFSETS_SECONDS = (2, 17, 32, 47)
LIVE_CLOSE_MAX_AGE_SECONDS = 20
QUOTE_MAX_AGE_SECONDS = 2.0
OPTION_CACHE_SECONDS = 60
EXPIRY_CACHE_SECONDS = 1800
_expiry_cache: dict[str, Any] = {"at": 0.0, "expiry": None}
_option_cache: dict[str, tuple[float, dict[str, Any]]] = {}


async def _cached_expiry(dhan: DhanService, settings: Settings) -> str | None:
    if _expiry_cache["expiry"] and time.monotonic() - _expiry_cache["at"] < EXPIRY_CACHE_SECONDS:
        return _expiry_cache["expiry"]
    expiry = await resolve_next_expiry(dhan, settings.dhan_nifty_security_id)
    if expiry:
        _expiry_cache.update(at=time.monotonic(), expiry=expiry)
    return expiry


async def _cached_atm_option(dhan: DhanService, settings: Settings, expiry: str, side: Side) -> dict[str, Any] | None:
    """The ATM option per side, re-read from the (rate-limited) chain at most
    once a minute -- shared by the monitor and the chart."""
    key = f"{expiry}:{side}"
    cached = _option_cache.get(key)
    if cached and time.monotonic() - cached[0] < OPTION_CACHE_SECONDS:
        return cached[1]
    option = await resolve_atm_option(
        dhan, underlying_scrip=settings.dhan_nifty_security_id, expiry=expiry, side=side, strike_step=STRIKE_STEP
    )
    if option:
        _option_cache[key] = (time.monotonic(), option)
    return option


async def _live_price(dhan: DhanService, security_id: str) -> float | None:
    quotes = await dhan.market_quotes_by_segment({OPTION_SEGMENT: [int(security_id)]}, max_age_seconds=QUOTE_MAX_AGE_SECONDS)
    value = (quotes.get(OPTION_SEGMENT) or {}).get(str(security_id), {}).get("last_price")
    return float(value) if value else None


def _seconds_to_next_poll(now_epoch: float) -> float:
    second = now_epoch % 60
    for offset in POLL_OFFSETS_SECONDS:
        if second < offset - 0.05:
            return offset - second
    return 60 - second + POLL_OFFSETS_SECONDS[0]


def is_day_direction_filter_enabled() -> bool:
    raw = db.get_simple_crossover_setting(DAY_DIRECTION_FILTER_SETTING_KEY)
    return True if raw is None else raw == "1"


def set_day_direction_filter_enabled(value: bool) -> None:
    db.set_simple_crossover_setting(DAY_DIRECTION_FILTER_SETTING_KEY, "1" if value else "0")


def is_trade_on_sideways_enabled() -> bool:
    raw = db.get_simple_crossover_setting(TRADE_ON_SIDEWAYS_SETTING_KEY)
    return raw == "1"


def set_trade_on_sideways_enabled(value: bool) -> None:
    db.set_simple_crossover_setting(TRADE_ON_SIDEWAYS_SETTING_KEY, "1" if value else "0")


def is_plain_crossover_enabled() -> bool:
    return db.get_simple_crossover_setting(PLAIN_CROSSOVER_SETTING_KEY) == "1"


def set_plain_crossover_enabled(value: bool) -> None:
    db.set_simple_crossover_setting(PLAIN_CROSSOVER_SETTING_KEY, "1" if value else "0")


def get_plain_target_percent() -> float:
    raw = db.get_simple_crossover_setting(PLAIN_TARGET_PERCENT_SETTING_KEY)
    return float(raw) if raw is not None else DEFAULT_PLAIN_TARGET_PERCENT


def set_plain_target_percent(value: float) -> None:
    if not 0 <= value <= 100:
        raise ValueError("plain target % must be between 0 and 100")
    db.set_simple_crossover_setting(PLAIN_TARGET_PERCENT_SETTING_KEY, str(value))


def get_stop_loss_percent() -> float:
    raw = db.get_simple_crossover_setting(STOP_LOSS_PERCENT_SETTING_KEY)
    return float(raw) if raw is not None else get_settings().simple_crossover_stop_loss_percent


def set_stop_loss_percent(value: float) -> None:
    db.set_simple_crossover_setting(STOP_LOSS_PERCENT_SETTING_KEY, str(value))


def get_timeframe_minutes() -> int:
    raw = db.get_simple_crossover_setting(TIMEFRAME_SETTING_KEY)
    value = int(raw) if raw and raw.isdigit() else 1
    return value if value in ALLOWED_TIMEFRAMES else 1


def set_timeframe_minutes(value: int) -> None:
    if value not in ALLOWED_TIMEFRAMES:
        raise ValueError(f"timeframe must be one of {ALLOWED_TIMEFRAMES}")
    db.set_simple_crossover_setting(TIMEFRAME_SETTING_KEY, str(value))


def get_runtime_config() -> dict[str, Any]:
    return {
        "dayDirectionFilterEnabled": is_day_direction_filter_enabled(),
        "tradeOnSideways": is_trade_on_sideways_enabled(),
        "stopLossPercent": get_stop_loss_percent(),
        "timeframeMinutes": get_timeframe_minutes(),
        "plainCrossover": is_plain_crossover_enabled(),
        "plainTargetPercent": get_plain_target_percent(),
    }


def resample_candles(candles: list[dict[str, Any]], minutes: int) -> list[dict[str, Any]]:
    """1m candles -> `minutes` candles aligned to the 09:15 IST open. Each
    output candle's time is its bucket start."""
    ordered = sorted(candles, key=lambda c: int(c["time"]))
    if minutes <= 1:
        return ordered
    buckets: dict[int, list[dict[str, Any]]] = {}
    for candle in ordered:
        t = int(candle["time"])
        minute_of_day = ((t + IST_OFFSET_SECONDS) // 60) % 1440
        start = t - ((minute_of_day - SESSION_OPEN_MINUTE_IST) % minutes) * 60
        buckets.setdefault(start, []).append(candle)
    return [
        {
            "time": start,
            "open": chunk[0]["open"],
            "high": max(float(c["high"]) for c in chunk),
            "low": min(float(c["low"]) for c in chunk),
            "close": chunk[-1]["close"],
        }
        for start, chunk in sorted(buckets.items())
    ]


def _apply_paper_charges(trade: dict[str, Any], settings: Settings) -> None:
    """Calculate entry, recorded partial-exit, and remaining-position charges."""
    lot_size = int(trade["lotSize"])
    quantity = int(trade["lots"]) * lot_size
    entry_charges = option_order_charges(
        premium=trade["entryPremium"],
        quantity=quantity,
        side="BUY",
        exchange_segment=trade["exchangeSegment"],
        settings=settings,
    )
    exit_legs = trade.get("exitLegs") or []
    actual_exit_charges = sum(
        option_order_charges(
            premium=float(leg["exitPremium"]),
            quantity=int(leg["lots"]) * lot_size,
            side="SELL",
            exchange_segment=trade["exchangeSegment"],
            settings=settings,
        )["total"]
        for leg in exit_legs
    )
    if trade["status"] == "closed" and not exit_legs and trade.get("exitPremium") is not None:
        actual_exit_charges = option_order_charges(
            premium=trade["exitPremium"], quantity=quantity, side="SELL",
            exchange_segment=trade["exchangeSegment"], settings=settings,
        )["total"]

    remaining_lots = int(trade.get("remainingLots") or 0) if trade["status"] == "open" else 0
    exit_estimate = 0.0
    if remaining_lots:
        exit_estimate = option_order_charges(
            premium=trade["currentPremium"] or trade["entryPremium"],
            quantity=remaining_lots * lot_size,
            side="SELL",
            exchange_segment=trade["exchangeSegment"],
            settings=settings,
        )["total"]
    total = round(entry_charges["total"] + actual_exit_charges + exit_estimate, 2)
    trade["charges"] = total
    trade["stopLossPercent"] = get_stop_loss_percent()
    trade["stopLossPrice"] = round(
        trade["entryPremium"] * (1 - trade["stopLossPercent"] / 100), 4
    )
    trade["remainingQuantity"] = remaining_lots * lot_size

    if trade["status"] == "closed":
        trade["netPnl"] = round((trade["realizedPnl"] or 0) - total, 2)
    else:
        unrealized = (
            (trade["currentPremium"] - trade["entryPremium"]) * remaining_lots * lot_size
            if trade["currentPremium"] is not None
            else 0.0
        )
        trade["unrealizedPnl"] = round(unrealized, 2)
        trade["netPnl"] = round((trade["realizedPnl"] or 0) + unrealized - total, 2)


def list_trades_with_charges() -> list[dict[str, Any]]:
    settings = get_settings()
    trades = db.list_simple_crossover_trades()
    for trade in trades:
        _apply_paper_charges(trade, settings)
    return trades


def sma(values: list[float | None], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    window: list[float] = []
    for i, v in enumerate(values):
        if v is None:
            window = []
            continue
        window.append(v)
        if len(window) > period:
            window.pop(0)
        if len(window) == period:
            result[i] = sum(window) / period
    return result


def detect_crossovers(
    times: list[int], closes: list[float], ema_fast: list[float | None], ema_slow: list[float | None], rsi_values: list[float | None]
) -> list[dict[str, Any]]:
    crossovers: list[dict[str, Any]] = []
    for i in range(1, len(times)):
        f0, s0, f1, s1 = ema_fast[i - 1], ema_slow[i - 1], ema_fast[i], ema_slow[i]
        if f0 is None or s0 is None or f1 is None or s1 is None:
            continue
        if f0 <= s0 and f1 > s1:
            direction = "up"
        elif f0 >= s0 and f1 < s1:
            direction = "down"
        else:
            continue
        crossovers.append({"time": times[i], "price": closes[i], "direction": direction, "rsi": rsi_values[i]})
    return crossovers


def touched_or_close_to_crossover(candle: dict[str, Any], ema_slow: float, max_gap_percent: float) -> bool:
    """XAUT-only entry helper; NIFTY entries do not apply this filter."""
    if ema_slow <= 0:
        return False
    touched = float(candle["low"]) <= ema_slow <= float(candle["high"])
    close_gap_percent = abs(float(candle["close"]) - ema_slow) / ema_slow * 100
    return touched or close_gap_percent <= max_gap_percent


def gap_series(ema_fast: list[float | None], ema_slow: list[float | None]) -> list[float | None]:
    return [(f - s) if f is not None and s is not None else None for f, s in zip(ema_fast, ema_slow)]


def gap_trend(gaps: list[float | None]) -> tuple[float | None, str | None]:
    current_gap = gaps[-1] if gaps else None
    recent = [g for g in gaps[-(GAP_TREND_LOOKBACK + 1):] if g is not None]
    if len(recent) < 2:
        return current_gap, None
    deltas = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
    avg_delta = sum(deltas) / len(deltas)
    trend = "increasing" if avg_delta > 0 else "decreasing" if avg_delta < 0 else "flat"
    return current_gap, trend


async def _day_direction(dhan: DhanService, settings: Settings, today: str) -> dict[str, Any] | None:
    try:
        raw = await dhan.intraday_candles(settings.dhan_nifty_security_id, INDEX_SEGMENT, "INDEX", "1", today, today)
    except Exception:
        return None
    if not raw:
        return None
    ordered = sorted(raw, key=lambda c: c["time"])
    day_open = float(ordered[0]["open"])
    current = float(ordered[-1]["close"])
    if not day_open:
        return None
    change_percent = (current - day_open) / day_open * 100
    if change_percent >= DAY_DIRECTION_THRESHOLD_PERCENT:
        label = "Up"
    elif change_percent <= -DAY_DIRECTION_THRESHOLD_PERCENT:
        label = "Down"
    else:
        label = "Sideways"
    return {"label": label, "changePercent": round(change_percent, 2), "dayOpen": day_open, "current": current}


async def get_data(side: Side) -> dict[str, Any]:
    settings = get_settings()
    dhan = DhanService()

    expiry = await _cached_expiry(dhan, settings)
    if not expiry:
        return {"error": "no valid expiry available", "candles": []}

    option = await _cached_atm_option(dhan, settings, expiry, side)
    if not option:
        return {"error": "ATM option chain data unavailable", "candles": []}

    today = now_ist().date().isoformat()
    try:
        raw = await dhan.intraday_candles(option["securityId"], OPTION_SEGMENT, "OPTIDX", "1", today, today)
    except Exception as exc:
        return {"error": str(exc), "candles": []}

    timeframe = get_timeframe_minutes()
    ordered = resample_candles(raw, timeframe)
    times = [int(c["time"]) for c in ordered]
    closes = [float(c["close"]) for c in ordered]

    ema_fast = ema(closes, EMA_FAST_PERIOD)
    ema_slow = ema(closes, EMA_SLOW_PERIOD)
    rsi_values = rsi(closes, RSI_PERIOD)
    rsi_sma_values = sma(rsi_values, RSI_SMA_PERIOD)

    crossovers = detect_crossovers(times, closes, ema_fast, ema_slow, rsi_values)
    last_crossover = crossovers[-1] if crossovers else None
    gap_values = gap_series(ema_fast, ema_slow)
    current_gap, gap_trend_label = gap_trend(gap_values)
    day_direction = await _day_direction(dhan, settings, today)

    return {
        "underlying": "NIFTY",
        "side": side,
        "strike": option["strike"],
        "expiry": expiry,
        "timeframeMinutes": timeframe,
        "candles": [
            {"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]}
            for c in ordered
        ],
        "emaFastValues": ema_fast,
        "emaSlowValues": ema_slow,
        "rsiValues": rsi_values,
        "rsiSmaValues": rsi_sma_values,
        "gapValues": gap_values,
        "crossovers": crossovers,
        "lastCrossover": last_crossover,
        "current": {
            "emaFast": ema_fast[-1] if ema_fast else None,
            "emaSlow": ema_slow[-1] if ema_slow else None,
            "rsi": rsi_values[-1] if rsi_values else None,
            "rsiSma": rsi_sma_values[-1] if rsi_sma_values else None,
            "gap": current_gap,
        },
        "gapTrend": gap_trend_label,
        "dayDirection": day_direction,
    }


def start_simple_crossover_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.simple_crossover_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_simple_crossover_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def _loop() -> None:
    while True:
        try:
            settings = get_settings()
            now = now_ist()
            in_hours = in_time_window(
                now.time(), settings.simple_crossover_session_start_time, settings.simple_crossover_session_end_time
            )
            has_open_trades = bool(db.list_open_simple_crossover_trades())
            after_close_with_open_trades = (
                has_open_trades and now.time() >= _parse_hhmm(settings.simple_crossover_session_end_time)
            )
            if settings.simple_crossover_monitor_enabled and (in_hours or after_close_with_open_trades) and now.weekday() < 5:
                await _poll_once(settings, now)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("simple_crossover: poll iteration failed")
        await asyncio.sleep(_seconds_to_next_poll(time.time()))


async def _poll_once(settings: Settings, now: Any) -> None:
    global _handled_date
    today = now.date().isoformat()
    if _handled_date != today:
        _handled_date = today
        _handled_crossover_time.clear()

    dhan = DhanService(settings)
    is_eod = now.time() >= _parse_hhmm(settings.simple_crossover_session_end_time)

    # Manage every open trade regardless of side or today's current
    # direction -- per the user's own resolution, direction only gates NEW
    # entries; an open position rides to its own exit.
    for trade in db.list_open_simple_crossover_trades():
        try:
            await _manage_open_trade(dhan, trade, is_eod)
        except Exception:
            logger.exception("simple_crossover: manage open trade #%s failed", trade["id"])

    if is_eod:
        return

    direction = await _day_direction(dhan, settings, today)

    if is_day_direction_filter_enabled():
        if not direction:
            return
        if direction["label"] == "Sideways":
            if not is_trade_on_sideways_enabled():
                return
            sides_to_check: tuple[Side, ...] = SIDES
        else:
            sides_to_check = ("CE",) if direction["label"] == "Up" else ("PE",)
    else:
        sides_to_check = SIDES

    for side in sides_to_check:
        try:
            await _evaluate_entry(dhan, settings, side, now, direction)
        except Exception:
            logger.exception("simple_crossover: evaluate entry failed for %s", side)


def _latest_pcr_snapshot(today: str) -> dict[str, Any] | None:
    snapshots = db.get_pcr_oi_snapshots(today).get("NIFTY", [])
    return snapshots[-1] if snapshots else None


async def _evaluate_entry(dhan: DhanService, settings: Settings, side: Side, now: Any, direction: dict[str, Any] | None) -> None:
    # One open position per side at a time -- re-entry is allowed (per the
    # user's resolution) once the previous one on this side has closed, not
    # multiple simultaneous positions on the same side.
    if db.get_open_simple_crossover_trade(side):
        return

    now_epoch = now_ist_epoch()
    today = now.date().isoformat()

    expiry = await _cached_expiry(dhan, settings)
    if not expiry:
        return
    option = await _cached_atm_option(dhan, settings, expiry, side)
    if not option:
        return
    try:
        ltp = await _live_price(dhan, option["securityId"])
    except Exception as exc:
        logger.warning("simple_crossover: live quote failed for %s entry check: %s", side, exc)
        ltp = None
    if not ltp:
        return

    try:
        raw = await dhan.intraday_candles(option["securityId"], OPTION_SEGMENT, "OPTIDX", "1", today, today)
    except Exception as exc:
        logger.warning("simple_crossover: candle fetch failed for %s entry check, skipping this poll: %s", side, exc)
        return
    timeframe = get_timeframe_minutes()
    ordered, live_minute = _closed_candles(raw, now_ist_epoch(), timeframe, ltp)
    closes = [float(c["close"]) for c in ordered]
    if len(closes) < EMA_SLOW_PERIOD + 2:
        return

    times = [int(c["time"]) for c in ordered]
    ema_fast = ema(closes, EMA_FAST_PERIOD)
    ema_slow = ema(closes, EMA_SLOW_PERIOD)
    rsi_values = rsi(closes, RSI_PERIOD)

    # Only a crossover on the just-closed candle can trigger (see
    # RECENT_CROSSOVER_LOOKBACK_CANDLES); never act on an older cross-over.
    all_crossovers = detect_crossovers(times, closes, ema_fast, ema_slow, rsi_values)
    recent_cutoff_index = len(ordered) - 1 - RECENT_CROSSOVER_LOOKBACK_CANDLES
    crossover = next(
        (item for item in reversed(all_crossovers) if times.index(item["time"]) >= recent_cutoff_index),
        None,
    )
    if crossover is None or crossover["direction"] != "up":
        return
    crossover_time = crossover["time"]

    if _handled_crossover_time.get(side) == crossover_time:
        return  # already acted on this exact crossover candle
    if ltp > crossover["price"] * (1 + ENTRY_CHASE_LIMIT_PERCENT / 100):
        _handled_crossover_time[side] = crossover_time
        logger.warning(
            "simple_crossover: %s crossover at %s skipped -- live %.2f already %.1f%% above the signal close %.2f",
            side, crossover_time, ltp, (ltp / crossover["price"] - 1) * 100, crossover["price"],
        )
        return

    entry_gap = ema_fast[-1] - ema_slow[-1]
    pcr_snapshot = _latest_pcr_snapshot(today)

    trade_id = db.create_simple_crossover_trade(
        underlying="NIFTY",
        side=side,
        strike=option["strike"],
        expiry=expiry,
        security_id=option["securityId"],
        exchange_segment=OPTION_SEGMENT,
        lots=PAPER_LOTS,
        lot_size=NIFTY_LOT_SIZE,
        entry_time=now_ist_epoch(),
        entry_premium=ltp,
        entry_ema_gap=entry_gap,
        entry_pcr=pcr_snapshot.get("pcr") if pcr_snapshot else None,
        entry_ce_oi_change=pcr_snapshot.get("ceOiChange") if pcr_snapshot else None,
        entry_pe_oi_change=pcr_snapshot.get("peOiChange") if pcr_snapshot else None,
        day_direction=direction["label"] if direction else None,
        timeframe_minutes=timeframe,
        signal_time=crossover_time,
        signal_close=crossover["price"],
        signal_source="live" if live_minute is not None and crossover_time <= live_minute < crossover_time + timeframe * 60 else "dhan",
        plain_crossover=is_plain_crossover_enabled(),
        plain_target_percent=get_plain_target_percent() if is_plain_crossover_enabled() else None,
    )
    _handled_crossover_time[side] = crossover_time
    logger.warning(
        "simple_crossover: entered %s x %s lots @ %s (strike %s, expiry %s, trade #%s) -- crossover candle %s close %s, %ss after it closed",
        side, PAPER_LOTS, ltp, option["strike"], expiry, trade_id, crossover_time, crossover["price"],
        now_ist_epoch() - (crossover_time + timeframe * 60),
    )


async def _manage_open_trade(dhan: DhanService, trade: dict[str, Any], is_eod: bool) -> None:
    try:
        quotes = await dhan.market_quotes_by_segment(
            {trade["exchangeSegment"]: [int(trade["securityId"])]}, max_age_seconds=QUOTE_MAX_AGE_SECONDS
        )
        current_premium = float(
            (quotes.get(trade["exchangeSegment"]) or {}).get(str(trade["securityId"]), {}).get("last_price") or 0
        )
    except Exception as exc:
        if is_eod and trade.get("currentPremium"):
            current_premium = float(trade["currentPremium"])
            logger.warning(
                "simple_crossover: using last recorded premium for EOD close of trade #%s after quote failure: %s",
                trade["id"], exc,
            )
        else:
            logger.warning("simple_crossover: quote fetch failed for trade #%s, skipping this tick: %s", trade["id"], exc)
            return
    if not current_premium and is_eod and trade.get("currentPremium"):
        current_premium = float(trade["currentPremium"])
    if not current_premium:
        return

    now_epoch = now_ist_epoch()
    entry_premium = float(trade["entryPremium"])
    peak_premium = max(float(trade.get("peakPremium") or entry_premium), current_premium)
    target1_hit = bool(trade.get("target1Hit"))
    target2_hit = bool(trade.get("target2Hit"))
    trailing_stop = _trailing_stop_price(entry_premium, peak_premium) if target2_hit else None
    db.update_simple_crossover_trade_progress(
        trade["id"], current_premium=current_premium, peak_premium=peak_premium,
        trailing_stop_price=trailing_stop,
    )

    remaining_lots = int(trade.get("remainingLots") or trade["lots"])
    if trade.get("plainCrossover"):
        # Plain cross over: the 15:30 square-off, the trade's own profit target
        # (if any) and the cross-under exit apply.
        if is_eod:
            _close_remaining(trade, lots=remaining_lots, exit_time=now_epoch, exit_premium=current_premium, exit_reason="eod")
            return
        target_percent = float(trade.get("plainTargetPercent") or 0)
        if target_percent > 0 and current_premium >= entry_premium * (1 + target_percent / 100):
            _close_remaining(trade, lots=remaining_lots, exit_time=now_epoch, exit_premium=current_premium, exit_reason="plain_target")
            return
        await _cross_under_exit(dhan, trade, remaining_lots, current_premium, now_epoch)
        return
    fixed_stop = entry_premium * (1 - get_stop_loss_percent() / 100)
    active_stop = trailing_stop if target2_hit else fixed_stop
    if current_premium <= active_stop:
        reason = "trailing_stop" if target2_hit else "stop_loss"
        _close_remaining(trade, lots=remaining_lots, exit_time=now_epoch, exit_premium=current_premium, exit_reason=reason)
        return

    if not target1_hit and remaining_lots > 0 and current_premium >= entry_premium * (1 + FIRST_TARGET_PERCENT / 100):
        target_price = entry_premium * (1 + FIRST_TARGET_PERCENT / 100)
        if db.record_simple_crossover_exit_leg(
            trade["id"], lots=1, exit_time=now_epoch, exit_premium=target_price, exit_reason="target_5"
        ):
            logger.info("simple_crossover: trade #%s target +5%% sold one lot @ %.2f", trade["id"], target_price)
            target1_hit = True
            remaining_lots -= 1
            trade["realizedPnl"] = float(trade.get("realizedPnl") or 0) + (target_price - entry_premium) * int(trade["lotSize"])
        if remaining_lots == 0:
            return

    if not target2_hit and remaining_lots > 0 and current_premium >= entry_premium * (1 + SECOND_TARGET_PERCENT / 100):
        target_price = entry_premium * (1 + SECOND_TARGET_PERCENT / 100)
        if db.record_simple_crossover_exit_leg(
            trade["id"], lots=1, exit_time=now_epoch, exit_premium=target_price, exit_reason="target_10"
        ):
            logger.info("simple_crossover: trade #%s target +10%% sold one lot @ %.2f", trade["id"], target_price)
            target2_hit = True
            remaining_lots -= 1
            trade["realizedPnl"] = float(trade.get("realizedPnl") or 0) + (target_price - entry_premium) * int(trade["lotSize"])
            trailing_stop = _trailing_stop_price(entry_premium, peak_premium)
        if remaining_lots == 0:
            return

    trade["remainingLots"] = remaining_lots
    trade["target1Hit"] = target1_hit
    trade["target2Hit"] = target2_hit
    trade["peakPremium"] = peak_premium
    trade["trailingStopPrice"] = trailing_stop
    db.update_simple_crossover_trade_progress(
        trade["id"], current_premium=current_premium, peak_premium=peak_premium,
        trailing_stop_price=trailing_stop,
    )

    if is_eod:
        _close_remaining(trade, lots=remaining_lots, exit_time=now_epoch, exit_premium=current_premium, exit_reason="eod")
        return

    await _cross_under_exit(dhan, trade, remaining_lots, current_premium, now_epoch)


async def _cross_under_exit(dhan: DhanService, trade: dict[str, Any], remaining_lots: int, current_premium: float, now_epoch: int) -> None:
    try:
        today = now_ist().date().isoformat()
        raw = await dhan.intraday_candles(trade["securityId"], trade["exchangeSegment"], "OPTIDX", "1", today, today)
    except Exception as exc:
        logger.warning("simple_crossover: candle fetch failed for trade #%s, skipping exit check this tick: %s", trade["id"], exc)
        return
    ordered, _ = _closed_candles(raw, now_epoch, int(trade.get("timeframeMinutes") or 1), current_premium)
    closes = [float(c["close"]) for c in ordered]
    if len(closes) < EMA_SLOW_PERIOD + 2:
        return

    times = [int(c["time"]) for c in ordered]
    ema_fast = ema(closes, EMA_FAST_PERIOD)
    ema_slow = ema(closes, EMA_SLOW_PERIOD)
    rsi_values = rsi(closes, RSI_PERIOD)
    recent_crossovers = detect_crossovers(times, closes, ema_fast, ema_slow, rsi_values)
    # Any cross-under on a candle after the crossover candle that triggered the
    # entry (older trades without signalTime: candles starting after entry).
    after = int(trade.get("signalTime") or trade["entryTime"])
    cross_under_after_entry = next(
        (
            cross for cross in reversed(recent_crossovers)
            if cross["direction"] == "down" and cross["time"] > after
        ),
        None,
    )
    if cross_under_after_entry:
        _close_remaining(
            trade, lots=remaining_lots, exit_time=now_epoch,
            exit_premium=current_premium, exit_reason="cross_under",
        )


def _trailing_stop_price(entry_premium: float, peak_premium: float) -> float:
    peak_gain_percent = max(0.0, (peak_premium / entry_premium - 1) * 100)
    steps = max(1, int((peak_gain_percent - SECOND_TARGET_PERCENT + 1e-9) // TRAIL_STEP_PERCENT) + 1)
    locked_gain_percent = steps * TRAIL_STEP_PERCENT
    return round(entry_premium * (1 + locked_gain_percent / 100), 4)


def _close_remaining(
    trade: dict[str, Any], *, lots: int, exit_time: int, exit_premium: float, exit_reason: str
) -> None:
    if lots <= 0:
        return
    closed = db.record_simple_crossover_exit_leg(
        trade["id"], lots=lots, exit_time=exit_time,
        exit_premium=exit_premium, exit_reason=exit_reason,
    )
    if closed:
        logger.info(
            "simple_crossover: exit %s %s x %s lots @ %s (%s)",
            trade["underlying"], trade["side"], lots, exit_premium, exit_reason,
        )


def _closed_candles(
    candles: list[dict[str, Any]], now_epoch: int, timeframe: int, live_close: float | None
) -> tuple[list[dict[str, Any]], int | None]:
    """Completed candles, with the minute that just closed filled from the
    live price when Dhan hasn't published it yet (only within the first
    LIVE_CLOSE_MAX_AGE_SECONDS after the close, while the live price still
    is that minute's close). Returns the candles and the start time of the
    filled-in minute (None if Dhan's own candle was used)."""
    just_closed = (now_epoch // 60) * 60 - 60
    minutes = [c for c in candles if int(c["time"]) <= just_closed]
    filled = None
    has_minute = any(int(c["time"]) == just_closed for c in minutes)
    if not has_minute and live_close and now_epoch - (just_closed + 60) <= LIVE_CLOSE_MAX_AGE_SECONDS:
        minutes.append({"time": just_closed, "open": live_close, "high": live_close, "low": live_close, "close": live_close, "volume": 0})
        filled = just_closed
    return _completed_candles(minutes, now_epoch, timeframe), filled


def _completed_candles(candles: list[dict[str, Any]], now_epoch: int, timeframe: int = 1) -> list[dict[str, Any]]:
    """Only fully closed candles of the timeframe (a 3m candle counts once all
    three of its minutes are over)."""
    return [candle for candle in resample_candles(candles, timeframe) if int(candle["time"]) + timeframe * 60 <= now_epoch]


def _parse_hhmm(value: str) -> dtime:
    hour, minute = value.split(":")
    return dtime(int(hour), int(minute))
