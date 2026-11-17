from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.animesh import router as animesh_router
from app.api.app_auth import router as app_auth_router
from app.api.assistant import router as assistant_router
from app.api.auth import router as auth_router
from app.api.batman import router as batman_router
from app.api.btc_strangle import router as btc_strangle_router
from app.api.credit_spread import router as credit_spread_router
from app.api.ema5 import router as ema5_router
from app.api.gamma_blast import router as gamma_blast_router
from app.api.journals import router as journals_router
from app.api.mantra import router as mantra_router
from app.api.melting import router as melting_router
from app.api.melting_gap import router as melting_gap_router
from app.api.melting_expiry import router as melting_expiry_router
from app.api.index_runway import router as index_runway_router
from app.api.nifty_strangle import router as nifty_strangle_router
from app.api.market_events import router as market_events_router
from app.api.kite import router as kite_router
from app.api.calm_strangle import router as calm_strangle_router
from app.api.calm_or import router as calm_or_router
from app.api.disha import router as disha_router
from app.api.btc_calm import router as btc_calm_router
from app.api.varaha_paper import router as varaha_paper_router
from app.api.alerts import router as alerts_router
from app.api.equity_swing import router as equity_swing_router
from app.api.market import router as market_router
from app.api.paper_trading import router as paper_trading_router
from app.api.equity import router as equity_router
from app.api.simple_crossover import router as simple_crossover_router
from app.api.theta import router as theta_router
from app.api.trades import router as trades_router
from app.api.turtle import router as turtle_router
from app.api.turtle_a1 import router as turtle_a1_router
from app.api.turtle_filtered import router as turtle_filtered_router
from app.api.notes import router as notes_router
from app.api.pf_lab import router as pf_lab_router
from app.api.choch import router as choch_router
from app.api.order_flow import router as order_flow_router
from app.api.varaha import router as varaha_router
from app.core.config import get_settings
from app.db.sqlite import init_db
from app.services.animesh import start_animesh_task, stop_animesh_task
from app.services.batman import start_batman_task, stop_batman_task
from app.services.btc_strangle import start_btc_strangle_task, stop_btc_strangle_task
from app.services.credit_spread import start_credit_spread_task, stop_credit_spread_task
from app.services.ema5 import start_ema5_task, stop_ema5_task
from app.services.gamma_blast import start_gamma_blast_task, stop_gamma_blast_task
from app.services.journal_insights import start_journal_insights_task, stop_journal_insights_task
from app.services.market_news import (
    start_market_calendar_task,
    start_market_news_task,
    stop_market_calendar_task,
    stop_market_news_task,
)
from app.services.oi_upgraded import start_oi_upgraded_task, stop_oi_upgraded_task
from app.services.paper_trading import start_paper_trading_task, stop_paper_trading_task
from app.services.pcr_oi import start_pcr_oi_task, stop_pcr_oi_task
from app.services.simple_crossover import start_simple_crossover_task, stop_simple_crossover_task
from app.services.mantra import start_mantra_task, stop_mantra_task
from app.services.melting import start_melting_task, stop_melting_task
from app.services.melting_gap import start_melting_gap_task, stop_melting_gap_task
from app.services.melting_expiry import start_melting_expiry_task, stop_melting_expiry_task
from app.services.index_runway import start_index_runway_task, stop_index_runway_task
from app.services.nifty_strangle import start_nifty_strangle_task, stop_nifty_strangle_task
from app.services.market_events import start_market_events_task, stop_market_events_task
from app.services.kite_broker import start_kite_task, stop_kite_task
from app.services.calm_strangle import start_calm_strangle_task, stop_calm_strangle_task
from app.services.calm_or import start_calm_or_task, stop_calm_or_task
from app.services.btc_calm import start_btc_calm_task, stop_btc_calm_task
from app.services.varaha_paper import start_varaha_paper_task, stop_varaha_paper_task
from app.services.alerts import start_alerts_task, stop_alerts_task
from app.services.dhan_health import start_dhan_health_task, stop_dhan_health_task
from app.services.equity_swing import start_equity_swing_task, stop_equity_swing_task
from app.services.theta import start_theta_task, stop_theta_task
from app.services.turtle import start_turtle_task, stop_turtle_task
from app.services.turtle_a1 import start_turtle_a1_task, stop_turtle_a1_task
from app.services.turtle_filtered import start_turtle_filtered_task, stop_turtle_filtered_task
from app.services.pf_lab import start_pf_lab_task, stop_pf_lab_task
from app.services.choch import start_choch_task, stop_choch_task
from app.services.order_flow import start_order_flow_task, stop_order_flow_task
from app.services.varaha import start_varaha_task, stop_varaha_task
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
theta_task = None
market_news_task = None
market_calendar_task = None
pcr_oi_task = None
paper_trading_task = None
oi_upgraded_task = None
simple_crossover_task = None
varaha_task = None
btc_strangle_task = None
batman_task = None
turtle_task = None
turtle_a1_task = None
turtle_filtered_task = None
pf_lab_task = None
choch_task = None
order_flow_task = None
mantra_task = None
melting_task = None
melting_gap_task = None
melting_expiry_task = None
index_runway_task = None
nifty_strangle_task = None
market_events_task = None
kite_task = None
calm_strangle_task = None
calm_or_task = None
btc_calm_task = None
varaha_paper_task = None
alerts_task = None
dhan_health_task = None
equity_swing_task = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    global risk_order_monitor_task, spot_distance_monitor_task, gamma_blast_task, journal_insights_task, ema5_task, animesh_task, credit_spread_task, theta_task, market_news_task, market_calendar_task, pcr_oi_task, paper_trading_task, oi_upgraded_task, simple_crossover_task, varaha_task, btc_strangle_task, batman_task, turtle_task, turtle_a1_task, turtle_filtered_task, pf_lab_task, choch_task, order_flow_task, mantra_task, melting_task, melting_gap_task, melting_expiry_task, index_runway_task, nifty_strangle_task, market_events_task, kite_task, calm_strangle_task, calm_or_task, btc_calm_task, varaha_paper_task, alerts_task, equity_swing_task, dhan_health_task
    init_db()
    spot_distance_monitor_task = start_spot_distance_monitor_task()
    risk_order_monitor_task = start_risk_order_monitor_task()
    gamma_blast_task = start_gamma_blast_task()
    journal_insights_task = start_journal_insights_task()
    ema5_task = start_ema5_task()
    animesh_task = start_animesh_task()
    credit_spread_task = start_credit_spread_task()
    theta_task = start_theta_task()
    market_news_task = start_market_news_task()
    market_calendar_task = start_market_calendar_task()
    pcr_oi_task = start_pcr_oi_task()
    paper_trading_task = start_paper_trading_task()
    oi_upgraded_task = start_oi_upgraded_task()
    simple_crossover_task = start_simple_crossover_task()
    varaha_task = start_varaha_task()
    btc_strangle_task = start_btc_strangle_task()
    batman_task = start_batman_task()
    turtle_task = start_turtle_task()
    turtle_a1_task = start_turtle_a1_task()
    turtle_filtered_task = start_turtle_filtered_task()
    pf_lab_task = start_pf_lab_task()
    choch_task = start_choch_task()
    order_flow_task = start_order_flow_task()
    mantra_task = start_mantra_task()
    melting_task = start_melting_task()
    melting_gap_task = start_melting_gap_task()
    melting_expiry_task = start_melting_expiry_task()
    index_runway_task = start_index_runway_task()
    nifty_strangle_task = start_nifty_strangle_task()
    market_events_task = start_market_events_task()
    kite_task = start_kite_task()
    calm_strangle_task = start_calm_strangle_task()
    calm_or_task = start_calm_or_task()
    btc_calm_task = start_btc_calm_task()
    varaha_paper_task = start_varaha_paper_task()
    alerts_task = start_alerts_task()
    dhan_health_task = start_dhan_health_task()
    equity_swing_task = start_equity_swing_task()


