"""Equity-Swing -- pure ranking and rebalance planning (no I/O).

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
        if free <= 0 or r["rank"] is None or r["rank"] > max(positions, fill_depth or positions):
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
        buys.append({"symbol": sym, "rank": r["rank"], "score": r["score"],
                     "reason": f"rank {r['rank']} of {sum(1 for x in ranking if x['rank'])}: 1m {r['returns'].get('21')}%, 3m {r['returns'].get('63')}%, vol {r['vol']}%"})
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
