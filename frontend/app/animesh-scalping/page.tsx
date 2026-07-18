"use client";

import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  ISeriesMarkersPluginApi,
  LineStyle,
  SeriesMarker,
  Time,
  UTCTimestamp,
  createChart,
  createSeriesMarkers,
  IChartApi,
  ISeriesApi,
  LineSeries,
} from "lightweight-charts";
import { RefreshCcw, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  approveAnimeshSignal,
  getAnimeshCandles,
  getAnimeshSessionDetail,
  getAnimeshSessions,
  getAnimeshState,
} from "@/lib/api";
import type {
  AnimeshCandle,
  AnimeshSession,
  AnimeshSessionDetail,
  AnimeshSide,
  AnimeshState,
  AnimeshTrade,
  AnimeshTradeLeg,
} from "@/types/animesh";

const moneyFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const STATE_REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_ANIMESH_STATE_REFRESH_SECONDS, 5);
const CANDLES_REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_ANIMESH_CANDLES_REFRESH_SECONDS, 15);

export default function AnimeshScalpingPage() {
  const [state, setState] = useState<AnimeshState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [approvingId, setApprovingId] = useState<number | null>(null);
  const [sessions, setSessions] = useState<AnimeshSession[]>([]);
  const [selectedDetail, setSelectedDetail] = useState<AnimeshSessionDetail | null>(null);

  async function loadState() {
    try {
      setState(await getAnimeshState());
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load animesh-scalping state.");
    } finally {
      setLoading(false);
    }
  }

  async function loadSessions() {
    try {
      const payload = await getAnimeshSessions();
      setSessions(payload.sessions);
    } catch {
      // Session history is secondary; ignore failures here.
    }
  }

  useEffect(() => {
    loadState();
    loadSessions();
    const timer = window.setInterval(loadState, STATE_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  async function handleApprove(signalId: number, label: string) {
    if (!window.confirm(`Approve ${label}? This sends an order (or simulates a paper fill) immediately.`)) return;
    setApprovingId(signalId);
    setMessage(null);
    setError(null);
    try {
      const result = await approveAnimeshSignal(signalId);
      setMessage(`Signal #${signalId} ${String(result.status ?? "processed")}.`);
      await loadState();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to approve signal.");
    } finally {
      setApprovingId(null);
    }
  }

  async function openSession(sessionId: string) {
    try {
      setSelectedDetail(await getAnimeshSessionDetail(sessionId));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load session detail.");
    }
  }

  const mode = state?.mode ?? "PAPER";
  const running = state?.status === "RUNNING";
  const dailyBias = running ? state.dailyBias : null;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>animesh-scalping</h1>
          <p>Daily HA bias + MACD(8,21,8) crossover scalp — 1m candles, 3 lots (65 each), index-price driven</p>
        </div>
        <div className="toolbar">
          <span className={mode === "LIVE" ? "status-live on" : "status-live"}>{mode}</span>
          {running ? (
            <>
              <span className={`risk-pill ${state.wsConnected ? "target" : "stopLoss"}`}>
                {state.wsConnected ? "Spot Live" : "Reconnecting"} · {money(state.spot)}
              </span>
              <span className="risk-pill">{dailyBias ? `Bias: ${dailyBias} only today` : "Bias: undetermined"}</span>
            </>
          ) : (
            <span className="risk-pill">Not started</span>
          )}
          <button className="icon-button" type="button" title="Refresh" onClick={loadState} disabled={loading}>
            <RefreshCcw size={16} />
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}

      <div className="ema5-grid">
        <SidePanel side="PE" label="PE — Short Setup" state={state} approvingId={approvingId} onApprove={handleApprove} />
        <SidePanel side="CE" label="CE — Long Setup" state={state} approvingId={approvingId} onApprove={handleApprove} />
      </div>

      <section className="table-section">
        <div className="section-title">
          <h2>Past Sessions</h2>
          <span>{sessions.length}</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Mode</th>
                <th>Bias</th>
                <th>Status</th>
                <th>PE trades / SL streak</th>
                <th>CE trades / SL streak</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((session) => (
                <tr key={session.id}>
                  <td>{session.sessionDate}</td>
                  <td>{session.mode}</td>
                  <td>{session.dailyBias ?? "-"}</td>
                  <td>{session.status}</td>
                  <td>
                    {session.peTradesCount} / {session.peConsecutiveSl}
                    {session.peHalted ? " (halted)" : ""}
                  </td>
                  <td>
                    {session.ceTradesCount} / {session.ceConsecutiveSl}
                    {session.ceHalted ? " (halted)" : ""}
                  </td>
                  <td>
                    <button className="icon-button" type="button" title="View session" onClick={() => openSession(session.id)}>
                      <ShieldCheck size={14} />
                    </button>
                  </td>
                </tr>
              ))}
              {!sessions.length ? (
                <tr>
                  <td colSpan={7}>No sessions yet.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      {selectedDetail ? <SessionDetailCard detail={selectedDetail} onClose={() => setSelectedDetail(null)} /> : null}
    </section>
  );
}

function SidePanel({
  side,
  label,
  state,
  approvingId,
  onApprove,
}: {
  side: AnimeshSide;
  label: string;
  state: AnimeshState | null;
  approvingId: number | null;
  onApprove: (signalId: number, label: string) => void;
}) {
  const running = state?.status === "RUNNING";
  const sideState = running ? state.sides[side] : null;
  const pendingSignals = running ? state.pendingSignals.filter((s) => s.side === side) : [];
  const openTrade = sideState?.openTrade ?? null;
  const trades = sideState?.trades ?? [];
  const isBiasActive = sideState?.isBiasActive ?? false;

  return (
    <section className="gb-panel ema5-panel">
      <div className="section-title">
        <h2>{label}</h2>
        {sideState?.halted ? <span className="risk-pill stopLoss">Halted</span> : null}
        {running && !isBiasActive ? <span className="risk-pill">Not active today</span> : null}
      </div>
      <div className="gb-status-row">
        <span>
          Trades today: <strong>{sideState?.tradesCount ?? 0}</strong>
        </span>
        <span>Consecutive SL: {sideState?.consecutiveSl ?? 0}</span>
        {sideState?.crossoverCandle ? (
          <span className="subtext">
            Crossover candle H {money(sideState.crossoverCandle.high)} / L {money(sideState.crossoverCandle.low)} at{" "}
            {formatCandleTime(sideState.crossoverCandle.time)}
          </span>
        ) : (
          <span className="subtext">No active crossover candle</span>
        )}
      </div>

      <AnimeshChart side={side} openTrade={openTrade} trades={trades} />

      {pendingSignals.length ? (
        <div className="alert warning">
          <strong>{pendingSignals.length} signal(s) awaiting approval</strong>
          <ul className="gb-signal-list">
            {pendingSignals.map((signal) => {
              const payload = (signal.payload ?? {}) as Record<string, unknown>;
              const actionLabel = signal.kind === "ENTRY" ? "ENTRY" : String(payload.action ?? "EXIT");
              return (
                <li key={signal.id}>
                  <span>
                    {actionLabel} · strike {signal.strike ?? ""} · index {money(signal.indexLevel)}
                  </span>
                  <button
                    className="icon-button approve"
                    type="button"
                    title="Approve"
                    onClick={() => onApprove(signal.id, `${side} ${actionLabel} at ${money(signal.indexLevel)}`)}
                    disabled={approvingId === signal.id}
                  >
                    <ShieldCheck size={15} />
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      <PaperTradesTable side={side} state={state} />
    </section>
  );
}

function AnimeshChart({ side, openTrade, trades }: { side: AnimeshSide; openTrade: AnimeshTrade | null; trades: AnimeshTrade[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const bandHighRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bandLowRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bandMedianRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const signalLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const histogramRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  const [candles, setCandles] = useState<AnimeshCandle[]>([]);
  const [macd, setMacd] = useState<(number | null)[]>([]);
  const [signal, setSignal] = useState<(number | null)[]>([]);
  const [histogram, setHistogram] = useState<(number | null)[]>([]);
  const [bandHigh, setBandHigh] = useState<(number | null)[]>([]);
  const [bandLow, setBandLow] = useState<(number | null)[]>([]);
  const [bandMedian, setBandMedian] = useState<(number | null)[]>([]);
  const [intervalMinutes, setIntervalMinutes] = useState<number | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const payload = await getAnimeshCandles(side);
        if (cancelled) return;
        setCandles(payload.candles);
        setMacd(payload.macd);
        setSignal(payload.signal);
        setHistogram(payload.histogram);
        setBandHigh(payload.bandHigh);
        setBandLow(payload.bandLow);
        setBandMedian(payload.bandMedian);
        setIntervalMinutes(payload.intervalMinutes);
        setChartError(null);
      } catch (exc) {
        if (!cancelled) setChartError(exc instanceof Error ? exc.message : "Failed to load candles.");
      }
    }
    load();
    const timer = window.setInterval(load, CANDLES_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [side]);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: containerRef.current.clientWidth,
      height: 420,
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time: Time) => formatIstTime(time),
      },
      localization: {
        timeFormatter: (time: Time) => formatIstTime(time),
      },
    });
    const candleSeries = chart.addSeries(
      CandlestickSeries,
      { upColor: "#168448", downColor: "#c93535", borderVisible: false, wickUpColor: "#168448", wickDownColor: "#c93535" },
      0,
    );
    const bandHighLine = chart.addSeries(LineSeries, { color: "#2368b6", lineWidth: 1 }, 0);
    const bandLowLine = chart.addSeries(LineSeries, { color: "#2368b6", lineWidth: 1 }, 0);
    const bandMedianLine = chart.addSeries(LineSeries, { color: "#8ebae8", lineWidth: 1, lineStyle: LineStyle.Dotted }, 0);
    const macdLine = chart.addSeries(LineSeries, { color: "#2368b6", lineWidth: 2 }, 1);
    const signalLine = chart.addSeries(LineSeries, { color: "#a56513", lineWidth: 2 }, 1);
    const histogramSeries = chart.addSeries(HistogramSeries, {}, 1);

    chart.panes()[1]?.setStretchFactor(0.32);

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    bandHighRef.current = bandHighLine;
    bandLowRef.current = bandLowLine;
    bandMedianRef.current = bandMedianLine;
    macdLineRef.current = macdLine;
    signalLineRef.current = signalLine;
    histogramRef.current = histogramSeries;
    markersRef.current = createSeriesMarkers(candleSeries, []);

    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      markersRef.current?.detach();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      bandHighRef.current = null;
      bandLowRef.current = null;
      bandMedianRef.current = null;
      macdLineRef.current = null;
      signalLineRef.current = null;
      histogramRef.current = null;
      markersRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!candleSeriesRef.current) return;
    candleSeriesRef.current.setData(
      candles.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })),
    );
    bandHighRef.current?.setData(numericLineData(candles, bandHigh));
    bandLowRef.current?.setData(numericLineData(candles, bandLow));
    bandMedianRef.current?.setData(numericLineData(candles, bandMedian));
    macdLineRef.current?.setData(numericLineData(candles, macd));
    signalLineRef.current?.setData(numericLineData(candles, signal));
    histogramRef.current?.setData(
      candles
        .map((c, i) => ({ time: c.time as UTCTimestamp, value: histogram[i] }))
        .filter((point): point is { time: UTCTimestamp; value: number } => point.value !== null && point.value !== undefined)
        .map((point) => ({ time: point.time, value: point.value, color: point.value >= 0 ? "#168448" : "#c93535" })),
    );
  }, [candles, macd, signal, histogram, bandHigh, bandLow, bandMedian]);

  useEffect(() => {
    const series = candleSeriesRef.current;
    if (!series) return;
    series.priceLines().forEach((line) => series.removePriceLine(line));
    if (!openTrade) return;
    series.createPriceLine({ price: openTrade.entryIndexLevel, color: "#6f7785", title: "Entry" });
    series.createPriceLine({ price: openTrade.initialSl, color: "#c93535", title: "SL" });
    series.createPriceLine({ price: openTrade.target1, color: "#168448", title: "T1 (1R)" });
    series.createPriceLine({ price: openTrade.target2, color: "#168448", title: "T2 (1.5R)" });
    if (openTrade.lot3TrailSl !== null && openTrade.lot3TrailSl !== undefined) {
      series.createPriceLine({ price: openTrade.lot3TrailSl, color: "#a56513", title: "Trail SL" });
    }
  }, [openTrade]);

  useEffect(() => {
    if (!markersRef.current || !candles.length) return;
    markersRef.current.setMarkers(buildTradeMarkers(trades, side, candles));
  }, [trades, side, candles]);

  return (
    <div>
      <div className="subtext">{intervalMinutes ? `${intervalMinutes}m candles · EMA band(21) · MACD(8,21,8)` : ""}</div>
      {chartError ? <div className="alert error">{chartError}</div> : null}
      <div ref={containerRef} style={{ width: "100%" }} />
    </div>
  );
}

