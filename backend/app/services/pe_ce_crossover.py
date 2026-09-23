"""PE-CE Crossover: a live, persisted paper-trading engine, structured like
pstrategy_nifty.py (same reason -- an option's live quote/chain state can't
be reconstructed after the fact for real-time decisions, even though its
OHLC candle history can be fetched separately for backtesting; see
pe_ce_backtest.py).

Per atm_ce_pe_premium_crossover_codex_spec.md: CE and PE are independent
signal streams on each configured underlying (NIFTY by default). A signal
is a bullish EMA8/EMA21 crossover computed on the OPTION'S OWN premium
candles -- never inferred from the underlying's direction, and never a
short position. Long-only, paper-only.

Exit is whichever fires first: a percentage-of-premium stop-loss or
target, an optional trailing stop that only ever tightens once armed, or
the option's own EMA8 crossing back below EMA21 -- plus a mandatory EOD
square-off. Guardrails (capital cap, daily-loss cap, max trades/day,
cooldown after a loss, one-position mode) mirror nifty_swing_live.py's
`_guardrails_ok` pattern -- there's no live Dhan fund-limit endpoint to
check a wallet balance against, so a configured rupee ceiling stands in,
same rationale as that module.

Every evaluated tick (entry candidate or not) is logged to
pe_ce_crossover_signal_log with one of the UI state labels the spec names
(NO_SIGNAL, CANDIDATE, WAITING_FOR_EXPANSION, READY, BLOCKED, IN_POSITION)
plus a reason when blocked -- spec: "Show why a trade is blocked; do not
hide rejected signals."
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time
from typing import Any

from app.core.config import Settings, get_settings
from app.core.timeutil import in_time_window, now_ist, now_ist_epoch
from app.db import sqlite as db
from app.services.charges import option_order_charges
from app.services.crypto_indicators import ema
from app.services.dhan import DhanService
from app.services.dhan_scrip_master import ScripMasterError, resolve_lot_size_by_security_id
from app.services.ema5_instruments import resolve_atm_option
from app.services.pe_ce_expiry import resolve_expiry_with_dte_policy
from app.services.pe_ce_filters import check_premium_expansion, check_quote_freshness, check_spread

logger = logging.getLogger(__name__)

OPTION_SEGMENT = "NSE_FNO"
INDEX_SEGMENT = "IDX_I"
STRIKE_STEP = {"NIFTY": 50.0, "BANKNIFTY": 100.0, "SENSEX": 100.0}
EMA_FAST_PERIOD = 8
EMA_SLOW_PERIOD = 21
SIDES = ("CE", "PE")

_handled_crossover_time: dict[tuple[str, str], int | None] = {}
_handled_date: str | None = None


def _underlyings(settings: Settings) -> list[str]:
    return [u.strip().upper() for u in settings.pe_ce_crossover_underlyings.split(",") if u.strip()]


def underlying_security_id(settings: Settings, underlying: str) -> int:
    if underlying == "NIFTY":
        return settings.dhan_nifty_security_id
    if underlying == "BANKNIFTY":
        return settings.dhan_banknifty_security_id
    return settings.dhan_sensex_security_id


def start_pe_ce_crossover_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.pe_ce_crossover_monitor_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_pe_ce_crossover_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def _loop() -> None:
    settings = get_settings()
    interval = max(settings.pe_ce_crossover_poll_interval_seconds, 15)
    while True:
        try:
            now = now_ist()
            in_hours = in_time_window(
                now.time(), settings.pe_ce_crossover_session_start_time, settings.pe_ce_crossover_session_end_time
            )
            if in_hours and now.weekday() < 5:
                await _poll_once(settings, now)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("pe_ce_crossover: poll iteration failed")
        await asyncio.sleep(interval)


async def _poll_once(settings: Settings, now: datetime) -> None:
    global _handled_date
    today = now.date().isoformat()
    if _handled_date != today:
        _handled_date = today
        _handled_crossover_time.clear()

    dhan = DhanService(settings)
    is_eod = now.time() >= _parse_hhmm(settings.pe_ce_crossover_session_end_time)

    for underlying in _underlyings(settings):
        for side in SIDES:
            try:
                await _evaluate(dhan, settings, underlying, side, now, is_eod)
            except Exception:
                logger.exception("pe_ce_crossover: evaluate failed for %s %s", underlying, side)


async def _evaluate(dhan: DhanService, settings: Settings, underlying: str, side: str, now: datetime, is_eod: bool) -> None:
    now_epoch = now_ist_epoch()
    session_date = now.date().isoformat()
    open_trade = db.get_open_pe_ce_crossover_trade(underlying, side)

    if open_trade:
        await _manage_open_trade(dhan, settings, open_trade, is_eod)
        _log(session_date, now_epoch, underlying, side, "IN_POSITION", None)
        return

    if is_eod:
        return

    expiry_info = await resolve_expiry_with_dte_policy(
        dhan, underlying_security_id(settings, underlying), override=settings.pe_ce_crossover_expiry_policy_override
    )
    if not expiry_info:
        _log(session_date, now_epoch, underlying, side, "BLOCKED", "no valid expiry available (DTE 0/1 with no next expiry listed)")
        return

    option = await resolve_atm_option(
        dhan,
        underlying_scrip=underlying_security_id(settings, underlying),
        expiry=expiry_info["expiry"],
        side=side,
        strike_step=STRIKE_STEP.get(underlying, 50.0),
    )
    if not option or not option.get("ltp"):
        _log(session_date, now_epoch, underlying, side, "BLOCKED", "ATM option chain data unavailable")
        return

    try:
        raw = await dhan.intraday_candles(
            option["securityId"], OPTION_SEGMENT, "OPTIDX", "1", now.date().isoformat(), now.date().isoformat()
        )
    except Exception:
        _log(session_date, now_epoch, underlying, side, "BLOCKED", "option candle fetch failed")
        return

    candles = sorted(raw, key=lambda c: c["time"])
    completed = [c for c in candles if c["time"] + 60 <= now_epoch]
    closes = [float(c["close"]) for c in completed]
    if len(closes) < EMA_SLOW_PERIOD + 2:
        _log(session_date, now_epoch, underlying, side, "NO_SIGNAL", "insufficient candle history")
        return

    ema_fast = ema(closes, EMA_FAST_PERIOD)
    ema_slow = ema(closes, EMA_SLOW_PERIOD)
    if ema_fast[-1] is None or ema_slow[-1] is None or ema_fast[-2] is None or ema_slow[-2] is None:
        _log(session_date, now_epoch, underlying, side, "NO_SIGNAL", "EMA warm-up incomplete")
        return

    crossed_up = ema_fast[-2] <= ema_slow[-2] and ema_fast[-1] > ema_slow[-1]
    closed_above_both = closes[-1] > ema_fast[-1] and closes[-1] > ema_slow[-1]

    if not (crossed_up and closed_above_both):
        state = "CANDIDATE" if ema_fast[-1] > ema_slow[-1] else "NO_SIGNAL"
        _log(session_date, now_epoch, underlying, side, state, None, ema_fast[-1], ema_slow[-1], closes[-1])
        return

    crossover_time = completed[-1]["time"]
    if _handled_crossover_time.get((underlying, side)) == crossover_time:
        return  # already acted on (or already logged) this exact crossover candle

    expansion = check_premium_expansion(
        closes, settings.pe_ce_crossover_premium_expansion_lookback_bars, settings.pe_ce_crossover_min_premium_expansion_percent
    )
    if not expansion["passed"]:
        _log(
            session_date, now_epoch, underlying, side, "WAITING_FOR_EXPANSION", expansion["reason"],
            ema_fast[-1], ema_slow[-1], closes[-1], expansion["value"],
        )
        return

    spread = check_spread(option.get("bid"), option.get("ask"), settings.pe_ce_crossover_max_spread_percent)
    if not spread["passed"]:
        _log(
            session_date, now_epoch, underlying, side, "BLOCKED", spread["reason"],
            ema_fast[-1], ema_slow[-1], closes[-1], expansion["value"], spread["value"],
        )
        return

    freshness = check_quote_freshness(crossover_time, now_epoch, settings.pe_ce_crossover_max_quote_age_seconds)
    if not freshness["passed"]:
        _log(
            session_date, now_epoch, underlying, side, "BLOCKED", freshness["reason"],
            ema_fast[-1], ema_slow[-1], closes[-1], expansion["value"], spread["value"],
        )
        return

    ok, reason = _guardrails_ok(settings, underlying, side, now_epoch, option["ltp"])
    if not ok:
        _log(
            session_date, now_epoch, underlying, side, "BLOCKED", reason,
            ema_fast[-1], ema_slow[-1], closes[-1], expansion["value"], spread["value"],
        )
        return

    try:
        lot_size = await resolve_lot_size_by_security_id(option["securityId"])
    except ScripMasterError:
        _log(session_date, now_epoch, underlying, side, "BLOCKED", "could not resolve current lot size from instrument master")
        return

    _handled_crossover_time[(underlying, side)] = crossover_time
    db.create_pe_ce_crossover_trade(
        underlying=underlying,
        side=side,
        strike=option["strike"],
        expiry=expiry_info["expiry"],
        dte=expiry_info["dte"],
        security_id=option["securityId"],
        exchange_segment=OPTION_SEGMENT,
        lots=settings.pe_ce_crossover_lots,
        lot_size=lot_size,
        entry_time=now_epoch,
        entry_premium=option["ltp"],
        stop_loss_percent=settings.pe_ce_crossover_stop_loss_percent,
        target_percent=settings.pe_ce_crossover_target_percent,
    )
    _log(
        session_date, now_epoch, underlying, side, "READY", None,
        ema_fast[-1], ema_slow[-1], closes[-1], expansion["value"], spread["value"],
    )
    logger.info("pe_ce_crossover: entered %s %s @ %s (strike %s, expiry %s)", underlying, side, option["ltp"], option["strike"], expiry_info["expiry"])


def _guardrails_ok(settings: Settings, underlying: str, side: str, now_epoch: int, entry_premium: float) -> tuple[bool, str]:
    start_of_day = _start_of_today_ist_epoch()

    if settings.pe_ce_crossover_position_mode == "total" and db.list_open_pe_ce_crossover_trades():
        return False, "one open position total is already active"

    last_exit = db.get_last_pe_ce_crossover_exit_time(underlying, side)
    if last_exit is not None and now_epoch - last_exit < settings.pe_ce_crossover_cooldown_minutes * 60:
        return False, f"cooldown active ({settings.pe_ce_crossover_cooldown_minutes}min after last exit)"

    trades_today = db.count_pe_ce_crossover_trades_today(underlying, side, start_of_day)
    if trades_today >= settings.pe_ce_crossover_max_trades_per_day:
        return False, f"max trades/day ({settings.pe_ce_crossover_max_trades_per_day}) reached"

    today_pnl = db.get_today_realized_pnl_pe_ce_crossover(start_of_day)
    if today_pnl <= -settings.pe_ce_crossover_max_daily_loss_rupees:
        return False, "max daily loss reached"

    cost_so_far = sum(
        t["entryPremium"] * t["lots"] * t["lotSize"] for t in db.list_open_pe_ce_crossover_trades()
    )
    incremental_cost = entry_premium * settings.pe_ce_crossover_lots
    if cost_so_far + incremental_cost > settings.pe_ce_crossover_max_capital_rupees:
        return False, "max capital deployed reached"

    return True, ""


async def _manage_open_trade(dhan: DhanService, settings: Settings, trade: dict[str, Any], is_eod: bool) -> None:
    try:
        quotes = await dhan.market_quotes_by_segment({trade["exchangeSegment"]: [int(trade["securityId"])]})
        current_premium = float(
            (quotes.get(trade["exchangeSegment"]) or {}).get(str(trade["securityId"]), {}).get("last_price") or 0
        )
    except Exception:
        return
    if not current_premium:
        return

    now_epoch = now_ist_epoch()

    if is_eod:
        _close(trade, exit_time=now_epoch, exit_premium=current_premium, exit_reason="eod")
        return

    entry_premium = trade["entryPremium"]
    stop_floor = entry_premium * (1 - trade["stopLossPercent"] / 100)
    target_ceiling = entry_premium * (1 + trade["targetPercent"] / 100)

    if current_premium <= stop_floor:
        _close(trade, exit_time=now_epoch, exit_premium=current_premium, exit_reason="stop_loss")
        return
    if current_premium >= target_ceiling:
        _close(trade, exit_time=now_epoch, exit_premium=current_premium, exit_reason="target")
        return

    peak = max(trade["peakPremium"] or entry_premium, current_premium)
    trail_stop = trade["trailStopPremium"]
    favorable_move_percent = (peak - entry_premium) / entry_premium * 100
    if trail_stop is not None or favorable_move_percent >= settings.pe_ce_crossover_trail_arm_percent:
        candidate = peak * (1 - settings.pe_ce_crossover_trail_percent / 100)
        trail_stop = candidate if trail_stop is None else max(trail_stop, candidate)  # only ever tightens upward

    db.update_pe_ce_crossover_trade_progress(trade["id"], peak_premium=peak, trail_stop_premium=trail_stop)

    if trail_stop is not None and current_premium <= trail_stop:
        _close(trade, exit_time=now_epoch, exit_premium=current_premium, exit_reason="trail_stop")
        return

    # EMA8 crossing back below EMA21 on the option's own candles.
    try:
        raw = await dhan.intraday_candles(
            trade["securityId"], trade["exchangeSegment"], "OPTIDX", "1", now_ist().date().isoformat(), now_ist().date().isoformat()
        )
        candles = sorted(raw, key=lambda c: c["time"])
        completed = [c for c in candles if c["time"] + 60 <= now_epoch]
        closes = [float(c["close"]) for c in completed]
        if len(closes) >= EMA_SLOW_PERIOD + 1:
            ema_fast = ema(closes, EMA_FAST_PERIOD)
            ema_slow = ema(closes, EMA_SLOW_PERIOD)
            if ema_fast[-1] is not None and ema_slow[-1] is not None and ema_fast[-1] < ema_slow[-1]:
                _close(trade, exit_time=now_epoch, exit_premium=current_premium, exit_reason="ema_cross_down")
    except Exception:
        pass


def _close(trade: dict[str, Any], *, exit_time: int, exit_premium: float, exit_reason: str) -> None:
    qty = trade["lots"] * trade["lotSize"]
    gross_pnl = (exit_premium - trade["entryPremium"]) * qty
    entry_charges = option_order_charges(
        premium=trade["entryPremium"], quantity=qty, side="BUY", exchange_segment=trade["exchangeSegment"]
    )
    exit_charges = option_order_charges(
        premium=exit_premium, quantity=qty, side="SELL", exchange_segment=trade["exchangeSegment"]
    )
    total_charges = round(entry_charges["total"] + exit_charges["total"], 2)
    realized_pnl = round(gross_pnl - total_charges, 2)
    db.close_pe_ce_crossover_trade(
        trade["id"], exit_time=exit_time, exit_premium=exit_premium, exit_reason=exit_reason,
        realized_pnl=realized_pnl, charges=total_charges,
    )
    logger.info("pe_ce_crossover: exit %s %s @ %s (%s) net pnl=₹%.2f", trade["underlying"], trade["side"], exit_premium, exit_reason, realized_pnl)


def _log(
    session_date: str,
    epoch: int,
    underlying: str,
    side: str,
    state: str,
    blocked_reason: str | None,
    ema_fast: float | None = None,
    ema_slow: float | None = None,
    premium: float | None = None,
    premium_expansion_percent: float | None = None,
    spread_percent: float | None = None,
) -> None:
    db.record_pe_ce_crossover_signal(
        session_date=session_date, epoch=epoch, underlying=underlying, side=side, state=state,
        blocked_reason=blocked_reason, ema_fast=ema_fast, ema_slow=ema_slow, premium=premium,
        premium_expansion_percent=premium_expansion_percent, spread_percent=spread_percent,
    )


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _start_of_today_ist_epoch() -> int:
    now = now_ist()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp())
