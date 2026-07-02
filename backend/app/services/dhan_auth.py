from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import struct
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.config import ROOT_DIR, Settings, get_settings


class DhanAuthError(RuntimeError):
    pass


_AUTH_LOCK = asyncio.Lock()


def _generate_totp(secret: str, digits: int = 6, period: int = 30) -> str:
    normalized = secret.replace(" ", "").upper()
    missing_padding = len(normalized) % 8
    if missing_padding:
        normalized += "=" * (8 - missing_padding)
    key = base64.b32decode(normalized, casefold=True)
    counter = int(time.time() // period)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**digits)).zfill(digits)


def _configured_pin(settings: Settings) -> str | None:
    return settings.dhan_pin or settings.dhan_login_pin or settings.dhan_web_pin


def _configured_totp_secret(settings: Settings) -> str | None:
    return settings.totp_secret or settings.dhan_totp_secret


def _store_env_value(name: str, value: str) -> None:
    env_path = Path(ROOT_DIR) / ".env"
    if not env_path.exists():
        env_path.write_text(f"{name}={value}\n", encoding="utf-8")
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    updated = False
    next_lines: list[str] = []
    for line in lines:
        if line.startswith(f"{name}="):
            next_lines.append(f"{name}={value}")
            updated = True
        else:
            next_lines.append(line)
    if not updated:
        next_lines.append(f"{name}={value}")
    env_path.write_text("\n".join(next_lines) + "\n", encoding="utf-8")


async def get_dhan_access_token(settings: Settings | None = None, *, force_refresh: bool = False) -> str:
    settings = settings or get_settings()
    if settings.dhan_access_token and not force_refresh:
        return settings.dhan_access_token

    async with _AUTH_LOCK:
        if settings.dhan_access_token and not force_refresh:
            return settings.dhan_access_token

        token = await generate_dhan_access_token(settings)
        settings.dhan_access_token = token
        os.environ["DHAN_ACCESS_TOKEN"] = token
        _store_env_value("DHAN_ACCESS_TOKEN", token)
        return token


async def generate_dhan_access_token(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    client_id = settings.resolved_dhan_client_id
    pin = _configured_pin(settings)
    totp_secret = _configured_totp_secret(settings)

    missing = [
        name
        for name, value in (
            ("DHAN_CLIENT_ID", client_id),
            ("DHAN_PIN / DHAN_LOGIN_PIN / DHAN_WEB_PIN", pin),
            ("TOTP_SECRET / DHAN_TOTP_SECRET", totp_secret),
        )
        if not value
    ]
    if missing:
        raise DhanAuthError(
            "Cannot auto-generate Dhan access token. Missing "
            f"{', '.join(missing)}. Manual DHAN_ACCESS_TOKEN may be required."
        )

    try:
        totp = _generate_totp(str(totp_secret))
    except Exception as exc:
        raise DhanAuthError(f"Cannot generate Dhan TOTP from configured secret: {exc}") from exc

    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(
            f"{settings.dhan_auth_base_url}/app/generateAccessToken",
            params={"dhanClientId": client_id, "pin": pin, "totp": totp},
        )

    try:
        payload: dict[str, Any] = response.json()
    except ValueError as exc:
        raise DhanAuthError(f"Dhan token generation failed: HTTP {response.status_code}") from exc

    access_token = payload.get("accessToken")
    if response.is_error or not access_token:
        message = payload.get("message") or payload.get("remarks") or payload.get("error") or str(payload)
        if "once every 2 minutes" in str(message).lower() and settings.dhan_access_token:
            return settings.dhan_access_token
        raise DhanAuthError(f"Dhan token generation failed: {message}")

    return str(access_token)

