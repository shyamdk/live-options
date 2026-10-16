# NIFTY Adaptive Daily Options Strategy
## 30-Minutes-Before-Close Decision Engine

### Purpose

This document consolidates the three strategy families developed for NIFTY:

1. **NIFTY Full Butterfly** — when a large move is expected but direction is uncertain.
2. **CE Butterfly** — when a large move is expected and the directional bias is UP.
3. **PE Butterfly** — when a large move is expected and the directional bias is DOWN.
4. **Neutral / No-Trade** — when a large move is not expected. A defined-risk short strangle/iron-condor style structure may be considered only when the range and risk conditions support it; otherwise avoid the trade.

The page should make this decision automatically, normally **30 minutes before the market closes**, and then show the selected structure, strikes relative to spot, payoff chart, validity checks and LLM explanation.

For the three big-move strategies (CE Butterfly, PE Butterfly, Full Butterfly), the user can **manually override the direction** before the decision is finalised — see Section 11A.

### Scope — current phase

- **Recommendation only.** The page produces the daily decision, strikes, payoff, validity checks and LLM explanation. It does **not** place orders or paper trades.
- **Entry and exit are manual.** The user decides whether to take the recommended trade, places it themselves, and manages the exit themselves. Exit rules (profit target, stop loss, hold-to-expiry, daily re-check) are therefore out of scope for now.
- **Future phase: automation.** Automated entry/exit (paper first, then live) will be added later and will need exit rules, position sizing and an account risk limit defined at that point.
- Each day's recommendation (engine inputs, engine direction, any manual override, selected strategy, strikes, validity result) should still be **stored**, so the decision tree can be reviewed and backtested before automation.

---

# 1. Daily Decision Tree

```text
                    30 MINUTES BEFORE CLOSE
                              |
                              v
                 ┌────────────────────────┐
                 │ Is a LARGE MOVE likely?│
                 └────────────┬───────────┘
                              |
                   ┌──────────┴──────────┐
                   |                     |
                  YES                    NO
                   |                     |
                   v                     v
          ┌─────────────────┐      RANGE / LOW MOVE
          │ Direction clear?│             |
          │ (+ manual       │             |
          │   override)     │             |
          └───────┬─────────┘             v
              ┌───┴───┐          ┌──────────────────┐
             UP      DOWN         │ Neutral strategy │
              |         |          │ or NO TRADE      │
              v         v          └──────────────────┘
        CE BUTTERFLY PE BUTTERFLY

                   If BIG MOVE + NO CLEAR DIRECTION
                              |
                              v
                       FULL BUTTERFLY
```

### Priority order

1. **Risk / data validity**
2. **Big-move classification**
3. **Directional classification**
4. **Manual direction override** (big-move only, optional)
5. **Strategy selection**
6. **Strike generation**
7. **Payoff and risk validation**
8. **LLM explanation**
9. **Recommendation output (trade / no-trade)** — manual execution in the current phase

The LLM should explain the decision; the deterministic engine should make the strategy classification and enforce risk gates.

---

# 2. Step 0 — Data Snapshot at T-30

At approximately 30 minutes before the market close, capture a single consistent snapshot.

## Required market data

- NIFTY spot
- Current option chain
- Bid / ask / LTP
- IV
- Delta
- Gamma
- Theta
- Vega
- Open interest
- Change in OI
- Volume
- Available expiries
- India VIX / volatility proxy if available
- Recent NIFTY OHLC data
- ATR / realized volatility
- Market trend indicators
- PCR
- Major scheduled events
- Global-market / overnight cues if available

The option chain provides strike, premium, bid/ask, volume, OI and IV inputs that can be used to construct the strategy. citeturn0search0turn0search1

---

# 3. Expiry Selection

The application should select the expiry based on the holding horizon rather than blindly using the nearest contract.

### Default rule

- If the nearest expiry has **0 or 1 trading day remaining**, use the **next available expiry**.
- Otherwise use the nearest expiry satisfying the configured DTE range.
- All legs within a strategy must use the same expiry.

For NIFTY, the current NSE contract specification provides weekly expiries and states that weekly contracts expire on Tuesday, subject to the holiday rule. Strike intervals are ₹50. The page should read the live contract specification rather than hard-code expiry dates. citeturn0search0

### Starting DTE configuration

```yaml
min_dte: 2
max_dte: 12
avoid_dte_0: true
avoid_dte_1: true
```

