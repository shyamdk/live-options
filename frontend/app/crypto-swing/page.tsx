"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  IChartApi,
  ISeriesApi,
  LineSeries,
  Time,
  UTCTimestamp,
} from "lightweight-charts";
import { Bitcoin, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { getCryptoSwingCandles, getCryptoSwingWallet } from "@/lib/api";
import type { CryptoSwingIndicators, CryptoSwingSymbol, CryptoSwingWallet } from "@/types/crypto-swing";

function assetLabel(row: CryptoSwingWallet["balances"][number]): string {
  return row.asset_symbol ?? row.asset?.symbol ?? "?";
}

function fmtAmount(value: string | number | undefined): string {
  if (value === undefined || value === null) return "—";
  const num = typeof value === "string" ? Number(value) : value;
  return Number.isFinite(num) ? num.toLocaleString("en-IN", { maximumFractionDigits: 8 }) : String(value);
}

const CANDLES_REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_CRYPTO_SWING_CANDLES_REFRESH_SECONDS, 60);

function secondsToMs(value: string | undefined, fallbackSeconds: number): number {
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : fallbackSeconds * 1000;
}

export default function CryptoSwingPage() {
  const [wallet, setWallet] = useState<CryptoSwingWallet | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  useEffect(() => {
    load();
  }, []);

  const nonZero = wallet?.balances.filter((row) => Number(row.balance ?? 0) !== 0) ?? [];

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
        <div className="toolbar">
          <button type="button" className="button secondary" onClick={load} disabled={loading}>
            <RefreshCw size={14} /> {loading ? "Checking…" : "Refresh"}
          </button>
        </div>
      </header>

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
        <CryptoChart symbol="BTCUSD" />
      </div>

      <div className="pcr-oi-section">
        <h3>ETH/USD</h3>
        <CryptoChart symbol="ETHUSD" />
      </div>
    </section>
  );
}

function CryptoChart({ symbol }: { symbol: CryptoSwingSymbol }) {
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

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    emaSeriesRef.current = emaLine;
    stUpSeriesRef.current = stUp;
    stDownSeriesRef.current = stDown;
    macdChartRef.current = macdChart;
    macdLineSeriesRef.current = macdLine;
    signalLineSeriesRef.current = signalLine;
    histogramSeriesRef.current = histogramSeries;

    const resizeObserver = new ResizeObserver(() => {
      if (mainContainerRef.current) chart.applyOptions({ width: mainContainerRef.current.clientWidth });
      if (macdContainerRef.current) macdChart.applyOptions({ width: macdContainerRef.current.clientWidth });
    });
    resizeObserver.observe(mainContainerRef.current);

    return () => {
      resizeObserver.disconnect();
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
    };
  }, []);

  useEffect(() => {
    if (!data || !candleSeriesRef.current) return;
    const times = data.candles.map((c) => c.time as UTCTimestamp);

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
