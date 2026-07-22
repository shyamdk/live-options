from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.animesh import router as animesh_router
from app.api.app_auth import router as app_auth_router
from app.api.auth import router as auth_router
from app.api.credit_spread import router as credit_spread_router
from app.api.ema5 import router as ema5_router
from app.api.gamma_blast import router as gamma_blast_router
from app.api.journals import router as journals_router
from app.api.market import router as market_router
from app.api.trades import router as trades_router
from app.core.config import get_settings
from app.db.sqlite import init_db
from app.services.animesh import start_animesh_task, stop_animesh_task
from app.services.credit_spread import start_credit_spread_task, stop_credit_spread_task
from app.services.ema5 import start_ema5_task, stop_ema5_task
from app.services.gamma_blast import start_gamma_blast_task, stop_gamma_blast_task
from app.services.journal_insights import start_journal_insights_task, stop_journal_insights_task
from app.services.trades import (
    start_risk_order_monitor_task,
    start_spot_distance_monitor_task,
    stop_risk_order_monitor_task,
    stop_spot_distance_monitor_task,
)


settings = get_settings()
app = FastAPI(title=settings.app_name)
spot_distance_monitor_task = None
risk_order_monitor_task = None
gamma_blast_task = None
journal_insights_task = None
ema5_task = None
animesh_task = None
credit_spread_task = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    global risk_order_monitor_task, spot_distance_monitor_task, gamma_blast_task, journal_insights_task, ema5_task, animesh_task, credit_spread_task
    init_db()
    spot_distance_monitor_task = start_spot_distance_monitor_task()
    risk_order_monitor_task = start_risk_order_monitor_task()
    gamma_blast_task = start_gamma_blast_task()
    journal_insights_task = start_journal_insights_task()
    ema5_task = start_ema5_task()
    animesh_task = start_animesh_task()
    credit_spread_task = start_credit_spread_task()


@app.on_event("shutdown")
async def shutdown() -> None:
    await stop_risk_order_monitor_task(risk_order_monitor_task)
    await stop_spot_distance_monitor_task(spot_distance_monitor_task)
    await stop_gamma_blast_task(gamma_blast_task)
    await stop_journal_insights_task(journal_insights_task)
    await stop_ema5_task(ema5_task)
    await stop_animesh_task(animesh_task)
    await stop_credit_spread_task(credit_spread_task)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(app_auth_router, prefix=settings.api_prefix)
app.include_router(journals_router, prefix=settings.api_prefix)
app.include_router(market_router, prefix=settings.api_prefix)
app.include_router(trades_router, prefix=settings.api_prefix)
app.include_router(gamma_blast_router, prefix=settings.api_prefix)
app.include_router(ema5_router, prefix=settings.api_prefix)
app.include_router(animesh_router, prefix=settings.api_prefix)
app.include_router(credit_spread_router, prefix=settings.api_prefix)
