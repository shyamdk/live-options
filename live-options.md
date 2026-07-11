# Live Options Runbook

Last updated: 2026-07-02

This project is the live trade management app for Dhan option positions. It is intended to run locally for development and on OCI for production-like live monitoring and order execution.

## Purpose

- Manage live Dhan positions from a custom UI.
- Show Nifty 50, Sensex, and India VIX in the common top market strip.
- Segregate open positions into Equity, Options Buy, and Options Sell.
- Show closed trades under their respective trade sections instead of in a separate global section.
- Manage option SL/Target levels from the UI.
- Track daily P&L, estimated charges, net P&L, realized/closed P&L, and journals.
- Send Telegram alerts when short option legs move close to spot.
- Run risk monitoring from the backend so SL/Target execution does not depend on browser refresh.

## Stack

- Frontend: Next.js
- Backend: FastAPI
- Database: SQLite
- Broker: DhanHQ Trading APIs
- Cloud: OCI compute instance
- Process manager on OCI: systemd
- Reverse proxy on OCI: nginx

## Repository

- GitHub remote: `git@github.com:shyamdk/live-options.git`
- Main branch: `main`
- Local project path: `/Users/shyamdk/Developer/options/live-options`
- OCI app path: `/opt/live-options/current`
- OCI shared SQLite path: `/opt/live-options/shared/data/live_options.sqlite3`
- Current public IP / URL: `140.245.25.236`

## Main Pages

### Manage Trades

Manage Trades shows the live Dhan snapshot grouped into:

- Equity
- Options Buy
- Options Sell

Each section can show open rows and a local closed-trades subsection when Dhan returns closed/zero-quantity rows for that category.

The options tables show:

- Strike / symbol
- Side
- Quantity
- Average premium
- LTP
- Gross P&L
- Estimated net P&L
- Estimated charges
- P&L %
- Remaining profit to target for sell options
- Remaining %
- Spot distance %
- SL %
- Target
- Risk/order status
- Actions

### Trade Journals

Trade Journals shows the consolidated daily snapshot and includes two editable text fields:

- Strategy Details
- Lessons Learnt

Closed trades are included in the daily P&L calculations and journal summary.

## Market Strip

The common top strip displays:

- Nifty 50
- Sensex
- India VIX

The backend fetches index quotes from Dhan and caches market quote calls with `DHAN_MARKET_QUOTE_CACHE_SECONDS`. This was added to avoid quote flicker and reduce stale/missing top-panel values.

## SL And Target Semantics

SL and Target are handled per option premium unit, not per lot total.

For example, if a short option was sold at average premium `6.50`:

- Target `3.00` means exit when premium falls to `3.00`.
- SL `50%` means computed SL premium is `9.75`.
- P&L is still calculated on total quantity, so quantity and lot size determine rupee impact.

For sell options:

- Profit improves as premium falls.
- Target should usually be below average premium.
- SL is usually above average premium.
- SL percentage is calculated as `avg * (1 + percent / 100)`.

For buy options:

- Profit improves as premium rises.
- Target should usually be above average premium.
- SL is usually below average premium.
- SL percentage is calculated as `avg * (1 - percent / 100)`.

The UI accepts SL as a percent input and displays the computed premium below the input. The backend stores the resulting premium price.

Target is currently an absolute premium price.

## P&L And Charges

The app estimates option charges so the dashboard can show more realistic net P&L.

Configured charge components include:

- Brokerage per buy/sell transaction
- GST
- STT on sell side
- Stamp duty on buy side
- SEBI turnover charges
- IPFT
- Exchange transaction charges

Important: app charges are estimates. Final charges must be reconciled against Dhan contract notes.

Closed trades are included in:

- Day P&L
- Estimated charges
- Net P&L
- Realized/closed P&L
- Journal summary

## Dhan Authentication

The app supports two Dhan token modes:

- Manual `DHAN_ACCESS_TOKEN`
- Auto generation using Dhan client id, PIN, and TOTP secret

For live operation, the safest current flow is:

1. Generate a fresh Dhan access token from Dhan Web.
2. Update `DHAN_ACCESS_TOKEN` in `.env`.
3. Restart the backend.
4. Verify `/api/dhan/login` or profile access returns 200.

Do not commit `.env`, access tokens, PINs, TOTP secrets, app auth passwords, or Telegram tokens.

## Dhan Static IP

Dhan order-placement APIs require static IP whitelisting.

Current OCI outbound/static IP:

```text
140.245.25.236
```

What was verified:

- Dhan `GET /v2/ip/getIP` returns primary IP `140.245.25.236`.
- OCI outbound IP check also returns `140.245.25.236`.
- After refreshing the access token, Dhan no longer returned `DH-905 Invalid IP`.

Important distinction:

- Dhan positions, order details, and trade details can work even when order placement IP validation fails.
- Actual order placement requires the whitelisted static IP to match the server's outbound IP.

## Live Orders

Live order placement is controlled by separate flags:

- `LIVE_ORDER_ENABLED=true` allows any live Dhan order payload to be sent.
- `RISK_ORDER_MONITOR_ENABLED=true` starts the backend risk monitor.
- `RISK_ORDER_EXECUTION_ENABLED=true` allows the risk monitor to send SL/Target exit orders.
- `RISK_ORDER_RETRY_SECONDS` controls retry spacing after failed risk order attempts.

Manual close orders and risk monitor orders use Dhan market orders.

The app must never show `Target hit` or `SL hit` merely because price crossed a configured level. It now uses order-aware status labels:

