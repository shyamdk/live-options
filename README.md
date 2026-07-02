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

