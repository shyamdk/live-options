"""Melting Straddles -- pure engine (docs/strategies/melting-straddles.md).

Combined-premium series (CE + PE close per minute, VWAP = VWAP(CE) + VWAP(PE)
on typical price x volume, both legs cumulative from 09:15) and a
logarithmic-box Point & Figure chart on it with the four sell patterns:

  DOUBLE_BOTTOM  an O column breaks below the previous O column's low
  TURTLE         an O column breaks below the lows of the previous N columns
  ANCHOR_FT      an O column breaks below a recent tall O column (>= k x the
                 median column height of the day so far)
  HIGH_POLE_FT   right after a tall X column (>= k x median), the O column
                 retraces more than 50% of it

Each signal is stamped with the minute whose close printed the box. The
same engine drives the live monitor and the backtest.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

PATTERNS = ("DOUBLE_BOTTOM", "TURTLE", "ANCHOR_FT", "HIGH_POLE_FT")


class PointAndFigure:
    def __init__(
        self,
        box_percent: float = 0.5,
        reversal: int = 3,
        *,
        turtle_lookback: int = 5,
        anchor_lookback: int = 10,
        tall_multiple: float = 2.0,
    ) -> None:
        self.box = math.log(1 + box_percent / 100)
        self.reversal = reversal
        self.turtle_lookback = turtle_lookback
        self.anchor_lookback = anchor_lookback
        self.tall_multiple = tall_multiple
        self.columns: list[dict[str, Any]] = []
        self.signals: list[dict[str, Any]] = []
        self.x_starts: list[int] = []  # minutes at which a new X column (up-reversal) formed
        self._anchor: int | None = None

    def price(self, level: float) -> float:
        return math.exp(level * self.box)

    def value(self) -> float | None:
        """Current column end (top of an X, bottom of an O) as a price."""
        if not self.columns:
            return None
        col = self.columns[-1]
        return self.price(col["top"] if col["type"] == "X" else col["bottom"])

    def add(self, time: int, close: float) -> list[dict[str, Any]]:
        if close <= 0:
            return []
        up = math.floor(math.log(close) / self.box + 1e-9)
        down = math.ceil(math.log(close) / self.box - 1e-9)
        fired: list[dict[str, Any]] = []
        if not self.columns:
            if self._anchor is None:
                self._anchor = up
            elif up > self._anchor:
                self._new("X", self._anchor, up, time)
            elif down < self._anchor:
                self._new("O", down, self._anchor, time)
                fired = self._o_signals(time)
            return fired
        col = self.columns[-1]
        if col["type"] == "X":
            if up > col["top"]:
                col["top"], col["end"] = up, time
            elif down <= col["top"] - self.reversal:
                self._new("O", down, col["top"] - 1, time)
                fired = self._o_signals(time)
        else:
            if down < col["bottom"]:
                col["bottom"], col["end"] = down, time
                fired = self._o_signals(time)
            elif up >= col["bottom"] + self.reversal:
                self._new("X", col["bottom"] + 1, up, time)
                self.x_starts.append(time)
        return fired

    def _new(self, kind: str, bottom: int, top: int, time: int) -> None:
        self.columns.append({"type": kind, "top": top, "bottom": bottom, "start": time, "end": time, "flags": set()})

    def _height(self, col: dict[str, Any]) -> int:
        return col["top"] - col["bottom"] + 1

    def _o_signals(self, time: int) -> list[dict[str, Any]]:
        i = len(self.columns) - 1
        col = self.columns[i]
        flags = col["flags"]
        found: list[str] = []
        done = [self._height(c) for c in self.columns[:i]]
        median = statistics.median(done) if done else None
        if i >= 2 and "DOUBLE_BOTTOM" not in flags and col["bottom"] < self.columns[i - 2]["bottom"]:
            found.append("DOUBLE_BOTTOM")
        previous = self.columns[max(0, i - self.turtle_lookback):i]
        if len(previous) == self.turtle_lookback and "TURTLE" not in flags and col["bottom"] < min(c["bottom"] for c in previous):
            found.append("TURTLE")
        if median and "ANCHOR_FT" not in flags:
            for j in range(max(0, i - self.anchor_lookback), i):
                anchor = self.columns[j]
                if anchor["type"] == "O" and self._height(anchor) >= self.tall_multiple * median and col["bottom"] < anchor["bottom"]:
                    found.append("ANCHOR_FT")
                    break
        if median and i >= 1 and "HIGH_POLE_FT" not in flags:
            pole = self.columns[i - 1]
            height = self._height(pole)
            if pole["type"] == "X" and height >= self.tall_multiple * median and col["bottom"] < pole["top"] - height / 2:
                found.append("HIGH_POLE_FT")
        signals = []
        for kind in found:
            flags.add(kind)
            signal = {"kind": kind, "time": time, "column": i, "price": round(self.price(col["bottom"]), 2)}
            self.signals.append(signal)
            signals.append(signal)
        return signals

    def payload(self, last: int = 60) -> list[dict[str, Any]]:
        start = max(0, len(self.columns) - last)
        return [
            {
                "index": start + k,
                "type": c["type"],
                "top": c["top"],
                "bottom": c["bottom"],
                "topPrice": round(self.price(c["top"]), 2),
                "bottomPrice": round(self.price(c["bottom"]), 2),
                "start": c["start"],
                "end": c["end"],
                "signals": sorted(c["flags"]),
            }
            for k, c in enumerate(self.columns[start:])
        ]


def combine(ce: list[dict[str, Any]], pe: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Minute series of the straddle: CE, PE, combined close and combined VWAP.
    A minute missing on one leg carries that leg's last close forward
    (volume 0), so the series has a row for every minute either leg traded."""
    by_time: dict[int, dict[str, dict[str, Any]]] = {}
    for side, candles in (("ce", ce), ("pe", pe)):
        for c in candles:
            by_time.setdefault(int(c["time"]), {})[side] = c
    last: dict[str, float] = {}
    pv = {"ce": 0.0, "pe": 0.0}
    vol = {"ce": 0.0, "pe": 0.0}
    rows = []
    for t in sorted(by_time):
        for side in ("ce", "pe"):
            c = by_time[t].get(side)
            if not c:
                continue
            last[side] = float(c["close"])
            v = float(c.get("volume") or 0)
            pv[side] += (float(c["high"]) + float(c["low"]) + float(c["close"])) / 3 * v
            vol[side] += v
        if "ce" not in last or "pe" not in last:
            continue
        vwap = pv["ce"] / vol["ce"] + pv["pe"] / vol["pe"] if vol["ce"] and vol["pe"] else None
        rows.append({
            "time": t, "ce": last["ce"], "pe": last["pe"], "combined": round(last["ce"] + last["pe"], 2),
            "vwap": round(vwap, 2) if vwap is not None else None,
        })
    return rows


def analyze(series: list[dict[str, Any]], *, box_percent: float, reversal: int, turtle_lookback: int = 5,
            anchor_lookback: int = 10, tall_multiple: float = 2.0) -> PointAndFigure:
    chart = PointAndFigure(box_percent, reversal, turtle_lookback=turtle_lookback, anchor_lookback=anchor_lookback, tall_multiple=tall_multiple)
    for row in series:
        chart.add(int(row["time"]), float(row["combined"]))
    return chart
