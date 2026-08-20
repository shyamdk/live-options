"use client";

import { RadioTower, RefreshCcw } from "lucide-react";
import { useEffect, useState } from "react";

import { CE_COLOR, Legend, NIFTY_COLOR, OiChangeChart, PcrChart, PE_COLOR, IvChart } from "@/components/PcrOiPanel";
import {
  getOiUpgradedSignal,
  getPcrOiSessionDates,
  getPcrOiSnapshots,
  refreshOiUpgradedSignal,
} from "@/lib/api";
import type { OiUpgradedPoint, PcrOiPayload, TrendState } from "@/types/live";

const DEFAULT_REFRESH_MS = 120000;
const REFRESH_OPTIONS: { value: number; label: string }[] = [
  { value: 30000, label: "30s" },
  { value: 60000, label: "1m" },
  { value: 120000, label: "2m" },
  { value: 180000, label: "3m" },
  { value: 300000, label: "5m" },
];
const GRID_HEIGHT = 300;

const SIGNAL_LABEL: Record<string, string> = { buyCe: "BUY CE", buyPe: "BUY PE", noTrade: "NO TRADE" };
const STATE_LABEL: Record<string, string> = {
  bullish: "Bullish",
  bearish: "Bearish",
  neutral: "Neutral",
  mixed: "Mixed",
  unwinding: "Unwinding",
  buildingBoth: "Building both sides",
  supportive: "Supportive",
  risky: "Risky",
};

function deriveRegime(pcrState: TrendState, oiState: string, priceState: TrendState): string {
  const bullishCount = [pcrState === "bullish", oiState === "bullish", priceState === "bullish"].filter(Boolean).length;
  const bearishCount = [pcrState === "bearish", oiState === "bearish", priceState === "bearish"].filter(Boolean).length;
  if (bullishCount >= 2 && bearishCount === 0) return "Trending Bullish";
  if (bearishCount >= 2 && bullishCount === 0) return "Trending Bearish";
  if (bullishCount > 0 && bearishCount > 0) return "Transition";
  return "Range";
}

export default function OiUpgradedPage() {
  const [signalData, setSignalData] = useState<OiUpgradedPoint[]>([]);
  const [chartData, setChartData] = useState<PcrOiPayload>({ NIFTY: [], SENSEX: [] });
  const [error, setError] = useState<string | null>(null);
  const [sessionDates, setSessionDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [refreshMs, setRefreshMs] = useState(DEFAULT_REFRESH_MS);
  const [refreshing, setRefreshing] = useState(false);

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
        const [signalPayload, chartPayload] = await Promise.all([
          getOiUpgradedSignal(selectedDate ?? undefined),
          getPcrOiSnapshots(selectedDate ?? undefined),
        ]);
        if (active) {
          setSignalData(signalPayload.NIFTY);
          setChartData(chartPayload);
          setError(null);
        }
      } catch (exc) {
        if (active) setError(exc instanceof Error ? exc.message : "Failed to load the upgraded OI signal.");
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

  async function handleManualRefresh() {
    setRefreshing(true);
    try {
      const [signalPayload, chartPayload] = await Promise.all([
        refreshOiUpgradedSignal(selectedDate ?? undefined),
        getPcrOiSnapshots(selectedDate ?? undefined),
      ]);
      setSignalData(signalPayload.NIFTY);
      setChartData(chartPayload);
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to refresh the upgraded OI signal.");
    } finally {
      setRefreshing(false);
    }
  }

  const latest = signalData.length ? signalData[signalData.length - 1] : null;
  const points = chartData.NIFTY;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <RadioTower size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            OI — Upgraded
          </h1>
          <p>
            A single filtered BUY CE / BUY PE / NO TRADE call for NIFTY -- rolling PCR/OI windows, VWAP + price
            confirmation, premium confirmation and a 3-poll persistence gate, so one noisy reading can&apos;t flip the
            call. Phases 1-3 of the signal-engine upgrade; hysteresis/cooldown and backtesting are a later phase.
          </p>
        </div>
        <div className="toolbar">
          <label className="subtext" htmlFor="oi-upgraded-session-select">
            Session
          </label>
          <select
            id="oi-upgraded-session-select"
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
          <label className="subtext" htmlFor="oi-upgraded-refresh-select">
            Refresh
          </label>
          <select
            id="oi-upgraded-refresh-select"
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
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}

      <SignalDashboard latest={latest} />

      <div className="pcr-oi-section">
        <div className="pcr-oi-split">
          <div className="oi-analysis-chart-col">
            <div className="oi-analysis-section-head">
              <h3>Put-Call Ratio — NIFTY</h3>
            </div>
            <PcrChart title="NIFTY" color={NIFTY_COLOR} points={points} height={GRID_HEIGHT} />
          </div>
          <div className="oi-analysis-chart-col">
            <div className="oi-analysis-section-head">
              <h3>Change in OI — NIFTY</h3>
            </div>
            <p className="pcr-oi-caption" style={{ margin: 0 }}>
              Y-axis in lakhs (1 L = 100,000 contracts).
            </p>
            <Legend items={[{ label: "CE chg OI", color: CE_COLOR }, { label: "PE chg OI", color: PE_COLOR }]} />
            <OiChangeChart title="NIFTY" points={points} height={GRID_HEIGHT} />
          </div>
        </div>
      </div>

      <div className="pcr-oi-section">
        <div className="pcr-oi-split">
          <div className="oi-analysis-chart-col">
            <div className="oi-analysis-section-head">
              <h3>India VIX</h3>
            </div>
            <PcrChart
              title="India VIX"
              color="#7a3fa0"
              points={points}
              height={GRID_HEIGHT}
              accessor={(p) => p.indiaVix}
              seriesLabel="India VIX"
            />
          </div>
          <div className="oi-analysis-chart-col">
            <div className="oi-analysis-section-head">
              <h3>ATM IV — NIFTY</h3>
            </div>
            <Legend items={[{ label: "CE IV", color: CE_COLOR }, { label: "PE IV", color: PE_COLOR }]} />
            <IvChart title="NIFTY" points={points} height={GRID_HEIGHT} />
          </div>
        </div>
      </div>
    </section>
  );
}

