"use client";

import type { MarketProfile } from "@/types/disha";

const n = (v: number | undefined) => (v === undefined ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: 0 }));
const tone = (rel?: string) => (rel === "above" ? "var(--green)" : rel === "below" ? "var(--red)" : "var(--muted)");

/** Market Profile levels as context (NIFTY): yesterday's value area / POC, today's IB and where price is.
 * Context only -- the classic Market Profile setups lost money as option trades in our back-test. */
export default function MarketProfileStrip({ mp, compact = false }: { mp: MarketProfile | null | undefined; compact?: boolean }) {
  if (!mp) return null;
  return (
    <div className="gb-status-row" style={{ flexWrap: "wrap", gap: 12, alignItems: "baseline", fontSize: compact ? 13 : 14 }}>
      <strong>Market Profile</strong>
      <span>
        Yesterday&apos;s value {n(mp.prev.val)}–{n(mp.prev.vah)} · POC {n(mp.prev.poc)}
      </span>
      {mp.openVsValue ? (
        <span>
          opened <strong style={{ color: tone(mp.openVsValue) }}>{mp.openVsValue}</strong> value
        </span>
      ) : null}
      {mp.nowVsValue ? (
        <span>
          now <strong style={{ color: tone(mp.nowVsValue) }}>{mp.nowVsValue}</strong> value ({n(mp.last)})
        </span>
      ) : null}
      {mp.ib ? (
        <span>
          IB {n(mp.ib.low)}–{n(mp.ib.high)} ({n(mp.ib.width)} pts{mp.ib.complete ? "" : ", forming"})
        </span>
      ) : null}
      {mp.today ? <span className="pcr-oi-caption">today so far: value {n(mp.today.val)}–{n(mp.today.vah)}, POC {n(mp.today.poc)}</span> : null}
      {!compact && mp.notes?.length ? (
        <div style={{ flexBasis: "100%", display: "grid", gap: 2 }}>
          {mp.notes.map((t) => (
            <span key={t} className="pcr-oi-caption">• {t}</span>
          ))}
          <span className="pcr-oi-caption">Context only: in our 2025–26 back-test the classic Market Profile setups lost money as ATM option buys.</span>
        </div>
      ) : null}
    </div>
  );
}
