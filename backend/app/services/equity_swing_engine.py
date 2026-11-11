"""Equity-Swing -- pure ranking and rebalance planning (no I/O).

MODEL (from 11 Nov 2026): alpha + low volatility, monthly (`rank_alpha_lowvol`).
  score  = mean of z(one-year Jensen alpha vs NIFTY) and z(-one-year volatility),
           daily log returns over the last 252 sessions, aligned with NIFTY by date
  buys   = top 15 by score, up to 30 holdings, equal weight; sell at rank 45 or worse
  rebalance on the last trading day of the month, orders at the next open
Back-test (backend/data/history/backtests/eq_rotation_bt.py; point-in-time top 200
NSE stocks by turnover, 2008 - Nov 2026, delivery costs + 0.1% slippage, STCG/LTCG
tax, Rs 5L): 15.1% CAGR, -37.8% max drawdown, +11 to +19% a year in every sub-period
(2008-13, 2014-19, 2020-22, 2023-26); NIFTY 50 7.6%. The previous model below lost
5.3% a year over the same test (-81% drawdown). Research: reports/Indian equity
swing strategies.md.

PREVIOUS MODEL (kept as model = "momentum"):

Weekly momentum rotation on the NIFTY 200 (back-test, 17 Oct 2026: Jan 2022 -
Oct 2026, Rs 5L, delivery costs + 0.1% slippage):
  score      = mean over lookbacks (21, 63 trading days) of return / annualised
               1-year volatility; stock must close above its SMA200
  buys       = top `positions` (8) eligible names, equal weight
  sells      = rank falls to `exitRank` (20) or worse, or held `maxHoldWeeks`
               (8) -- a capped stock can't come back for `cooldownWeeks` (4)
  regime     = no new buys while NIFTY is below its SMA200
Result: 30.7% CAGR, -18.4% max drawdown, median hold 4.1 weeks (+55.6% a
year in the 2022-24 half, +9.7% since); 8 random NIFTY 200 stocks rotated
monthly made 11.4%. Today's index list flatters all of these numbers.
"""

from __future__ import annotations

import math
from typing import Any


def sma(values: list[float], n: int) -> float | None:
    return sum(values[-n:]) / n if len(values) >= n else None


def annual_vol(closes: list[float], n: int = 252) -> float | None:
    if len(closes) < n + 1:
        return None
    rets = [closes[i] / closes[i - 1] - 1 for i in range(len(closes) - n, len(closes))]
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / n
    return math.sqrt(var) * math.sqrt(252) if var > 0 else None


def score_stock(closes: list[float], lookbacks: tuple[int, ...]) -> dict[str, Any] | None:
    """Momentum score of one stock from its daily closes (oldest first)."""
    if len(closes) < max(max(lookbacks) + 1, 253):
        return None
    vol = annual_vol(closes)
    if not vol:
        return None
    rets = {lb: closes[-1] / closes[-1 - lb] - 1 for lb in lookbacks}
    sma200 = sma(closes, 200)
    return {
        "score": round(sum(r / vol for r in rets.values()) / len(rets), 4),
        "returns": {str(lb): round(r * 100, 2) for lb, r in rets.items()},
        "vol": round(vol * 100, 1),
        "close": closes[-1],
        "sma200": round(sma200, 2) if sma200 else None,
        "aboveSma200": bool(sma200 and closes[-1] > sma200),
    }