function numericLineData(candles: AnimeshCandle[], values: (number | null)[]): { time: UTCTimestamp; value: number }[] {
  return candles
    .map((c, i) => ({ time: c.time as UTCTimestamp, value: values[i] }))
    .filter((point): point is { time: UTCTimestamp; value: number } => point.value !== null && point.value !== undefined);
}

function PaperTradesTable({ side, state }: { side: AnimeshSide; state: AnimeshState | null }) {
  const running = state?.status === "RUNNING";
  const sideState = running ? state.sides[side] : null;
  const trade = sideState?.openTrade ?? null;
  const legs = sideState?.legs ?? [];

  if (!trade) {
    return (
      <div className="table-section">
        <div className="section-title">
          <h2>Paper Trade Detail</h2>
        </div>
        <p className="subtext">No trade for {side} yet today.</p>
      </div>
    );
  }

  const isOpen = trade.status === "OPEN";
  const pnl = isOpen ? trade.unrealizedPnl : trade.realizedPnl;
  const pnlTone = pnl === null || pnl === undefined ? undefined : pnl < 0 ? "negative" : "positive";

  return (
    <div className="table-section">
      <div className="section-title">
        <h2>Paper Trade Detail — {trade.id}</h2>
        <span>{trade.status}</span>
      </div>
      <div className="ema5-metric-grid">
        <Metric label="Strike / Qty" value={`${trade.strike ?? "-"} × ${trade.entryQty ?? "-"}`} />
        <Metric label="Entry Price" value={money(trade.entryPremium)} />
        <Metric label="LTP" value={isOpen ? money(trade.currentPremium) : "-"} />
        <Metric label={isOpen ? "Unrealized P&L" : "Realized P&L"} value={money(pnl)} tone={pnlTone} />
        <Metric label="Phase" value={trade.phase.replaceAll("_", " ")} />
        <Metric label="Entry Index" value={money(trade.entryIndexLevel)} />
        <Metric label="Stop Loss" value={money(trade.initialSl)} tone="negative" />
        <Metric label="Target 1 (1R)" value={money(trade.target1)} tone="positive" />
        <Metric label="Target 2 (1.5R)" value={money(trade.target2)} tone="positive" />
        <Metric label="Trailing SL" value={trade.lot3TrailSl !== null && trade.lot3TrailSl !== undefined ? money(trade.lot3TrailSl) : "-"} />
      </div>
      <div className="table-wrap gb-subtable">
        <table>
          <thead>
            <tr>
              <th>Lot</th>
              <th>Qty</th>
              <th>Status</th>
              <th>Entry Price</th>
              <th>Exit Index</th>
              <th>Exit Price</th>
              <th>Reason</th>
              <th>P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {legs.map((leg: AnimeshTradeLeg) => (
              <tr key={leg.id} className={leg.status === "CLOSED" ? "closed-row" : ""}>
                <td>Lot {leg.lotNumber}</td>
                <td>{leg.qty}</td>
                <td>{leg.status}</td>
                <td>{money(trade.entryPremium)}</td>
                <td>{money(leg.exitIndexLevel)}</td>
                <td>{money(leg.exitPremium)}</td>
                <td>{leg.exitReason ?? "-"}</td>
                <td className={leg.realizedPnl && leg.realizedPnl < 0 ? "negative" : "positive"}>
                  {leg.status === "CLOSED" ? money(leg.realizedPnl) : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "positive" | "negative" }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={tone ?? ""}>{value}</strong>
    </div>
  );
}

function SessionDetailCard({ detail, onClose }: { detail: AnimeshSessionDetail; onClose: () => void }) {
  return (
    <section className="table-section">
      <div className="section-title">
        <h2>
          animesh-scalping — {detail.session.sessionDate} (bias: {detail.session.dailyBias ?? "-"})
        </h2>
        <button className="icon-button" type="button" onClick={onClose} title="Close">
          ×
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Trade</th>
              <th>Side</th>
              <th>Strike</th>
              <th>Entry idx</th>
              <th>Phase</th>
              <th>Status</th>
              <th>Realized P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {detail.trades.map((trade) => (
              <tr key={trade.id}>
                <td>{trade.id}</td>
                <td>{trade.side}</td>
                <td>{trade.strike}</td>
                <td>{money(trade.entryIndexLevel)}</td>
                <td>{trade.phase}</td>
                <td>{trade.status}</td>
                <td className={trade.realizedPnl && trade.realizedPnl < 0 ? "negative" : "positive"}>{money(trade.realizedPnl)}</td>
              </tr>
            ))}
            {!detail.trades.length ? (
              <tr>
                <td colSpan={7}>No trades this session.</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <div className="gb-timeline">
        {detail.events
          .slice(-20)
          .reverse()
          .map((event) => (
            <div key={event.id} className="gb-timeline-row">
              <span className="subtext">{formatTime(event.createdAt)}</span>
              <span>{event.message}</span>
            </div>
          ))}
      </div>
    </section>
  );
}

function buildTradeMarkers(trades: AnimeshTrade[], side: AnimeshSide, candles: AnimeshCandle[]): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = [];
  for (const trade of trades) {
    if (trade.entryAt) {
      const time = nearestCandleTime(candles, istIsoToEpoch(trade.entryAt));
      if (time !== null) {
        markers.push({
          time: time as UTCTimestamp,
          position: side === "CE" ? "belowBar" : "aboveBar",
          color: side === "CE" ? "#168448" : "#c93535",
          shape: side === "CE" ? "arrowUp" : "arrowDown",
          text: `Entry ${money(trade.entryPremium)}`,
        });
      }
    }
    for (const leg of trade.legs ?? []) {
      if (leg.status !== "CLOSED" || !leg.exitAt) continue;
      const time = nearestCandleTime(candles, istIsoToEpoch(leg.exitAt));
      if (time === null) continue;
      const positive = (leg.realizedPnl ?? 0) >= 0;
      markers.push({
        time: time as UTCTimestamp,
        position: "inBar",
        color: positive ? "#168448" : "#c93535",
        shape: "circle",
        text: `L${leg.lotNumber} ${leg.exitReason ?? "exit"} ${money(leg.exitPremium)}`,
      });
    }
  }
  markers.sort((a, b) => (a.time as number) - (b.time as number));
  return markers;
}

function istIsoToEpoch(iso: string): number {
  const [datePart, timePart] = iso.split("T");
  const [year, month, day] = datePart.split("-").map(Number);
  const [hour, minute, second] = (timePart ?? "00:00:00").split(":").map(Number);
  const IST_OFFSET_MS = (5 * 60 + 30) * 60 * 1000;
  const utcMillis = Date.UTC(year, month - 1, day, hour, minute, second || 0) - IST_OFFSET_MS;
  return Math.floor(utcMillis / 1000);
}

function nearestCandleTime(candles: AnimeshCandle[], epochSeconds: number): number | null {
  if (!candles.length) return null;
  let best = candles[0].time;
  for (const candle of candles) {
    if (candle.time <= epochSeconds) best = candle.time;
    else break;
  }
  return best;
}

function formatCandleTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatIstTime(time: Time): string {
  if (typeof time !== "number") return String(time);
  return formatCandleTime(time);
}

function formatTime(iso: string): string {
  const parts = iso.split("T");
  return parts[1] ?? iso;
}

function money(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return moneyFormat.format(value);
}

function secondsToMs(value: string | undefined, fallbackSeconds: number): number {
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : fallbackSeconds * 1000;
}
