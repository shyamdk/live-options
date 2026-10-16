# Calm Strangle — intraday NIFTY short strangle sold only when the market has settled

Idea (notes.txt): sell an intraday NIFTY strangle once the market opens and settles at a level,
step aside when it moves, and sell again when it settles at the next level. Built and tuned on
6 months of real 1-min NIFTY option data (Dhan expired-options API), 12 Oct 2026. Paper first.

## Rules

| Topic | Rule |
|---|---|
| Days | Every trading day **except expiry day** (expiry-day versions lost in every test). Nearest weekly expiry. |
| Opening range | No entries before **09:45**; entries until **14:30**. |
| "Settled" | NIFTY's high–low of the **last 15 one-minute closes ≤ 15% of the ATM straddle** (CE + PE at the strike nearest spot — the move the market still expects today). |
| Strikes | CE at the first strike ≥ spot + **1.0 × straddle**, PE at the first strike ≤ spot − 1.0 × straddle. Credit must be ≥ 6 pts. |
| Exit — move | NIFTY moves **0.6 × straddle** (the straddle at entry) away from the entry spot, either way. |
| Exit — backstop | Combined premium **+150%** over the credit. |
| Exit — time | Flat at **15:15**. **No profit target** (fixed targets reduced results — the decay is held). |
| Exit — early profit | At entry, the strangle's value at 15:15 if NIFTY stays put is computed (Black-Scholes, each leg's implied vol at entry). If the premium falls to it earlier, **book it and take no more entries that day** (setting; on by default). |
| Re-entry | After a stop, sell again only when the 15-min calm test passes again. Max **3 entries / 2 stops** a day. |
| Size | **5 lots** (325) per leg. |
| Fills | Paper: sell at bid, buy at ask (LTP if no quote), Dhan charge model. Live (later) behind `CALM_STRANGLE_LIVE_ORDER_ENABLED` + page mode; needs near-mid fills. |
| Alerts | Telegram on every entry and exit. |

## Backtest (1 Apr – 7 Oct 2026, 129 days, 5 lots, charges included)

| Slippage / leg / fill | Apr–Jul (tuned) | Aug–Oct (check) | Full | Max DD |
|---|---|---|---|---|
| 0.1 | +₹82,768 | +₹47,865 | +₹1,30,633 | −₹18,265 |
| **0.25** | **+₹67,948** | **+₹39,480** | **+₹1,07,428** | **−₹20,037** |
| 0.5 | +₹43,248 | +₹25,505 | +₹68,753 | −₹27,837 |
| 1.0 | −₹6,152 | −₹2,445 | −₹8,597 | −₹43,437 |

At 0.25 slippage: 119 trades, 71% winners, 71/129 winning days, worst day −₹15.6k, 5 of 7 months
up. Caveats: execution cost decides it (loses at 1 pt/leg); expiry-day skip and the 15:15 exit were
chosen with the Aug–Oct period visible, so forward paper results are the real test; backtest stops
are on 1-min closes, the live monitor checks every few seconds.

### Early-profit exit (added 14 Oct 2026)

| 0.25 pt slippage | Hold to 15:15 | Early exit, then done for the day | Early exit, re-enter when calm |
|---|---|---|---|
| Full net | ₹1,07,428 | ₹92,564 | ₹78,750 |
| Max DD | −₹20,037 | **−₹11,691** | −₹22,738 |
| Worst day | −₹15,558 | **−₹10,243** | −₹15,686 |
| Win % / stops | 71% / 23 | **86% / 12** | 84% / 17 |
| Aug–Oct | +₹39,480 | +₹17,096 | −₹257 |

Adopted: early exit then done for the day — ~14% less profit for roughly half the drawdown and worst day.

### Europe-open guard (optional, added 14 Oct 2026)

9 of 13 stop-outs in the backtest happened 12:00–13:30 (European open). Re-entering for a second
trade was flat-to-negative in Aug–Oct in every variant (drawdown ~2x), so the rule stays one trade a
day. Optional guard: if the trade is still open at **12:15** and in profit, book it, then no more
entries that day. Off by default.

| 0.25 pt slippage | Current | With 12:15 guard |
|---|---|---|
| Full net | ₹92,564 | ₹70,828 |
| Aug–Oct | +₹17,096 | +₹5,569 |
| Max DD | −₹11,691 | **−₹7,144** |
| Worst day | −₹10,243 | **−₹6,648** |
