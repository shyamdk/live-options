# Live Options

Live Dhan trade management workspace with a FastAPI backend, SQLite persistence, and a Next.js frontend.

## Strategies

- **Gamma Blast** (`/gamma-blast`) - expiry-day OI-wall breakout monitor.
- **ema5** (`/ema5`) and **animesh-scalping** (`/animesh-scalping`) - intraday option-buying engines.
- **BN Credit Spread** (`/bank-nifty-credit-spread`) - positional Bank Nifty monthly bear call spread: sell the futures-ATM CE, buy the ~Rs 100 hedge CE on the first trading day after monthly expiry (09:45), exit both legs at 09:20 when 10 trading days remain (plus a 50%-of-credit profit target). Rules were reverse engineered and Dhan-verified from a 31-month track record; see `bank-nifty/strategy.md` in the sibling repo for the full derivation and risk notes. Runs in `CREDIT_SPREAD_MODE=PAPER` by default; flip to `LIVE` (plus `LIVE_ORDER_ENABLED=true`) only after paper-trading a full cycle. Keep `NSE_HOLIDAYS` current - the T-10 exit date is computed from it.

## Structure

- `backend` - FastAPI middle tier and SQLite data store.
- `frontend` - Next.js app with Manage Trades and Trade Journals pages.
- `.env` - copied from Options Dash and read by the backend.

## Local Run

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
cd backend
../.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

```bash
cd frontend
npm install
npm run dev -- --hostname 127.0.0.1 --port 3001
```

The frontend defaults to `http://127.0.0.1:8001` for API calls. Set `NEXT_PUBLIC_API_BASE_URL` if the backend is hosted elsewhere.

## Public Deployment

Copy `.env.example` to `.env` and set at minimum:

- `APP_AUTH_PASSWORD` and `APP_AUTH_SECRET` for the app login.
- Dhan credentials/token fields.
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` for spot-distance alerts.
- `CORS_ORIGINS` to the production frontend URL.

Auto SL/Target exits are controlled separately from manual close orders:

- `RISK_ORDER_MONITOR_ENABLED=true` starts the backend monitor.
- `RISK_ORDER_EXECUTION_ENABLED=true` is required before the monitor can send Dhan close orders.
- `LIVE_ORDER_ENABLED=true` is still required for any live Dhan order to be sent.
- `RISK_ORDER_RETRY_SECONDS` controls retry spacing after a failed Dhan risk order.

Risk labels are order-aware: `Target reached` / `SL reached` means the price crossed the configured level, while `Target hit` / `SL hit` is shown only after Dhan accepts the exit order. Failed Dhan attempts show `Target order failed` or `SL order failed`.
On Manage Trades, SL can be entered as an absolute premium price or as a percent like `20%`; percent entries are converted from the trade average before saving.

Keep the backend behind HTTPS on OCI, restrict inbound ports, and do not expose `.env`, SQLite data, or logs. The app estimates option charges from configurable rates; reconcile final charges against the Dhan contract note.
