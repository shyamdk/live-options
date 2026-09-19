"use client";

import { CandlestickSeries, ColorType, createChart, IChartApi, ISeriesApi, LineSeries, Time, UTCTimestamp } from "lightweight-charts";
import { PenTool, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { getPstrategyCandles } from "@/lib/api";
import type { ConsolidationBox, PstrategyData, PstrategyResolution } from "@/types/pstrategy";

const RESOLUTIONS: PstrategyResolution[] = ["1m", "5m", "15m"];
const REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_PSTRATEGY_REFRESH_SECONDS, 30);
const STORAGE_PREFIX = "live-options-pstrategy-lines";
// Pixel tolerance for "close enough to grab" when hit-testing the mouse
// against a drawn line's endpoints or body.
const HIT_PX = 8;

interface LinePoint {
  time: UTCTimestamp;
  price: number;
}

interface ManualLine {
  id: string;
  a: LinePoint;
  b: LinePoint;
}

function secondsToMs(value: string | undefined, fallbackSeconds: number): number {
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : fallbackSeconds * 1000;
}

function loadManualLines(resolution: PstrategyResolution): ManualLine[] {
  try {
    const raw = window.localStorage.getItem(`${STORAGE_PREFIX}-${resolution}`);
    return raw ? (JSON.parse(raw) as ManualLine[]) : [];
  } catch {
    return [];
  }
}

function saveManualLines(resolution: PstrategyResolution, lines: ManualLine[]): void {
  try {
    window.localStorage.setItem(`${STORAGE_PREFIX}-${resolution}`, JSON.stringify(lines));
  } catch {
    // Best-effort only -- a private window or full storage just means
    // manual lines won't survive a reload, not a functional break.
  }
}

export default function PstrategyPage() {
  const [resolution, setResolution] = useState<PstrategyResolution>("5m");

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <PenTool size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            pStrategy
          </h1>
          <p>
            XAUTUSD (gold) consolidation detection -- the last 4 candles are auto-marked with support/resistance
            when none of them is a momentum candle relative to recent volatility. Draw your own lines too, and drag
            to reposition them. Stage 1.
          </p>
        </div>
        <div className="toolbar">
          {RESOLUTIONS.map((r) => (
            <button
              key={r}
              type="button"
              className="button secondary"
              style={r === resolution ? { background: "var(--accent, #2368b6)", color: "#fff" } : undefined}
              onClick={() => setResolution(r)}
            >
              {r}
            </button>
          ))}
        </div>
      </header>
      <PstrategyChart resolution={resolution} />
    </section>
  );
}

