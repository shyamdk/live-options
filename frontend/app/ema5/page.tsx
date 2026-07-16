"use client";

import { CandlestickSeries, ColorType, createChart, IChartApi, ISeriesApi, LineSeries, UTCTimestamp } from "lightweight-charts";
import { RefreshCcw, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { approveEma5Signal, getEma5Candles, getEma5SessionDetail, getEma5Sessions, getEma5State } from "@/lib/api";
import type { Ema5Candle, Ema5Session, Ema5SessionDetail, Ema5Side, Ema5State, Ema5Trade, Ema5TradeLeg } from "@/types/ema5";

const moneyFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const STATE_REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_EMA5_STATE_REFRESH_SECONDS, 5);
const CANDLES_REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_EMA5_CANDLES_REFRESH_SECONDS, 20);

export default function Ema5Page() {
  const [state, setState] = useState<Ema5State | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [approvingId, setApprovingId] = useState<number | null>(null);
  const [sessions, setSessions] = useState<Ema5Session[]>([]);
  const [selectedDetail, setSelectedDetail] = useState<Ema5SessionDetail | null>(null);

  async function loadState() {
    try {
      setState(await getEma5State());
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load ema5 state.");
    } finally {
      setLoading(false);
    }
  }

  async function loadSessions() {
    try {
      const payload = await getEma5Sessions();
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
      const result = await approveEma5Signal(signalId);
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
      setSelectedDetail(await getEma5SessionDetail(sessionId));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load session detail.");
    }
  }

  const mode = state?.mode ?? "PAPER";
  const running = state?.status === "RUNNING";

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>ema5</h1>
          <p>5-EMA alert-candle scalp — PE on 5m, CE on 15m, 3 lots (65 each), index-price driven</p>
        </div>
        <div className="toolbar">
          <span className={mode === "LIVE" ? "status-live on" : "status-live"}>{mode}</span>
          {running ? (
            <span className={`risk-pill ${state.wsConnected ? "target" : "stopLoss"}`}>
              {state.wsConnected ? "Spot Live" : "Reconnecting"} · {money(state.spot)}
            </span>
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
        <SidePanel
          side="PE"
          label="PE — 5m Alert-Candle Short Setup"
          state={state}
          approvingId={approvingId}
          onApprove={handleApprove}
        />
        <SidePanel
          side="CE"
          label="CE — 15m Alert-Candle Long Setup"
          state={state}
          approvingId={approvingId}
          onApprove={handleApprove}
        />
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
                  <td colSpan={6}>No sessions yet.</td>
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
  side: Ema5Side;
  label: string;
  state: Ema5State | null;
  approvingId: number | null;
  onApprove: (signalId: number, label: string) => void;
}) {
  const running = state?.status === "RUNNING";
  const sideState = running ? state.sides[side] : null;
  const pendingSignals = running ? state.pendingSignals.filter((s) => s.side === side) : [];
  const openTrade = sideState?.openTrade ?? null;

  return (
    <section className="gb-panel ema5-panel">
      <div className="section-title">
        <h2>{label}</h2>
        {sideState?.halted ? <span className="risk-pill stopLoss">Halted</span> : null}
      </div>
      <div className="gb-status-row">
        <span>
          Trades today: <strong>{sideState?.tradesCount ?? 0}</strong>
        </span>
        <span>Consecutive SL: {sideState?.consecutiveSl ?? 0}</span>
        {sideState?.alertCandle ? (
          <span className="subtext">
            Alert candle H {money(sideState.alertCandle.high)} / L {money(sideState.alertCandle.low)} at {formatCandleTime(sideState.alertCandle.time)}
          </span>
        ) : (
          <span className="subtext">No active alert candle</span>
        )}
      </div>

      <Ema5Chart side={side} openTrade={openTrade} />

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

      <OpenTradeCard trade={openTrade} />
      <PaperTradesTable side={side} state={state} />
    </section>
  );
}

function Ema5Chart({ side, openTrade }: { side: Ema5Side; openTrade: Ema5Trade | null }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const emaSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const [candles, setCandles] = useState<Ema5Candle[]>([]);
  const [ema, setEma] = useState<(number | null)[]>([]);
  const [intervalMinutes, setIntervalMinutes] = useState<number | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const payload = await getEma5Candles(side);
        if (cancelled) return;
        setCandles(payload.candles);
        setEma(payload.ema);
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
      height: 340,
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#168448",
      downColor: "#c93535",
      borderVisible: false,
      wickUpColor: "#168448",
      wickDownColor: "#c93535",
    });
    const emaLine = chart.addSeries(LineSeries, { color: "#2368b6", lineWidth: 2 });
    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    emaSeriesRef.current = emaLine;

    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      emaSeriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!candleSeriesRef.current || !emaSeriesRef.current) return;
    candleSeriesRef.current.setData(
      candles.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })),
    );
    emaSeriesRef.current.setData(
      candles
        .map((c, i) => ({ time: c.time as UTCTimestamp, value: ema[i] ?? null }))
        .filter((point): point is { time: UTCTimestamp; value: number } => point.value !== null),
    );
  }, [candles, ema]);

  useEffect(() => {
    const series = candleSeriesRef.current;
    if (!series) return;
    series.priceLines().forEach((line) => series.removePriceLine(line));
    if (!openTrade) return;
    series.createPriceLine({ price: openTrade.entryIndexLevel, color: "#6f7785", title: "Entry" });
    series.createPriceLine({ price: openTrade.initialSl, color: "#c93535", title: "SL" });
    series.createPriceLine({ price: openTrade.target1, color: "#168448", title: "T1 (1R)" });
    series.createPriceLine({ price: openTrade.target2, color: "#168448", title: "T2 (2R)" });
    if (openTrade.lot3TrailSl !== null && openTrade.lot3TrailSl !== undefined) {
      series.createPriceLine({ price: openTrade.lot3TrailSl, color: "#a56513", title: "Trail SL" });
    }
  }, [openTrade]);

  return (
    <div>
      <div className="subtext">{intervalMinutes ? `${intervalMinutes}m candles` : ""}</div>
      {chartError ? <div className="alert error">{chartError}</div> : null}
      <div ref={containerRef} style={{ width: "100%" }} />
    </div>
  );
}

