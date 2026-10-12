"use client";

import { ColorType, createChart, createSeriesMarkers, IChartApi, IPriceLine, ISeriesApi, LineSeries, Time, UTCTimestamp } from "lightweight-charts";
import { Play, RefreshCw, Save, SquareArrowOutUpRight, Waves } from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";

import CollapsibleSection from "@/components/CollapsibleSection";
import { DailyTotalsTable, groupDailyTotals } from "@/components/DailyTotals";
import StrikeDistanceMap from "@/components/StrikeDistanceMap";
import { closeCalmTrade, enterCalmNow, getCalmState, getCalmTrades, updateCalmConfig } from "@/lib/api";
import type { CalmConfig, CalmState, CalmTrade } from "@/types/calm-strangle";

const REFRESH_MS = 15000;

function inr(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value < 0 ? "−" : ""}₹${Math.abs(Math.round(value)).toLocaleString("en-IN")}`;
}

function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function signed(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(2)}`;
}

function tone(value: number | null | undefined): string | undefined {
  if (!value) return undefined;
  return value > 0 ? "var(--green)" : "var(--red)";
}

function clock(epoch: number | null | undefined): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });
}

function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(`${iso}T00:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", weekday: "short", day: "2-digit", month: "short" });
}

export default function CalmStranglePage() {
  const [state, setState] = useState<CalmState | null>(null);
  const [trades, setTrades] = useState<CalmTrade[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    try {
      const [s, t] = await Promise.all([getCalmState(), getCalmTrades()]);
      setState(s);
      setTrades(t.trades);
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load Calm Strangle.");
    }
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  async function act(key: string, fn: () => Promise<string>) {
    setBusy(key);
    try {
      setMessage(await fn());
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Action failed.");
    } finally {
      setBusy(null);
    }
  }

  const config = state?.config;
  const snap = state?.snapshot;
  const closed = trades.filter((t) => t.status === "CLOSED");

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Waves size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Calm Strangle
          </h1>
          <p>
            Intraday NIFTY short strangle sold only after the market settles: when NIFTY&apos;s last {config?.calmWindow ?? 15} minutes move less than{" "}
            {config?.calmPercent ?? 15}% of the ATM straddle, sell CE/PE at ±{config?.strikeMultiple ?? 1}× straddle; exit if NIFTY moves{" "}
            {config?.stopMultiple ?? 0.6}× straddle or at {config?.exitTime ?? "15:15"}; re-enter when it settles again. No trading on expiry day.
            See calm-strangle.md.
          </p>
        </div>
        <div className="toolbar" style={{ alignItems: "center" }}>
          <span className="status-live on" style={{ whiteSpace: "nowrap" }}>
            {state?.mode === "live" ? "LIVE" : "PAPER"}
          </span>
          <span className={`status-live ${config?.enabled ? "on" : ""}`} style={{ whiteSpace: "nowrap" }}>
            {config ? (config.enabled ? "Auto entry on" : "Auto entry paused") : "…"}
          </span>
          <button type="button" className="button secondary" onClick={load} style={{ whiteSpace: "nowrap" }}>
            <RefreshCw size={14} /> Refresh
          </button>
          <button
            type="button"
            className="button"
            disabled={!!busy || !!state?.openTrade}
            style={{ whiteSpace: "nowrap" }}
            onClick={() =>
              window.confirm("Sell the strangle now, without waiting for the calm test?") &&
              act("enter", async () => {
                const r = await enterCalmNow();
                return r.message ? `${r.status}: ${r.message}` : `Strangle ${r.status}.`;
              })
            }
          >
            <Play size={14} /> Enter now
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}

      <StatusStrip state={state} />

      <CollapsibleSection id="calm-chart" title="NIFTY today" aside={<span className="pcr-oi-caption">1-min closes · ▼ entries, ▲ exits · dashed: open position&apos;s stop band</span>}>
        <SpotChart state={state} />
      </CollapsibleSection>

      <CollapsibleSection id="calm-open" title={`Open position (${state?.openTrade ? 1 : 0})`}>
        {state?.openTrade ? (
          <OpenPosition
            trade={state.openTrade}
            busy={busy === "close"}
            onClose={() =>
              window.confirm(`Buy back #${state.openTrade!.id} now?`) &&
              act("close", async () => {
                const r = await closeCalmTrade(state.openTrade!.id);
                return `#${state.openTrade!.id}: ${r.status}`;
              })
            }
          />
        ) : (
          <NextEntry state={state} />
        )}
      </CollapsibleSection>

      <CollapsibleSection id="calm-today" title={`Today's trades (${state?.todayTrades.length ?? 0})`}>
        <TradesTable trades={state?.todayTrades ?? []} />
      </CollapsibleSection>

      <CollapsibleSection id="calm-log" title={`Today's log (${state?.events.length ?? 0})`} defaultOpen={false}>
        {state?.events.length ? (
          <table style={{ fontSize: 12 }}>
            <tbody>
              {state.events.map((e, i) => (
                <tr key={i}>
                  <td style={{ whiteSpace: "nowrap" }}>{clock(e.time)}</td>
                  <td>{e.kind}</td>
                  <td>{e.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="pcr-oi-caption" style={{ margin: 0 }}>Nothing yet today.</p>
        )}
      </CollapsibleSection>

      <CollapsibleSection id="calm-pnl" title="Daily P&L">
        <DailyTotalsTable rows={groupDailyTotals(closed, (t) => t.exitTime, (t) => t.grossPnl, (t) => t.netPnl)} />
        <BacktestReference trades={closed} />
      </CollapsibleSection>

      <CollapsibleSection id="calm-history" title={`All trades (${trades.length})`} defaultOpen={false}>
        <TradesTable trades={trades} showDay />
      </CollapsibleSection>

      {config ? <SettingsSection config={config} onSaved={load} /> : null}
    </section>
  );
}

function Metric({ label, value, caption, color }: { label: string; value: string; caption?: string; color?: string }) {
  return (
    <div className="metric metric-compact" style={{ flex: "1 1 150px" }}>
      <span>{label}</span>
      <strong style={{ color }}>{value}</strong>
      {caption ? <span className="pcr-oi-caption">{caption}</span> : null}
    </div>
  );
}

function StatusStrip({ state }: { state: CalmState | null }) {
  const snap = state?.snapshot;
  const config = state?.config;
  const expiryDay = snap?.dte === 0;
  const ratio = snap?.calmRange != null && snap?.calmThreshold ? snap.calmRange / snap.calmThreshold : null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
      <Metric
        label="Today"
        value={snap?.expiry ? (expiryDay ? "Expiry day" : `${snap.dte}d to expiry`) : "—"}
        caption={snap?.expiry ? `expiry ${day(snap.expiry)}${expiryDay && config?.skipExpiryDay ? " · no trading today" : ""}` : snap?.error ?? ""}
        color={expiryDay && config?.skipExpiryDay ? "var(--amber)" : undefined}
      />
      <Metric label="NIFTY" value={num(snap?.spot)} caption={snap?.atmStrike ? `ATM ${snap.atmStrike.toLocaleString("en-IN")} · ${clock(snap.time)}` : ""} />
      <Metric label="ATM straddle" value={num(snap?.straddle)} caption="the move still priced in today" />
      <div className="metric metric-compact" style={{ flex: "1 1 220px" }}>
        <span>Calm test (last {config?.calmWindow ?? 15} min)</span>
        <strong style={{ color: snap?.calm ? "var(--green)" : "var(--red)" }}>
          {snap?.calm ? "CALM" : "moving"} · {num(snap?.calmRange, 1)} / {num(snap?.calmThreshold, 1)} pts
        </strong>
        <div style={{ height: 6, borderRadius: 3, background: "var(--line-soft)", marginTop: 4 }}>
          <div
            style={{
              width: `${Math.min(100, (ratio ?? 0) * 50)}%`,
              height: 6,
              borderRadius: 3,
              background: (ratio ?? 2) <= 1 ? "var(--green)" : "var(--red)",
            }}
          />
        </div>
        <span className="pcr-oi-caption">range must be ≤ {config?.calmPercent ?? 15}% of the straddle (bar half-way = threshold)</span>
      </div>
      <Metric
        label="Entries / stops today"
        value={`${state?.entriesToday ?? 0}/${config?.maxEntries ?? 3} · ${state?.stopsToday ?? 0}/${config?.maxStops ?? 2}`}
        caption={`entries ${config?.entryStart ?? ""}–${config?.lastEntry ?? ""}, flat ${config?.exitTime ?? ""}`}
      />
      <Metric label="Market" value={state?.marketOpen ? "Open" : "Closed"} caption="checked 2 s after each minute closes" />
    </div>
  );
}

function NextEntry({ state }: { state: CalmState | null }) {
  const snap = state?.snapshot;
  const config = state?.config;
  if (!snap || snap.error) return <p className="pcr-oi-caption">{snap?.error ?? "Loading…"}</p>;
  const legs = snap.legs ?? {};
  return (
    <div>
      <p className="pcr-oi-caption" style={{ marginTop: 0 }}>
        No open position. If the calm test passes in the entry window it would sell, right now:
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        <Metric label="PE" value={legs.PE ? `${legs.PE.strike.toLocaleString("en-IN")} @ ${num(legs.PE.bid)}` : "—"} caption={legs.PE ? `${legs.PE.distancePercent}% below · Δ ${num(legs.PE.delta)}` : ""} />
        <Metric label="CE" value={legs.CE ? `${legs.CE.strike.toLocaleString("en-IN")} @ ${num(legs.CE.bid)}` : "—"} caption={legs.CE ? `${legs.CE.distancePercent}% above · Δ ${num(legs.CE.delta)}` : ""} />
        <Metric
          label="Credit"
          value={snap.credit ? `${num(snap.credit)} pts` : "—"}
          caption={snap.credit && config ? `${inr(snap.credit * config.quantity)} on ${config.lots} lots · min ${config.minCredit} pts` : ""}
        />
        <Metric label="Stop band" value={`± ${num(snap.stopBand, 0)} pts`} caption={`NIFTY ${num((snap.spot ?? 0) - (snap.stopBand ?? 0), 0)} – ${num((snap.spot ?? 0) + (snap.stopBand ?? 0), 0)}`} />
      </div>
    </div>
  );
}

function OpenPosition({ trade: t, busy, onClose }: { trade: CalmTrade; busy: boolean; onClose: () => void }) {
  const spot = t.lastSpot ?? t.entrySpot;
  const pos = Math.max(0, Math.min(100, ((spot - t.stopLow) / (t.stopHigh - t.stopLow)) * 100));
  return (
    <div className="strategy-chart-card">
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "baseline" }}>
        <strong>
          #{t.id} · SHORT {t.peStrike.toLocaleString("en-IN")} PE / {t.ceStrike.toLocaleString("en-IN")} CE · {t.lots} lots
        </strong>
        <span className="pcr-oi-caption">
          {t.mode.toUpperCase()} · entered {clock(t.entryTime)} at NIFTY {num(t.entrySpot)} ({t.trigger}{t.calmRange != null ? `, range ${num(t.calmRange, 1)}` : ""})
        </span>
        <button type="button" className="button secondary" onClick={onClose} disabled={busy} style={{ marginLeft: "auto" }}>
          <SquareArrowOutUpRight size={14} /> Buy back now
        </button>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 10 }}>
        <Metric label="Credit (sold)" value={num(t.credit)} caption={`PE ${num(t.entryPe)} + CE ${num(t.entryCe)} · ${inr(t.premiumCollected)}`} />
        <Metric label="Now" value={num(t.current)} caption={`PE ${num(t.lastPe)} + CE ${num(t.lastCe)} · ${clock(t.lastUpdate)}`} />
        <Metric label="P&L" value={inr(t.grossPnl)} caption={`${signed(t.points)} pts · net ${inr(t.netPnl)}`} color={tone(t.grossPnl)} />
        <Metric label="Best / worst" value={`${num(t.best)} / ${num(t.worst)}`} caption="combined premium seen" />
        <Metric label="Backstop" value={num(t.backstop)} caption="combined premium exit" />
        <Metric label="Held" value={`${t.minutesHeld} min`} caption={`charges ${inr(t.charges)}`} />
      </div>
      <div style={{ marginTop: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
          <span style={{ color: "var(--red)" }}>stop {num(t.stopLow, 0)}</span>
          <span>NIFTY {num(spot)}</span>
          <span style={{ color: "var(--red)" }}>stop {num(t.stopHigh, 0)}</span>
        </div>
        <div style={{ position: "relative", height: 10, borderRadius: 5, background: "var(--line-soft)", marginTop: 4 }}>
          <div style={{ position: "absolute", left: "50%", top: -3, width: 2, height: 16, background: "var(--muted)" }} title="entry" />
          <div style={{ position: "absolute", left: `calc(${pos}% - 6px)`, top: -1, width: 12, height: 12, borderRadius: 6, background: Math.abs(pos - 50) > 35 ? "var(--red)" : "var(--green)" }} />
        </div>
      </div>
      <div style={{ marginTop: 10 }}>
        <StrikeDistanceMap
          id={`calm-${t.id}`}
          spot={spot}
          legs={[
            { key: "pe", strike: t.peStrike, label: `${t.peStrike.toLocaleString("en-IN")} PE`, short: true },
            { key: "ce", strike: t.ceStrike, label: `${t.ceStrike.toLocaleString("en-IN")} CE`, short: true },
          ]}
          marks={[0.25, 0.5, 0.75, 1, 1.25]}
        />
      </div>
    </div>
  );
}

