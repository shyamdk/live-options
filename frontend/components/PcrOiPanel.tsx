"use client";

import {
  ColorType,
  createChart,
  createSeriesMarkers,
  IChartApi,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  LineSeries,
  LineStyle,
  MouseEventParams,
  SeriesMarker,
  Time,
  UTCTimestamp,
} from "lightweight-charts";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { getPcrOiSnapshots } from "@/lib/api";
import type { ConfidenceLevel, PcrOiPayload, PcrOiSnapshot } from "@/types/live";

const PANEL_REFRESH_MS = 120000;

const NIFTY_COLOR = "#2368b6";
const SENSEX_COLOR = "#a56513";
const CE_COLOR = "#168448";
const PE_COLOR = "#c93535";
const CE_MUTED = "#a9d4bb";
const PE_MUTED = "#e3aeae";
const BAND_COLOR = "#9aa4b2";

const CONFIDENCE_COLOR: Record<ConfidenceLevel, string> = {
  low: "#6f7785",
  medium: NIFTY_COLOR,
  high: SENSEX_COLOR,
  extreme: PE_COLOR,
};

const CONFIDENCE_LABEL: Record<ConfidenceLevel, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  extreme: "Extreme",
};

type ChartHandle = { chart: IChartApi; series: ISeriesApi<"Line"> };

