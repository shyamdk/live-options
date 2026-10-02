from __future__ import annotations

from typing import Any


def build_recommendation(
    *,
    holding: dict[str, Any],
    fundamentals: dict[str, Any] | None,
    technicals: dict[str, Any] | None,
    news: dict[str, Any] | None,
) -> dict[str, Any]:
    fundamentals = fundamentals or {}
    technicals = technicals or {}
    news = news or {}
    score = 50
    reasons: list[str] = []
    risks: list[str] = []

    pe = _number(fundamentals.get("pe"))
    median_pe = _number(fundamentals.get("medianPe"))
    industry_pe = _number(fundamentals.get("industryPe"))
    roce = _number(fundamentals.get("roce"))
    roe = _number(fundamentals.get("roe"))
    debt = _number(fundamentals.get("debtToEquity"))
    pledge = _number(fundamentals.get("pledge"))
    sales_growth = _number(fundamentals.get("salesGrowth3y"))
    profit_growth = _number(fundamentals.get("profitGrowth3y"))
    sma20 = _number(technicals.get("sma20"))
    sma50 = _number(technicals.get("sma50"))
    sma200 = _number(technicals.get("sma200"))
    close = _number(technicals.get("close"))
    sentiment = str(news.get("sentiment") or "neutral").lower()
    long_term_gates = _long_term_gates(
        pe=pe,
        median_pe=median_pe,
        industry_pe=industry_pe,
        roce=roce,
        roe=roe,
        debt=debt,
        pledge=pledge,
        sales_growth=sales_growth,
        profit_growth=profit_growth,
        sentiment=sentiment,
    )
    long_term_ready = all(gate["passed"] for gate in long_term_gates)
    timing_ready = _timing_ready(sma20, sma50, sma200, close)

    if pe is not None and median_pe:
        if pe <= median_pe * 0.85:
            score += 12
            reasons.append(f"PE {pe:.2f} is meaningfully below 3Yrs PE {median_pe:.2f}.")
        elif pe <= median_pe:
            score += 8
            reasons.append(f"PE {pe:.2f} is below 3Yrs PE {median_pe:.2f}.")
        elif pe >= median_pe * 1.35:
            score -= 12
            risks.append(f"PE {pe:.2f} is stretched versus 3Yrs PE {median_pe:.2f}.")
    if pe is not None and industry_pe:
        if pe <= industry_pe:
            score += 4
            reasons.append(f"PE is below industry PE {industry_pe:.2f}.")
        elif pe > industry_pe * 1.25:
            score -= 5
            risks.append(f"PE is above industry PE {industry_pe:.2f}.")

    if roce is not None:
        if roce >= 20:
            score += 10
            reasons.append(f"ROCE {roce:.1f}% shows strong capital efficiency.")
        elif roce >= 15:
            score += 6
            reasons.append(f"ROCE {roce:.1f}% is acceptable.")
        elif roce < 10:
            score -= 8
            risks.append(f"ROCE {roce:.1f}% is weak.")
    if roe is not None:
        if roe >= 15:
            score += 6
            reasons.append(f"ROE {roe:.1f}% is healthy.")
        elif roe < 8:
            score -= 5
            risks.append(f"ROE {roe:.1f}% is weak.")
    if debt is not None:
        if debt <= 0.5:
            score += 8
            reasons.append(f"Debt/equity {debt:.2f} is conservative.")
        elif debt > 1:
            score -= 12
            risks.append(f"Debt/equity {debt:.2f} is elevated.")
    if pledge is not None and pledge > 5:
        score -= 10
        risks.append(f"Promoter pledge {pledge:.1f}% needs review.")
    if profit_growth is not None:
        if profit_growth >= 12:
            score += 6
            reasons.append(f"3Y profit growth {profit_growth:.1f}% supports valuation.")
        elif profit_growth < 0:
            score -= 8
            risks.append(f"3Y profit growth {profit_growth:.1f}% is negative.")
    if sales_growth is not None:
        if sales_growth >= 10:
            score += 4
            reasons.append(f"3Y sales growth {sales_growth:.1f}% is constructive.")
        elif sales_growth < 0:
            score -= 5
            risks.append(f"3Y sales growth {sales_growth:.1f}% is negative.")
    if sales_growth is None and profit_growth is None:
        risks.append("3Y sales/profit growth data is unavailable; verify durability manually.")

    if sma20 is not None and sma50 is not None:
        if sma20 > sma50:
            score += 8
            reasons.append(f"SMA20 {sma20:.2f} is above SMA50 {sma50:.2f}.")
        else:
            score -= 8
            risks.append(f"SMA20 {sma20:.2f} is below SMA50 {sma50:.2f}.")
    if close is not None and sma200 is not None:
        if close > sma200:
            score += 6
            reasons.append(f"Price is above SMA200 {sma200:.2f}.")
        else:
            score -= 8
            risks.append(f"Price is below SMA200 {sma200:.2f}.")
    if sentiment == "positive":
        score += 5
        reasons.append("Recent news sentiment is positive.")
    elif sentiment == "negative":
        score -= 12
        risks.append("Recent news sentiment is negative.")
    elif sentiment == "mixed":
        score -= 4
        risks.append("Recent news sentiment is mixed.")

    if long_term_ready:
        reasons.insert(0, "Long-term gates passed: quality, leverage, growth durability, valuation and business-risk checks.")
    else:
        failed = ", ".join(gate["label"] for gate in long_term_gates if not gate["passed"])
        risks.insert(0, f"Long-term gate not fully passed: {failed}.")

    score = max(0, min(100, score))
    if score >= 75 and long_term_ready and timing_ready:
        action = "Potential Buy"
        grade = "A"
    elif score >= 62 and long_term_ready:
        action = "Accumulate / Hold"
        grade = "B"
    elif score >= 45:
        action = "Hold / Watch"
        grade = "C"
    elif score >= 30:
        action = "Review"
        grade = "D"
    else:
        action = "Avoid / Reduce"
        grade = "E"

    if long_term_ready and timing_ready and _potential_buy(pe, median_pe, sma20, sma50):
        if "Potential Buy" not in action:
            action = "Potential Buy Setup"
        reasons.insert(0, "Core setup passed: PE below 3Yrs PE and SMA20 above SMA50.")

    return {
        "symbol": holding.get("symbol") or holding.get("tradingSymbol"),
        "score": round(score, 1),
        "grade": grade,
        "action": action,
        "reasons": reasons[:8],
        "risks": risks[:8],
        "longTermGates": long_term_gates,
        "guruSignals": _guru_signals(
            pe=pe,
            median_pe=median_pe,
            roce=roce,
            roe=roe,
            debt=debt,
            pledge=pledge,
            profit_growth=profit_growth,
            sma20=sma20,
            sma50=sma50,
            sma200=sma200,
            close=close,
            sentiment=sentiment,
        ),
    }


