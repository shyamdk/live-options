"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  IChartApi,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  LineSeries,
  SeriesMarker,
  Time,
  UTCTimestamp,
} from "lightweight-charts";
import { PenTool, RefreshCw, Trash2, TrendingUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { getPstrategyCandles } from "@/lib/api";
import type { ConsolidationBox, EmaSettings, ExitReason, PstrategyData, PstrategyResolution, PstrategyTrade } from "@/types/pstrategy";

const TRADES_RESOLUTION: PstrategyResolution = "5m";

const RESOLUTIONS: PstrategyResolution[] = ["1m", "5m", "15m"];
const REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_PSTRATEGY_REFRESH_SECONDS, 30);
const STORAGE_PREFIX = "live-options-pstrategy-lines";
const EMA_SETTINGS_KEY = "live-options-pstrategy-ema-settings";
const DEFAULT_EMA_SETTINGS: EmaSettings = { enabled: true, fast: 9, slow: 20 };
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

function loadEmaSettings(): EmaSettings {
  try {
    const raw = window.localStorage.getItem(EMA_SETTINGS_KEY);
    if (raw) return { ...DEFAULT_EMA_SETTINGS, ...(JSON.parse(raw) as Partial<EmaSettings>) };
  } catch {
    // fall through to defaults
  }
  return DEFAULT_EMA_SETTINGS;
}

