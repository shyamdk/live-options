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
import { LineChart, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { getNiftySwingCandles, getNiftySwingLiveStatus, getNiftySwingTrades } from "@/lib/api";
import type { CryptoSwingTrailSettings } from "@/lib/api";
import type { NiftySwingIndicators, NiftySwingLiveStatus, NiftySwingResolution, NiftySwingTrade } from "@/types/nifty-swing";

const RESOLUTIONS: NiftySwingResolution[] = ["5m", "15m", "30m", "1h"];
const LIVE_STATUS_REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_NIFTY_SWING_LIVE_STATUS_REFRESH_SECONDS, 60);

function secondsToMs(value: string | undefined, fallbackSeconds: number): number {
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : fallbackSeconds * 1000;
}

const CANDLES_REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_NIFTY_SWING_CANDLES_REFRESH_SECONDS, 60);
const TRADES_REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_NIFTY_SWING_TRADES_REFRESH_SECONDS, 30);
const TRAIL_SETTINGS_KEY = "live-options-nifty-swing-trail-settings";
const DEFAULT_TRAIL_SETTINGS: CryptoSwingTrailSettings = { arm: 2.0, multiple: 1.5 };
const QUANTITY_KEY = "live-options-nifty-swing-quantity";
const DEFAULT_QUANTITY = 50;

function loadTrailSettings(): CryptoSwingTrailSettings {
  try {
    const raw = window.localStorage.getItem(TRAIL_SETTINGS_KEY);
    if (raw) return { ...DEFAULT_TRAIL_SETTINGS, ...(JSON.parse(raw) as Partial<CryptoSwingTrailSettings>) };
  } catch {
    // fall through to defaults
  }
  return DEFAULT_TRAIL_SETTINGS;
}