function SignalDashboard({ latest }: { latest: OiUpgradedPoint | null }) {
  if (!latest) {
    return (
      <div className="pcr-oi-section">
        <p className="pcr-oi-caption">No data yet for this session.</p>
      </div>
    );
  }

  const { signal, ceScore, peScore, persistence, reasons, pcrState, oiState, priceState } = latest;
  const score = signal === "buyCe" ? ceScore : signal === "buyPe" ? peScore : Math.max(ceScore, peScore);
  const regime = deriveRegime(pcrState, oiState, priceState);
  const badgeClass = signal === "buyCe" ? "buy-ce" : signal === "buyPe" ? "buy-pe" : "no-trade";

  return (
    <div className="pcr-oi-section">
      <div className={`oi-upgraded-card ${badgeClass}`}>
        <div className="oi-upgraded-badge">{SIGNAL_LABEL[signal]}</div>
        <div className="metric-grid oi-upgraded-metric-grid">
          <div className="metric">
            <span>Regime</span>
            <strong>{regime}</strong>
          </div>
          <div className="metric">
            <span>Score</span>
            <strong>
              {ceScore} CE / {peScore} PE
            </strong>
          </div>
          <div className="metric">
            <span>Persistence</span>
            <strong>{Math.min(persistence, 3)} / 3</strong>
          </div>
          <div className="metric">
            <span>NIFTY vs VWAP</span>
            <strong>
              {latest.niftyPrice?.toFixed(2) ?? "—"} / {latest.vwap?.toFixed(2) ?? "—"}
            </strong>
          </div>
        </div>
        <ul className="oi-upgraded-reasons">
          {reasons.map((reason) => (
            <li key={reason.label} className={reason.met ? "met" : "unmet"}>
              <span className="oi-upgraded-reason-mark">{reason.met ? "✓" : "•"}</span>
              {reason.label}
              {reason.value ? <span className="subtext"> — {STATE_LABEL[reason.value] ?? reason.value}</span> : null}
            </li>
          ))}
        </ul>
        <p className="pcr-oi-caption" style={{ margin: 0 }}>
          Signal-engine design (upgrade.md phases 1-3) — score ≥ 8, a ≥3-point lead over the other side, price/premium
          confirmation, and 3 consecutive polls all required before a call fires. Not yet backtested; treat as
          assistive, not a guarantee. Score shown is a live read on today&apos;s real data (may still say NO TRADE for
          the whole session on choppier days).
        </p>
      </div>
    </div>
  );
}
