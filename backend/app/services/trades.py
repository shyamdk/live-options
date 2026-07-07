from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from app.core.config import get_settings
from app.db.sqlite import (
    get_trade_actions,
    get_trade_levels,
    has_configured_trade_levels,
    record_alert_once,
    record_trade_action,
    upsert_trade_levels,
)
from app.services.charges import (
    apply_closed_option_charge_estimates,
    apply_option_charge_estimates,
    order_counts_from_trade_book,
)
from app.services.dhan import DhanService
from app.services.market import MarketService
from app.services.orders import DhanOrderService
from app.services.telegram import TelegramNotifier


_TRADE_LTP_CACHE: dict[str, float] = {}


async def live_trade_snapshot() -> dict[str, Any]:
    try:
        return await _live_trade_snapshot()
    except Exception as exc:
        return _empty_snapshot(str(exc))


async def _live_trade_snapshot() -> dict[str, Any]:
    service = DhanService()
    raw_positions = await service.positions()
    trades = [trade for row in raw_positions if (trade := _normalize_position(row))]
    open_trades = [trade for trade in trades if trade.get("status") != "CLOSED"]
    closed = [trade for trade in trades if trade.get("status") == "CLOSED"]
    await _apply_live_quotes(service, open_trades)
    await _apply_spot_distances(open_trades)

    try:
        trade_book = await service.trade_book()
    except Exception:
        trade_book = []
    order_counts = order_counts_from_trade_book(trade_book)

    option_trades = [trade for trade in open_trades if trade["assetClass"] == "OPTION"]
    levels_by_id = get_trade_levels([trade["id"] for trade in option_trades])
    risk_actions_by_id = get_trade_actions([trade["id"] for trade in option_trades], action_prefix="RISK_EXIT_")
    for trade in option_trades:
        trade["levels"] = levels_by_id.get(trade["id"]) or _empty_levels(trade)
        trade["riskStatus"] = _risk_status(trade, risk_actions_by_id.get(trade["id"]) or [])
        apply_option_charge_estimates(trade, order_counts=order_counts)
    for trade in closed:
        if trade["assetClass"] == "OPTION":
            apply_closed_option_charge_estimates(trade, order_counts=order_counts)
        else:
            trade["estimatedCharges"] = None
            trade["estimatedNetPnl"] = trade.get("dayPnl")

    equity = [trade for trade in open_trades if trade["assetClass"] == "EQUITY"]
    options_buy = [trade for trade in option_trades if trade["side"] == "BUY"]
    options_sell = [trade for trade in option_trades if trade["side"] == "SELL"]
    await _notify_spot_distance_alerts(options_sell)
    summary = _summary(closed, equity, options_buy, options_sell)
    return {
        "source": "dhan",
        "warning": None,
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "groups": {
            "closed": sorted(closed, key=_closed_sort_key),
            "equity": sorted(equity, key=lambda row: row["tradingSymbol"]),
            "optionsBuy": sorted(options_buy, key=_option_sort_key),
            "optionsSell": sorted(options_sell, key=_option_sort_key),
        },
    }


