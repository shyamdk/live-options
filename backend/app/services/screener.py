from __future__ import annotations

import asyncio
import html
import json
import re
from asyncio import Lock, sleep
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.core.config import Settings, get_settings


_REQUEST_LOCK = Lock()
_LAST_REQUEST_AT = 0.0
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}


class ScreenerService:
    def __init__(self, settings: Settings | None = None, url_overrides: dict[str, str] | None = None) -> None:
        self.settings = settings or get_settings()
        self.configured_url = self.settings.screener_url or "https://www.screener.in"
        self.base_url = self._base_url(self.configured_url)
        self.url_overrides = {_normalize_symbol(key): value for key, value in (url_overrides or {}).items() if value}

    async def fundamentals(self, symbol: str) -> dict[str, Any]:
        normalized_symbol = _normalize_symbol(symbol)
        if not normalized_symbol:
            return _empty_fundamentals(symbol, "Missing symbol.")
        results = await self.fundamentals_many([normalized_symbol])
        return results.get(normalized_symbol) or _empty_fundamentals(normalized_symbol, "Missing Screener result.")

    async def fundamentals_many(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        normalized_symbols = [_normalize_symbol(symbol) for symbol in symbols]
        normalized_symbols = [symbol for symbol in normalized_symbols if symbol]
        results: dict[str, dict[str, Any]] = {}
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=_BROWSER_HEADERS) as client:
                if self.settings.login_email and self.settings.login_password:
                    await self._login(client)
                for symbol in normalized_symbols:
                    try:
                        results[symbol] = await self._fundamentals_with_client(client, symbol)
                    except Exception as exc:
                        results[symbol] = _empty_fundamentals(symbol, str(exc))
        except Exception as exc:
            for symbol in normalized_symbols:
                results[symbol] = _empty_fundamentals(symbol, str(exc))
        return results

    def company_url(self, symbol: str) -> str:
        return urljoin(self.base_url + "/", f"company/{_normalize_symbol(symbol)}/")

    async def _fundamentals_with_client(self, client: httpx.AsyncClient, symbol: str) -> dict[str, Any]:
        html_text, url = await self._company_html(client, symbol)
        if self._needs_login(html_text):
            await self._login(client)
            html_text, url = await self._company_html(client, symbol)
        quick_ratios = await self._quick_ratios_html(client, html_text, referer=url)
        if quick_ratios:
            html_text = f"{html_text}\n{quick_ratios}"

        text = _html_text(html_text)
        metrics = {
            "pe": _extract_metric(html_text, text, ("Stock P/E", "P/E", "PE")),
            "medianPe": _extract_metric(
                html_text,
                text,
                (
                    "Median PE",
                    "Median P/E",
                    "10 Year Median PE",
                    "5 Year Median PE",
                    "3Yrs PE",
                    "3 Yrs PE",
                    "3Yr PE",
                    "3 Year PE",
                    "3 Years PE",
                ),
            ),
            "industryPe": _extract_metric(html_text, text, ("Industry PE", "Industry P/E")),
            "roce": _extract_metric(html_text, text, ("ROCE", "Return on capital employed")),
            "roe": _extract_metric(html_text, text, ("ROE", "Return on equity")),
            "debtToEquity": _extract_metric(html_text, text, ("Debt to equity", "Debt / equity", "Debt/Equity")),
            "salesGrowth3y": _extract_metric(
                html_text,
                text,
                ("Sales growth 3Years", "Sales growth 3 years", "3 Year Sales Growth"),
            ),
            "profitGrowth3y": _extract_metric(
                html_text,
                text,
                ("Profit growth 3Years", "Profit growth 3 years", "3 Year Profit Growth"),
            ),
            "promoterHolding": _extract_metric(html_text, text, ("Promoter holding", "Promoters holding")),
            "pledge": _extract_metric(
                html_text,
                text,
                ("Pledged percentage", "Promoter pledge", "Pledged promoter holding"),
            ),
            "marketCap": _extract_metric(html_text, text, ("Market Cap", "Mkt Cap")),
            "dividendYield": _extract_metric(html_text, text, ("Dividend Yield",)),
        }
        return {
            "symbol": symbol,
            "source": "screener",
            "parserVersion": 2,
            "url": url,
            "warning": None if any(value is not None for value in metrics.values()) else "Screener page loaded, but no known ratios were parsed.",
            **metrics,
        }

    async def _login(self, client: httpx.AsyncClient) -> None:
        if not self.settings.login_email or not self.settings.login_password:
            return
        login_url = urljoin(self.base_url + "/", "login/")
        response = await client.get(login_url)
        csrf = _csrf_token(response.text)
        payload = {
            "username": self.settings.login_email,
            "email": self.settings.login_email,
            "password": self.settings.login_password,
        }
        if csrf:
            payload["csrfmiddlewaretoken"] = csrf
        headers = {"Referer": login_url}
        response = await client.post(login_url, data=payload, headers=headers)
        redirect = response.headers.get("X-Redirect-To")
        final_url = str(response.url)
        if redirect and "/login" in redirect:
            raise RuntimeError("Screener login did not create a registered session.")
        if final_url.rstrip("/").endswith("/login"):
            raise RuntimeError("Screener login returned the login page.")

    async def _company_html(self, client: httpx.AsyncClient, symbol: str) -> tuple[str, str]:
        urls = self._candidate_urls(symbol)
        last_error: Exception | None = None
        for url in urls:
            try:
                await _screener_rate_limit()
                response = await client.get(url)
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                return response.text, str(response.url)
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"Could not load Screener page for {symbol}: {last_error}")

    async def _quick_ratios_html(self, client: httpx.AsyncClient, html_text: str, *, referer: str | None = None) -> str | None:
        warehouse_id = _warehouse_id(html_text)
        if not warehouse_id:
            return None
        url = urljoin(self.base_url + "/", f"api/company/{warehouse_id}/quick_ratios/")
        for attempt in range(3):
            await _screener_rate_limit()
            headers = {"X-Requested-With": "XMLHttpRequest"}
            if referer:
                headers["Referer"] = referer
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                if _needs_login_or_register(response.text):
                    return None
                return response.text
            if response.status_code != 429:
                return None
            await asyncio.sleep(2 * (attempt + 1))
        return None

    def _candidate_urls(self, symbol: str) -> list[str]:
        configured = self.configured_url or ""
        if symbol in self.url_overrides:
            return [self.url_overrides[symbol]]
        mapped_url = _mapped_screener_url(self.settings.screener_urls, symbol)
        if mapped_url:
            return [mapped_url]
        if "{symbol}" in configured:
            return [configured.format(symbol=symbol)]
        if "/company/" in configured and configured.rstrip("/").upper().endswith(symbol):
            return [configured]
        return [
            urljoin(self.base_url + "/", f"company/{symbol}/consolidated/"),
            urljoin(self.base_url + "/", f"company/{symbol}/"),
        ]

    def _base_url(self, configured: str) -> str:
        parsed = urlparse(configured)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        return "https://www.screener.in"

    def _needs_login(self, html_text: str) -> bool:
        lowered = html_text.lower()
        return "csrfmiddlewaretoken" in lowered and "password" in lowered and "login" in lowered


