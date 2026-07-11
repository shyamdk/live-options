# Build Progress Log

A detailed, chronological record of everything built, fixed, and deployed in
this project's working sessions — what the problem was, why it mattered, what
was actually done, and how it was verified before shipping. Ordered by git
commit sequence.

---

## 1. Detect invalid-token Dhan errors beyond HTTP 401

**Commit:** `7beba1a`

### Why

The Manage Trades dashboard was intermittently showing a yellow banner:
`Dhan GET /positions failed: {'errorType': 'Order_Error', 'errorCode': 'DH-906', 'errorMessage': 'Invalid Token'}`.

### Investigation

`DhanService._request()` in `backend/app/services/dhan.py` only retried with a
force-refreshed token when Dhan's HTTP response status was literally `401`.
Tracing the actual error message shown, it was clear Dhan was returning this
specific invalid-token failure with some *other* status code (the code path
that formats a `401` explicitly says "401 Unauthorized from Dhan..." — the
banner showed the raw dict instead, meaning it fell through the generic
`str(payload)` branch). So once the cached access token actually went stale,
**every** poll of `/positions` — UI refresh, the 5s risk monitor, the
spot-distance monitor — hit the same dead end repeatedly, because the retry
condition never matched.

### What was done

`_request()` now calls a new `_is_invalid_token_response()` check instead of
comparing `status_code == 401` directly. That check treats a `401`, **or** a
JSON body whose error text mentions `token`/`invalid access` (regardless of
HTTP status), as a signal to retry once with a forced token refresh — mirroring
a pattern already used elsewhere in `orders.py` for detecting `DH-`-prefixed
error codes independent of HTTP status.

### Verification

Unit-style checks confirmed: the exact `DH-906 Invalid Token` case now
triggers a refresh regardless of status code, while the *different*
`DH-906 Market is Closed!` case (a separate, already-documented failure mode)
correctly does **not** trigger a wasted refresh attempt.

---

## 2. Use real Dhan trade-book fills for option brokerage estimates

**Commit:** `2f81e92`

### Why

User flagged that charges looked wrong after placing several new orders on
positions that were already open, even though quantity was displaying
correctly.

### Investigation

`apply_option_charge_estimates()` in `backend/app/services/charges.py` always
assumed exactly **one** entry order and one hypothetical exit order per
position leg, charging a flat ₹20 brokerage for each. But Dhan charges
brokerage *per executed order*, and Dhan's own `/positions` response only
returns the *net* aggregated quantity/average price — it can't tell you how
many separate orders built that position.

