"""Which features may call OpenAI (credit control, 12 Nov 2026).

Credits were running out, so OpenAI is used only where it supports live
trading: the NIFTY Strangle event list (market_events). Every other AI
feature skips its call and shows PAUSED_MESSAGE instead. Re-enable a feature
by adding its name to OPENAI_ENABLED_FEATURES (comma-separated) in .env:
  market_events, market_news, market_calendar, journal_insights,
  gamma_retrospective, varaha_ranking, equity_news, assistant, notes_digest
"""

from __future__ import annotations

from app.core.config import get_settings

PAUSED_MESSAGE = "AI usage stopped because of OpenAI credit overuse -- this feature is paused (only NIFTY Strangle events use AI now)."


def ai_allowed(feature: str) -> bool:
    enabled = {f.strip() for f in (get_settings().openai_enabled_features or "").split(",") if f.strip()}
    return feature in enabled
