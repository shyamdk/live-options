# NIFTY Directional Butterfly Strategy — Trade Validity & LLM Decision Page

## 1. Purpose

This document defines a **repeatable, automatable trade-validity framework** for two directional NIFTY option structures:

- **Positive Bias — NIFTY Moving Up:** 1:-2:1 Call Butterfly
- **Negative Bias — NIFTY Moving Down:** 1:-2:1 Put Butterfly

The objective is not to hard-code particular strikes or premiums. Premiums change with spot, volatility, time to expiry, skew and liquidity.

Instead, the system should:

1. Determine the directional bias.
2. Generate candidate 1:-2:1 structures.
3. Apply objective validity conditions.
4. Reject structures that fail mandatory risk/structure rules.
5. Rank valid structures using a consistent framework.
6. Send the structured market/option data to an LLM.
7. Ask the LLM for an **explanation and suggestion**, not for uncontrolled risk decisions.
8. Display the result on a web page.

> **Important:** Thresholds in this document are starting parameters for backtesting. They should be optimized and validated on historical/out-of-sample data before being used for live trading.

---

# 2. The Two Strategy Views

## View A — Positive Bias: NIFTY Moving Up

### Structure

`BUY near CE ×1 → SELL farther CE ×2 → BUY still-farther CE ×1`

Example from the supplied screenshot:

| Action | Strike | Option | Lots | Premium |
|---|---:|---|---:|---:|
| BUY | 23,300 | CE | 1 | ₹118.00 |
| SELL | 24,100 | CE | 2 | ₹5.35 |
| BUY | 24,700 | CE | 1 | ₹1.65 |

The screenshot shows:

- NIFTY: 23,140.50
- Expiry: 6 Oct 2026
- Maximum profit: ₹44,268.25
- Maximum loss: ₹7,081.75
- Platform risk/reward: 0.16
- POP: 35.30%
- Breakeven: 23,408.95

![Positive Bias — NIFTY Moving Up](Positive_Bias_NIFTY_Moving_Up.png)

---

## View B — Negative Bias: NIFTY Moving Down

### Structure

`BUY near PE ×1 → SELL farther PE ×2 → BUY still-farther PE ×1`

Example from the supplied screenshot:

| Action | Strike | Option | Lots | Premium |
|---|---:|---|---:|---:|
| BUY | 23,000 | PE | 1 | ₹91.55 |
| SELL | 22,200 | PE | 2 | ₹11.50 |
| BUY | 21,600 | PE | 1 | ₹5.40 |

The screenshot shows:

- NIFTY: 23,140.50
- Expiry: 6 Oct 2026
- Maximum profit: ₹46,543.25
- Maximum loss: ₹4,806.75
- Platform risk/reward: 0.10
- POP: 33.27%
- Breakeven: 22,926.05

![Negative Bias — NIFTY Moving Down](Negative_Bias_NIFTY_Moving_Down.png)

---

# 3. Core Principle: Do Not Fix Premiums

The system must **not** use rules such as:

- "Buy CE if premium is below ₹100."
- "Sell CE if premium is above ₹10."

Those values are highly dependent on volatility and time.

Instead, use normalized relationships:

- Delta
- DTE
- Expected move
- Strike distance
- Wing geometry
- IV percentile/rank
- IV skew
- Maximum loss
- Reward/risk
- Breakeven
- Liquidity
- Position risk

This allows the same strategy to adapt to changing option premiums.

---

# 4. Strategy Construction Rules

## 4.1 Fixed structure

Always use:

`+1 / -2 / +1`

For bullish:

`+1 CE / -2 CE / +1 CE`

For bearish:

`+1 PE / -2 PE / +1 PE`

All three legs should normally use the **same expiry**.

---

# 5. Candidate Strike Selection

The strike selection engine should not start from fixed strikes.

It should generate candidates using delta.

### Starting parameters

| Leg | Target absolute delta |
|---|---:|
| Near long option | 0.55–0.65 |
| Short option | 0.20–0.30 |
| Far insurance option | 0.05–0.15 |

Preferred starting points:

- Long delta: **0.60**
- Short delta: **0.25**
- Hedge delta: **0.10**