This is a research configuration and should be optimized using backtesting.

---

# 4. Step 1 — Is a Large Move Expected?

This is the first major branch.

Do not rely on a single indicator.

Create a **Move Score** from several independent signals.

## 4.1 Event score

Look for events during the intended holding period:

- Fed / FOMC decisions
- RBI policy
- US CPI / jobs data
- India CPI / GDP
- Union Budget
- Major geopolitical events
- Major global risk events
- Other scheduled events known to affect index volatility

### Starting score

| Event | Score |
|---|---:|
| No major event | 0 |
| Moderate event | +1 |
| Major event | +2 |
| Very high-impact event | +3 |

---

# 5. Expected Move

A simple option-market estimate is:

```text
Expected Move ≈ ATM CE Premium + ATM PE Premium
```

This is a useful distance estimate, not a guaranteed range or barrier. citeturn0search1turn0search2

Calculate the expected move for the selected expiry.

For an overnight / next-session decision, also calculate a **session-adjusted expected move** using IV and time remaining.

---

# 6. Expected Move vs Recent Realized Move

Calculate:

```text
EM/ATR Ratio = Expected Move / ATR(14)
```

Starting classification:

| EM / ATR | Interpretation |
|---:|---|
| < 0.90 | Low expected movement |
| 0.90–1.20 | Normal |
| 1.20–1.50 | Elevated |
| > 1.50 | Very elevated |

These are starting research thresholds.

**Implementation note:** the ATM straddle covers the whole period to expiry while ATR14 is a one-day range, so the engine compares like with like: `EM/ATR = (straddle / √trading days to expiry) / ATR14`. Comparing the raw straddle to ATR14 would score "very elevated" almost every day.

**Implementation note (pricing):** theoretical "today" P&L and fallback deltas are priced off the forward implied by ATM put-call parity (F = K + C − P), not bare spot, because Dhan's IVs are quoted against the forward; pricing off spot with r = 0 misprices calls high and puts low.

**Implementation note (events):** if the event calendar is unavailable the event score counts as 0 and the page shows a data warning, rather than forcing NO TRADE (Section 17), so a calendar outage does not blank the page.

---

# 7. IV Expansion

Calculate:

```text
IV Change = Current ATM IV - Previous Snapshot ATM IV
```

and:

```text
IV Percentile / Rank
```

A sudden increase in IV can indicate that the options market is pricing more movement.

Use this as a supporting signal rather than an automatic trade trigger.

---

# 8. Realized Volatility / Range Expansion

Track:

- Today's range vs recent average range
- ATR
- 5-day realized volatility
- 20-day realized volatility
- Intraday range expansion
- Trend strength

Example:

```text
Range Expansion =
Today's intraday range / Average 10-day daily range
```

---

# 9. Big-Move Classification

Create:

```text
MOVE_SCORE =
    Event Score
  + Expected Move Score
  + IV Expansion Score
  + Realized Volatility Score
  + Range Expansion Score
```

### Starting classification

```text
MOVE_SCORE >= 6       → BIG MOVE
MOVE_SCORE 4–5        → ELEVATED / WATCH
MOVE_SCORE <= 3       → LOW / NORMAL
```

The exact thresholds should be calibrated using historical data.

### Component scoring (starting values)

Event Score uses the Section 4.1 table (0–3). Each remaining component scores **0–2**:

