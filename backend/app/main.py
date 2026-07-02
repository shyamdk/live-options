from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.journals import router as journals_router
from app.api.market import router as market_router
from app.api.trades import router as trades_router
from app.core.config import get_settings
from app.db.sqlite import init_db


settings = get_settings()
app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    init_db()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(journals_router, prefix=settings.api_prefix)
app.include_router(market_router, prefix=settings.api_prefix)
app.include_router(trades_router, prefix=settings.api_prefix)

