"""Crypto-Swing live/shadow trading engine.

Off by default. Reuses simulate_trades() -- the exact same function the
paper-trading panel already uses -- as the sole source of truth for "what
is the strategy doing right now": every poll re-runs the full historical
replay and looks only at whether its LAST trade is open or closed, and
compares that against what this engine last recorded. This means the
live engine can never disagree with what the paper-trading panel shows,
since there's only one implementation of the strategy's entry/exit
logic, not two that could drift apart.

Two independent flags gate anything happening at all:
  - crypto_swing_live_enabled: master switch. False (default) means this
    module's poll loop doesn't even start (see main.py).
  - crypto_swing_shadow_mode: True (default) means every decision is
    logged to crypto_swing_live_trades as if it happened, but
    DeltaExchangeService.place_order() is never called -- no real order,
    no real money. Only once both live_enabled=true AND shadow_mode=false
    does an order actually get sent.

Guardrails (checked before every new entry or pyramid add, live or
shadow -- shadow mode exists to prove these behave correctly before any
real money is at risk):
  - crypto_swing_max_concurrent_positions: caps open positions across all
    symbols combined.
  - crypto_swing_max_daily_loss_percent: once today's realized loss (IST
    calendar day) exceeds this fraction of the balance captured at the
    start of the day, no new entries -- existing positions still get
    managed (can still exit) but nothing new opens.
  - crypto_swing_min_margin_buffer_percent: refuses an entry if the
    estimated margin it would use leaves less than this percentage of
    available balance free.

Position sizing is risk-based (matching gamma_blast_risk_percent_per_trade
elsewhere in this app): risk crypto_swing_risk_percent_per_trade percent
of available balance against the distance from entry to the strategy's
own stop (the Supertrend level), not a flat notional -- so size scales
with both account size and how far away the stop actually is.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import Settings, get_settings
from app.core.timeutil import now_ist
from app.db import sqlite as db
from app.services.crypto_swing import SYMBOLS, load_indicators, simulate_trades
from app.services.delta_exchange import DeltaExchangeError, DeltaExchangeService

logger = logging.getLogger(__name__)

RESOLUTION = "30m"
# See _record_entry: a genuine stop closer than this (as a fraction of
# entry price) is floored to this value for sizing purposes only, so a
# noise-level stop distance can't imply an outsized position.
MIN_STOP_DISTANCE_FOR_SIZING = 0.01
MODE_SHADOW = "shadow"
MODE_LIVE = "live"

_product_cache: dict[str, dict[str, Any]] = {}


def _mode(settings: Settings) -> str:
    return MODE_LIVE if not settings.crypto_swing_shadow_mode else MODE_SHADOW


async def _get_product(delta: DeltaExchangeService, symbol: str) -> dict[str, Any]:
    if symbol not in _product_cache:
        _product_cache[symbol] = await delta.get_product(symbol)
    return _product_cache[symbol]


def start_of_today_ist_epoch() -> int:
    now = now_ist()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp())


async def _guardrails_ok(settings: Settings, delta: DeltaExchangeService, mode: str) -> tuple[bool, str]:
    if db.count_open_crypto_swing_live_trades(mode) >= settings.crypto_swing_max_concurrent_positions:
        return False, "max_concurrent_positions"

    today_pnl = db.get_today_realized_pnl_usd(mode, start_of_today_ist_epoch())
    try:
        balances = await delta.get_wallet_balances()
        usd = next((b for b in balances if b.get("asset_symbol") == "USD"), {})
        available = float(usd.get("available_balance") or 0)
    except Exception:
        return False, "wallet_lookup_failed"

    baseline = available - today_pnl  # approx capital at start of day
    if baseline > 0 and today_pnl < 0 and abs(today_pnl) / baseline * 100 >= settings.crypto_swing_max_daily_loss_percent:
        return False, "max_daily_loss"

    return True, ""


async def evaluate_symbol(symbol: str, settings: Settings) -> None:
    mode = _mode(settings)
    delta = DeltaExchangeService(settings)

    try:
        bundle = await load_indicators(symbol, RESOLUTION)
    except DeltaExchangeError as exc:
        logger.warning("crypto_swing_live: candle fetch failed for %s: %s", symbol, exc)
        return

    sim_trades = simulate_trades(
        bundle.ordered, bundle.ema200, bundle.macd_line, bundle.signal_line, bundle.histogram, bundle.st_values, bundle.st_directions
    )
    latest = sim_trades[-1] if sim_trades else None
    db_open = db.get_open_crypto_swing_live_trade(symbol, mode)

    strategy_has_position = latest is not None and latest["status"] == "open"

    if not strategy_has_position:
        if db_open:
            # The strategy's own history no longer ends in an open trade
            # -- it closed. The most recently CLOSED sim trade for this
            # side is that exit; use it to close our record too.
            closed = next((t for t in reversed(sim_trades) if t["status"] == "closed" and t["side"] == db_open["side"]), None)
            if closed:
                await _record_exit(db_open, closed, mode)
        return

    if db_open and db_open["side"] == latest["side"]:
        if latest["tranches"] > db_open["tranches"]:
            await _record_pyramid(symbol, latest, db_open, settings, delta, mode)
        return

    if db_open and db_open["side"] != latest["side"]:
        # Shouldn't happen -- simulate_trades always fully closes before a
        # new opposite entry -- but if history and our record disagree,
        # don't silently act on a stale side.
        logger.error("crypto_swing_live: %s side mismatch, db=%s sim=%s -- skipping", symbol, db_open["side"], latest["side"])
        return

    await _record_entry(symbol, latest, settings, delta, mode)


async def _record_entry(symbol: str, latest: dict[str, Any], settings: Settings, delta: DeltaExchangeService, mode: str) -> None:
    ok, reason = await _guardrails_ok(settings, delta, mode)
    if not ok:
        logger.info("crypto_swing_live: entry blocked for %s (%s)", symbol, reason)
        return

    try:
        balances = await delta.get_wallet_balances()
        usd = next((b for b in balances if b.get("asset_symbol") == "USD"), {})
        available = float(usd.get("available_balance") or 0)
        product = await _get_product(delta, symbol)
    except Exception as exc:
        logger.warning("crypto_swing_live: sizing lookup failed for %s: %s", symbol, exc)
        return

    entry_price = float(latest["entryPrice"])
    stop = latest.get("stopLoss") or entry_price
    stop_distance_fraction = abs(entry_price - stop) / entry_price
    if stop_distance_fraction <= 0:
        return
    # Risk-based sizing (risk$ / stop-distance) blows up when the stop
    # happens to sit very close to entry -- seen live in testing: a 0.19%
    # XAUTUSD stop distance sized a $2,191 notional on a $413 account (5x
    # total capital), because a tighter stop mathematically "justifies" a
    # bigger position for the same dollar risk. That's a degenerate input,
    # not a real edge -- a fresh Supertrend flip can sit arbitrarily close
    # to price. Flooring the distance used for sizing (not the real stop
    # itself, which still governs the actual exit) keeps a noise-level
    # stop from implying outsized size.
    stop_distance_fraction = max(stop_distance_fraction, MIN_STOP_DISTANCE_FOR_SIZING)

    risk_amount = available * settings.crypto_swing_risk_percent_per_trade / 100
    notional_usd = risk_amount / stop_distance_fraction
    # Backstop regardless of the above: never let one position's notional
    # exceed available capital -- i.e. at most 1x effective exposure, well
    # under whatever leverage is configured, leaving real margin headroom.
    notional_usd = min(notional_usd, available)

    contract_value = float(product.get("contract_value") or 0)
    product_id = product.get("id")
    if not contract_value or not product_id:
        logger.warning("crypto_swing_live: missing product spec for %s -- skipping entry", symbol)
        return

    size_contracts = max(1, round((notional_usd / entry_price) / contract_value))
    est_margin = notional_usd / float(settings.crypto_swing_leverage)
    if est_margin > available * (1 - settings.crypto_swing_min_margin_buffer_percent / 100):
        logger.info("crypto_swing_live: entry blocked for %s (min_margin_buffer)", symbol)
        return

    order_id = None
    note = f"shadow: would {latest['side']} {size_contracts} contracts (~${notional_usd:.2f}) @ {entry_price}"
    if mode == MODE_LIVE:
        side = "buy" if latest["side"] == "long" else "sell"
        await delta.set_leverage(product_id, settings.crypto_swing_leverage)
        result = await delta.place_order(product_id, size_contracts, side)
        order_id = str(result.get("id")) if result.get("id") else None
        note = f"live order placed: {result}"

    db.create_crypto_swing_live_trade(
        symbol=symbol,
        side=latest["side"],
        mode=mode,
        entry_time=latest["entryTime"],
        entry_price=entry_price,
        size_contracts=size_contracts,
        notional_usd=notional_usd,
        stop_loss=stop,
        order_id=order_id,
        note=note,
    )
    logger.info("crypto_swing_live: %s entry recorded (%s) -- %s", symbol, mode, note)


async def _record_pyramid(
    symbol: str, latest: dict[str, Any], db_open: dict[str, Any], settings: Settings, delta: DeltaExchangeService, mode: str
) -> None:
    ok, reason = await _guardrails_ok(settings, delta, mode)
    if not ok:
        logger.info("crypto_swing_live: pyramid add blocked for %s (%s)", symbol, reason)
        return
    # Same-sized add as the initial tranche, keeping sizing simple and
    # consistent rather than re-deriving a fresh risk calc mid-trade.
    add_contracts = max(1, round(db_open["sizeContracts"] / db_open["tranches"]))
    add_notional = db_open["notionalUsd"] / db_open["tranches"]

    if mode == MODE_LIVE:
        product = await _get_product(delta, symbol)
        side = "buy" if latest["side"] == "long" else "sell"
        await delta.place_order(product["id"], add_contracts, side)

    db.add_crypto_swing_live_tranche(db_open["id"], size_contracts=add_contracts, notional_usd=add_notional)
    logger.info("crypto_swing_live: %s pyramid add recorded (%s)", symbol, mode)


async def _record_exit(db_open: dict[str, Any], closed_sim_trade: dict[str, Any], mode: str) -> None:
    pnl_pct = closed_sim_trade["pnlPercent"] or 0.0
    pnl_usd = pnl_pct / 100 * db_open["notionalUsd"]

    if mode == MODE_LIVE:
        delta = DeltaExchangeService()
        product = await _get_product(delta, db_open["symbol"])
        side = "sell" if db_open["side"] == "long" else "buy"
        await delta.place_order(product["id"], db_open["sizeContracts"], side, reduce_only=True)

    db.close_crypto_swing_live_trade(
        db_open["id"],
        exit_time=closed_sim_trade["exitTime"],
        exit_price=closed_sim_trade["exitPrice"],
        exit_reason=closed_sim_trade["exitReason"],
        pnl_usd=pnl_usd,
    )
    logger.info("crypto_swing_live: %s exit recorded (%s) pnl=$%.2f", db_open["symbol"], mode, pnl_usd)


async def _loop() -> None:
    settings = get_settings()
    interval = settings.crypto_swing_live_poll_interval_seconds
    while True:
        try:
            settings = get_settings()
            if settings.crypto_swing_live_enabled:
                for symbol in SYMBOLS:
                    await evaluate_symbol(symbol, settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("crypto_swing_live: poll iteration failed")
        await asyncio.sleep(interval)


def start_crypto_swing_live_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.crypto_swing_live_enabled:
        return None
    return asyncio.create_task(_loop())


async def stop_crypto_swing_live_task(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
