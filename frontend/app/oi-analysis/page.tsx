"use client";

import { BarChart3, RefreshCcw, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

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
import { getPcrOiSessionDates, getPcrOiSnapshots, refreshPcrOiSnapshots } from "@/lib/api";
import { useChartLines, type StoredLine } from "@/lib/useChartLines";
import type { PcrOiSnapshot, PcrOiPayload } from "@/types/live";

const NOTIFY_STORAGE_KEY = "oi-analysis-notify-enabled";
type NotifyPermission = NotificationPermission | "unsupported";

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
const GRID_HEIGHT = 320;
const EXPANDED_HEIGHT = 520;
const LINES_HINT = "Click empty space to mark a level · drag a line to move it · click a line (or its × below) to remove it.";
type Underlying = "NIFTY" | "SENSEX";
type ExpandKind = "pcr" | "oi" | "vix" | "iv";

const EXPAND_TITLE: Record<ExpandKind, string> = {
  pcr: "Put-Call Ratio",
  oi: "Change in OI",
  vix: "India VIX",
  iv: "ATM IV",
};

const PCR_GUIDELINES = [
  "Rising PCR (more put OI than call OI building) is read here as bullish/CE-favoring; falling PCR as bearish/PE-favoring — this app follows the trend-following convention, not the contrarian-at-extremes one some traders use.",
  "Judge it against today's own average, not a fixed universal number like 1.0 — what's \"high\" shifts session to session.",
  "A sharp multi-poll move is a faster repositioning than a slow drift and generally deserves more weight.",
];

const OI_GUIDELINES = [
  "Rising CE OI + flat/falling CE premium = call writing = resistance forming = bearish lean. Rising CE OI + rising CE premium = call buying = bullish conviction.",
  "Rising PE OI + flat/falling PE premium = put writing = support forming = bullish lean. Rising PE OI + rising PE premium = put buying (fear) = bearish lean.",
  "Falling OI on a side means unwinding/covering — existing positions closing, that side's earlier influence fading.",
  "One line moving sharply while the other stays flat is more informative than either line read alone.",
];

const VIX_GUIDELINES = [
  "Rising VIX = rising fear/uncertainty = wider expected moves and richer premiums — favorable for premium sellers, riskier for premium buyers already in a position.",
  "Falling VIX = complacency; calmer trending or range-bound conditions where theta decay tends to dominate.",
  "A VIX spike arriving alongside a price move (not before it) confirms the move is being treated as urgent, not routine.",
  "VIX near session lows plus one-sided OI buildup often precedes a breakout — options are comparatively cheap for the eventual move.",
];

const IV_GUIDELINES = [
  "IV rising on one side before price has moved much is often a leading signal — the market is pricing in an expected move that direction.",
  "IV rising together with price moving that direction means the move is being chased/confirmed, not just noise.",
  "IV falling while price keeps moving suggests the move is decelerating, or theta/IV crush is setting in as the move gets \"used up\".",
  "A persistent gap between CE IV and PE IV is skew — the market paying more for one side's convexity, i.e. a directional lean already priced in.",
];

function keyFor(kind: ExpandKind, underlying: Underlying): string {
  return kind === "vix" ? "vix" : `${kind}:${underlying}`;
}

export default function OiAnalysisPage() {
  const [underlying, setUnderlying] = useState<Underlying>("NIFTY");
  const [data, setData] = useState<PcrOiPayload>({ NIFTY: [], SENSEX: [] });
  const [error, setError] = useState<string | null>(null);
  const [sessionDates, setSessionDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [refreshMs, setRefreshMs] = useState(DEFAULT_REFRESH_MS);
  const [expandedChart, setExpandedChart] = useState<ExpandKind | null>(null);
  const [expandedHandle, setExpandedHandle] = useState<ChartHandle | null>(null);
  const [pcrHandle, setPcrHandle] = useState<ChartHandle | null>(null);
  const [vixHandle, setVixHandle] = useState<ChartHandle | null>(null);
  const [ivHandle, setIvHandle] = useState<ChartHandle | null>(null);
  const [oiHandle, setOiHandle] = useState<ChartHandle | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [notifyEnabled, setNotifyEnabled] = useState(false);
  const [notifyPermission, setNotifyPermission] = useState<NotifyPermission>("default");
  const lastSideRef = useRef<Map<string, "above" | "below">>(new Map());

  const pcrLines = useChartLines(pcrHandle, keyFor("pcr", underlying));
  const oiLines = useChartLines(oiHandle, keyFor("oi", underlying));
  const vixLines = useChartLines(vixHandle, keyFor("vix", underlying));
  const ivLines = useChartLines(ivHandle, keyFor("iv", underlying));
  const expandedLines = useChartLines(expandedHandle, expandedChart ? keyFor(expandedChart, underlying) : "");
  const points = data[underlying];
  const color = underlying === "NIFTY" ? NIFTY_COLOR : SENSEX_COLOR;

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

  useEffect(() => {
    if (typeof window === "undefined") return;
    setNotifyEnabled(window.localStorage.getItem(NOTIFY_STORAGE_KEY) === "true");
    setNotifyPermission("Notification" in window ? Notification.permission : "unsupported");
  }, []);

  // Watches each chart's lines against its latest value; fires a browser
  // notification the moment the value crosses to the other side of a line.
  // Tracks "which side is it currently on" per line rather than diffing
  // consecutive data points, so it naturally fires once per crossing and
  // re-arms itself once the value crosses back -- no separate cooldown
  // bookkeeping needed.
  useEffect(() => {
    if (!notifyEnabled) return;
    if (typeof window === "undefined" || !("Notification" in window) || Notification.permission !== "granted") return;

    const watchers: { key: string; label: string; value: number | null; lines: StoredLine[]; format: (v: number) => string }[] = [
      { key: "pcr", label: `${underlying} PCR`, value: latestDelta(points, (p) => p.pcr).value, lines: pcrLines.lines, format: (v) => v.toFixed(3) },
      { key: "vix", label: "India VIX", value: latestDelta(points, (p) => p.indiaVix).value, lines: vixLines.lines, format: (v) => v.toFixed(2) },
      { key: "oiCe", label: `${underlying} CE chg OI`, value: latestDelta(points, (p) => p.ceOiChange).value, lines: oiLines.lines, format: formatLakhsShort },
      { key: "oiPe", label: `${underlying} PE chg OI`, value: latestDelta(points, (p) => p.peOiChange).value, lines: oiLines.lines, format: formatLakhsShort },
      { key: "ivCe", label: `${underlying} CE IV`, value: latestDelta(points, (p) => p.ceIv).value, lines: ivLines.lines, format: (v) => `${v.toFixed(2)}%` },
      { key: "ivPe", label: `${underlying} PE IV`, value: latestDelta(points, (p) => p.peIv).value, lines: ivLines.lines, format: (v) => `${v.toFixed(2)}%` },
    ];

    for (const watcher of watchers) {
      if (watcher.value === null) continue;
      for (const line of watcher.lines) {
        const side: "above" | "below" = watcher.value >= line.price ? "above" : "below";
        const trackKey = `${watcher.key}:${line.id}`;
        const prevSide = lastSideRef.current.get(trackKey);
        if (prevSide && prevSide !== side) {
          try {
            new Notification(`${watcher.label} crossed ${watcher.format(line.price)}`, {
              body: `Now ${watcher.format(watcher.value)} — was ${prevSide}, now ${side}.`,
              tag: trackKey,
            });
          } catch {
            // Some browsers restrict Notification construction in certain contexts -- fail quietly.
          }
        }
        lastSideRef.current.set(trackKey, side);
      }
    }
  }, [points, pcrLines.lines, vixLines.lines, oiLines.lines, ivLines.lines, notifyEnabled, underlying]);

  function toggleNotify() {
    if (typeof window === "undefined" || !("Notification" in window)) {
      setNotifyPermission("unsupported");
      return;
    }
    if (!notifyEnabled && Notification.permission === "default") {
      Notification.requestPermission().then((permission) => {
        setNotifyPermission(permission);
        if (permission === "granted") {
          setNotifyEnabled(true);
          window.localStorage.setItem(NOTIFY_STORAGE_KEY, "true");
        }
      });
      return;
    }
    const next = !notifyEnabled;
    setNotifyEnabled(next);
    window.localStorage.setItem(NOTIFY_STORAGE_KEY, String(next));
  }

  async function handleManualRefresh() {
    setRefreshing(true);
    try {
      const payload = await refreshPcrOiSnapshots(selectedDate ?? undefined);
      setData(payload);
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to refresh PCR/OI data.");
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(() => {
    if (!expandedChart) {
      setExpandedHandle(null);
      return;
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setExpandedChart(null);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [expandedChart]);

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <BarChart3 size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            OI Analysis
          </h1>
          <p>PCR, Change in OI, India VIX and ATM IV side by side, one underlying at a time, for reading fine intraday moves precisely.</p>
        </div>
        <div className="toolbar">
          <label className="subtext" htmlFor="oi-analysis-underlying-select">
            Underlying
          </label>
          <select
            id="oi-analysis-underlying-select"
            className="pcr-oi-session-select"
            value={underlying}
            onChange={(event) => setUnderlying(event.target.value as Underlying)}
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
          <button
            type="button"
            className="icon-button"
            title="Refresh now (backend re-polls immediately)"
            onClick={handleManualRefresh}
            disabled={refreshing || selectedDate !== null}
          >
            <RefreshCcw size={15} />
          </button>
          <label className="oi-analysis-notify-toggle subtext" htmlFor="oi-analysis-notify-checkbox">
            <input
              id="oi-analysis-notify-checkbox"
              type="checkbox"
              checked={notifyEnabled}
              onChange={toggleNotify}
              disabled={notifyPermission === "unsupported" || notifyPermission === "denied"}
            />
            Notify on line breach
            {notifyPermission === "denied" ? " (blocked in browser settings)" : null}
            {notifyPermission === "unsupported" ? " (not supported in this browser)" : null}
          </label>
          {selectedDate ? (
            <span className="pcr-oi-caption" style={{ margin: 0 }}>
              Viewing a past session — not live, no auto-refresh.
            </span>
          ) : null}
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}

      <div className="pcr-oi-section">
        <div className="pcr-oi-split">
          <div className="oi-analysis-chart-col">
            <div className="oi-analysis-section-head">
              <h3>Put-Call Ratio — {underlying}</h3>
              <DeltaChip label="PCR" points={points} accessor={(p) => p.pcr} format={(v) => v.toFixed(3)} />
            </div>
            <ul className="pcr-oi-rules">
              {PCR_GUIDELINES.map((rule) => (
                <li key={rule}>{rule}</li>
              ))}
            </ul>
            <PcrChart
              title={underlying}
              color={color}
              points={points}
              onReady={setPcrHandle}
              onExpand={() => setExpandedChart("pcr")}
              height={GRID_HEIGHT}
            />
            <LinesFooter lines={pcrLines.lines} onRemove={pcrLines.removeLine} format={(v) => v.toFixed(3)} />
          </div>

          <div className="oi-analysis-chart-col">
            <div className="oi-analysis-section-head">
              <h3>Change in OI — {underlying}</h3>
              <div className="oi-analysis-chip-row">
                <DeltaChip label="CE" points={points} accessor={(p) => p.ceOiChange} format={formatLakhsShort} />
                <DeltaChip label="PE" points={points} accessor={(p) => p.peOiChange} format={formatLakhsShort} />
              </div>
            </div>
            <p className="pcr-oi-caption" style={{ margin: 0 }}>
              Y-axis in lakhs (1 L = 100,000 contracts).
            </p>
            <Legend items={[{ label: "CE chg OI", color: CE_COLOR }, { label: "PE chg OI", color: PE_COLOR }]} />
            <ul className="pcr-oi-rules">
              {OI_GUIDELINES.map((rule) => (
                <li key={rule}>{rule}</li>
              ))}
            </ul>
            <OiChangeChart
              title={underlying}
              points={points}
              onReady={setOiHandle}
              onExpand={() => setExpandedChart("oi")}
              height={GRID_HEIGHT}
            />
            <LinesFooter lines={oiLines.lines} onRemove={oiLines.removeLine} format={formatLakhsShort} />
          </div>
        </div>
      </div>

      <div className="pcr-oi-section">
        <div className="pcr-oi-split">
          <div className="oi-analysis-chart-col">
            <div className="oi-analysis-section-head">
              <h3>India VIX</h3>
              <DeltaChip label="VIX" points={points} accessor={(p) => p.indiaVix} format={(v) => v.toFixed(2)} />
            </div>
            <p className="pcr-oi-caption" style={{ margin: 0 }}>
              Market-wide fear gauge — same series regardless of underlying selected above.
            </p>
            <ul className="pcr-oi-rules">
              {VIX_GUIDELINES.map((rule) => (
                <li key={rule}>{rule}</li>
              ))}
            </ul>
            <PcrChart
              title="India VIX"
              color={VIX_COLOR}
              points={points}
              onReady={setVixHandle}
              onExpand={() => setExpandedChart("vix")}
              height={GRID_HEIGHT}
              accessor={(p) => p.indiaVix}
              seriesLabel="India VIX"
            />
            <LinesFooter lines={vixLines.lines} onRemove={vixLines.removeLine} format={(v) => v.toFixed(2)} />
          </div>

          <div className="oi-analysis-chart-col">
            <div className="oi-analysis-section-head">
              <h3>ATM IV — {underlying}</h3>
              <div className="oi-analysis-chip-row">
                <DeltaChip label="CE IV" points={points} accessor={(p) => p.ceIv} format={(v) => `${v.toFixed(2)}%`} />
                <DeltaChip label="PE IV" points={points} accessor={(p) => p.peIv} format={(v) => `${v.toFixed(2)}%`} />
              </div>
            </div>
            <Legend items={[{ label: "CE IV", color: CE_COLOR }, { label: "PE IV", color: PE_COLOR }]} />
            <ul className="pcr-oi-rules">
              {IV_GUIDELINES.map((rule) => (
                <li key={rule}>{rule}</li>
              ))}
            </ul>
            <IvChart
              title={underlying}
              points={points}
              onReady={setIvHandle}
              onExpand={() => setExpandedChart("iv")}
              height={GRID_HEIGHT}
            />
            <LinesFooter lines={ivLines.lines} onRemove={ivLines.removeLine} format={(v) => `${v.toFixed(2)}%`} />
          </div>
        </div>
      </div>

      {expandedChart ? (
        <div className="pcr-oi-modal-backdrop" onClick={() => setExpandedChart(null)}>
          <div className="pcr-oi-modal" onClick={(event) => event.stopPropagation()}>
            <div className="pcr-oi-modal-head">
              <h3>
                {EXPAND_TITLE[expandedChart]} — {expandedChart === "vix" ? "Market-wide" : underlying}
              </h3>
              <button type="button" className="pcr-oi-expand-btn" title="Close" onClick={() => setExpandedChart(null)}>
                <X size={16} />
              </button>
            </div>
            {expandedChart === "pcr" ? (
              <PcrChart title={underlying} color={color} points={points} height={EXPANDED_HEIGHT} onReady={setExpandedHandle} />
            ) : null}
            {expandedChart === "oi" ? (
              <OiChangeChart title={underlying} points={points} height={EXPANDED_HEIGHT} onReady={setExpandedHandle} />
            ) : null}
            {expandedChart === "vix" ? (
              <PcrChart
                title="India VIX"
                color={VIX_COLOR}
                points={points}
                height={EXPANDED_HEIGHT}
                accessor={(p) => p.indiaVix}
                seriesLabel="India VIX"
                onReady={setExpandedHandle}
              />
            ) : null}
            {expandedChart === "iv" ? (
              <IvChart title={underlying} points={points} height={EXPANDED_HEIGHT} onReady={setExpandedHandle} />
            ) : null}
            <LinesFooter
              lines={expandedLines.lines}
              onRemove={expandedLines.removeLine}
              format={expandedChart === "oi" ? formatLakhsShort : expandedChart === "iv" ? (v) => `${v.toFixed(2)}%` : (v) => v.toFixed(3)}
            />
          </div>
        </div>
      ) : null}
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

// A move only earns "Rapid" once today has enough polls to know what
// "normal" even looks like for this series -- same spirit as the app's own
// z-score confidence badges elsewhere, simplified to one ratio since this
// only needs two buckets, not four.
const MIN_SAMPLES_FOR_PACE = 4;
const RAPID_THRESHOLD_MULTIPLIER = 1.5;
type MoveSpeed = "rapid" | "nominal" | null;

function computeMoveStats(
  points: PcrOiSnapshot[],
  accessor: (p: PcrOiSnapshot) => number | null,
): { value: number | null; delta: number | null; pctChange: number | null; speed: MoveSpeed } {
  const { value, delta } = latestDelta(points, accessor);
  const previous = value !== null && delta !== null ? value - delta : null;
  const pctChange = delta !== null && previous !== null && previous !== 0 ? (delta / Math.abs(previous)) * 100 : null;

  // Today's typical poll-to-poll pace for this series, so "rapid" means
  // "faster than today's own normal", not an arbitrary fixed percentage
  // that wouldn't mean the same thing for PCR (tiny moves) vs OI (huge
  // absolute numbers).
  const pctChanges: number[] = [];
  let prevVal: number | null = null;
  for (const point of points) {
    const raw = accessor(point);
    if (raw === null || raw === undefined) continue;
    if (prevVal !== null && prevVal !== 0) {
      pctChanges.push(Math.abs(((raw - prevVal) / Math.abs(prevVal)) * 100));
    }
    prevVal = raw;
  }

  let speed: MoveSpeed = null;
  if (pctChange !== null && pctChanges.length >= MIN_SAMPLES_FOR_PACE) {
    const mean = pctChanges.reduce((a, b) => a + b, 0) / pctChanges.length;
    speed = mean > 0 && Math.abs(pctChange) >= mean * RAPID_THRESHOLD_MULTIPLIER ? "rapid" : "nominal";
  }

  return { value, delta, pctChange, speed };
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
  const { value, delta, pctChange, speed } = computeMoveStats(points, accessor);
  if (value === null) {
    return (
      <span className="oi-analysis-delta-chip">
        <strong>{label}</strong> <span className="subtext">—</span>
      </span>
    );
  }
  const arrow = delta === null || delta === 0 ? "→" : delta > 0 ? "▲" : "▼";
  const cls = delta === null || delta === 0 ? "" : delta > 0 ? "positive" : "negative";
  const direction = delta === null || delta === 0 ? null : delta > 0 ? "Increase" : "Decrease";
  const pillClass = speed === "rapid" ? (delta! > 0 ? "rapid-up" : "rapid-down") : "nominal";
  return (
    <span className="oi-analysis-delta-chip">
      <strong>{label}</strong> {format(value)}
      {delta !== null ? (
        <span className={cls}>
          {" "}
          {arrow} {format(Math.abs(delta))}
          {pctChange !== null ? ` (${pctChange >= 0 ? "+" : ""}${pctChange.toFixed(2)}%)` : ""} since last refresh
        </span>
      ) : null}
      {speed && direction ? (
        <span className={`oi-analysis-speed-pill ${pillClass}`}>
          {speed === "rapid" ? "Rapid" : "Nominal"} {direction}
        </span>
      ) : null}
    </span>
  );
}

function LinesFooter({
  lines,
  onRemove,
  format,
}: {
  lines: StoredLine[];
  onRemove: (id: string) => void;
  format: (value: number) => string;
}) {
  return (
    <div className="oi-analysis-lines-footer">
      <span className="pcr-oi-caption" style={{ margin: 0 }}>
        {LINES_HINT}
      </span>
      {lines.length > 0 ? (
        <div className="oi-analysis-lines-list">
          {lines.map((line) => (
            <span key={line.id} className="oi-analysis-line-chip">
              {format(line.price)}
              <button type="button" title="Remove line" aria-label="Remove line" onClick={() => onRemove(line.id)}>
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
