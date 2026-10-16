# PCR/OI Signal — Fine-Tuning Plan

Status: Options 1 and 2 are **implemented** (see `enrich_with_signal` in
`backend/app/services/pcr_oi.py` — `MIN_SIGNAL_CONFIDENCE` and
`PCR_SMOOTHING_WINDOW`). Options 3-5 remain planning only.

---

## Why signals are noisy today

`enrich_with_signal` in `backend/app/services/pcr_oi.py` calls Buy CE / Buy PE
the moment two factors merely *agree in direction*:

1. **OI-skew factor** — regime-aware (writer- vs buyer-driven) read of
   CE/PE change-in-OI, z-scored against today's own expanding distribution.
2. **PCR-trend factor** — raw point-to-point `pcrDelta`, z-scored the same
   way.

Two things make this noisier than it needs to be:

- The signal fires on **any** agreement, even when both factors are only at
  "low" confidence (within 1σ — by construction, over 30% of all
  observations land there).
- **PCR moves smoothly**, so tick-to-tick `pcrDelta` rarely produces a
  strong z-score even during a real trend — it was already observed
  elsewhere in this project that PCR's own delta series almost never hits
  high/extreme confidence on its own.
- There's no persistence check — a single noisy poll can flip the signal,
  since each poll is scored independently with no smoothing across polls.

---

## Options (roughly ordered by effort)

### 1. Raise the confidence bar to fire
Require both factors to be at least "medium" (or "high") before calling
Buy CE/PE, instead of any agreement counting.
- **Effort**: one-line threshold change in `enrich_with_signal`.
- **Impact**: biggest single lever — cuts out the "low confidence" noise
  floor entirely.
- **Trade-off**: slightly later entries.

### 2. Smooth PCR's own trend instead of tick-to-tick delta
Replace `pcrDelta` (point-to-point) with a short rolling slope — e.g. PCR
vs. its own 3-5 poll moving average — so the PCR factor tracks genuine
trend rather than single-tick jitter.
- **Effort**: moderate — new rolling-average helper, same z-score plumbing.
- **Impact**: directly targets PCR's known noisiness; should let the PCR
  factor actually contribute confidence instead of usually sitting at
  "low."
- **Trade-off**: none significant; strictly more informative than the
  current delta.

### 3. Require persistence (N consecutive agreeing polls) before confirming
Instead of trusting a single poll's agreement, require the same direction
to hold for 2-3 consecutive polls (6-9 min at the default 3-min poll
interval) before promoting it to a real signal.
- **Effort**: moderate — small state machine (candidate → confirmed).
- **Impact**: kills one-off blips.
- **Trade-off**: adds a few minutes of lag before a signal counts.

### 4. Gate on price confirmation
`deltaVegaAligned` (spot + IV both moving with the call) is currently just
a badge, not a filter. Promote it to a required condition — only fire if
spot is already moving in the implied direction.
- **Effort**: moderate — move existing computation earlier, use it to gate
  `signal` instead of just labeling it.
- **Impact**: most powerful filter — kills cases where OI/PCR says one
  thing but price already contradicts it.
- **Trade-off**: most opinionated change — shifts the signal's meaning from
  "pure derivatives read" to "derivatives + price agree." Best tried after
  1+2 have been observed for a while.

### 5. Suppress known-noisy time windows
The Timing Notes section already warns (as text) to ignore the first ~15
min after open and the last ~20-30 min before close. Bake that into
`enrich_with_signal` as an actual suppression window (no signal emitted,
not just advised against).
- **Effort**: low — time-of-day check against `now_ist()`.
- **Impact**: removes a known noise source outright, backed by the user's
  own stated rule already documented in the panel's Timing Notes.
- **Trade-off**: none — this is already the advised behavior, just not
  enforced.

---

## Recommendation

Start with **1 + 2** together — cheap, orthogonal, and directly address the
two loosest parts of the current logic (the confidence floor and PCR's
noisiness). Add **5** next since it's low-effort and already validated by
existing product copy. Reach for **3** if signals are still too frequent
after that. Save **4** for last — it's the most powerful but also changes
what the signal *means*, so it's worth evaluating 1+2(+5) in isolation
first.