def _guru_signals(**values: float | str | None) -> list[dict[str, str]]:
    pe = _number(values.get("pe"))
    median_pe = _number(values.get("median_pe"))
    roce = _number(values.get("roce"))
    roe = _number(values.get("roe"))
    debt = _number(values.get("debt"))
    pledge = _number(values.get("pledge"))
    profit_growth = _number(values.get("profit_growth"))
    sma20 = _number(values.get("sma20"))
    sma50 = _number(values.get("sma50"))
    sma200 = _number(values.get("sma200"))
    close = _number(values.get("close"))
    sentiment = str(values.get("sentiment") or "neutral")
    peg = pe / profit_growth if pe is not None and profit_growth and profit_growth > 0 else None

    return [
        _signal("Buffett/Munger", bool((roce and roce >= 15) and (debt is None or debt <= 0.5)), "Quality compounder: high capital efficiency without heavy leverage."),
        _signal("Graham", bool(pe is not None and median_pe and pe <= median_pe), "Valuation is below 3Yrs PE."),
        _signal("Peter Lynch", bool(peg is not None and peg <= 1.5), "PE is reasonable relative to profit growth."),
        _signal("O'Neil/Minervini", bool(sma20 and sma50 and close and sma200 and sma20 > sma50 and close > sma200), "Trend confirmation from moving averages."),
        _signal("Howard Marks", bool((debt is None or debt <= 1) and (pledge is None or pledge <= 5) and sentiment != "negative"), "Risk flags are contained."),
        _signal("Owner Check", bool(roe is not None and roe >= 12), "Shareholder returns appear acceptable."),
    ]