export default function PcrOiPanel() {
  const [expanded, setExpanded] = useState(false);
  const [data, setData] = useState<PcrOiPayload>({ NIFTY: [], SENSEX: [] });
  const [error, setError] = useState<string | null>(null);

  const [niftyOi, setNiftyOi] = useState<ChartHandle | null>(null);
  const [niftyRoc, setNiftyRoc] = useState<ChartHandle | null>(null);
  const [sensexOi, setSensexOi] = useState<ChartHandle | null>(null);
  const [sensexRoc, setSensexRoc] = useState<ChartHandle | null>(null);

  useEffect(() => {
    if (!niftyOi || !niftyRoc) return;
    return linkCrosshairs(niftyOi, niftyRoc);
  }, [niftyOi, niftyRoc]);

  useEffect(() => {
    if (!sensexOi || !sensexRoc) return;
    return linkCrosshairs(sensexOi, sensexRoc);
  }, [sensexOi, sensexRoc]);

  useEffect(() => {
    if (!expanded) return;
    let active = true;
    async function load() {
      try {
        const payload = await getPcrOiSnapshots();
        if (active) {
          setData(payload);
          setError(null);
        }
      } catch (exc) {
        if (active) setError(exc instanceof Error ? exc.message : "Failed to load PCR/OI data.");
      }
    }
    load();
    const timer = window.setInterval(load, PANEL_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [expanded]);

  return (
    <section className="table-section">
      <div className="section-title pcr-oi-title" onClick={() => setExpanded((v) => !v)}>
        <h2 style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
          <button className="icon-button" type="button" title={expanded ? "Collapse" : "Expand"}>
            {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          </button>
          Market Internals — PCR &amp; Change in OI
        </h2>
        <span className="subtext">NIFTY vs SENSEX, nearest expiry · all times IST</span>
      </div>
      {expanded ? (
        <>
          {error ? <div className="alert error">{error}</div> : null}
          <div className="pcr-oi-section">
            <h3>Signal</h3>
            <p className="pcr-oi-caption">Your OI/PCR rule, mechanically applied — not a recommendation.</p>
            <div className="pcr-oi-split">
              <SignalCard title="NIFTY" points={data.NIFTY} />
              <SignalCard title="SENSEX" points={data.SENSEX} />
            </div>
          </div>
          <div className="pcr-oi-section">
            <h3>Timing Notes</h3>
            <TimingRules />
            <div className="pcr-oi-split">
              <SignalHistory title="NIFTY" points={data.NIFTY} />
              <SignalHistory title="SENSEX" points={data.SENSEX} />
            </div>
          </div>
          <div className="pcr-oi-section">
            <h3>Put-Call Ratio</h3>
            <div className="pcr-oi-split">
              <PcrChart title="NIFTY" color={NIFTY_COLOR} points={data.NIFTY} />
              <PcrChart title="SENSEX" color={SENSEX_COLOR} points={data.SENSEX} />
            </div>
          </div>
          <div className="pcr-oi-section">
            <h3>Change in OI</h3>
            <Legend items={[{ label: "CE chg OI", color: CE_COLOR }, { label: "PE chg OI", color: PE_COLOR }]} />
            <div className="pcr-oi-split">
              <OiChangeChart title="NIFTY" points={data.NIFTY} onReady={setNiftyOi} />
              <OiChangeChart title="SENSEX" points={data.SENSEX} onReady={setSensexOi} />
            </div>
          </div>
          <div className="pcr-oi-section">
            <h3>Rate of Change (OI/min) &amp; Confidence</h3>
            <Legend
              items={[
                { label: "CE roc", color: CE_COLOR },
                { label: "PE roc", color: PE_COLOR },
                { label: "±1σ band (today)", color: BAND_COLOR, dashed: true },
              ]}
            />
            <div className="pcr-oi-split">
              <RocChart title="NIFTY" points={data.NIFTY} onReady={setNiftyRoc} />
              <RocChart title="SENSEX" points={data.SENSEX} onReady={setSensexRoc} />
            </div>
          </div>
        </>
      ) : null}
    </section>
  );
}

function Legend({ items }: { items: { label: string; color: string; dashed?: boolean }[] }) {
  return (
    <div className="pcr-oi-legend">
      {items.map((item) => (
        <span className="pcr-oi-legend-item" key={item.label}>
          <span
            className="pcr-oi-legend-swatch"
            style={item.dashed ? { borderTop: `2px dashed ${item.color}` } : { background: item.color }}
          />
          {item.label}
        </span>
      ))}
    </div>
  );
}

/** Bidirectionally syncs the crosshair (vertical hover line) between two
 * charts sharing the same time axis, so hovering either the Change-in-OI or
 * Rate-of-Change chart for an underlying shows the same moment in both.
 * Guards against the infinite loop that would otherwise happen since
 * setCrosshairPosition() on the partner chart re-fires its own
 * subscribeCrosshairMove handler.
 */
function linkCrosshairs(a: ChartHandle, b: ChartHandle): () => void {
  let syncing = false;

  const forward = (source: ChartHandle, target: ChartHandle) => (param: MouseEventParams<Time>) => {
    if (syncing) return;
    syncing = true;
    if (param.time === undefined || !param.point) {
      target.chart.clearCrosshairPosition();
    } else {
      const point = param.seriesData.get(source.series);
      const price = point && "value" in point ? point.value : 0;
      target.chart.setCrosshairPosition(price, param.time, target.series);
    }
    syncing = false;
  };

  const onA = forward(a, b);
  const onB = forward(b, a);
  a.chart.subscribeCrosshairMove(onA);
  b.chart.subscribeCrosshairMove(onB);

  return () => {
    a.chart.unsubscribeCrosshairMove(onA);
    b.chart.unsubscribeCrosshairMove(onB);
  };
}

function PcrChart({ title, color, points }: { title: string; color: string; points: PcrOiSnapshot[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: containerRef.current.clientWidth,
      height: 200,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (time: Time) => formatIstTime(time) },
      localization: { timeFormatter: (time: Time) => formatIstTime(time) },
    });
    seriesRef.current = chart.addSeries(LineSeries, { color, lineWidth: 2, title: `${title} PCR` });
    chartRef.current = chart;

    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    seriesRef.current?.setData(toLineData(points, (p) => p.pcr));
  }, [points]);

  return (
    <div className="pcr-oi-split-item">
      <span className="subtext">{title}</span>
      <div ref={containerRef} />
    </div>
  );
}

