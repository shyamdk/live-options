# The Theta Book — Strategy Note

*Strategy note · for review, not yet implemented*

A safe-distance, premium-selling framework — reverse-engineered from three of your own live sessions and checked against real option-chain and index data.

**Sessions read:** 28 Jul NIFTY (Tue exp) · 29 Jul SENSEX (T-1) · 30 Jul SENSEX (exp)
**Legs:** 28
**Margin base:** ₹23L

---

You're already running a coherent strategy — you just haven't written it down. This note names what your three sessions show you actually do, then turns it into explicit rules for strike range, scaling, exits, and news, so it can be reviewed and encoded into Manage Trades rather than re-decided by feel every session.

> **The pattern:** you sell theta at a distance that scales with how much time is left — wide (~2%) two days out, tighter (~0.8%) on expiry morning — and you add to a strike only after it has already proven itself by richening, not on a schedule. The one leg that lost money is the one instructive failure: a call sold 0.35% OTM that spot rallied through: 90.9% of that day's legs still won, and you closed the loser rather than let it ride. That's the strategy. This note just gives it numbers.

## 01 — The evidence

### What your own trades already show

Distances below are measured against each day's *closing* level, since the exports don't carry fill timestamps — treat them as "how much room the strike ultimately had to survive," not the exact distance at the moment you sold it. On a day that trends (30 Jul rallied +338 pts into the close), your true entry distance on the earlier legs was almost certainly wider than what's shown here.

| | |
|---|---|
| T-1 avg distance | **2.07%** |
| Expiry-day avg (Nifty) | **0.79%** |
| Expiry-day avg (Sensex) | **0.74%** |
| Closest leg that won | **0.35%** |
| Closest leg that broke | **0.16%** |
| 30 Jul win rate | **10 / 11** |

#### 28 Jul — NIFTY, Tuesday expiry

Close 23,987.80 · day range 23,954.60–24,041.15 (86 pts, 0.36%)

| Side | Strike | Dist. from close | Entries | Premiums collected |
|---|---:|---:|---:|---|
| CALL | 24,050 | +0.26% | 3 | 4.00 · 5.80 · 4.55 |
| CALL | 24,100 | +0.47% | 1 | 2.40 |
| CALL | 24,150 | +0.68% | 3 | 1.35 · 4.00 · 3.00 |
| CALL | 24,250 | +1.09% | 2 | 0.80 · 2.75 |
| CALL | 24,300 | +1.30% | 2 | 0.75 · 1.60 |
| PUT | 23,900 | −0.37% | 7 | 4.35 · 4.00 · 6.50 · 5.70 · 5.10 · 4.50 · 3.80 |
| PUT | 23,800 | −0.78% | 2 | 4.80 · 4.00 |
| PUT | 23,750 | −0.99% | 3 | 0.95 · 2.80 · 2.15 |
| PUT | 23,700 | −1.20% | 2 | 0.85 · 1.80 |

23,900 PUT sold seven separate times as premium richened from 3.80 to 6.50 — this is the clearest "add on strength" example in the whole set, and it stayed 0.37% clear of the close throughout.

#### 29 Jul — SENSEX, day before expiry

Close 77,632.89 · day range 77,425.81–77,765.49 (340 pts, 0.44%)

| Side | Strike | Dist. from close | Entries | Premiums collected |
|---|---:|---:|---:|---|
| CALL | 79,100 | +1.89% | 4 | 2.35 · 4.70 · 5.50 · 4.60 |
| PUT | 76,100 | −1.97% | 3 | 10.85 · 10.50 · 11.75 |
| PUT | 75,800 | −2.36% | 3 | 7.95 · 10.20 · 11.15 |

#### 30 Jul — SENSEX, expiry day

Close 77,928.15 · day range 77,495.76–78,007.09 (511 pts, 0.66%) · sell avg → buy-back avg shown

| Side | Strike | Dist. from close | Sell → buy avg | P&L |
|---|---:|---:|---:|---:|
| PUT | 76,500 | −1.83% | 4.87 → 1.70 | +190 |
| PUT | 77,000 | −1.19% | 14.20 → 5.35 | +354 |
| PUT | 77,100 | −1.06% | 10.13 → 1.30 | +530 |
| PUT | 77,200 | −0.93% | 9.50 → 1.65 | +157 |
| PUT | 77,400 | −0.68% | 12.84 → 2.90 | +1,391 |
| PUT | 77,500 | −0.55% | 5.15 → 0.05 | +204 |
| CALL | 78,500 | +0.73% | 4.77 → 2.30 | +148 |
| CALL | 78,400 | +0.61% | 5.70 → 1.60 | +164 |
| CALL | 78,200 | +0.35% | 11.26 → 1.05 | +1,429 |
| CALL | 77,900 | −0.04% | 5.29 → 0.80 | +987 |
| CALL | 77,800 | −0.16% | 13.86 → 18.00 | **−497** |

77,900 CALL (closed before the late rally reached it) and 77,800 CALL (caught by it, stopped out) sat 12 points apart. That gap is the entire case for a hard distance floor below.

## 02 — Forward guidance

### Strike range by day-type

Grounded in your own bands above, plus the live NIFTY (04 Aug) and SENSEX (06 Aug) chains: current 1-week put skew is real — puts carry ~12–13% IV against ~8–10% for calls on both names — so a put at the same % distance as a call is structurally safer and richer. Weight size slightly toward puts when skew is this wide.

**T-2 / T-1 — 1.8% – 2.4% OTM** for opening size. Matches your own 29 Jul range exactly. On the current week-out chain that's roughly delta 0.08–0.15 — genuinely far, which is the point: this size is what carries you through to expiry day with room to add.

