"""Simple Cross Over - XAUT: the same strategy as simple_crossover.py
(NIFTY options), applied to XAUTUSD on Delta Exchange -- a genuinely
different market structure, not a copy-paste. See archive/README.md's
"closest prior art" note and this repo's own simple_crossover.py for the
shared design reasoning; only the differences are called out below.

- Single spot/perp instrument, no CE/PE-equivalent pair -- one chart, one
  symbol. Up day -> long on an up-crossover; Down day -> short on a
  down-crossover (the mirror signal), since there's no separate instrument
  that rises when gold falls the way a PE does for an index.
- Exits mirror by side: long exits on cross-under or RSI >= rsi_long_exit;
  short exits on cross-over or RSI <= rsi_short_exit (same two-threshold
  pattern pstrategy_nifty already uses for long/short RSI-extreme exits,
  now archived but the convention is reused here).
- Delta Exchange trades 24/7 -- no NSE session window. Polls continuously;
  "EOD" becomes a midnight-IST square-off of any still-open position
  instead of a market-close time.
- No PCR/OI tracking (NSE-options-flow-specific, doesn't exist for a Delta
  Exchange perpetual) -- EMA gap is the only per-trade tracking field.
- Paper-only, same as the NIFTY version -- quantity is plain XAUTUSD units,
  no real order/contract-size conversion needed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from app.core.config import Settings, get_settings
from app.core.timeutil import now_ist, now_ist_epoch, start_of_today_ist_epoch
from app.db import sqlite as db
from app.services.crypto_indicators import ema, rsi
from app.services.delta_exchange import DeltaExchangeService
from app.services.simple_crossover import detect_crossovers, gap_series, gap_trend, sma, touched_or_close_to_crossover

logger = logging.getLogger(__name__)

SYMBOL = "XAUTUSD"
EMA_FAST_PERIOD = 8
EMA_SLOW_PERIOD = 21
RSI_PERIOD = 8
RSI_SMA_PERIOD = 5
DAY_DIRECTION_THRESHOLD_PERCENT = 0.3
# How many recent 1-minute candles _evaluate_entry looks back through for
# an unhandled crossover, instead of only the very latest candle pair --
# recovers from a single missed/failed poll without risking entry into a
# stale, long-past crossover after a real outage.
RECENT_CROSSOVER_LOOKBACK_CANDLES = 5

Side = Literal["long", "short"]
SIDES: tuple[Side, ...] = ("long", "short")

# Runtime-toggleable, DB-backed, editable from the UI without a restart --
# same pattern as simple_crossover.py's own toggle. Default ON. When off,
# both long and short are evaluated independently every tick -- whichever
# side's own crossover condition is satisfied enters, Sideways days no
# longer block anything either.
DAY_DIRECTION_FILTER_SETTING_KEY = "day_direction_filter_enabled"

# Only meaningful when the day-direction filter above is ON. Default OFF
# (unset == disabled) so deploying this doesn't change today's live
# behavior -- Sideways days still take no entries unless explicitly turned
# on here, in which case both long and short are evaluated independently
# on Sideways days only (Up/Down days still gate to a single side).
TRADE_ON_SIDEWAYS_SETTING_KEY = "trade_on_sideways"

# RSI-extreme exit, same DB-backed/UI-editable pattern. Default ON. Long
# exits when RSI rises to/above the long threshold; short exits when RSI
# falls to/below the short threshold.
RSI_EXIT_FILTER_SETTING_KEY = "rsi_exit_filter_enabled"
RSI_LONG_EXIT_THRESHOLD_KEY = "rsi_long_exit_threshold"
RSI_SHORT_EXIT_THRESHOLD_KEY = "rsi_short_exit_threshold"

# Position sizing: quantity at entry = margin * leverage / entry price,
# same margin+leverage model the archived pStrategy engine used for
# XAUTUSD. DB-backed/UI-editable, same pattern as everything else here.
MARGIN_PER_TRADE_KEY = "margin_per_trade"
LEVERAGE_KEY = "leverage"

# Entry EMA-gap filter: only take an entry when the EMA8-EMA21 separation at
# the moment of entry (a proxy for how confirmed/developing the move is) is
# within [min, max]. Default ON here, backed by an analysis of this
# engine's own first 36 trades: gap < ~0.06 (a weak, barely-confirmed
# cross) and gap >= ~0.25 (already-extended, chasing a late entry) were
# both net losers (10-14% win rate); the 0.06-0.15 band was the clear
# winner (64% win rate, +33% of margin combined). Unlike the day-direction/
# RSI-exit toggles, this one defaults ON because it's evidence-based for
# this specific instrument, not just a behavior-preserving default.
ENTRY_GAP_FILTER_SETTING_KEY = "entry_gap_filter_enabled"
MIN_ENTRY_GAP_KEY = "min_entry_gap"
MAX_ENTRY_GAP_KEY = "max_entry_gap"

_handled_crossover_time: dict[Side, int | None] = {}
_handled_date: str | None = None


def is_day_direction_filter_enabled() -> bool:
    raw = db.get_simple_crossover_xaut_setting(DAY_DIRECTION_FILTER_SETTING_KEY)
    return True if raw is None else raw == "1"


def set_day_direction_filter_enabled(value: bool) -> None:
    db.set_simple_crossover_xaut_setting(DAY_DIRECTION_FILTER_SETTING_KEY, "1" if value else "0")


def is_trade_on_sideways_enabled() -> bool:
    raw = db.get_simple_crossover_xaut_setting(TRADE_ON_SIDEWAYS_SETTING_KEY)
    return raw == "1"


def set_trade_on_sideways_enabled(value: bool) -> None:
    db.set_simple_crossover_xaut_setting(TRADE_ON_SIDEWAYS_SETTING_KEY, "1" if value else "0")


def is_rsi_exit_filter_enabled() -> bool:
    raw = db.get_simple_crossover_xaut_setting(RSI_EXIT_FILTER_SETTING_KEY)
    return True if raw is None else raw == "1"


def set_rsi_exit_filter_enabled(value: bool) -> None:
    db.set_simple_crossover_xaut_setting(RSI_EXIT_FILTER_SETTING_KEY, "1" if value else "0")


def get_rsi_long_exit_threshold() -> float:
    raw = db.get_simple_crossover_xaut_setting(RSI_LONG_EXIT_THRESHOLD_KEY)
    return float(raw) if raw is not None else get_settings().simple_crossover_xaut_rsi_long_exit


def set_rsi_long_exit_threshold(value: float) -> None:
    db.set_simple_crossover_xaut_setting(RSI_LONG_EXIT_THRESHOLD_KEY, str(value))


def get_rsi_short_exit_threshold() -> float:
    raw = db.get_simple_crossover_xaut_setting(RSI_SHORT_EXIT_THRESHOLD_KEY)
    return float(raw) if raw is not None else get_settings().simple_crossover_xaut_rsi_short_exit


def set_rsi_short_exit_threshold(value: float) -> None:
    db.set_simple_crossover_xaut_setting(RSI_SHORT_EXIT_THRESHOLD_KEY, str(value))


def get_margin_per_trade() -> float:
    raw = db.get_simple_crossover_xaut_setting(MARGIN_PER_TRADE_KEY)
    return float(raw) if raw is not None else get_settings().simple_crossover_xaut_margin_per_trade


def set_margin_per_trade(value: float) -> None:
    db.set_simple_crossover_xaut_setting(MARGIN_PER_TRADE_KEY, str(value))


def get_leverage() -> float:
    raw = db.get_simple_crossover_xaut_setting(LEVERAGE_KEY)
    return float(raw) if raw is not None else get_settings().simple_crossover_xaut_leverage


def set_leverage(value: float) -> None:
    db.set_simple_crossover_xaut_setting(LEVERAGE_KEY, str(value))


def is_entry_gap_filter_enabled() -> bool:
    raw = db.get_simple_crossover_xaut_setting(ENTRY_GAP_FILTER_SETTING_KEY)
    return True if raw is None else raw == "1"


def set_entry_gap_filter_enabled(value: bool) -> None:
    db.set_simple_crossover_xaut_setting(ENTRY_GAP_FILTER_SETTING_KEY, "1" if value else "0")


def get_min_entry_gap() -> float:
    raw = db.get_simple_crossover_xaut_setting(MIN_ENTRY_GAP_KEY)
    return float(raw) if raw is not None else get_settings().simple_crossover_xaut_min_entry_gap


def set_min_entry_gap(value: float) -> None:
    db.set_simple_crossover_xaut_setting(MIN_ENTRY_GAP_KEY, str(value))


def get_max_entry_gap() -> float:
    raw = db.get_simple_crossover_xaut_setting(MAX_ENTRY_GAP_KEY)
    return float(raw) if raw is not None else get_settings().simple_crossover_xaut_max_entry_gap


def set_max_entry_gap(value: float) -> None:
    db.set_simple_crossover_xaut_setting(MAX_ENTRY_GAP_KEY, str(value))


def get_runtime_config() -> dict[str, Any]:
    return {
        "dayDirectionFilterEnabled": is_day_direction_filter_enabled(),
        "tradeOnSideways": is_trade_on_sideways_enabled(),
        "rsiExitEnabled": is_rsi_exit_filter_enabled(),
        "rsiLongExitThreshold": get_rsi_long_exit_threshold(),
        "rsiShortExitThreshold": get_rsi_short_exit_threshold(),
        "marginPerTrade": get_margin_per_trade(),
        "leverage": get_leverage(),
        "entryGapFilterEnabled": is_entry_gap_filter_enabled(),
        "minEntryGap": get_min_entry_gap(),
        "maxEntryGap": get_max_entry_gap(),
    }


def _apply_paper_charges(trade: dict[str, Any], settings: Settings) -> None:
    """Delta Exchange's published XAUTUSD taker fee (see
    simple_crossover_xaut_taker_fee_percent) on the entry and exit legs'
    notional. Closed trades get real charges/net P&L; open trades get an
    estimate as if exiting at the current price right now.
    """
    quantity = trade["quantity"]
    fee_percent = settings.simple_crossover_xaut_taker_fee_percent
    entry_fee = round(trade["entryPrice"] * quantity * fee_percent / 100, 2)

    exit_price = trade["exitPrice"] if trade["status"] == "closed" else trade["currentPrice"]
    if exit_price is None:
        exit_price = trade["entryPrice"]
    exit_fee = round(exit_price * quantity * fee_percent / 100, 2)

    total = round(entry_fee + exit_fee, 2)
    trade["charges"] = total

    if trade["status"] == "closed":
        trade["netPnl"] = round((trade["realizedPnl"] or 0) - total, 2)
    elif trade["currentPrice"] is not None:
        if trade["side"] == "long":
            current_pnl = (trade["currentPrice"] - trade["entryPrice"]) * quantity
        else:
            current_pnl = (trade["entryPrice"] - trade["currentPrice"]) * quantity
        trade["netPnl"] = round(current_pnl - total, 2)
    else:
        trade["netPnl"] = None

    # % of margin -- the number that actually shows whether fees are eating
    # returns, since $ P&L and $ charges both scale with position size the
    # same way. None for trades opened before this field existed.
    margin = trade.get("margin")
    trade["netPnlPercent"] = round(trade["netPnl"] / margin * 100, 2) if margin and trade["netPnl"] is not None else None


def list_trades_with_charges() -> list[dict[str, Any]]:
    settings = get_settings()
    trades = db.list_simple_crossover_xaut_trades()
    for trade in trades:
        _apply_paper_charges(trade, settings)
    return trades


def _day_direction_from_candles(ordered: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not ordered:
        return None
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


CANDLE_RESOLUTION_SECONDS = 60


async def _fetch_today_candles(delta: DeltaExchangeService, *, drop_forming: bool = False) -> list[dict[str, Any]]:
    """`drop_forming=True` strips a trailing candle whose 1-minute bucket
    hasn't closed yet. Delta's candle API returns the current, still-forming
    minute as the last row when queried up to "now" -- its own open/high/low/
    close are identical (a single-tick snapshot at whatever moment we asked),
    not a real closed bar. Feeding that into an EMA crossover check lets one
    noisy in-flight tick flip the sign of a near-zero fast/slow gap and fire
    a trade action that a look at the FINAL, closed candle never would have
    justified -- confirmed against a real trade: exit logged "cross_under" at
    06:02 IST 2026-09-25, but the closed 1m candles show EMA8 stayed above
    EMA21 the whole time (gap dipped to +0.04, never went negative). Entry
    evaluation is naturally more resistant to this (it scans several recent
    CLOSED candles via detect_crossovers + a touch/lookback confirmation) but
    exit's plain `ema_fast[-1] < ema_slow[-1]` has no such cushion, so this
    matters most for _manage_open_trade. get_data() intentionally keeps the
    forming candle (drop_forming=False) so the live chart still updates
    within the minute -- only the trade-decision paths need closed-only data.
    """
    raw = await delta.get_candles(SYMBOL, "1m", start_of_today_ist_epoch(), now_ist_epoch())
    ordered = sorted(raw, key=lambda c: c["time"])
    if drop_forming and ordered:
        now_epoch = now_ist_epoch()
        if int(ordered[-1]["time"]) + CANDLE_RESOLUTION_SECONDS > now_epoch:
            ordered = ordered[:-1]
    return ordered


async def get_data() -> dict[str, Any]:
    settings = get_settings()
    delta = DeltaExchangeService(settings)

    try:
        ordered = await _fetch_today_candles(delta)
    except Exception as exc:
        return {"error": str(exc), "candles": []}

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
    day_direction = _day_direction_from_candles(ordered)

    return {
        "symbol": SYMBOL,
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


def start_simple_crossover_xaut_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.simple_crossover_xaut_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_simple_crossover_xaut_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def _loop() -> None:
    settings = get_settings()
    interval = max(settings.simple_crossover_xaut_poll_interval_seconds, 15)
    while True:
        try:
            settings = get_settings()
            if settings.simple_crossover_xaut_monitor_enabled:
                await _poll_once(settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("simple_crossover_xaut: poll iteration failed")
        await asyncio.sleep(interval)


async def _poll_once(settings: Settings) -> None:
    global _handled_date
    now = now_ist()
    today = now.date().isoformat()
    is_new_day = _handled_date != today
    if is_new_day:
        _handled_date = today
        _handled_crossover_time.clear()

    delta = DeltaExchangeService(settings)

    # Manage every open trade regardless of side/direction -- direction
    # only gates new entries, an open position rides to its own exit,
    # except for the midnight square-off on the first tick of a new day.
    for trade in db.list_open_simple_crossover_xaut_trades():
        try:
            await _manage_open_trade(delta, settings, trade, force_close=is_new_day)
        except Exception:
            logger.exception("simple_crossover_xaut: manage open trade #%s failed", trade["id"])

    try:
        ordered = await _fetch_today_candles(delta, drop_forming=True)
    except Exception as exc:
        logger.warning("simple_crossover_xaut: candle fetch failed, skipping this poll: %s", exc)
        return
    direction = _day_direction_from_candles(ordered)

    if is_day_direction_filter_enabled():
        if not direction:
            return
        if direction["label"] == "Sideways":
            if not is_trade_on_sideways_enabled():
                return
            sides_to_check: tuple[Side, ...] = SIDES
        else:
            sides_to_check = ("long",) if direction["label"] == "Up" else ("short",)
    else:
        sides_to_check = SIDES

    for side in sides_to_check:
        try:
            await _evaluate_entry(delta, settings, side, direction, ordered)
        except Exception:
            logger.exception("simple_crossover_xaut: evaluate entry failed for %s", side)


async def _evaluate_entry(
    delta: DeltaExchangeService,
    settings: Settings,
    side: Side,
    direction: dict[str, Any] | None,
    ordered: list[dict[str, Any]],
) -> None:
    # One open position per side at a time -- re-entry allowed once the
    # previous one on this side has closed.
    if db.get_open_simple_crossover_xaut_trade(side):
        return

    closes = [float(c["close"]) for c in ordered]
    if len(closes) < EMA_SLOW_PERIOD + 2:
        return

    times = [int(c["time"]) for c in ordered]
    ema_fast = ema(closes, EMA_FAST_PERIOD)
    ema_slow = ema(closes, EMA_SLOW_PERIOD)
    rsi_values = rsi(closes, RSI_PERIOD)

    # Scan the last few candles for a not-yet-acted-on crossover in this
    # side's direction, instead of only the very latest candle pair -- a
    # single missed poll (a candle-fetch hiccup, or unlucky timing against
    # the 1-minute candle boundary) would otherwise permanently lose the
    # signal once newer candles push past it. Capped to a short lookback
    # so a long outage doesn't cause entry into a now-stale crossover.
    wanted_direction = "up" if side == "long" else "down"
    all_crossovers = detect_crossovers(times, closes, ema_fast, ema_slow, rsi_values)
    recent_cutoff_index = len(ordered) - 1 - RECENT_CROSSOVER_LOOKBACK_CANDLES
    found: tuple[dict[str, Any], int] | None = None
    for crossover in reversed(all_crossovers):
        index = times.index(crossover["time"])
        if index < recent_cutoff_index:
            break  # crossovers are in time order -- everything older fails too
        if crossover["direction"] == wanted_direction:
            found = (crossover, index)
            break
    if found is None:
        return
    crossover, crossover_index = found
    crossover_time = crossover["time"]

    if _handled_crossover_time.get(side) == crossover_time:
        return  # already acted on this exact crossover candle

    crossover_candle = ordered[crossover_index]
    crossover_ema_slow = ema_slow[crossover_index]
    if crossover_ema_slow is None:
        return

    if not touched_or_close_to_crossover(
        crossover_candle, crossover_ema_slow, settings.simple_crossover_xaut_max_gap_from_crossover_percent
    ):
        logger.info(
            "simple_crossover_xaut: %s crossover at %s rejected -- candle range %s-%s didn't touch EMA21 %.2f and close %.2f is too far",
            side, crossover_candle["time"], crossover_candle["low"], crossover_candle["high"], crossover_ema_slow, crossover_candle["close"],
        )
        return

    entry_gap = ema_fast[-1] - ema_slow[-1]
    if is_entry_gap_filter_enabled():
        min_gap = get_min_entry_gap()
        max_gap = get_max_entry_gap()
        if not (min_gap <= abs(entry_gap) <= max_gap):
            logger.info(
                "simple_crossover_xaut: %s crossover at %s rejected -- entry EMA gap %.4f outside [%.4f, %.4f]",
                side, crossover_time, entry_gap, min_gap, max_gap,
            )
            return

    _handled_crossover_time[side] = crossover_time

    try:
        ticker = await delta.get_ticker(SYMBOL)
        entry_price = float(ticker.get("close") or ticker.get("mark_price") or 0)
    except Exception as exc:
        logger.warning("simple_crossover_xaut: ticker fetch failed for entry, falling back to crossover candle close: %s", exc)
        entry_price = 0.0
    if not entry_price:
        entry_price = float(crossover_candle["close"])

    now_epoch = now_ist_epoch()

    margin = get_margin_per_trade()
    leverage = get_leverage()
    quantity = (margin * leverage) / entry_price

    trade_id = db.create_simple_crossover_xaut_trade(
        side=side,
        quantity=quantity,
        entry_time=now_epoch,
        entry_price=entry_price,
        entry_ema_gap=entry_gap,
        day_direction=direction["label"] if direction else None,
        margin=margin,
        leverage=leverage,
    )
    logger.info("simple_crossover_xaut: entered %s @ %s (trade #%s)", side, entry_price, trade_id)


async def _manage_open_trade(
    delta: DeltaExchangeService, settings: Settings, trade: dict[str, Any], force_close: bool
) -> None:
    try:
        ticker = await delta.get_ticker(SYMBOL)
        current_price = float(ticker.get("close") or ticker.get("mark_price") or 0)
    except Exception as exc:
        logger.warning("simple_crossover_xaut: ticker fetch failed for trade #%s, skipping this tick: %s", trade["id"], exc)
        return
    if not current_price:
        return

    now_epoch = now_ist_epoch()
    db.update_simple_crossover_xaut_trade_progress(trade["id"], current_price=current_price)

    if force_close:
        _close(trade, exit_time=now_epoch, exit_price=current_price, exit_reason="day_boundary")
        return

    try:
        ordered = await _fetch_today_candles(delta, drop_forming=True)
    except Exception as exc:
        logger.warning("simple_crossover_xaut: candle fetch failed for trade #%s, skipping exit check this tick: %s", trade["id"], exc)
        return
    closes = [float(c["close"]) for c in ordered]
    if len(closes) < EMA_SLOW_PERIOD + 2:
        return

    ema_fast = ema(closes, EMA_FAST_PERIOD)
    ema_slow = ema(closes, EMA_SLOW_PERIOD)
    rsi_values = rsi(closes, RSI_PERIOD)
    if ema_fast[-1] is None or ema_slow[-1] is None or ema_fast[-2] is None or ema_slow[-2] is None:
        return

    # Require the EMA reversal to hold for 2 consecutive CLOSED candles, not
    # just the very latest one -- a single-candle flip on a near-zero gap
    # was the dominant loss driver in practice (cross_under/cross_over exits
    # were 78% of all trades at an 18% win rate). This can only delay an
    # exit by one candle (~1 minute), never block a real reversal.
    rsi_exit_enabled = is_rsi_exit_filter_enabled()
    if trade["side"] == "long":
        if ema_fast[-1] < ema_slow[-1] and ema_fast[-2] < ema_slow[-2]:
            _close(trade, exit_time=now_epoch, exit_price=current_price, exit_reason="cross_under")
            return
        if rsi_exit_enabled and rsi_values[-1] is not None and rsi_values[-1] >= get_rsi_long_exit_threshold():
            _close(trade, exit_time=now_epoch, exit_price=current_price, exit_reason="rsi_peak")
            return
    else:
        if ema_fast[-1] > ema_slow[-1] and ema_fast[-2] > ema_slow[-2]:
            _close(trade, exit_time=now_epoch, exit_price=current_price, exit_reason="cross_over")
            return
        if rsi_exit_enabled and rsi_values[-1] is not None and rsi_values[-1] <= get_rsi_short_exit_threshold():
            _close(trade, exit_time=now_epoch, exit_price=current_price, exit_reason="rsi_trough")
            return


def _close(trade: dict[str, Any], *, exit_time: int, exit_price: float, exit_reason: str) -> None:
    quantity = trade["quantity"]
    if trade["side"] == "long":
        realized_pnl = round((exit_price - trade["entryPrice"]) * quantity, 2)
    else:
        realized_pnl = round((trade["entryPrice"] - exit_price) * quantity, 2)
    db.close_simple_crossover_xaut_trade(
        trade["id"], exit_time=exit_time, exit_price=exit_price, exit_reason=exit_reason, realized_pnl=realized_pnl
    )
    logger.info(
        "simple_crossover_xaut: exit %s @ %s (%s) pnl=$%.2f", trade["side"], exit_price, exit_reason, realized_pnl
    )
