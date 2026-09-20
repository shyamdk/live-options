"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  IChartApi,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  LineSeries,
  SeriesMarker,
  Time,
  UTCTimestamp,
} from "lightweight-charts";
import { Bitcoin, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { getCryptoSwingCandles, getCryptoSwingTrades, getCryptoSwingWallet } from "@/lib/api";
import type { CryptoSwingIndicators, CryptoSwingSymbol, CryptoSwingTrade, CryptoSwingWallet } from "@/types/crypto-swing";

function assetLabel(row: CryptoSwingWallet["balances"][number]): string {
  return row.asset_symbol ?? row.asset?.symbol ?? "?";
}

function fmtAmount(value: string | number | undefined): string {
  if (value === undefined || value === null) return "—";
  const num = typeof value === "string" ? Number(value) : value;
  return Number.isFinite(num) ? num.toLocaleString("en-IN", { maximumFractionDigits: 8 }) : String(value);
}

const CANDLES_REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_CRYPTO_SWING_CANDLES_REFRESH_SECONDS, 60);
const TRADES_REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_CRYPTO_SWING_TRADES_REFRESH_SECONDS, 30);

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

function fmtPrice(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
}

function fmtPnl(pct: number | null | undefined, amount: number | null | undefined): string {
  if (pct === null || pct === undefined || amount === null || amount === undefined) return "—";
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}% (${sign}$${amount.toFixed(2)})`;
}

const EXIT_REASON_LABEL: Record<string, string> = { trap_confirmed_reversal: "Trend reversal confirmed" };

function PaperTradesPanel({
  trades,
  loading,
  error,
  onRefresh,
  title,
  variant,
  secondsUntilRefresh,
}: {
  trades: CryptoSwingTrade[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  title: string;
  variant: "open" | "closed";
  secondsUntilRefresh: number;
}) {
  const usable = trades.filter((t) => t.status === variant);
  const errors = trades.filter((t) => t.status === "error");

  return (
    <div className="pcr-oi-section">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>{title}</h3>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="pcr-oi-caption">Auto-refreshes in {secondsUntilRefresh}s</span>
          <button type="button" className="button secondary" onClick={onRefresh} disabled={loading}>
            <RefreshCw size={14} /> {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>
      <p className="pcr-oi-caption" style={{ margin: "4px 0 10px" }}>
        Simulated only -- replayed deterministically from the 3-way confirmation strategy against 30m candle history.
        No real orders are placed. Entries/exits are also marked on the charts below.
      </p>
      {error ? <div className="alert error">{error}</div> : null}
      {errors.map((t) => (
        <div className="alert error" key={t.symbol}>
          {t.symbol}: {t.error}
        </div>
      ))}
      {usable.length === 0 ? (
        <p className="pcr-oi-caption">
          {variant === "open"
            ? "No open positions right now."
            : "No closed trades yet -- the strategy hasn't fired an entry signal in the fetched history."}
        </p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Entry time</th>
                <th>Entry price</th>
                <th>Tranches</th>
                {variant === "open" ? (
                  <>
                    <th>Current price</th>
                    <th>Current P&amp;L</th>
                    <th>Stop</th>
                  </>
                ) : (
                  <>
                    <th>Exit time</th>
                    <th>Exit price</th>
                    <th>Exit reason</th>
                    <th>P&amp;L</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {usable.map((t, i) => {
                const isOpen = variant === "open";
                const pnlPct = isOpen ? t.unrealizedPnlPercent : t.pnlPercent;
                const pnlAmount = isOpen ? t.unrealizedPnlAmount : t.pnlAmount;
                return (
                  <tr key={`${t.symbol}-${t.entryTime}-${i}`}>
                    <td>{t.symbol}</td>
                    <td>
                      <span className={`badge ${t.side === "long" ? "buy" : "sell"}`}>{t.side === "long" ? "LONG" : "SHORT"}</span>
                    </td>
                    <td>{fmtDateTime(t.entryTime)}</td>
                    <td>{fmtPrice(t.entryPrice)}</td>
                    <td>{t.tranches}</td>
                    {isOpen ? (
                      <>
                        <td>{fmtPrice(t.currentPrice)}</td>
                        <td style={{ color: (pnlPct ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>{fmtPnl(pnlPct, pnlAmount)}</td>
                        <td>{fmtPrice(t.stopLoss)}</td>
                      </>
                    ) : (
                      <>
                        <td>{fmtDateTime(t.exitTime)}</td>
                        <td>{fmtPrice(t.exitPrice)}</td>
                        <td>{t.exitReason ? EXIT_REASON_LABEL[t.exitReason] ?? t.exitReason : "—"}</td>
                        <td style={{ color: (pnlPct ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>{fmtPnl(pnlPct, pnlAmount)}</td>
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

export default function CryptoSwingPage() {
  const [wallet, setWallet] = useState<CryptoSwingWallet | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [trades, setTrades] = useState<CryptoSwingTrade[]>([]);
  const [tradesLoading, setTradesLoading] = useState(true);
  const [tradesError, setTradesError] = useState<string | null>(null);
  const [lastTradesRefreshAt, setLastTradesRefreshAt] = useState(Date.now());
  const [nowTick, setNowTick] = useState(Date.now());

  useEffect(() => {
    const tick = window.setInterval(() => setNowTick(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, []);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setWallet(await getCryptoSwingWallet());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load Delta Exchange wallet.");
    } finally {
      setLoading(false);
    }
  }

  async function loadTrades() {
    setTradesLoading(true);
    setLastTradesRefreshAt(Date.now());
    try {
      const payload = await getCryptoSwingTrades();
      setTrades(payload.trades);
      setTradesError(null);
    } catch (exc) {
      setTradesError(exc instanceof Error ? exc.message : "Failed to load paper trades.");
    } finally {
      setTradesLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    loadTrades();
    const timer = window.setInterval(loadTrades, TRADES_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  const nonZero = wallet?.balances.filter((row) => Number(row.balance ?? 0) !== 0) ?? [];
  const secondsUntilTradesRefresh = Math.max(0, Math.ceil((TRADES_REFRESH_MS - (nowTick - lastTradesRefreshAt)) / 1000));

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Bitcoin size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Crypto-Swing
          </h1>
          <p>Delta Exchange India connectivity and account funds. Strategy execution isn&apos;t wired up yet -- this confirms the connection and shows what capital is available to trade.</p>
        </div>
        <div className="toolbar" style={{ alignItems: "center", gap: 8 }}>
          <span className="pcr-oi-caption">Manual refresh only</span>
          <button type="button" className="button secondary" onClick={load} disabled={loading}>
            <RefreshCw size={14} /> {loading ? "Checking…" : "Refresh"}
          </button>
        </div>
      </header>

      <PaperTradesPanel
        trades={trades}
        loading={tradesLoading}
        error={tradesError}
        onRefresh={loadTrades}
        title="Current trades"
        variant="open"
        secondsUntilRefresh={secondsUntilTradesRefresh}
      />

      {error ? <div className="alert error">{error}</div> : null}

      {wallet && !wallet.connected ? (
        <div className="alert error">
          Not connected to Delta Exchange: {wallet.error}
          {wallet.error?.includes("ip_not_whitelisted") ? " -- whitelist this server's IP under the Delta Exchange API key settings." : ""}
        </div>
      ) : null}

      {wallet?.connected ? (
        <div className="pcr-oi-section">
          <h3>Wallet balances</h3>
          {nonZero.length === 0 ? (
            <p className="pcr-oi-caption">Connected, but every asset balance is currently zero.</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>Asset</th>
                    <th>Balance</th>
                    <th>Available</th>
                  </tr>
                </thead>
                <tbody>
                  {nonZero.map((row) => (
                    <tr key={assetLabel(row)}>
                      <td>{assetLabel(row)}</td>
                      <td>{fmtAmount(row.balance)}</td>
                      <td>{fmtAmount(row.available_balance)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}

      <div className="pcr-oi-section">
        <h3>BTC/USD</h3>
        <CryptoChart symbol="BTCUSD" trades={trades.filter((t) => t.symbol === "BTCUSD")} />
      </div>

      <div className="pcr-oi-section">
        <h3>ETH/USD</h3>
        <CryptoChart symbol="ETHUSD" trades={trades.filter((t) => t.symbol === "ETHUSD")} />
      </div>

      <div className="pcr-oi-section">
        <h3>Gold/USD</h3>
        <CryptoChart symbol="XAUTUSD" trades={trades.filter((t) => t.symbol === "XAUTUSD")} />
      </div>

      <PaperTradesPanel
        trades={trades}
        loading={tradesLoading}
        error={tradesError}
        onRefresh={loadTrades}
        title="Closed trades"
        variant="closed"
        secondsUntilRefresh={secondsUntilTradesRefresh}
      />
    </section>
  );
}

function CryptoChart({ symbol, trades }: { symbol: CryptoSwingSymbol; trades: CryptoSwingTrade[] }) {
  const mainContainerRef = useRef<HTMLDivElement | null>(null);
  const macdContainerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const emaSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const stUpSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const stDownSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdChartRef = useRef<IChartApi | null>(null);
  const macdLineSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const signalLineSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const histogramSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const closeByTimeRef = useRef<Map<UTCTimestamp, number>>(new Map());
  const macdByTimeRef = useRef<Map<UTCTimestamp, number>>(new Map());

  const [data, setData] = useState<CryptoSwingIndicators | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const payload = await getCryptoSwingCandles(symbol);
        if (cancelled) return;
        if (payload.error) {
          setError(payload.error);
          return;
        }
        setData(payload);
        setError(null);
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : `Failed to load ${symbol} candles.`);
      }
    }
    load();
    const timer = window.setInterval(load, CANDLES_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [symbol]);

  useEffect(() => {
    if (!mainContainerRef.current || !macdContainerRef.current || chartRef.current) return;
    const chart = createChart(mainContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: mainContainerRef.current.clientWidth,
      height: 320,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (time: Time) => formatCryptoTime(time) },
      localization: { timeFormatter: (time: Time) => formatCryptoTime(time) },
    });
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#168448",
      downColor: "#c93535",
      borderVisible: false,
      wickUpColor: "#168448",
      wickDownColor: "#c93535",
    });
    const emaLine = chart.addSeries(LineSeries, { color: "#2368b6", lineWidth: 2, title: "EMA200" });
    const stUp = chart.addSeries(LineSeries, { color: "#168448", lineWidth: 2, title: "Supertrend" });
    const stDown = chart.addSeries(LineSeries, { color: "#c93535", lineWidth: 2 });

    const macdChart = createChart(macdContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: macdContainerRef.current.clientWidth,
      height: 140,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (time: Time) => formatCryptoTime(time) },
      localization: { timeFormatter: (time: Time) => formatCryptoTime(time) },
    });
    const histogramSeries = macdChart.addSeries(HistogramSeries, { color: "#8391a3" });
    const macdLine = macdChart.addSeries(LineSeries, { color: "#2368b6", lineWidth: 1, title: "MACD" });
    const signalLine = macdChart.addSeries(LineSeries, { color: "#c9772f", lineWidth: 1, title: "Signal" });

    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) macdChart.timeScale().setVisibleLogicalRange(range);
    });
    macdChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) chart.timeScale().setVisibleLogicalRange(range);
    });

    // Crosshair sync -- setCrosshairPosition is a programmatic move, not a
    // real mouse event, so it doesn't re-trigger these handlers and can't
    // feed back into an infinite loop between the two charts.
    chart.subscribeCrosshairMove((param) => {
      if (!param.point || param.time === undefined) {
        macdChart.clearCrosshairPosition();
        return;
      }
      const t = param.time as UTCTimestamp;
      macdChart.setCrosshairPosition(macdByTimeRef.current.get(t) ?? 0, t, macdLine);
    });
    macdChart.subscribeCrosshairMove((param) => {
      if (!param.point || param.time === undefined) {
        chart.clearCrosshairPosition();
        return;
      }
      const t = param.time as UTCTimestamp;
      chart.setCrosshairPosition(closeByTimeRef.current.get(t) ?? 0, t, candleSeries);
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    emaSeriesRef.current = emaLine;
    stUpSeriesRef.current = stUp;
    stDownSeriesRef.current = stDown;
    macdChartRef.current = macdChart;
    macdLineSeriesRef.current = macdLine;
    signalLineSeriesRef.current = signalLine;
    histogramSeriesRef.current = histogramSeries;
    markersRef.current = createSeriesMarkers(candleSeries, []);

    const resizeObserver = new ResizeObserver(() => {
      if (mainContainerRef.current) chart.applyOptions({ width: mainContainerRef.current.clientWidth });
      if (macdContainerRef.current) macdChart.applyOptions({ width: macdContainerRef.current.clientWidth });
    });
    resizeObserver.observe(mainContainerRef.current);

    return () => {
      resizeObserver.disconnect();
      markersRef.current?.detach();
      chart.remove();
      macdChart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      emaSeriesRef.current = null;
      stUpSeriesRef.current = null;
      stDownSeriesRef.current = null;
      macdChartRef.current = null;
      macdLineSeriesRef.current = null;
      signalLineSeriesRef.current = null;
      histogramSeriesRef.current = null;
      markersRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!data || !candleSeriesRef.current) return;
    const times = data.candles.map((c) => c.time as UTCTimestamp);

    closeByTimeRef.current = new Map(times.map((t, i) => [t, data.candles[i].close]));
    macdByTimeRef.current = new Map(times.map((t, i) => [t, data.macdLine[i] ?? 0]));

    candleSeriesRef.current.setData(
      data.candles.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })),
    );
    emaSeriesRef.current?.setData(numericSeries(times, data.ema200));

    const stUp = data.supertrend.map((v, i) => (data.supertrendDirection[i] === "up" ? v : null));
    const stDown = data.supertrend.map((v, i) => (data.supertrendDirection[i] === "down" ? v : null));
    stUpSeriesRef.current?.setData(numericSeries(times, stUp));
    stDownSeriesRef.current?.setData(numericSeries(times, stDown));

    macdLineSeriesRef.current?.setData(numericSeries(times, data.macdLine));
    signalLineSeriesRef.current?.setData(numericSeries(times, data.signalLine));
    histogramSeriesRef.current?.setData(
      data.histogram
        .map((v, i) => (v === null ? null : { time: times[i], value: v, color: v >= 0 ? "#16844880" : "#c9353580" }))
        .filter((point): point is { time: UTCTimestamp; value: number; color: string } => point !== null),
    );
  }, [data]);

  useEffect(() => {
    if (!markersRef.current) return;
    markersRef.current.setMarkers(buildTradeMarkers(trades));
  }, [trades]);

  return (
    <div>
      {error ? <div className="alert error">{error}</div> : null}
      <div ref={mainContainerRef} style={{ width: "100%" }} />
      <div className="subtext" style={{ margin: "8px 0 4px" }}>
        MACD (12, 26, 9)
      </div>
      <div ref={macdContainerRef} style={{ width: "100%" }} />
    </div>
  );
}

function buildTradeMarkers(trades: CryptoSwingTrade[]): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = [];
  for (const t of trades) {
    if (t.status === "error" || t.entryTime === null) continue;
    const isLong = t.side === "long";
    markers.push({
      time: t.entryTime as UTCTimestamp,
      position: isLong ? "belowBar" : "aboveBar",
      color: isLong ? "#168448" : "#c93535",
      shape: isLong ? "arrowUp" : "arrowDown",
      text: `Entry ${fmtPrice(t.entryPrice)}`,
    });
    if (t.status === "closed" && t.exitTime !== null) {
      const positive = (t.pnlPercent ?? 0) >= 0;
      markers.push({
        time: t.exitTime as UTCTimestamp,
        position: isLong ? "aboveBar" : "belowBar",
        color: positive ? "#168448" : "#c93535",
        shape: "circle",
        text: `Exit ${fmtPrice(t.exitPrice)} (${(t.pnlPercent ?? 0).toFixed(2)}%)`,
      });
    }
  }
  markers.sort((a, b) => (a.time as number) - (b.time as number));
  return markers;
}

function numericSeries(times: UTCTimestamp[], values: (number | null)[]): { time: UTCTimestamp; value: number }[] {
  return values
    .map((value, i) => (value === null ? null : { time: times[i], value }))
    .filter((point): point is { time: UTCTimestamp; value: number } => point !== null);
}

function formatCryptoTime(time: Time): string {
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
