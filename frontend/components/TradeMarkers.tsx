"use client";

import type { IChartApi, ISeriesApi, MouseEventParams, SeriesMarker, SeriesType, Time, UTCTimestamp } from "lightweight-charts";
import { createSeriesMarkers } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

/**
 * One entry/exit/adjustment point drawn on a strategy chart. `title` and
 * `lines` are shown in a tooltip when the mouse is over the marker's candle.
 */
export type TradeNote = {
  time: number; // epoch seconds of the event
  kind: "entry" | "exit" | "adjust";
  label: string; // short text drawn next to the arrow
  title: string; // first line of the tooltip
  lines: string[]; // the reasons / details
  color?: string;
};

const KIND_STYLE = {
  entry: { position: "belowBar" as const, shape: "arrowUp" as const, color: "#0f6b78" },
  exit: { position: "aboveBar" as const, shape: "arrowDown" as const, color: "#7a8494" },
  adjust: { position: "aboveBar" as const, shape: "circle" as const, color: "#b7791f" },
};

/**
 * Draws `notes` as markers on `series` and returns a tooltip element that
 * shows the reasons when the crosshair is on (or next to) a marker's bar.
 * `bucketSeconds` is the chart's bar size; markers snap to the bar they
 * happened in. Render the returned element inside a position:relative
 * wrapper around the chart container.
 */
export function useTradeMarkers(
  chart: IChartApi | null,
  series: ISeriesApi<SeriesType> | null,
  notes: TradeNote[],
  bucketSeconds: number,
  barTimes?: number[],
) {
  const [tip, setTip] = useState<{ x: number; y: number; notes: TradeNote[] } | null>(null);
  const byBar = useRef<Map<number, TradeNote[]>>(new Map());
  const pluginRef = useRef<ReturnType<typeof createSeriesMarkers<Time>> | null>(null);
  const seriesRef = useRef<ISeriesApi<SeriesType> | null>(null);

  // snap an event to the bar it falls in: the last bar time <= event time
  const snap = (t: number): number => {
    if (barTimes && barTimes.length) {
      let lo = 0;
      let hi = barTimes.length - 1;
      if (t < barTimes[0]) return barTimes[0];
      while (lo < hi) {
        const mid = Math.ceil((lo + hi) / 2);
        if (barTimes[mid] <= t) lo = mid;
        else hi = mid - 1;
      }
      return barTimes[lo];
    }
    return Math.floor(t / bucketSeconds) * bucketSeconds;
  };

  useEffect(() => {
    if (!series) return;
    if (seriesRef.current !== series) {
      pluginRef.current?.detach();
      pluginRef.current = createSeriesMarkers(series as ISeriesApi<SeriesType, Time>, []);
      seriesRef.current = series;
    }
    const first = barTimes?.[0] ?? -Infinity;
    const last = barTimes && barTimes.length ? barTimes[barTimes.length - 1] + bucketSeconds : Infinity;
    const map = new Map<number, TradeNote[]>();
    const markers: SeriesMarker<Time>[] = [];
    for (const n of notes) {
      if (!n.time || n.time < first || n.time >= last) continue;
      const bar = snap(n.time);
      map.set(bar, [...(map.get(bar) ?? []), n]);
      const style = KIND_STYLE[n.kind];
      markers.push({ time: bar as UTCTimestamp, position: style.position, shape: style.shape, color: n.color ?? style.color, text: n.label });
    }
    byBar.current = map;
    pluginRef.current?.setMarkers(markers.sort((a, b) => (a.time as number) - (b.time as number)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, notes, bucketSeconds, barTimes]);

  useEffect(() => {
    if (!chart) return;
    const onMove = (param: MouseEventParams<Time>) => {
      if (!param.point || param.time === undefined) {
        setTip(null);
        return;
      }
      const t = Number(param.time);
      const hits = [t, t - bucketSeconds, t + bucketSeconds].flatMap((k) => byBar.current.get(k) ?? []);
      setTip(hits.length ? { x: param.point.x, y: param.point.y, notes: hits } : null);
    };
    chart.subscribeCrosshairMove(onMove);
    return () => chart.unsubscribeCrosshairMove(onMove);
  }, [chart, bucketSeconds]);

  useEffect(
    () => () => {
      pluginRef.current = null;
      seriesRef.current = null;
    },
    [],
  );

  return tip ? <MarkerTooltip x={tip.x} y={tip.y} notes={tip.notes} /> : null;
}

export function MarkerTooltip({ x, y, notes }: { x: number; y: number; notes: TradeNote[] }) {
  return (
    <div
      style={{
        position: "absolute",
        left: Math.max(0, x + 14),
        top: Math.max(0, y - 20),
        maxWidth: 340,
        background: "var(--surface, #fff)",
        border: "1px solid var(--line)",
        borderRadius: 6,
        boxShadow: "0 4px 14px rgba(0,0,0,0.12)",
        padding: "8px 10px",
        fontSize: 12,
        zIndex: 5,
        pointerEvents: "none",
        transform: x > 600 ? "translateX(calc(-100% - 28px))" : undefined,
      }}
    >
      {notes.map((n, i) => (
        <div key={i} style={{ marginBottom: i < notes.length - 1 ? 8 : 0 }}>
          <strong style={{ color: n.color }}>
            {n.kind === "entry" ? "▲ " : n.kind === "exit" ? "▼ " : "● "}
            {n.title}
          </strong>
          {n.lines.filter(Boolean).map((line, j) => (
            <div key={j}>{line}</div>
          ))}
        </div>
      ))}
    </div>
  );
}

export function istTime(epoch: number | null | undefined): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
}
