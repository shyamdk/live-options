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
import { RefreshCw, SplitSquareHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  getPeCeCrossoverCandles,
  getPeCeCrossoverSignalLog,
  getPeCeCrossoverStatus,
  getPeCeCrossoverTrades,
  getPcrOiSnapshots,
  runPeCeCrossoverBacktest,
} from "@/lib/api";
import type {
  PeCeBacktestResult,
  PeCeCandlesData,
  PeCeSide,
  PeCeSignalLogEntry,
  PeCeStatus,
  PeCeTrade,
  PeCeUnderlying,
} from "@/types/pe-ce-crossover";
import { DailyTotalsTable, groupDailyTotals } from "@/components/DailyTotals";

const UNDERLYINGS: PeCeUnderlying[] = ["NIFTY", "BANKNIFTY", "SENSEX"];
const REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_PE_CE_CROSSOVER_REFRESH_SECONDS, 20);

function secondsToMs(value: string | undefined, fallbackSeconds: number): number {
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : fallbackSeconds * 1000;
}

function fmtDateTime(epochSeconds: number | null | undefined): string {
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

function fmtPremium(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
}

function fmtInr(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const sign = value >= 0 ? "+" : "-";
  return `${sign}₹${Math.abs(value).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

const EXIT_REASON_LABEL: Record<string, string> = {
  target: "Target",
  stop_loss: "Stop-loss",
  trail_stop: "Trailing stop",
  ema_cross_down: "EMA8 crossed below EMA21",
  eod: "End of day",
};

const STATE_LABEL: Record<string, string> = {
  NO_SIGNAL: "NO SIGNAL",
  CANDIDATE: "CANDIDATE",
  WAITING_FOR_EXPANSION: "WAITING FOR EXPANSION",
  READY: "READY",
  BLOCKED: "BLOCKED",
  IN_POSITION: "IN POSITION",
};

const STATE_COLOR: Record<string, string> = {
  NO_SIGNAL: "#8391a3",
  CANDIDATE: "#c9772f",
  WAITING_FOR_EXPANSION: "#c9772f",
  READY: "#168448",
  BLOCKED: "#c93535",
  IN_POSITION: "#2368b6",
};

export default function PeCeCrossoverPage() {
  const [underlying, setUnderlying] = useState<PeCeUnderlying>("NIFTY");
  const [status, setStatus] = useState<PeCeStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [statusError, setStatusError] = useState<string | null>(null);

  async function loadStatus() {
    setStatusLoading(true);
    try {
      setStatus(await getPeCeCrossoverStatus());
      setStatusError(null);
    } catch (exc) {
      setStatusError(exc instanceof Error ? exc.message : "Failed to load status.");
    } finally {
      setStatusLoading(false);
    }
  }

  useEffect(() => {
    loadStatus();
    const timer = window.setInterval(loadStatus, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <SplitSquareHorizontal size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            PE-CE Crossover
          </h1>
          <p>
            Independent CE and PE signal streams: a long entry fires only when EMA8 crosses above EMA21 on that
            option&apos;s OWN premium candles (never inferred from the underlying&apos;s direction), and only after
            the premium-expansion and spread/liquidity gates pass. Long-only, paper trades only.
          </p>
        </div>
        <div className="toolbar">
          {UNDERLYINGS.map((u) => (
            <button
              key={u}
              type="button"
              className="button secondary"
              style={u === underlying ? { background: "var(--accent, #2368b6)", color: "#fff" } : undefined}
              onClick={() => setUnderlying(u)}
            >
              {u}
            </button>
          ))}
        </div>
      </header>

      <StatusPanel status={status} loading={statusLoading} error={statusError} />

      <PcrAnalyticsStrip underlying={underlying} />

      <div className="pe-ce-split" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <SidePanel underlying={underlying} side="PE" />
        <SidePanel underlying={underlying} side="CE" />
      </div>

      <SignalLogPanel underlying={underlying} />

      <BacktestPanel underlying={underlying} />
    </section>
  );
}

function defaultDateRange(): { from: string; to: string } {
  const to = new Date();
  const from = new Date(to.getTime() - 7 * 24 * 3600 * 1000);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return { from: iso(from), to: iso(to) };
}

function BacktestPanel({ underlying }: { underlying: PeCeUnderlying }) {
  const defaults = defaultDateRange();
  const [side, setSide] = useState<PeCeSide>("CE");
  const [fromDate, setFromDate] = useState(defaults.from);
  const [toDate, setToDate] = useState(defaults.to);
  const [result, setResult] = useState<PeCeBacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setLoading(true);
    setError(null);
    try {
      const payload = await runPeCeCrossoverBacktest(underlying, side, fromDate, toDate);
      setResult(payload);
      if (payload.error) setError(payload.error);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Backtest failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="pcr-oi-section">
      <h3 style={{ margin: "0 0 6px" }}>
        Backtest <span className="pcr-oi-caption">({underlying}, using the option&apos;s own historical premium candles)</span>
      </h3>
      <p className="pcr-oi-caption" style={{ margin: "0 0 8px" }}>
        Covers only the lifetime of the currently listed expiry (Dhan has no historical option-chain-as-of-date
        endpoint) -- so this is a recent-history check, not an arbitrary-date-range backtest. No lookahead: ATM
        strike at each bar is computed only from data up to and including that bar.
      </p>
      <div className="toolbar" style={{ marginBottom: 10 }}>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span className="pcr-oi-caption">Side</span>
          {(["CE", "PE"] as PeCeSide[]).map((s) => (
            <button
              key={s}
              type="button"
              className="button secondary"
              style={s === side ? { background: "var(--accent, #2368b6)", color: "#fff" } : undefined}
              onClick={() => setSide(s)}
            >
              {s}
            </button>
          ))}
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span className="pcr-oi-caption">From</span>
          <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span className="pcr-oi-caption">To</span>
          <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} />
        </span>
        <button type="button" className="button" onClick={run} disabled={loading}>
          {loading ? "Running…" : "Run backtest"}
        </button>
      </div>
      {error ? <div className="alert error">{error}</div> : null}
      {result && !result.error ? (
        <>
          {result.metrics ? (
            <div className="metric-grid" style={{ marginBottom: 10 }}>
              <div className="metric">
                <span>Trades</span>
                <strong>{result.metrics.tradeCount}</strong>
              </div>
              <div className="metric">
                <span>Net P&amp;L</span>
                <strong style={{ color: result.metrics.netPnl >= 0 ? "var(--green)" : "var(--red)" }}>{fmtInr(result.metrics.netPnl)}</strong>
              </div>
              <div className="metric">
                <span>Win rate</span>
                <strong>{result.metrics.winRate !== null ? `${result.metrics.winRate}%` : "—"}</strong>
              </div>
              <div className="metric">
                <span>Profit factor</span>
                <strong>{result.metrics.profitFactor ?? "—"}</strong>
              </div>
              <div className="metric">
                <span>Expectancy</span>
                <strong>{result.metrics.expectancy !== null ? fmtInr(result.metrics.expectancy) : "—"}</strong>
              </div>
              <div className="metric">
                <span>Max drawdown</span>
                <strong>{fmtInr(result.metrics.maxDrawdown)}</strong>
              </div>
              <div className="metric">
                <span>Longest losing streak</span>
                <strong>{result.metrics.longestLosingStreak}</strong>
              </div>
            </div>
          ) : null}
          {result.trades.length > 0 ? (
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>Strike</th>
                    <th>Entry time</th>
                    <th>Entry premium</th>
                    <th>Exit time</th>
                    <th>Exit premium</th>
                    <th>Exit reason</th>
                    <th>Charges</th>
                    <th>Net P&amp;L</th>
                  </tr>
                </thead>
                <tbody>
                  {result.trades.map((t, i) => (
                    <tr key={i}>
                      <td>{t.strike}</td>
                      <td>{fmtDateTime(t.entryTime)}</td>
                      <td>{fmtPremium(t.entryPremium)}</td>
                      <td>{fmtDateTime(t.exitTime)}</td>
                      <td>{fmtPremium(t.exitPremium)}</td>
                      <td>{EXIT_REASON_LABEL[t.exitReason] ?? t.exitReason}</td>
                      <td className="pcr-oi-caption">{fmtInr(-t.charges)}</td>
                      <td style={{ color: t.netPnl >= 0 ? "var(--green)" : "var(--red)" }}>{fmtInr(t.netPnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="pcr-oi-caption">No crossover signals found in this window.</p>
          )}
          {result.limitations && result.limitations.length > 0 ? (
            <ul className="pcr-oi-caption" style={{ marginTop: 8 }}>
              {result.limitations.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function StatusPanel({ status, loading, error }: { status: PeCeStatus | null; loading: boolean; error: string | null }) {
  return (
    <div className="pcr-oi-section">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>Engine status</h3>
        {status ? (
          <span className="badge" style={{ background: status.monitorEnabled ? "#c93535" : "#8391a3", color: "#fff" }}>
            {status.monitorEnabled ? "PAPER -- MONITOR ON" : "DISABLED"}
          </span>
        ) : null}
      </div>
      {error ? <div className="alert error">{error}</div> : null}
      {loading && !status ? <p className="pcr-oi-caption">Loading…</p> : null}
      {status ? (
        <div className="metric-grid" style={{ marginTop: 8 }}>
          <div className="metric">
            <span>Open positions</span>
            <strong>{status.openPositions}</strong>
          </div>
          <div className="metric">
            <span>Today&apos;s realized P&amp;L</span>
            <strong style={{ color: status.todayRealizedPnl >= 0 ? "var(--green)" : "var(--red)" }}>{fmtInr(status.todayRealizedPnl)}</strong>
          </div>
          <div className="metric">
            <span>Stop-loss / Target</span>
            <strong>
              {status.stopLossPercent}% / {status.targetPercent}%
            </strong>
          </div>
          <div className="metric">
            <span>Trail arm / distance</span>
            <strong>
              {status.trailArmPercent}% / {status.trailPercent}%
            </strong>
          </div>
          <div className="metric">
            <span>Max capital / daily loss</span>
            <strong>
              ₹{status.maxCapitalRupees.toLocaleString("en-IN")} / ₹{status.maxDailyLossRupees.toLocaleString("en-IN")}
            </strong>
          </div>
          <div className="metric">
            <span>Max trades/day / cooldown</span>
            <strong>
              {status.maxTradesPerDay} / {status.cooldownMinutes}min
            </strong>
          </div>
          <div className="metric">
            <span>Position mode</span>
            <strong>{status.positionMode === "total" ? "One total" : "One per side"}</strong>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function PcrAnalyticsStrip({ underlying }: { underlying: PeCeUnderlying }) {
  const [point, setPoint] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const payload = await getPcrOiSnapshots();
        if (cancelled) return;
        const rows = (payload as unknown as Record<string, Record<string, unknown>[]>)[underlying] ?? [];
        setPoint(rows.length ? rows[rows.length - 1] : null);
        setError(null);
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : "Failed to load PCR/OI data.");
      }
    }
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [underlying]);

  const num = (key: string): number | null => {
    const v = point?.[key];
    return typeof v === "number" ? v : null;
  };

  return (
    <div className="pcr-oi-section">
      <h3 style={{ margin: "0 0 6px" }}>
        Market context <span className="pcr-oi-caption">({underlying})</span>
      </h3>
      {error ? <div className="alert error">{error}</div> : null}
      {!point ? (
        <p className="pcr-oi-caption">No PCR/OI snapshot yet today.</p>
      ) : (
        <div className="metric-grid">
          <div className="metric">
            <span>Spot</span>
            <strong>{fmtPremium(num("spot"))}</strong>
          </div>
          <div className="metric">
            <span>PCR (OI-based)</span>
            <strong>{num("pcr") ?? "—"}</strong>
          </div>
          <div className="metric">
            <span>India VIX</span>
            <strong>{num("indiaVix") ?? "—"}</strong>
          </div>
          <div className="metric">
            <span>CE IV / PE IV</span>
            <strong>
              {num("ceIv")?.toFixed(2) ?? "—"} / {num("peIv")?.toFixed(2) ?? "—"}
            </strong>
          </div>
          <div className="metric">
            <span>CE Chg OI / PE Chg OI</span>
            <strong>
              {num("ceOiChange")?.toLocaleString("en-IN") ?? "—"} / {num("peOiChange")?.toLocaleString("en-IN") ?? "—"}
            </strong>
          </div>
          <div className="metric">
            <span>CE bid/ask</span>
            <strong>
              {num("ceBid") ?? "—"} / {num("ceAsk") ?? "—"}
            </strong>
          </div>
          <div className="metric">
            <span>PE bid/ask</span>
            <strong>
              {num("peBid") ?? "—"} / {num("peAsk") ?? "—"}
            </strong>
          </div>
        </div>
      )}
      <p className="pcr-oi-caption" style={{ marginTop: 6 }}>
        OI-based PCR, contextual only -- not a standalone signal. IV is provider-supplied (Dhan), not model-derived.
      </p>
    </div>
  );
}

function SidePanel({ underlying, side }: { underlying: PeCeUnderlying; side: PeCeSide }) {
  const [data, setData] = useState<PeCeCandlesData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [trades, setTrades] = useState<PeCeTrade[]>([]);
  const [lastRefreshAt, setLastRefreshAt] = useState(Date.now());
  const [nowTick, setNowTick] = useState(Date.now());

  useEffect(() => {
    const tick = window.setInterval(() => setNowTick(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, []);

  async function load() {
    setLoading(true);
    setLastRefreshAt(Date.now());
    try {
      const [candlesPayload, tradesPayload] = await Promise.all([
        getPeCeCrossoverCandles(underlying, side),
        getPeCeCrossoverTrades(underlying),
      ]);
      setData(candlesPayload);
      setTrades(tradesPayload.trades.filter((t) => t.side === side));
      setError(candlesPayload.error ?? null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load data.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [underlying, side]);

  const secondsUntilRefresh = Math.max(0, Math.ceil((REFRESH_MS - (nowTick - lastRefreshAt)) / 1000));
  const open = trades.filter((t) => t.status === "open");
  const closed = trades.filter((t) => t.status === "closed");

  return (
    <div className="pcr-oi-section">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>
          {underlying} {side} {data?.strike ? `${data.strike}` : ""}
          <span className="pcr-oi-caption" style={{ marginLeft: 8 }}>
            {data?.expiry ? `exp ${data.expiry} (DTE ${data.dte})` : ""}
          </span>
        </h3>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="pcr-oi-caption">Auto-refreshes in {secondsUntilRefresh}s</span>
          <button type="button" className="button secondary" onClick={load} disabled={loading}>
            <RefreshCw size={14} /> {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>
      {data?.expiryReason ? <p className="pcr-oi-caption" style={{ margin: "4px 0" }}>{data.expiryReason}</p> : null}
      {error ? <div className="alert error">{error}</div> : null}

      <SideChart data={data} trades={trades} />

      <div style={{ marginTop: 10 }}>
        <h4 style={{ margin: "0 0 4px", fontSize: 13 }}>Live position</h4>
        {open.length === 0 ? (
          <p className="pcr-oi-caption">No open position.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Entry time</th>
                  <th>Entry premium</th>
                  <th>Peak</th>
                  <th>Trail stop</th>
                </tr>
              </thead>
              <tbody>
                {open.map((t) => (
                  <tr key={t.id}>
                    <td>{fmtDateTime(t.entryTime)}</td>
                    <td>{fmtPremium(t.entryPremium)}</td>
                    <td>{fmtPremium(t.peakPremium)}</td>
                    <td>{t.trailStopPremium !== null ? fmtPremium(t.trailStopPremium) : <span className="pcr-oi-caption">not armed</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div style={{ marginTop: 10 }}>
        <h4 style={{ margin: "0 0 4px", fontSize: 13 }}>Closed trades</h4>
        {closed.length === 0 ? (
          <p className="pcr-oi-caption">No closed trades yet.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Entry</th>
                  <th>Exit</th>
                  <th>Exit reason</th>
                  <th>Charges</th>
                  <th>Net P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {closed.map((t) => (
                  <tr key={t.id}>
                    <td>{fmtPremium(t.entryPremium)}</td>
                    <td>{fmtPremium(t.exitPremium)}</td>
                    <td>{t.exitReason ? EXIT_REASON_LABEL[t.exitReason] ?? t.exitReason : "—"}</td>
                    <td className="pcr-oi-caption">{t.charges !== null ? fmtInr(-t.charges) : "—"}</td>
                    <td style={{ color: (t.realizedPnl ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>{fmtInr(t.realizedPnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <DailyTotalsTable
              rows={groupDailyTotals(
                closed,
                (t) => t.exitTime,
                (t) => (t.realizedPnl ?? 0) + (t.charges ?? 0),
                (t) => t.realizedPnl,
              )}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function SideChart({ data, trades }: { data: PeCeCandlesData | null; trades: PeCeTrade[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const emaFastSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const emaSlowSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: containerRef.current.clientWidth,
      height: 260,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (time: Time) => formatIstTime(time) },
      localization: { timeFormatter: (time: Time) => formatIstTime(time) },
    });
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#168448",
      downColor: "#c93535",
      borderVisible: false,
      wickUpColor: "#168448",
      wickDownColor: "#c93535",
    });
    const emaFast = chart.addSeries(LineSeries, { color: "#14b8a6", lineWidth: 2, title: "EMA8" });
    const emaSlow = chart.addSeries(LineSeries, { color: "#8b5cf6", lineWidth: 2, title: "EMA21" });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    emaFastSeriesRef.current = emaFast;
    emaSlowSeriesRef.current = emaSlow;
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
      emaFastSeriesRef.current = null;
      emaSlowSeriesRef.current = null;
      markersRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!data || !candleSeriesRef.current) return;
    const times = data.candles.map((c) => c.time as UTCTimestamp);
    candleSeriesRef.current.setData(
      data.candles.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })),
    );
    emaFastSeriesRef.current?.setData(numericSeries(times, data.emaFastValues));
    emaSlowSeriesRef.current?.setData(numericSeries(times, data.emaSlowValues));
  }, [data]);

  useEffect(() => {
    if (!markersRef.current) return;
    const markers: SeriesMarker<Time>[] = [];
    for (const t of trades) {
      markers.push({
        time: t.entryTime as UTCTimestamp,
        position: "belowBar",
        color: "#168448",
        shape: "arrowUp",
        text: `Entry ${fmtPremium(t.entryPremium)}`,
      });
      if (t.status === "closed" && t.exitTime !== null) {
        const positive = (t.realizedPnl ?? 0) >= 0;
        markers.push({
          time: t.exitTime as UTCTimestamp,
          position: "aboveBar",
          color: positive ? "#168448" : "#c93535",
          shape: "circle",
          text: `Exit ${fmtPremium(t.exitPremium)}`,
        });
      }
    }
    markers.sort((a, b) => (a.time as number) - (b.time as number));
    markersRef.current.setMarkers(markers);
  }, [trades]);

  return <div ref={containerRef} style={{ width: "100%" }} />;
}

function SignalLogPanel({ underlying }: { underlying: PeCeUnderlying }) {
  const [log, setLog] = useState<PeCeSignalLogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const payload = await getPeCeCrossoverSignalLog(underlying);
        if (!cancelled) {
          setLog(payload.log);
          setError(null);
        }
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : "Failed to load signal log.");
      }
    }
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [underlying]);

  return (
    <div className="pcr-oi-section">
      <h3 style={{ margin: "0 0 6px" }}>
        Signal &amp; event log <span className="pcr-oi-caption">({underlying}, today, newest first)</span>
      </h3>
      {error ? <div className="alert error">{error}</div> : null}
      {log.length === 0 ? (
        <p className="pcr-oi-caption">No evaluations logged yet today.</p>
      ) : (
        <div style={{ overflowX: "auto", maxHeight: 320, overflowY: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Side</th>
                <th>State</th>
                <th>Premium</th>
                <th>EMA8 / EMA21</th>
                <th>Expansion %</th>
                <th>Spread %</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {log.map((row, i) => (
                <tr key={`${row.time}-${row.side}-${i}`}>
                  <td>{fmtDateTime(row.time)}</td>
                  <td>
                    <span className={`badge ${row.side === "CE" ? "buy" : "sell"}`}>{row.side}</span>
                  </td>
                  <td>
                    <span className="badge" style={{ background: STATE_COLOR[row.state] ?? "#8391a3", color: "#fff" }}>
                      {STATE_LABEL[row.state] ?? row.state}
                    </span>
                  </td>
                  <td>{fmtPremium(row.premium)}</td>
                  <td>
                    {row.emaFast?.toFixed(2) ?? "—"} / {row.emaSlow?.toFixed(2) ?? "—"}
                  </td>
                  <td>{row.premiumExpansionPercent?.toFixed(1) ?? "—"}</td>
                  <td>{row.spreadPercent?.toFixed(1) ?? "—"}</td>
                  <td className="pcr-oi-caption">{row.blockedReason ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function numericSeries(times: UTCTimestamp[], values: (number | null)[]): { time: UTCTimestamp; value: number }[] {
  return values
    .map((value, i) => (value === null ? null : { time: times[i], value }))
    .filter((point): point is { time: UTCTimestamp; value: number } => point !== null);
}

function formatIstTime(time: Time): string {
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