function PstrategyChart({ resolution }: { resolution: PstrategyResolution }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const boxSeriesRef = useRef<ISeriesApi<"Line">[]>([]);
  const manualSeriesRef = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  const drawModeRef = useRef(false);
  const pendingPointRef = useRef<LinePoint | null>(null);
  const draggingRef = useRef<{ id: string; endpoint: "a" | "b" | "whole"; lastPrice: number } | null>(null);
  const manualLinesRef = useRef<ManualLine[]>([]);

  const [data, setData] = useState<PstrategyData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [manualLines, setManualLines] = useState<ManualLine[]>([]);
  const [drawMode, setDrawMode] = useState(false);

  useEffect(() => {
    drawModeRef.current = drawMode;
  }, [drawMode]);

  useEffect(() => {
    manualLinesRef.current = manualLines;
  }, [manualLines]);

  useEffect(() => {
    setManualLines(loadManualLines(resolution));
    setDrawMode(false);
  }, [resolution]);

  useEffect(() => {
    saveManualLines(resolution, manualLines);
  }, [resolution, manualLines]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const payload = await getPstrategyCandles(resolution);
        if (cancelled) return;
        if (payload.error) {
          setError(payload.error);
          return;
        }
        setData(payload);
        setError(null);
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : "Failed to load XAUTUSD candles.");
      }
    }
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [resolution]);

  // Chart lifecycle -- created once, reused across resolution switches
  // (only the data changes; the same candlestick series gets fresh data).
  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: containerRef.current.clientWidth,
      height: 420,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (time: Time) => formatIstDateTime(time) },
      localization: { timeFormatter: (time: Time) => formatIstDateTime(time) },
    });
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#168448",
      downColor: "#c93535",
      borderVisible: false,
      wickUpColor: "#168448",
      wickDownColor: "#c93535",
    });
    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;

    chart.subscribeClick((param) => {
      if (!drawModeRef.current || !param.point || param.time === undefined) return;
      const price = candleSeries.coordinateToPrice(param.point.y);
      if (price === null) return;
      const point: LinePoint = { time: param.time as UTCTimestamp, price };
      const pending = pendingPointRef.current;
      if (!pending) {
        pendingPointRef.current = point;
        return;
      }
      pendingPointRef.current = null;
      setManualLines((current) => [...current, { id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, a: pending, b: point }]);
      setDrawMode(false);
    });

    function pixelOf(point: LinePoint): { x: number; y: number } | null {
      const x = chart.timeScale().timeToCoordinate(point.time);
      const y = candleSeries.priceToCoordinate(point.price);
      if (x === null || y === null) return null;
      return { x, y };
    }

    function hitTest(mouseX: number, mouseY: number): { id: string; endpoint: "a" | "b" | "whole" } | null {
      for (const line of manualLinesRef.current) {
        const pa = pixelOf(line.a);
        const pb = pixelOf(line.b);
        if (!pa || !pb) continue;
        if (Math.hypot(mouseX - pa.x, mouseY - pa.y) <= HIT_PX) return { id: line.id, endpoint: "a" };
        if (Math.hypot(mouseX - pb.x, mouseY - pb.y) <= HIT_PX) return { id: line.id, endpoint: "b" };
        const minX = Math.min(pa.x, pb.x);
        const maxX = Math.max(pa.x, pb.x);
        if (mouseX >= minX - HIT_PX && mouseX <= maxX + HIT_PX && maxX > minX) {
          const t = (mouseX - pa.x) / (pb.x - pa.x);
          const expectedY = pa.y + t * (pb.y - pa.y);
          if (Math.abs(mouseY - expectedY) <= HIT_PX) return { id: line.id, endpoint: "whole" };
        }
      }
      return null;
    }

    function handleMouseDown(ev: MouseEvent) {
      if (drawModeRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const x = ev.clientX - rect.left;
      const y = ev.clientY - rect.top;
      const hit = hitTest(x, y);
      if (!hit) return;
      const price = candleSeries.coordinateToPrice(y);
      draggingRef.current = { id: hit.id, endpoint: hit.endpoint, lastPrice: price ?? 0 };
      ev.preventDefault();
    }

    function handleMouseMove(ev: MouseEvent) {
      const dragging = draggingRef.current;
      if (!dragging || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const x = ev.clientX - rect.left;
      const y = ev.clientY - rect.top;
      const time = chart.timeScale().coordinateToTime(x);
      const price = candleSeries.coordinateToPrice(y);
      if (price === null) return;

      setManualLines((current) =>
        current.map((line) => {
          if (line.id !== dragging.id) return line;
          if (dragging.endpoint === "whole") {
            const delta = price - dragging.lastPrice;
            return { ...line, a: { ...line.a, price: line.a.price + delta }, b: { ...line.b, price: line.b.price + delta } };
          }
          const updatedPoint: LinePoint = { time: (time as UTCTimestamp) ?? line[dragging.endpoint].time, price };
          return { ...line, [dragging.endpoint]: updatedPoint };
        }),
      );
      draggingRef.current = { ...dragging, lastPrice: price };
    }

    function handleMouseUp() {
      draggingRef.current = null;
    }

    const container = containerRef.current;
    container.addEventListener("mousedown", handleMouseDown);
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);

    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      container.removeEventListener("mousedown", handleMouseDown);
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
    };
  }, []);

  // Candle data + auto-detected consolidation boxes.
  useEffect(() => {
    if (!data || !candleSeriesRef.current || !chartRef.current) return;
    candleSeriesRef.current.setData(
      data.candles.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })),
    );

    for (const series of boxSeriesRef.current) chartRef.current.removeSeries(series);
    boxSeriesRef.current = [];
    for (const box of data.consolidations) {
      boxSeriesRef.current.push(addBoxLine(chartRef.current, box, "resistance"));
      boxSeriesRef.current.push(addBoxLine(chartRef.current, box, "support"));
    }
  }, [data]);

  // Manual lines -- diffed against the current series map so dragging
  // updates data in place instead of tearing down/recreating series.
  useEffect(() => {
    if (!chartRef.current) return;
    const chart = chartRef.current;
    const existing = manualSeriesRef.current;

    for (const id of existing.keys()) {
      if (!manualLines.some((l) => l.id === id)) {
        chart.removeSeries(existing.get(id)!);
        existing.delete(id);
      }
    }
    for (const line of manualLines) {
      let series = existing.get(line.id);
      if (!series) {
        series = chart.addSeries(LineSeries, { color: "#c9772f", lineWidth: 2, lastValueVisible: false, priceLineVisible: false });
        existing.set(line.id, series);
      }
      series.setData([
        { time: line.a.time, value: line.a.price },
        { time: line.b.time, value: line.b.price },
      ]);
    }
  }, [manualLines]);

  return (
    <div>
      {error ? <div className="alert error">{error}</div> : null}
      <div className="toolbar" style={{ margin: "0 0 8px" }}>
        <button
          type="button"
          className="button secondary"
          style={drawMode ? { background: "var(--accent, #2368b6)", color: "#fff" } : undefined}
          onClick={() => {
            pendingPointRef.current = null;
            setDrawMode((v) => !v);
          }}
        >
          <PenTool size={14} /> {drawMode ? "Click two points…" : "Draw line"}
        </button>
        <button type="button" className="button secondary" onClick={() => setManualLines([])} disabled={manualLines.length === 0}>
          <Trash2 size={14} /> Clear drawn lines
        </button>
        <span className="pcr-oi-caption" style={{ alignSelf: "center" }}>
          Blue = auto-detected support/resistance. Orange = your own lines -- drag an end to resize, drag the middle to
          shift the whole line.
        </span>
      </div>
      <div ref={containerRef} style={{ width: "100%" }} />
    </div>
  );
}

function addBoxLine(chart: IChartApi, box: ConsolidationBox, kind: "support" | "resistance"): ISeriesApi<"Line"> {
  const series = chart.addSeries(LineSeries, {
    color: "#2368b6",
    lineWidth: 2,
    lastValueVisible: false,
    priceLineVisible: false,
  });
  const value = box[kind];
  series.setData([
    { time: box.startTime as UTCTimestamp, value },
    { time: box.endTime as UTCTimestamp, value },
  ]);
  return series;
}

function formatIstDateTime(time: Time): string {
  if (typeof time !== "number") return String(time);
  return new Date(time * 1000).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
