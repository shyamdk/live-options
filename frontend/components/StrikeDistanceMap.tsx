"use client";

export type StrikeMapLeg = { key: string; strike: number; label: string; short: boolean };

const DEFAULT_MARKS = [0.5, 1, 1.5, 2, 2.5];

// Compact number line: spot in blue, green guide marks every `marks`% either
// side (above the line), each strike labelled with its % from spot (below).
export default function StrikeDistanceMap({
  id,
  spot,
  legs,
  marks = DEFAULT_MARKS,
}: {
  id: string;
  spot: number | null | undefined;
  legs: StrikeMapLeg[];
  marks?: number[];
}) {
  if (!spot || !legs.length) return null;
  const width = 900;
  const maxMark = Math.max(...marks) / 100;
  const values = [spot * (1 - maxMark), spot * (1 + maxMark), ...legs.map((l) => l.strike)];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min) * 0.04;
  const x = (value: number) => 16 + ((value - (min - pad)) / (max - min + 2 * pad)) * (width - 32);

  const labelMinGap = 120;
  let lastAt = -Infinity;
  let lastRow = 1;
  const labels = legs
    .map((leg) => ({
      ...leg,
      at: x(leg.strike),
      text: `${leg.label} (${((Math.abs(leg.strike - spot) / spot) * 100).toFixed(2)}%)`,
    }))
    .sort((a, b) => a.at - b.at)
    .map((item) => {
      const row = item.at - lastAt < labelMinGap && lastRow === 0 ? 1 : 0;
      lastAt = item.at;
      lastRow = row;
      return { ...item, row };
    });
  const axisY = 26;
  const labelsY = axisY + 17;
  const height = labelsY + (labels.some((l) => l.row === 1) ? 14 : 0) + 6;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      style={{ width: "100%", maxWidth: 980, height: "auto", display: "block", margin: "2px 0 8px" }}
      role="img"
      aria-label={`${id} strikes relative to spot`}
    >
      <line x1={8} x2={width - 8} y1={axisY} y2={axisY} stroke="var(--text)" strokeWidth={1} />
      {marks.flatMap((mark) =>
        [-1, 1].map((sign) => {
          const at = x(spot * (1 + (sign * mark) / 100));
          return (
            <g key={`m${sign}${mark}`}>
              <line x1={at} x2={at} y1={axisY - 5} y2={axisY} stroke="var(--green)" strokeWidth={1} />
              <text x={at} y={axisY - 8} textAnchor="middle" fontSize={9} fill="var(--green)">
                {mark}%
              </text>
            </g>
          );
        }),
      )}
      <line x1={x(spot)} x2={x(spot)} y1={axisY - 9} y2={axisY + 6} stroke="var(--blue)" strokeWidth={2.5} />
      <text x={x(spot)} y={axisY - 12} textAnchor="middle" fontSize={10} fontWeight={700} fill="var(--blue)">
        SPOT {Math.round(spot).toLocaleString("en-US")}
      </text>
      {labels.map((item) => (
        <g key={`s${item.key}`}>
          <line
            x1={item.at}
            x2={item.at}
            y1={axisY - 5}
            y2={axisY + 5}
            stroke={item.short ? "var(--red)" : "var(--green)"}
            strokeWidth={2}
          />
          <text
            x={Math.min(Math.max(item.at, 70), width - 70)}
            y={labelsY + item.row * 14}
            textAnchor="middle"
            fontSize={10}
            fill={item.short ? "var(--red)" : "var(--green)"}
          >
            {item.text}
          </text>
        </g>
      ))}
    </svg>
  );
}
