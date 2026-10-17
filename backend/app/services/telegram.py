from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# The chat id comes from TELEGRAM_CHAT_ID, or is discovered from the bot's
# recent updates (someone messaged the bot) and then remembered in the DB.
# Telegram only keeps updates for ~24 h, so without remembering it every
# alert was silently dropped once that window passed (found 17 Oct 2026).
CHAT_ID_SETTING = "telegram.chatId"
_last: dict[str, Any] = {"ok": None, "at": None, "error": None}


def _stored_chat_id() -> str | None:
    try:
        from app.db.sqlite import get_manage_setting

        return get_manage_setting(CHAT_ID_SETTING)
    except Exception:
        return None


def _remember_chat_id(chat_id: str) -> None:
    try:
        from app.db.sqlite import set_manage_setting

        set_manage_setting(CHAT_ID_SETTING, chat_id)
    except Exception:
        logger.exception("telegram: could not store the chat id")


class TelegramNotifier:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def send(self, text: str) -> bool:
        token = self.settings.telegram_bot_token
        if not token:
            self._record(False, "TELEGRAM_BOT_TOKEN is not set")
            return False
        chat_id = self.settings.telegram_chat_id or _stored_chat_id()
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                if not chat_id:
                    chat_id = await self._discover_chat_id(client, token)
                    if chat_id:
                        _remember_chat_id(chat_id)
                if not chat_id:
                    self._record(False, "No chat id: send /start to the bot in Telegram once, then send a test message")
                    return False
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                )
                response.raise_for_status()
                self._record(True, None)
                return True
        except Exception as exc:
            self._record(False, f"{type(exc).__name__}: {str(exc)[:160]}")
            return False

    def _record(self, ok: bool, error: str | None) -> None:
        _last.update(ok=ok, at=int(time.time()), error=error)
        if not ok:
            logger.warning("telegram: message not sent -- %s", error)

    async def _discover_chat_id(self, client: httpx.AsyncClient, token: str) -> str | None:
        response = await client.get(f"https://api.telegram.org/bot{token}/getUpdates")
        response.raise_for_status()
        payload = response.json()
        for update in reversed(payload.get("result", [])):
            message = update.get("message") or update.get("channel_post")
            chat = (message or {}).get("chat") or {}
            chat_id = chat.get("id")
            if chat_id is not None:
                return str(chat_id)
        return None


def status() -> dict[str, Any]:
    settings = get_settings()
    env_chat = settings.telegram_chat_id
    stored = _stored_chat_id()
    return {
        "tokenSet": bool(settings.telegram_bot_token),
        "botUsername": settings.telegram_bot_username,
        "chatIdSource": "env" if env_chat else "remembered" if stored else None,
        "lastOk": _last["ok"],
        "lastAt": _last["at"],
        "lastError": _last["error"],
    }
