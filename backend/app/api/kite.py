from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.services import kite_broker
from app.services.app_auth import require_auth

router = APIRouter(prefix="/kite", tags=["kite"])


@router.get("/status", dependencies=[Depends(require_auth)])
async def status() -> dict[str, Any]:
    out = kite_broker.status()
    if out["connected"]:
        try:
            out["margins"] = await kite_broker.margins()
        except Exception as exc:
            out["error"] = str(exc)
    return out


@router.get("/callback", response_class=HTMLResponse)
async def callback(request_token: str | None = None, status: str | None = None) -> HTMLResponse:
    """Kite's login redirect. Public on purpose: a request_token is useless without the API secret."""
    if status != "success" or not request_token:
        return HTMLResponse("<h3>Zerodha login was not completed.</h3>", status_code=400)
    try:
        who = await kite_broker.complete_login(request_token)
    except Exception as exc:
        return HTMLResponse(f"<h3>Zerodha login failed</h3><p>{exc}</p>", status_code=400)
    return HTMLResponse(f"<h3>Zerodha connected ({who.get('user') or 'ok'}) for today.</h3>"
                        "<p><a href='/nifty-strangle-hedged'>Back to NIFTY Strangle (hedged)</a></p>")
