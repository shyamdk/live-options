"""P&F Lab -- Point & Figure chart + five pattern systems (pure, no I/O).

Source: the Definedge transcripts in "PF - Strategies/" (Prashant Shah, Raju
Choudhary, B. Krishna Kumar). Shared by the backtest
(backend/data/history/backtests/pf_lab_bt.py) and the live P&F Lab pages, so
both apply identical rules.

Chart: percentage (log) boxes, 3-box reversal, built from DAILY CLOSES (closing
method). Horizons per the transcripts: 0.25% short term, 1% medium, 3% long.

Systems (long and short, one position each, signals on the daily close):
  dtb_ma   Double Top Buy above the 10-column average -> long; Double Bottom Sell
           below it -> short. A long exits on any Double Bottom Sell, a short on
           any Double Top Buy (the transcript's stop = the opposite signal).
  triple   Triple Top Buy: an X column one box above the equal tops of the two
           previous X columns (5-column pattern). Exit on Double Bottom Sell.
           Triple Bottom Sell is the mirror.
  turtle   Turtle breakout: a column above the highest point of the previous 5
           columns. Exit on the opposite (bearish) Turtle breakout or a 9% stop
           from entry (the transcript caps risk at 8-9%).
  abc      Anchor column of >= 15 boxes, consolidation of >= 2 O and >= 2 X
           columns that stays above the anchor's low, then the first X column to
           break the 45-degree line drawn down from the anchor's top. Exit on
           Double Bottom Sell. Mirror for shorts.
  vcp      Volatility contraction: close within 5% of the 52-week (250-session)
           high, the last three O columns each shorter than the one before, then
           a Double Top Buy. Exit on Double Bottom Sell. Mirror for shorts.
"""

from __future__ import annotations

import math
from typing import Any

SYSTEMS = ["dtb_ma", "triple", "turtle", "abc", "vcp"]
SYSTEM_LABELS = {
    "dtb_ma": "Double Top/Bottom + 10-col MA",
    "triple": "Triple Top / Bottom",
    "turtle": "Turtle breakout (5 col)",
    "abc": "ABC (anchor + 45° breakout)",
    "vcp": "VCP (contraction near 52w high/low)",
}
HORIZON_BOX = {"short": 0.25, "medium": 1.0, "long": 3.0}
REVERSAL = 3
MA_COLUMNS = 10
TURTLE_COLUMNS = 5
TURTLE_STOP_PERCENT = 9.0
ANCHOR_BOXES = 15
VCP_NEAR_PERCENT = 5.0
VCP_LOOKBACK = 250


class Chart:
    def __init__(self, box_percent: float, reversal: int = REVERSAL) -> None:
        self.box = math.log(1 + box_percent / 100)
        self.reversal = reversal
        self.columns: list[dict[str, Any]] = []
        self._anchor: int | None = None

    def price(self, level: float) -> float:
        return math.exp(level * self.box)

    def _up(self, p: float) -> int:
        return math.floor(math.log(p) / self.box + 1e-9)

    def _down(self, p: float) -> int:
        return math.ceil(math.log(p) / self.box - 1e-9)

    def add(self, time: int, close: float) -> bool:
        """Add a close; True if a box printed (column extended or a new column)."""
        up, down = self._up(close), self._down(close)
        if not self.columns:
            if self._anchor is None:
                self._anchor = up
                return False
            if up > self._anchor:
                self._new("X", self._anchor, up, time)
                return True
            if down < self._anchor:
                self._new("O", down, self._anchor, time)
                return True
            return False
        c = self.columns[-1]
        if c["type"] == "X":
            if up > c["top"]:
                c["top"], c["end"] = up, time
                return True
            if down <= c["top"] - self.reversal:
                self._new("O", down, c["top"] - 1, time)
                return True
        else:
            if down < c["bottom"]:
                c["bottom"], c["end"] = down, time
                return True
            if up >= c["bottom"] + self.reversal:
                self._new("X", c["bottom"] + 1, up, time)
                return True
        return False

    def _new(self, kind: str, bottom: int, top: int, time: int) -> None:
        self.columns.append({"type": kind, "top": top, "bottom": bottom, "start": time, "end": time, "flags": set()})

    def height(self, c: dict[str, Any]) -> int:
        return c["top"] - c["bottom"] + 1

    def ma(self, n: int = MA_COLUMNS) -> float | None:
        if len(self.columns) < n:
            return None
        return sum(self.price((c["top"] + c["bottom"]) / 2) for c in self.columns[-n:]) / n


