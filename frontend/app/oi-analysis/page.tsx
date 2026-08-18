"use client";

import { BarChart3 } from "lucide-react";
import { useEffect, useState } from "react";

import {
  ChartHandle,
  CE_COLOR,
  IvChart,
  Legend,
  linkCrosshairs,
  NIFTY_COLOR,
  OiChangeChart,
  PcrChart,
  PE_COLOR,
  SENSEX_COLOR,
} from "@/components/PcrOiPanel";
import { getPcrOiSessionDates, getPcrOiSnapshots } from "@/lib/api";
import type { PcrOiSnapshot, PcrOiPayload } from "@/types/live";

const DEFAULT_REFRESH_MS = 120000;
// The backend itself only polls the option chain every 3 minutes
// (pcr_oi_poll_interval_seconds) -- refreshing faster just re-fetches the
// same cached snapshot sooner, which is still useful (less time to first
// paint of a new poll) but won't surface data any fresher than that.
const REFRESH_OPTIONS: { value: number; label: string }[] = [
  { value: 30000, label: "30s" },
  { value: 60000, label: "1m" },
  { value: 120000, label: "2m" },
  { value: 180000, label: "3m" },
  { value: 300000, label: "5m" },
];
const VIX_COLOR = "#7a3fa0";
type Underlying = "NIFTY" | "SENSEX";