function OpenTradeCard({ trade }: { trade: Ema5Trade | null }) {
  if (!trade) return <p className="subtext">No open trade.</p>;
  return (
    <div className="gb-status-row">
      <span>
        Open: strike <strong>{trade.strike}</strong> qty {trade.entryQty} @ {money(trade.entryPremium)}
      </span>
      <span>Phase: {trade.phase}</span>
      <span>Entry idx: {money(trade.entryIndexLevel)}</span>
      <span>SL: {money(trade.initialSl)}</span>
      <span>T1: {money(trade.target1)} · T2: {money(trade.target2)}</span>
      {trade.lot3TrailSl !== null && trade.lot3TrailSl !== undefined ? <span>Trail SL: {money(trade.lot3TrailSl)}</span> : null}
    </div>
  );
}

function PaperTradesTable({ side, state }: { side: Ema5Side; state: Ema5State | null }) {
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

  return (
    <div className="table-section">
      <div className="section-title">
        <h2>Paper Trade Detail — {trade.id}</h2>
        <span>{trade.status}</span>
      </div>
      <div className="table-wrap gb-subtable">
        <table>
          <thead>
            <tr>
              <th>Lot</th>
              <th>Qty</th>
              <th>Status</th>
              <th>Exit idx</th>
              <th>Exit premium</th>
              <th>Reason</th>
              <th>P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {legs.map((leg: Ema5TradeLeg) => (
              <tr key={leg.id} className={leg.status === "CLOSED" ? "closed-row" : ""}>
                <td>Lot {leg.lotNumber}</td>
                <td>{leg.qty}</td>
                <td>{leg.status}</td>
                <td>{money(leg.exitIndexLevel)}</td>
                <td>{money(leg.exitPremium)}</td>
                <td>{leg.exitReason ?? "-"}</td>
                <td className={leg.realizedPnl && leg.realizedPnl < 0 ? "negative" : "positive"}>{money(leg.realizedPnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SessionDetailCard({ detail, onClose }: { detail: Ema5SessionDetail; onClose: () => void }) {
  return (
    <section className="table-section">
      <div className="section-title">
        <h2>ema5 — {detail.session.sessionDate}</h2>
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

function formatCandleTime(epochSeconds: number): string {
  const date = new Date(epochSeconds * 1000);
  return date.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });
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