def _signal(name: str, passed: bool, detail: str) -> dict[str, str]:
    return {"name": name, "status": "pass" if passed else "watch", "detail": detail}


def _potential_buy(pe: float | None, median_pe: float | None, sma20: float | None, sma50: float | None) -> bool:
    return bool(pe is not None and median_pe and pe < median_pe and sma20 is not None and sma50 is not None and sma20 > sma50)


def _long_term_gates(
    *,
    pe: float | None,
    median_pe: float | None,
    industry_pe: float | None,
    roce: float | None,
    roe: float | None,
    debt: float | None,
    pledge: float | None,
    sales_growth: float | None,
    profit_growth: float | None,
    sentiment: str,
) -> list[dict[str, Any]]:
    quality = bool((roce is not None and roce >= 15) and (roe is None or roe >= 10))
    leverage = bool((debt is not None and debt <= 1) and (pledge is None or pledge <= 5))
    growth_values = [value for value in (profit_growth, sales_growth) if value is not None]
    growth = bool(not growth_values or all(value >= 0 for value in growth_values))
    valuation = _valuation_reasonable(pe, median_pe, industry_pe)
    business_risk = bool(sentiment != "negative" and (pledge is None or pledge <= 5))
    return [
        {
            "key": "quality",
            "label": "Quality",
            "passed": quality,
            "detail": _quality_detail(roce, roe),
        },
        {
            "key": "leverage",
            "label": "Leverage",
            "passed": leverage,
            "detail": _leverage_detail(debt, pledge),
        },
        {
            "key": "growthDurability",
            "label": "Growth durability",
            "passed": growth,
            "detail": _growth_detail(sales_growth, profit_growth),
        },
        {
            "key": "valuation",
            "label": "Valuation",
            "passed": valuation,
            "detail": _valuation_detail(pe, median_pe, industry_pe),
        },
        {
            "key": "businessRisk",
            "label": "Business risk",
            "passed": business_risk,
            "detail": _business_risk_detail(sentiment, pledge),
        },
    ]


def _timing_ready(sma20: float | None, sma50: float | None, sma200: float | None, close: float | None) -> bool:
    return bool(sma20 is not None and sma50 is not None and sma20 > sma50 and (close is None or sma200 is None or close > sma200))


def _valuation_reasonable(pe: float | None, median_pe: float | None, industry_pe: float | None) -> bool:
    if pe is None:
        return False
    checks = []
    if median_pe:
        checks.append(pe <= median_pe * 1.1)
    if industry_pe:
        checks.append(pe <= industry_pe * 1.15)
    return bool(checks and any(checks))


def _quality_detail(roce: float | None, roe: float | None) -> str:
    return f"ROCE {_fmt(roce)} needs >= 15%; ROE {_fmt(roe)} should be >= 10% when available."


def _leverage_detail(debt: float | None, pledge: float | None) -> str:
    return f"Debt/equity {_fmt(debt)} needs <= 1; pledge {_fmt(pledge)}% needs <= 5% when available."


def _growth_detail(sales_growth: float | None, profit_growth: float | None) -> str:
    if sales_growth is None and profit_growth is None:
        return "3Y sales/profit growth is unavailable; verify durability manually."
    return f"3Y profit growth {_fmt(profit_growth)}% and 3Y sales growth {_fmt(sales_growth)}% should be non-negative when available."


def _valuation_detail(pe: float | None, median_pe: float | None, industry_pe: float | None) -> str:
    return f"PE {_fmt(pe)} should be reasonable against available references: <= 110% of 3Yrs PE {_fmt(median_pe)} or <= 115% of industry PE {_fmt(industry_pe)}."


def _business_risk_detail(sentiment: str, pledge: float | None) -> str:
    return f"News sentiment is {sentiment}; pledge {_fmt(pledge)}% should not indicate promoter stress."


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _number(value: Any) -> float | None:
    if value in (None, "", "NA", "NaN"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