@app.on_event("shutdown")
async def shutdown() -> None:
    await stop_risk_order_monitor_task(risk_order_monitor_task)
    await stop_spot_distance_monitor_task(spot_distance_monitor_task)
    await stop_gamma_blast_task(gamma_blast_task)
    await stop_journal_insights_task(journal_insights_task)
    await stop_ema5_task(ema5_task)
    await stop_animesh_task(animesh_task)
    await stop_credit_spread_task(credit_spread_task)
    await stop_theta_task(theta_task)
    await stop_market_news_task(market_news_task)
    await stop_market_calendar_task(market_calendar_task)
    await stop_pcr_oi_task(pcr_oi_task)
    await stop_paper_trading_task(paper_trading_task)
    await stop_oi_upgraded_task(oi_upgraded_task)
    await stop_simple_crossover_task(simple_crossover_task)
    await stop_varaha_task(varaha_task)
    await stop_btc_strangle_task(btc_strangle_task)
    await stop_batman_task(batman_task)
    await stop_turtle_task(turtle_task)
    await stop_turtle_a1_task(turtle_a1_task)
    await stop_turtle_filtered_task(turtle_filtered_task)
    await stop_pf_lab_task(pf_lab_task)
    await stop_choch_task(choch_task)
    await stop_order_flow_task(order_flow_task)
    await stop_mantra_task(mantra_task)
    await stop_melting_task(melting_task)
    await stop_melting_gap_task(melting_gap_task)
    await stop_melting_expiry_task(melting_expiry_task)
    await stop_index_runway_task(index_runway_task)
    await stop_nifty_strangle_task(nifty_strangle_task)
    await stop_market_events_task(market_events_task)
    await stop_kite_task(kite_task)
    await stop_calm_strangle_task(calm_strangle_task)
    await stop_calm_or_task(calm_or_task)
    await stop_btc_calm_task(btc_calm_task)
    await stop_varaha_paper_task(varaha_paper_task)
    await stop_alerts_task(alerts_task)
    await stop_dhan_health_task(dhan_health_task)
    await stop_equity_swing_task(equity_swing_task)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(app_auth_router, prefix=settings.api_prefix)
