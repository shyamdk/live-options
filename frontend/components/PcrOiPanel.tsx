"use client";

import {
  ColorType,
  createChart,
  IChartApi,
  ISeriesApi,
  LineSeries,
  LineStyle,
  MouseEventParams,
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
            <h3>Put-Call Ratio</h3>
            <Legend items={[{ label: "NIFTY PCR", color: NIFTY_COLOR }, { label: "SENSEX PCR", color: SENSEX_COLOR }]} />
            <PcrChart nifty={data.NIFTY} sensex={data.SENSEX} />
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

function PcrChart({ nifty, sensex }: { nifty: PcrOiSnapshot[]; sensex: PcrOiSnapshot[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const niftyRef = useRef<ISeriesApi<"Line"> | null>(null);
  const sensexRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: containerRef.current.clientWidth,
      height: 220,
      leftPriceScale: { visible: true, borderColor: NIFTY_COLOR },
      rightPriceScale: { visible: true, borderColor: SENSEX_COLOR },
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (time: Time) => formatIstTime(time) },
      localization: { timeFormatter: (time: Time) => formatIstTime(time) },
    });
    niftyRef.current = chart.addSeries(LineSeries, { color: NIFTY_COLOR, lineWidth: 2, priceScaleId: "left", title: "NIFTY PCR" });
    sensexRef.current = chart.addSeries(LineSeries, { color: SENSEX_COLOR, lineWidth: 2, priceScaleId: "right", title: "SENSEX PCR" });
    chartRef.current = chart;

    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      niftyRef.current = null;
      sensexRef.current = null;
    };
  }, []);

  useEffect(() => {
    niftyRef.current?.setData(toLineData(nifty, (p) => p.pcr));
  }, [nifty]);

  useEffect(() => {
    sensexRef.current?.setData(toLineData(sensex, (p) => p.pcr));
  }, [sensex]);

  return <div ref={containerRef} />;
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
    const ce = chart.addSeries(LineSeries, { color: CE_COLOR, lineWidth: 2, title: "CE roc" });
    const pe = chart.addSeries(LineSeries, { color: PE_COLOR, lineWidth: 2, title: "PE roc" });
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
      ceUpperRef.current = null;
      ceLowerRef.current = null;
      peUpperRef.current = null;
      peLowerRef.current = null;
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

function toLineData(points: PcrOiSnapshot[], pick: (p: PcrOiSnapshot) => number | null) {
  return points
    .filter((p) => pick(p) !== null && pick(p) !== undefined)
    .map((p) => ({ time: p.time as UTCTimestamp, value: pick(p) as number }));
}

function formatIstTime(time: Time): string {
  const totalSeconds = typeof time === "number" ? time : 0;
  const date = new Date(totalSeconds * 1000);
  return date.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });
}
