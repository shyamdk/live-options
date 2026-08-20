# OI Analysis Upgrade Specification

## 1. Objective

Upgrade the existing **OI Analysis** module so that it produces clear, stable, actionable signals for **NIFTY option buying**, rather than exposing several fast-changing indicators that the trader must interpret manually.

The system should reduce signal flipping/whipsaws while retaining the useful information already present:

- Put-Call Ratio (PCR)
- CE/PE Change in OI
- CE/PE option premium behaviour
- India VIX
- ATM CE/PE IV
- NIFTY price
- NIFTY VWAP
- Short-term NIFTY price trend

The desired output is deliberately simple:

- `BUY CE`
- `BUY PE`
- `NO TRADE`

The system must default to `NO TRADE` whenever the evidence is conflicting or insufficient.

---

## 2. Existing OI Analysis Interpretation

Preserve the existing application's core interpretations:

### PCR

- Rising PCR is treated as bullish / CE-favouring.
- Falling PCR is treated as bearish / PE-favouring.
- PCR should be judged against its own intraday trend rather than a fixed universal threshold.
- Sharp multi-poll PCR movement should carry more weight than slow drift.

### Change in OI

Use OI together with option premium:

- Rising CE OI + flat/falling CE premium = call writing = resistance = bearish lean.
- Rising CE OI + rising CE premium = call buying = bullish conviction.
- Rising PE OI + flat/falling PE premium = put writing = support = bullish lean.
- Rising PE OI + rising PE premium = put buying = bearish lean.
- Falling OI means unwinding/covering and reduces the influence of that side.
- A sharply moving OI side is more informative than a flat side.

These interpretations are already documented in the existing OI Analysis screen.

### India VIX

Use VIX primarily as a trade-quality/risk filter, NOT as the primary CE-vs-PE direction signal.

### ATM IV

Use ATM IV primarily to assess option premium conditions and confirmation, NOT as a standalone direction signal.

---

# 3. New Signal Architecture

The system should use this hierarchy:

    PCR
      ↓
    MARKET BIAS
      ↓
    OI POSITIONING
      ↓
    PRICE CONFIRMATION
      ↓
    OPTION PREMIUM CONFIRMATION
      ↓
    FINAL SIGNAL

The roles are:

### PCR = Bias

Answers:

> "What is the broader intraday derivatives bias?"

### OI = Positioning

Answers:

> "What are option participants currently positioning for?"

### NIFTY price = Trigger

Answers:

> "Is the market actually moving in the expected direction?"

### Option premium = Confirmation

Answers:

> "Is the option I am about to buy actually responding?"

### VIX / IV = Trade-quality filter

Answers:

> "Is this a good environment to buy premium?"

No single indicator should independently generate a BUY signal.

---

# 4. Signal States

The application must expose only four high-level market states:

1. `BULLISH`
2. `BEARISH`
3. `RANGE`
4. `TRANSITION`

And three actionable outputs:

1. `BUY CE`
2. `BUY PE`
3. `NO TRADE`

`NO TRADE` is the default state.

Do NOT force a CE or PE signal when conditions are mixed.

---

# 5. PCR Processing

Do not use the latest 2-minute PCR change as a standalone signal.

The application currently refreshes every 2 minutes. Keep the refresh capability, but calculate PCR trend using rolling windows.

Recommended windows:

- Fast window: 6 minutes
- Confirmation window: 12 minutes
- Session trend: from session start

Example:

    PCR rising for 10-15 minutes → bullish bias
    PCR flat/noisy             → neutral
    PCR falling for 10-15 min  → bearish bias

A single poll should not change the market bias.

### PCR state

Return:

    PCR_BULLISH
    PCR_NEUTRAL
    PCR_BEARISH

Also calculate:

- PCR slope
- PCR change over 6 minutes
- PCR change over 12 minutes
- session-relative PCR position

Do not use a fixed threshold such as PCR > 1.0 as the primary directional rule.

---

# 6. OI Momentum

Do not rely only on cumulative/session Change in OI.

Calculate OI momentum over:

- Last 2 minutes
- Last 6 minutes
- Last 12 minutes
- Session cumulative

Example:

    CE OI:
      2m   -10L
      6m   -42L
      12m  -81L

    PE OI:
      2m   +8L
      6m   +31L
      12m  +74L

The 6-minute and 12-minute values should carry more weight than the latest 2-minute value.

---

# 7. OI Positioning Classification

Convert raw OI and premium behaviour into a normalized positioning state.

## Bullish positioning

Strong bullish evidence:

- CE OI decreasing / call unwinding
- PE OI increasing while PE premium is flat/falling / put writing

Especially strong when both occur together.

Return:

    OI_BULLISH

## Bearish positioning

Strong bearish evidence:

