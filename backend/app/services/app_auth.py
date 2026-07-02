from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import Header, HTTPException

from app.core.config import Settings, get_settings


def create_session_token(username: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    expires_at = int(time.time() + max(settings.app_auth_session_hours, 1) * 3600)
    payload = {"sub": username, "exp": expires_at}
    payload_part = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _sign(payload_part, settings)
    return f"{payload_part}.{signature}"


def verify_session_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    try:
        payload_part, signature = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid session token.") from exc
    expected = _sign(payload_part, settings)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid session token.")
    try:
        payload = json.loads(_unb64(payload_part).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid session token.") from exc
    if int(payload.get("exp") or 0) < int(time.time()):
        raise HTTPException(status_code=401, detail="Session expired.")
    return payload


def authenticate(username: str, password: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if not settings.auth_enabled:
        return create_session_token(username or settings.app_auth_username, settings)
    if not settings.app_auth_password:
        raise HTTPException(status_code=503, detail="APP_AUTH_PASSWORD is not configured.")
    valid_username = hmac.compare_digest(username, settings.app_auth_username)
    valid_password = hmac.compare_digest(password, settings.app_auth_password)
    if not (valid_username and valid_password):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return create_session_token(username, settings)


async def require_auth(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    settings = get_settings()
    if not settings.auth_enabled:
        return {"sub": "local", "exp": None}
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required.")
    return verify_session_token(authorization.split(" ", 1)[1], settings)


def auth_status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": settings.auth_enabled,
        "configured": bool(settings.app_auth_password) if settings.auth_enabled else True,
        "username": settings.app_auth_username,
        "sessionHours": settings.app_auth_session_hours,
    }


def _sign(payload_part: str, settings: Settings) -> str:
    secret = settings.app_auth_secret or settings.app_auth_password
    if not secret and not settings.auth_enabled:
        secret = "local-dev-auth-disabled"
    if not secret:
        raise HTTPException(status_code=503, detail="APP_AUTH_SECRET or APP_AUTH_PASSWORD is required.")
    digest = hmac.new(secret.encode("utf-8"), payload_part.encode("utf-8"), hashlib.sha256).digest()
    return _b64(digest)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