function TradesTable({ trades, showDay = false }: { trades: CalmTrade[]; showDay?: boolean }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!trades.length) return <p className="pcr-oi-caption" style={{ margin: 0 }}>No trades yet.</p>;
  const net = trades.reduce((a, t) => a + t.netPnl, 0);
  const wins = trades.filter((t) => t.status === "CLOSED" && t.netPnl > 0).length;
  const closedN = trades.filter((t) => t.status === "CLOSED").length;
  return (
    <div style={{ overflowX: "auto", width: 0, minWidth: "100%" }}>
      <p className="pcr-oi-caption" style={{ marginTop: 0 }}>
        {trades.length} trades · {closedN ? `${Math.round((wins / closedN) * 100)}% winners` : "—"} ·{" "}
        <strong style={{ color: tone(net) }}>net {inr(net)}</strong> · click a row for fills, quotes and order ids
      </p>
      <table style={{ fontSize: 12 }}>
        <thead>
          <tr>
            <th>#</th>
            {showDay ? <th>Day</th> : null}
            <th>Entry</th>
            <th>NIFTY</th>
            <th>Calm range</th>
            <th>Straddle</th>
            <th>PE / CE</th>
            <th>Credit</th>
            <th>Exit</th>
            <th>Reason</th>
            <th>Exit premium</th>
            <th>Held</th>
            <th>Pts</th>
            <th>Gross</th>
            <th>Charges</th>
            <th>Net</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <Fragment key={t.id}>
              <tr onClick={() => setOpen(open === t.id ? null : t.id)} style={{ cursor: "pointer" }}>
                <td>{t.id}</td>
                {showDay ? <td>{day(t.day)}</td> : null}
                <td>
                  {clock(t.entryTime)} {t.trigger === "manual" ? <span className="pcr-oi-caption">(manual)</span> : null}
                </td>
                <td>{num(t.entrySpot, 0)}</td>
                <td>{num(t.calmRange, 1)}</td>
                <td>{num(t.straddle)}</td>
                <td>
                  {t.peStrike} / {t.ceStrike}
                </td>
                <td>{num(t.credit)}</td>
                <td>{t.status === "OPEN" ? "open" : clock(t.exitTime)}</td>
                <td>{t.exitReason ?? "—"}</td>
                <td>{t.status === "OPEN" ? num(t.current) : num((t.exitCe ?? 0) + (t.exitPe ?? 0))}</td>
                <td>{t.minutesHeld}m</td>
                <td style={{ color: tone(t.points) }}>{signed(t.points)}</td>
                <td style={{ color: tone(t.grossPnl) }}>{inr(t.grossPnl)}</td>
                <td>{inr(t.charges)}</td>
                <td style={{ color: tone(t.netPnl) }}>
                  <strong>{inr(t.netPnl)}</strong>
                </td>
              </tr>
              {open === t.id ? (
                <tr>
                  <td colSpan={showDay ? 16 : 15} style={{ background: "var(--panel)" }}>
                    <div className="pcr-oi-caption" style={{ fontStyle: "normal" }}>
                      {(["PE", "CE"] as const).map((s) => (
                        <div key={s}>
                          <strong>{s}</strong> sold {num(s === "PE" ? t.entryPe : t.entryCe)} (bid/ask/ltp at entry {num(t.entryQuotes[s]?.bid)}/{num(t.entryQuotes[s]?.ask)}/
                          {num(t.entryQuotes[s]?.ltp)}) · bought {num(s === "PE" ? t.exitPe : t.exitCe)} (at exit {num(t.exitQuotes[s]?.bid)}/{num(t.exitQuotes[s]?.ask)}/
                          {num(t.exitQuotes[s]?.ltp)})
                        </div>
                      ))}
                      <div>
                        Stop band NIFTY {num(t.stopLow, 0)} – {num(t.stopHigh, 0)} · backstop {num(t.backstop)} · NIFTY at exit {num(t.exitSpot)} · expiry {t.expiry} ({t.dte}d) · {t.mode} ·
                        orders {Object.entries(t.orderIds).map(([k, v]) => `${k}:${v ?? "—"}`).join(" ")}
                      </div>
                    </div>
                  </td>
                </tr>
              ) : null}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BacktestReference({ trades }: { trades: CalmTrade[] }) {
  const days = new Set(trades.map((t) => t.day)).size;
  const net = trades.reduce((a, t) => a + t.netPnl, 0);
  const wins = trades.filter((t) => t.netPnl > 0).length;
  return (
    <div style={{ marginTop: 10, overflowX: "auto", width: 0, minWidth: "100%" }}>
      <table style={{ fontSize: 12 }}>
        <thead>
          <tr>
            <th />
            <th>Trading days</th>
            <th>Trades</th>
            <th>Win %</th>
            <th>Net</th>
            <th>Net per trading day</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Backtest (Apr–Oct 2026, 0.25 pt slippage)</td>
            <td>129</td>
            <td>119</td>
            <td>71%</td>
            <td>₹1,07,428</td>
            <td>₹833</td>
          </tr>
          <tr>
            <td>
              <strong>Paper so far</strong>
            </td>
            <td>{days}</td>
            <td>{trades.length}</td>
            <td>{trades.length ? `${Math.round((wins / trades.length) * 100)}%` : "—"}</td>
            <td style={{ color: tone(net) }}>{inr(net)}</td>
            <td style={{ color: tone(net) }}>{days ? inr(net / days) : "—"}</td>
          </tr>
        </tbody>
      </table>
      <p className="pcr-oi-caption">Per trading day counts only days with a trade here; the backtest figure is over all 129 days (some had no trade).</p>
    </div>
  );
}

function istTick(time: Time): string {
  return typeof time === "number" ? clock(time) : String(time);
}

function SpotChart({ state }: { state: CalmState | null }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const markersRef = useRef<ReturnType<typeof createSeriesMarkers<Time>> | null>(null);
  const linesRef = useRef<IPriceLine[]>([]);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: containerRef.current.clientWidth,
      height: 260,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (t: Time) => istTick(t) },
      localization: { timeFormatter: (t: Time) => istTick(t) },
    });
    seriesRef.current = chart.addSeries(LineSeries, { color: "#2368b6", lineWidth: 2, title: "NIFTY" });
    markersRef.current = createSeriesMarkers(seriesRef.current, []);
    chartRef.current = chart;
    const observer = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      linesRef.current = [];
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !state) return;
    series.setData(state.spot.map((c) => ({ time: c.time as UTCTimestamp, value: c.close })));
    const minute = (t: number) => (Math.floor(t / 60) * 60) as UTCTimestamp;
    markersRef.current?.setMarkers(
      state.todayTrades
        .flatMap((t) => [
          { time: minute(t.entryTime), position: "aboveBar" as const, color: "#c93535", shape: "arrowDown" as const, text: `#${t.id} sell ${num(t.credit)}` },
          ...(t.exitTime
            ? [{ time: minute(t.exitTime), position: "belowBar" as const, color: t.netPnl >= 0 ? "#168448" : "#c93535", shape: "arrowUp" as const, text: `exit ${inr(t.netPnl)}` }]
            : []),
        ])
        .sort((a, b) => (a.time as number) - (b.time as number)),
    );
    for (const l of linesRef.current) series.removePriceLine(l);
    linesRef.current = state.openTrade
      ? [
          series.createPriceLine({ price: state.openTrade.stopHigh, color: "#c93535", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "stop" }),
          series.createPriceLine({ price: state.openTrade.stopLow, color: "#c93535", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "stop" }),
          series.createPriceLine({ price: state.openTrade.entrySpot, color: "#7a8494", lineWidth: 1, lineStyle: 3, axisLabelVisible: false, title: "entry" }),
        ]
      : [];
    chartRef.current?.timeScale().fitContent();
  }, [state]);

  return <div ref={containerRef} style={{ width: "100%", height: 260 }} />;
}

