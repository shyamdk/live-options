"""Equity-Swing back-test over the stored daily candles (equity_swing_bars),
with the live rules: weekly ranking (mean of lookback returns / 1-year vol,
above SMA200), top N equal weight filled down to `fillDepth`, sell at
`exitRank` or after `maxHoldWeeks` (then `cooldownWeeks`), no new buys while
NIFTY < SMA200. Signals on day t's close, fills at day t+1's open, delivery
charges + slippage. The quality and news gates can't be replayed (no
history), so they are not part of the back-test.
"""

from __future__ import annotations

import math
import random
from typing import Any

from app.services.equity_swing_engine import delivery_charges

CAPITAL = 500_000.0


def _sma_series(x: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(x)
    s = 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def prepare(bars_by_symbol: dict[str, list[dict[str, Any]]], nifty: list[dict[str, Any]]) -> dict[str, Any]:
    dates = [b["ts"] for b in nifty]
    idx = {t: i for i, t in enumerate(dates)}
    stocks = {}
    for sym, bars in bars_by_symbol.items():
        n = len(dates)
        o: list[float | None] = [None] * n
        c: list[float | None] = [None] * n
        for b in bars:
            i = idx.get(b["ts"])
            if i is not None:
                o[i], c[i] = b["open"], b["close"]
        first = next((i for i in range(n) if c[i] is not None), None)
        if first is None:
            continue
        last = c[first]
        for i in range(first, n):  # forward-fill holidays / suspensions
            if c[i] is None:
                o[i] = c[i] = last
            last = c[i]
        cc = [x if x is not None else c[first] for x in c]
        rets = [0.0] + [cc[i] / cc[i - 1] - 1 for i in range(1, n)]
        vol: list[float | None] = [None] * n
        s1 = s2 = 0.0
        for i in range(n):
            s1 += rets[i]; s2 += rets[i] ** 2
            if i >= 252:
                s1 -= rets[i - 252]; s2 -= rets[i - 252] ** 2
            if i >= 251:
                vol[i] = math.sqrt(max(s2 / 252 - (s1 / 252) ** 2, 1e-12)) * math.sqrt(252)
        stocks[sym] = {"o": o, "c": cc, "first": first, "sma200": _sma_series(cc, 200), "vol": vol}
    nc = [b["close"] for b in nifty]
    return {"dates": dates, "stocks": stocks, "nifty": nc, "nifty200": _sma_series(nc, 200)}


class _Book:
    def __init__(self) -> None:
        self.cash = CAPITAL
        self.pos: dict[str, dict[str, Any]] = {}
        self.trades: list[dict[str, Any]] = []
        self.curve: list[tuple[int, float]] = []
        self.costs = 0.0

    def value(self, S: dict[str, Any], i: int) -> float:
        return self.cash + sum(p["qty"] * S[s]["c"][i] for s, p in self.pos.items())

    def buy(self, S, s, i, budget, slip):
        px = (S[s]["o"][i] or S[s]["c"][i]) * (1 + slip)
        qty = int(budget // (px * 1.0025))
        if qty <= 0:
            return False
        val = qty * px
        fee = delivery_charges(val, "BUY")
        if val + fee > self.cash:
            return False
        self.cash -= val + fee; self.costs += fee
        self.pos[s] = {"qty": qty, "entry": px, "i0": i, "fee": fee}
        return True

    def sell(self, S, s, i, slip, reason, close=False):
        p = self.pos.pop(s)
        px = (S[s]["c"][i] if close else (S[s]["o"][i] or S[s]["c"][i])) * (1 - slip)
        val = p["qty"] * px
        fee = delivery_charges(val, "SELL")
        self.cash += val - fee; self.costs += fee
        self.trades.append({"symbol": s, "i0": p["i0"], "i1": i, "pnl": val - fee - p["qty"] * p["entry"] - p["fee"], "reason": reason})


def run(data: dict[str, Any], cfg: dict[str, Any], start: int, end: int | None = None, picker: str = "momentum", seed: int = 0) -> dict[str, Any]:
    dates, S = data["dates"], data["stocks"]
    end = end or len(dates) - 1
    looks = tuple(int(x) for x in str(cfg["lookbacks"]).split(","))
    top, depth = int(cfg["positions"]), max(int(cfg["positions"]), int(cfg.get("fillDepth") or 0))
    exit_rank, cap_days = int(cfg["exitRank"]), int(cfg["maxHoldWeeks"]) * 7
    cool_days = int(cfg["cooldownWeeks"]) * 7
    slip = float(cfg.get("slippagePercent", 0.1)) / 100
    rnd = random.Random(seed)
    book, blocked = _Book(), {}
    for i in range(start, end):
        book.curve.append((i, book.value(S, i)))
        for s in list(book.pos):
            if cap_days and dates[i] - dates[book.pos[s]["i0"]] >= cap_days * 86400:
                book.sell(S, s, i + 1, slip, "time")
                blocked[s] = dates[i] + cool_days * 86400
        if (i - start) % 5:
            continue
        scores = {}
        for s, d in S.items():
            if i - d["first"] < max(max(looks), 252) + 5 or d["vol"][i] is None:
                continue
            if cfg.get("requireSma200", True) and not (d["sma200"][i] and d["c"][i] > d["sma200"][i]):
                continue
            c = d["c"]
            scores[s] = sum((c[i] / c[i - lb] - 1) / d["vol"][i] for lb in looks) / len(looks)
        if picker == "random":
            ranked = list(scores)
            rnd.shuffle(ranked)
        else:
            ranked = sorted(scores, key=scores.get, reverse=True)
        rank = {s: k for k, s in enumerate(ranked)}
        for s in list(book.pos):
            if rank.get(s, 10**6) >= exit_rank:
                book.sell(S, s, i + 1, slip, "rank")
        if cfg.get("regimeFilter", True) and not (data["nifty200"][i] and data["nifty"][i] > data["nifty200"][i]):
            continue
        slots = top - len(book.pos)
        target = book.value(S, i) / top
        for s in ranked:
            if slots <= 0 or rank[s] >= depth:
                break
            if s in book.pos or blocked.get(s, 0) > dates[i]:
                continue
            if book.buy(S, s, i + 1, min(target, book.cash - 100), slip):
                slots -= 1
    for s in list(book.pos):
        book.sell(S, s, end, slip, "end", close=True)
    book.curve.append((end, book.cash))
    return summarize(book, data, start, end)


def summarize(book: _Book, data: dict[str, Any], start: int, end: int) -> dict[str, Any]:
    dates = data["dates"]
    vals = [v for _, v in book.curve]
    peak, dd = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        dd = min(dd, v / peak - 1)
    years = max((dates[end] - dates[start]) / (365.25 * 86400), 1 / 52)
    final = vals[-1]
    nifty = data["nifty"][end] / data["nifty"][start]
    trades = book.trades
    return {
        "cagr": round(((final / CAPITAL) ** (1 / years) - 1) * 100, 2),
        "totalReturn": round((final / CAPITAL - 1) * 100, 2),
        "maxDrawdown": round(dd * 100, 2),
        "niftyCagr": round((nifty ** (1 / years) - 1) * 100, 2),
        "trades": len(trades),
        "winRate": round(sum(t["pnl"] > 0 for t in trades) / len(trades) * 100, 1) if trades else None,
        "costs": round(book.costs),
        "years": round(years, 2),
    }