async def save_trade_levels(trade_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = await live_trade_snapshot()
    trade = _find_trade(snapshot, trade_id)
    if not trade:
        payload = {"tradeId": trade_id, **payload}
    else:
        payload = {
            **payload,
            "symbol": trade.get("symbol"),
            "expiry": trade.get("expiry"),
            "strikePrice": trade.get("strikePrice"),
            "optionSide": trade.get("optionSide"),
        }
    return upsert_trade_levels(trade_id, payload)


async def close_trade(trade_id: str, quantity: int | None = None) -> dict[str, Any]:
    snapshot = await live_trade_snapshot()
    trade = _find_trade(snapshot, trade_id)
    if not trade:
        return {"status": "blocked", "message": "Trade is no longer active.", "tradeId": trade_id}
    if trade.get("assetClass") != "OPTION":
        return {"status": "blocked", "message": "Only option trades can be closed from this page.", "tradeId": trade_id}
    close_quantity = quantity or abs(int(trade.get("qty") or 0))
    if close_quantity <= 0:
        return {"status": "blocked", "message": "Quantity must be greater than zero.", "tradeId": trade_id}
    if not trade.get("securityId") or not trade.get("exchangeSegment"):
        return {"status": "blocked", "message": "Trade is missing Dhan security id or exchange segment.", "tradeId": trade_id}

    transaction_type = "SELL" if int(trade.get("qty") or 0) > 0 else "BUY"
    result = await DhanOrderService().place_market_order(
        transaction_type=transaction_type,
        exchange_segment=str(trade["exchangeSegment"]),
        security_id=trade["securityId"],
        quantity=close_quantity,
        correlation_id=f"CLOSE-{trade.get('symbol')}-{int(datetime.now().timestamp())}",
        product_type=trade.get("productType"),
    )
    record_trade_action(trade_id, "CLOSE", str(result.get("status") or "unknown"), result.get("request"), result)
    return {"tradeId": trade_id, "closeSide": transaction_type, "quantity": close_quantity, "data": result, "status": result.get("status")}


def start_risk_order_monitor_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.risk_order_monitor_enabled:
        return None
    return asyncio.create_task(_risk_order_monitor_loop())


async def stop_risk_order_monitor_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def process_risk_order_check() -> dict[str, Any]:
    settings = get_settings()
    if not settings.risk_order_monitor_enabled:
        return {"enabled": False, "checked": 0, "actions": []}
    if not has_configured_trade_levels():
        return {"enabled": True, "executionEnabled": settings.risk_order_execution_enabled, "checked": 0, "actions": []}

    snapshot = await _live_trade_snapshot()
    groups = snapshot.get("groups") or {}
    option_trades = [*(groups.get("optionsBuy") or []), *(groups.get("optionsSell") or [])]
    actions = []
    for trade in option_trades:
        action = await _maybe_alert_risk_exit(trade)
        if action:
            actions.append(action)
    return {
        "enabled": True,
        "executionEnabled": settings.risk_order_execution_enabled,
        "checked": len(option_trades),
        "actions": actions,
    }


async def _risk_order_monitor_loop() -> None:
    settings = get_settings()
    interval = max(settings.risk_order_monitor_interval_seconds, 1)
    while True:
        try:
            await process_risk_order_check()
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(interval)


async def _maybe_alert_risk_exit(trade: dict[str, Any]) -> dict[str, Any] | None:
    """Never places orders automatically. Alerts (Telegram + web) and waits for manual approval."""
    settings = get_settings()
    signal = _risk_exit_signal(trade, settings.risk_order_allow_stale_ltp)
    if not signal:
        return None
    if signal.get("status") == "skipped":
        return signal

    alert_action_name = f"RISK_ALERT_{str(signal['kind']).upper()}"
    if not _should_send_risk_alert(trade, signal, alert_action_name, settings.risk_order_alert_repeat_seconds):
        return {"tradeId": trade.get("id"), "status": "awaiting-approval", **signal}

    record_trade_action(str(trade.get("id")), alert_action_name, "sent", None, {"signal": signal})
    await _notify_risk_awaiting_approval(trade, signal)
    return {"tradeId": trade.get("id"), "status": "alerted", **signal}


def _should_send_risk_alert(
    trade: dict[str, Any], signal: dict[str, Any], alert_action_name: str, repeat_seconds: int
) -> bool:
    trade_id = str(trade.get("id"))
    actions = get_trade_actions([trade_id], action_prefix=alert_action_name).get(trade_id) or []
    level = _number(signal.get("level")) or 0.0
    latest = _latest_matching_risk_action(trade, actions, alert_action_name, level)
    if not latest:
        return True
    created_at = _parse_datetime(latest.get("createdAt"))
    if not created_at:
        return True
    return datetime.now() >= created_at + timedelta(seconds=max(repeat_seconds, 1))


async def approve_risk_exit(trade_id: str) -> dict[str, Any]:
    """Called only when the user clicks Approve in the UI. Places the actual exit order."""
    settings = get_settings()
    snapshot = await _live_trade_snapshot()
    trade = _find_trade(snapshot, trade_id)
    if not trade:
        return {"status": "blocked", "message": "Trade is no longer active.", "tradeId": trade_id}

    status = trade.get("riskStatus") or {}
    kind = status.get("signalKind") or status.get("kind")
    if kind not in {"stopLoss", "target"}:
        return {"status": "blocked", "message": "No active SL/Target signal to approve.", "tradeId": trade_id}

    qty = int(trade.get("qty") or 0)
    security_id = trade.get("securityId")
    exchange_segment = trade.get("exchangeSegment")
    if trade.get("assetClass") != "OPTION" or qty == 0 or not security_id or not exchange_segment:
        return {"status": "blocked", "message": "Trade is missing option order fields.", "tradeId": trade_id}

    close_side = "SELL" if qty > 0 else "BUY"
    correlation_id = f"RISK-{kind}-{trade.get('symbol')}-{int(datetime.now().timestamp())}"
    signal = {
        "kind": kind,
        "level": status.get("level"),
        "ltp": trade.get("ltp"),
        "quantity": abs(qty),
        "closeSide": close_side,
        "correlationId": correlation_id,
        "mode": "live" if settings.risk_order_execution_enabled and settings.live_order_enabled else "dry-run",
    }

    action_name = f"RISK_EXIT_{str(kind).upper()}"
    order_service = DhanOrderService(settings)
    try:
        request = order_service.build_market_order_request(
            transaction_type=close_side,
            exchange_segment=str(exchange_segment),
            security_id=security_id,
            quantity=abs(qty),
            correlation_id=correlation_id,
            product_type=trade.get("productType"),
        )
    except Exception as exc:
        result = {"status": "failed", "message": str(exc), "request": None, "order": None}
        record_trade_action(trade_id, action_name, "failed", None, {**result, "signal": signal})
        await _notify_risk_exit(trade, signal, result)
        return {"tradeId": trade_id, "status": "failed", **signal}

    if not settings.risk_order_execution_enabled:
        result = {
            "status": "blocked",
            "message": "RISK_ORDER_EXECUTION_ENABLED is false. Approved SL/Target order was not sent to Dhan.",
            "request": request,
            "order": None,
        }
    else:
        result = await order_service.place_market_order(
            transaction_type=close_side,
            exchange_segment=str(exchange_segment),
            security_id=security_id,
            quantity=abs(qty),
            correlation_id=correlation_id,
            product_type=trade.get("productType"),
        )

    order_success = _is_successful_order_result(result)
    audit_result = {**result, "signal": signal, "orderSuccess": order_success}
    record_trade_action(trade_id, action_name, str(result.get("status") or "unknown"), request, audit_result)
    await _notify_risk_exit(trade, signal, result)
    return {"tradeId": trade_id, "status": result.get("status"), "order": result.get("order"), **signal}


def start_spot_distance_monitor_task() -> asyncio.Task | None:
    settings = get_settings()
    if not settings.spot_distance_monitor_enabled:
        return None
    return asyncio.create_task(_spot_distance_monitor_loop())


async def stop_spot_distance_monitor_task(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return


async def _spot_distance_monitor_loop() -> None:
    settings = get_settings()
    interval = max(settings.spot_distance_monitor_interval_seconds, 10)
    while True:
        try:
            await asyncio.sleep(interval)
            await _live_trade_snapshot()
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(interval)


def _find_trade(snapshot: dict[str, Any], trade_id: str) -> dict[str, Any] | None:
    groups = snapshot.get("groups") or {}
    for key in ("optionsBuy", "optionsSell", "equity"):
        for trade in groups.get(key) or []:
            if trade.get("id") == trade_id:
                return trade
    return None


def _normalize_position(row: dict[str, Any]) -> dict[str, Any] | None:
    qty = int(_number(_first(row, "netQty", "netQuantity", "quantity", "positionQty")) or 0)

    trading_symbol = str(_first(row, "tradingSymbol", "customSymbol", "symbol") or "").strip()
    security_id = str(_first(row, "securityId", "security_id") or "")
    exchange_segment = str(_first(row, "exchangeSegment", "exchange_segment") or "")
    product_type = str(_first(row, "productType", "product") or "")
    instrument = str(_first(row, "instrument", "instrumentType", "drvInstrumentType") or "").upper()
    strike = _number(_first(row, "drvStrikePrice", "strikePrice", "strike"))
    raw_option_type = str(_first(row, "drvOptionType", "optionType", "optionSide") or "").upper()
    option_side = _option_side(raw_option_type, trading_symbol)
    is_option = bool(option_side and (strike is not None or "OPT" in instrument or "FNO" in exchange_segment.upper()))
    buy_avg = _number(_first(row, "buyAvg", "buyAvgPrice"))
    sell_avg = _number(_first(row, "sellAvg", "sellAvgPrice"))
    buy_qty = int(_number(_first(row, "buyQty", "dayBuyQty")) or 0)
    sell_qty = int(_number(_first(row, "sellQty", "daySellQty")) or 0)
    avg_price = _average_price(row, qty)
    ltp = _number(_first(row, "lastTradedPrice", "ltp", "lastPrice", "last_price"))
    realized = round(_number(_first(row, "realizedProfit", "realizedPnl", "realisedProfit")) or 0, 2)
    position_open_pnl = _number(_first(row, "unrealizedProfit", "unrealizedPnl", "unrealisedProfit"))
    position_type = str(_first(row, "positionType", "positionStatus", "status") or "").upper()
    is_closed = qty == 0 and (position_type == "CLOSED" or realized != 0 or (buy_qty > 0 and sell_qty > 0))
    if qty == 0 and not is_closed:
        return None

    asset_class = "OPTION" if is_option else "EQUITY"
    symbol = _underlying_symbol(trading_symbol) if asset_class == "OPTION" else _equity_symbol(trading_symbol)
    expiry = _date_part(_first(row, "drvExpiryDate", "expiryDate", "expiry"))
    trade_id = _trade_id(asset_class, security_id, exchange_segment, product_type, symbol, expiry, strike, option_side)

    if is_closed:
        closed_qty = max(abs(buy_qty), abs(sell_qty))
        entry_side = _closed_entry_side(row, buy_avg, sell_avg, asset_class)
        entry_avg = sell_avg if entry_side == "SELL" else buy_avg
        exit_avg = buy_avg if entry_side == "SELL" else sell_avg
        if entry_avg is None:
            entry_avg = avg_price
        percent_qty = -closed_qty if entry_side == "SELL" else closed_qty
        return {
            "id": trade_id,
            "assetClass": asset_class,
            "symbol": symbol,
            "tradingSymbol": trading_symbol or symbol,
            "securityId": security_id,
            "exchangeSegment": exchange_segment,
            "productType": product_type,
            "instrument": instrument,
            "expiry": expiry,
            "strikePrice": strike,
            "optionSide": option_side,
            "side": entry_side,
            "entrySide": entry_side,
            "status": "CLOSED",
            "qty": 0,
            "absQty": closed_qty,
            "closedQty": closed_qty,
            "buyQty": buy_qty,
            "sellQty": sell_qty,
            "buyAvg": buy_avg,
            "sellAvg": sell_avg,
            "avgPrice": entry_avg,
            "entryAvgPrice": entry_avg,
            "exitAvgPrice": exit_avg,
            "ltp": exit_avg,
            "ltpDerived": False,
            "positionOpenPnl": position_open_pnl,
            "pnlSource": "position",
            "openPnl": 0,
            "realizedPnl": realized,
            "dayPnl": realized,
            "percentChange": _percent_change(entry_avg, exit_avg, percent_qty),
            "rawProductType": row.get("productType"),
        }

    ltp_derived = False
    if ltp is None:
        ltp = _ltp_from_open_pnl(avg_price, position_open_pnl, qty)
        ltp_derived = ltp is not None
    open_pnl = position_open_pnl
    if open_pnl is None:
        open_pnl = _live_pnl(avg_price, ltp, qty)
    open_pnl = round(open_pnl or 0, 2)

    trade = {
        "id": trade_id,
        "assetClass": asset_class,
        "symbol": symbol,
        "tradingSymbol": trading_symbol or symbol,
        "securityId": security_id,
        "exchangeSegment": exchange_segment,
        "productType": product_type,
        "instrument": instrument,
        "expiry": expiry,
        "strikePrice": strike,
        "optionSide": option_side,
        "side": "BUY" if qty > 0 else "SELL",
        "status": "OPEN",
        "qty": qty,
        "absQty": abs(qty),
        "buyQty": buy_qty,
        "sellQty": sell_qty,
        "buyAvg": buy_avg,
        "sellAvg": sell_avg,
        "avgPrice": avg_price,
        "ltp": ltp,
        "ltpDerived": ltp_derived,
        "positionOpenPnl": position_open_pnl,
        "pnlSource": "position" if position_open_pnl is not None else "calculated",
        "openPnl": open_pnl,
        "realizedPnl": realized,
        "dayPnl": round(open_pnl + realized, 2),
        "percentChange": _percent_change(avg_price, ltp, qty),
        "rawProductType": row.get("productType"),
    }
    used_stale_ltp = _apply_cached_ltp(trade)
    if used_stale_ltp:
        if position_open_pnl is None:
            trade["openPnl"] = _live_pnl(avg_price, trade.get("ltp"), qty)
            trade["dayPnl"] = round((_number(trade.get("openPnl")) or 0) + realized, 2)
        trade["percentChange"] = _percent_change(avg_price, trade.get("ltp"), qty)
    _apply_profit_remaining(trade)
    return trade


async def _apply_live_quotes(service: DhanService, trades: list[dict[str, Any]]) -> None:
    securities_by_segment: dict[str, list[int]] = {}
    for trade in trades:
        if trade.get("positionOpenPnl") is not None:
            continue
        security_id = _int(trade.get("securityId"))
        segment = str(trade.get("exchangeSegment") or "")
        if security_id and segment:
            securities_by_segment.setdefault(segment, []).append(security_id)
    if not securities_by_segment:
        return
    try:
        quotes = await service.market_quotes_by_segment(securities_by_segment)
    except Exception:
        return
    for trade in trades:
        quote = (quotes.get(str(trade.get("exchangeSegment") or "")) or {}).get(str(trade.get("securityId") or "")) or {}
        live_ltp = _number(quote.get("last_price"))
        if live_ltp is not None:
            trade["ltp"] = live_ltp
            trade["ltpDerived"] = False
            trade["ltpStale"] = False
            _remember_ltp(trade)
            _refresh_metrics(trade)


def _refresh_metrics(trade: dict[str, Any]) -> None:
    avg_price = _number(trade.get("avgPrice"))
    ltp = _number(trade.get("ltp"))
    qty = int(trade.get("qty") or 0)
    open_pnl = _live_pnl(avg_price, ltp, qty)
    realized = round(_number(trade.get("realizedPnl")) or 0, 2)
    trade["openPnl"] = open_pnl
    trade["dayPnl"] = round(open_pnl + realized, 2)
    trade["percentChange"] = _percent_change(avg_price, ltp, qty)
    _apply_profit_remaining(trade)
    apply_option_charge_estimates(trade)


async def _apply_spot_distances(trades: list[dict[str, Any]]) -> None:
    option_trades = [trade for trade in trades if trade.get("assetClass") == "OPTION"]
    if not option_trades:
        return
    try:
        payload = await MarketService().indices()
    except Exception:
        return
    spots: dict[str, float] = {}
    for index in payload.get("indices") or []:
        name = str(index.get("name") or "").upper()
        last_price = _number(index.get("lastPrice"))
        if last_price is None:
            continue
        if "NIFTY 50" in name:
            spots["NIFTY"] = last_price
        elif "SENSEX" in name:
            spots["SENSEX"] = last_price
    for trade in option_trades:
        spot = spots.get(str(trade.get("symbol") or "").upper())
        strike = _number(trade.get("strikePrice"))
        if spot is None or not spot or strike is None:
            continue
        signed_points = strike - spot
        distance_points = abs(signed_points)
        distance_percent = round((distance_points / spot) * 100, 2)
        trade["spotPrice"] = spot
        trade["spotDistancePoints"] = round(distance_points, 2)
        trade["spotDistancePercent"] = distance_percent
        trade["spotDistanceSignedPoints"] = round(signed_points, 2)


async def _notify_spot_distance_alerts(options_sell: list[dict[str, Any]]) -> None:
    settings = get_settings()
    if not settings.spot_distance_alert_enabled:
        return
    threshold = abs(settings.spot_distance_alert_percent)
    notifier = TelegramNotifier(settings)
    for trade in options_sell:
        distance_percent = _number(trade.get("spotDistancePercent"))
        if distance_percent is None or distance_percent > threshold:
            continue
        trade["spotDistanceAlert"] = True
        alert_key = f"{datetime.now().date().isoformat()}:spot-distance:{trade.get('id')}:{threshold:g}"
        if not record_alert_once(alert_key, {"tradeId": trade.get("id"), "distancePercent": distance_percent, "threshold": threshold}):
            continue
        spot = _number(trade.get("spotPrice"))
        strike = _number(trade.get("strikePrice"))
        await notifier.send(
            "\n".join(
                [
                    "Spot distance alert",
                    f"{trade.get('symbol')} {strike:g} {trade.get('optionSide')} is {distance_percent:.2f}% from spot.",
                    f"Spot: {spot:.2f}" if spot is not None else "Spot: -",
                    f"LTP: {_text_number(trade.get('ltp'))}, Qty: {trade.get('qty')}",
                    f"Threshold: {threshold:.2f}%",
                ]
            )
        )


def _apply_profit_remaining(trade: dict[str, Any]) -> None:
    avg_price = _number(trade.get("avgPrice"))
    ltp = _number(trade.get("ltp"))
    qty = int(trade.get("qty") or 0)
    if qty >= 0 or avg_price is None or avg_price <= 0:
        trade["maxProfit"] = None
        trade["profitRemaining"] = None
        trade["profitRemainingPercent"] = None
        return

    max_profit = round(avg_price * abs(qty), 2)
    remaining = round((ltp or 0) * abs(qty), 2) if ltp is not None else None
    trade["maxProfit"] = max_profit
    trade["profitRemaining"] = remaining
    trade["profitRemainingPercent"] = round((remaining / max_profit) * 100, 2) if remaining is not None and max_profit else None


def _apply_cached_ltp(trade: dict[str, Any]) -> bool:
    trade_id = str(trade.get("id") or "")
    ltp = _number(trade.get("ltp"))
    if ltp is not None:
        trade["ltpStale"] = False
        _remember_ltp(trade)
        return False
    cached_ltp = _TRADE_LTP_CACHE.get(trade_id)
    if cached_ltp is None:
        return False
    trade["ltp"] = cached_ltp
    trade["ltpStale"] = True
    return True


def _remember_ltp(trade: dict[str, Any]) -> None:
    trade_id = str(trade.get("id") or "")
    ltp = _number(trade.get("ltp"))
    if trade_id and ltp is not None:
        _TRADE_LTP_CACHE[trade_id] = ltp


def _summary(
    closed: list[dict[str, Any]],
    equity: list[dict[str, Any]],
    options_buy: list[dict[str, Any]],
    options_sell: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = [*closed, *equity, *options_buy, *options_sell]
    open_pnl = round(sum(_number(row.get("openPnl")) or 0 for row in rows), 2)
    realized = round(sum(_number(row.get("realizedPnl")) or 0 for row in rows), 2)
    estimated_charges = round(sum(_number(row.get("estimatedCharges")) or 0 for row in [*closed, *options_buy, *options_sell]), 2)
    return {
        "totalPositions": len(rows),
        "closedCount": len(closed),
        "equityCount": len(equity),
        "optionsBuyCount": len(options_buy),
        "optionsSellCount": len(options_sell),
        "openPnl": open_pnl,
        "realizedPnl": realized,
        "dayPnl": round(open_pnl + realized, 2),
        "estimatedCharges": estimated_charges,
        "estimatedNetPnl": round(open_pnl + realized - estimated_charges, 2),
        "configuredLevels": sum(1 for row in [*options_buy, *options_sell] if (row.get("levels") or {}).get("stopLoss") or (row.get("levels") or {}).get("target")),
        "stopLossHits": sum(1 for row in [*options_buy, *options_sell] if (row.get("riskStatus") or {}).get("kind") == "stopLoss"),
        "targetHits": sum(1 for row in [*options_buy, *options_sell] if (row.get("riskStatus") or {}).get("kind") == "target"),
    }


def _risk_status_for_signal(
    trade: dict[str, Any],
    kind: str,
    level: float,
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    exit_action_name = f"RISK_EXIT_{kind.upper()}"
    success = _latest_matching_risk_action(trade, actions, exit_action_name, level, success_only=True)
    if success:
        return {
            "kind": kind,
            "signalKind": kind,
            "label": "Target hit" if kind == "target" else "SL hit",
            "level": level,
            "orderStatus": "sent",
            "orderAction": success.get("action"),
            "orderId": _order_id_from_action(success),
            "orderAt": success.get("createdAt"),
        }

    latest = _latest_matching_risk_action(trade, actions, exit_action_name, level)
    if latest:
        retry_at = _risk_retry_at(latest)
        retry_active = retry_at is not None and datetime.now() < retry_at
        status = str(latest.get("status") or "unknown")
        if status in {"failed", "blocked"} and retry_active:
            return {
                "kind": "orderFailed",
                "signalKind": kind,
                "label": "Target order failed" if kind == "target" else "SL order failed",
                "level": level,
                "orderStatus": status,
                "orderAction": latest.get("action"),
                "orderAt": latest.get("createdAt"),
                "retryAt": retry_at.isoformat(timespec="seconds") if retry_at else None,
                "message": _action_message(latest),
            }

    return {
        "kind": "targetSignal" if kind == "target" else "stopLossSignal",
        "signalKind": kind,
        "label": "Target reached" if kind == "target" else "SL reached",
        "level": level,
    }


def _latest_matching_risk_action(
    trade: dict[str, Any],
    actions: list[dict[str, Any]],
    action_name: str,
    level: float,
    *,
    success_only: bool = False,
) -> dict[str, Any] | None:
    levels_updated_at = _parse_datetime((trade.get("levels") or {}).get("updatedAt"))
    for action in actions:
        if action.get("action") != action_name:
            continue
        created_at = _parse_datetime(action.get("createdAt"))
        if levels_updated_at and created_at and created_at < levels_updated_at:
            continue
        response = action.get("response") or {}
        signal = response.get("signal") if isinstance(response, dict) else None
        signal_level = _number((signal or {}).get("level")) if isinstance(signal, dict) else None
        if signal_level is not None and abs(signal_level - level) > 0.0001:
            continue
        if success_only and not _risk_action_successful(action):
            continue
        return action
    return None


def _risk_action_successful(action: dict[str, Any]) -> bool:
    status = str(action.get("status") or "").lower()
    response = action.get("response") or {}
    if isinstance(response, dict) and response.get("orderSuccess") is True:
        return True
    if status not in {"sent", "success", "placed", "submitted"}:
        return False
    return not _order_payload_failed(response.get("order") if isinstance(response, dict) else None)


def _is_successful_order_result(result: dict[str, Any]) -> bool:
    if str(result.get("status") or "").lower() != "sent":
        return False
    return not _order_payload_failed(result.get("order"))


def _order_payload_failed(order: Any) -> bool:
    failed_statuses = {"failed", "failure", "rejected", "cancelled", "canceled", "error"}
    if isinstance(order, dict):
        for key in ("status", "orderStatus", "order_status", "errorType", "errorCode"):
            value = str(order.get(key) or "").lower()
            if value in failed_statuses or value.startswith("dh-"):
                return True
        data = order.get("data")
        if isinstance(data, dict):
            return _order_payload_failed(data)
    return False


def _risk_retry_at(action: dict[str, Any]) -> datetime | None:
    created_at = _parse_datetime(action.get("createdAt"))
    if not created_at:
        return None
    retry_seconds = max(get_settings().risk_order_retry_seconds, 5)
    return created_at.replace(microsecond=0) + timedelta(seconds=retry_seconds)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _order_id_from_action(action: dict[str, Any]) -> str | None:
    response = action.get("response") or {}
    order = response.get("order") if isinstance(response, dict) else None
    return _order_id_from_payload(order)


def _order_id_from_payload(order: Any) -> str | None:
    if not isinstance(order, dict):
        return None
    for key in ("orderId", "order_id", "orderNo", "orderNumber"):
        value = order.get(key)
        if value:
            return str(value)
    data = order.get("data")
    if isinstance(data, dict):
        return _order_id_from_payload(data)
    return None


def _action_message(action: dict[str, Any]) -> str | None:
    response = action.get("response") or {}
    if not isinstance(response, dict):
        return None
    message = response.get("message")
    if message:
        return str(message)
    order = response.get("order")
    if isinstance(order, dict):
        for key in ("errorMessage", "message", "remarks"):
            value = order.get(key)
            if value:
                return str(value)
    return None


def _risk_status(trade: dict[str, Any], actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    levels = trade.get("levels") or {}
    ltp = _number(trade.get("ltp"))
    qty = int(trade.get("qty") or 0)
    if ltp is None or qty == 0:
        return {"kind": "none", "label": "Monitoring"}
    stop_loss = _number(levels.get("stopLoss"))
    target = _number(levels.get("target"))
    is_short = qty < 0
    if stop_loss is not None and ((is_short and ltp >= stop_loss) or (not is_short and ltp <= stop_loss)):
        return _risk_status_for_signal(trade, "stopLoss", stop_loss, actions or [])
    if target is not None and ((is_short and ltp <= target) or (not is_short and ltp >= target)):
        return _risk_status_for_signal(trade, "target", target, actions or [])
    return {"kind": "none", "label": "Monitoring"}


def _risk_exit_signal(trade: dict[str, Any], allow_stale_ltp: bool = False) -> dict[str, Any] | None:
    status = trade.get("riskStatus") or {}
    kind = status.get("signalKind") or status.get("kind")
    if kind not in {"stopLoss", "target"}:
        return None
    if status.get("orderStatus") == "sent":
        return None
    retry_at = _parse_datetime(status.get("retryAt"))
    if retry_at and datetime.now() < retry_at:
        return {
            "tradeId": trade.get("id"),
            "kind": kind,
            "status": "skipped",
            "reason": f"retry after {retry_at.isoformat(timespec='seconds')}",
            "level": status.get("level"),
            "ltp": trade.get("ltp"),
        }
    if trade.get("ltpStale") and not allow_stale_ltp:
        return {
            "tradeId": trade.get("id"),
            "kind": kind,
            "status": "skipped",
            "reason": "stale LTP",
            "level": status.get("level"),
            "ltp": trade.get("ltp"),
        }

    qty = int(trade.get("qty") or 0)
    security_id = trade.get("securityId")
    exchange_segment = trade.get("exchangeSegment")
    if trade.get("assetClass") != "OPTION" or qty == 0 or not security_id or not exchange_segment:
        return {
            "tradeId": trade.get("id"),
            "kind": kind,
            "status": "skipped",
            "reason": "missing option order fields",
            "level": status.get("level"),
            "ltp": trade.get("ltp"),
        }

    close_side = "SELL" if qty > 0 else "BUY"
    correlation_id = f"RISK-{kind}-{trade.get('symbol')}-{int(datetime.now().timestamp())}"
    return {
        "kind": kind,
        "level": status.get("level"),
        "ltp": trade.get("ltp"),
        "quantity": abs(qty),
        "closeSide": close_side,
        "correlationId": correlation_id,
    }


async def _notify_risk_exit(trade: dict[str, Any], signal: dict[str, Any], result: dict[str, Any]) -> None:
    status = str(result.get("status") or "unknown").upper()
    level = _number(signal.get("level"))
    ltp = _number(signal.get("ltp"))
    label = _risk_trade_label(trade)
    lines = [
        f"Approved risk exit {status}",
        label,
        f"Reason: {signal.get('kind')}, Level: {_text_number(level)}",
        f"LTP: {_text_number(ltp)}, Close: {signal.get('closeSide')} {signal.get('quantity')}",
        f"Mode: {signal.get('mode')}",
    ]
    message = result.get("message")
    if message:
        lines.append(str(message))
    await TelegramNotifier().send("\n".join(lines))


async def _notify_risk_awaiting_approval(trade: dict[str, Any], signal: dict[str, Any]) -> None:
    level = _number(signal.get("level"))
    ltp = _number(signal.get("ltp"))
    label = _risk_trade_label(trade)
    kind_label = "Target" if signal.get("kind") == "target" else "Stop Loss"
    lines = [
        f"⚠️ {kind_label} reached — approval needed",
        label,
        f"Level: {_text_number(level)}, LTP: {_text_number(ltp)}",
        f"Close: {signal.get('closeSide')} {signal.get('quantity')}",
        "Open Manage Trades and click Approve to send the exit order.",
    ]
    await TelegramNotifier().send("\n".join(lines))


def _risk_trade_label(trade: dict[str, Any]) -> str:
    strike = _number(trade.get("strikePrice"))
    strike_text = f"{strike:g}" if strike is not None else str(trade.get("tradingSymbol") or "")
    return f"{trade.get('symbol')} {strike_text} {trade.get('optionSide') or ''}".strip()


def _empty_levels(trade: dict[str, Any]) -> dict[str, Any]:
    return {
        "tradeId": trade.get("id"),
        "symbol": trade.get("symbol"),
        "expiry": trade.get("expiry"),
        "strikePrice": trade.get("strikePrice"),
        "optionSide": trade.get("optionSide"),
        "stopLoss": None,
        "target": None,
        "notes": "",
        "updatedAt": None,
    }


def _empty_snapshot(warning: str | None = None) -> dict[str, Any]:
    return {
        "source": "error" if warning else "dhan",
        "warning": warning,
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "totalPositions": 0,
            "closedCount": 0,
            "equityCount": 0,
            "optionsBuyCount": 0,
            "optionsSellCount": 0,
            "openPnl": 0,
            "realizedPnl": 0,
            "dayPnl": 0,
            "estimatedCharges": 0,
            "estimatedNetPnl": 0,
            "configuredLevels": 0,
            "stopLossHits": 0,
            "targetHits": 0,
        },
        "groups": {"closed": [], "equity": [], "optionsBuy": [], "optionsSell": []},
    }


def _trade_id(
    asset_class: str,
    security_id: str,
    exchange_segment: str,
    product_type: str,
    symbol: str,
    expiry: str | None,
    strike: float | None,
    option_side: str | None,
) -> str:
    if security_id:
        return ":".join(part for part in (asset_class, exchange_segment, security_id, product_type) if part)
    strike_text = str(int(strike)) if strike is not None and float(strike).is_integer() else str(strike or "NA")
    return ":".join(part for part in (asset_class, symbol, expiry or "NA", strike_text, option_side or "NA", product_type) if part)


def _option_sort_key(trade: dict[str, Any]) -> tuple[str, str, float, str]:
    return (
        str(trade.get("symbol") or ""),
        str(trade.get("expiry") or ""),
        float(trade.get("strikePrice") or 0),
        str(trade.get("optionSide") or ""),
    )


def _closed_sort_key(trade: dict[str, Any]) -> tuple[str, str, float, str, str]:
    return (
        str(trade.get("symbol") or ""),
        str(trade.get("expiry") or ""),
        float(trade.get("strikePrice") or 0),
        str(trade.get("optionSide") or ""),
        str(trade.get("tradingSymbol") or ""),
    )


def _option_side(raw_option_type: str, trading_symbol: str) -> str | None:
    if raw_option_type in {"CALL", "CE"}:
        return "CE"
    if raw_option_type in {"PUT", "PE"}:
        return "PE"
    upper = trading_symbol.upper()
    if upper.endswith("CE"):
        return "CE"
    if upper.endswith("PE"):
        return "PE"
    return None


def _underlying_symbol(trading_symbol: str) -> str:
    upper = trading_symbol.upper()
    if upper.startswith("SENSEX"):
        return "SENSEX"
    if upper.startswith("BANKNIFTY"):
        return "BANKNIFTY"
    if upper.startswith("FINNIFTY"):
        return "FINNIFTY"
    if upper.startswith("MIDCPNIFTY"):
        return "MIDCPNIFTY"
    if upper.startswith("NIFTY"):
        return "NIFTY"
    return upper.split("-")[0] if upper else "OPTION"


def _equity_symbol(trading_symbol: str) -> str:
    return trading_symbol.upper().replace("-EQ", "").replace(" ", "") or "EQUITY"


def _average_price(row: dict[str, Any], qty: int) -> float | None:
    cost = _number(_first(row, "costPrice", "avgPrice", "averagePrice"))
    if cost:
        return cost
    if qty > 0:
        return _number(_first(row, "buyAvg", "buyAvgPrice"))
    return _number(_first(row, "sellAvg", "sellAvgPrice"))


def _closed_entry_side(row: dict[str, Any], buy_avg: float | None, sell_avg: float | None, asset_class: str) -> str:
    cost = _number(_first(row, "costPrice", "avgPrice", "averagePrice"))
    if cost is not None:
        if sell_avg is not None and abs(cost - sell_avg) < 0.0001:
            return "SELL"
        if buy_avg is not None and abs(cost - buy_avg) < 0.0001:
            return "BUY"
    return "SELL" if asset_class == "OPTION" else "BUY"


def _live_pnl(avg_price: float | None, ltp: float | None, qty: int) -> float:
    if avg_price is None or ltp is None or qty == 0:
        return 0
    return round((ltp - avg_price) * qty, 2)


def _ltp_from_open_pnl(avg_price: float | None, open_pnl: float | None, qty: int) -> float | None:
    if avg_price is None or open_pnl is None or qty == 0:
        return None
    return round(avg_price + (open_pnl / qty), 2)


def _percent_change(avg_price: float | None, ltp: float | None, qty: int) -> float | None:
    if not avg_price or ltp is None:
        return None
    change = ((ltp - avg_price) / avg_price) * 100
    if qty < 0:
        change *= -1
    return round(change, 2)


def _text_number(value: Any) -> str:
    number = _number(value)
    return "-" if number is None else f"{number:.2f}"


def _date_part(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    if text.startswith("0001-01-01"):
        return None
    return text[:10]


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", "NA"):
            return value
    return None


def _number(value: Any) -> float | None:
    if value in (None, "", "NA", "NaN"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None