- CE OI increasing while CE premium is flat/falling / call writing
- PE OI decreasing / put unwinding

Especially strong when both occur together.

Return:

    OI_BEARISH

## Mixed

If the two sides do not agree:

    OI_MIXED

## Transition

If both CE and PE OI are falling significantly:

    OI_UNWINDING

If both are increasing significantly:

    OI_BUILDING_BOTH_SIDES

These should generally result in `NO TRADE` unless price subsequently provides a very strong directional confirmation.

---

# 8. NIFTY Price Confirmation

Add NIFTY price as a mandatory final directional confirmation.

At minimum calculate:

- NIFTY LTP
- VWAP
- 5-minute trend
- short-term momentum
- recent swing high/low or equivalent price structure

## Bullish price confirmation

Examples:

- NIFTY > VWAP
- 5-minute trend bullish
- price making higher highs / higher lows
- short-term momentum positive

Return:

    PRICE_BULLISH

## Bearish price confirmation

Examples:

- NIFTY < VWAP
- 5-minute trend bearish
- price making lower highs / lower lows
- short-term momentum negative

Return:

    PRICE_BEARISH

Otherwise:

    PRICE_NEUTRAL

Price confirmation should be the final trigger before an option-buying signal.

---

# 9. Option Premium Confirmation

For CE:

    CE premium rising
    AND preferably CE premium momentum positive

For PE:

    PE premium rising
    AND preferably PE premium momentum positive

This prevents the system from recommending an option that is theoretically directionally correct but is not actually responding.

Return:

    CE_PREMIUM_BULLISH
    CE_PREMIUM_NEUTRAL
    PE_PREMIUM_BEARISH
    PE_PREMIUM_NEUTRAL

The terminology should describe the option's response, not claim that option premium movement alone proves market direction.

---

# 10. India VIX Filter

Do not use India VIX as a CE/PE direction generator.

Use it as a risk/trade-quality filter.

Calculate:

- Current VIX
- VIX change over 6 minutes
- VIX change over 12 minutes
- Session-relative VIX level

Classify:

    VIX_SUPPORTIVE
    VIX_NEUTRAL
    VIX_RISKY

A rapidly increasing VIX should increase caution because option premiums may already be expensive and moves can be volatile.

A low VIX combined with strong directional positioning may be supportive of a fresh breakout, but this is only a filter.

---

# 11. ATM IV Filter

Use CE IV and PE IV to assess premium conditions.

Calculate:

- CE IV
- PE IV
- 6-minute IV change
- 12-minute IV change
- CE/PE IV spread

For a CE setup:

    CE IV rising moderately + CE premium rising
        → supportive confirmation

For a PE setup:

    PE IV rising moderately + PE premium rising
        → supportive confirmation

Avoid treating a large IV spike as automatically bullish/bearish.

A very large IV increase may mean the move is already being aggressively priced.

Return:

    IV_SUPPORTIVE
    IV_NEUTRAL
    IV_RISKY

---

# 12. Scoring Model

Implement independent CE and PE scores.

## CE score

| Condition | Points |
|---|---:|
| PCR bullish trend | +1 |
| CE OI unwinding | +2 |
| PE writing | +2 |
| NIFTY > VWAP | +2 |
| 5-minute NIFTY trend bullish | +1 |
| CE premium rising | +1 |
| CE IV supportive | +1 |

Maximum = 10.

## PE score

Mirror the CE rules:

| Condition | Points |
|---|---:|
| PCR bearish trend | +1 |
| PE OI unwinding | +2 |
| CE writing | +2 |
| NIFTY < VWAP | +2 |
| 5-minute NIFTY trend bearish | +1 |
| PE premium rising | +1 |
| PE IV supportive | +1 |

Maximum = 10.

---

# 13. Minimum Signal Requirements

Do not generate a trade from score alone.

## BUY CE

All must be true:

    CE score >= 8
    CE score - PE score >= 3
    PCR is not strongly bearish
    OI positioning is not strongly bearish
    Price confirmation is bullish
    CE premium is rising
    Signal persistence >= 3 consecutive readings

Then:

    BUY CE

## BUY PE

All must be true:

    PE score >= 8
    PE score - CE score >= 3
    PCR is not strongly bullish
    OI positioning is not strongly bullish
    Price confirmation is bearish
    PE premium is rising
    Signal persistence >= 3 consecutive readings

Then:

    BUY PE

Everything else:

    NO TRADE

---

# 14. Signal Persistence

This is critical.

The application refreshes every 2 minutes.

A new entry signal must remain valid for at least:

    3 consecutive readings

Therefore approximately 6 minutes of persistence is required.

Example:

    10:30  Bullish
    10:32  Bullish
    10:34  Bullish
            ↓
          BUY CE