function OiChangeChart({
  title,
  points,
  onReady,
}: {
  title: string;
  points: PcrOiSnapshot[];
  onReady?: (handle: ChartHandle) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const ceRef = useRef<ISeriesApi<"Line"> | null>(null);
  const peRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: containerRef.current.clientWidth,
      height: 220,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (time: Time) => formatIstTime(time) },
      localization: { timeFormatter: (time: Time) => formatIstTime(time) },
    });
    const ce = chart.addSeries(LineSeries, { color: CE_COLOR, lineWidth: 2, title: "CE chg OI" });
    const pe = chart.addSeries(LineSeries, { color: PE_COLOR, lineWidth: 2, title: "PE chg OI" });
    ceRef.current = ce;
    peRef.current = pe;
    chartRef.current = chart;
    onReady?.({ chart, series: ce });

    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      ceRef.current = null;
      peRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    ceRef.current?.setData(toLineData(points, (p) => p.ceOiChange));
    peRef.current?.setData(toLineData(points, (p) => p.peOiChange));
  }, [points]);

  return (
    <div className="pcr-oi-split-item">
      <span className="subtext">{title}</span>
      <div ref={containerRef} />
    </div>
  );
}

function RocChart({
  title,
  points,
  onReady,
}: {
  title: string;
  points: PcrOiSnapshot[];
  onReady?: (handle: ChartHandle) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const ceRef = useRef<ISeriesApi<"Line"> | null>(null);
  const peRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ceUpperRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ceLowerRef = useRef<ISeriesApi<"Line"> | null>(null);
  const peUpperRef = useRef<ISeriesApi<"Line"> | null>(null);
  const peLowerRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ceMarkersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const peMarkersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: containerRef.current.clientWidth,
      height: 180,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (time: Time) => formatIstTime(time) },
      localization: { timeFormatter: (time: Time) => formatIstTime(time) },
    });
    const bandOptions = { color: BAND_COLOR, lineWidth: 1 as const, lineStyle: LineStyle.Dashed, crosshairMarkerVisible: false };
    ceUpperRef.current = chart.addSeries(LineSeries, { ...bandOptions, title: "CE band" });
    ceLowerRef.current = chart.addSeries(LineSeries, bandOptions);
    peUpperRef.current = chart.addSeries(LineSeries, { ...bandOptions, title: "PE band" });
    peLowerRef.current = chart.addSeries(LineSeries, bandOptions);
    // Base lines muted -- normal noise shouldn't compete for attention;
    // the markers below are what should draw the eye.
    const ce = chart.addSeries(LineSeries, { color: CE_MUTED, lineWidth: 1, title: "CE roc" });
    const pe = chart.addSeries(LineSeries, { color: PE_MUTED, lineWidth: 1, title: "PE roc" });
    ceRef.current = ce;
    peRef.current = pe;
    ceMarkersRef.current = createSeriesMarkers(ce, []);
    peMarkersRef.current = createSeriesMarkers(pe, []);
    chartRef.current = chart;
    onReady?.({ chart, series: ce });

    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      ceMarkersRef.current?.detach();
      peMarkersRef.current?.detach();
      chart.remove();
      chartRef.current = null;
      ceRef.current = null;
      peRef.current = null;
      ceUpperRef.current = null;
      ceLowerRef.current = null;
      peUpperRef.current = null;
      peLowerRef.current = null;
      ceMarkersRef.current = null;
      peMarkersRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    ceRef.current?.setData(toLineData(points, (p) => p.ceRoc));
    peRef.current?.setData(toLineData(points, (p) => p.peRoc));
    ceUpperRef.current?.setData(toLineData(points, (p) => p.ceRocBandUpper));
    ceLowerRef.current?.setData(toLineData(points, (p) => p.ceRocBandLower));
    peUpperRef.current?.setData(toLineData(points, (p) => p.peRocBandUpper));
    peLowerRef.current?.setData(toLineData(points, (p) => p.peRocBandLower));
    ceMarkersRef.current?.setMarkers(buildConfidenceMarkers(points, "ce"));
    peMarkersRef.current?.setMarkers(buildConfidenceMarkers(points, "pe"));
  }, [points]);

  const latest = points.length ? points[points.length - 1] : null;

  return (
    <div className="pcr-oi-split-item">
      <div className="pcr-oi-badge-row">
        <span className="subtext">{title}</span>
        <ConfidenceBadge label="CE" level={latest?.ceConfidence ?? null} />
        <ConfidenceBadge label="PE" level={latest?.peConfidence ?? null} />
      </div>
      <div ref={containerRef} />
    </div>
  );
}