For CE structures use positive CE delta.

For PE structures use the absolute value of PE delta.

### Why delta?

Delta provides a volatility-adjusted way of describing how far an option is from ATM.

This is more robust than selecting a strike based only on a fixed number of points.

---

# 6. Mandatory Validity Conditions

A trade is **VALID** only if all mandatory gates pass.

## Gate 1 — Directional Bias

### Positive

`BIAS = BULLISH`

### Negative

`BIAS = BEARISH`

The directional signal can come from the existing strategy engine/technical model.

The LLM should explain the evidence but should not silently override the deterministic bias.

---

## Gate 2 — Structure

The candidate must be exactly:

`+1 / -2 / +1`

Same option type and same expiry.

**Fail if:**

- different expiry between legs,
- incorrect quantity ratio,
- missing hedge leg,
- naked short tail.

---

## Gate 3 — DTE

Starting parameter:

`MIN_DTE = 5`

`MAX_DTE = 10`

Trade is valid only when:

`5 <= DTE <= 10`

This should be backtested and configurable.

---

## Gate 4 — Delta

Starting ranges:

### Long

`0.55 <= |Delta| <= 0.65`

### Short

`0.20 <= |Delta| <= 0.30`

### Hedge

`0.05 <= |Delta| <= 0.15`

A candidate failing these ranges is rejected unless the system is explicitly configured to allow relaxed ranges.

---

## Gate 5 — Wing Geometry

Define:

`W1 = |Short Strike - Near Long Strike|`

`W2 = |Far Hedge Strike - Short Strike|`

Then:

`Wing Ratio = W2 / W1`

Starting acceptable range:

`0.60 <= Wing Ratio <= 0.80`

Preferred starting value:

`Wing Ratio ≈ 0.75`

This keeps the structure similar to the supplied examples.

---

## Gate 6 — Maximum Loss

For the defined-risk 1:-2:1 structure, calculate the maximum theoretical loss from the actual payoff.

Starting account-level rule:

`Max Loss <= 0.50% of trading capital`

This should be configurable.

Example:

If strategy capital = ₹10,00,000:

`Maximum allowed loss = ₹5,000`

A candidate exceeding this is **INVALID**, regardless of its reward/risk ratio.

---

## Gate 7 — Reward / Risk

Calculate:

`Reward_Risk = Max Profit / Max Loss`

Starting requirement:

`Reward_Risk >= 4.0`

Equivalent platform-style ratio:

`Risk_Reward <= 0.25`

Do not use RR alone. A very high RR can still represent an unrealistic target.

---

## Gate 8 — Expected Move

Calculate the expected NIFTY move for the selected expiry.

A simple starting model can use ATM straddle premium:

`Expected Move ≈ ATM CE Premium + ATM PE Premium`

Then calculate:

`Target Distance = |Short Strike - Spot|`

and:

`Target / Expected Move = Target Distance / Expected Move`

Starting range:

`0.8 <= Target / Expected Move <= 1.5`

This is a **starting research parameter**, not a universal rule.

The intention is to avoid:

- targets that are too close to spot,
- targets that require an unusually large move.

---

## Gate 9 — Short Strike Must Match the Directional Target

The short strike is the strategy's preferred profit zone.

### Bullish

`Short CE Strike ≈ bullish target`

### Bearish

`Short PE Strike ≈ bearish target`

The system should compare the technical/model target with the short strike.

Starting tolerance:

`Target Difference <= 0.25 × Expected Move`

---

## Gate 10 — IV Regime

Do not use absolute option premium.

Use volatility measures such as:

- ATM IV
- IV percentile
- IV rank
- term IV
- strike IV

Starting configuration:

`IV Percentile >= 20`

and

`IV Percentile <= 80`

This avoids automatically entering during extremely compressed or extremely stressed volatility regimes.

This gate should be tested separately because the strategy contains both long and short options.

---

## Gate 11 — IV Skew / Premium Efficiency

Because the strategy depends on selling two options to finance the long options, calculate the relative IV of the three legs.

For example:

`Short_IV / Average(Long_IV, Hedge_IV)`

Track this as a **premium-efficiency metric**.

Do not initially hard-code a universal threshold.

