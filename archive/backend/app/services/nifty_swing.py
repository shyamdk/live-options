"""NIFTYBEES paper-trading simulation -- the exact same 3-way confirmation
strategy as crypto_swing.py (see that module's docstring), reused as-is via
simulate_trades(allow_short=False, quantity_per_tranche=...), just fed
NIFTYBEES candles from Dhan instead of a Delta Exchange perpetual.

Long-only: NIFTYBEES is a cash ETF, not realistically shortable, so a
bearish 3-way confirmation is simply not traded (see simulate_trades'
allow_short param) rather than opening a notional short that couldn't
really be placed.

Stateless like crypto_swing.py -- every call recomputes the full trade
sequence fresh from Dhan's candle history, no persisted state.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.timeutil import now_ist
from app.services.crypto_indicators import atr as compute_atr
from app.services.crypto_indicators import ema, macd, resample_ohlc, supertrend
from app.services.crypto_swing import IndicatorBundle
from app.services.dhan import DhanService
from app.services.dhan_scrip_master import resolve_equity_security_id

ATR_LOOKBACK = 14
DEFAULT_QUANTITY_PER_TRANCHE = 50.0
TRADING_SYMBOL = "NIFTYBEES"
EQUITY_SEGMENT = "NSE_EQ"
EQUITY_INSTRUMENT = "EQUITY"
RESOLUTION_SECONDS = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600}
# Dhan's /charts/intraday only natively serves 1/5/15/25/60-minute bars --
# there's no native "30". 30m bars are built by pairing up consecutive 15m
# bars instead (see resample_ohlc); every other resolution here is native.
DHAN_INTERVAL = {"5m": "5", "15m": "15", "30m": "15", "1h": "60"}
RESAMPLE_GROUP = {"30m": 2}

_security_id_cache: int | None = None


async def get_security_id() -> int:
    global _security_id_cache
    if _security_id_cache is None:
        _security_id_cache = await resolve_equity_security_id(TRADING_SYMBOL, exchange="NSE")
    return _security_id_cache


async def load_indicators(resolution: str) -> IndicatorBundle:
    dhan = DhanService()
    security_id = await get_security_id()
    interval = DHAN_INTERVAL.get(resolution, "25")

    # NIFTYBEES only trades 9:15-15:30 IST on weekdays, unlike Delta's 24/7
    # crypto feed -- fetch a generous 60 calendar-day window so 200+ candles
    # (EMA200's warm-up) are available even at 30m/1h resolution once
    # weekends/holidays thin it out.
    today = now_ist().date()
    from_date = (today - timedelta(days=60)).isoformat()
    to_date = today.isoformat()

    raw = await dhan.intraday_candles(str(security_id), EQUITY_SEGMENT, EQUITY_INSTRUMENT, interval, from_date, to_date)
    ordered = sorted(raw, key=lambda c: c["time"])

    group_size = RESAMPLE_GROUP.get(resolution)
    if group_size:
        ordered = resample_ohlc(ordered, group_size, day_key=lambda c: _ist_date(c["time"]))

    closes = [float(c["close"]) for c in ordered]

    ema200 = ema(closes, 200)
    macd_line, signal_line, histogram = macd(closes)
    st_values, st_directions = supertrend(ordered, period=13, multiplier=4.0)
    atr_values = compute_atr(ordered, ATR_LOOKBACK)
    return IndicatorBundle(ordered, ema200, macd_line, signal_line, histogram, st_values, st_directions, atr_values)


_IST = ZoneInfo("Asia/Kolkata")


def _ist_date(epoch: int) -> date:
    return datetime.fromtimestamp(epoch, _IST).date()