def _empty_fundamentals(symbol: str, warning: str) -> dict[str, Any]:
    return {
        "symbol": _normalize_symbol(symbol),
        "source": "screener",
        "parserVersion": 2,
        "url": None,
        "warning": warning,
        "pe": None,
        "medianPe": None,
        "industryPe": None,
        "roce": None,
        "roe": None,
        "debtToEquity": None,
        "salesGrowth3y": None,
        "profitGrowth3y": None,
        "promoterHolding": None,
        "pledge": None,
        "marketCap": None,
        "dividendYield": None,
    }


async def _screener_rate_limit() -> None:
    import time

    global _LAST_REQUEST_AT
    async with _REQUEST_LOCK:
        elapsed = time.monotonic() - _LAST_REQUEST_AT
        if elapsed < 2:
            await sleep(2 - elapsed)
        _LAST_REQUEST_AT = time.monotonic()


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").upper().replace("-EQ", "").replace(" ", "").strip()


def _csrf_token(value: str) -> str | None:
    soup = BeautifulSoup(value, "html.parser")
    field = soup.find("input", attrs={"name": "csrfmiddlewaretoken"})
    if field and field.get("value"):
        return html.unescape(str(field.get("value")))
    match = re.search(r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)["\']', value)
    return html.unescape(match.group(1)) if match else None


def _warehouse_id(value: str) -> str | None:
    soup = BeautifulSoup(value, "html.parser")
    company_info = soup.find(id="company-info") or soup.find(attrs={"data-warehouse-id": True})
    if not company_info:
        return None
    warehouse_id = company_info.get("data-warehouse-id")
    return html.unescape(str(warehouse_id)) if warehouse_id else None


def _html_text(value: str) -> str:
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<[^>]+>", "\n", value)
    value = html.unescape(value)
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r"\n+", "\n", value)
    return value


