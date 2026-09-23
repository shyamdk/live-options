"""Backtest/replay for PE-CE Crossover, using the OPTION'S OWN historical
premium candles (spec Section 12: "Backtest the actual option contracts
and premiums, not merely index signals").

Real constraint, stated rather than glossed over: Dhan has no "option chain
as of a past date" endpoint (verified during design -- see
atm_ce_pe_premium_crossover_codex_spec.md's own review). A strike's
security_id is assigned once when its contract is listed and never
changes for that expiry's life, so a SINGLE CURRENT option_chain() call
gives a valid strike->security_id map for any date within that expiry's
own lifetime -- but this means a backtest can only cover an expiry that
is still listed (current or very recently past), not an arbitrary
historical date range spanning expiries that have since rolled off.

No lookahead: the ATM strike at each bar is computed only from the
underlying's own close UP TO AND INCLUDING that bar, never a later one.
A strike roll (ATM strike changes bar-to-bar as spot moves) is treated as
a new instrument -- EMA8/21 state resets rather than carrying over from
the previous strike's series, since it's a different option's premium.

Spread/liquidity filters aren't applied here (Dhan's historical option
candles are OHLCV only, no historical bid/ask) -- reported separately as
a coverage limitation in the result, per spec Section 12's own
requirement to report data coverage/limitations.
"""

from __future__ import annotations

from typing import Any

from app.services.charges import option_order_charges
from app.services.crypto_indicators import ema
from app.services.dhan import DhanService
from app.services.pe_ce_crossover import EMA_FAST_PERIOD, EMA_SLOW_PERIOD, OPTION_SEGMENT, STRIKE_STEP
from app.services.pe_ce_filters import premium_expansion_percent

INDEX_SEGMENT = "IDX_I"


async def run_backtest(
    dhan: DhanService,
    *,
    underlying: str,
    underlying_scrip: int,
    side: str,
    expiry: str,
    from_date: str,
    to_date: str,
    lot_size: int,
    stop_loss_percent: float,
    target_percent: float,
    trail_arm_percent: float,
    trail_percent: float,
    min_premium_expansion_percent: float,
    premium_expansion_lookback_bars: int,
) -> dict[str, Any]:
    spot_raw = await dhan.intraday_candles(str(underlying_scrip), INDEX_SEGMENT, "INDEX", "1", from_date, to_date)
    spot_candles = sorted(spot_raw, key=lambda c: c["time"])
    if not spot_candles:
        return {"error": "no underlying candle history for this window", "trades": []}

    step = STRIKE_STEP.get(underlying, 50.0)
    strike_key = "ce" if side == "CE" else "pe"

    chain = await dhan.option_chain(underlying_scrip, INDEX_SEGMENT, expiry)
    oc = chain.get("oc") or {}
    strike_to_security_id: dict[float, str] = {}
    for strike_str, sides in oc.items():
        try:
            strike_price = float(strike_str)
        except (TypeError, ValueError):
            continue
        payload = (sides or {}).get(strike_key) or {}
        sid = payload.get("security_id")
        if sid:
            strike_to_security_id[strike_price] = str(sid)
    if not strike_to_security_id:
        return {"error": "option chain has no usable strikes for this expiry/side", "trades": []}

    # Determine every distinct strike actually visited as ATM across the
    # window (no lookahead -- this only reads each bar's own close).
    visited_strikes: set[float] = set()
    for c in spot_candles:
        atm = round(float(c["close"]) / step) * step
        if atm in strike_to_security_id:
            visited_strikes.add(atm)

    option_candles_by_security_id: dict[str, dict[int, dict[str, Any]]] = {}
    for strike in visited_strikes:
        sid = strike_to_security_id[strike]
        try:
            raw = await dhan.intraday_candles(sid, OPTION_SEGMENT, "OPTIDX", "1", from_date, to_date)
        except Exception:
            continue
        option_candles_by_security_id[sid] = {int(c["time"]): c for c in raw}

    trades: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None
    current_sid: str | None = None
    closes_by_sid: dict[str, list[float]] = {}

    for spot_candle in spot_candles:
        t = int(spot_candle["time"])
        atm_strike = round(float(spot_candle["close"]) / step) * step
        sid = strike_to_security_id.get(atm_strike)
        if not sid:
            continue
        option_candle = option_candles_by_security_id.get(sid, {}).get(t)
        if not option_candle:
            continue

        current_sid = sid
        closes = closes_by_sid.setdefault(sid, [])
        closes.append(float(option_candle["close"]))

        # An already-open position keeps being managed on its OWN contract's
        # candle series below, independent of whichever strike is currently
        # ATM -- a strike roll doesn't touch it, same as the live engine
        # (which only opens against the ATM strike at entry time).
        if position:
            pos_closes = closes_by_sid.get(position["security_id"], [])
            pos_candle = option_candles_by_security_id.get(position["security_id"], {}).get(t)
            if pos_candle:
                current_premium = float(pos_candle["close"])
                exit_reason = _check_exit(
                    position, current_premium, pos_closes, trail_arm_percent, trail_percent
                )
                if exit_reason:
                    trades.append(_close_trade(position, t, current_premium, exit_reason, lot_size))
                    position = None
            continue

        if len(closes) < EMA_SLOW_PERIOD + 2:
            continue
        ema_fast = ema(closes, EMA_FAST_PERIOD)
        ema_slow = ema(closes, EMA_SLOW_PERIOD)
        if ema_fast[-1] is None or ema_slow[-1] is None or ema_fast[-2] is None or ema_slow[-2] is None:
            continue
        crossed_up = ema_fast[-2] <= ema_slow[-2] and ema_fast[-1] > ema_slow[-1]
        closed_above_both = closes[-1] > ema_fast[-1] and closes[-1] > ema_slow[-1]
        if not (crossed_up and closed_above_both):
            continue
        expansion = premium_expansion_percent(closes, premium_expansion_lookback_bars)
        if expansion is None or expansion < min_premium_expansion_percent:
            continue

        position = {
            "security_id": sid,
            "strike": atm_strike,
            "entry_time": t,
            "entry_premium": closes[-1],
            "peak_premium": closes[-1],
            "trail_stop": None,
            "stop_loss_percent": stop_loss_percent,
            "target_percent": target_percent,
        }

    metrics = _compute_metrics(trades)
    return {
        "underlying": underlying,
        "side": side,
        "expiry": expiry,
        "fromDate": from_date,
        "toDate": to_date,
        "strikesVisited": sorted(visited_strikes),
        "trades": trades,
        "metrics": metrics,
        "limitations": [
            "Spread/liquidity filters not applied (Dhan's historical option candles are OHLCV only, no historical bid/ask).",
            "Covers only the lifetime of the given expiry (Dhan has no historical option-chain-as-of-date endpoint).",
            "1-minute bar resolution; intrabar stop/target/trail fills are approximated at the bar's close, not checked intrabar.",
        ],
    }


