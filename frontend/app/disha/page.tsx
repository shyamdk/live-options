"use client";

import { ColorType, createChart, createSeriesMarkers, IChartApi, IPriceLine, ISeriesApi, LineSeries, Time, UTCTimestamp } from "lightweight-charts";
import { Compass, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import CollapsibleSection from "@/components/CollapsibleSection";
import { getDishaState } from "@/lib/api";
import type { DishaSituation, DishaState, DishaStatement } from "@/types/disha";

const REFRESH_MS = 30_000;

function num(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function signed(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}
function tone(v: number | null | undefined): string | undefined {
  if (!v) return undefined;
  return v > 0 ? "var(--green)" : "var(--red)";
}
function clock(epoch: number | null | undefined): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });
}
function istTick(t: Time): string {
  return typeof t === "number" ? clock(t) : String(t);
}
const pct = (r: number) => `${Math.round(r * 100)}%`;

const GAP_LABEL: Record<string, string> = {
  gap_up_big: "big gap up", gap_up: "gap up", gap_flat: "flat open", gap_down: "gap down", gap_down_big: "big gap down",
};

export default function DishaPage() {
  const [state, setState] = useState<DishaState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setState(await getDishaState());
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load Disha.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(id);
  }, []);

  const rates = state?.baseRates;
  const gapKey = state?.matches.find((k) => k.startsWith("gap_"));

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Compass size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Disha - NM
          </h1>
          <p>
            NIFTY&apos;s morning in context: the gap, the 09:15–09:30 opening range and its breakout, the first 15 minutes, India VIX and
            option OI added since the open — each next to how often that situation played out before. These are historical frequencies,
            not predictions: in testing, nothing here predicted the next minutes or the morning well enough to pay for a debit spread.
          </p>
        </div>
        <div className="toolbar" style={{ alignItems: "center" }}>
          <span className="pcr-oi-caption" style={{ whiteSpace: "nowrap", margin: 0 }}>
            {state ? `Updated ${clock(state.asOf)} · every 30 s` : "Loading…"}
          </span>
          <button type="button" className="button secondary" onClick={load} disabled={loading} style={{ whiteSpace: "nowrap" }}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {state?.errors.length ? <div className="alert warning">Some data is missing: {state.errors.join(" · ")}</div> : null}

      <div className="metric-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 170px), 1fr))" }}>
        <Metric label="NIFTY" value={num(state?.last)} caption={`${signed(state?.fromOpenPts)} pts from the open (${num(state?.open)})`} color={tone(state?.fromOpenPts)} />
        <Metric
          label="Gap"
          value={state?.gapPts != null ? `${signed(state.gapPts)} pts` : "—"}
          caption={state?.gapBps != null ? `${signed(state.gapBps / 100, 2)}% · ${gapKey ? GAP_LABEL[gapKey] : ""} · prev close ${num(state.prevClose)}` : "previous close not loaded"}
          color={tone(state?.gapPts)}
        />
        <Metric
          label="Opening range 09:15–09:30"
          value={state?.openingRange ? `${num(state.openingRange.low, 0)} – ${num(state.openingRange.high, 0)}` : "forming…"}
          caption={
            state?.openingRange
              ? `${num(state.openingRange.widthPts, 0)} pts wide · ${state.openingRange.narrow === null ? "" : state.openingRange.narrow ? "narrow" : "normal-to-wide"}${state.openingRange.complete ? "" : " · still forming"}`
              : "set by the first 15 one-minute candles"
          }
        />
        <Metric
          label="Breakout (by 10:30)"
          value={state?.breakout ? `${state.breakout.side === "up" ? "Above" : "Below"} at ${clock(state.breakout.time)}` : state?.matches.includes("no_breakout") ? "None by 10:30" : "Not yet"}
          caption={state?.breakout ? `level ${num(state.breakout.level, 1)} · now ${signed(state.breakout.distancePts)} pts beyond it` : "first move beyond the opening range"}
          color={state?.breakout ? (state.breakout.side === "up" ? "var(--green)" : "var(--red)") : undefined}
        />
        <Metric
          label="First 15 minutes"
          value={state?.move930Bps != null ? `${signed(state.move930Bps / 100, 2)}%` : "—"}
          caption={state?.move930Bps != null ? (Math.abs(state.move930Bps) >= 20 ? "a strong start" : "a quiet start") : "09:15 open → 09:29 close"}
          color={tone(state?.move930Bps)}
        />
        <Metric
          label="India VIX"
          value={num(state?.vix.now)}
          caption={state?.vix.change != null ? `${signed(state.vix.change, 2)} vs previous close ${num(state.vix.prev)}` : "—"}
          color={state?.vix.change ? (state.vix.change > 0 ? "var(--red)" : "var(--green)") : undefined}
        />
        <Metric
          label="Option OI since the open"
          value={state?.oi ? `CE ${signed(state.oi.ceAdded, 1)}L · PE ${signed(state.oi.peAdded, 1)}L` : "—"}
          caption={state?.oi ? `PCR ${num(state.oi.pcrOpen)} → ${num(state.oi.pcrNow)} · since ${clock(state.oi.since)}` : "from the OI snapshots (every ~3 min)"}
        />
      </div>

      <CollapsibleSection id="disha-chart" title="NIFTY today" aside={<span className="pcr-oi-caption">1-min closes · previous close and opening range drawn as lines</span>}>
        <SpotChart state={state} />
      </CollapsibleSection>

      <CollapsibleSection id="disha-today" title={`Today's situations (${state?.matches.length ?? 0})`}>
        {!rates ? (
          <p className="pcr-oi-caption">Historical base rates are not available.</p>
        ) : state?.matches.length ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 360px), 1fr))", gap: 12 }}>
            {state.matches.filter((k) => rates.situations[k]).map((k) => (
              <SituationCard key={k} situation={rates.situations[k]} highlight />
            ))}
          </div>
        ) : (
          <p className="pcr-oi-caption">Nothing to match yet — the gap is known at 09:15, the opening range at 09:30.</p>
        )}
      </CollapsibleSection>

      <CollapsibleSection id="disha-all" title="All morning situations" defaultOpen={false}>
        {rates ? (
          <>
            <p className="pcr-oi-caption" style={{ margin: "0 0 8px" }}>
              {rates.days} trading days, {rates.from} to {rates.to}. A rate near 50% means the situation says little; check both years before
              leaning on one. Points are NIFTY points (average). {rates.note}
            </p>
            <AllSituations rates={rates.situations} matches={state?.matches ?? []} />
          </>
        ) : null}
      </CollapsibleSection>
    </section>
  );
}

