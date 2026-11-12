"""Define Turtle -- pure Point & Figure engine (see docs/strategies/define-turtle.md).

Builds a logarithmic-box P&F chart from 1-minute closes (close method),
computes RSI(14) over column end values, and flags Turtle Breakout /
Turtle Follow-Through (and Strike Back, defined but unused) the moment the
box that completes them prints.
"""

from __future__ import annotations

import math
from typing import Any

from app.services.crypto_indicators import rsi


class PointAndFigure:
    def __init__(self, box_percent: float = 0.03, reversal: int = 3, turtle_lookback: int = 5) -> None:
        self.box = math.log(1 + box_percent / 100)
        self.reversal = reversal
        self.turtle_lookback = turtle_lookback
        self.columns: list[dict[str, Any]] = []
        self.signals: list[dict[str, Any]] = []
        self._anchor: int | None = None  # first level, before the first column forms

    # -------------------------------------------------------------- levels
    def price(self, level: int) -> float:
        return math.exp(level * self.box)

    def _up_level(self, price: float) -> int:
        return math.floor(math.log(price) / self.box + 1e-9)

    def _down_level(self, price: float) -> int:
        return math.ceil(math.log(price) / self.box - 1e-9)

    # -------------------------------------------------------------- build
    def add(self, time: int, close: float) -> None:
        up, down = self._up_level(close), self._down_level(close)
        if not self.columns:
            if self._anchor is None:
                self._anchor = up
                return
            if up > self._anchor:
                self._new_column("X", self._anchor, up, time)
            elif down < self._anchor:
                self._new_column("O", down, self._anchor, time)
            return
        col = self.columns[-1]
        if col["type"] == "X":
            if up > col["top"]:
                col["top"], col["end"] = up, time
                self._on_x_extended(time)
            elif down <= col["top"] - self.reversal:
                self._new_column("O", down, col["top"] - 1, time)
        else:
            if down < col["bottom"]:
                col["bottom"], col["end"] = down, time
                self._on_o_extended(time)
            elif up >= col["bottom"] + self.reversal:
                self._new_column("X", col["bottom"] + 1, up, time)

    def _new_column(self, kind: str, bottom: int, top: int, time: int) -> None:
        self.columns.append({
            "type": kind, "top": top, "bottom": bottom, "start": time, "end": time,
            "turtle": False, "followThrough": False, "doubleTop": False, "doubleBottom": False, "strikeBack": False,
            "turtleBear": False, "followThroughBear": False,
        })
        if kind == "X":
            self._on_x_extended(time)
        else:
            self._on_o_extended(time)

    # -------------------------------------------------------------- patterns
    def _on_x_extended(self, time: int) -> None:
        i = len(self.columns) - 1
        col = self.columns[i]
        previous = self.columns[max(0, i - self.turtle_lookback):i]
        if len(previous) == self.turtle_lookback and not col["turtle"] and col["top"] > max(c["top"] for c in previous):
            col["turtle"] = True
            self.signals.append(self._signal("turtle_breakout", i, time))
        if i >= 2 and not col["doubleTop"] and col["top"] > self.columns[i - 2]["top"]:
            col["doubleTop"] = True
            # Follow-Through: a Double Top Buy right after a Bullish Turtle Breakout column.
            if self.columns[i - 2]["turtle"] and not col["followThrough"]:
                col["followThrough"] = True
                self.signals.append(self._signal("turtle_follow_through", i, time))
            # Strike Back (working definition, docs/strategies/define-turtle.md 4.3): bear trap X at i-2
            # (it double-topped right after a double-bottom O at i-3), higher-low pullback at i-1.
            if (
                i >= 4 and self.columns[i - 2]["doubleTop"] and self.columns[i - 3]["doubleBottom"]
                and self.columns[i - 1]["bottom"] > self.columns[i - 3]["bottom"] and not col["strikeBack"]
            ):
                col["strikeBack"] = True
                self.signals.append(self._signal("strike_back", i, time))

    def _on_o_extended(self, time: int) -> None:
        i = len(self.columns) - 1
        col = self.columns[i]
        # bearish mirror (Nov 2026): Turtle Breakdown = an O column below the lows of the previous
        # `turtle_lookback` columns; Follow-Through Bearish = a Double Bottom Sell right after it
        previous = self.columns[max(0, i - self.turtle_lookback):i]
        if len(previous) == self.turtle_lookback and not col["turtleBear"] and col["bottom"] < min(c["bottom"] for c in previous):
            col["turtleBear"] = True
            self.signals.append(self._signal("turtle_breakdown", i, time))
        if i >= 2 and not col["doubleBottom"] and col["bottom"] < self.columns[i - 2]["bottom"]:
            col["doubleBottom"] = True
            if self.columns[i - 2]["turtleBear"] and not col["followThroughBear"]:
                col["followThroughBear"] = True
                self.signals.append(self._signal("turtle_follow_through_bearish", i, time))

    def _signal(self, kind: str, index: int, time: int) -> dict[str, Any]:
        col = self.columns[index]
        return {
            "kind": kind,
            "time": time,
            "column": index,
            "price": round(self.price(col["top"] if col["type"] == "X" else col["bottom"]), 2),
            "rsi": self.rsi(),
        }

    # -------------------------------------------------------------- RSI
    def column_values(self) -> list[float]:
        return [self.price(c["top"] if c["type"] == "X" else c["bottom"]) for c in self.columns]

    def rsi(self, period: int = 14) -> float | None:
        values = self.column_values()
        if len(values) <= period:
            return None
        series = rsi(values, period)
        return round(series[-1], 2) if series and series[-1] is not None else None

    def rsi_series(self, period: int = 14) -> list[float | None]:
        values = self.column_values()
        if len(values) <= period:
            return [None] * len(values)
        return [round(v, 2) if v is not None else None for v in rsi(values, period)]


def build(candles: list[dict[str, Any]], *, box_percent: float, reversal: int, turtle_lookback: int) -> PointAndFigure:
    chart = PointAndFigure(box_percent, reversal, turtle_lookback)
    for candle in sorted(candles, key=lambda c: int(c["time"])):
        chart.add(int(candle["time"]), float(candle["close"]))
    return chart
