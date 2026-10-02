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
from app.services.crypto_indicators import adx, ema, rsi
from app.services.dhan import DhanService
from app.services.dhan_scrip_master import ScripMasterError, resolve_lot_size_by_security_id
from app.services.ema5_instruments import resolve_atm_option
from app.services.orders import DhanOrderService
from app.services.pe_ce_expiry import resolve_expiry_with_dte_policy
from app.services.pe_ce_filters import check_premium_expansion, check_quote_freshness, check_spread
from app.services.telegram import TelegramNotifier

logger = logging.getLogger(__name__)

OPTION_SEGMENT = "NSE_FNO"
INDEX_SEGMENT = "IDX_I"
STRIKE_STEP = {"NIFTY": 50.0, "BANKNIFTY": 100.0, "SENSEX": 100.0}
EMA_FAST_PERIOD = 8
EMA_SLOW_PERIOD = 21
RSI_PERIOD = 14
ADX_PERIOD = 14
SIDES = ("CE", "PE")
ORDER_TIMEOUT_SECONDS = 20

# Runtime-toggleable filters (spec Section 6's gates), stored in
# pe_ce_crossover_settings rather than .env -- editable from the UI without
# a backend restart, unlike the rest of this strategy's config. Default ON
# (unset == enabled) so deploying this doesn't change today's live behavior;
# a user must explicitly turn one off. When disabled, the computed value is
# still logged for visibility, it just no longer blocks an entry.
PREMIUM_EXPANSION_FILTER_SETTING_KEY = "premium_expansion_filter_enabled"
SPREAD_FILTER_SETTING_KEY = "spread_filter_enabled"

_handled_crossover_time: dict[tuple[str, str], int | None] = {}
_handled_date: str | None = None
# Phase 2 position reconciliation: (underlying, side) -> True while a
# broker/DB quantity mismatch on an open live trade is unresolved. New live
# entries on that side are refused until a subsequent check matches again.
_reconciliation_blocked: dict[tuple[str, str], bool] = {}


def current_mode(settings: Settings) -> str:
    """"paper" unless live_enabled; then "shadow" or "live" per shadow_mode.
    A real order additionally still requires the global live_order_enabled
    kill switch (see DhanOrderService.place_market_order)."""
    if not settings.pe_ce_crossover_live_enabled:
        return "paper"
    return "shadow" if settings.pe_ce_crossover_shadow_mode else "live"


def _setting_bool(key: str, default: bool = True) -> bool:
    raw = db.get_pe_ce_crossover_setting(key)
    return default if raw is None else raw == "1"


def is_premium_expansion_filter_enabled() -> bool:
    return _setting_bool(PREMIUM_EXPANSION_FILTER_SETTING_KEY)


def is_spread_filter_enabled() -> bool:
    return _setting_bool(SPREAD_FILTER_SETTING_KEY)


def set_premium_expansion_filter_enabled(value: bool) -> None:
    db.set_pe_ce_crossover_setting(PREMIUM_EXPANSION_FILTER_SETTING_KEY, "1" if value else "0")


def set_spread_filter_enabled(value: bool) -> None:
    db.set_pe_ce_crossover_setting(SPREAD_FILTER_SETTING_KEY, "1" if value else "0")


