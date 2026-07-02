from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from app.core.config import get_settings
from app.db.sqlite import get_trade_levels, record_alert_once, record_trade_action, upsert_trade_levels
from app.services.charges import apply_option_charge_estimates
from app.services.dhan import DhanService
from app.services.market import MarketService
from app.services.orders import DhanOrderService
from app.services.telegram import TelegramNotifier


async def live_trade_snapshot() -> dict[str, Any]:
    try:
        return await _live_trade_snapshot()
    except Exception as exc:
        return _empty_snapshot(str(exc))


async def _live_trade_snapshot() -> dict[str, Any]:
    service = DhanService()
    raw_positions = await service.positions()
    trades = [trade for row in raw_positions if (trade := _normalize_position(row))]
    await _apply_live_quotes(service, trades)
    await _apply_spot_distances(trades)

    option_trades = [trade for trade in trades if trade["assetClass"] == "OPTION"]
    levels_by_id = get_trade_levels([trade["id"] for trade in option_trades])
    for trade in option_trades:
        trade["levels"] = levels_by_id.get(trade["id"]) or _empty_levels(trade)
        trade["riskStatus"] = _risk_status(trade)
        apply_option_charge_estimates(trade)

    equity = [trade for trade in trades if trade["assetClass"] == "EQUITY"]
    options_buy = [trade for trade in option_trades if trade["side"] == "BUY"]
    options_sell = [trade for trade in option_trades if trade["side"] == "SELL"]
    await _notify_spot_distance_alerts(options_sell)
    summary = _summary(equity, options_buy, options_sell)
    return {
        "source": "dhan",
        "warning": None,
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "groups": {
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
    if qty == 0:
        return None

    trading_symbol = str(_first(row, "tradingSymbol", "customSymbol", "symbol") or "").strip()
    security_id = str(_first(row, "securityId", "security_id") or "")
    exchange_segment = str(_first(row, "exchangeSegment", "exchange_segment") or "")
    product_type = str(_first(row, "productType", "product") or "")
    instrument = str(_first(row, "instrument", "instrumentType", "drvInstrumentType") or "").upper()
    strike = _number(_first(row, "drvStrikePrice", "strikePrice", "strike"))
    raw_option_type = str(_first(row, "drvOptionType", "optionType", "optionSide") or "").upper()
    option_side = _option_side(raw_option_type, trading_symbol)
    is_option = bool(option_side and (strike is not None or "OPT" in instrument or "FNO" in exchange_segment.upper()))
    avg_price = _average_price(row, qty)
    ltp = _number(_first(row, "lastTradedPrice", "ltp", "lastPrice", "last_price"))
    realized = round(_number(_first(row, "realizedProfit", "realizedPnl", "realisedProfit")) or 0, 2)
    open_pnl = _number(_first(row, "unrealizedProfit", "unrealizedPnl", "unrealisedProfit"))
    if open_pnl is None:
        open_pnl = _live_pnl(avg_price, ltp, qty)
    open_pnl = round(open_pnl or 0, 2)

    asset_class = "OPTION" if is_option else "EQUITY"
    symbol = _underlying_symbol(trading_symbol) if asset_class == "OPTION" else _equity_symbol(trading_symbol)
    expiry = _date_part(_first(row, "drvExpiryDate", "expiryDate", "expiry"))
    trade_id = _trade_id(asset_class, security_id, exchange_segment, product_type, symbol, expiry, strike, option_side)

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
        "qty": qty,
        "absQty": abs(qty),
        "avgPrice": avg_price,
        "ltp": ltp,
        "openPnl": open_pnl,
        "realizedPnl": realized,
        "dayPnl": round(open_pnl + realized, 2),
        "percentChange": _percent_change(avg_price, ltp, qty),
        "rawProductType": row.get("productType"),
    }
    _apply_profit_remaining(trade)
    return trade


async def _apply_live_quotes(service: DhanService, trades: list[dict[str, Any]]) -> None:
    securities_by_segment: dict[str, list[int]] = {}
    for trade in trades:
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


def _summary(equity: list[dict[str, Any]], options_buy: list[dict[str, Any]], options_sell: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [*equity, *options_buy, *options_sell]
    open_pnl = round(sum(_number(row.get("openPnl")) or 0 for row in rows), 2)
    realized = round(sum(_number(row.get("realizedPnl")) or 0 for row in rows), 2)
    estimated_charges = round(sum(_number(row.get("estimatedCharges")) or 0 for row in [*options_buy, *options_sell]), 2)
    return {
        "totalPositions": len(rows),
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


def _risk_status(trade: dict[str, Any]) -> dict[str, Any]:
    levels = trade.get("levels") or {}
    ltp = _number(trade.get("ltp"))
    qty = int(trade.get("qty") or 0)
    if ltp is None or qty == 0:
        return {"kind": "none", "label": "Monitoring"}
    stop_loss = _number(levels.get("stopLoss"))
    target = _number(levels.get("target"))
    is_short = qty < 0
    if stop_loss is not None and ((is_short and ltp >= stop_loss) or (not is_short and ltp <= stop_loss)):
        return {"kind": "stopLoss", "label": "SL hit", "level": stop_loss}
    if target is not None and ((is_short and ltp <= target) or (not is_short and ltp >= target)):
        return {"kind": "target", "label": "Target hit", "level": target}
    return {"kind": "none", "label": "Monitoring"}


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
        "groups": {"equity": [], "optionsBuy": [], "optionsSell": []},
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


def _live_pnl(avg_price: float | None, ltp: float | None, qty: int) -> float:
    if avg_price is None or ltp is None or qty == 0:
        return 0
    return round((ltp - avg_price) * qty, 2)


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