def _flag_once(col: dict[str, Any], name: str) -> bool:
    if name in col["flags"]:
        return False
    col["flags"].add(name)
    return True


def chart_events(chart: Chart, closes: list[float]) -> dict[str, bool]:
    """Pattern events completed by the latest box (each fires once per column)."""
    cols = chart.columns
    ev = {k: False for k in ("dtb", "dbs", "ttb", "tbs", "turtle_up", "turtle_down", "abc_up", "abc_down", "vcp_up", "vcp_down")}
    if not cols:
        return ev
    i = len(cols) - 1
    cur = cols[i]
    if cur["type"] == "X":
        if i >= 2 and cur["top"] > cols[i - 2]["top"] and _flag_once(cur, "dtb"):
            ev["dtb"] = True
            if i >= 4 and cols[i - 2]["top"] == cols[i - 4]["top"]:
                ev["ttb"] = True
            if _vcp(chart, i, closes, up=True):
                ev["vcp_up"] = True
        if i >= TURTLE_COLUMNS and cur["top"] > max(c["top"] for c in cols[i - TURTLE_COLUMNS:i]) and _flag_once(cur, "turtle"):
            ev["turtle_up"] = True
        if _abc(chart, i, up=True):
            ev["abc_up"] = True
    else:
        if i >= 2 and cur["bottom"] < cols[i - 2]["bottom"] and _flag_once(cur, "dbs"):
            ev["dbs"] = True
            if i >= 4 and cols[i - 2]["bottom"] == cols[i - 4]["bottom"]:
                ev["tbs"] = True
            if _vcp(chart, i, closes, up=False):
                ev["vcp_down"] = True
        if i >= TURTLE_COLUMNS and cur["bottom"] < min(c["bottom"] for c in cols[i - TURTLE_COLUMNS:i]) and _flag_once(cur, "turtle"):
            ev["turtle_down"] = True
        if _abc(chart, i, up=False):
            ev["abc_down"] = True
    return ev


def _abc(chart: Chart, i: int, up: bool) -> bool:
    cols = chart.columns
    kind = "X" if up else "O"
    # the most recent anchor of the right kind, with >= 4 columns between it and now
    for a in range(i - 5, max(-1, i - 60), -1):
        an = cols[a]
        if an["type"] != kind or chart.height(an) < ANCHOR_BOXES or "abc_used" in an["flags"]:
            continue
        between = cols[a + 1:i]
        if sum(c["type"] != kind for c in between) < 2 or sum(c["type"] == kind for c in between) < 2:
            return False
        if up:
            if any(c["bottom"] < an["bottom"] for c in between) or cols[i]["bottom"] < an["bottom"]:
                return False
            line = lambda j: an["top"] - (j - a)
            if any(c["type"] == "X" and c["top"] > line(j) for j, c in zip(range(a + 1, i), between)):
                an["flags"].add("abc_used")  # already broke out earlier
                return False
            if cols[i]["top"] > line(i):
                an["flags"].add("abc_used")
                return True
        else:
            if any(c["top"] > an["top"] for c in between) or cols[i]["top"] > an["top"]:
                return False
            line = lambda j: an["bottom"] + (j - a)
            if any(c["type"] == "O" and c["bottom"] < line(j) for j, c in zip(range(a + 1, i), between)):
                an["flags"].add("abc_used")
                return False
            if cols[i]["bottom"] < line(i):
                an["flags"].add("abc_used")
                return True
        return False
    return False