def get_runtime_config() -> dict[str, bool]:
    return {
        "premiumExpansionFilterEnabled": is_premium_expansion_filter_enabled(),
        "spreadFilterEnabled": is_spread_filter_enabled(),
    }


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

    if settings.pe_ce_crossover_live_enabled:
        try:
            await _reconcile_positions(dhan, settings)
        except Exception:
            logger.exception("pe_ce_crossover: position reconciliation failed")

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

    # RSI/ADX are informational only -- displayed for visibility into entry
    # conditions, not a gating filter (the spec's own filters are EMA
    # crossover + premium expansion + spread + freshness, checked below).
    current_rsi = rsi(closes, RSI_PERIOD)[-1]
    current_adx = adx(completed, ADX_PERIOD)[-1]

    crossed_up = ema_fast[-2] <= ema_slow[-2] and ema_fast[-1] > ema_slow[-1]
    closed_above_both = closes[-1] > ema_fast[-1] and closes[-1] > ema_slow[-1]

    if not (crossed_up and closed_above_both):
        state = "CANDIDATE" if ema_fast[-1] > ema_slow[-1] else "NO_SIGNAL"
        _log(
            session_date, now_epoch, underlying, side, state, None, ema_fast[-1], ema_slow[-1], closes[-1],
            rsi=current_rsi, adx=current_adx,
        )
        return

    crossover_time = completed[-1]["time"]
    if _handled_crossover_time.get((underlying, side)) == crossover_time:
        return  # already acted on (or already logged) this exact crossover candle

    # Premium expansion and spread are optionally-gating: the computed value
    # is always logged for visibility (spec: "show values"), but only
    # blocks entry while its toggle (pe_ce_crossover_settings, editable from
    # the UI, default on) is enabled.
    expansion = check_premium_expansion(
        closes, settings.pe_ce_crossover_premium_expansion_lookback_bars, settings.pe_ce_crossover_min_premium_expansion_percent
    )
    if is_premium_expansion_filter_enabled() and not expansion["passed"]:
        _log(
            session_date, now_epoch, underlying, side, "WAITING_FOR_EXPANSION", expansion["reason"],
            ema_fast[-1], ema_slow[-1], closes[-1], expansion["value"], rsi=current_rsi, adx=current_adx,
        )
        return

    spread = check_spread(option.get("bid"), option.get("ask"), settings.pe_ce_crossover_max_spread_percent)
    if is_spread_filter_enabled() and not spread["passed"]:
        _log(
            session_date, now_epoch, underlying, side, "BLOCKED", spread["reason"],
            ema_fast[-1], ema_slow[-1], closes[-1], expansion["value"], spread["value"], current_rsi, current_adx,
        )
        return

    freshness = check_quote_freshness(crossover_time, now_epoch, settings.pe_ce_crossover_max_quote_age_seconds)
    if not freshness["passed"]:
        _log(
            session_date, now_epoch, underlying, side, "BLOCKED", freshness["reason"],
            ema_fast[-1], ema_slow[-1], closes[-1], expansion["value"], spread["value"], current_rsi, current_adx,
        )
        return

    mode = current_mode(settings)

    ok, reason = _guardrails_ok(settings, underlying, side, now_epoch, option["ltp"], mode)
    if not ok:
        _log(
            session_date, now_epoch, underlying, side, "BLOCKED", reason,
            ema_fast[-1], ema_slow[-1], closes[-1], expansion["value"], spread["value"], current_rsi, current_adx,
        )
        if mode != "paper":
            await _notify(
                settings,
                f"PE-CE Crossover would have entered {underlying} {side} {option['strike']:g} @ {option['ltp']:g} "
                f"but was BLOCKED ({mode}): {reason}",
            )
        return

    try:
        lot_size = await resolve_lot_size_by_security_id(option["securityId"])
    except ScripMasterError:
        _log(session_date, now_epoch, underlying, side, "BLOCKED", "could not resolve current lot size from instrument master")
        return

    quantity = settings.pe_ce_crossover_lots * lot_size
    entry_premium = option["ltp"]
    entry_order_id: str | None = None
    note: str | None = None

    if mode == "live":
        result = await _place_order(
            "BUY", option["securityId"], quantity, settings, f"pcx-{underlying}-{side}-entry-{now_epoch}"
        )
        status = str(result.get("status") or "unknown")
        if status != "sent":
            message = str(result.get("message") or "order not sent")
            logger.warning("pe_ce_crossover: LIVE entry not sent (%s) for %s %s: %s", status, underlying, side, message)
            await _notify(settings, f"🚨 PE-CE Crossover LIVE entry FAILED {underlying} {side}: {message}")
            _log(
                session_date, now_epoch, underlying, side, "BLOCKED", f"live order not sent: {message}",
                ema_fast[-1], ema_slow[-1], closes[-1], expansion["value"], spread["value"], current_rsi, current_adx,
            )
            return  # not marked handled -- next poll retries within the freshness window
        order = result.get("order") or {}
        entry_premium = _number(order.get("price")) or option["ltp"]
        entry_order_id = _order_id(result)
    elif mode == "shadow":
        note = f"shadow: would BUY {quantity} {underlying} {side} {option['strike']:g} @ {option['ltp']:g}"

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
        entry_premium=entry_premium,
        stop_loss_percent=settings.pe_ce_crossover_stop_loss_percent,
        target_percent=settings.pe_ce_crossover_target_percent,
        mode=mode,
        entry_order_id=entry_order_id,
        note=note,
    )
    _log(
        session_date, now_epoch, underlying, side, "READY", None,
        ema_fast[-1], ema_slow[-1], closes[-1], expansion["value"], spread["value"], current_rsi, current_adx,
    )
    logger.info(
        "pe_ce_crossover: entered %s %s @ %s (%s, strike %s, expiry %s)",
        underlying, side, entry_premium, mode, option["strike"], expiry_info["expiry"],
    )
    await _notify(
        settings,
        f"{'✅' if mode != 'shadow' else '🟡'} PE-CE Crossover {mode.upper()} entry: {underlying} {side} "
        f"{option['strike']:g} @ {entry_premium:g}, expiry {expiry_info['expiry']}",
    )


