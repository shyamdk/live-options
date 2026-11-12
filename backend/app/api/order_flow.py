from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.services import order_flow
from app.services.app_auth import require_auth

router = APIRouter(prefix="/order-flow", tags=["order-flow"])


@router.get("/state", dependencies=[Depends(require_auth)])
async def state() -> dict[str, Any]:
    return order_flow.state()
