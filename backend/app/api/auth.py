from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings
from app.services.dhan import DhanService


router = APIRouter(prefix="/dhan", tags=["dhan"])


class LoginIn(BaseModel):
    forceRefresh: bool = False


@router.post("/login")
async def login(payload: LoginIn) -> dict[str, Any]:
    profile = await DhanService().profile(force_refresh=payload.forceRefresh)
    return {
        "authenticated": True,
        "clientId": get_settings().resolved_dhan_client_id,
        "profile": _redact_profile(profile),
    }


@router.get("/session")
async def session() -> dict[str, Any]:
    settings = get_settings()
    return {
        "hasAccessToken": bool(settings.dhan_access_token),
        "hasClientId": bool(settings.resolved_dhan_client_id),
        "clientId": settings.resolved_dhan_client_id,
        "liveOrderEnabled": settings.live_order_enabled,
    }


def _redact_profile(profile: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(profile)
    for key in ("accessToken", "token", "jwt"):
        redacted.pop(key, None)
    return redacted