def _needs_login_or_register(value: str) -> bool:
    lowered = _html_text(value).lower()
    return ("login" in lowered and "register" in lowered and "quick" not in lowered) or "register using google" in lowered


def _extract_metric(html_text: str, text: str, labels: tuple[str, ...]) -> float | None:
    value = _extract_metric_from_ratio_items(html_text, labels)
    if value is not None:
        return value
    for label in labels:
        escaped = re.escape(label)
        patterns = (
            rf"{escaped}\s*[:\-]?\s*(?:Rs\.?|₹)?\s*(-?\d[\d,]*(?:\.\d+)?)\s*%?",
            rf"{escaped}\s*\n\s*(?:Rs\.?|₹)?\s*(-?\d[\d,]*(?:\.\d+)?)\s*%?",
            rf"{escaped}\s+(-?\d[\d,]*(?:\.\d+)?)\s*%?",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return _number(match.group(1))
    return None


def _extract_metric_from_ratio_items(html_text: str, labels: tuple[str, ...]) -> float | None:
    soup = BeautifulSoup(html_text, "html.parser")
    normalized_labels = {_normalize_label(label) for label in labels}
    for item in soup.find_all("li"):
        name_el = item.find(class_="name")
        value_el = item.find(class_="value")
        if not name_el:
            continue
        name = _normalize_label(name_el.get_text(" ", strip=True))
        if name not in normalized_labels:
            continue
        value_text = value_el.get_text(" ", strip=True) if value_el else item.get_text(" ", strip=True)
        numbers = re.findall(r"-?\d[\d,]*(?:\.\d+)?", value_text)
        if numbers:
            return _number(numbers[0])
    return None


def _mapped_screener_url(raw_urls: str | None, symbol: str) -> str | None:
    if not raw_urls:
        return None
    normalized_symbol = _normalize_symbol(symbol)
    try:
        parsed = json.loads(raw_urls)
        if isinstance(parsed, dict):
            return _url_for_symbol(parsed, normalized_symbol)
    except json.JSONDecodeError:
        pass
    pairs = {}
    for item in re.split(r"[,;\n]+", raw_urls):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        pairs[key.strip()] = value.strip()
    return _url_for_symbol(pairs, normalized_symbol)


def _url_for_symbol(urls: dict[Any, Any], symbol: str) -> str | None:
    for key, value in urls.items():
        if _normalize_symbol(str(key)) == symbol and value:
            return str(value)
    return None


def _normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _number(value: Any) -> float | None:
    if value in (None, "", "NA", "NaN"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