- `Monitoring`: no configured threshold reached.
- `Target reached`: target price crossed, but no confirmed Dhan order accepted yet.
- `SL reached`: SL price crossed, but no confirmed Dhan order accepted yet.
- `Target order failed`: Dhan/order layer rejected the target exit attempt.
- `SL order failed`: Dhan/order layer rejected the SL exit attempt.
- `Target hit`: Dhan accepted the target exit order.
- `SL hit`: Dhan accepted the SL exit order.

The audit table records order attempts and broker responses. Failed attempts are retryable after `RISK_ORDER_RETRY_SECONDS`; they do not permanently block a future retry.

## Current OCI Order Status

After the latest access-token refresh on OCI:

- Dhan profile/auth call through the backend returned 200.
- Static IP rejection moved past `DH-905 Invalid IP`.
- Dhan then rejected live target-exit attempts with `DH-906 Market is Closed! Want to place an offline order?`.
- No `orderId` was returned for those attempts, so no Dhan order was placed.

This means the Dhan IP/token path is now working, but testing happened after market close.

## Telegram Alerts

Spot-distance alerts are configured for short option positions.

Relevant settings:

- `SPOT_DISTANCE_ALERT_ENABLED`
- `SPOT_DISTANCE_ALERT_PERCENT`
- `SPOT_DISTANCE_MONITOR_ENABLED`
- `SPOT_DISTANCE_MONITOR_INTERVAL_SECONDS`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

The current threshold logic alerts when a short option leg is within the configured spot-distance percentage, for example `0.5%` or less.

## Local Development

Create Python virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
```

Run backend locally:

```bash
cd backend
../.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

Run frontend locally:

```bash
cd frontend
npm install
npm run dev -- --hostname 127.0.0.1 --port 3001
```

The local frontend defaults to:

```text
http://127.0.0.1:8001
```

Set `NEXT_PUBLIC_API_BASE_URL` if pointing the frontend at a different backend.

## Trade Instance Scheduling

`140.245.25.236` is only needed on trading days and is now automatically
stopped outside trading hours to save cost/reduce exposure:

- A reconciler script (`ops/trade_instance_scheduler.py` in this repo;
  deployed at `~/trade-instance-scheduler/scheduler.py`) runs every 5 minutes
  via cron on `161.118.162.75`, an always-on box in the same OCI compartment.
- It starts the instance at 8:30 AM IST and soft-stops it at 5:00 PM IST,
  Monday-Friday, skipping NSE holidays (maintained as a hardcoded set in the
  script — update once a year).
- Auth: instance-principal, via a Dynamic Group (`trade-instance-scheduler`,
  matching `161.118.162.75` by instance OCID) and a Policy granting it
  `manage instance-family` in the shared compartment. A tighter
  `where target.resource.id = '<instance OCID>'` condition was tried first to
  scope this to only the trade instance, but OCI rejected it as a no-op for
  this resource type — fell back to compartment-scoped (acceptable, only two
  instances live there).
- Since the box is not always on, don't expect health checks, deploys, or SSH
  to work outside 8:30 AM-5:00 PM IST on a trading day unless manually started
  (`oci compute instance action --instance-id <OCID> --action START`).
- Logs: `~/trade-instance-scheduler/scheduler.log` on `161.118.162.75`.

## OCI Operations

Backend service:

```bash
sudo systemctl restart live-options-backend.service
systemctl is-active live-options-backend.service
journalctl -u live-options-backend.service --since "10 minutes ago" --no-pager
```

Frontend service:

```bash
sudo systemctl restart live-options-frontend.service
systemctl is-active live-options-frontend.service
```

Health checks:

```bash
curl http://140.245.25.236/health
curl http://140.245.25.236/api/auth/status
```

Dhan IP verification from OCI:

```bash
curl -4 https://ifconfig.me
```

Use Dhan `GET /v2/ip/getIP` with the configured access token to verify the broker-side whitelist.

## Deployment Notes

Current deploy approach:

- Build/test locally.
- Push code to GitHub.
- Deploy to OCI release directory under `/opt/live-options/releases/...`.
- Point `/opt/live-options/current` at the active release.
- Keep production `.env` and SQLite data in shared locations.
- Restart backend/frontend services.
- Verify public URL and API health.

Before deploying live-order changes:

- Run backend compile checks.
- Run frontend typecheck/build.
- Test locally against live read-only Dhan calls where possible.
- Confirm `LIVE_ORDER_ENABLED`, `RISK_ORDER_EXECUTION_ENABLED`, and token freshness intentionally.
- Check latest order audit after deployment.

## Security

The app is on a public URL, so these controls matter:

- App authentication is enabled.
- `APP_AUTH_SECRET` signs session tokens.
- `APP_AUTH_PASSWORD` protects login.
- `.env` must never be committed or exposed through nginx.
- SQLite database and logs must not be web-served.
- Dhan token must be rotated regularly.
- Restrict OCI inbound ports to only what is required.
- Prefer HTTPS/domain setup before serious live use.

## Known Follow-Up Work

- Add market-hours guard so the risk monitor stops retrying live exit orders after market close.
- Add stronger postback/live order update handling so accepted Dhan orders can be reconciled automatically.
- Add a dedicated order audit page in the UI.
- Add explicit target percent support if needed; target is currently absolute premium.
- Add a safer production secret-management path instead of editing `.env` for token updates.
- Add automated tests around SL percent conversion, closed-trade grouping, and risk status labels.
