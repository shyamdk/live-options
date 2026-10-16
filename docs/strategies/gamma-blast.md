# Gamma Blast on Expiry Day — Research & Proposal

Status: **Research / design phase.** No implementation yet. This document is the
"understand first" step before building a NIFTY + SENSEX gamma-blast algo.

> Note: `Old/docs/Gamma-Blast.md` describes a *different, older* strategy
> (straddle-expansion breakout). This document proposes the **real** community
> "gamma blast" (expiry-day OI-wall breakout / zero-to-hero), and explains why.

---

## Part 1 — The 30-second options foundation

An **option** is a contract giving the right (not obligation) to buy/sell
NIFTY/SENSEX at a fixed **strike** price.

- **CE (Call)** = bet the index goes **up**.
- **PE (Put)** = bet the index goes **down**.
- You pay a **premium** to buy it. As an option **buyer**, max loss = premium
  paid; upside is large.
- **ATM** (at-the-money) = strike nearest the index. **OTM** (out-of-the-money)
  = strike the move hasn't reached yet (cheaper, needs the index to travel).

A premium has two parts:

- **Intrinsic value** = the real in-the-money amount.
- **Time value** = the "hope" a move might still happen before expiry.

**On expiry afternoon, time value is nearly gone.** An ATM option is almost pure
hope, priced cheaply (Rs 5-30). That is the setup for everything below.

---

## Part 2 — The three Greeks that make expiry day violent

"Greeks" measure how an option's price reacts to things. Three matter here:

| Greek | Plain meaning | Analogy |
|---|---|---|
| **Delta** | Premium move per 1 point of index move. Ranges 0 to 1. | **Speed** of the option |
| **Gamma** | How fast **delta itself** changes as the index moves. | **Acceleration** — the gas pedal |
| **Theta** | Premium **bled away** every minute just from time passing. | The **melting ice cube** |

Key fact:

> **As expiry approaches, gamma on ATM options goes vertical.**

An ATM option on expiry afternoon is on a knife's edge: it will either expire
**worthless** (delta collapses to 0) or **in-the-money** (delta jumps to 1). A
small index move flips it hard from one fate to the other — a huge, sudden
change in delta = **massive gamma**.

When delta swings from ~0.2 to ~0.6 in minutes, the premium does not move
linearly — it **explodes**. A Rs 8 option becomes Rs 35 on a 60-point NIFTY
spike. **That is the "gamma blast."**

The catch: **theta is equally brutal.** If the move does not come, that Rs 8
melts to Rs 1 within the hour. Gamma is the reason for the jackpot; theta is the
reason ~95% of these trades die.

---

## Part 3 — What "Gamma Blast" actually is

The community "Gamma Blast" (aka the **"zero-to-hero" trade**):

> **Late on expiry day, buy a cheap ATM / 1-strike-OTM option right as the index
> breaks out of a tight range — betting gamma multiplies the premium 3-10x in
> minutes.**

The real edge is **not** "premium is expanding" (that was the old strategy). It
is "**a trapped-seller breakout is about to force a violent directional move near
expiry.**"

---

## Part 4 — The real edge: short-covering, not magic

The blast has **fuel: trapped option sellers.**

On expiry day, sellers pile huge **Open Interest (OI)** at round-number strikes
(24,000 / 24,500 on NIFTY; 80,000 / 80,500 on SENSEX), betting the index *stays
below* that wall so their sold calls expire worthless. This creates a visible
**OI wall.**

As the index grinds up toward that wall late in the day:

1. Price pokes **through** the wall.
2. Sellers face large expiry loss and **panic-buy** to cover / hedge.
3. Their buying **pushes price further**, forcing *more* sellers to cover — a
   feedback loop.
4. Gamma turns that fast index move into a **premium explosion** on the calls.

So the genuine edge is: **be positioned in the ATM option just before a high-OI
wall breaks, in the last ~90 minutes, on an otherwise quiet day.** The "quiet
day" matters — if the index already moved 1.5% by 1:45 PM, the fuel is spent and
you are just chasing.

---

## Part 5 — The brutal truth (why most lose)

- **~95% of naive gamma-blast tickets go to zero.** "Buy a Rs 5 option and pray"
  gets melted by theta before any breakout comes.
- It is a **low-hit-rate, high-payout** strategy. Perhaps 25-35% of attempts win,
  but winners pay 3-10x and losers cost ~1x. Works only with **tiny sizing and
  ruthless exits.**
- The edge is **not** gamma itself (everyone sees gamma). It is **timing + a real
  catalyst (OI-wall break) + not chasing + taking profit fast** — gamma cuts
  *both* ways (a 15-point pullback crushes the premium as fast as it inflated).

Tradeable as a disciplined, filtered, small-size algo. **Not** a "set 5x target
and relax" strategy.

---

## Part 6 — How this fits the existing system