const FIELDS: { key: keyof CalmConfig; label: string; hint: string; text?: boolean }[] = [
  { key: "lots", label: "Lots per leg", hint: "65 per lot" },
  { key: "calmPercent", label: "Calm: range ≤ % of straddle", hint: "15" },
  { key: "calmWindow", label: "Calm window (minutes)", hint: "15" },
  { key: "strikeMultiple", label: "Strikes at ± × straddle", hint: "1.0" },
  { key: "stopMultiple", label: "Stop: NIFTY move × straddle", hint: "0.6" },
  { key: "backstopPercent", label: "Premium backstop %", hint: "150" },
  { key: "minCredit", label: "Min credit (pts)", hint: "6" },
  { key: "entryStart", label: "Entries from", hint: "09:45", text: true },
  { key: "lastEntry", label: "Last entry", hint: "14:30", text: true },
  { key: "exitTime", label: "Flat at", hint: "15:15", text: true },
  { key: "maxEntries", label: "Max entries / day", hint: "3" },
  { key: "maxStops", label: "Max stops / day", hint: "2" },
];

function SettingsSection({ config, onSaved }: { config: CalmConfig; onSaved: () => void }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setDraft(Object.fromEntries(FIELDS.map((f) => [f.key, String(config[f.key])])));
  }, [config]);

  async function save(updates?: Partial<CalmConfig>) {
    setSaving(true);
    setError(null);
    try {
      await updateCalmConfig(updates ?? (Object.fromEntries(FIELDS.map((f) => [f.key, f.text ? draft[f.key] : Number(draft[f.key])])) as Partial<CalmConfig>));
      onSaved();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <CollapsibleSection id="calm-settings" title="Settings" defaultOpen={false}>
      {error ? <div className="alert error">{error}</div> : null}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12 }}>
        {FIELDS.map((f) => (
          <label key={f.key} style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12 }}>
            <span style={{ color: "var(--muted)", fontWeight: 600 }}>{f.label}</span>
            <input value={draft[f.key] ?? ""} onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))} style={{ width: 90, fontSize: 13, padding: "3px 6px" }} />
            <span className="pcr-oi-caption">backtest: {f.hint}</span>
          </label>
        ))}
      </div>
      <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", marginTop: 12, fontSize: 13 }}>
        <label style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={config.enabled} onChange={(e) => save({ enabled: e.target.checked })} disabled={saving} />
          Automatic entries
        </label>
        <label style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={config.skipExpiryDay} onChange={(e) => save({ skipExpiryDay: e.target.checked })} disabled={saving} />
          Skip expiry day
        </label>
        <button type="button" className="button" onClick={() => save()} disabled={saving}>
          <Save size={14} /> Save settings
        </button>
        <span className="pcr-oi-caption">
          {config.liveOrdersAllowed ? "Live orders allowed on the server." : "Live trading is locked on the server (CALM_STRANGLE_LIVE_ORDER_ENABLED=false) -- paper only."}
        </span>
      </div>
    </CollapsibleSection>
  );
}