function ConfidenceBadge({ label, level }: { label: string; level: ConfidenceLevel | null }) {
  if (!level) {
    return (
      <span className="pcr-oi-confidence" style={{ color: "#9aa4b2", borderColor: "#dde4ec" }}>
        {label}: warming up
      </span>
    );
  }
  const color = CONFIDENCE_COLOR[level];
  return (
    <span className="pcr-oi-confidence" style={{ color, borderColor: color }}>
      {label}: {CONFIDENCE_LABEL[level]}
    </span>
  );
}

const SIGNAL_COLOR: Record<"buyCe" | "buyPe" | "neutral", string> = {
  buyCe: CE_COLOR,
  buyPe: PE_COLOR,
  neutral: "#6f7785",
};

const SIGNAL_LABEL: Record<"buyCe" | "buyPe" | "neutral", string> = {
  buyCe: "Buy CE",
  buyPe: "Buy PE",
  neutral: "Neutral / mixed",
};

function signalReason(point: PcrOiSnapshot): string {
  const skewPart =
    point.oiSkew === null
      ? null
      : point.oiSkew > 0
        ? "PE OI building (writer-driven)"
        : point.oiSkew < 0
          ? "CE OI building (writer-driven)"
          : null;
  const pcrPart = point.pcrDelta === null ? null : point.pcrDelta > 0 ? "PCR rising" : point.pcrDelta < 0 ? "PCR falling" : null;
  const parts = [skewPart, pcrPart].filter((p): p is string => p !== null);
  return parts.length ? parts.join(" + ") : "Not enough data yet today";
}