def _guardrails_ok(
    settings: Settings, underlying: str, side: str, now_epoch: int, entry_premium: float, mode: str
) -> tuple[bool, str]:
    if mode == "live" and _reconciliation_blocked.get((underlying, side)):
        return False, "position reconciliation mismatch on this side, entries paused"

    start_of_day = _start_of_today_ist_epoch()

    if settings.pe_ce_crossover_position_mode == "total" and db.list_open_pe_ce_crossover_trades(mode):
        return False, "one open position total is already active"

    last_exit = db.get_last_pe_ce_crossover_exit_time(underlying, side, mode)
    if last_exit is not None and now_epoch - last_exit < settings.pe_ce_crossover_cooldown_minutes * 60:
        return False, f"cooldown active ({settings.pe_ce_crossover_cooldown_minutes}min after last exit)"

    trades_today = db.count_pe_ce_crossover_trades_today(underlying, side, start_of_day, mode)
    if trades_today >= settings.pe_ce_crossover_max_trades_per_day:
        return False, f"max trades/day ({settings.pe_ce_crossover_max_trades_per_day}) reached"

    today_pnl = db.get_today_realized_pnl_pe_ce_crossover(start_of_day, mode)
    if today_pnl <= -settings.pe_ce_crossover_max_daily_loss_rupees:
        return False, "max daily loss reached"

    cost_so_far = sum(
        t["entryPremium"] * t["lots"] * t["lotSize"] for t in db.list_open_pe_ce_crossover_trades(mode)
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
        await _close(settings, trade, exit_time=now_epoch, exit_premium=current_premium, exit_reason="eod")
        return

    entry_premium = trade["entryPremium"]
    stop_floor = entry_premium * (1 - trade["stopLossPercent"] / 100)
    target_ceiling = entry_premium * (1 + trade["targetPercent"] / 100)

    if current_premium <= stop_floor:
        await _close(settings, trade, exit_time=now_epoch, exit_premium=current_premium, exit_reason="stop_loss")
        return
    if current_premium >= target_ceiling:
        await _close(settings, trade, exit_time=now_epoch, exit_premium=current_premium, exit_reason="target")
        return

    peak = max(trade["peakPremium"] or entry_premium, current_premium)
    trail_stop = trade["trailStopPremium"]
    favorable_move_percent = (peak - entry_premium) / entry_premium * 100
    if trail_stop is not None or favorable_move_percent >= settings.pe_ce_crossover_trail_arm_percent:
        candidate = peak * (1 - settings.pe_ce_crossover_trail_percent / 100)
        trail_stop = candidate if trail_stop is None else max(trail_stop, candidate)  # only ever tightens upward

    db.update_pe_ce_crossover_trade_progress(trade["id"], peak_premium=peak, trail_stop_premium=trail_stop)

    if trail_stop is not None and current_premium <= trail_stop:
        await _close(settings, trade, exit_time=now_epoch, exit_premium=current_premium, exit_reason="trail_stop")
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
                await _close(settings, trade, exit_time=now_epoch, exit_premium=current_premium, exit_reason="ema_cross_down")
    except Exception:
        pass


async def _close(settings: Settings, trade: dict[str, Any], *, exit_time: int, exit_premium: float, exit_reason: str) -> None:
    mode = trade["mode"]
    qty = trade["lots"] * trade["lotSize"]
    exit_order_id: str | None = None
    exit_note: str | None = None

    if mode == "live":
        result = await _place_order(
            "SELL", trade["securityId"], qty, settings, f"pcx-{trade['underlying']}-{trade['side']}-exit-{trade['id']}"
        )
        status = str(result.get("status") or "unknown")
        if status != "sent":
            message = str(result.get("message") or "order not sent")
            # Left open deliberately -- never mark a position closed without
            # a confirmed sell. The next poll's exit check retries.
            logger.warning(
                "pe_ce_crossover: LIVE exit not sent (%s) for trade #%s: %s -- left open, will retry",
                status, trade["id"], message,
            )
            await _notify(settings, f"🚨 PE-CE Crossover LIVE exit FAILED, position #{trade['id']} still open: {message}")
            return
        order = result.get("order") or {}
        exit_premium = _number(order.get("price")) or exit_premium
        exit_order_id = _order_id(result)
    elif mode == "shadow":
        exit_note = f"shadow: would SELL {qty} @ {exit_premium:g} ({exit_reason})"

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
        realized_pnl=realized_pnl, charges=total_charges, exit_order_id=exit_order_id, exit_note=exit_note,
    )
    logger.info(
        "pe_ce_crossover: exit %s %s @ %s (%s, %s) net pnl=₹%.2f",
        trade["underlying"], trade["side"], exit_premium, exit_reason, mode, realized_pnl,
    )
    await _notify(
        settings,
        f"{'✅' if realized_pnl >= 0 else '🔻'} PE-CE Crossover {mode.upper()} exit: {trade['underlying']} {trade['side']} "
        f"{exit_reason} @ {exit_premium:g}, net P&L ₹{realized_pnl:,.2f}",
    )


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
    rsi: float | None = None,
    adx: float | None = None,
) -> None:
    db.record_pe_ce_crossover_signal(
        session_date=session_date, epoch=epoch, underlying=underlying, side=side, state=state,
        blocked_reason=blocked_reason, ema_fast=ema_fast, ema_slow=ema_slow, premium=premium,
        premium_expansion_percent=premium_expansion_percent, spread_percent=spread_percent,
        rsi=rsi, adx=adx,
    )


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _start_of_today_ist_epoch() -> int:
    now = now_ist()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp())


