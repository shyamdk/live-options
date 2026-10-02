"""Shared trade-metrics computation for PE-CE Crossover, used by both the
backtest engine (pe_ce_backtest.py, trades shaped with "netPnl") and the
Phase 3b performance report over real paper/shadow/live trade history
(pe_ce_crossover_trades rows, shaped with "realizedPnl") -- same formulas,
different field name for the realized P&L per trade.
"""

from __future__ import annotations

from typing import Any


def compute_trade_metrics(trades: list[dict[str, Any]], *, pnl_key: str = "netPnl") -> dict[str, Any]:
    if not trades:
        return {
            "tradeCount": 0, "netPnl": 0.0, "winRate": None, "profitFactor": None,
            "expectancy": None, "maxDrawdown": 0.0, "avgWin": None, "avgLoss": None,
            "longestLosingStreak": 0,
        }
    pnls = [t[pnl_key] or 0.0 for t in trades]
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
