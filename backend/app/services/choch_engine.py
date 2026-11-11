"""1-Min CHoCH -- Mukesh Jha's 1-minute NIFTY Change-of-Character reversal (pure, no I/O).

Source: 1_minute_chart_trading_strategy_transcript.pdf. Shared by the paper page
(app/services/choch.py) and the backtests (backend/data/history/backtests/choch_*.py).

Swings: a zigzag on 1-min highs/lows with a minimum swing of `swing` points (the
transcript's "zoom out"); a swing is known only once price has moved `swing` points
away from it, so there is no look-ahead. A candle CLOSE below the last swing low is
a bearish break of structure (BOS) and the CHoCH level becomes the last swing high
before it; a close above that level is a bullish CHoCH -> long at the close (mirror
for shorts). Entries `start`-`last_entry` (HHMM IST), stop `stop` points, target
`target` points (stop checked first within a candle), flat at `flat`, one position
at a time, at most `max_trades` per day. State starts fresh every session.

Backtest Jan 2025 - Oct 2026 (NIFTY index 1-min): the transcript's settings (swings
15-30 pts, stop 10 / target 30) lose; swing 55-70 / stop 10 / target 60 / max 2 a day
is positive in both 2025 and 2026 (swing 65: +894 pts at 1.5 pts cost per trade).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30))

DEFAULTS: dict[str, Any] = {"swing": 65.0, "stop": 10.0, "target": 60.0, "max_trades": 2, "start": 945, "last_entry": 1500, "flat": 1515}


def hm(ts: int) -> int:
    d = datetime.fromtimestamp(int(ts), IST)
    return d.hour * 100 + d.minute


def run_day(bars: list[dict[str, Any]], swing: float, stop: float, target: float, max_trades: int,
            stop_mode: str = "fixed", start: int = 945, last_entry: int = 1500, flat: int = 1515,
            close_open: bool = True) -> list[dict[str, Any]] | dict[str, Any]:
    """Replay one session's 1-min bars (dicts with time/open/high/low/close).

    close_open=True (backtest): returns the trade list, an open position closed at the
    last bar. close_open=False (live): returns {"trades", "open", "state"}."""
    trades: list[dict[str, Any]] = []
    direction, ext, ext_i = 0, None, None
    trend, choch, pos = 0, None, None
    last_sh = last_sl = None
    leg_low = leg_high = None
    for i, b in enumerate(bars):
        t, h, l, c = hm(int(b["time"])), b["high"], b["low"], b["close"]
        # ---- manage an open position (stop first: conservative)
        if pos:
            side, entry, sl, tp = pos["side"], pos["entry"], pos["sl"], pos["tp"]
            exit_px, reason = None, None
            if side == 1:
                if l <= sl: exit_px, reason = sl, "stop"
                elif h >= tp: exit_px, reason = tp, "target"
            else:
                if h >= sl: exit_px, reason = sl, "stop"
                elif l <= tp: exit_px, reason = tp, "target"
            if exit_px is None and t >= flat:
                exit_px, reason = c, "time"
            if exit_px is not None:
                trades.append({**pos, "exit": exit_px, "pts": (exit_px - entry) * side, "exitT": t, "exitTime": int(b["time"]), "reason": reason})
                pos = None
        # ---- zigzag swing confirmation
        if direction == 0:
            direction, ext, ext_i = 1, h, i
        elif direction == 1:
            if h > ext:
                ext, ext_i = h, i
            elif l <= ext - swing:
                last_sh = ext
                direction, ext, ext_i = -1, l, i
        else:
            if l < ext:
                ext, ext_i = l, i
            elif h >= ext + swing:
                last_sl = ext
                direction, ext, ext_i = 1, h, i
        # ---- structure on candle closes (CHoCH first, then BOS)
        leg_low = l if leg_low is None else min(leg_low, l)
        leg_high = h if leg_high is None else max(leg_high, h)
        signal = 0
        if trend == -1 and choch is not None and c > choch:
            signal = 1
            trend, choch, last_sh = 1, leg_low, None
            leg_low = leg_high = None
        elif trend == 1 and choch is not None and c < choch:
            signal = -1
            trend, choch, last_sl = -1, leg_high, None
            leg_low = leg_high = None
        elif last_sl is not None and c < last_sl:
            trend, choch, last_sl = -1, last_sh, None
            leg_low = leg_high = None
        elif last_sh is not None and c > last_sh:
            trend, choch, last_sh = 1, last_sl, None
            leg_low = leg_high = None
        if signal and pos is None and start <= t <= last_entry and len(trades) < max_trades:
            if stop_mode == "candle":
                sl_px = (l - 1) if signal == 1 else (h + 1)
                risk = abs(c - sl_px)
                if risk > 25 or risk < 3:
                    continue
            else:
                sl_px = c - stop * signal
                risk = stop
            pos = {"side": signal, "entry": c, "sl": sl_px, "tp": c + signal * (target if stop_mode == "fixed" else 3 * risk),
                   "entryT": t, "entryTime": int(b["time"])}
    if close_open:
        if pos:
            last = bars[-1]
            trades.append({**pos, "exit": last["close"], "pts": (last["close"] - pos["entry"]) * pos["side"], "exitT": hm(int(last["time"])),
                           "exitTime": int(last["time"]), "reason": "data end"})
        return trades
    return {"trades": trades, "open": pos,
            "state": {"trend": trend, "choch": choch, "swingHigh": last_sh, "swingLow": last_sl,
                      "zigzag": "up" if direction == 1 else "down" if direction == -1 else None, "extreme": ext}}