function saveTrailSettings(settings: CryptoSwingTrailSettings): void {
  try {
    window.localStorage.setItem(TRAIL_SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    // Best-effort only.
  }
}

function loadQuantity(): number {
  try {
    const raw = window.localStorage.getItem(QUANTITY_KEY);
    const parsed = raw ? Number(raw) : NaN;
    return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_QUANTITY;
  } catch {
    return DEFAULT_QUANTITY;
  }
}

function saveQuantity(quantity: number): void {
  try {
    window.localStorage.setItem(QUANTITY_KEY, String(quantity));
  } catch {
    // Best-effort only.
  }
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
  return `${sign}${pct.toFixed(2)}% (${sign}₹${amount.toFixed(2)})`;
}

function fmtInr(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const sign = value >= 0 ? "+" : "";
  return `${sign}₹${value.toFixed(2)}`;
}

const EXIT_REASON_LABEL: Record<string, string> = {
  trap_confirmed_reversal: "Trend reversal confirmed",
  trail_stop: "Trailing stop (ATR)",
};

function LiveStatusPanel({ status, loading, error }: { status: NiftySwingLiveStatus | null; loading: boolean; error: string | null }) {
  return (
    <div className="pcr-oi-section">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>Live trading status</h3>
        {status ? (
          <span
            className="badge"
            style={{
              background: !status.liveEnabled ? "#8391a3" : status.mode === "shadow" ? "#2368b6" : "#c93535",
              color: "#fff",
            }}
          >
            {!status.liveEnabled ? "DISABLED" : status.mode === "shadow" ? "SHADOW (no real orders)" : "LIVE -- REAL ORDERS"}
          </span>
        ) : null}
      </div>
      {error ? <div className="alert error">{error}</div> : null}
      {loading && !status ? <p className="pcr-oi-caption">Loading…</p> : null}
      {status ? (
        <>
          <p className="pcr-oi-caption" style={{ margin: "4px 0 10px" }}>
            {!status.liveEnabled
              ? "Live engine is off entirely -- only the deterministic paper-replay panels below are active."
              : status.mode === "shadow"
                ? "Every signal is evaluated and logged (entry/exit, quantity, guardrail checks) exactly as if it were real, but no order is ever sent to Dhan."
                : "Both nifty_swing_live_enabled and nifty_swing_shadow_mode=false are set -- real CNC orders are being placed with real capital."}
          </p>
          <div className="metric-grid" style={{ marginBottom: 10 }}>
            <div className="metric">
              <span>Open positions</span>
              <strong>{status.openPositions}</strong>
            </div>
            <div className="metric">
              <span>Today&apos;s realized P&amp;L</span>
              <strong style={{ color: status.todayRealizedPnlInr >= 0 ? "var(--green)" : "var(--red)" }}>
                {fmtInr(status.todayRealizedPnlInr)}
              </strong>
            </div>
            <div className="metric">
              <span>Quantity per tranche</span>
              <strong>{status.quantityPerTranche}</strong>
            </div>
            <div className="metric">
              <span>Max capital</span>
              <strong>₹{status.maxCapitalRupees.toLocaleString("en-IN")}</strong>
            </div>
            <div className="metric">
              <span>Max daily loss</span>
              <strong>₹{status.maxDailyLossRupees.toLocaleString("en-IN")}</strong>
            </div>
            <div className="metric">
              <span>Product type</span>
              <strong>{status.productType}</strong>
            </div>
          </div>
          {status.trades.length === 0 ? (
            <p className="pcr-oi-caption">No {status.mode} trades recorded yet.</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Entry time</th>
                    <th>Entry price</th>
                    <th>Quantity</th>
                    <th>Tranches</th>
                    <th>Exit time</th>
                    <th>Exit reason</th>
                    <th>P&amp;L</th>
                    <th>Note</th>
                  </tr>
                </thead>
                <tbody>
                  {status.trades.map((t) => (
                    <tr key={t.id}>
                      <td>{t.status === "open" ? <span className="badge buy">OPEN</span> : "Closed"}</td>
                      <td>{fmtDateTime(t.entryTime)}</td>
                      <td>{fmtPrice(t.entryPrice)}</td>
                      <td>{t.quantity}</td>
                      <td>{t.tranches}</td>
                      <td>{fmtDateTime(t.exitTime)}</td>
                      <td>{t.exitReason ? EXIT_REASON_LABEL[t.exitReason] ?? t.exitReason : "—"}</td>
                      <td style={{ color: (t.pnlInr ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>{fmtInr(t.pnlInr)}</td>
                      <td style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={t.note ?? ""}>
                        {t.note ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}

function PaperTradesPanel({
  trades,
  loading,
  error,
  onRefresh,
  title,
  variant,
  secondsUntilRefresh,
}: {
  trades: NiftySwingTrade[];
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
        <h3 style={{ margin: 0 }}>
          {title} <span className="pcr-oi-caption">(NIFTYBEES)</span>
        </h3>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="pcr-oi-caption">Auto-refreshes in {secondsUntilRefresh}s</span>
          <button type="button" className="button secondary" onClick={onRefresh} disabled={loading}>
            <RefreshCw size={14} /> {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>
      <p className="pcr-oi-caption" style={{ margin: "4px 0 10px" }}>
        Simulated only -- replayed deterministically from the same 3-way confirmation strategy as Crypto-Swing, but
        long-only (NIFTYBEES is a cash ETF, not shortable) and sized in real units, not leveraged notional. No real
        orders are placed. Peak = best price reached since entry; Trail stop = the current ATR Chandelier level once
        armed -- it can exit a position even while a counter-move is still being held as a suspected trap.
      </p>
      {error ? <div className="alert error">{error}</div> : null}
      {errors.map((t, i) => (
        <div className="alert error" key={`err-${i}`}>
          {t.error}
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
                <th>Entry time</th>
                <th>Entry price</th>
                <th>Tranches</th>
                <th>Quantity</th>
                <th>Peak</th>
                <th>Trail stop</th>
                {variant === "open" ? (
                  <>
                    <th>Current price</th>
                    <th>Current P&amp;L</th>
                    <th>Box stop</th>
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
                  <tr key={`${t.entryTime}-${i}`}>
                    <td>{fmtDateTime(t.entryTime)}</td>
                    <td>{fmtPrice(t.entryPrice)}</td>
                    <td>{t.tranches}</td>
                    <td>{t.quantity}</td>
                    <td>{fmtPrice(t.peakPrice)}</td>
                    <td>
                      {t.trailStop !== null && t.trailStop !== undefined ? (
                        fmtPrice(t.trailStop)
                      ) : (
                        <span className="pcr-oi-caption">not armed</span>
                      )}
                    </td>
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

export default function NiftySwingPage() {
  const [resolution, setResolution] = useState<NiftySwingResolution>("30m");

  const [trades, setTrades] = useState<NiftySwingTrade[]>([]);
  const [tradesLoading, setTradesLoading] = useState(true);
  const [tradesError, setTradesError] = useState<string | null>(null);
  const [lastTradesRefreshAt, setLastTradesRefreshAt] = useState(Date.now());
  const [nowTick, setNowTick] = useState(Date.now());

  const [trailSettings, setTrailSettings] = useState<CryptoSwingTrailSettings>(DEFAULT_TRAIL_SETTINGS);
  const [trailArmInput, setTrailArmInput] = useState(String(DEFAULT_TRAIL_SETTINGS.arm));
  const [trailMultipleInput, setTrailMultipleInput] = useState(String(DEFAULT_TRAIL_SETTINGS.multiple));

  const [quantity, setQuantity] = useState(DEFAULT_QUANTITY);
  const [quantityInput, setQuantityInput] = useState(String(DEFAULT_QUANTITY));

  useEffect(() => {
    const loaded = loadTrailSettings();
    setTrailSettings(loaded);
    setTrailArmInput(String(loaded.arm));
    setTrailMultipleInput(String(loaded.multiple));
    const loadedQty = loadQuantity();
    setQuantity(loadedQty);
    setQuantityInput(String(loadedQty));
  }, []);

  useEffect(() => {
    saveTrailSettings(trailSettings);
  }, [trailSettings]);

  useEffect(() => {
    saveQuantity(quantity);
  }, [quantity]);

  function commitTrailSettings() {
    const arm = Math.max(0.1, Math.min(10, Number(trailArmInput) || DEFAULT_TRAIL_SETTINGS.arm));
    const multiple = Math.max(0.1, Math.min(10, Number(trailMultipleInput) || DEFAULT_TRAIL_SETTINGS.multiple));
    setTrailArmInput(String(arm));
    setTrailMultipleInput(String(multiple));
    setTrailSettings({ arm, multiple });
  }

  function commitQuantity() {
    const value = Math.max(1, Math.min(100_000, Math.round(Number(quantityInput)) || DEFAULT_QUANTITY));
    setQuantityInput(String(value));
    setQuantity(value);
  }

  useEffect(() => {
    const tick = window.setInterval(() => setNowTick(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, []);

  async function loadTrades() {
    setTradesLoading(true);
    setLastTradesRefreshAt(Date.now());
    try {
      const payload = await getNiftySwingTrades(resolution, trailSettings, quantity);
      setTrades(payload.trades);
      setTradesError(null);
    } catch (exc) {
      setTradesError(exc instanceof Error ? exc.message : "Failed to load paper trades.");
    } finally {
      setTradesLoading(false);
    }
  }

  useEffect(() => {
    loadTrades();
    const timer = window.setInterval(loadTrades, TRADES_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [resolution, trailSettings, quantity]);

  const [liveStatus, setLiveStatus] = useState<NiftySwingLiveStatus | null>(null);
  const [liveStatusLoading, setLiveStatusLoading] = useState(true);
  const [liveStatusError, setLiveStatusError] = useState<string | null>(null);

  async function loadLiveStatus() {
    setLiveStatusLoading(true);
    try {
      setLiveStatus(await getNiftySwingLiveStatus());
      setLiveStatusError(null);
    } catch (exc) {
      setLiveStatusError(exc instanceof Error ? exc.message : "Failed to load live trading status.");
    } finally {
      setLiveStatusLoading(false);
    }
  }

  useEffect(() => {
    loadLiveStatus();
    const timer = window.setInterval(loadLiveStatus, LIVE_STATUS_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  const secondsUntilTradesRefresh = Math.max(0, Math.ceil((TRADES_REFRESH_MS - (nowTick - lastTradesRefreshAt)) / 1000));

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <LineChart size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Nifty-Swing
          </h1>
          <p>
            The same 3-way confirmation strategy as Crypto-Swing (Supertrend flip + EMA200 macro filter + MACD
            alignment), applied to NIFTYBEES instead of a crypto perpetual. Long-only, real share quantity instead of
            leveraged notional. A live/shadow engine (see status below) can place real CNC orders once explicitly
            enabled -- shadow mode logs what it would do without ever sending an order.
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

      <div className="toolbar" style={{ margin: "0 0 8px", alignItems: "center", gap: 8 }}>
        <span className="pcr-oi-caption" style={{ fontWeight: 600 }}>
          ATR trailing stop:
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span className="pcr-oi-caption">Arm</span>
          <input
            type="number"
            value={trailArmInput}
            onChange={(e) => setTrailArmInput(e.target.value)}
            onBlur={commitTrailSettings}
            onKeyDown={(e) => e.key === "Enter" && commitTrailSettings()}
            style={{ width: 52 }}
            min={0.1}
            max={10}
            step={0.1}
            aria-label="Trail arm ATR multiple"
          />
          <span className="pcr-oi-caption">x ATR</span>
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span className="pcr-oi-caption">Trail</span>
          <input
            type="number"
            value={trailMultipleInput}
            onChange={(e) => setTrailMultipleInput(e.target.value)}
            onBlur={commitTrailSettings}
            onKeyDown={(e) => e.key === "Enter" && commitTrailSettings()}
            style={{ width: 52 }}
            min={0.1}
            max={10}
            step={0.1}
            aria-label="Trail distance ATR multiple"
          />
          <span className="pcr-oi-caption">x ATR</span>
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 4, marginLeft: "auto" }}>
          <span className="pcr-oi-caption">Quantity per tranche</span>
          <input
            type="number"
            value={quantityInput}
            onChange={(e) => setQuantityInput(e.target.value)}
            onBlur={commitQuantity}
            onKeyDown={(e) => e.key === "Enter" && commitQuantity()}
            style={{ width: 70 }}
            min={1}
            max={100_000}
            aria-label="Quantity per tranche"
          />
        </span>
      </div>

      <LiveStatusPanel status={liveStatus} loading={liveStatusLoading} error={liveStatusError} />

      <PaperTradesPanel
        trades={trades}
        loading={tradesLoading}
        error={tradesError}
        onRefresh={loadTrades}
        title="Live trades"
        variant="open"
        secondsUntilRefresh={secondsUntilTradesRefresh}
      />

      <NiftySwingChart resolution={resolution} trades={trades} />

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

function NiftySwingChart({ resolution, trades }: { resolution: NiftySwingResolution; trades: NiftySwingTrade[] }) {
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

  const [data, setData] = useState<NiftySwingIndicators | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const payload = await getNiftySwingCandles(resolution);
        if (cancelled) return;
        if (payload.error) {
          setError(payload.error);
          return;
        }
        setData(payload);
        setError(null);
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : "Failed to load NIFTYBEES candles.");
      }
    }
    load();
    const timer = window.setInterval(load, CANDLES_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [resolution]);

  useEffect(() => {
    if (!mainContainerRef.current || !macdContainerRef.current || chartRef.current) return;
    const chart = createChart(mainContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: mainContainerRef.current.clientWidth,
      height: 320,
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
    const emaLine = chart.addSeries(LineSeries, { color: "#2368b6", lineWidth: 2, title: "EMA200" });
    const stUp = chart.addSeries(LineSeries, { color: "#168448", lineWidth: 2, title: "Supertrend" });
    const stDown = chart.addSeries(LineSeries, { color: "#c93535", lineWidth: 2 });

    const macdChart = createChart(macdContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: macdContainerRef.current.clientWidth,
      height: 140,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (time: Time) => formatIstTime(time) },
      localization: { timeFormatter: (time: Time) => formatIstTime(time) },
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
    <div className="pcr-oi-section">
      <h3>NIFTYBEES</h3>
      {error ? <div className="alert error">{error}</div> : null}
      <div ref={mainContainerRef} style={{ width: "100%" }} />
      <div className="subtext" style={{ margin: "8px 0 4px" }}>
        MACD (12, 26, 9)
      </div>
      <div ref={macdContainerRef} style={{ width: "100%" }} />
    </div>
  );
}

function buildTradeMarkers(trades: NiftySwingTrade[]): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = [];
  for (const t of trades) {
    if (t.status === "error" || t.entryTime === null) continue;
    markers.push({
      time: t.entryTime as UTCTimestamp,
      position: "belowBar",
      color: "#168448",
      shape: "arrowUp",
      text: `Entry ${fmtPrice(t.entryPrice)}`,
    });
    if (t.status === "closed" && t.exitTime !== null) {
      const positive = (t.pnlPercent ?? 0) >= 0;
      markers.push({
        time: t.exitTime as UTCTimestamp,
        position: "aboveBar",
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
