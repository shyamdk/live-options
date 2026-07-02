from __future__ import annotations

import httpx

from app.core.config import Settings, get_settings


class TelegramNotifier:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def send(self, text: str) -> bool:
        token = self.settings.telegram_bot_token
        if not token:
            return False
        chat_id = self.settings.telegram_chat_id
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                if not chat_id:
                    chat_id = await self._discover_chat_id(client, token)
                if not chat_id:
                    return False
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                )
                response.raise_for_status()
                return True
        except Exception:
            return False

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