But:

    10:30  Bullish
    10:32  Bearish
    10:34  Bullish
            ↓
        NO TRADE

Do not reset the entire market regime because of one contradictory poll.

---

# 15. Hysteresis

Use different thresholds for entry and maintaining an existing signal.

This prevents signal flipping.

Example:

### Entry

    CE score >= 8
    PE score <= 5
    Difference >= 3

### Hold CE

Continue holding while:

    CE score >= 6
    AND price remains above the invalidation level

### Exit CE

Exit when either:

    CE score <= 5 for 2 consecutive readings

OR:

    price invalidates the bullish setup

OR:

    option premium hits the configured stop loss

Do NOT require 3 consecutive readings for an emergency/price-based exit.

Apply the mirror logic to PE.

---

# 16. Cooldown

After exiting an option trade because of signal invalidation, introduce a configurable cooldown.

Default:

    10 minutes

During cooldown:

    do not generate a new opposite-direction option signal

unless a configurable "strong reversal" condition is met.

This prevents:

    CE → PE → CE → PE

whipsaw behaviour.

---

# 17. Market Regime Classification

Before generating a trade signal, classify the market.

## TRENDING_BULLISH

Typical requirements:

- PCR bullish
- OI positioning bullish
- NIFTY above VWAP
- 5-minute trend bullish
- directional score clearly dominant

## TRENDING_BEARISH

Mirror of bullish.

## RANGE

Typical conditions:

- PCR flat/noisy
- OI mixed
- NIFTY oscillating around VWAP
- no clear short-term trend
- CE and PE scores close together

Output:

    NO TRADE

## TRANSITION

Typical conditions:

- PCR recently changed direction
- OI sides are unwinding/rebuilding
- price has not confirmed the new direction
- CE and PE scores are rapidly changing

Output:

    NO TRADE

Transition should be treated as a deliberate "wait" state.

---

# 18. Signal State Machine

Implement an explicit state machine.

Possible states:

    NO_TRADE
    BULLISH_WATCH
    BUY_CE
    HOLD_CE
    BEARISH_WATCH
    BUY_PE
    HOLD_PE
    COOLDOWN

Example CE flow:

    NO_TRADE
        ↓
    BULLISH_WATCH
        ↓ (3 consecutive valid readings)
    BUY_CE
        ↓
    HOLD_CE
        ↓
    EXIT
        ↓
    COOLDOWN
        ↓
    NO_TRADE

Do not jump directly from BUY_CE to BUY_PE on one contradictory reading.

---

# 19. Recommended UI

The current dashboard has useful charts, but the trader should not have to interpret all charts manually.

Add a prominent summary section at the top.

Example:

    ┌──────────────────────────────────────────────┐
    │ NIFTY SIGNAL                                 │
    │                                              │
    │          🟢 BUY CE                           │
    │          Confidence: HIGH                    │
    │                                              │
    │ Market Regime: TRENDING BULLISH              │
    │ Score: 8.5 / 10                              │
    │ Persistence: 3 / 3                           │
    └──────────────────────────────────────────────┘

Then show the supporting evidence:

    PCR              🟢 Bullish
    OI Positioning   🟢 Bullish
    NIFTY vs VWAP    🟢 Above
    5m Trend         🟢 Bullish
    CE Premium       🟢 Rising
    CE IV            🟢 Supportive
    VIX              🟡 Neutral

For a non-trade:

    ┌──────────────────────────────────────────────┐
    │ NIFTY SIGNAL                                 │
    │                                              │
    │             ⚪ NO TRADE                      │
    │                                              │
    │ Reason: Conflicting signals                  │
    │                                              │
    │ PCR              🟢 Bullish                  │
    │ OI Positioning   🔴 Bearish                  │
    │ Price            🟡 Neutral                   │
    │ Persistence      1 / 3                       │
    └──────────────────────────────────────────────┘

The "Reason" should be generated automatically.

---

# 20. Keep the Existing Charts

Do NOT remove the existing charts.

Keep:

- PCR chart
- CE/PE Change in OI chart
- India VIX chart
- CE/PE ATM IV chart

The charts remain useful for manual analysis.

The new signal layer should sit ABOVE the charts.

The purpose is:

    Charts = detailed analysis
    Signal panel = actionable decision

---

# 21. Signal Explanation

Every BUY signal must explain itself.

Example:

    BUY CE

    Why?
    ✓ PCR rising for 12 min
    ✓ CE OI unwinding
    ✓ PE writing
    ✓ NIFTY above VWAP
    ✓ 5-min trend bullish
    ✓ CE premium rising
    ✓ Conditions persisted for 6 min

Every NO TRADE state should also explain itself.

