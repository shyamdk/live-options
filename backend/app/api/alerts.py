from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.services import alerts, telegram
from app.services.app_auth import require_auth
from app.services.telegram import TelegramNotifier

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertIn(BaseModel):
    kind: str
    symbol: str | None = None
    securityId: str | None = None
    segment: str | None = None
    direction: str | None = None
    price: float | None = None
    remindAt: int | None = None
    note: str | None = None
    source: str | None = None


@router.get("", dependencies=[Depends(require_auth)])
async def list_alerts() -> dict[str, Any]:
    return {**alerts.list_all(), "telegram": telegram.status()}


@router.post("", dependencies=[Depends(require_auth)])
async def create_alert(body: AlertIn) -> dict[str, Any]:
    try:
        return alerts.create(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{alert_id}/{action}", dependencies=[Depends(require_auth)])
async def alert_action(alert_id: int, action: str) -> dict[str, Any]:
    try:
        return alerts.set_status(alert_id, action)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/telegram-test", dependencies=[Depends(require_auth)])
async def telegram_test() -> dict[str, Any]:
    ok = await TelegramNotifier().send("✅ Live Options: test message -- Telegram alerts are working.")
    return {"sent": ok, **telegram.status()}
