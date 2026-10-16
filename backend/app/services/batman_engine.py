"""Batman (1:3:2 double ratio spread) -- pure construction logic.

Monthly follows docs/sources/batman-option-strategy-guide.pdf exactly: call side BUY 1x at
spot+400, SELL 3x 200 further, BUY 2x 800 beyond the sell; mirror on puts; 3/9/6
lot base; if ATM is a 50-strike the call base shifts up and the put base down
one strike; Filter 1 shifts the buy offset outward until net credit <= cap;
Filter 2 adds extra outer calls until the T+0 loss at an equal +-move is
balanced on both sides.

Weekly uses the same proportions measured in expected-move units (ATM
straddle) instead of fixed points, because a fixed +-400 means something very
different 11 days from expiry than 31 days from expiry.
"""

from __future__ import annotations

from typing import Any

from app.services import varaha_engine as ve

STRIKE_STEP = 50.0


def _round_to_step(value: float, step: float = STRIKE_STEP) -> float:
    return max(step, round(value / step) * step)


def bases(spot: float) -> tuple[float, float, float]:
    """(atm, call_base, put_base) -- a 50-strike ATM shifts the call base up
    and the put base down one strike (rulebook liquidity rule)."""
    atm = round(spot / STRIKE_STEP) * STRIKE_STEP
    if atm % 100:
        return atm, atm + STRIKE_STEP, atm - STRIKE_STEP
    return atm, atm, atm


def _quote(chain: list[dict[str, Any]], strike: float, option_type: str) -> dict[str, Any] | None:
    for row in chain:
        if abs(float(row["strike"]) - strike) < 0.01:
            quote = row.get(option_type.lower())
            return quote if quote and (quote.get("ltp") or 0) > 0 else None
    return None


def _fill(quote: dict[str, Any], action: str) -> float:
    bid, ask = quote.get("bid"), quote.get("ask")
    if bid and ask and ask >= bid > 0:
        return float(ask) if action == "BUY" else float(bid)
    return float(quote["ltp"])


def build_legs(
    chain: list[dict[str, Any]], spot: float, *, buy_offset: float, sell_gap: float, hedge_gap: float,
    base_lots: int, extra_call_lots: int = 0, short_ratio: int = 3, outer_ratio: int = 2,
) -> list[dict[str, Any]] | None:
    """Ratio defaults to the rulebook's 1:3:2 (inner : short : outer)."""
    _, call_base, put_base = bases(spot)
    spec = [
        ("BUY", base_lots, "CE", call_base + buy_offset, "inner"),
        ("SELL", short_ratio * base_lots, "CE", call_base + buy_offset + sell_gap, "short"),
        ("BUY", outer_ratio * base_lots + extra_call_lots, "CE", call_base + buy_offset + sell_gap + hedge_gap, "outer"),
        ("BUY", base_lots, "PE", put_base - buy_offset, "inner"),
        ("SELL", short_ratio * base_lots, "PE", put_base - buy_offset - sell_gap, "short"),
        ("BUY", outer_ratio * base_lots, "PE", put_base - buy_offset - sell_gap - hedge_gap, "outer"),
    ]
    legs = []
    for action, lots, option_type, strike, role in spec:
        quote = _quote(chain, strike, option_type)
        if not quote:
            return None
        legs.append({
            "action": action,
            "qty": lots,
            "optionType": option_type,
            "strike": strike,
            "role": role,
            "price": round(_fill(quote, action), 2),
            "ltp": quote.get("ltp"),
            "bid": quote.get("bid"),
            "ask": quote.get("ask"),
            "iv": quote.get("iv"),
            "delta": quote.get("delta"),
            "securityId": quote.get("securityId"),
        })
    return legs


def net_credit(legs: list[dict[str, Any]], lot_size: int) -> float:
    """Rupees received (positive) for the whole position at entry fills."""
    return sum((1 if l["action"] == "SELL" else -1) * l["qty"] * l["price"] for l in legs) * lot_size


def t0_pnl(legs: list[dict[str, Any]], price: float, years: float, forward_ratio: float, lot_size: int) -> float:
    return ve.today_pnl_points(legs, price, years, forward_ratio) * lot_size


