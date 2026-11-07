"use client";

import type { PfColumn } from "@/types/pf-lab";

/** A plain Point & Figure grid: X / O glyphs per box, price labels on the left, the 10-column average as a dashed line. */
export default function PfColumnsChart({ columns, ma, lastClose }: { columns: PfColumn[]; ma: number | null; lastClose: number }) {
  if (!columns.length) return null;
  const top = Math.max(...columns.map((c) => c.top));
  const bottom = Math.min(...columns.map((c) => c.bottom));
  const rows = top - bottom + 1;
  const cell = Math.max(9, Math.min(16, Math.floor(420 / Math.max(rows, 1))));
  const left = 64;
  const width = left + columns.length * cell + 8;
  const height = rows * cell + 8;
  const y = (level: number) => (top - level) * cell + 4;
  // price of a level from any column that touches it (log boxes: interpolate from the extremes)
  const hi = columns.find((c) => c.top === top)!.topPrice;
  const lo = columns.find((c) => c.bottom === bottom)!.bottomPrice;
  const priceAt = (level: number) => lo * Math.pow(hi / lo, rows > 1 ? (level - bottom) / (top - bottom) : 0);
  const levelOf = (price: number) => bottom + (Math.log(price / lo) / Math.log(hi / lo)) * (top - bottom);
  const labelEvery = Math.max(1, Math.round(rows / 12));
  return (
    <div style={{ overflowX: "auto", width: "100%" }}>
      <svg width={width} height={height} role="img" aria-label="Point and figure chart" style={{ display: "block", fontFamily: "var(--font-mono, monospace)" }}>
        {Array.from({ length: rows }, (_, r) => top - r)
          .filter((lvl) => (top - lvl) % labelEvery === 0)
          .map((lvl) => (
            <g key={lvl}>
              <line x1={left} x2={width} y1={y(lvl) + cell / 2} y2={y(lvl) + cell / 2} stroke="var(--border)" strokeWidth={0.5} />
              <text x={left - 6} y={y(lvl) + cell / 2 + 3} fontSize={10} textAnchor="end" fill="var(--muted)">
                {priceAt(lvl).toLocaleString("en-IN", { maximumFractionDigits: priceAt(lvl) < 100 ? 2 : 0 })}
              </text>
            </g>
          ))}
        {columns.map((c, k) =>
          Array.from({ length: c.top - c.bottom + 1 }, (_, b) => c.bottom + b).map((lvl) => (
            <text key={`${k}-${lvl}`} x={left + k * cell + cell / 2} y={y(lvl) + cell * 0.8} fontSize={cell * 0.85} textAnchor="middle"
              fill={c.type === "X" ? "var(--green)" : "var(--red)"} fontWeight={600}>
              {c.type}
            </text>
          )),
        )}
        {ma && ma > lo && ma < hi ? (
          <line x1={left} x2={width} y1={y(levelOf(ma)) + cell / 2} y2={y(levelOf(ma)) + cell / 2} stroke="var(--amber, #c58a00)" strokeDasharray="5 4" strokeWidth={1.2} />
        ) : null}
        {lastClose > lo && lastClose < hi ? (
          <circle cx={left + (columns.length - 1) * cell + cell / 2} cy={y(levelOf(lastClose)) + cell / 2} r={3} fill="var(--text, #222)" />
        ) : null}
      </svg>
    </div>
  );
}
