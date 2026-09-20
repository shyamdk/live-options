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
import { RefreshCw, TrendingUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { getPstrategyNiftyCandles, getPstrategyNiftyTrades } from "@/lib/api";
import type {
  PstrategyNiftyCandlesData,
  PstrategyNiftyConsolidationBox,
  PstrategyNiftyResolution,
  PstrategyNiftyTrade,
} from "@/types/pstrategy-nifty";
import { DailyTotalsTable, groupDailyTotals } from "@/components/DailyTotals";

const RESOLUTIONS: PstrategyNiftyResolution[] = ["1m", "3m"];

function secondsToMs(value: string | undefined, fallbackSeconds: number): number {
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : fallbackSeconds * 1000;
}

const REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_PSTRATEGY_NIFTY_REFRESH_SECONDS, 20);

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

function fmtPrice(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function fmtPremium(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
}

function fmtInr(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const sign = value >= 0 ? "+" : "";
  return `${sign}₹${value.toFixed(2)}`;
}

const EXIT_REASON_LABEL: Record<string, string> = {
  underlying_trail_stop: "Trailing stop (underlying ATR)",
  underlying_ema_exit: "Crossed EMA20 (underlying)",
  underlying_rsi_target: "RSI profit-booking (underlying)",
  premium_stop_loss: "Premium stop-loss",
  eod: "End of day",
};

function TradesGroup({ resolution }: { resolution: PstrategyNiftyResolution }) {
  const [trades, setTrades] = useState<PstrategyNiftyTrade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
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
      const payload = await getPstrategyNiftyTrades(resolution);
      setTrades(payload.trades);
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load paper trades.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolution]);

  const secondsUntilRefresh = Math.max(0, Math.ceil((REFRESH_MS - (nowTick - lastRefreshAt)) / 1000));
  const open = trades.filter((t) => t.status === "open");
  const closed = trades.filter((t) => t.status === "closed");

  return (
    <div style={{ margin: "20px 0" }}>
      <h2 style={{ fontSize: 16, margin: "0 0 8px", display: "flex", alignItems: "center", gap: 8 }}>
        {resolution} strategy trades
        <span className="pcr-oi-caption" style={{ fontWeight: 400 }}>
          Auto-refreshes in {secondsUntilRefresh}s
        </span>
        <button type="button" className="button secondary" onClick={load} disabled={loading} style={{ marginLeft: "auto" }}>
          <RefreshCw size={14} /> {loading ? "Refreshing…" : "Refresh"}
        </button>
      </h2>
      {error ? <div className="alert error">{error}</div> : null}

      <div className="pcr-oi-section">
        <h3 style={{ margin: "0 0 6px" }}>
          Live trades <span className="pcr-oi-caption">(NIFTY, {resolution})</span>
        </h3>
        {open.length === 0 ? (
          <p className="pcr-oi-caption">No open positions right now.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Side</th>
                  <th>Strike</th>
                  <th>Expiry</th>
                  <th>Entry time</th>
                  <th>Entry premium</th>
                  <th>Current premium</th>
                  <th>Charges</th>
                  <th>P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {open.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <span className={`badge ${t.side === "CE" ? "buy" : "sell"}`}>{t.side}</span>
                    </td>
                    <td>{fmtPrice(t.strike)}</td>
                    <td>{t.expiry}</td>
                    <td>{fmtDateTime(t.entryTime)}</td>
                    <td>{fmtPremium(t.entryPremium)}</td>
                    <td>{fmtPremium(t.currentPremium)}</td>
                    <td className="pcr-oi-caption">{t.charges !== undefined && t.charges !== null ? fmtInr(-t.charges) : "—"}</td>
                    <td style={{ color: (t.unrealizedPnl ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                      {t.netUnrealizedPnl !== undefined && t.netUnrealizedPnl !== null ? fmtInr(t.netUnrealizedPnl) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="pcr-oi-section">
        <h3 style={{ margin: "0 0 6px" }}>
          Closed trades <span className="pcr-oi-caption">(NIFTY, {resolution})</span>
        </h3>
        {closed.length === 0 ? (
          <p className="pcr-oi-caption">No closed trades yet.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Side</th>
                  <th>Strike</th>
                  <th>Expiry</th>
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
                {closed.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <span className={`badge ${t.side === "CE" ? "buy" : "sell"}`}>{t.side}</span>
                    </td>
                    <td>{fmtPrice(t.strike)}</td>
                    <td>{t.expiry}</td>
                    <td>{fmtDateTime(t.entryTime)}</td>
                    <td>{fmtPremium(t.entryPremium)}</td>
                    <td>{fmtDateTime(t.exitTime)}</td>
                    <td>{fmtPremium(t.exitPremium)}</td>
                    <td>{t.exitReason ? EXIT_REASON_LABEL[t.exitReason] ?? t.exitReason : "—"}</td>
                    <td className="pcr-oi-caption">{t.charges !== undefined && t.charges !== null ? fmtInr(-t.charges) : "—"}</td>
                    <td style={{ color: (t.netRealizedPnl ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                      {t.netRealizedPnl !== undefined && t.netRealizedPnl !== null ? fmtInr(t.netRealizedPnl) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <DailyTotalsTable
          rows={groupDailyTotals(
            closed,
            (t) => t.exitTime,
            (t) => t.realizedPnl,
            (t) => t.netRealizedPnl ?? null,
          )}
        />
      </div>
    </div>
  );
}

export default function PstrategyNiftyPage() {
  const [chartResolution, setChartResolution] = useState<PstrategyNiftyResolution>("1m");

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <TrendingUp size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            pStrategy-Nifty
          </h1>
          <p>
            The same consolidation-breakout momentum detection as pStrategy, applied to NIFTY spot at 1m and 3m. On a
            confirmed bullish breakout it buys 1 lot of ATM CE; on a confirmed bearish breakout, ATM PE. Exit is
            pStrategy&apos;s own EMA-hold/ATR-trailing-stop rule on NIFTY&apos;s price, or a hard stop-loss on the
            premium itself, whichever fires first -- plus a forced square-off at end of day. This is a live,
            persisted paper-trading engine, not an instant replay: trade history only builds up from whenever the
            engine is switched on. Paper trades only.
          </p>
        </div>
        <div className="toolbar">
          {RESOLUTIONS.map((r) => (
            <button
              key={r}
              type="button"
              className="button secondary"
              style={r === chartResolution ? { background: "var(--accent, #2368b6)", color: "#fff" } : undefined}
              onClick={() => setChartResolution(r)}
            >
              {r} chart
            </button>
          ))}
        </div>
      </header>

      <NiftyMomentumChart resolution={chartResolution} />

      {RESOLUTIONS.map((r) => (
        <TradesGroup key={r} resolution={r} />
      ))}
    </section>
  );
}

function NiftyMomentumChart({ resolution }: { resolution: PstrategyNiftyResolution }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const emaSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const boxSeriesRef = useRef<ISeriesApi<"Line">[]>([]);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  const [data, setData] = useState<PstrategyNiftyCandlesData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const payload = await getPstrategyNiftyCandles(resolution);
        if (cancelled) return;
        if (payload.error) {
          setError(payload.error);
          return;
        }
        setData(payload);
        setError(null);
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : "Failed to load NIFTY candles.");
      }
    }
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [resolution]);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: containerRef.current.clientWidth,
      height: 360,
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
    const emaLine = chart.addSeries(LineSeries, { color: "#8b5cf6", lineWidth: 2, title: "EMA20" });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    emaSeriesRef.current = emaLine;
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
      emaSeriesRef.current = null;
      markersRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!data || !candleSeriesRef.current || !chartRef.current) return;
    const times = data.candles.map((c) => c.time as UTCTimestamp);

    candleSeriesRef.current.setData(
      data.candles.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })),
    );
    emaSeriesRef.current?.setData(
      data.emaSlowValues
        .map((v, i) => (v === null ? null : { time: times[i], value: v }))
        .filter((point): point is { time: UTCTimestamp; value: number } => point !== null),
    );

    for (const series of boxSeriesRef.current) chartRef.current.removeSeries(series);
    boxSeriesRef.current = [];
    for (const box of data.consolidations) {
      boxSeriesRef.current.push(addBoxLine(chartRef.current, box, "resistance"));
      boxSeriesRef.current.push(addBoxLine(chartRef.current, box, "support"));
    }

    markersRef.current?.setMarkers(
      data.momentumCandles.map((m) => ({
        time: m.time as UTCTimestamp,
        position: m.side === "long" ? "belowBar" : "aboveBar",
        color: m.side === "long" ? "#168448" : "#c93535",
        shape: m.side === "long" ? "arrowUp" : "arrowDown",
        text: m.side === "long" ? "CE" : "PE",
      })),
    );
  }, [data]);

  return (
    <div className="pcr-oi-section">
      <h3>
        NIFTY spot <span className="pcr-oi-caption">({resolution})</span>
      </h3>
      {data ? (
        <p className="pcr-oi-caption" style={{ margin: "0 0 8px" }}>
          RSI profit-booking: long exit at RSI ≥ {data.rsiLongExit}, short exit at RSI ≤ {data.rsiShortExit} -- set via
          the backend&apos;s pstrategy_nifty_rsi_long_exit / pstrategy_nifty_rsi_short_exit settings (no page control
          yet, matching the other engine-side settings like the stop-loss percent).
        </p>
      ) : null}
      {error ? <div className="alert error">{error}</div> : null}
      <div ref={containerRef} style={{ width: "100%" }} />
    </div>
  );
}

function addBoxLine(chart: IChartApi, box: PstrategyNiftyConsolidationBox, kind: "support" | "resistance"): ISeriesApi<"Line"> {
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