| Component | 0 | 1 | 2 |
|---|---|---|---|
| Expected Move Score (EM / ATR14) | < 0.90 | 0.90–1.20 | > 1.20 |
| IV Expansion Score (ATM IV change vs previous snapshot, or VIX change) | ≤ 0 | small rise | sharp rise / IV rank > 70 |
| Realized Volatility Score (5-day RV / 20-day RV) | < 0.9 | 0.9–1.2 | > 1.2 |
| Range Expansion Score (today's range / 10-day avg range) | < 0.9 | 0.9–1.3 | > 1.3 |

Maximum MOVE_SCORE = 11. All cut-offs are configurable research parameters.

### ELEVATED / WATCH band (score 4–5)

Do not force a strategy and do not silently return No Trade. Generate candidates for **all** big-move structures and the neutral structure (Section 18A), let the AI rank them, and show the best options clearly labelled **WATCH — not a confirmed big-move setup**.

---

# 10. Step 2 — Determine Direction

Only determine direction strongly when the evidence is sufficiently aligned.

Create a **Directional Score**.

## Bullish inputs

Examples:

- Price above short/medium moving averages
- Positive momentum
- Positive trend structure
- ADX confirms trend
- Call-side positioning not strongly restrictive
- Put-side positioning supports downside
- Positive overnight/global cues
- Existing directional model = bullish

## Bearish inputs

Mirror the above:

- Price below moving averages
- Negative momentum
- Negative trend structure
- ADX confirms trend
- Put-side positioning / skew indicates downside risk
- Weak global cues
- Existing directional model = bearish

---

# 11. Directional Confidence

Example:

```text
Bullish signals = 7
Bearish signals = 2
Neutral = 1
```

Then:

```text
Bullish confidence = 70%
Bearish confidence = 20%
```

### Starting rule

```text
Bullish confidence >= 65% → UP
Bearish confidence >= 65% → DOWN
Neither >= 65%            → NO CLEAR DIRECTION
```

Do not force a directional decision when evidence is mixed.

---

# 11A. Step 2B — Manual Direction Override

After the engine classifies direction, the user can override it. This step applies **only when the move classification is BIG MOVE**, i.e. only to the three big-move strategies.

### Override options

| Override | Effective direction | Strategy selected |
|---|---|---|
| AUTO (default) | Engine's classification | Per Section 12 |
| UP | UP | CE Butterfly |
| DOWN | DOWN | PE Butterfly |
| NO DIRECTION | NO CLEAR DIRECTION | Full Butterfly |

### Rules

- The override changes **direction only**. It cannot turn a LOW / NORMAL or ELEVATED / WATCH move into a big move, and it is not available for the Neutral / No-Trade branch.
- Strategy selection, strike generation, payoff and validity checks all run on the **effective direction** (override if set, otherwise the engine's).
- The override **never bypasses hard gates**: if the overridden strategy fails validity, the result is still **NO TRADE**.
- Changing the override re-runs selection → strikes → payoff → validity → LLM immediately.
- The override is per trading day: it resets to AUTO for the next day's decision.
- Always record and display both values, e.g. `Direction: UP (manual override; engine: NO CLEAR DIRECTION, 42% / 39%)`, so overridden decisions can be compared with the engine's in backtest/review.
- The LLM receives both the engine direction and the override, and should call out when the override contradicts the engine's evidence.

---

# 12. Final Strategy Selection

Cases A–C use the **effective direction** (the manual override from Section 11A if set, otherwise the engine's classification).

## CASE A — Big move + bullish

### Select:

# CE BUTTERFLY

Structure:

```text
BUY CE ×1
SELL CE ×2
BUY farther CE ×1
```

---

## CASE B — Big move + bearish

### Select:

# PE BUTTERFLY

Structure:

```text
BUY PE ×1
SELL PE ×2
BUY farther PE ×1
```

---

## CASE C — Big move + no clear direction

### Select:

# NIFTY FULL BUTTERFLY

Structure:

```text
PUT:
BUY PE ×1
SELL PE ×2
BUY farther PE ×1

CALL:
BUY CE ×1
SELL CE ×2
BUY farther CE ×1
```

This is the six-leg Full Butterfly structure from the supplied screenshot.

---

## CASE D — No big move + range expected

### Neutral strategy

Prefer a **defined-risk short strangle / iron-condor-style structure** for automation rather than an uncovered short strangle.

A naked short strangle has theoretically unlimited loss. If the application uses the word "strangle", the UI should clearly distinguish:

- **Long strangle** — buying both wings, designed for a large move.
- **Short strangle** — selling both sides, benefits from limited movement but has uncapped risk.
- **Defined-risk short strangle / iron condor** — adds protective long options.

A range strategy should only be enabled when the risk engine confirms that the expected range and premium justify it.

If those conditions do not pass:

# AVOID TRADE

---

# 13. Strategy 1 — CE Butterfly

## Structure

```text
BUY  CE  near spot
SELL CE  farther OTM ×2
BUY  CE  still farther OTM
```

### Starting relative-to-spot geometry

Use delta as the primary selector.

| Leg | Starting delta | Relative location |
|---|---:|---|
| Near long CE | 0.55–0.65 | Near ATM / slightly OTM |
| Short CE | 0.20–0.30 | Above spot |
| Far hedge CE | 0.05–0.15 | Farther above spot |

### Wing geometry

```text
Inner Wing =
Short CE Strike - Near Long CE Strike

Outer Wing =
Far CE Strike - Short CE Strike

Wing Ratio =
Outer Wing / Inner Wing
```

Starting:

```text
Wing Ratio = 0.60–0.80
Preferred ≈ 0.67–0.75
```

### Example from supplied strategy

Spot ≈ 23,140.5

```text
BUY  23,300 CE   → +160.5
SELL 24,100 CE   → +959.5
BUY  24,700 CE   → +1,559.5
```

The actual application should generate these strikes dynamically rather than copy the example.

---

# 14. Strategy 2 — PE Butterfly

## Structure

```text
BUY  PE  near spot
SELL PE  farther OTM ×2
BUY  PE  still farther OTM
```

### Starting relative-to-spot geometry

| Leg | Starting absolute delta | Relative location |
|---|---:|---|
| Near long PE | 0.55–0.65 | Near ATM / slightly OTM |
| Short PE | 0.20–0.30 | Below spot |
| Far hedge PE | 0.05–0.15 | Farther below spot |

### Example

Spot ≈ 23,140.5

```text
BUY  23,000 PE   → -140.5
SELL 22,200 PE   → -940.5
BUY  21,600 PE   → -1,540.5
```

Again, these are example relative positions, not fixed strikes.

---

# 15. Strategy 3 — Full Butterfly

## Structure

```text
PUT SIDE
+1 PE near spot
-2 PE farther below
+1 PE far below

CALL SIDE
+1 CE near spot
-2 CE farther above
+1 CE far above
```

### Starting geometry

Both sides should initially be approximately symmetric.

Example:

```text
SPOT = 23,140

PE:
+23,100  (-40)
-22,200  (-940)
+21,600  (-1,540)

CE:
+23,200  (+60)
-24,100  (+960)
+24,700  (+1,560)
```

The primary selector remains delta and wing ratio; relative point distances are displayed to make the structure understandable.

### Key metric

```text
Central Loss Width =
Upper Central Breakeven - Lower Central Breakeven
```

Then:

```text
Loss Width / Expected Move
```

Starting target:

```text
<= 0.75
```

**This is a soft ranking metric, not a hard gate.** The supplied example itself has a loss width of ~787 points against an ATM-straddle expected move of ~400 (ratio ≈ 2.0), so a hard 0.75 cut-off would reject almost every candidate. The ratio is shown on every Full Butterfly candidate and used by the AI ranking (Section 18A); lower is better.

---

# 16. Strategy 4 — Neutral / Strangle

If the market is expected to remain within a range, a neutral premium-selling structure may be considered.

For automation, prefer:

```text
SELL OTM PE
BUY farther OTM PE

SELL OTM CE
BUY farther OTM CE
```

This is effectively a defined-risk short-strangle / iron-condor-style implementation.

### Strike selection

Start with:

```text
Short PE delta: 0.15–0.25
Short CE delta: 0.15–0.25

Long hedge delta: 0.05–0.10
```

Place the short strikes outside the expected move.

Example:

```text
Expected Move = ±350

Spot = 23,140

Short PE ≈ 22,790 or lower
Short CE ≈ 23,490 or higher
```

Then choose protective long strikes farther away.

These are examples only; the engine should use the actual chain and deltas.

---

# 17. Avoid-Trade Conditions

Regardless of the classification, return:

# NO TRADE

if:

- Option chain is stale
- Bid/ask spreads are too wide
- Required strikes have poor liquidity
- Maximum loss exceeds account risk limit
- Payoff cannot be constructed reliably
- Event information is incomplete
- Direction is ambiguous when a directional strategy requires confidence
- Expected move and payoff geometry produce poor risk/reward
- Candidate requires unrealistic movement
- IV/skew makes the structure inefficient
- Data quality fails

---

# 18. Common Validity Engine

Every candidate goes through the same checks, split into **hard gates** (deterministic, a failure removes the candidate) and **soft checks** (reported as PASS / WATCH and used for ranking, never to remove a candidate on their own).

### Hard gates — deterministic, never overridden by the AI

1. Correct expiry (all legs same expiry, within DTE range)
2. Correct option type
3. Correct quantity ratio
4. Defined risk
5. All legs liquid (bid/ask spread and volume/OI within limits)
6. Maximum loss within the configured capital limit
7. No stale quotes
8. Payoff can be constructed reliably

### Soft checks — PASS / WATCH, fed into the AI ranking

1. Reward/risk
2. Reasonable breakevens
3. Expected-move alignment
4. Delta bands (Sections 13–16)
5. Wing ratio (0.60–0.80)
6. Full Butterfly central loss width / expected move
7. IV / skew efficiency

### Strategy-specific

- CE butterfly → CE delta / wing checks
- PE butterfly → PE delta / wing checks
- Full Butterfly → both-side symmetry + central loss-zone check
- Neutral → short strikes outside expected move + defined tail risk

---

# 18A. Candidate Generation and AI Ranking

Instead of committing to one fixed strike geometry, the engine generates **several candidates** per applicable structure, removes any that fail a hard gate, and the AI ranks the survivors. The page shows the **best options**, not a single hard-coded answer.

### 1. Generate candidates (deterministic)

For each applicable structure (by effective direction; all structures in the WATCH band), build variants from the live chain, for example:

| Variant | Near long leg | Short leg (×2) | Far hedge |
|---|---|---|---|
| Delta-based (spec default) | Δ 0.55–0.65 | Δ 0.20–0.30 | Δ 0.05–0.15 |
| Moderate | Δ ≈ 0.45–0.50 | Δ ≈ 0.10–0.20 | wing ratio 0.60–0.80 |
| Wide / cheap-debit (supplied screenshots) | Δ ≈ 0.35–0.45, near ATM | ≈ 1–1.5× expected move beyond spot | wing ratio 0.60–0.80 |

Also vary the expiry across valid DTEs (Section 3). Aim for roughly 3–10 candidates per structure; every leg on a candidate uses the same expiry.

### 2. Compute metrics (deterministic)

For every candidate: net debit/credit, max profit, max loss, reward/risk, breakevens, distance of each leg from spot (points and %), expected-move alignment, wing ratio, loss width / EM (Full Butterfly), net Greeks, total charges, and PASS / WATCH / FAIL on every check in Section 18.

### 3. Remove hard-gate failures (deterministic)

Any candidate failing a hard gate is dropped (kept in the log with the reason). If **no** candidate survives, the output is **NO TRADE**.

### 4. AI ranking

Send the AI the market snapshot, move and direction assessment (including any manual override) and the surviving candidates with all their metrics. The AI:

- ranks the candidates and picks a **best** option plus up to two **alternatives**;
- explains each pick in the context of the market view (Section 24);
- flags WATCH items and trade-offs (e.g. "higher max profit but needs a 4% move").

The AI may only choose among candidates the engine supplied. It cannot invent strikes, change quantities or revive a hard-gate failure. Its output is validated: any pick that is not in the supplied list is discarded.

### 5. Fallback

If the AI is unavailable or its answer fails validation, rank by a deterministic score (reward/risk, expected-move alignment, fewest WATCH items) and say on the page that the ranking was not AI-generated.

### 6. Display

Show the top 3 candidates side by side: rank, structure, legs (absolute and relative-to-spot), debit/credit, max profit / max loss, breakevens, WATCH items, and the AI's one-line reason. The best candidate gets the full payoff chart and validity panel; the others can be expanded.

---

# 19. Relative-to-Spot Strike Model

The page should display both:

### Absolute strike

```text
23,200 CE
```

and:

### Relative distance

```text
+60 points from spot
+0.26%
```

For every leg.

Example:

| Leg | Strike | Distance from Spot | % From Spot |
|---|---:|---:|---:|
| Long PE | 23,100 | -40.5 | -0.17% |
| Short PE | 22,200 | -940.5 | -4.06% |
| Hedge PE | 21,600 | -1,540.5 | -6.66% |
| Long CE | 23,200 | +59.5 | +0.26% |
| Short CE | 24,100 | +959.5 | +4.15% |
| Hedge CE | 24,700 | +1,559.5 | +6.74% |

This makes the strategy understandable even when NIFTY moves to a completely different level.

---

# 20. Web Page — Recommended Layout

## Header

```text
NIFTY 50        23,140.50

Decision Time   15:00
Expiry          13 Oct 2026
DTE             12

Expected Move   ±XXX
IV Percentile   XX
Market Regime   TRENDING / RANGE
```

---

## Decision Card

```text
MOVE EXPECTATION
🟢 LARGE MOVE

DIRECTION
🟡 NO CLEAR DIRECTION

SELECTED STRATEGY
🟢 FULL BUTTERFLY
```

or:

```text
MOVE EXPECTATION
🟢 LARGE MOVE

DIRECTION
🟢 BULLISH

SELECTED STRATEGY
🟢 CE BUTTERFLY
```

### Direction override control

Shown only when the move classification is BIG MOVE:

```text
DIRECTION OVERRIDE   [ AUTO ] [ UP ] [ DOWN ] [ NO DIRECTION ]
```

When an override is active, the decision card shows it explicitly:

```text
DIRECTION
🟢 BULLISH  (manual override — engine: NO CLEAR DIRECTION)

SELECTED STRATEGY
🟢 CE BUTTERFLY
```

---

# 21. Strategy Card

Show:

### PE BUTTERFLY / CE BUTTERFLY / FULL BUTTERFLY

- All strikes
- Action
- Quantity
- Premium
- Delta
- IV
- Distance from spot
- Expected move distance

---

# 22. Payoff Chart

The chart should show:

- Current spot
- Expected-move band
- 1σ / 2σ if available
- Expiry payoff
- Current theoretical P&L
- Breakevens
- Maximum profit
- Maximum loss

For the Full Butterfly, clearly shade the **central loss region**.

---

# 23. Validity Panel

Example:

```text
STRUCTURE             PASS
DTE                   PASS
DELTA                 PASS
WING RATIO             PASS
MAX LOSS               PASS
REWARD/RISK            PASS
EXPECTED MOVE          PASS
LOSS ZONE              PASS
IV REGIME              WATCH
LIQUIDITY              PASS

-----------------------------
STRATEGY STATUS: VALID
-----------------------------
```

---

# 24. LLM Panel

The LLM should receive the complete structured snapshot and the candidates that passed every hard gate (Section 18A).

Ask it:

> "Rank the supplied candidates and choose the best one plus up to two alternatives, using only candidates from the list. Explain why the chosen strategy fits the current market regime. Identify the strongest evidence for the move classification, directional classification and selected structure. If a manual direction override is set, say whether the evidence supports it. Highlight any borderline conditions, WATCH items, risks and invalidation conditions. Do not override hard validity gates and do not invent missing data or new strikes."

The response should be structured (JSON with candidate ids, ranks and reasons, plus the text sections below) so the engine can validate the picks.

The LLM should produce:

### Market View

### Why this strategy

### Key strikes

### Risk

### Expected move

### What could go wrong

### What invalidates the setup

### Alternative candidate

The LLM should not execute or override the deterministic strategy engine.

---

# 25. Strategy Selection JSON

```json
{
  "spot": 23140.5,
  "decision_time": "15:00",
  "expiry": "2026-10-13",

  "move_assessment": {
    "event_score": 2,
    "expected_move": 520,
    "atr14": 350,
    "em_atr_ratio": 1.49,
    "iv_expansion": true,
    "move_score": 7,
    "classification": "BIG_MOVE"
  },

  "direction": {
    "bullish_confidence": 42,
    "bearish_confidence": 39,
    "classification": "NO_CLEAR_DIRECTION",
    "manual_override": null,
    "effective": "NO_CLEAR_DIRECTION"
  },

  "selected_strategy": "FULL_BUTTERFLY",

  "candidates": [
    {
      "id": "FB-wide-13OCT",
      "structure": "FULL_BUTTERFLY",
      "variant": "wide",
      "hard_gates": "PASS",
      "watch_items": ["loss_width_em_ratio"],
      "max_profit": 35529,
      "max_loss": 22321,
      "ai_rank": 1,
      "ai_reason": "..."
    }
  ],
  "ranking_source": "AI",

  "validity": {
    "expiry": "PASS",
    "structure": "PASS",
    "risk": "PASS",
    "liquidity": "PASS",
    "expected_move": "PASS"
  }
}
```

---

# 26. State Machine

```text
DATA_ERROR
    |
    v
NO_TRADE

DATA_OK
    |
    v
MOVE_CLASSIFICATION
    |
    +---- BIG MOVE ----+
    |                  |
    |            DIRECTION
    |                  |
    |         MANUAL OVERRIDE (optional)
    |                  |
    |         EFFECTIVE DIRECTION
    |             /    |    \
    |            /     |     \
    |          UP    NONE    DOWN
    |           |      |       |
    |           v      v       v
    |          CE  FULL BFLY  PE
    |
    +---- LOW MOVE ----+
              |
              v
       NEUTRAL / AVOID
```

---

# 27. Recommended Output

The application should end with a simple decision.

### Example

```text
┌──────────────────────────────────────┐
│ DAILY NIFTY STRATEGY                 │
│                                      │
│ Move:       LARGE                    │
│ Direction:  NO CLEAR BIAS            │
│                                      │
│ Strategy:   FULL BUTTERFLY           │
│ Status:     VALID                    │
│                                      │
│ Max Loss:   ₹XX,XXX                  │
│ Max Profit: ₹XX,XXX                  │
│ BE Zone:    XXXX – XXXX              │
│                                      │
│ [VIEW PAYOFF] [VIEW CONDITIONS]      │
└──────────────────────────────────────┘
```

---

# 28. Images / Visual References

## Full Butterfly

Use the supplied Full Butterfly payoff screenshot to explain the six-leg structure and central loss zone.

## Positive Bias

Use the CE butterfly screenshot to show the upside directional structure.

## Negative Bias

Use the PE butterfly screenshot to show the downside directional structure.

## Neutral

Use the schematic long/short-strangle visual on the strategy page, but make the risk type explicit.

---

# 29. Final Decision Logic

The entire application can be summarized as:

```text
30 MINUTES BEFORE CLOSE
        |
        v
Collect market + option-chain + event data
        |
        v
Estimate expected move
        |
        v
Is a large move expected?
       / \
     YES  NO
      |    |
      |    +----> Neutral/range conditions?
      |             |
      |          YES | NO
      |             |  \
      |             v   v
      |        Defined-risk  NO TRADE
      |        neutral
      |
      v
Is direction strong?
(manual override may set UP / DOWN / NO DIRECTION)
    /       \
  UP        DOWN
   |          |
   v          v
CE Butterfly PE Butterfly

If BIG MOVE + NO CLEAR DIRECTION:
        |
        v
Full Butterfly

Then for every candidate:
        |
        v
Calculate payoff
        |
        v
Check risk / RR / breakevens /
expected move / liquidity
        |
        v
VALID?
  /       \
YES       NO
 |         |
 v         v
LLM      Reject
Analysis
```

---

# 30. Design Philosophy

The system is deliberately split into two layers.

## Layer 1 — Deterministic Strategy Engine

Responsible for:

- data
- event classification
- expected move
- move score
- directional score
- applying the manual direction override
- strategy selection
- strike selection
- payoff
- risk
- candidate generation
- validity (hard gates)
- fallback ranking when the AI is unavailable

## Layer 2 — LLM

Responsible for:

- ranking the candidates that passed every hard gate and picking the best options (Section 18A)
- explanation
- contextual interpretation
- identifying unusual factors
- comparing valid candidates
- explaining risks
- explaining why the strategy was selected

The LLM must not be the component that decides whether a trade violates a hard risk rule.

---

# 31. Backtesting Plan

Backtest the complete decision tree, not just individual strategies.

Test:

### Move classification

- Event score
- EM/ATR thresholds
- IV expansion
- range expansion

### Direction

- Engine direction vs manual overrides (did overrides help or hurt?)
- Confidence thresholds
- Trend indicators
- Momentum
- OI/PCR inputs

### Strategy

- CE butterfly
- PE butterfly
- Full Butterfly
- Neutral
- No trade

Measure:

- Strategy frequency
- Win rate
- Expectancy
- Average win/loss
- Profit factor
- Maximum drawdown
- Overnight gap impact
- Slippage
- Transaction costs
- Performance by IV regime
- Performance by event type
- Performance by DTE
- Performance by market regime

The objective is to validate the **decision tree**, not merely optimize one strategy.

---

# 32. Important Risk Note

The strategy classification should never be interpreted as certainty about the next day's NIFTY move.

"Big move expected" means the available market/event/volatility data indicate an elevated movement regime relative to the configured baseline.

All thresholds should be treated as configurable research parameters until validated through out-of-sample testing.

---

# 33. Final Strategy Framework

> **At T-30, determine whether NIFTY is likely to experience an unusually large move. If yes, determine whether the directional evidence is sufficiently strong, and let the user manually override that direction if they choose. Use CE Butterfly for an upside bias, PE Butterfly for a downside bias, and the Full Butterfly when a large move is expected but direction is uncertain. If no large move is expected, use a defined-risk neutral premium structure only when its range and risk conditions pass; otherwise avoid the trade. Generate all strikes dynamically relative to spot using delta, expected move and wing geometry. Validate the resulting payoff deterministically, then use the LLM to explain the selected setup.**