function Metric({ label, value, caption, color }: { label: string; value: string; caption?: string; color?: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong style={{ color }}>{value}</strong>
      {caption ? <span>{caption}</span> : null}
    </div>
  );
}

function RateBar({ s }: { s: DishaStatement }) {
  const lean = s.rate - 0.5;
  const color = Math.abs(lean) < 0.04 ? "var(--muted)" : lean > 0 ? "var(--green)" : "var(--red)";
  return (
    <div style={{ display: "grid", gap: 3 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 13 }}>
        <span>{s.text}</span>
        <strong className="num" style={{ color, whiteSpace: "nowrap" }}>{pct(s.rate)}</strong>
      </div>
      <div style={{ position: "relative", height: 6, borderRadius: 3, background: "var(--panel-2)" }}>
        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${s.rate * 100}%`, borderRadius: 3, background: color, opacity: 0.75 }} />
        <div style={{ position: "absolute", left: "50%", top: -2, bottom: -2, width: 1, background: "var(--text)", opacity: 0.35 }} title="50%" />
      </div>
      <span className="pcr-oi-caption" style={{ margin: 0 }}>
        {s.n} days · avg {signed(s.avgPts)} pts (median {signed(s.medianPts)}) ·{" "}
        {Object.entries(s.byYear).map(([y, v]) => `${y}: ${pct(v.rate)} of ${v.n}`).join(" · ")}
      </span>
    </div>
  );
}

function SituationCard({ situation, highlight }: { situation: DishaSituation; highlight?: boolean }) {
  return (
    <div className="metric" style={{ gap: 10, borderColor: highlight ? "var(--blue)" : undefined }}>
      <span>{situation.label}</span>
      {situation.statements.map((s) => (
        <RateBar key={s.text} s={s} />
      ))}
    </div>
  );
}

function AllSituations({ rates, matches }: { rates: Record<string, DishaSituation>; matches: string[] }) {
  return (
    <div className="table-wrap" style={{ overflowX: "auto" }}>
      <table style={{ minWidth: 760 }}>
        <thead>
          <tr>
            <th>Situation</th>
            <th>What happened next</th>
            <th style={{ textAlign: "right" }}>Days</th>
            <th style={{ textAlign: "right" }}>Rate</th>
            <th style={{ textAlign: "right" }}>Avg pts</th>
            <th>By year</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(rates).flatMap(([key, sit]) =>
            sit.statements.map((s, i) => (
              <tr key={`${key}-${i}`} style={matches.includes(key) ? { background: "var(--blue-soft)" } : undefined}>
                <td>{i === 0 ? <strong>{sit.label}</strong> : null}{i === 0 && matches.includes(key) ? <span className="badge" style={{ marginLeft: 6 }}>today</span> : null}</td>
                <td>{s.text}</td>
                <td className="num" style={{ textAlign: "right" }}>{s.n}</td>
                <td className="num" style={{ textAlign: "right", color: Math.abs(s.rate - 0.5) < 0.04 ? undefined : s.rate > 0.5 ? "var(--green)" : "var(--red)" }}>{pct(s.rate)}</td>
                <td className="num" style={{ textAlign: "right" }}>{signed(s.avgPts)}</td>
                <td>{Object.entries(s.byYear).map(([y, v]) => `${y}: ${pct(v.rate)} (${v.n})`).join(" · ")}</td>
              </tr>
            )),
          )}
        </tbody>
      </table>
    </div>
  );
}

function SpotChart({ state }: { state: DishaState | null }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const linesRef = useRef<IPriceLine[]>([]);
  const markersRef = useRef<ReturnType<typeof createSeriesMarkers<Time>> | null>(null);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#17212b" },
      grid: { vertLines: { color: "#e8edeb" }, horzLines: { color: "#e8edeb" } },
      width: containerRef.current.clientWidth,
      height: 300,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (t: Time) => istTick(t) },
      localization: { timeFormatter: (t: Time) => istTick(t) },
    });
    const series = chart.addSeries(LineSeries, { color: "#0f6b78", lineWidth: 2, title: "NIFTY" });
    seriesRef.current = series;
    markersRef.current = createSeriesMarkers(series, []);
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
      markersRef.current = null;
      linesRef.current = [];
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !state) return;
    series.setData(state.spot.map((c) => ({ time: c.time as UTCTimestamp, value: c.close })));
    for (const l of linesRef.current) series.removePriceLine(l);
    const lines: IPriceLine[] = [];
    if (state.prevClose) lines.push(series.createPriceLine({ price: state.prevClose, color: "#7a8494", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "prev close" }));
    if (state.openingRange) {
      lines.push(series.createPriceLine({ price: state.openingRange.high, color: "#1b7a4b", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "OR high" }));
      lines.push(series.createPriceLine({ price: state.openingRange.low, color: "#b23c35", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "OR low" }));
    }
    linesRef.current = lines;
    const bars = state.spot.map((c) => c.time);
    const bo = state.breakout;
    const barTime = bo ? bars.filter((t) => t <= bo.time).pop() : undefined;
    markersRef.current?.setMarkers(
      bo && barTime
        ? [{ time: barTime as UTCTimestamp, position: bo.side === "up" ? "belowBar" : "aboveBar", shape: bo.side === "up" ? "arrowUp" : "arrowDown",
             color: bo.side === "up" ? "#1b7a4b" : "#b23c35", text: `Breakout ${bo.side === "up" ? "above" : "below"} (${bo.level.toFixed(1)})` }]
        : [],
    );
    chartRef.current?.timeScale().fitContent();
  }, [state]);

  return <div ref={containerRef} style={{ width: "100%", height: 300 }} />;
}
