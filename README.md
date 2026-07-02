# Live Options

Live Dhan trade management workspace with a FastAPI backend, SQLite persistence, and a Next.js frontend.

## Structure

- `backend` - FastAPI middle tier and SQLite data store.
- `frontend` - Next.js app with Manage Trades and Trade Journals pages.
- `.env` - copied from Options Dash and read by the backend.

## Local Run

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
cd backend
../.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
cd frontend
npm install
npm run dev -- --hostname 127.0.0.1 --port 3000
```

The frontend defaults to `http://127.0.0.1:8000` for API calls. Set `NEXT_PUBLIC_API_BASE_URL` if the backend is hosted elsewhere.

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

Keep the backend behind HTTPS on OCI, restrict inbound ports, and do not expose `.env`, SQLite data, or logs. The app estimates option charges from configurable rates; reconcile final charges against the Dhan contract note.