**Expiry morning — 0.9% – 1.3% OTM** for the first new legs of the day. This is your NIFTY Tue average almost exactly. Open here by default; only go tighter once the flat-market checklist below passes.

**Expiry, confirmed flat — 0.5% – 0.9% OTM** — the tighter half of your own 30 Jul book, where 6 of your 7 winning legs in that band sat. Only enter here after the regime check passes, and only as an add, not your first sell of the day.

**Hard floor — never open new size inside 0.35%.** That's your own line between a leg that survived (78,200 CALL, +1,429) and one that didn't (77,800 CALL, −497), 12 points apart on the same board. Anything tighter than that is a scalp with a pre-committed stop, not a theta sell — size it like one if you take it at all.

## 03 — Is today flat enough to go tighter?

You already do this by feel — "if it's flat for a long time, I go closer." Make it a checklist instead of a feeling, checked once around 10:00–10:30 and again after 1:00pm:

- [ ] **Opening range held.** The 9:15–10:00 range is under ~0.3% of spot and price hasn't closed outside it since.
- [ ] **Range-so-far is below trend.** Your last four expiry-adjacent sessions ranged 299–511 pts on Sensex (~0.4–0.66%). If today's range at the checkpoint is already tracking below the low end of that, it's a flat-day signal.
- [ ] **India VIX flat or falling** versus its own 5-day average — rising VIX intraday overrides everything else here, stay wide regardless of range.
- [ ] **No pending catalyst** for the rest of the session (see news framework below).

All four pass → you're clear to use the "expiry, confirmed flat" band for *new adds*. Any one fails → stay at the expiry-morning default or wider, no matter how attractive a tight premium looks.

## 04 — Scaling in

Your 23,900 PUT (7 entries) and 79,100 CALL (4 entries) are the model to formalize, not a habit to rein in — but give it three edges so it can't drift into averaging into danger:

**Add trigger** — Only add to a strike whose premium has richened ≥30% above your own average entry on that strike, and whose distance from spot is still at or above the band floor for the day-type you're in.

**Tranche cap** — Cap it around 5 tranches per strike. Seven worked on 28 Jul, but that's concentration risk stacking on one line — past ~5, open a fresh strike one step further out instead of adding to the same one.

**Direction check** — If spot is moving *toward* an existing short rather than away from it, that's not an add signal even if premium is up — that's the loss-discipline case in the next section.

## 05 — When to book the loss and roll further out

77,800 CALL is the whole rule in one trade: sold at 13.86, spot rallied through it, bought back at 18.00 for −497 rather than held into expiry hoping it would fade back. Codified:

**Distance stop** — Exit the leg when its distance from spot closes inside ~0.15% with more than 30 minutes left in the session — the exact gap between your winning 77,900 CALL and your losing 77,800 CALL.

**Premium stop** — Equivalent trigger if you'd rather watch price than distance: exit when the buy-back cost would exceed ~2.5× your average sell price on that leg.

**Roll, don't rescue** — If the setup that made you sell the strike still holds (still theta-rich, still expiry day) — take the loss, then open a new strike further out at the current band floor. Don't lower your own floor to "make it back" on the same line.

## 06 — Using sentiment and news

Your edge here is distance and theta, not direction — so treat news as a gate on size and distance, never as a reason to sell tighter or bet a side.

- **Before scheduled events** (RBI policy, Fed, budget, index-heavyweight earnings) that land before that day's expiry: skip the tightened "confirmed flat" band entirely for that session, and treat the expiry-morning band as your *minimum*, not your default.
- **Mid-session headlines that move premium your way** (your own words: "when premium increases, I try to capitalize") are exactly the add-trigger in Section 04 — richened premium, distance still holding. No special news handling needed; the existing rule already covers it.
- **Mid-session headlines that move spot toward a short** are exactly the loss-discipline trigger in Section 05, regardless of whether you believe the move is "just noise." The distance/premium stop doesn't care why spot moved.

## 07 — Putting this in Manage Trades

Everything above is mechanical enough to sit on top of what's already built rather than a new tool:

- **Tag each leg by day-type** — `t1_wide`, `exp_morning`, `exp_tight` — the same free-text tagging you asked for on Manage Trades already gives you the per-tag P&L split needed to check, week over week, whether the tight band is actually earning its keep or just adding risk.
- **Set the SL% field** on each leg to the premium stop from Section 05 (~2.5× entry) so a breach shows up as an SL signal you approve, instead of a mental note you might miss mid-session.
- **Watch the Spot Dist column** already on the Sell table — it's the same 0.15% distance-stop number from Section 05, just live instead of computed after the fact.
- Your separate **Bank Nifty Aug positions** (57,300 / 60,000 CALL, net +2,907 across the two) sit outside this framework entirely — longer-dated, closer to spot, more actively managed. Worth its own tag and its own note once this one's settled; don't fold it into the weekly-expiry rules above.

---

## Before we build anything — open questions

1. Does the 0.35% hard floor feel right, or has a tighter sell worked for you before in a way these three sessions don't show?
2. Should Manage Trades actively warn (or block) a new sell inside that day-type's floor, or just surface the distance and leave the call to you?
3. Is 5 tranches the right cap, or does your real ceiling depend more on total premium collected than entry count?
4. Want the Bank Nifty tactical book split into its own note with its own rules, once we've settled this one?

---

*Sources: 28thJulyNiftyExpiry.xlsx · 29thJulySensex.xlsx · 30thJulySensexExpiry.csv — cross-checked against live NIFTY / SENSEX / BANKNIFTY 15-min OHLC (24–30 Jul) and current NIFTY (04 Aug) / SENSEX (06 Aug) option chains via Dhan.*