| Already have | Relevance |
|---|---|
| **Strange-E-Day** (short strangle on expiry — option *selling*) | Gamma Blast is the **opposite side**: option *buying* on expiry. On a day the strangle is stressed by a breakout, a gamma-blast long is *winning*. Natural complement. |
| **NIFTY (Tue) + SENSEX (Thu) expiry plumbing** | **Two independent setups every week**, two different days. One shared algo. |
| **Option chain with OI per strike, live quotes, paper engine, guardrails** | ~70% of the infra exists. OI-wall data is already in chain snapshots. |

---

## Part 7 — Proposed strategy (the WHAT)

### Pre-conditions (from ~1:45 PM onward)

| Rule | Default | Why |
|---|---|---|
| **Expiry day only** | NIFTY Tue / SENSEX Thu | Gamma only goes vertical on expiry. |
| **Quiet day filter** | Index moved **< 1.0%** from open by trigger time | Confirms fuel unspent; avoids chasing. |
| **Time window** | Enter **2:00-3:00 PM**, hard exit **3:20 PM** | Before 2 PM theta kills you; after 3:20 liquidity dies. |
| **OI wall identified** | Nearest heavy-OI call strike above spot (put strike below) | The catalyst level that must break. |

### Entry trigger

- **BUY CE** when spot **breaks above** the call OI wall (+ buffer) on a
  volume/IV uptick, day still quiet.
- **BUY PE** when spot **breaks below** the put OI wall, same conditions.
- **No trade** if no clean wall, day already ran, or outside the window.

### Strike selection (critical)

- Buy **ATM or exactly 1 strike OTM** in the breakout direction. Never further —
  far-OTM strikes have too little gamma to respond and usually expire worthless.
- NIFTY strikes 50 apart (lot 65); SENSEX 100 apart (lot 20) — same logic,
  different granularity.

### Exits (where the money is kept)

| Exit | Default | Why |
|---|---|---|
| **Fast profit-take / scale-out** | Book half at +40-60%, trail the rest | Gamma reverses violently; lock the spike. |
| **Hard premium stop** | -25 to -30% of premium paid | Small, fixed, survivable loss. |
| **"Blast failed" time-stop** | Exit if no follow-through in N minutes | A break that does not ignite short-covering fast is a dud; theta will eat it. |
| **Force exit** | 3:20 PM | No expiry-close illiquidity risk. |

### Position sizing

- **Risk 1-2% of capital per attempt, max.** Most attempts lose; survival is the
  entire edge.

### Reuse from the old implementation

Keep the old Gamma-Blast guardrails: liquidity/spread checks, data-freshness
(stale expiry-day quotes are dangerous), `maxTradesPerDay`,
**consecutive-loss breaker**, brokerage/slippage modeling, and paper-first with a
150-trade evidence gate before any live switch.

---

## Part 8 — What to do differently from a naive gamma blast

1. **OI-wall catalyst instead of "premium expanded."** The real edge is trapped
   sellers, not vol expansion. Biggest upgrade over the archived version.
2. **Quiet-day gate.** No trade if the index already traveled — the single best
   filter against chasing.
3. **"Blast-failed" fast time-stop.** A gamma-blast entry that does not ignite in
   minutes is already wrong; do not let theta bleed it.
4. **Direction confirmation.** Reuse the `day_direction` engine (EMA/ADX/VWAP/
   structure) so we do not buy calls into a structurally weak tape.
5. **Honest expectancy tracking.** Log hit-rate and payoff ratio so the edge is
   *visible* on paper before risking anything — this strategy lives or dies on
   that ratio, not on any single trade.

---

## Part 9 — Open decisions before implementing

1. **Catalyst model** — agree the **OI-wall breakout** (short-covering) is the
   entry trigger, rather than the old "straddle expansion"? Core design fork.
2. **Directional vs both-sides** — buy only the breakout direction, or run a
   both-sides version that catches a blast either way?
3. **Confirmation strictness** — require agreement from `day_direction`, or is the
   OI-wall break enough on its own? (Stricter = fewer, higher-quality trades.)
4. **Does the "trapped sellers at OI walls" model match what actually happens on
   NIFTY/SENSEX expiries?** The whole strategy hangs off that assumption.

---

## Sources

- EnrichMoney — Gamma Blast Guide:
  https://enrichmoney.in/blog/gamma-blast-strategy-nse-options-expiry
- ORB Trader — Zero-to-Hero Expiry Blasts Safely:
  https://orbtrader.in/the-truth-about-zero-to-hero-trades-how-to-catch-expiry-day-gamma-blasts-safely/
- Pushkarraj Thakur — Gamma Blast Jackpot:
  https://pushkarrajthakur.com/gamma-blast-expiry-jackpot-strategy-option-buying-in-stock-market/
- Quantsapp — The Gamma Factor:
  https://medium.com/@quantsapp.optiontrading/as-your-options-explode-the-gamma-factor-2f42be10dd91
- Sahi — Nifty Expiry Scalping:
  https://www.sahi.com/blogs/nifty-expiry-day-strategies-scalping-guide
- Own reference: `Old/docs/Gamma-Blast.md`