Instead:

1. record the value,
2. backtest outcomes by skew bucket,
3. determine the threshold empirically.

Starting dashboard flag:

`SKEW_EFFICIENCY = PASS / WATCH / FAIL`

---

## Gate 12 — Liquidity

Every leg must satisfy minimum liquidity requirements.

Starting rules:

- Bid/ask spread <= 5% of mid price where practical.
- Minimum OI threshold.
- Minimum volume threshold.
- No stale/zero quotes.
- All three legs must have executable prices.

For very low-premium insurance legs, use an absolute tick/spread rule in addition to the percentage rule.

---

# 7. Optional Conditions / Soft Filters

These should **not initially be hard rejection rules**.

They should influence the confidence/explanation.

Examples:

### Trend alignment

- price vs SMA/EMA
- ADX
- market structure
- momentum

### OI structure

- call OI
- put OI
- change in OI
- key OI concentrations

### PCR

- PCR level
- change in PCR

### Volatility

- VIX
- IV change
- IV term structure

### Event risk

- major economic events
- RBI/Fed events
- major expiry-related events

### Market regime

- trending
- range-bound
- high-volatility
- low-volatility

These are useful for the LLM explanation and later can be promoted to hard filters if backtesting supports them.

---

# 8. Trade Validity Engine

The web page should display the result as a **gate-based decision**, not simply a single AI score.

Example:

```text
NIFTY: 23,140.50

BIAS
🟢 BULLISH

STRUCTURE
+1 23,300 CE
-2 24,100 CE
+1 24,700 CE

VALIDITY

Direction             PASS
Structure             PASS
DTE                   PASS
Delta                 PASS
Wing Ratio             PASS
Max Loss               PASS
Reward/Risk            PASS
Expected Move          PASS
Target Alignment       PASS
IV Regime              PASS
IV Skew                WATCH
Liquidity              PASS

--------------------------------
TRADE STATUS: VALID
--------------------------------

LLM VIEW:
"Structure satisfies all mandatory risk
conditions. IV skew is slightly less
favorable, but does not invalidate the
setup."

Confidence:
HIGH / MEDIUM / LOW
```

---

# 9. Hard Gates vs Soft Signals

This separation is important.

## HARD GATES

These can make a trade invalid:

1. Direction
2. Structure
3. Same expiry
4. DTE
5. Delta ranges
6. Wing ratio
7. Maximum loss
8. Minimum reward/risk
9. Expected-move range
10. Target alignment
11. Minimum liquidity

## SOFT SIGNALS

These should initially produce context:

1. Trend strength
2. ADX
3. PCR
4. OI
5. IV percentile
6. IV skew
7. VIX
8. Event risk
9. Momentum
10. Market regime

This prevents the LLM from turning one interesting market observation into a trade that violates the core risk rules.

---

# 10. LLM Integration

The LLM should receive **structured JSON**, not a screenshot as its primary input.

Example:

```json
{
  "spot": 23140.5,
  "bias": "BULLISH",
  "expiry": "2026-10-06",
  "dte": 7,

  "legs": [
    {
      "action": "BUY",
      "type": "CE",
      "strike": 23300,
      "delta": 0.60,
      "iv": 15.2
    },
    {
      "action": "SELL",
      "type": "CE",
      "strike": 24100,
      "quantity": 2,
      "delta": 0.25,
      "iv": 16.1
    },
    {
      "action": "BUY",
      "type": "CE",
      "strike": 24700,
      "delta": 0.10,
      "iv": 15.8
    }
  ],

  "max_profit": 44268.25,
  "max_loss": 7081.75,
  "reward_risk": 6.25,
  "expected_move": 850,
  "target_distance": 959.5,

  "validity": {
    "direction": "PASS",
    "structure": "PASS",
    "dte": "PASS",
    "delta": "PASS",
    "wing_ratio": "PASS",
    "max_loss": "PASS",
    "reward_risk": "PASS",
    "expected_move": "PASS",
    "target_alignment": "PASS",
    "iv_regime": "PASS",
    "iv_skew": "WATCH",
    "liquidity": "PASS"
  }
}
```

---

# 11. LLM Responsibilities

The LLM should answer:

### 1. What is the market setup?

### 2. Why does the structure fit the directional bias?

### 3. Which conditions passed?

### 4. Which conditions are borderline?

### 5. What are the major risks?

### 6. What alternative structure could be considered if the current candidate fails?

### 7. What would invalidate the trade thesis?

The LLM should **not**:

- override a hard risk gate,
- increase position size,
- remove the insurance leg,
- convert the trade into a naked short,
- claim certainty,
- invent missing option-chain data.

---

# 12. Suggested Web Page Layout

## Header

```text
NIFTY 50    23,140.50

Market Bias:
🟢 BULLISH

Volatility:
IV 14.8 | IV Percentile 42

Expected Move:
±850
```

## Candidate Strategies

Show 3–5 candidate structures.

| Candidate | Max Loss | Max Profit | RR | POP | Status |
|---|---:|---:|---:|---:|---|
| A | ₹7,082 | ₹44,268 | 6.25 | 35.3% | VALID |
| B | ₹6,100 | ₹31,500 | 5.16 | 39.2% | VALID |
| C | ₹3,900 | ₹25,000 | 6.41 | 27.8% | FAIL |

## Condition Panel

Use green / amber / red states:

`PASS / WATCH / FAIL`

## LLM Commentary

A separate panel:

> **LLM Analysis**

The LLM explains why the candidate is valid, what is borderline and what could invalidate it.

---

# 13. Candidate Ranking

Do not rank trades using only maximum profit.

A candidate score can combine:

- Risk compliance
- Reward/risk
- Target probability
- Expected move alignment
- Delta quality
- Liquidity
- IV efficiency

But the ranking must happen **only after all hard gates pass**.

Conceptually:

`VALID candidates → score → rank → LLM explanation`

not:

`all candidates → LLM chooses one → trade`

---

# 14. Suggested Initial Configuration

These values are starting points for research:

```yaml
structure:
  ratio: [1, -2, 1]
  same_expiry: true

dte:
  min: 5
  max: 10

delta:
  long_min: 0.55
  long_max: 0.65
  short_min: 0.20
  short_max: 0.30
  hedge_min: 0.05
  hedge_max: 0.15

wing_ratio:
  min: 0.60
  max: 0.80
  preferred: 0.75

risk:
  max_loss_pct_capital: 0.50
  min_reward_risk: 4.0

expected_move:
  target_min: 0.80
  target_max: 1.50

target_alignment:
  max_difference_expected_move: 0.25

iv:
  percentile_min: 20
  percentile_max: 80

liquidity:
  max_bid_ask_pct: 5

execution:
  same_expiry_only: true
  defined_risk_only: true
```

These numbers are **configuration parameters, not proven optimal values**. The backtester should be able to sweep them.

---

# 15. Backtesting Requirement

Before using the validity engine live, test combinations of:

- DTE
- long delta
- short delta
- hedge delta
- wing ratio
- expected-move multiple
- IV percentile
- minimum RR
- maximum risk %

Measure:

- Win rate
- Average win
- Average loss
- Expectancy
- Profit factor
- Maximum drawdown
- Average holding time
- Slippage impact
- Transaction costs
- Performance by IV regime
- Performance by trend/range regime

The objective is to find **robust ranges**, not a single parameter combination that happens to perform best historically.

---

# 16. Final Trade State Model

The application should have four possible states:

### 🔴 INVALID

One or more mandatory gates fail.

**Do not present it as a valid trade.**

### 🟡 WATCH

Mandatory conditions are close but one or more soft signals are unfavorable.

### 🟢 VALID

All mandatory gates pass.

### 🔵 ACTIVE

A valid structure has actually been entered.

This makes the web page useful as both a scanner and a trading dashboard.

---

# 17. Final Philosophy

The strategy should be expressed as:

> **Direction + Structure + Target + Volatility + Risk + Liquidity**

rather than:

> **Direction + fixed strikes + fixed premium**

The system should automatically adapt the strikes as NIFTY and volatility change while preserving the strategy's underlying characteristics.

The LLM then becomes the **explanation and contextual-analysis layer**, while the deterministic validity engine remains the **risk-control layer**.

That separation is important for reliable automation.