def construct(
    chain: list[dict[str, Any]], spot: float, *, years: float, lot_size: int, capital: float, base_lots: int,
    buy_offset: float, sell_gap: float, hedge_gap: float, credit_cap_percent: float, shift_step: float,
    max_shifts: int, balance_move: float, over_hedge: bool, max_extra_call_lots: int,
    short_ratio: int = 3, outer_ratio: int = 2, fixed_extra_call_lots: int | None = None,
) -> dict[str, Any]:
    """Applies Filter 1 (credit cap) then Filter 2 (call over-hedge). With
    fixed_extra_call_lots set, Filter 2 just reports the balance for every
    trial and uses that fixed number instead of the best one."""
    ratio = {"short_ratio": short_ratio, "outer_ratio": outer_ratio}
    expiry_block = {"chain": chain, "years": years}
    forward_ratio = ve.forward_ratio(expiry_block, spot)
    offset = buy_offset
    shifts = 0
    legs = None
    credit = 0.0
    while True:
        legs = build_legs(chain, spot, buy_offset=offset, sell_gap=sell_gap, hedge_gap=hedge_gap, base_lots=base_lots, **ratio)
        if not legs:
            return {"error": f"Option chain has no quote for a leg at buy offset {offset:.0f}."}
        credit = net_credit(legs, lot_size)
        if credit / capital * 100 <= credit_cap_percent or shifts >= max_shifts:
            break
        offset += shift_step
        shifts += 1
    credit_ok = credit / capital * 100 <= credit_cap_percent

    extra = 0
    balance_rows = []
    if over_hedge:
        best = None
        for k in range(0, max_extra_call_lots + 1):
            trial = build_legs(chain, spot, buy_offset=offset, sell_gap=sell_gap, hedge_gap=hedge_gap,
                               base_lots=base_lots, extra_call_lots=k, **ratio)
            if not trial:
                break
            down = t0_pnl(trial, spot - balance_move, years, forward_ratio, lot_size)
            up = t0_pnl(trial, spot + balance_move, years, forward_ratio, lot_size)
            balance_rows.append({"extraCallLots": k, "t0Down": round(down), "t0Up": round(up)})
            gap = abs(up - down)
            if best is None or gap < best[0]:
                best = (gap, k, trial)
        if best:
            extra, legs = best[1], best[2]
    if fixed_extra_call_lots is not None:
        fixed = build_legs(chain, spot, buy_offset=offset, sell_gap=sell_gap, hedge_gap=hedge_gap,
                           base_lots=base_lots, extra_call_lots=fixed_extra_call_lots, **ratio)
        if fixed:
            extra, legs = fixed_extra_call_lots, fixed
    credit = net_credit(legs, lot_size)

    # Max profit/loss at expiry within +-15% of spot: with extra outer calls
    # the upside keeps growing forever, so an unbounded figure is meaningless.
    low, high = spot * 0.85, spot * 1.15
    kinks = sorted({l["strike"] for l in legs if low < l["strike"] < high})
    values = [ve.expiry_pnl_points(legs, x) * lot_size for x in [low, high, *kinks]]
    breakevens = ve._breakevens(legs, low, high)
    zones = ve._payoff_zones(legs, breakevens, low, high)
    t0_down = t0_pnl(legs, spot - balance_move, years, forward_ratio, lot_size)
    t0_up = t0_pnl(legs, spot + balance_move, years, forward_ratio, lot_size)
    for leg in legs:
        leg["distance"] = round(leg["strike"] - spot, 1)
        leg["distancePercent"] = round((leg["strike"] - spot) / spot * 100, 2)
    return {
        "spot": spot,
        "forwardRatio": forward_ratio,
        "legs": legs,
        "buyOffset": offset,
        "sellGap": sell_gap,
        "hedgeGap": hedge_gap,
        "creditShifts": shifts,
        "credit": round(credit, 2),
        "creditPercent": round(credit / capital * 100, 2),
        "creditOk": credit_ok,
        "extraCallLots": extra,
        "balanceMove": balance_move,
        "balanceTable": balance_rows,
        "t0Down": round(t0_down),
        "t0Up": round(t0_up),
        "t0DownPercent": round(t0_down / capital * 100, 2),
        "t0UpPercent": round(t0_up / capital * 100, 2),
        "expiryMaxProfit": round(max(values)),
        "expiryMaxLoss": round(min(values)),
        "breakevens": breakevens,
        "zones": zones,
        "years": years,
    }


def payoff_points(legs: list[dict[str, Any]], spot: float, years: float, forward_ratio: float, lot_size: int, span_percent: float = 8.0) -> list[dict[str, float]]:
    low, high = spot * (1 - span_percent / 100), spot * (1 + span_percent / 100)
    count = 181
    step = (high - low) / (count - 1)
    points = []
    for i in range(count):
        price = low + i * step
        points.append({
            "price": round(price, 1),
            "expiry": round(ve.expiry_pnl_points(legs, price) * lot_size, 0),
            "today": round(ve.today_pnl_points(legs, price, years, forward_ratio) * lot_size, 0),
        })
    return points


def weekly_distances(expected_move: float, buy_em: float, sell_em: float, hedge_em: float) -> tuple[float, float, float]:
    return (
        _round_to_step(expected_move * buy_em),
        _round_to_step(expected_move * sell_em),
        _round_to_step(expected_move * hedge_em),
    )