async def _place_order(
    transaction_type: str, security_id: str, quantity: int, settings: Settings, correlation_id: str
) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(
            DhanOrderService(settings).place_market_order(
                transaction_type=transaction_type,
                exchange_segment=OPTION_SEGMENT,
                security_id=security_id,
                quantity=quantity,
                correlation_id=correlation_id,
                product_type=settings.pe_ce_crossover_live_order_product_type,
            ),
            timeout=ORDER_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return {"status": "failed", "message": f"order request timed out after {ORDER_TIMEOUT_SECONDS}s", "order": None}


def _order_id(result: dict[str, Any]) -> str | None:
    order = result.get("order")
    if isinstance(order, dict):
        order_id = order.get("orderId") or order.get("order_id")
        return str(order_id) if order_id else None
    return None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def _notify(settings: Settings, text: str) -> None:
    if not settings.pe_ce_crossover_telegram_alerts_enabled:
        return
    try:
        await TelegramNotifier(settings).send(text)
    except Exception:
        logger.exception("pe_ce_crossover: telegram notify failed")


async def _reconcile_positions(dhan: DhanService, settings: Settings) -> None:
    """Compares each open mode="live" trade's expected quantity against
    Dhan's own /positions for that security_id. Never auto-corrects DB or
    broker state on a mismatch -- only alerts and blocks new entries on that
    (underlying, side) until a later check matches again."""
    live_trades = db.list_open_pe_ce_crossover_trades("live")
    if not live_trades:
        return

    try:
        positions = await dhan.positions()
    except Exception:
        logger.warning("pe_ce_crossover: reconciliation skipped, positions() fetch failed")
        return

    net_qty_by_security_id: dict[str, int] = {}
    for p in positions:
        sid = str(p.get("securityId") or p.get("security_id") or "")
        if not sid:
            continue
        qty = p.get("netQty")
        if qty is None:
            qty = p.get("netQuantity", p.get("net_qty", 0))
        net_qty_by_security_id[sid] = net_qty_by_security_id.get(sid, 0) + int(_number(qty) or 0)

    for trade in live_trades:
        key = (trade["underlying"], trade["side"])
        expected_qty = trade["lots"] * trade["lotSize"]
        actual_qty = net_qty_by_security_id.get(str(trade["securityId"]), 0)
        mismatched = actual_qty != expected_qty
        was_blocked = _reconciliation_blocked.get(key, False)

        if mismatched and not was_blocked:
            logger.error(
                "pe_ce_crossover: RECONCILIATION MISMATCH %s %s trade #%s -- DB expects %s, broker shows %s",
                trade["underlying"], trade["side"], trade["id"], expected_qty, actual_qty,
            )
            await _notify(
                settings,
                f"🚨 PE-CE Crossover reconciliation mismatch: {trade['underlying']} {trade['side']} trade #{trade['id']} "
                f"-- DB expects {expected_qty}, broker shows {actual_qty}. New live entries on this side are paused.",
            )
        elif not mismatched and was_blocked:
            logger.info("pe_ce_crossover: reconciliation restored for %s %s", *key)
            await _notify(settings, f"✅ PE-CE Crossover reconciliation restored: {trade['underlying']} {trade['side']}.")

        _reconciliation_blocked[key] = mismatched