def _check_exit(position: dict[str, Any], current_premium: float, closes: list[float], trail_arm_percent: float, trail_percent: float) -> str | None:
    entry = position["entry_premium"]
    stop_floor = entry * (1 - position.get("stop_loss_percent", 30.0) / 100)
    target_ceiling = entry * (1 + position.get("target_percent", 50.0) / 100)
    if current_premium <= stop_floor:
        return "stop_loss"
    if current_premium >= target_ceiling:
        return "target"

    peak = max(position["peak_premium"], current_premium)
    position["peak_premium"] = peak
    favorable_move_percent = (peak - entry) / entry * 100
    trail_stop = position["trail_stop"]
    if trail_stop is not None or favorable_move_percent >= trail_arm_percent:
        candidate = peak * (1 - trail_percent / 100)
        trail_stop = candidate if trail_stop is None else max(trail_stop, candidate)
        position["trail_stop"] = trail_stop
    if trail_stop is not None and current_premium <= trail_stop:
        return "trail_stop"

    if len(closes) >= EMA_SLOW_PERIOD + 1:
        ema_fast = ema(closes, EMA_FAST_PERIOD)
        ema_slow = ema(closes, EMA_SLOW_PERIOD)
        if ema_fast[-1] is not None and ema_slow[-1] is not None and ema_fast[-1] < ema_slow[-1]:
            return "ema_cross_down"
    return None


def _close_trade(position: dict[str, Any], exit_time: int, exit_premium: float, exit_reason: str, lot_size: int) -> dict[str, Any]:
    entry_premium = position["entry_premium"]
    gross_pnl = (exit_premium - entry_premium) * lot_size
    entry_charges = option_order_charges(premium=entry_premium, quantity=lot_size, side="BUY", exchange_segment=OPTION_SEGMENT)
    exit_charges = option_order_charges(premium=exit_premium, quantity=lot_size, side="SELL", exchange_segment=OPTION_SEGMENT)
    total_charges = round(entry_charges["total"] + exit_charges["total"], 2)
    net_pnl = round(gross_pnl - total_charges, 2)
    return {
        "strike": position["strike"],
        "entryTime": position["entry_time"],
        "entryPremium": entry_premium,
        "exitTime": exit_time,
        "exitPremium": exit_premium,
        "exitReason": exit_reason,
        "grossPnl": round(gross_pnl, 2),
        "charges": total_charges,
        "netPnl": net_pnl,
    }


def _compute_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "tradeCount": 0, "netPnl": 0.0, "winRate": None, "profitFactor": None,
            "expectancy": None, "maxDrawdown": 0.0, "avgWin": None, "avgLoss": None,
            "longestLosingStreak": 0,
        }
    pnls = [t["netPnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    streak = 0
    longest_losing_streak = 0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        streak = streak + 1 if p <= 0 else 0
        longest_losing_streak = max(longest_losing_streak, streak)

    return {
        "tradeCount": len(trades),
        "netPnl": round(sum(pnls), 2),
        "winRate": round(len(wins) / len(trades) * 100, 1),
        "profitFactor": round(gross_profit / gross_loss, 2) if gross_loss else None,
        "expectancy": round(sum(pnls) / len(trades), 2),
        "maxDrawdown": round(max_drawdown, 2),
        "avgWin": round(sum(wins) / len(wins), 2) if wins else None,
        "avgLoss": round(sum(losses) / len(losses), 2) if losses else None,
        "longestLosingStreak": longest_losing_streak,
    }