export default function OiAnalysisPage() {
  const [underlying, setUnderlying] = useState<Underlying>("NIFTY");
  const [data, setData] = useState<PcrOiPayload>({ NIFTY: [], SENSEX: [] });
  const [error, setError] = useState<string | null>(null);
  const [sessionDates, setSessionDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [refreshMs, setRefreshMs] = useState(DEFAULT_REFRESH_MS);
  const [pcrHandle, setPcrHandle] = useState<ChartHandle | null>(null);
  const [vixHandle, setVixHandle] = useState<ChartHandle | null>(null);
  const [ivHandle, setIvHandle] = useState<ChartHandle | null>(null);
  const [oiHandle, setOiHandle] = useState<ChartHandle | null>(null);

  useEffect(() => {
    if (sessionDates.length) return;
    let active = true;
    getPcrOiSessionDates()
      .then((dates) => {
        if (active) setSessionDates(dates);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [sessionDates.length]);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const payload = await getPcrOiSnapshots(selectedDate ?? undefined);
        if (active) {
          setData(payload);
          setError(null);
        }
      } catch (exc) {
        if (active) setError(exc instanceof Error ? exc.message : "Failed to load PCR/OI data.");
      }
    }
    load();
    if (selectedDate !== null) {
      return () => {
        active = false;
      };
    }
    const timer = window.setInterval(load, refreshMs);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [selectedDate, refreshMs]);

  useEffect(() => {
    const handles = [pcrHandle, vixHandle, ivHandle, oiHandle].filter((h): h is ChartHandle => h !== null);
    if (handles.length < 2) return;
    return linkCrosshairs(handles);
  }, [pcrHandle, vixHandle, ivHandle, oiHandle]);

  const points = data[underlying];
  const color = underlying === "NIFTY" ? NIFTY_COLOR : SENSEX_COLOR;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <BarChart3 size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            OI Analysis
          </h1>
          <p>Full-width PCR, India VIX, ATM IV and Change in OI, one underlying at a time, for reading fine intraday moves precisely.</p>
        </div>
        <div className="toolbar">
          <label className="subtext" htmlFor="oi-analysis-underlying-select">
            Underlying
          </label>
          <select
            id="oi-analysis-underlying-select"
            className="pcr-oi-session-select"
            value={underlying}
            onChange={(event) => {
              setUnderlying(event.target.value as Underlying);
              setPcrHandle(null);
              setVixHandle(null);
              setIvHandle(null);
              setOiHandle(null);
            }}
          >
            <option value="NIFTY">NIFTY</option>
            <option value="SENSEX">SENSEX</option>
          </select>
          <label className="subtext" htmlFor="oi-analysis-session-select">
            Session
          </label>
          <select
            id="oi-analysis-session-select"
            className="pcr-oi-session-select"
            value={selectedDate ?? ""}
            onChange={(event) => setSelectedDate(event.target.value || null)}
          >
            <option value="">Today (live)</option>
            {sessionDates.map((date) => (
              <option key={date} value={date}>
                {date}
              </option>
            ))}
          </select>
          <label className="subtext" htmlFor="oi-analysis-refresh-select">
            Refresh
          </label>
          <select
            id="oi-analysis-refresh-select"
            className="pcr-oi-session-select"
            value={refreshMs}
            disabled={selectedDate !== null}
            onChange={(event) => setRefreshMs(Number(event.target.value))}
          >
            {REFRESH_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          {selectedDate ? (
            <span className="pcr-oi-caption" style={{ margin: 0 }}>
              Viewing a past session — not live, no auto-refresh.
            </span>
          ) : null}
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}

      <div className="pcr-oi-section">
        <div className="oi-analysis-section-head">
          <h3>Put-Call Ratio — {underlying}</h3>
          <DeltaChip label="PCR" points={points} accessor={(p) => p.pcr} format={(v) => v.toFixed(3)} />
        </div>
        <PcrChart title={underlying} color={color} points={points} onReady={setPcrHandle} height={380} />
      </div>

      <div className="pcr-oi-section">
        <div className="oi-analysis-section-head">
          <h3>India VIX</h3>
          <DeltaChip label="VIX" points={points} accessor={(p) => p.indiaVix} format={(v) => v.toFixed(2)} />
        </div>
        <p className="pcr-oi-caption">Market-wide fear gauge — same series regardless of underlying selected above.</p>
        <PcrChart
          title="India VIX"
          color={VIX_COLOR}
          points={points}
          onReady={setVixHandle}
          height={300}
          accessor={(p) => p.indiaVix}
          seriesLabel="India VIX"
        />
      </div>

      <div className="pcr-oi-section">
        <div className="oi-analysis-section-head">
          <h3>ATM IV — {underlying}</h3>
          <div className="oi-analysis-chip-row">
            <DeltaChip label="CE IV" points={points} accessor={(p) => p.ceIv} format={(v) => `${v.toFixed(2)}%`} />
            <DeltaChip label="PE IV" points={points} accessor={(p) => p.peIv} format={(v) => `${v.toFixed(2)}%`} />
          </div>
        </div>
        <p className="pcr-oi-caption">
          Rising IV alongside a directional move means that move is being priced as real (more demand for that
          side's premium), not just noise.
        </p>
        <Legend items={[{ label: "CE IV", color: CE_COLOR }, { label: "PE IV", color: PE_COLOR }]} />
        <IvChart title={underlying} points={points} onReady={setIvHandle} height={380} />
      </div>

      <div className="pcr-oi-section">
        <div className="oi-analysis-section-head">
          <h3>Change in OI — {underlying}</h3>
          <div className="oi-analysis-chip-row">
            <DeltaChip label="CE" points={points} accessor={(p) => p.ceOiChange} format={formatLakhsShort} />
            <DeltaChip label="PE" points={points} accessor={(p) => p.peOiChange} format={formatLakhsShort} />
          </div>
        </div>
        <p className="pcr-oi-caption">Y-axis in lakhs (1 L = 100,000 contracts) for legible fine-grained moves.</p>
        <Legend items={[{ label: "CE chg OI", color: CE_COLOR }, { label: "PE chg OI", color: PE_COLOR }]} />
        <OiChangeChart title={underlying} points={points} onReady={setOiHandle} height={380} />
      </div>
    </section>
  );
}

function formatLakhsShort(value: number): string {
  return `${(value / 100000).toFixed(2)} L`;
}

/** Scans back from the latest point to find the most recent non-null value
 * and the one before it, so an occasional missed poll doesn't blank the
 * badge out. */
function latestDelta(
  points: PcrOiSnapshot[],
  accessor: (p: PcrOiSnapshot) => number | null,
): { value: number | null; delta: number | null } {
  let value: number | null = null;
  let previous: number | null = null;
  for (let i = points.length - 1; i >= 0; i -= 1) {
    const raw = accessor(points[i]);
    if (raw === null || raw === undefined) continue;
    if (value === null) {
      value = raw;
      continue;
    }
    previous = raw;
    break;
  }
  const delta = value !== null && previous !== null ? value - previous : null;
  return { value, delta };
}

function DeltaChip({
  label,
  points,
  accessor,
  format,
}: {
  label: string;
  points: PcrOiSnapshot[];
  accessor: (p: PcrOiSnapshot) => number | null;
  format: (value: number) => string;
}) {
  const { value, delta } = latestDelta(points, accessor);
  if (value === null) {
    return (
      <span className="oi-analysis-delta-chip">
        <strong>{label}</strong> <span className="subtext">—</span>
      </span>
    );
  }
  const arrow = delta === null || delta === 0 ? "→" : delta > 0 ? "▲" : "▼";
  const cls = delta === null || delta === 0 ? "" : delta > 0 ? "positive" : "negative";
  return (
    <span className="oi-analysis-delta-chip">
      <strong>{label}</strong> {format(value)}
      {delta !== null ? (
        <span className={cls}>
          {" "}
          {arrow} {format(Math.abs(delta))} since last refresh
        </span>
      ) : null}
    </span>
  );
}