def _vcp(chart: Chart, i: int, closes: list[float], up: bool) -> bool:
    if len(closes) < VCP_LOOKBACK:
        return False
    window = closes[-VCP_LOOKBACK:]
    last = closes[-1]
    if up and last < max(window) * (1 - VCP_NEAR_PERCENT / 100):
        return False
    if not up and last > min(window) * (1 + VCP_NEAR_PERCENT / 100):
        return False
    pull = [c for c in chart.columns[:i] if c["type"] == ("O" if up else "X")][-3:]
    if len(pull) < 3:
        return False
    h = [chart.height(c) for c in pull]
    return h[0] > h[1] > h[2]


class System:
    """One pattern system's position state, driven by daily closes."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.side = 0  # 1 long, -1 short, 0 flat
        self.entry_price: float | None = None
        self.entry_time: int | None = None

    def decide(self, ev: dict[str, bool], close: float, ma: float | None) -> int:
        """Desired position after this close (1 / -1 / 0)."""
        n, side = self.name, self.side
        # exits first
        if side == 1:
            if n == "turtle":
                if ev["turtle_down"] or close <= self.entry_price * (1 - TURTLE_STOP_PERCENT / 100):
                    side = 0
            elif ev["dbs"]:
                side = 0
        elif side == -1:
            if n == "turtle":
                if ev["turtle_up"] or close >= self.entry_price * (1 + TURTLE_STOP_PERCENT / 100):
                    side = 0
            elif ev["dtb"]:
                side = 0
        # entries (can reverse on the same close)
        if side == 0:
            if n == "dtb_ma" and ma is not None:
                if ev["dtb"] and close > ma:
                    side = 1
                elif ev["dbs"] and close < ma:
                    side = -1
            elif n == "triple":
                side = 1 if ev["ttb"] else -1 if ev["tbs"] else 0
            elif n == "turtle":
                side = 1 if ev["turtle_up"] else -1 if ev["turtle_down"] else 0
            elif n == "abc":
                side = 1 if ev["abc_up"] else -1 if ev["abc_down"] else 0
            elif n == "vcp":
                side = 1 if ev["vcp_up"] else -1 if ev["vcp_down"] else 0
        return side


def replay(bars: list[dict[str, Any]], box_percent: float, systems: list[str] | None = None) -> dict[str, Any]:
    """Run every system over daily bars [{time, close}] (sorted). Returns the chart,
    the trades per system [{side, entryTime, entryPrice, exitTime, exitPrice}] and
    each system's open position at the end."""
    systems = systems or SYSTEMS
    chart = Chart(box_percent)
    state = {s: System(s) for s in systems}
    trades: dict[str, list[dict[str, Any]]] = {s: [] for s in systems}
    closes: list[float] = []
    for b in bars:
        t, c = int(b["time"]), float(b["close"])
        closes.append(c)
        printed = chart.add(t, c)
        ev = chart_events(chart, closes) if printed else {k: False for k in ("dtb", "dbs", "ttb", "tbs", "turtle_up", "turtle_down", "abc_up", "abc_down", "vcp_up", "vcp_down")}
        ma = chart.ma()
        for s in state.values():
            want = s.decide(ev, c, ma)
            if want != s.side:
                if s.side != 0:
                    trades[s.name].append({"side": s.side, "entryTime": s.entry_time, "entryPrice": s.entry_price, "exitTime": t, "exitPrice": c})
                s.side = want
                s.entry_price, s.entry_time = (c, t) if want else (None, None)
    open_pos = {s.name: ({"side": s.side, "entryTime": s.entry_time, "entryPrice": s.entry_price} if s.side else None) for s in state.values()}
    return {"chart": chart, "trades": trades, "open": open_pos, "lastClose": closes[-1] if closes else None, "lastTime": int(bars[-1]["time"]) if bars else None}