Example:

    NO TRADE

    Why?
    • PCR bullish
    • OI mixed
    • NIFTY below VWAP
    • CE/PE scores too close
    • Persistence only 1/3

This makes the system auditable.

---

# 22. Signal History

Store every calculated signal snapshot.

At minimum:

    timestamp
    underlying
    PCR
    PCR trend
    CE OI change
    PE OI change
    CE OI 6m
    PE OI 6m
    CE OI 12m
    PE OI 12m
    NIFTY price
    VWAP
    price trend
    CE premium
    PE premium
    CE IV
    PE IV
    India VIX
    CE score
    PE score
    market regime
    signal
    persistence
    reason
    state transition

This is important because the scoring model should eventually be validated using historical data.

---

# 23. Backtesting / Validation

Before relying on the new signal system for live trading, backtest the signal rules.

At minimum measure:

- Number of CE signals
- Number of PE signals
- Number of NO TRADE periods
- Win rate
- Average option return
- Average loss
- Maximum consecutive losses
- Maximum drawdown
- Average signal duration
- Number of signal flips
- Number of trades avoided because of persistence
- Performance by time of day

Compare:

    Existing signal logic
    vs
    New filtered signal logic

The objective is NOT simply to maximize win rate.

Also measure whether the new system reduces:

    signal flips
    unnecessary entries
    consecutive small losses
    CE/PE reversals

---

# 24. Configurable Parameters

Do not hard-code these values.

Create configuration parameters for:

    REFRESH_INTERVAL = 2 minutes

    PCR_FAST_WINDOW = 6 minutes
    PCR_CONFIRM_WINDOW = 12 minutes

    OI_FAST_WINDOW = 6 minutes
    OI_CONFIRM_WINDOW = 12 minutes

    SIGNAL_PERSISTENCE = 3 readings

    CE_ENTRY_SCORE = 8
    PE_ENTRY_SCORE = 8

    MIN_SCORE_DIFFERENCE = 3

    EXIT_CONFIRMATION = 2 readings

    COOLDOWN_MINUTES = 10

    VWAP_REQUIRED = true

    PREMIUM_CONFIRMATION_REQUIRED = true

    VIX_FILTER_ENABLED = true
    IV_FILTER_ENABLED = true

All should be adjustable later without changing core signal logic.

---

# 25. Important Design Principle

Do NOT add more indicators simply to improve apparent confidence.

The objective is:

    Fewer
    clearer
    more persistent
    more explainable
    higher-quality signals

A "NO TRADE" result is a successful outcome when the market is ambiguous.

---

# 26. Suggested Final Signal Logic

Conceptually:

    PCR
      ↓
    Bias
      ↓
    OI positioning
      ↓
    Market regime
      ↓
    NIFTY price/VWAP confirmation
      ↓
    Option premium confirmation
      ↓
    Score
      ↓
    Persistence
      ↓
    Hysteresis / cooldown
      ↓
    FINAL SIGNAL

Final output:

    🟢 BUY CE
    🔴 BUY PE
    ⚪ NO TRADE

---

# 27. Implementation Priority

Implement in this order.

### Phase 1 — Signal stability

1. Add 6m / 12m rolling windows.
2. Add PCR trend classification.
3. Add OI positioning classification.
4. Add 3-reading persistence.
5. Add NO TRADE state.

### Phase 2 — Direction confirmation

6. Add NIFTY VWAP.
7. Add 5-minute trend.
8. Add CE/PE premium confirmation.

### Phase 3 — Scoring

9. Implement CE score.
10. Implement PE score.
11. Implement minimum score difference.

### Phase 4 — State management

12. Implement market regime.
13. Implement hysteresis.
14. Implement exit confirmation.
15. Implement cooldown.
16. Implement state machine.

### Phase 5 — Analytics

17. Store signal history.
18. Add signal explanation.
19. Add backtesting.
20. Compare old vs new logic.

---

# 28. Acceptance Criteria

The upgrade is successful if:

1. A single 2-minute contradictory reading does NOT flip a live signal.
2. A BUY signal requires at least 3 consecutive confirmations.
3. CE and PE scores must have meaningful separation.
4. NIFTY price must confirm the directional OI/PCR bias before entry.
5. Option premium must confirm the direction before entry.
6. Conflicting signals produce NO TRADE.
7. Range and transition markets produce NO TRADE.
8. Existing charts remain available.
9. Every signal has a human-readable explanation.
10. Every signal can be reconstructed from stored historical inputs.
11. CE → PE reversal cannot happen immediately without passing the cooldown/strong-reversal rules.
12. All thresholds and windows are configurable.

---

## Important

This specification is a **signal-engine design**, not a guarantee of profitability.

The scoring weights, persistence period, VWAP requirement, cooldown, and thresholds should be validated with historical data and paper trading before being used for live option buying.
