from __future__ import annotations

from typing import Any

from app.core.config import Settings, get_settings


def apply_option_charge_estimates(
    trade: dict[str, Any],
    settings: Settings | None = None,
    order_counts: dict[tuple[str, str], int] | None = None,
) -> None:
    settings = settings or get_settings()
    qty = int(trade.get("qty") or 0)
    avg_price = _number(trade.get("avgPrice"))
    ltp = _number(trade.get("ltp"))
    if trade.get("assetClass") != "OPTION" or qty == 0 or avg_price is None:
        trade["estimatedCharges"] = None
        trade["estimatedNetPnl"] = trade.get("dayPnl")
        return

    entry_side = "BUY" if qty > 0 else "SELL"
    exit_side = "SELL" if qty > 0 else "BUY"
    abs_qty = abs(qty)
    entry_orders = _order_count(order_counts, trade.get("securityId"), entry_side)
    entry = option_order_charges(
        premium=avg_price,
        quantity=abs_qty,
        side=entry_side,
        exchange_segment=str(trade.get("exchangeSegment") or ""),
        settings=settings,
        order_count=entry_orders,
    )
    exit_charges = option_order_charges(
        premium=ltp or 0,
        quantity=abs_qty,
        side=exit_side,
        exchange_segment=str(trade.get("exchangeSegment") or ""),
        settings=settings,
    )
    total = round(entry["total"] + exit_charges["total"], 2)
    trade["estimatedCharges"] = total
    trade["estimatedNetPnl"] = round((_number(trade.get("dayPnl")) or 0) - total, 2)
    trade["charges"] = {"entry": entry, "exitAtLtp": exit_charges, "total": total}


def apply_closed_option_charge_estimates(
    trade: dict[str, Any],
    settings: Settings | None = None,
    order_counts: dict[tuple[str, str], int] | None = None,
) -> None:
    settings = settings or get_settings()
    if trade.get("assetClass") != "OPTION":
        trade["estimatedCharges"] = None
        trade["estimatedNetPnl"] = trade.get("dayPnl")
        return

    buy_avg = _number(trade.get("buyAvg"))
    sell_avg = _number(trade.get("sellAvg"))
    buy_qty = int(_number(trade.get("buyQty")) or 0)
    sell_qty = int(_number(trade.get("sellQty")) or 0)
    security_id = trade.get("securityId")

    buy_charges = option_order_charges(
        premium=buy_avg or 0,
        quantity=buy_qty,
        side="BUY",
        exchange_segment=str(trade.get("exchangeSegment") or ""),
        settings=settings,
        order_count=_order_count(order_counts, security_id, "BUY"),
    )
    sell_charges = option_order_charges(
        premium=sell_avg or 0,
        quantity=sell_qty,
        side="SELL",
        exchange_segment=str(trade.get("exchangeSegment") or ""),
        settings=settings,
        order_count=_order_count(order_counts, security_id, "SELL"),
    )
    total = round(buy_charges["total"] + sell_charges["total"], 2)
    trade["estimatedCharges"] = total
    trade["estimatedNetPnl"] = round((_number(trade.get("dayPnl")) or 0) - total, 2)
    trade["charges"] = {"buy": buy_charges, "sell": sell_charges, "total": total}


def order_counts_from_trade_book(trade_book: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for row in trade_book:
        security_id = str(row.get("securityId") or "")
        transaction_type = str(row.get("transactionType") or "").upper()
        if not security_id or not transaction_type:
            continue
        key = (security_id, transaction_type)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _order_count(
    order_counts: dict[tuple[str, str], int] | None, security_id: Any, side: str
) -> int:
    if not order_counts or not security_id:
        return 1
    return max(order_counts.get((str(security_id), side.upper()), 0), 1)


def option_order_charges(
    *,
    premium: float,
    quantity: int,
    side: str,
    exchange_segment: str,
    settings: Settings | None = None,
    order_count: int = 1,
) -> dict[str, Any]:
    settings = settings or get_settings()
    turnover = max(premium, 0) * max(quantity, 0)
    transaction_percent = (
        settings.option_bse_transaction_percent
        if exchange_segment.upper().startswith("BSE")
        else settings.option_nse_transaction_percent
    )
    brokerage = settings.option_brokerage_per_order * max(order_count, 1) if quantity > 0 else 0
    transaction = _round_money(_percent(turnover, transaction_percent))
    sebi = _round_money(_percent(turnover, settings.option_sebi_turnover_percent))
    ipft = _round_money(_percent(turnover, settings.option_ipft_percent))
    stt = _round_rupee(_percent(turnover, settings.option_stt_sell_percent)) if side.upper() == "SELL" else 0
    stamp = _round_rupee(_percent(turnover, settings.option_stamp_buy_percent)) if side.upper() == "BUY" else 0
    gst = _round_money(_percent(brokerage + transaction + sebi + ipft, settings.option_gst_percent))
    total = _round_money(brokerage + transaction + sebi + ipft + stt + stamp + gst)
    return {
        "side": side.upper(),
        "turnover": _round_money(turnover),
        "brokerage": _round_money(brokerage),
        "transaction": transaction,
        "sebi": sebi,
        "ipft": ipft,
        "stt": stt,
        "stamp": stamp,
        "gst": gst,
        "total": total,
    }


def _percent(value: float, percent: float) -> float:
    return value * percent / 100


def _round_money(value: float) -> float:
    return round(value + 1e-9, 2)


def _round_rupee(value: float) -> int:
    return int(value + 0.5)


def _number(value: Any) -> float | None:
    if value in (None, "", "NA", "NaN"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
