from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.services.app_auth import auth_status, authenticate, require_auth


router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


@router.get("/status")
async def status() -> dict[str, Any]:
    return auth_status()


@router.get("/session")
async def session(user: dict[str, Any] = Depends(require_auth)) -> dict[str, Any]:
    return {"authenticated": True, "user": user.get("sub"), **auth_status()}


@router.post("/login")
async def login(payload: LoginIn) -> dict[str, Any]:
    token = authenticate(payload.username, payload.password)
    return {"token": token, "authenticated": True, "user": payload.username, **auth_status()}