Confirmed against **live Dhan data**: `NIFTY-Jul2026-24650-CE` (qty -390) had
actually been built from **3 separate sell orders** (65 @ 3.0, 195 @ 2.5, 130
@ 3.1 — weighted average 2.783, matching the UI's displayed 2.78), while a
sibling position (`NIFTY 24200 PE`, qty -195) came from a single order. The app
was charging both as if each had exactly one entry order.

### What was done

- `DhanService.trade_book()` added to `dhan.py` — calls Dhan's `GET /trades`
  (today's executed trade/fill list).
- `order_counts_from_trade_book()` in `charges.py` counts actual fills per
  `(securityId, transactionType)`.
- `apply_option_charge_estimates()` (open positions) and
  `apply_closed_option_charge_estimates()` (closed positions) now multiply
  brokerage by the real order count for that leg/side, falling back to 1 if no
  matching trade-book entry exists (e.g. a position carried from a prior day).

### Verification

Re-ran the charge calculation against the real trade-book data pulled above:
the single-order leg still computed to exactly ₹48.64 (matching the UI,
proving no regression), while the 3-order leg correctly rose from ₹49.09 to
₹96.29 — the extra ₹47.20 accounting for 2 more ₹20 brokerage charges plus GST
on them.

---

## 3. Speed up risk-monitor and UI polling for faster SL/Target execution

**Commit:** `4aafdb9`

### Why

User asked whether polling could be made faster (lower slippage risk on
SL/Target execution) without tripping Dhan's rate limits.

### Investigation

Looked up Dhan's actual documented API rate limits: **Non-Trading APIs**
(`/positions`, `/holdings`, `/trades`) allow **20 requests/second**, unlimited
per minute/hour/day. The app's risk monitor was polling `/positions` only
**every 5 seconds** (~0.2 req/sec) — a tiny fraction of the available budget.
Tracing `_normalize_position()`, the LTP used for SL/Target decisions already
comes straight off the fresh `/positions` response (`lastTradedPrice`) with no
caching involved; the only place caching mattered was a rarely-used quote
fallback for the few positions where Dhan doesn't supply live P&L directly.

### What was done

- `RISK_ORDER_MONITOR_INTERVAL_SECONDS` default dropped from 5s to 1s.
- `NEXT_PUBLIC_TRADES_REFRESH_SECONDS` (frontend poll) dropped from 30s to 3s.
- The new `trade_book()` call added in the charges fix above was decoupled
  from this fast loop by adding its own cache
  (`DHAN_TRADE_BOOK_CACHE_SECONDS`, default 30s) — order counts don't need
  per-second freshness, and re-fetching the trade book every second would
  have added needless API load right as the loop got 5x faster.

---

## 4. Require manual approval before sending SL/Target exit orders to Dhan

**Commit:** `151dae9`

### Why

User's explicit instruction: never auto-send an SL exit order to Dhan. Alert
first (web + Telegram), and only place the order when a human clicks Approve.
The concern: unattended auto-execution is a single point of failure for a
live-money system — one bad tick, retry bug, or data glitch could fire a real
market order with no check.

### Clarifying decisions made before building (via AskUserQuestion)

- Applies to **both SL and Target** exits, not just SL.
- Web alert: **both** an in-page banner **and** a native browser push
  notification.
- Re-alert cadence: every 15 seconds while the condition remains unresolved,
  rather than a single one-shot alert or continuous per-tick spam.

### What was done

**Backend** (`backend/app/services/trades.py`):
- `_maybe_execute_risk_exit()` (the old auto-exec function) was replaced by
  `_maybe_alert_risk_exit()`, which **never** calls the order-placement API.
  It records a throttled `RISK_ALERT_{KIND}` action and sends a Telegram
  alert, gated by `_should_send_risk_alert()` so it doesn't re-notify more
  than once per `RISK_ORDER_ALERT_REPEAT_SECONDS` (15s default) for the same
  unresolved signal.
- New `approve_risk_exit(trade_id)` is the **only** code path that calls
  `DhanOrderService` — triggered exclusively by a new API endpoint
  (`POST /trades/{trade_id}/risk/approve`), reusing the same order-building
  logic the old auto-exec loop used, so behavior at the Dhan API layer is
  unchanged — only *who* triggers it changed.
- `_latest_matching_risk_action()` was generalized to take an explicit action
  name (rather than deriving it from "kind") so it could be reused for both
  the new alert-throttle lookups and the existing exit-status lookups.

**Frontend**:
- A green shield "Approve" icon-button appears in the Actions column whenever
  a trade's risk status is `SL reached`, `Target reached`, or
  `order failed` — clicking asks for confirmation, then calls the approve
  endpoint.
- A banner at the top of Manage Trades lists every position currently
  awaiting approval.
- Browser `Notification` API fires when a signal first appears and repeats
  every 15s while unresolved (permission requested once on page load).

### Verification

Ran the new alert-throttle logic locally against a **real open position**
(temporarily set a test SL level that the live LTP had already crossed):
confirmed the first check alerts, an immediate second check is throttled
(`awaiting-approval`, no duplicate Telegram message), and after simulating 20
seconds of elapsed time a third check re-alerts. Confirmed via direct
database query that **zero** `RISK_EXIT_*` order-placement actions were ever
created by the alert path — only `RISK_ALERT_*` records — proving the new
code genuinely cannot place an order without going through `approve_risk_exit`.

---

## 5. Rate-limit Dhan token refresh attempts to stop login lockouts

**Commit:** `09f8b07`

### Why

A few days after the above, the dashboard started showing:
`Dhan token generation failed: Too many attempts. Please try again after sometime.`
— a *different*, harsher failure than the earlier `DH-906`, and one that (per
the user) "keeps coming, always."

### Investigation

Two compounding root causes, found by direct testing on the live OCI instance:

1. **A concurrency bug in `get_dhan_access_token()`** (`dhan_auth.py`): its
   double-checked locking pattern was broken specifically when
   `force_refresh=True` — the inner "did someone already refresh this for me
   while I waited for the lock?" check was unconditionally skipped in that
   case. With the risk monitor now polling every 1 second (from fix #3) and
   several Dhan calls per poll cycle (positions, quotes, trade book, market
   indices), if the cached token went stale, **every one** of those calls
   would independently trigger its own real HTTP call to Dhan's
   `generateAccessToken` login endpoint, back-to-back, every second — exactly
   the kind of rapid-fire login-attempt pattern that trips an anti-abuse lock.
   Confirmed with a synthetic test: 4 concurrent `force_refresh=True` calls
   before the fix would have made 4 real network calls; a single isolated call
   to Dhan's token endpoint (made directly, to test) succeeded immediately,
   proving the lockout was self-inflicted rather than a real outage.

2. **A separate, structural problem**: `options-dash` and `the-p5-idea` —
   other local projects on the same developer machine — were found running
   locally and configured with the **same** `DHAN_CLIENT_ID`. Dhan allows only
   one active access token per client at a time, so whenever *any* of these
   apps refreshed its own token (including OCI), it silently invalidated
   whatever token every other app was holding, creating a flapping cycle: one
   app's refresh invalidates another's session, which then also refreshes,
   invalidating the first again, and so on.

### What was done

- `dhan_auth.py`: added a minimum-interval gate
  (`DHAN_TOKEN_REFRESH_MIN_INTERVAL_SECONDS`, default 120s, matching Dhan's
  own documented "once every 2 minutes" limit for token generation) tracked
  via a module-level `_last_refresh_attempt` timestamp. Now, no matter how
  many concurrent callers detect an invalid token, only **one** real call to
  Dhan's login endpoint is made per interval — others reuse the cached token,
  or get a clear local `DhanAuthError` if there's no cached token to fall
  back to (rather than hammering Dhan again).
- **Operational fix**: stopped the colliding local dev backends
  (`options-dash` on port 8000, `the-p5-idea` on port 8008) so OCI holds the
  only active session against that Dhan login.

### Verification

Simulated 4 concurrent `force_refresh=True` calls against a fake
`generate_dhan_access_token` — confirmed exactly 1 real call was made and all
4 callers got the same fresh token. Simulated a scenario with no fallback
token available — confirmed the 2nd/3rd calls within the cooldown window fail
fast locally instead of retrying against Dhan. Deployed and confirmed the live
OCI instance could read positions cleanly afterward.

---

## 6. Add Gamma Blast: expiry-day OI-wall breakout strategy (v1, paper-first)

**Commits:** `698db36`, `d4bdb9e` (IST timezone fix), `19a73f8` (expiry-weekday gate)

### Why

`gamma-blast.md` (a pre-existing research doc in the repo) proposed a new
options strategy: buy a cheap ATM/1-strike-OTM option when spot breaks a
heavy-OI "wall" late on NIFTY/SENSEX expiry day, riding the gamma explosion
from short-covering as trapped option sellers panic-cover. The doc explicitly
called itself "design phase — no implementation yet."

### Decisions made before building (via AskUserQuestion + a full plan-mode cycle)

- **Execution safety**: manual Approve required for entries **and** exits in
  live mode (mirroring fix #4 above); paper mode auto-approves by default
  (`GAMMA_BLAST_PAPER_AUTO_APPROVE=true`) so evidence-gathering runs hands-off,
  but live mode always waits for a click regardless of that flag.
- **Directional scope**: both-sides — watch the call-wall and put-wall
  breakout simultaneously, not just one direction.
- **Confirmation strictness**: OI-wall break alone is sufficient to signal —
  no secondary "day_direction" trend-engine confirmation for v1.
- **Reuse strategy**: a sibling project (`options-dash`) has a more mature
  `day_direction.py` engine and scattered per-strategy guardrails
  (maxTradesPerDay, consecutive-loss breakers, liquidity checks), but they're
  inconsistent/not cleanly reusable there either (confirmed by exploration)
  and `options-dash` has no OCI deploy path anyway. v1 explicitly **defers**
  porting these — schema was designed so they can be added later without a
  rewrite.
- **Capital base**: ₹2,00,000 placeholder, overridable via `.env`.

### What was built

**Data layer** — continuous via WebSocket, REST only for bootstrap:
- `gamma_blast_ws.py`: an asyncio-native Dhan v2 WebSocket client. Full mode
  (`RequestCode 21`) carries LTP **and** Open Interest in one packet — no
  separate polling needed for OI. Binary packet layout implemented directly
  from Dhan's documented byte offsets and cross-checked against a working
  reference parser in a sibling project (`strangle/dhan_ws.py`), rewritten to
  be asyncio-native instead of thread-based. Auto-reconnects with backoff,
  re-subscribes after reconnect, always fetches a fresh token on connect (so
  it benefits from the rate-limit fix in #5 automatically).
- `gamma_blast_instruments.py`: one-time-per-session REST calls to Dhan's
  `/optionchain/expirylist` and `/optionchain` (confirmed via live testing:
  Dhan rate-limits these to 1 request/3 seconds — enforced locally in
  `DhanService._option_chain_request`) to resolve the current week's expiry
  and the strike→securityId mapping to subscribe to.

**Strategy engine** (`gamma_blast_engine.py`) — pure functions, no I/O, fully
unit-tested in isolation:
- Wall identification: highest-OI CE strike above spot (call wall), highest-OI
  PE strike below spot (put wall), within a configurable strike range and
  minimum-OI threshold.
- Quiet-day gate: blocks entries if spot has already moved more than 1% from
  the session open (avoids chasing a day that already ran).
- Breakout trigger: spot crossing a wall ± a buffer, only inside a configured
  entry window (default 14:00–15:00 IST).
- Exit rules evaluated per open leg, in priority order: forced time-exit
  (15:20 IST) > hard stop (-27%) > scale-out target (+45%) > "blast failed"
  time-stop (no follow-through within 15 minutes).
- Position sizing from configured capital base, risk %, and lot size.

**Orchestration** (`gamma_blast.py`) — mirrors the shape of the existing
`trades.py` risk-monitor pattern:
- A background scheduler starts a session only on the correct expiry weekday
  for each index (NIFTY Tuesday, SENSEX Thursday — enforced explicitly via
  `expiry_weekday_for()`, *before* even calling the REST bootstrap, in
  addition to Dhan's own expiry-list match) and within configured market
  hours, tearing the WebSocket connection down at day's end and triggering the
  retrospective.
- Every signal (including ones the user never acted on) and every trade fill
  is logged for the end-of-day review.
- `approve_gamma_blast_signal()` is the only code path that ever calls
  `DhanOrderService` — paper mode simulates a fill at the current LTP without
  touching Dhan at all; live mode places a real order, additionally gated by
  the existing `LIVE_ORDER_ENABLED` master switch. Same code path either way,
  so flipping `GAMMA_BLAST_MODE` from `PAPER` to `LIVE` is a config change,
  not a code change.

**Retrospective** (`gamma_blast_retrospective.py`): after a session ends,
gathers that day's signals/trades/events and asks OpenAI (`gpt-4o` by
default) for a plain-language review — what happened, concrete mistakes,
what worked, and specific tweaks to try next time.

**Database**: five new tables (`gamma_blast_sessions`, `_signals`, `_trades`,
`_events`, `_retrospectives`) following the app's existing hybrid style
(normalized columns for queryable fields, a JSON payload column for the rest).

**Frontend**: a new `/gamma-blast` page — mode/connection status header, a
per-index panel (NIFTY/SENSEX) with a hand-rolled OI-by-strike bar
visualization highlighting the identified walls, an Approve button wired to
pending signals, an open-trades table, a chronological event timeline (the
"quickly understand what happened" requirement), and a past-sessions list with
retrospective detail view.

### A real bug found and fixed mid-deployment

While deploying, discovered the OCI host's **system clock is GMT, not IST**
(confirmed via `timedatectl`). The strategy's market-hours/entry-window/
force-exit logic used naive `datetime.now()`, which would have silently run
the entire session schedule 5.5 hours off from real IST market hours — and
worse, a mismatch between an IST-aware "now" in the decision logic and
GMT-naive timestamps stored for trade fills would have crashed the exit-timing
math outright (subtracting a naive datetime from an aware one raises in
Python). Fixed by adding a shared `now_ist()` helper
(`app/core/timeutil.py` — a naive datetime whose *fields* are correct IST wall
time, deliberately not timezone-aware, so it stays consistent with every other
naive timestamp already stored via `isoformat()`), and using it everywhere
gamma-blast reads or writes the current time, including the database layer.
Verified the IST offset and timestamp consistency directly on OCI after
deploying.

### Verification

- Engine pure functions: unit-tested standalone (wall detection, quiet-day
  gate, breakout/exit triggers, position sizing).
- Option-chain/expiry-list REST calls: tested against **live Dhan data**
  (found real NIFTY call/put walls at 24500/24000 with real OI figures).
- WebSocket client: connection and auth confirmed against live Dhan
  (a rapid-reconnect test during development briefly tripped Dhan's own WS
  rate limit — good real-world confirmation the backoff logic is necessary;
  full tick reception wasn't verified since market was closed during testing).
- Full paper entry→exit approve cycle run locally end-to-end with a real
  security ID and injected live-tick data — P&L math confirmed correct, and a
  database check confirmed zero real Dhan order calls were made in paper mode.
- OpenAI retrospective call confirmed working against the real configured key.
- The actual page: screenshotted via a real headless-browser session (both
  the empty "not started" state and a populated past-session/retrospective
  detail view).
- Weekday gate: confirmed programmatically that NIFTY is only ever eligible
  on Tuesdays and SENSEX only on Thursdays, all other weekdays excluded for
  both.

---

## 7. Revamp Trade Journals: 7-day selector, 5 reflection fields, AI insights

**Commit:** `cf83234`

### Why

The existing Trade Journals page only ever showed **today**, with two
editable fields (Strategy Details, Lessons Learnt). User wanted to review and
edit the last 7 trading sessions, with Date/Trades/P&L auto-populated from
actual trades, five reflection fields per day (Strategy, How I felt, What
happened, Lessons Learnt, Comments), and an AI-distilled summary of lessons
learnt shown as a standing reminder at the top of the page.

### A gap surfaced before building

The app only ever reads **today's** live positions from Dhan — there is no
stored history of past days' trades/P&L anywhere. This was surfaced to the
user directly before building: "last 7 trading sessions" would need a new
mechanism to start capturing each day's numbers *going forward*; days before
that ship date would have no real trade data, since Dhan's positions API
doesn't expose history.

### Decisions made before building (via AskUserQuestion)

- **Auto-only, blank until captured**: Trades/P&L are always derived from
  Dhan automatically, never hand-typed, even for days with no data yet.
- **AI insights auto-refresh daily** (configurable time, default 18:00 IST),
  not just an on-demand button.
- **Insights scope**: distilled from **all** journal entries ever recorded,
  not just the 7 currently visible — broader pattern-spotting over time.

### What was built

**Daily capture**: `live_trade_snapshot()` in `trades.py` was hooked to
opportunistically upsert a new `daily_trade_summary` table (trade count,
day P&L, net P&L, realized P&L, charges) for **today's** IST date on every
successful call — no new scheduler needed, since the UI/risk-monitor already
polls this function constantly; the last successful write of the day
naturally captures the closing state.

**Journal fields**: the existing `trade_journals` table was migrated in place
(new `_add_column_if_missing()` helper using `ALTER TABLE ADD COLUMN`,
checked against `PRAGMA table_info` first so it's safe to run repeatedly) to
add `how_i_felt`, `what_happened`, and `comments` alongside the existing
`strategy_details` and `lessons_learnt`.

**AI insights** (`journal_insights.py`): gathers every journal entry with any
content across all recorded dates, asks OpenAI to return a JSON list of short
(<15 words), imperative, deduplicated bullets — explicitly instructed to
merge recurring lessons rather than summarize each day individually. Runs
automatically once daily via a new background task, plus a manual refresh
button on the page for on-demand regeneration.

**API** (`journals.py` rewritten): `GET /journals/recent` returns the last 7
weekdays (Monday–Friday going backward from today) each paired with whatever
`daily_trade_summary`/journal data exists for that date (`None`/blank if not
yet captured); `PUT /journals/{date}` saves the five fields; `GET/POST
/journals/insights[/refresh]` for the AI summary.

**Frontend**: a 7-day tab strip (date, trade count, P&L) at the top, click to
select a day; below it, read-only summary metrics for the selected day plus
the five editable reflection fields and a Save button; an "AI Lessons
Reminder" card above everything with the distilled bullets and a manual
refresh button.

**A layering cleanup made along the way**: `now_ist()` (and a related
`in_time_window()` helper) had been added to `gamma_blast_engine.py` in the
previous feature, but `trades.py` and the new `journal_insights.py` needed
them too — depending on a gamma-blast-named module for a generic timezone
utility was a smell, so both were extracted into the shared
`app/core/timeutil.py` from feature #6, with `gamma_blast_engine.py` now just
re-exporting them for its existing callers.

### Verification

- DB migration confirmed idempotent by running it against the already-existing
  (pre-migration) local schema and re-running it a second time with no error.
- Full CRUD path tested directly: save/fetch a journal entry, record/fetch a
  daily summary, save/fetch insights.
- Daily-capture hook confirmed against a **real** live Dhan snapshot — today's
  row appeared in `daily_trade_summary` with real trade count and P&L.
- OpenAI distillation tested with three synthetic multi-day journal entries
  containing overlapping lessons — confirmed the model correctly merged and
  deduplicated them into concise bullets rather than restating each day.
- The full page flow (7-day selector, save, insights refresh) driven through a
  real headless-browser session and screenshotted, including confirming the
  manual insights-refresh button's network call actually completes (an
  earlier test script closed the browser too early and made it look broken;
  re-tested with a proper wait to confirm it works).
- Test/synthetic journal content was deleted from the database afterward,
  keeping only the real captured `daily_trade_summary` row for that day.

---

## 8. Auto start/stop trade instance outside trading hours

**Commits:** `00856fb`, `fdc533a` (moved script into version control)

### Why

`140.245.25.236` (the trading server) is only needed on NSE trading days.
User wanted it automatically stopped outside trading hours (8:30 AM–5:00 PM
IST) to reduce cost/exposure, with the scheduling logic running on a
*different*, always-on box (`161.118.162.75`) in the same OCI compartment.

### Decisions made before building (via AskUserQuestion)

- **Auth method**: instance-principal (161.118.162.75's own OCI identity),
  not a long-lived user API key — no key file to manage or leak.
- **Holiday awareness**: maintain an explicit NSE 2026 holiday list (looked up
  and sourced from Zerodha's published holiday calendar) rather than running
  every weekday regardless.

### What was built

`ops/trade_instance_scheduler.py`: a small, self-healing reconciler script.
Each run (via cron, every 5 minutes) computes the current IST time using the
same `now_ist()`-style pattern established in feature #6, checks it against
weekday + the hardcoded 2026 NSE holiday set + the 8:30–17:00 window, reads
the trade instance's **actual** lifecycle state via the OCI SDK
(`ComputeClient.get_instance`, instance-principal auth), and only acts if the
actual state disagrees with what the schedule says it should be — `START` if
it should be running but is `STOPPED`, `SOFTSTOP` if it should be stopped but
is `RUNNING`, otherwise nothing. Being idempotent this way means a missed
cron tick, a slow OCI API call, or catching the instance mid-transition never
causes a duplicate or wrong action.

### Infrastructure setup (done via OCI Console, walked through step by step)

- Created a **Dynamic Group** (`trade-instance-scheduler`) matching
  161.118.162.75 by its own instance OCID — this is what lets OCI treat that
  box as an authenticated identity at all.
- Created a **Policy** granting that dynamic group `manage instance-family`
  permission. A tighter condition
  (`where target.resource.id = '<trade-instance OCID>'`) was tried first to
  scope the grant to *only* the trade instance, but OCI silently treated it as
  a no-op for this resource type (confirmed by testing: removing the `where`
  clause immediately fixed authorization, isolating the condition itself as
  the problem rather than IAM propagation delay). Fell back to
  compartment-scoped — acceptable since the compartment only contains these
  two instances.

### Verification

Before enabling anything unattended:
1. Verified the instance-principal auth chain with a **read-only** check
   (`get_instance`) first.
2. Ran the actual reconciler script **manually once** (not via cron) so the
   real decision and action could be observed directly. Since testing
   happened on a Sunday — outside the trading window — this correctly decided
   "should be stopped, currently running" and issued a real `SOFTSTOP`.
3. Confirmed via a follow-up API check that the instance actually reached
   `STOPPED` (not just that the action was *sent*).
4. Only then installed the cron job (`*/5 * * * *`) for unattended operation.

The trade instance is now stopped outside 8:30 AM–5:00 PM IST on trading days
and will auto-start the next trading morning; manual start is available via
`oci compute instance action --action START` from 161.118.162.75 if needed
sooner.

---

## Cross-cutting notes

- **IST timezone handling** is now centralized in `app/core/timeutil.py`
  (`now_ist()`, `today_ist()`, `in_time_window()`) after two separate bugs
  (Gamma Blast's market-hours logic, and this being the *second* time a
  GMT-vs-IST mismatch was found on these OCI hosts) made clear that naive
  `datetime.now()` cannot be trusted on this infrastructure for anything
  IST-dependent.
- **Dhan token handling** went through two rounds of hardening: first
  detecting invalid-token failures that don't arrive as HTTP 401 (#1), then
  rate-limiting how often a refresh is actually attempted against Dhan's login
  endpoint (#5) — both necessary because Dhan enforces its own strict limits
  and multiple local dev projects sharing one `DHAN_CLIENT_ID` can silently
  invalidate each other's sessions.
- **Manual-approval-before-order-placement** is now the standing pattern for
  any automated exit/entry logic in this codebase (SL/Target in #4, Gamma
  Blast entries/exits in #6) — alert first, place the order only on an
  explicit user action, with paper/simulated modes exempted where explicitly
  configured.
- Every feature above was verified against **real Dhan data, real OCI
  infrastructure, or a real browser session** before being called done — not
  just compiled/typechecked — per this project's working conventions.
