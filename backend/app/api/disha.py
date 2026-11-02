from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.services.app_auth import require_auth
from app.services.disha import get_state

router = APIRouter(prefix="/disha", tags=["disha"])


@router.get("/state", dependencies=[Depends(require_auth)])
async def state() -> dict[str, Any]:
    return await get_state()
