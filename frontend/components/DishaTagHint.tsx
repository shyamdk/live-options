"use client";

import type { DishaState, DishaStatement } from "@/types/disha";
import type { LiveTrade } from "@/types/live";

/**
 * One line per tag: which way the tag's open legs lean (delta-weighted), and
 * whether this morning's Disha situations historically favoured that lean.
 * Disha's base rates are weak tilts (mostly 40-60%), so the wording stays at
 * "leans with / against you", never a buy/sell signal.
 */

const MORNING_END_MIN = 11 * 60;
const NEUTRAL_LOTS = 0.15; // |net delta| below this many NIFTY lots (~10 delta) counts as neutral -- spreads carry small net deltas
const LOT = 65;

function ncdf(x: number): number {
  // Abramowitz-Stegun approximation of the normal CDF
  const t = 1 / (1 + 0.2316419 * Math.abs(x));
  const d = 0.3989423 * Math.exp((-x * x) / 2);
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
  return x > 0 ? 1 - p : p;
}

function legDelta(trade: LiveTrade, spot: number, vol: number): number | null {
  const strike = trade.strikePrice;
  const side = trade.optionSide;
  if (!strike || (side !== "CE" && side !== "PE") || !trade.expiry) return null;
  const expiry = new Date(`${trade.expiry}T15:30:00+05:30`).getTime();
  const years = Math.max((expiry - Date.now()) / (365 * 24 * 3600 * 1000), 1 / (365 * 24 * 12));
  const d1 = (Math.log(spot / strike) + (vol * vol * years) / 2) / (vol * Math.sqrt(years));
  const callDelta = ncdf(d1);
  return side === "CE" ? callDelta : callDelta - 1;
}

/** Net delta of the tag's open legs, in NIFTY lots (positive = gains if NIFTY rises). */
export function tagNetDeltaLots(trades: LiveTrade[], spot: number, vix: number | null): number | null {
  const vol = Math.max((vix ?? 14) / 100, 0.05);
  let total = 0;
  let counted = 0;
  for (const t of trades) {
    const delta = legDelta(t, spot, vol);
    if (delta === null) continue;
    total += delta * Number(t.qty ?? 0);
    counted += 1;
  }
  return counted ? total / LOT : null;
}

/** Each matched situation's first statement as "chance the morning favours an UP move". */
type Read = { label: string; s: DishaStatement; upChance: number; flip: boolean };

function bullishReads(disha: DishaState): Read[] {
  const sits = disha.baseRates?.situations ?? {};
  const out: Read[] = [];
  for (const key of disha.matches) {
    const sit = sits[key];
    const s = sit?.statements[0];
    if (!sit || !s) continue;
    const bearishContinuation = key === "breakout_down" || key === "breakout_down_narrow" || key === "open_strong_down";
    out.push({ label: sit.label, s, upChance: bearishContinuation ? 1 - s.rate : s.rate, flip: bearishContinuation });
  }
  return out;
}

function istMinuteNow(): number {
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(new Date());
  const h = Number(parts.find((p) => p.type === "hour")?.value ?? 0);
  const m = Number(parts.find((p) => p.type === "minute")?.value ?? 0);
  return h * 60 + m;
}

const pct = (r: number) => `${Math.round(r * 100)}%`;

export default function DishaTagHint({ trades, disha }: { trades: LiveTrade[]; disha: DishaState | null }) {
  const open = trades.filter((t) => Number(t.qty ?? 0) !== 0 && (t.optionSide === "CE" || t.optionSide === "PE"));
  if (!disha || !disha.last || !open.length) return null;
  const lots = tagNetDeltaLots(open, disha.last, disha.vix.now);
  if (lots === null) return null;
  const lean = Math.abs(lots) < NEUTRAL_LOTS ? "neutral" : lots > 0 ? "bullish" : "bearish";
  const leanText = lean === "neutral" ? "roughly neutral" : `${lean} (≈ ${lots > 0 ? "+" : "−"}${Math.abs(lots).toFixed(1)} lots of NIFTY delta)`;
  const morningOver = istMinuteNow() >= MORNING_END_MIN;
  const reads = bullishReads(disha);

  let pill: { text: string; tone: string };
  let detail: string;
  if (!reads.length) {
    pill = { text: "No context yet", tone: "var(--muted)" };
    detail = "Disha matches situations from 09:15 (gap) and 09:30 (opening range).";
  } else if (lean === "neutral") {
    const bo = disha.breakout;
    const boRead = reads.find((r) => r.label.toLowerCase().startsWith("breaks"));
    pill = bo ? { text: "Moving morning", tone: "var(--amber)" } : { text: "Range so far", tone: "var(--muted)" };
    detail = bo
      ? `NIFTY broke ${bo.side === "up" ? "above" : "below"} the opening range at ${new Date(bo.time * 1000).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false })} (${bo.distancePts >= 0 ? "+" : ""}${bo.distancePts.toFixed(0)} pts beyond it now)${boRead ? `; that kind of breakout held ${pct(boRead.s.rate)} of ${boRead.s.n} days` : ""}. A continued move hurts a neutral position on the ${bo.side === "up" ? "call" : "put"} side — watch that leg's distance.`
      : "No opening-range breakout — the kind of morning a neutral position prefers.";
  } else {
    // the matched situation with the strongest historical tilt
    const best = reads.reduce((a, b) => (Math.abs(b.upChance - 0.5) > Math.abs(a.upChance - 0.5) ? b : a));
    const favour = lean === "bullish" ? best.upChance : 1 - best.upChance;
    const years = Object.entries(best.s.byYear)
      .map(([y, v]) => {
        const up = best.flip ? 1 - v.rate : v.rate;
        return `${y} ${pct(lean === "bullish" ? up : 1 - up)}`;
      })
      .join(", ");
    if (Math.abs(favour - 0.5) < 0.06) {
      pill = { text: "No meaningful edge", tone: "var(--muted)" };
    } else if (favour > 0.5) {
      pill = { text: `Leans with you (${pct(favour)})`, tone: "var(--green)" };
    } else {
      pill = { text: `Leans against you (${pct(1 - favour)})`, tone: "var(--red)" };
    }
    detail = `${best.label}: on ${best.s.n} past days the morning went your way ${pct(favour)} of the time (${years}).${
      favour < 0.44 ? " Consider tightening the stop or trimming the leg that loses on that move." : favour > 0.56 ? " Fine to hold to your levels." : " Manage by your levels."
    }`;
  }

  return (
    <div className="gb-status-row" style={{ alignItems: "baseline", flexWrap: "wrap", gap: 8 }}>
      <span style={{ fontWeight: 600 }}>Disha</span>
      <span className="badge" style={{ color: pill.tone, borderColor: pill.tone, background: "transparent" }}>{pill.text}</span>
      <span>
        Tag is {leanText}. {detail}
        {morningOver ? " (Disha's rates cover the 09:15–11:00 morning; later in the day treat this as background.)" : ""}
      </span>
    </div>
  );
}
