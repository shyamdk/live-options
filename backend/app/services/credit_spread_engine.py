"""Pure strategy logic for the Bank Nifty monthly call credit spread.

Rules reverse-engineered and Dhan-verified from a 31-month track record
(see bank-nifty/strategy.md):
  - SELL the monthly call at the 100-strike nearest the synthetic future
    (F = K_atm + C_atm - P_atm), not spot: the futures basis is where the
    index converges at expiry, so that is the true max-theta strike.
  - BUY the same-expiry call priced closest to Rs 100 as the hedge
    (premium-selected, not width-selected).
  - Enter on the first trading day of the new monthly series at 09:45.
  - Exit both legs at 09:20 when exactly N (default 10) trading days remain
    before expiry — the position only ever lives in the low-gamma first half
    of the cycle. Optional profit-target / hard-stop overlays on top.

No I/O here: everything takes plain dicts/numbers so it is unit-testable.
"""

from __future__ import annotations

from typing import Any

STRIKE_STEP = 100.0


def parse_chain(chain: dict[str, Any]) -> tuple[float | None, dict[float, dict[str, Any]]]:
    """Normalize a Dhan option-chain payload to (spot, {strike: {ce, pe}})."""
    spot = _number(chain.get("last_price"))
    strikes: dict[float, dict[str, Any]] = {}
    oc = chain.get("oc") or {}
    for strike_key, sides in oc.items():
        try:
            strike = float(strike_key)
        except (TypeError, ValueError):
            continue
        if not isinstance(sides, dict):
            continue
        strikes[strike] = sides
    return spot, strikes


def leg(strikes: dict[float, dict[str, Any]], strike: float, side: str) -> dict[str, Any] | None:
    payload = (strikes.get(strike) or {}).get(side)
    if not isinstance(payload, dict) or not payload.get("security_id"):
        return None
    price = _number(payload.get("last_price"))
    if price is None or price <= 0:
        return None
    return {"strike": strike, "side": side.upper(), "securityId": str(payload["security_id"]), "price": price}


def synthetic_future(spot: float, strikes: dict[float, dict[str, Any]]) -> dict[str, Any] | None:
    """F = K + C(K) - P(K), evaluated at the strike nearest spot, then
    re-evaluated once at the strike nearest F for better accuracy."""
    reference = spot
    result: dict[str, Any] | None = None
    for _ in range(2):
        atm_strike = _nearest_strike_with_both_sides(strikes, reference)
        if atm_strike is None:
            return result
        ce = leg(strikes, atm_strike, "ce")
        pe = leg(strikes, atm_strike, "pe")
        if not ce or not pe:
            return result
        future = atm_strike + ce["price"] - pe["price"]
        result = {"future": round(future, 2), "atmStrike": atm_strike, "atmCall": ce["price"], "atmPut": pe["price"]}
        reference = future
    return result


def select_spread(
    spot: float,
    strikes: dict[float, dict[str, Any]],
    *,
    hedge_premium_target: float,
) -> dict[str, Any] | None:
    """Pick both legs. Returns None only when the chain is unusable."""
    synth = synthetic_future(spot, strikes)
    if not synth:
        return None
    sell_strike = _nearest_strike_with_both_sides(strikes, synth["future"])
    if sell_strike is None:
        return None
    sell = leg(strikes, sell_strike, "ce")
    if not sell:
        return None

    hedge = None
    best_distance = None
    for strike in sorted(strikes):
        if strike <= sell_strike:
            continue
        candidate = leg(strikes, strike, "ce")
        if not candidate:
            continue
        distance = abs(candidate["price"] - hedge_premium_target)
        if best_distance is None or distance < best_distance:
            best_distance = distance
            hedge = candidate

    net_credit = round(sell["price"] - (hedge["price"] if hedge else 0.0), 2)
    width = (hedge["strike"] - sell_strike) if hedge else None
    return {
        "spot": spot,
        "syntheticFuture": synth["future"],
        "atmStrike": synth["atmStrike"],
        "sell": sell,
        "hedge": hedge,
        "netCredit": net_credit,
        "width": width,
        "creditPercentOfWidth": round(100 * net_credit / width, 1) if width else None,
    }


def entry_blockers(
    selection: dict[str, Any],
    *,
    min_net_credit: float,
    min_credit_width_percent: float,
    max_entry_vix: float,
    vix: float | None,
) -> list[str]:
    """Empty list means the entry is allowed."""
    blockers: list[str] = []
    if not selection.get("hedge"):
        blockers.append("No hedge leg found near the premium target — refusing to sell naked.")
    if selection["netCredit"] < min_net_credit:
        blockers.append(
            f"Net credit {selection['netCredit']:.2f} below floor {min_net_credit:.0f} — trade is not paying for its risk."
        )
    credit_pct = selection.get("creditPercentOfWidth")
    if credit_pct is not None and credit_pct < min_credit_width_percent:
        blockers.append(
            f"Credit is {credit_pct:.1f}% of width, below the {min_credit_width_percent:.0f}% floor."
        )
    if vix is not None and max_entry_vix > 0 and vix > max_entry_vix:
        blockers.append(f"India VIX {vix:.2f} above the {max_entry_vix:.0f} entry ceiling.")
    return blockers


def mark_to_market(
    position: dict[str, Any],
    sell_ltp: float | None,
    hedge_ltp: float | None,
) -> dict[str, Any] | None:
    if sell_ltp is None:
        return None
    qty = int(position["qty"] or 0)
    sell_pnl = (position["sellEntryPrice"] - sell_ltp) * qty
    hedge_pnl = 0.0
    if position.get("hedgeEntryPrice") is not None and hedge_ltp is not None:
        hedge_pnl = (hedge_ltp - position["hedgeEntryPrice"]) * qty
    total = round(sell_pnl + hedge_pnl, 2)
    credit_value = (position["netCredit"] or 0) * qty
    return {
        "sellLtp": sell_ltp,
        "hedgeLtp": hedge_ltp,
        "unrealizedPnl": total,
        "capturePercent": round(100 * total / credit_value, 1) if credit_value else None,
    }


def evaluate_exit(
    *,
    remaining_trading_days_after_today: int,
    exit_days_threshold: int,
    now_hhmm: str,
    exit_time: str,
    mtm: dict[str, Any] | None,
    profit_target_percent: float,
    hard_stop_credit_multiple: float,
) -> dict[str, Any] | None:
    """Priority: hard stop > time exit > profit target."""
    capture = (mtm or {}).get("capturePercent")

    if hard_stop_credit_multiple > 0 and capture is not None and capture <= -100.0 * hard_stop_credit_multiple:
        return {"reason": "HARD_STOP", "detail": f"Loss reached {capture:.1f}% of credit."}

    if remaining_trading_days_after_today <= exit_days_threshold and now_hhmm >= exit_time:
        return {
            "reason": "TIME_EXIT",
            "detail": f"{remaining_trading_days_after_today} trading days remain (threshold {exit_days_threshold}).",
        }

    if profit_target_percent > 0 and capture is not None and capture >= profit_target_percent:
        return {"reason": "PROFIT_TARGET", "detail": f"Captured {capture:.1f}% of credit."}

    return None


def _nearest_strike_with_both_sides(strikes: dict[float, dict[str, Any]], reference: float) -> float | None:
    best = None
    best_distance = None
    for strike in strikes:
        if strike % STRIKE_STEP != 0:
            continue
        if not leg(strikes, strike, "ce") or not leg(strikes, strike, "pe"):
            continue
        distance = abs(strike - reference)
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best = strike
    return best


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
