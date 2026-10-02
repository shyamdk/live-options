"use client";

import { useState } from "react";

import type { VarahaPayoffPoint } from "@/types/varaha";

function fmtNum(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function fmtInr(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value < 0 ? "−" : ""}₹${fmtNum(Math.abs(value))}`;
}

export default function VarahaPayoffChart({
  chartId,
  label,
  points,
  breakevens,
  spot,
  expectedMove,
  lossZone,
}: {
  chartId: string;
  label: string;
  points: VarahaPayoffPoint[];
  breakevens: number[];
  spot: number;
  expectedMove: number | null;
  lossZone?: [number, number] | null;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 900;
  const height = 320;
  const pad = { left: 64, right: 16, top: 16, bottom: 30 };
  if (points.length < 2) return null;

  const xMin = points[0].price;
  const xMax = points[points.length - 1].price;
  const values = points.flatMap((p) => [p.expiry, p.today]);
  const rawMin = Math.min(0, ...values);
  const rawMax = Math.max(0, ...values);
  const span = rawMax - rawMin || 1;
  const yMin = rawMin - span * 0.08;
  const yMax = rawMax + span * 0.08;
  const x = (price: number) => pad.left + ((price - xMin) / (xMax - xMin)) * (width - pad.left - pad.right);
  const y = (value: number) => pad.top + ((yMax - value) / (yMax - yMin)) * (height - pad.top - pad.bottom);
  const zeroY = y(0);

  const expiryPath = points.map((p, i) => `${i ? "L" : "M"}${x(p.price).toFixed(1)},${y(p.expiry).toFixed(1)}`).join(" ");
  const todayPath = points.map((p, i) => `${i ? "L" : "M"}${x(p.price).toFixed(1)},${y(p.today).toFixed(1)}`).join(" ");
  const areaPath = `${expiryPath} L${x(xMax).toFixed(1)},${zeroY.toFixed(1)} L${x(xMin).toFixed(1)},${zeroY.toFixed(1)} Z`;
  const xTicks = Array.from({ length: 7 }, (_, i) => xMin + ((xMax - xMin) * i) / 6);
  const yTicks = Array.from({ length: 5 }, (_, i) => yMin + ((yMax - yMin) * i) / 4);
  const clipId = `clip-${chartId.replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const hovered = hover != null ? points[hover] : null;
  const band = (multiple: number) =>
    expectedMove ? [Math.max(xMin, spot - multiple * expectedMove), Math.min(xMax, spot + multiple * expectedMove)] : null;
  const band1 = band(1);
  const band2 = band(2);

  function onMove(event: React.MouseEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * width;
    const price = xMin + ((px - pad.left) / (width - pad.left - pad.right)) * (xMax - xMin);
    const index = Math.round(((price - xMin) / (xMax - xMin)) * (points.length - 1));
    setHover(index >= 0 && index < points.length ? index : null);
  }

  return (
    <div>
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", fontSize: 12, marginBottom: 4 }}>
        <span>
          <span style={{ color: "var(--green)", fontWeight: 700 }}>━</span> Expiry payoff
        </span>
        <span>
          <span style={{ color: "var(--blue)", fontWeight: 700 }}>━</span> Today (theoretical)
        </span>
        <span>
          <span style={{ color: "rgba(35,104,182,0.35)", fontWeight: 700 }}>■</span> ±1× / ±2× expected move
        </span>
        {lossZone ? (
          <span>
            <span style={{ color: "rgba(201,53,53,0.6)", fontWeight: 700 }}>┆</span> Central loss V {fmtNum(lossZone[0])} – {fmtNum(lossZone[1])}
          </span>
        ) : null}
        {hovered ? (
          <span style={{ marginLeft: "auto" }}>
            NIFTY {fmtNum(hovered.price)} · expiry {fmtInr(hovered.expiry)} · today {fmtInr(hovered.today)}
          </span>
        ) : null}
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        style={{ width: "100%", height: "auto", display: "block", background: "var(--panel)" }}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label={`Payoff chart for ${label}`}
      >
        <defs>
          <clipPath id={`${clipId}-above`}>
            <rect x={0} y={0} width={width} height={zeroY} />
          </clipPath>
          <clipPath id={`${clipId}-below`}>
            <rect x={0} y={zeroY} width={width} height={height - zeroY} />
          </clipPath>
        </defs>
        {band2 ? (
          <rect x={x(band2[0])} y={pad.top} width={x(band2[1]) - x(band2[0])} height={height - pad.top - pad.bottom} fill="rgba(35,104,182,0.06)" />
        ) : null}
        {band1 ? (
          <rect x={x(band1[0])} y={pad.top} width={x(band1[1]) - x(band1[0])} height={height - pad.top - pad.bottom} fill="rgba(35,104,182,0.10)" />
        ) : null}
        {yTicks.map((tick) => (
          <g key={`y${tick}`}>
            <line x1={pad.left} x2={width - pad.right} y1={y(tick)} y2={y(tick)} stroke="var(--line-soft)" />
            <text x={pad.left - 6} y={y(tick) + 4} textAnchor="end" fontSize={11} fill="var(--muted)">
              {fmtInr(Math.round(tick / 100) * 100)}
            </text>
          </g>
        ))}
        {xTicks.map((tick) => (
          <text key={`x${tick}`} x={x(tick)} y={height - 10} textAnchor="middle" fontSize={11} fill="var(--muted)">
            {fmtNum(Math.round(tick / 50) * 50)}
          </text>
        ))}
        <path d={areaPath} fill="rgba(22,132,72,0.18)" clipPath={`url(#${clipId}-above)`} />
        <path d={areaPath} fill="rgba(201,53,53,0.18)" clipPath={`url(#${clipId}-below)`} />
        <line x1={pad.left} x2={width - pad.right} y1={zeroY} y2={zeroY} stroke="var(--muted)" />
        <path d={expiryPath} fill="none" stroke="var(--green)" strokeWidth={2} clipPath={`url(#${clipId}-above)`} />
        <path d={expiryPath} fill="none" stroke="var(--red)" strokeWidth={2} clipPath={`url(#${clipId}-below)`} />
        <path d={todayPath} fill="none" stroke="var(--blue)" strokeWidth={1.5} />
        {lossZone ? (
          <rect
            x={x(Math.max(xMin, lossZone[0]))}
            y={pad.top}
            width={Math.max(0, x(Math.min(xMax, lossZone[1])) - x(Math.max(xMin, lossZone[0])))}
            height={height - pad.top - pad.bottom}
            fill="rgba(201,53,53,0.07)"
            stroke="rgba(201,53,53,0.45)"
            strokeDasharray="4 3"
          />
        ) : null}
        {breakevens
          .filter((b) => b >= xMin && b <= xMax)
          .map((b, i) => (
            <g key={`be${b}`}>
              <line x1={x(b)} x2={x(b)} y1={pad.top} y2={height - pad.bottom} stroke="var(--muted)" strokeDasharray="3 3" />
              <text x={x(b) + 3} y={pad.top + 10 + (i % 2) * 12} fontSize={10} fill="var(--muted)">
                BE {fmtNum(b)}
              </text>
            </g>
          ))}
        <line x1={x(spot)} x2={x(spot)} y1={pad.top} y2={height - pad.bottom} stroke="var(--blue)" strokeWidth={1.5} />
        <text x={x(spot) + 3} y={height - pad.bottom - 4} fontSize={10} fill="var(--blue)">
          Spot {fmtNum(spot)}
        </text>
        {hovered ? (
          <g>
            <line x1={x(hovered.price)} x2={x(hovered.price)} y1={pad.top} y2={height - pad.bottom} stroke="var(--text)" strokeOpacity={0.3} />
            <circle cx={x(hovered.price)} cy={y(hovered.expiry)} r={3.5} fill={hovered.expiry >= 0 ? "var(--green)" : "var(--red)"} />
            <circle cx={x(hovered.price)} cy={y(hovered.today)} r={3.5} fill="var(--blue)" />
          </g>
        ) : null}
      </svg>
    </div>
  );
}