def rank_alpha_lowvol(series_by_symbol: dict[str, list[tuple[int, float]]], nifty: list[tuple[int, float]], n: int = 252) -> list[dict[str, Any]]:
    """Alpha + low-volatility ranking. series: [(day ts, close)] oldest first."""
    if len(nifty) < n + 1:
        return []
    days = [ts for ts, _ in nifty[-(n + 1):]]
    nidx = {ts: c for ts, c in nifty[-(n + 1):]}
    x = [math.log(nidx[days[i]] / nidx[days[i - 1]]) for i in range(1, len(days))]
    xm = sum(x) / len(x)
    sxx = sum((v - xm) ** 2 for v in x)
    raw = []
    for symbol, series in series_by_symbol.items():
        by_day = dict(series)
        closes = [by_day.get(d) for d in days]
        if sum(c is None for c in closes) > 10 or closes[-1] is None:
            continue  # too many missing sessions in the year
        filled, last = [], None
        for c in closes:
            last = c if c is not None else last
            filled.append(last)
        if filled[0] is None:
            continue
        y = [math.log(filled[i] / filled[i - 1]) for i in range(1, len(filled))]
        ym = sum(y) / len(y)
        beta = sum((yi - ym) * (xi - xm) for yi, xi in zip(y, x)) / sxx if sxx else 0.0
        alpha = (ym - beta * xm) * 252
        vol = math.sqrt(sum((yi - ym) ** 2 for yi in y) / len(y)) * math.sqrt(252)
        r6 = filled[-1] / filled[-127] - 1 if len(filled) > 127 else None
        raw.append({"symbol": symbol, "alpha": alpha, "volRaw": vol, "beta": beta, "close": filled[-1], "r12": filled[-1] / filled[0] - 1, "r6": r6})
    if len(raw) < 5:
        return []
    def z(values):
        m = sum(values) / len(values)
        sd = math.sqrt(sum((v - m) ** 2 for v in values) / len(values)) or 1.0
        return [(v - m) / sd for v in values]
    za, zv = z([r["alpha"] for r in raw]), z([-r["volRaw"] for r in raw])
    rows = []
    for r, a, v in zip(raw, za, zv):
        rows.append({
            "symbol": r["symbol"], "score": round((a + v) / 2, 4), "alpha": round(r["alpha"] * 100, 1), "beta": round(r["beta"], 2),
            "vol": round(r["volRaw"] * 100, 1), "close": r["close"], "eligible": True,
            "returns": {"126": round(r["r6"] * 100, 2) if r["r6"] is not None else None, "252": round(r["r12"] * 100, 2)},
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    for k, r in enumerate(rows, start=1):
        r["rank"] = k
    return rows


def rank(closes_by_symbol: dict[str, list[float]], lookbacks: tuple[int, ...], require_sma200: bool) -> list[dict[str, Any]]:
    rows = []
    for symbol, closes in closes_by_symbol.items():
        sc = score_stock(closes, lookbacks)
        if not sc:
            continue
        sc["symbol"] = symbol
        sc["eligible"] = sc["aboveSma200"] or not require_sma200
        rows.append(sc)
    eligible = sorted((r for r in rows if r["eligible"]), key=lambda r: r["score"], reverse=True)
    for k, r in enumerate(eligible, start=1):
        r["rank"] = k
    for r in rows:
        r.setdefault("rank", None)
    return eligible + sorted((r for r in rows if not r["eligible"]), key=lambda r: r["score"], reverse=True)


def plan(
    ranking: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    *,
    positions: int,
    fill_depth: int | None = None,
    buy_rank: int | None = None,
    exit_rank: int,
    max_hold_days: int | None,
    cooldown_until: dict[str, int],
    now: int,
    regime_ok: bool,
    blocked: dict[str, str],
) -> dict[str, Any]:
    """Sells and buys for the next session.

    holdings: [{symbol, entryTime}] currently held.
    blocked: symbol -> reason it can't be bought now (quality / news / cooldown).
    """
    by_symbol = {r["symbol"]: r for r in ranking}
    sells, keep = [], []
    for h in holdings:
        r = by_symbol.get(h["symbol"])
        held_days = (now - int(h["entryTime"])) / 86400 if h.get("entryTime") else 0
        if max_hold_days and held_days >= max_hold_days:
            sells.append({"symbol": h["symbol"], "reason": f"held {held_days / 7:.1f} weeks (cap {max_hold_days // 7})", "kind": "time"})
        elif not r or r["rank"] is None:
            sells.append({"symbol": h["symbol"], "reason": "dropped out of the eligible list (below SMA200 or no data)", "kind": "rank"})
        elif r["rank"] >= exit_rank:
            sells.append({"symbol": h["symbol"], "reason": f"rank fell to {r['rank']} (exit at {exit_rank} or worse)", "kind": "rank"})
        else:
            keep.append(h["symbol"])
    buys, skipped = [], []
    free = positions - len(keep)
    held = {h["symbol"] for h in holdings}
    if not regime_ok:
        return {"sells": sells, "buys": [], "skipped": [], "free": free, "note": "NIFTY is below its SMA200: no new buys this week."}
    for r in ranking:
        if free <= 0 or r["rank"] is None or r["rank"] > (buy_rank or max(positions, fill_depth or positions)):
            break
        sym = r["symbol"]
        if sym in held:
            continue
        if cooldown_until.get(sym, 0) > now:
            skipped.append({"symbol": sym, "rank": r["rank"], "reason": "cool-down after a time exit"})
            continue
        if sym in blocked:
            skipped.append({"symbol": sym, "rank": r["rank"], "reason": blocked[sym]})
            continue
        why = (f"alpha {r['alpha']}%/yr, vol {r['vol']}%, beta {r['beta']}" if "alpha" in r
               else f"1m {r['returns'].get('21')}%, 3m {r['returns'].get('63')}%, vol {r['vol']}%")
        buys.append({"symbol": sym, "rank": r["rank"], "score": r["score"], "reason": f"rank {r['rank']} of {sum(1 for x in ranking if x['rank'])}: {why}"})
        free -= 1
    return {"sells": sells, "buys": buys, "skipped": skipped, "free": free, "note": None}


def delivery_charges(value: float, side: str) -> float:
    """Indian equity delivery charges for one order (Angel One-like)."""
    brokerage = min(20.0, value * 0.001)
    exch = value * 0.0000297
    sebi = value * 0.000001
    gst = 0.18 * (brokerage + exch + sebi)
    stt = value * 0.001
    stamp = value * 0.00015 if side == "BUY" else 0.0
    dp = 20.0 if side == "SELL" else 0.0
    return round(brokerage + exch + sebi + gst + stt + stamp + dp, 2)
