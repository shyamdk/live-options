"""Nifty-Swing live/shadow trading engine -- mirrors crypto_swing_live.py's
design exactly (see that module's docstring for the full rationale): reuses
simulate_trades() as the sole source of truth for "what is the strategy
doing right now," diffing its last trade against what this engine last
recorded, so the live engine can never disagree with the paper-trading
panel.

Two independent flags gate anything happening at all:
  - nifty_swing_live_enabled: master switch. False (default) means this
    module's poll loop doesn't even start (see main.py).
  - nifty_swing_shadow_mode: True (default) means every decision is logged
    to nifty_swing_live_trades as if it happened, but
    DhanOrderService.place_market_order() is never called -- no real
    order, no real money. Only once both live_enabled=true AND
    shadow_mode=false does an order actually get sent. A third, global
    kill-switch (settings.live_order_enabled) also gates every order at
    the DhanOrderService layer itself, independent of these two.

Unlike crypto's leveraged, risk-percent-of-wallet sizing, this is a flat
cash purchase: size is always nifty_swing_live_quantity_per_tranche shares,
directly, no formula -- matching the paper strategy's own fixed tranche
quantity. Guardrails (checked before every new entry or pyramid add, live
or shadow):
  - nifty_swing_live_max_capital_rupees: refuses an entry/add that would
    push this position's total cost basis over this rupee ceiling. There's
    no Dhan fund-limit lookup wired into this codebase to check available
    balance against (unlike crypto's wallet balance check), so this is a
    fixed configured cap rather than a percentage of anything live.
  - nifty_swing_live_max_daily_loss_rupees: once today's realized loss
    (IST calendar day) in this mode reaches this rupee amount, no new
    entries -- an existing open position can still exit.

Order-result handling is intentionally conservative given real-world
settlement risk (NIFTYBEES bought CNC settles T+1 -- whether Dhan allows
selling still-settling shares the same day is a brokerage mechanics
question this code doesn't assume an answer to): a DB row is only ever
created/grown on a *sent* order (or in shadow mode), and only ever closed
on a *sent* exit order. A blocked/failed/rejected order leaves the DB
state exactly as it was and logs the reason -- the next poll's diff against
simulate_trades' history will simply retry, rather than this code ever
recording a position that doesn't actually exist at the broker.

Only polls within the actual trading session (nifty_swing_live_session_
start/end_time) on weekdays -- no separate opening-minutes entry delay
like pStrategy-Nifty's, since this strategy's 30m/1h candles can't confirm
a fresh signal before a candle closes (earliest possible: 9:45 for the
first bar of the day), already well past the opening volatility window.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import Settings, get_settings
from app.core.timeutil import in_time_window, now_ist
from app.db import sqlite as db
from app.services.crypto_swing import simulate_trades
from app.services.crypto_swing_live import start_of_today_ist_epoch
from app.services.nifty_swing import EQUITY_SEGMENT, get_security_id, load_indicators
from app.services.orders import DhanOrderService

logger = logging.getLogger(__name__)

MODE_SHADOW = "shadow"
MODE_LIVE = "live"


def _mode(settings: Settings) -> str:
    return MODE_LIVE if not settings.nifty_swing_shadow_mode else MODE_SHADOW


def _guardrails_ok(settings: Settings, mode: str, cost_so_far: float, incremental_cost: float) -> tuple[bool, str]:
    if cost_so_far + incremental_cost > settings.nifty_swing_live_max_capital_rupees:
        return False, "max_capital"

    today_pnl = db.get_today_realized_pnl_inr(mode, start_of_today_ist_epoch())
    if today_pnl <= -settings.nifty_swing_live_max_daily_loss_rupees:
        return False, "max_daily_loss"

    return True, ""


async def evaluate(settings: Settings) -> None:
    mode = _mode(settings)
    resolution = settings.nifty_swing_live_resolution

    try:
        bundle = await load_indicators(resolution)
    except Exception as exc:
        logger.warning("nifty_swing_live: candle fetch failed: %s", exc)
        return

    sim_trades = simulate_trades(
        bundle.ordered,
        bundle.ema200,
        bundle.macd_line,
        bundle.signal_line,
        bundle.histogram,
        bundle.st_values,
        bundle.st_directions,
        bundle.atr_values,
        allow_short=False,
        quantity_per_tranche=settings.nifty_swing_live_quantity_per_tranche,
    )
    latest = sim_trades[-1] if sim_trades else None
    db_open = db.get_open_nifty_swing_live_trade(mode)

    strategy_has_position = latest is not None and latest["status"] == "open"

    if not strategy_has_position:
        if db_open:
            closed = next((t for t in reversed(sim_trades) if t["status"] == "closed" and t["side"] == db_open["side"]), None)
            if closed:
                await _record_exit(db_open, closed, mode, settings)
        return

    if db_open and db_open["side"] == latest["side"]:
        if latest["tranches"] > db_open["tranches"]:
            await _record_pyramid(latest, db_open, settings, mode)
        return

    if db_open and db_open["side"] != latest["side"]:
        # Shouldn't happen -- simulate_trades always fully closes before a
        # new opposite entry (and Nifty-Swing is long-only in the first
        # place) -- but don't silently act on a stale side if it does.
        logger.error("nifty_swing_live: side mismatch, db=%s sim=%s -- skipping", db_open["side"], latest["side"])
        return

    await _record_entry(latest, settings, mode)


async def _record_entry(latest: dict[str, Any], settings: Settings, mode: str) -> None:
    entry_price = float(latest["entryPrice"])
    quantity = int(latest["quantity"])
    incremental_cost = entry_price * quantity

    ok, reason = _guardrails_ok(settings, mode, cost_so_far=0.0, incremental_cost=incremental_cost)
    if not ok:
        logger.info("nifty_swing_live: entry blocked (%s)", reason)
        return

    order_id = None
    note = f"shadow: would BUY {quantity} NIFTYBEES (~₹{incremental_cost:.2f}) @ {entry_price}"
    if mode == MODE_LIVE:
        result = await _place_order("BUY", quantity, settings)
        if result["status"] != "sent":
            logger.warning("nifty_swing_live: entry order not sent (%s): %s", result["status"], result.get("message"))
            return
        order_id = _order_id(result)
        note = f"live order placed: {result['order']}"

    db.create_nifty_swing_live_trade(
        side=latest["side"],
        mode=mode,
        entry_time=latest["entryTime"],
        entry_price=entry_price,
        quantity=quantity,
        stop_loss=latest.get("stopLoss"),
        order_id=order_id,
        note=note,
    )
    logger.info("nifty_swing_live: entry recorded (%s) -- %s", mode, note)


async def _record_pyramid(latest: dict[str, Any], db_open: dict[str, Any], settings: Settings, mode: str) -> None:
    add_quantity = max(1, round(db_open["quantity"] / db_open["tranches"]))
    add_price = float(latest["entryPrice"])
    incremental_cost = add_price * add_quantity
    cost_so_far = db_open["quantity"] * db_open["entryPrice"]

    ok, reason = _guardrails_ok(settings, mode, cost_so_far=cost_so_far, incremental_cost=incremental_cost)
    if not ok:
        logger.info("nifty_swing_live: pyramid add blocked (%s)", reason)
        return

    if mode == MODE_LIVE:
        result = await _place_order("BUY", add_quantity, settings)
        if result["status"] != "sent":
            logger.warning("nifty_swing_live: pyramid order not sent (%s): %s", result["status"], result.get("message"))
            return

    db.add_nifty_swing_live_tranche(db_open["id"], quantity=add_quantity)
    logger.info("nifty_swing_live: pyramid add recorded (%s), +%s shares", mode, add_quantity)


async def _record_exit(db_open: dict[str, Any], closed_sim_trade: dict[str, Any], mode: str, settings: Settings) -> None:
    pnl_pct = closed_sim_trade["pnlPercent"] or 0.0
    pnl_inr = pnl_pct / 100 * db_open["entryPrice"] * db_open["quantity"]

    if mode == MODE_LIVE:
        result = await _place_order("SELL", db_open["quantity"], settings)
        if result["status"] != "sent":
            # Left open deliberately -- see module docstring on same-day CNC
            # settlement risk. The next poll retries; this trade must never
            # be marked closed without a confirmed sell.
            logger.warning(
                "nifty_swing_live: exit order not sent (%s): %s -- trade #%s left open, will retry",
                result["status"],
                result.get("message"),
                db_open["id"],
            )
            return

    db.close_nifty_swing_live_trade(
        db_open["id"],
        exit_time=closed_sim_trade["exitTime"],
        exit_price=closed_sim_trade["exitPrice"],
        exit_reason=closed_sim_trade["exitReason"],
        pnl_inr=pnl_inr,
    )
    logger.info("nifty_swing_live: exit recorded (%s) pnl=₹%.2f", mode, pnl_inr)


async def _place_order(transaction_type: str, quantity: int, settings: Settings) -> dict[str, Any]:
    security_id = await get_security_id()
    return await DhanOrderService(settings).place_market_order(
        transaction_type=transaction_type,
        exchange_segment=EQUITY_SEGMENT,
        security_id=security_id,
        quantity=quantity,
        correlation_id=f"nifty-swing-{transaction_type.lower()}",
        product_type=settings.nifty_swing_live_product_type,
    )


def _order_id(result: dict[str, Any]) -> str | None:
    order = result.get("order")
    if isinstance(order, dict):
        order_id = order.get("orderId") or order.get("order_id")
        return str(order_id) if order_id else None
    return None


async def _loop() -> None:
    settings = get_settings()
    interval = settings.nifty_swing_live_poll_interval_seconds
    while True:
        try:
            settings = get_settings()
            now = now_ist()
            in_hours = in_time_window(
                now.time(), settings.nifty_swing_live_session_start_time, settings.nifty_swing_live_session_end_time
            )
            if settings.nifty_swing_live_enabled and in_hours and now.weekday() < 5:
                await evaluate(settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("nifty_swing_live: poll iteration failed")
        await asyncio.sleep(interval)


def start_nifty_swing_live_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.nifty_swing_live_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_nifty_swing_live_task(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
