"use client";

import { CandlestickSeries, ColorType, createChart, createSeriesMarkers, IChartApi, ISeriesApi, LineStyle, Time, UTCTimestamp } from "lightweight-charts";
import { Crosshair, RefreshCw, Save } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import CollapsibleSection from "@/components/CollapsibleSection";
import { DailyTotalsTable, groupDailyTotals } from "@/components/DailyTotals";
import { getChochCandles, getChochState, getChochTrades, updateChochConfig } from "@/lib/api";
import { cumulativeNet } from "@/lib/cumulative";
import { isMarketHoursNow } from "@/lib/marketHours";
import type { ChochConfig, ChochState, ChochTrade } from "@/types/choch";

type Candle = { time: number; open: number; high: number; low: number; close: number };

function inr(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v < 0 ? "−" : ""}₹${Math.abs(Math.round(v)).toLocaleString("en-IN")}`;
}

function num(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function tone(v: number | null | undefined): string | undefined {
  if (!v) return undefined;
  return v > 0 ? "var(--green)" : "var(--red)";
}

function clock(epoch: number | null | undefined, withDay = false): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false, ...(withDay ? { day: "numeric", month: "short" } : {}),
  });
}

const sideText = (s: number) => (s === 1 ? "LONG" : "SHORT");
const sideColor = (s: number) => (s === 1 ? "var(--green)" : "var(--red)");

function Metric({ label, value, caption, color }: { label: string; value: string; caption?: string; color?: string }) {
  return (
    <div className="metric metric-compact" style={{ flex: "1 1 150px" }}>
      <span>{label}</span>
      <strong style={{ color }}>{value}</strong>
      {caption ? <span className="pcr-oi-caption">{caption}</span> : null}
    </div>
  );
}

export default function ChochPage() {
  const [state, setState] = useState<ChochState | null>(null);
  const [trades, setTrades] = useState<ChochTrade[]>([]);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const [s, t] = await Promise.all([getChochState(), getChochTrades()]);
      setState(s);
      setTrades(t.trades);
      setError(s.error ?? null);
      getChochCandles().then((c) => setCandles(c.candles)).catch(() => undefined);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load.");
    }
  }

  useEffect(() => {
    load();
    const id = window.setInterval(() => {
      if (isMarketHoursNow()) load();
    }, 20000);
    return () => window.clearInterval(id);
  }, []);

  const config = state?.config;
  const st = state?.structure;
  const open = state?.open ?? [];
  const today = state?.today ?? [];
  const closed = trades.filter((t) => t.status === "CLOSED");
  const todayNet = today.reduce((s, t) => s + t.netPnl, 0);
  const totalNet = closed.reduce((s, t) => s + t.netPnl, 0);
  const trend = st?.trend === 1 ? "Uptrend" : st?.trend === -1 ? "Downtrend" : "Not set yet";

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Crosshair size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            1-Min CHoCH
          </h1>
          <p>
            Mukesh Jha&apos;s 1-minute NIFTY reversal: after a break of structure, a candle <strong>closing</strong> beyond the Change-of-Character level
            (the last swing before the break) opens a trade the other way. Run with the backtest&apos;s best settings -- only swings of{" "}
            {config?.swing ?? 65}+ points count, stop {config?.stop ?? 10} / target {config?.target ?? 60} points, at most {config?.maxTrades ?? 2} trades a
            day, entries {config?.start ?? "09:45"}–{config?.lastEntry ?? "15:00"}, flat {config?.flat ?? "15:15"}. Paper, in NIFTY futures points.
          </p>
        </div>
        <div className="toolbar" style={{ alignItems: "center" }}>
          <span className="status-live on">PAPER</span>
          <span className={`status-live ${config?.enabled ? "on" : ""}`}>{config?.enabled ? "Auto entry on" : "Auto entry paused"}</span>
          <button type="button" className="button secondary" onClick={load}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <Metric label="NIFTY (last 1-min close)" value={num(state?.lastBar?.close)} caption={state?.lastBar ? clock(state.lastBar.time) : state?.marketOpen ? "" : "market closed"} />
        <Metric label="Structure" value={trend} caption={st?.zigzag ? `swinging ${st.zigzag}` : ""} color={st?.trend === 1 ? "var(--green)" : st?.trend === -1 ? "var(--red)" : undefined} />
        <Metric
          label="CHoCH level"
          value={num(st?.choch)}
          caption={st?.choch ? (st.trend === -1 ? "close above → LONG" : st.trend === 1 ? "close below → SHORT" : "") : "needs a break of structure first"}
        />
        <Metric label="Last swing high / low" value={`${num(st?.swingHigh, 0)} / ${num(st?.swingLow, 0)}`} caption={`swings of ${config?.swing ?? 65}+ pts`} />
        <Metric label="Today" value={inr(todayNet)} caption={`${today.length} of ${config?.maxTrades ?? 2} trades`} color={tone(todayNet)} />
        <Metric label="All closed (net)" value={inr(totalNet)} caption={`${closed.length} trades · ${config?.lots ?? 1} lot × ${config?.lotSize ?? 65}`} color={tone(totalNet)} />
      </div>

      <CollapsibleSection id="choch-chart" title="NIFTY 1-min today" aside={<span className="pcr-oi-caption">CHoCH (amber) · swing high / low (grey) · open trade entry / stop / target</span>}>
        {candles.length ? <ChochChart candles={candles} state={state} trades={today} /> : <p className="pcr-oi-caption">No candles yet today.</p>}
      </CollapsibleSection>

      <CollapsibleSection id="choch-open" title={`Open position (${open.length})`}>
        {open.length ? (
          open.map((t) => (
            <div key={t.id} className="gb-status-row" style={{ flexWrap: "wrap", gap: 14 }}>
              <strong style={{ color: sideColor(t.side) }}>{sideText(t.side)}</strong>
              <span>entry {num(t.entry)} at {clock(t.entryTime)}</span>
              <span>stop {num(t.stop)}</span>
              <span>target {num(t.target)}</span>
              <span>NIFTY {num(t.lastPrice)}</span>
              <span>
                {t.points >= 0 ? "+" : ""}
                {num(t.points, 1)} pts · <strong style={{ color: tone(t.netPnl) }}>{inr(t.netPnl)}</strong> net
              </span>
            </div>
          ))
        ) : (
          <p className="pcr-oi-caption" style={{ margin: 0 }}>
            No open position. The next one opens when a 1-min candle closes beyond the CHoCH level between {config?.start ?? "09:45"} and{" "}
            {config?.lastEntry ?? "15:00"}.
          </p>
        )}
      </CollapsibleSection>

      <CollapsibleSection id="choch-pnl" title="Daily P&L">
        <DailyTotalsTable rows={groupDailyTotals(closed, (t) => t.exitTime, (t) => t.grossPnl, (t) => t.netPnl)} cumulative />
      </CollapsibleSection>

      <CollapsibleSection id="choch-trades" title={`All trades (${trades.length})`} defaultOpen={false}>
        <TradesTable trades={trades} />
      </CollapsibleSection>

      <CollapsibleSection id="choch-backtest" title="Backtest" defaultOpen={false}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Settings ({state?.backtest.period})</th>
                <th>Result (futures, after costs)</th>
                <th>Win rate</th>
              </tr>
            </thead>
            <tbody>
              {(state?.backtest.rows ?? []).map((r) => (
                <tr key={r.label}>
                  <td>{r.label}</td>
                  <td>{r.result}</td>
                  <td>{r.win}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="pcr-oi-caption">{state?.backtest.notes} Opposite-direction entries at the same moments lose, so the setup does call direction.</p>
      </CollapsibleSection>

      {config ? <Settings config={config} onSaved={load} /> : null}
    </section>
  );
}

function TradesTable({ trades }: { trades: ChochTrade[] }) {
  if (!trades.length) return <div className="empty-state">No trades yet.</div>;
  const cum = cumulativeNet(trades, (t) => t.id, (t) => t.exitTime, (t) => t.netPnl, (t) => t.status === "CLOSED");
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Day</th>
            <th>Side</th>
            <th>Entry</th>
            <th>Stop / target</th>
            <th>Exit</th>
            <th>Reason</th>
            <th>Points</th>
            <th>Gross</th>
            <th>Charges</th>
            <th>Net</th>
            <th>Cumulative net</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr key={t.id}>
              <td>{t.id}</td>
              <td>{t.day}</td>
              <td style={{ color: sideColor(t.side), fontWeight: 600 }}>{sideText(t.side)}</td>
              <td>
                {num(t.entry)} <span className="pcr-oi-caption">{clock(t.entryTime)}</span>
              </td>
              <td>
                {num(t.stop)} / {num(t.target)}
              </td>
              <td>
                {t.exit !== null ? num(t.exit) : "open"} <span className="pcr-oi-caption">{t.exitTime ? clock(t.exitTime) : ""}</span>
              </td>
              <td>{t.exitReason ?? "—"}</td>
              <td style={{ color: tone(t.points) }}>{num(t.points, 1)}</td>
              <td style={{ color: tone(t.grossPnl) }}>{inr(t.grossPnl)}</td>
              <td>{inr(t.charges)}</td>
              <td style={{ color: tone(t.netPnl), fontWeight: 600 }}>{inr(t.netPnl)}</td>
              <td style={{ color: tone(cum.get(t.id)) }}>{cum.has(t.id) ? inr(cum.get(t.id)) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChochChart({ candles, state, trades }: { candles: Candle[]; state: ChochState | null; trades: ChochTrade[] }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const tick = (t: Time) => (typeof t === "number" ? clock(t) : String(t));
    const chart = createChart(ref.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#17212b" },
      grid: { vertLines: { color: "#eef1f0" }, horzLines: { color: "#eef1f0" } },
      width: ref.current.clientWidth,
      height: 320,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: tick },
      localization: { timeFormatter: tick },
    });
    seriesRef.current = chart.addSeries(CandlestickSeries, { upColor: "#1b7a4b", downColor: "#b23c35", borderVisible: false, wickUpColor: "#1b7a4b", wickDownColor: "#b23c35" });
    chartRef.current = chart;
    const resize = () => ref.current && chart.applyOptions({ width: ref.current.clientWidth });
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.remove();
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    series.setData(candles.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })));
    for (const line of series.priceLines()) series.removePriceLine(line);
    const st = state?.structure;
    const add = (price: number | null | undefined, color: string, title: string, style = LineStyle.Dashed) => {
      if (price) series.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title });
    };
    add(st?.choch, "#c58a00", "CHoCH", LineStyle.Solid);
    add(st?.swingHigh, "#8a949a", "swing H");
    add(st?.swingLow, "#8a949a", "swing L");
    for (const t of trades.filter((x) => x.status === "OPEN")) {
      add(t.entry, "#0f6b78", "entry", LineStyle.Solid);
      add(t.stop, "#b23c35", "stop");
      add(t.target, "#1b7a4b", "target");
    }
    const markers = trades.flatMap((t) => [
      { time: t.entryTime as UTCTimestamp, position: t.side === 1 ? ("belowBar" as const) : ("aboveBar" as const), color: t.side === 1 ? "#1b7a4b" : "#b23c35",
        shape: t.side === 1 ? ("arrowUp" as const) : ("arrowDown" as const), text: `${t.side === 1 ? "L" : "S"} ${num(t.entry, 0)}` },
      ...(t.exitTime ? [{ time: t.exitTime as UTCTimestamp, position: "inBar" as const, color: t.netPnl >= 0 ? "#1b7a4b" : "#b23c35", shape: "circle" as const,
        text: `${t.exitReason} ${t.points >= 0 ? "+" : ""}${num(t.points, 0)}` }] : []),
    ]).sort((a, b) => a.time - b.time);
    createSeriesMarkers(series, markers);
  }, [candles, state, trades]);

  return <div ref={ref} style={{ width: "100%" }} />;
}

function Settings({ config, onSaved }: { config: ChochConfig; onSaved: () => void }) {
  const fields: { key: keyof ChochConfig; label: string; hint: string }[] = [
    { key: "swing", label: "Min swing (pts)", hint: "65 (backtest band 55–70)" },
    { key: "stop", label: "Stop (pts)", hint: "10" },
    { key: "target", label: "Target (pts)", hint: "60" },
    { key: "maxTrades", label: "Max trades / day", hint: "2" },
    { key: "start", label: "Entries from", hint: "09:45" },
    { key: "lastEntry", label: "Entries until", hint: "15:00" },
    { key: "flat", label: "Flat at", hint: "15:15" },
    { key: "lots", label: "Lots (65 each)", hint: "1" },
    { key: "costPoints", label: "Cost per trade (pts)", hint: "1.5" },
  ];
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => setDraft(Object.fromEntries(fields.map((f) => [f.key, String(config[f.key])]))), [config]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save(extra?: Partial<ChochConfig>) {
    setErr(null);
    try {
      const textKeys = new Set(["start", "lastEntry", "flat"]);
      await updateChochConfig(extra ?? Object.fromEntries(fields.map((f) => [f.key, textKeys.has(f.key) ? draft[f.key] : Number(draft[f.key])])));
      onSaved();
    } catch (exc) {
      setErr(exc instanceof Error ? exc.message : "Save failed.");
    }
  }

  return (
    <CollapsibleSection id="choch-settings" title="Settings" defaultOpen={false}>
      {err ? <div className="alert error">{err}</div> : null}
      <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13, marginBottom: 10 }}>
        <input type="checkbox" checked={config.enabled} onChange={(e) => save({ enabled: e.target.checked })} />
        Automatic entries (paper)
      </label>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))", gap: 12 }}>
        {fields.map((f) => (
          <label key={f.key} style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12 }}>
            <span style={{ color: "var(--muted)", fontWeight: 600 }}>{f.label}</span>
            <input value={draft[f.key] ?? ""} onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))} style={{ width: 110, fontSize: 13, padding: "3px 6px" }} />
            <span className="pcr-oi-caption">{f.hint}</span>
          </label>
        ))}
      </div>
      <div style={{ marginTop: 12, display: "flex", gap: 10, alignItems: "center" }}>
        <button type="button" className="button" onClick={() => save()}>
          <Save size={14} /> Save settings
        </button>
        <span className="pcr-oi-caption">Changes apply from the next session; today keeps the settings it started with.</span>
      </div>
    </CollapsibleSection>
  );
}