app.include_router(assistant_router, prefix=settings.api_prefix)
app.include_router(journals_router, prefix=settings.api_prefix)
app.include_router(market_router, prefix=settings.api_prefix)
app.include_router(trades_router, prefix=settings.api_prefix)
app.include_router(gamma_blast_router, prefix=settings.api_prefix)
app.include_router(ema5_router, prefix=settings.api_prefix)
app.include_router(animesh_router, prefix=settings.api_prefix)
app.include_router(credit_spread_router, prefix=settings.api_prefix)
app.include_router(theta_router, prefix=settings.api_prefix)
app.include_router(varaha_router, prefix=settings.api_prefix)
app.include_router(btc_strangle_router, prefix=settings.api_prefix)
app.include_router(batman_router, prefix=settings.api_prefix)
app.include_router(turtle_router, prefix=settings.api_prefix)
app.include_router(turtle_a1_router, prefix=settings.api_prefix)
app.include_router(turtle_filtered_router, prefix=settings.api_prefix)
app.include_router(notes_router, prefix=settings.api_prefix)
app.include_router(pf_lab_router, prefix=settings.api_prefix)
app.include_router(choch_router, prefix=settings.api_prefix)
app.include_router(order_flow_router, prefix=settings.api_prefix)
app.include_router(mantra_router, prefix=settings.api_prefix)
app.include_router(melting_router, prefix=settings.api_prefix)
app.include_router(melting_gap_router, prefix=settings.api_prefix)
app.include_router(melting_expiry_router, prefix=settings.api_prefix)
app.include_router(index_runway_router, prefix=settings.api_prefix)
app.include_router(nifty_strangle_router, prefix=settings.api_prefix)
app.include_router(market_events_router, prefix=settings.api_prefix)
app.include_router(kite_router, prefix=settings.api_prefix)
app.include_router(calm_strangle_router, prefix=settings.api_prefix)
app.include_router(calm_or_router, prefix=settings.api_prefix)
app.include_router(disha_router, prefix=settings.api_prefix)
app.include_router(btc_calm_router, prefix=settings.api_prefix)
app.include_router(varaha_paper_router, prefix=settings.api_prefix)
app.include_router(alerts_router, prefix=settings.api_prefix)
app.include_router(equity_swing_router, prefix=settings.api_prefix)
app.include_router(paper_trading_router, prefix=settings.api_prefix)
app.include_router(simple_crossover_router, prefix=settings.api_prefix)
app.include_router(equity_router, prefix=settings.api_prefix)
