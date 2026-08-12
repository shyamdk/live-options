"use client";

import { ColorType, createChart, IChartApi, ISeriesApi, LineSeries, LineStyle, Time, UTCTimestamp } from "lightweight-charts";
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

export default function PcrOiPanel() {
  const [expanded, setExpanded] = useState(false);
  const [data, setData] = useState<PcrOiPayload>({ NIFTY: [], SENSEX: [] });
  const [error, setError] = useState<string | null>(null);

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
        <span className="subtext">NIFTY vs SENSEX, nearest expiry</span>
      </div>
      {expanded ? (
        <>
          {error ? <div className="alert error">{error}</div> : null}
          <div className="pcr-oi-section">
            <h3>Put-Call Ratio</h3>
            <PcrChart nifty={data.NIFTY} sensex={data.SENSEX} />
          </div>
          <div className="pcr-oi-section">
            <h3>Change in OI</h3>
            <div className="pcr-oi-split">
              <OiChangeChart title="NIFTY" points={data.NIFTY} />
              <OiChangeChart title="SENSEX" points={data.SENSEX} />
            </div>
          </div>
          <div className="pcr-oi-section">
            <h3>Rate of Change (OI/min) &amp; Confidence</h3>
            <div className="pcr-oi-split">
              <RocChart title="NIFTY" points={data.NIFTY} />
              <RocChart title="SENSEX" points={data.SENSEX} />
            </div>
          </div>
        </>
      ) : null}
    </section>
  );
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

function OiChangeChart({ title, points }: { title: string; points: PcrOiSnapshot[] }) {
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
    ceRef.current = chart.addSeries(LineSeries, { color: CE_COLOR, lineWidth: 2, title: "CE chg OI" });
    peRef.current = chart.addSeries(LineSeries, { color: PE_COLOR, lineWidth: 2, title: "PE chg OI" });
    chartRef.current = chart;

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

function RocChart({ title, points }: { title: string; points: PcrOiSnapshot[] }) {
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
    ceRef.current = chart.addSeries(LineSeries, { color: CE_COLOR, lineWidth: 2, title: "CE roc" });
    peRef.current = chart.addSeries(LineSeries, { color: PE_COLOR, lineWidth: 2, title: "PE roc" });
    chartRef.current = chart;

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