function saveEmaSettings(settings: EmaSettings): void {
  try {
    window.localStorage.setItem(EMA_SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    // Best-effort only.
  }
}

export default function PstrategyPage() {
  const [resolution, setResolution] = useState<PstrategyResolution>("5m");
  const [emaSettings, setEmaSettings] = useState<EmaSettings>(DEFAULT_EMA_SETTINGS);
  const [emaFastInput, setEmaFastInput] = useState(String(DEFAULT_EMA_SETTINGS.fast));
  const [emaSlowInput, setEmaSlowInput] = useState(String(DEFAULT_EMA_SETTINGS.slow));

  const [tradesData, setTradesData] = useState<PstrategyData | null>(null);
  const [tradesLoading, setTradesLoading] = useState(true);
  const [tradesError, setTradesError] = useState<string | null>(null);

  useEffect(() => {
    const loaded = loadEmaSettings();
    setEmaSettings(loaded);
    setEmaFastInput(String(loaded.fast));
    setEmaSlowInput(String(loaded.slow));
  }, []);

  useEffect(() => {
    saveEmaSettings(emaSettings);
  }, [emaSettings]);

  function commitEmaPeriods() {
    const fast = Math.max(2, Math.min(200, Math.round(Number(emaFastInput)) || DEFAULT_EMA_SETTINGS.fast));
    const slow = Math.max(2, Math.min(200, Math.round(Number(emaSlowInput)) || DEFAULT_EMA_SETTINGS.slow));
    if (fast >= slow) {
      setEmaFastInput(String(emaSettings.fast));
      setEmaSlowInput(String(emaSettings.slow));
      return;
    }
    setEmaFastInput(String(fast));
    setEmaSlowInput(String(slow));
    setEmaSettings((current) => ({ ...current, fast, slow }));
  }

  // Paper trades always run at 5m, independent of whichever resolution
  // tab is selected for chart viewing.
  async function loadTrades() {
    setTradesLoading(true);
    try {
      const payload = await getPstrategyCandles(TRADES_RESOLUTION, emaSettings);
      setTradesData(payload);
      setTradesError(payload.error ?? null);
    } catch (exc) {
      setTradesError(exc instanceof Error ? exc.message : "Failed to load paper trades.");
    } finally {
      setTradesLoading(false);
    }
  }

  useEffect(() => {
    loadTrades();
    const timer = window.setInterval(loadTrades, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [emaSettings]);

  const trades = tradesData?.trades ?? [];

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <PenTool size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            pStrategy
          </h1>
          <p>
            XAUTUSD (gold) consolidation detection -- a variable-length run of narrow candles gets a
            support/resistance box, and the candle that breaks out of it is marked as a momentum candle (when EMA
            cross is on, it must also close on the correct side of the slow EMA). Paper trades run at the 5m
            timeframe using the proposed entry/exit rule. Draw your own lines on any timeframe and drag to
            reposition them.
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

      <div className="toolbar" style={{ margin: "0 0 8px" }}>
        <button
          type="button"
          className="button secondary"
          style={emaSettings.enabled ? { background: "var(--accent, #2368b6)", color: "#fff" } : undefined}
          onClick={() => setEmaSettings((current) => ({ ...current, enabled: !current.enabled }))}
        >
          <TrendingUp size={14} /> EMA cross: {emaSettings.enabled ? "ON" : "OFF"}
        </button>
        {emaSettings.enabled ? (
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <input
              type="number"
              value={emaFastInput}
              onChange={(e) => setEmaFastInput(e.target.value)}
              onBlur={commitEmaPeriods}
              onKeyDown={(e) => e.key === "Enter" && commitEmaPeriods()}
              style={{ width: 52 }}
              min={2}
              max={200}
              aria-label="Fast EMA period"
            />
            <span>/</span>
            <input
              type="number"
              value={emaSlowInput}
              onChange={(e) => setEmaSlowInput(e.target.value)}
              onBlur={commitEmaPeriods}
              onKeyDown={(e) => e.key === "Enter" && commitEmaPeriods()}
              style={{ width: 52 }}
              min={2}
              max={200}
              aria-label="Slow EMA period"
            />
          </span>
        ) : null}
        <span className="pcr-oi-caption" style={{ alignSelf: "center" }}>
          Applies to all charts and to the paper trades below.
          {emaSettings.enabled ? ` EMA${emaSettings.fast} (teal) / EMA${emaSettings.slow} (violet).` : ""}
        </span>
      </div>

      <PaperTradesPanel
        trades={trades}
        loading={tradesLoading}
        error={tradesError}
        onRefresh={loadTrades}
        title="Live trades"
        variant="open"
        leverage={tradesData?.leverage ?? 50}
      />

      <PstrategyChart resolution={resolution} emaSettings={emaSettings} />

      <PaperTradesPanel
        trades={trades}
        loading={tradesLoading}
        error={tradesError}
        onRefresh={loadTrades}
        title="Closed trades"
        variant="closed"
        leverage={tradesData?.leverage ?? 50}
      />
    </section>
  );
}

const EXIT_REASON_LABEL: Record<ExitReason, string> = { target: "Target", stop: "Stop", ema_exit: "Crossed EMA20" };

function fmtDateTime(epochSeconds: number | null): string {
  if (!epochSeconds) return "—";
  return new Date(epochSeconds * 1000).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function fmtPriceValue(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
}

function fmtPnlValue(pct: number | null | undefined): string {
  if (pct === null || pct === undefined) return "—";
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(3)}%`;
}

function PaperTradesPanel({
  trades,
  loading,
  error,
  onRefresh,
  title,
  variant,
  leverage,
}: {
  trades: PstrategyTrade[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  title: string;
  variant: "open" | "closed";
  leverage: number;
}) {
  const filtered = trades
    .filter((t) => t.status === variant)
    .sort((a, b) => (b.exitTime ?? b.entryTime) - (a.exitTime ?? a.entryTime));

  return (
    <div className="pcr-oi-section">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>
          {title} <span className="pcr-oi-caption">(XAUTUSD, 5m)</span>
        </h3>
        <button type="button" className="button secondary" onClick={onRefresh} disabled={loading}>
          <RefreshCw size={14} /> {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      <p className="pcr-oi-caption" style={{ margin: "4px 0 10px" }}>
        Simulated only -- replayed deterministically from the proposed entry/exit rule against 5m candle history. No
        real orders are placed. P&amp;L is the return on margin at {leverage}x leverage (matching Delta's XAUTUSD
        perpetual), not the raw price move.
      </p>
      {error ? <div className="alert error">{error}</div> : null}
      {filtered.length === 0 ? (
        <p className="pcr-oi-caption">{variant === "open" ? "No open positions right now." : "No closed trades yet."}</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Side</th>
                <th>Entry time</th>
                <th>Entry price</th>
                {variant === "open" ? (
                  <>
                    <th>Current price</th>
                    <th>Current P&amp;L ({leverage}x)</th>
                    <th>Stop</th>
                  </>
                ) : (
                  <>
                    <th>Exit time</th>
                    <th>Exit price</th>
                    <th>Exit reason</th>
                    <th>P&amp;L ({leverage}x)</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {filtered.map((t, i) => {
                const isOpen = variant === "open";
                const pnl = isOpen ? t.unrealizedPnlPercent : t.pnlPercent;
                return (
                  <tr key={`${t.entryTime}-${i}`}>
                    <td>
                      <span className={`badge ${t.side === "long" ? "buy" : "sell"}`}>{t.side === "long" ? "LONG" : "SHORT"}</span>
                    </td>
                    <td>{fmtDateTime(t.entryTime)}</td>
                    <td>{fmtPriceValue(t.entryPrice)}</td>
                    {isOpen ? (
                      <>
                        <td>{fmtPriceValue(t.currentPrice)}</td>
                        <td style={{ color: (pnl ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>{fmtPnlValue(pnl)}</td>
                        <td>{fmtPriceValue(t.stopLoss)}</td>
                      </>
                    ) : (
                      <>
                        <td>{fmtDateTime(t.exitTime)}</td>
                        <td>{fmtPriceValue(t.exitPrice)}</td>
                        <td>{t.exitReason ? EXIT_REASON_LABEL[t.exitReason] : "—"}</td>
                        <td style={{ color: (pnl ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>{fmtPnlValue(pnl)}</td>
                      </>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function PstrategyChart({ resolution, emaSettings }: { resolution: PstrategyResolution; emaSettings: EmaSettings }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const rsiContainerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const ema9SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ema20SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const boxSeriesRef = useRef<ISeriesApi<"Line">[]>([]);
  const manualSeriesRef = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  const rsiChartRef = useRef<IChartApi | null>(null);
  const rsiSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const closeByTimeRef = useRef<Map<UTCTimestamp, number>>(new Map());
  const rsiByTimeRef = useRef<Map<UTCTimestamp, number>>(new Map());
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
        const payload = await getPstrategyCandles(resolution, emaSettings);
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
  }, [resolution, emaSettings]);

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
    const ema9Series = chart.addSeries(LineSeries, { color: "#14b8a6", lineWidth: 2, title: "EMA fast" });
    const ema20Series = chart.addSeries(LineSeries, { color: "#8b5cf6", lineWidth: 2, title: "EMA slow" });

    const rsiChart = createChart(rsiContainerRef.current!, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: rsiContainerRef.current!.clientWidth,
      height: 140,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (time: Time) => formatIstDateTime(time) },
      localization: { timeFormatter: (time: Time) => formatIstDateTime(time) },
    });
    const rsiSeries = rsiChart.addSeries(LineSeries, { color: "#c9772f", lineWidth: 2, title: "RSI 14" });
    rsiSeries.createPriceLine({ price: 70, color: "#c93535", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "70" });
    rsiSeries.createPriceLine({ price: 30, color: "#168448", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "30" });
    rsiChart.priceScale("right").applyOptions({ autoScale: false });
    rsiSeries.priceScale().setVisibleRange({ from: 0, to: 100 });

    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) rsiChart.timeScale().setVisibleLogicalRange(range);
    });
    rsiChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) chart.timeScale().setVisibleLogicalRange(range);
    });
    chart.subscribeCrosshairMove((param) => {
      if (!param.point || param.time === undefined) {
        rsiChart.clearCrosshairPosition();
        return;
      }
      const t = param.time as UTCTimestamp;
      rsiChart.setCrosshairPosition(rsiByTimeRef.current.get(t) ?? 50, t, rsiSeries);
    });
    rsiChart.subscribeCrosshairMove((param) => {
      if (!param.point || param.time === undefined) {
        chart.clearCrosshairPosition();
        return;
      }
      const t = param.time as UTCTimestamp;
      chart.setCrosshairPosition(closeByTimeRef.current.get(t) ?? 0, t, candleSeries);
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    ema9SeriesRef.current = ema9Series;
    ema20SeriesRef.current = ema20Series;
    rsiChartRef.current = rsiChart;
    rsiSeriesRef.current = rsiSeries;
    markersRef.current = createSeriesMarkers(candleSeries, []);

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
      if (rsiContainerRef.current) rsiChart.applyOptions({ width: rsiContainerRef.current.clientWidth });
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      container.removeEventListener("mousedown", handleMouseDown);
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
      markersRef.current?.detach();
      chart.remove();
      rsiChart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      ema9SeriesRef.current = null;
      ema20SeriesRef.current = null;
      rsiChartRef.current = null;
      rsiSeriesRef.current = null;
      markersRef.current = null;
    };
  }, []);

  // Candle data + auto-detected consolidation boxes + EMA9/20 + markers.
  useEffect(() => {
    if (!data || !candleSeriesRef.current || !chartRef.current) return;
    const times = data.candles.map((c) => c.time as UTCTimestamp);
    candleSeriesRef.current.setData(
      data.candles.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })),
    );
    ema9SeriesRef.current?.setData(data.emaEnabled ? numericSeries(times, data.emaFastValues) : []);
    ema20SeriesRef.current?.setData(data.emaEnabled ? numericSeries(times, data.emaSlowValues) : []);
    rsiSeriesRef.current?.setData(numericSeries(times, data.rsi));

    closeByTimeRef.current = new Map(times.map((t, i) => [t, data.candles[i].close]));
    rsiByTimeRef.current = new Map(
      times.map((t, i) => [t, data.rsi[i]]).filter((entry): entry is [UTCTimestamp, number] => entry[1] !== null),
    );

    for (const series of boxSeriesRef.current) chartRef.current.removeSeries(series);
    boxSeriesRef.current = [];
    for (const box of data.consolidations) {
      boxSeriesRef.current.push(addBoxLine(chartRef.current, box, "resistance"));
      boxSeriesRef.current.push(addBoxLine(chartRef.current, box, "support"));
    }

    markersRef.current?.setMarkers(buildMarkers(data));
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
          Blue lines = support/resistance. Orange lines = your own -- drag an end to resize, the middle to shift.
          {emaSettings.enabled ? ` EMA${emaSettings.fast} (teal) / EMA${emaSettings.slow} (violet), crossovers as circles.` : ""}{" "}
          EN = entry (arrow = confirmed momentum candle). EX = exit -- when EMA cross is on (grey), the trade is
          held unconditionally as long as it stays on the favorable side of the slow EMA and exits the moment it
          closes on the wrong side; stop/target (red/green) only apply with EMA cross off.
        </span>
      </div>
      <div ref={containerRef} style={{ width: "100%" }} />
      <div className="subtext" style={{ margin: "8px 0 4px" }}>
        RSI (14)
      </div>
      <div ref={rsiContainerRef} style={{ width: "100%" }} />
    </div>
  );
}

function numericSeries(times: UTCTimestamp[], values: (number | null)[]): { time: UTCTimestamp; value: number }[] {
  return values
    .map((value, i) => (value === null ? null : { time: times[i], value }))
    .filter((point): point is { time: UTCTimestamp; value: number } => point !== null);
}

const EXIT_COLOR: Record<ExitReason, string> = { target: "#168448", stop: "#c93535", ema_exit: "#8391a3" };

function buildMarkers(data: PstrategyData): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = [];
  // EN always lands on the same candle as a confirmed momentum candle (by
  // construction -- entry *is* that candle's close), so a separate "M"
  // marker there was pure duplicate clutter. EN/EX sit on opposite sides
  // of the candle (matching Crypto-Swing's entry/exit marker convention)
  // so they don't stack when a trade opens and closes in quick succession.
  for (const t of data.trades) {
    const isLong = t.side === "long";
    markers.push({
      time: t.entryTime as UTCTimestamp,
      position: isLong ? "belowBar" : "aboveBar",
      color: isLong ? "#168448" : "#c93535",
      shape: isLong ? "arrowUp" : "arrowDown",
      text: "EN",
    });
    if (t.status === "closed" && t.exitTime !== null && t.exitReason) {
      markers.push({
        time: t.exitTime as UTCTimestamp,
        position: isLong ? "aboveBar" : "belowBar",
        color: EXIT_COLOR[t.exitReason],
        shape: "circle",
        text: "EX",
      });
    }
  }
  for (const c of data.crossovers) {
    const bullish = c.direction === "bullish";
    markers.push({
      time: c.time as UTCTimestamp,
      position: "inBar",
      color: bullish ? "#168448" : "#c93535",
      shape: "circle",
      text: `${data.emaFast}×${data.emaSlow}${bullish ? "↑" : "↓"}`,
    });
  }
  markers.sort((a, b) => (a.time as number) - (b.time as number));
  return markers;
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