function SignalCard({ title, points }: { title: string; points: PcrOiSnapshot[] }) {
  const latest = points.length ? points[points.length - 1] : null;
  const signal = latest?.signal ?? null;

  return (
    <div className="pcr-oi-split-item">
      <span className="subtext">{title}</span>
      <div className="pcr-oi-signal-card">
        <div className="pcr-oi-signal-headline">
          <span
            className="pcr-oi-signal-badge"
            style={signal ? { background: SIGNAL_COLOR[signal], color: "#fff" } : { background: "#dde4ec", color: "#6f7785" }}
          >
            {signal ? SIGNAL_LABEL[signal] : "Warming up"}
          </span>
          {latest?.signalConfidence ? <ConfidenceBadge label="Strength" level={latest.signalConfidence} /> : null}
          {latest?.deltaVegaAligned ? (
            <span className="pcr-oi-confidence" style={{ color: SIGNAL_COLOR.buyCe, borderColor: SIGNAL_COLOR.buyCe }}>
              Δ+Vega aligned ({latest.deltaVegaAligned})
            </span>
          ) : null}
        </div>
        <p className="pcr-oi-signal-reason">{latest ? signalReason(latest) : "No data yet."}</p>
        {latest?.atmStrike ? (
          <div className="pcr-oi-atm-row">
            <div className="pcr-oi-atm-item">
              <span className="subtext">ATM {latest.atmStrike.toFixed(0)} CE</span>
              <strong>
                {fmt(latest.cePremium)} <span className="pcr-oi-atm-iv">IV {fmt(latest.ceIv, 1)}%</span>
              </strong>
            </div>
            <div className="pcr-oi-atm-item">
              <span className="subtext">ATM {latest.atmStrike.toFixed(0)} PE</span>
              <strong>
                {fmt(latest.pePremium)} <span className="pcr-oi-atm-iv">IV {fmt(latest.peIv, 1)}%</span>
              </strong>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

const TIMING_RULES = [
  "Wait for the signal to sustain a poll or two before acting — a single spike can be noise, not a trend.",
  "Prefer entries when the Δ+Vega badge is showing — price and IV are both working in your favor at once.",
  '"Low" confidence is background noise; only Medium and above reflect a genuinely unusual pace.',
  "Avoid fresh entries in the first ~15 minutes after open — opening-range volatility produces false spikes.",
  "Avoid fresh entries in the last ~20–30 minutes before close — theta decay accelerates and exit liquidity thins.",
  "On expiry day, IV tends to compress into the close — buying premium late in an expiry session works against you twice over (theta + IV crush).",
];

function TimingRules() {
  return (
    <ul className="pcr-oi-rules">
      {TIMING_RULES.map((rule) => (
        <li key={rule}>{rule}</li>
      ))}
    </ul>
  );
}

/** Logs when the signal flips INTO a directional call (buyCe/buyPe), not
 * every poll that repeats the same state -- a steady trend would otherwise
 * repeat the same line dozens of times. This is "when did the read change"
 * rather than "what was the read at every poll", which is what the badges/
 * chart already show for the current moment.
 */
function SignalHistory({ title, points }: { title: string; points: PcrOiSnapshot[] }) {
  const transitions: PcrOiSnapshot[] = [];
  let lastSignal: string | null = null;
  for (const p of points) {
    if (p.signal && p.signal !== lastSignal) {
      if (p.signal !== "neutral") transitions.push(p);
      lastSignal = p.signal;
    }
  }
  const history = transitions.slice().reverse();

  return (
    <div className="pcr-oi-split-item">
      <span className="subtext">{title} — today</span>
      <div className="pcr-oi-history">
        {history.length ? (
          history.map((p) => {
            const signal = p.signal as "buyCe" | "buyPe";
            return (
              <div className="pcr-oi-history-row" key={p.time}>
                <span className="pcr-oi-history-time">{formatIstTime(p.time as UTCTimestamp)}</span>
                <span className="pcr-oi-history-signal" style={{ color: SIGNAL_COLOR[signal] }}>
                  {SIGNAL_LABEL[signal]}
                </span>
                {p.signalConfidence ? (
                  <span
                    className="pcr-oi-confidence"
                    style={{ color: CONFIDENCE_COLOR[p.signalConfidence], borderColor: CONFIDENCE_COLOR[p.signalConfidence] }}
                  >
                    {CONFIDENCE_LABEL[p.signalConfidence]}
                  </span>
                ) : null}
              </div>
            );
          })
        ) : (
          <p className="pcr-oi-signal-reason">No Buy CE/PE signal yet today.</p>
        )}
      </div>
    </div>
  );
}

function fmt(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

function toLineData(points: PcrOiSnapshot[], pick: (p: PcrOiSnapshot) => number | null) {
  return points
    .filter((p) => pick(p) !== null && pick(p) !== undefined)
    .map((p) => ({ time: p.time as UTCTimestamp, value: pick(p) as number }));
}

/** Only High/Extreme confidence points get a marker -- the muted base line
 * carries the normal noise, markers are where the eye should actually go.
 */
function buildConfidenceMarkers(points: PcrOiSnapshot[], side: "ce" | "pe"): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = [];
  for (const p of points) {
    const confidence = side === "ce" ? p.ceConfidence : p.peConfidence;
    const roc = side === "ce" ? p.ceRoc : p.peRoc;
    if (roc === null || (confidence !== "high" && confidence !== "extreme")) continue;
    markers.push({
      time: p.time as UTCTimestamp,
      position: roc >= 0 ? "aboveBar" : "belowBar",
      color: CONFIDENCE_COLOR[confidence],
      shape: "circle",
      text: CONFIDENCE_LABEL[confidence],
    });
  }
  return markers;
}

function formatIstTime(time: Time): string {
  const totalSeconds = typeof time === "number" ? time : 0;
  const date = new Date(totalSeconds * 1000);
  return date.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });
}
