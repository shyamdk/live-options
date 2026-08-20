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
import type { OiUpgradedPoint, PcrOiPayload } from "@/types/live";

const DEFAULT_REFRESH_MS = 120000;
const REFRESH_OPTIONS: { value: number; label: string }[] = [
  { value: 30000, label: "30s" },
  { value: 60000, label: "1m" },
  { value: 120000, label: "2m" },
  { value: 180000, label: "3m" },
  { value: 300000, label: "5m" },
];
const GRID_HEIGHT = 300;
// Must match oi_signal_engine.py's SIGNAL_PERSISTENCE -- shown here so the
// "X / 2" readout below is accurate without round-tripping the constant
// through the API just to display it.
const PERSISTENCE_TARGET = 2;

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

const REGIME_LABEL: Record<string, string> = {
  trendingBullish: "Trending Bullish",
  trendingBearish: "Trending Bearish",
  range: "Range",
  transition: "Transition",
};

const STATE_DISPLAY: Record<string, { label: string; cls: string }> = {
  noTrade: { label: "NO TRADE", cls: "no-trade" },
  bullishWatch: { label: "WATCHING — bullish building", cls: "watching" },
  buyCe: { label: "BUY CE — just triggered", cls: "buy-ce" },
  holdCe: { label: "BUY CE — holding", cls: "buy-ce" },
  bearishWatch: { label: "WATCHING — bearish building", cls: "watching" },
  buyPe: { label: "BUY PE — just triggered", cls: "buy-pe" },
  holdPe: { label: "BUY PE — holding", cls: "buy-pe" },
  cooldown: { label: "COOLDOWN", cls: "cooldown" },
};

const LEGEND_ITEMS = [
  {
    title: "State: WATCH → BUY → HOLD → COOLDOWN",
    body: "WATCH means conditions look right but haven't held for 2 straight polls yet. BUY fires once, on the exact poll persistence is met. HOLD keeps the call alive on a lower bar (6/10) than entry (7/10) -- hysteresis -- so a score wobbling by a point doesn't flip a genuinely intact setup back to NO TRADE. COOLDOWN blocks a fresh call on the OPPOSITE side for 10 minutes after an exit; that's specifically what stops a CE → PE → CE whipsaw right after closing a position.",
  },
  {
    title: "Regime — context only, not a gate",
    body: "Trending Bullish/Bearish means PCR, OI positioning and price all broadly agree; Range means they're flat/mixed; Transition means they actively disagree. It's shown so a call can be sanity-checked against the bigger picture. It does NOT block a trade by itself -- the score and persistence rules below already require enough agreement on their own, so stacking a regime gate on top would just make signals rarer for no extra benefit.",
  },
  {
    title: "Score — CE / PE, out of 10",
    body: "A weighted checklist. NIFTY vs VWAP and OI unwind/writing on either side count double (+2 each) since they're the strongest individual tells -- real price confirmation, real positions unwinding. PCR trend, 5-minute trend, premium rising, and supportive IV count +1 each as corroborating evidence. Entry needs 7+; once a call is live, holding only needs 6+ (see State above).",
  },
  {
    title: `Persistence — X / ${PERSISTENCE_TARGET}`,
    body: `Requires ${PERSISTENCE_TARGET} consecutive ~3-minute polls to agree before a call fires -- not just one. This was backtested against a real trading day: requiring 3 consecutive polls, as the design doc literally specifies, produced ZERO confirmed signals despite the raw score reaching 8-10 eight separate times that day. The doc's "~6 minutes" framing assumed a 2-minute poll cadence, not this app's actual 3-minute one -- 3 reads here is closer to 9 minutes. ${PERSISTENCE_TARGET} polls (~6 minutes) is what actually let genuine setups through without going back to firing on every noisy read.`,
  },
  {
    title: "Cooldown countdown",
    body: "When the badge shows COOLDOWN, a fresh signal on the opposite side is deliberately held back until the timer clears -- unless the opposite read is very strong (score 9+, fully confirmed), which overrides the block. The SAME direction can still rebuild during cooldown; only a reversal is blocked.",
  },
];

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
            A single filtered BUY CE / BUY PE / NO TRADE call for NIFTY, built to reduce whipsaws: rolling PCR/OI
            windows, VWAP + price confirmation, premium confirmation, a persistence gate, hysteresis-based
            hold/exit, and a post-exit cooldown. Phases 1-4 of the signal-engine upgrade -- see the legend below for
            what each part does and why.
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
        <h3>How to read this panel</h3>
        <div className="oi-upgraded-legend">
          {LEGEND_ITEMS.map((item) => (
            <div key={item.title} className="oi-upgraded-legend-item">
              <strong>{item.title}</strong>
              <p>{item.body}</p>
            </div>
          ))}
        </div>
      </div>

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

  const { state, ceScore, peScore, persistence, exitStreak, cooldownUntil, reasons } = latest;
  const display = STATE_DISPLAY[state] ?? STATE_DISPLAY.noTrade;
  const cooldownRemainingMin = cooldownUntil ? Math.max(0, Math.round((cooldownUntil - latest.time) / 60)) : null;

  return (
    <div className="pcr-oi-section">
      <div className={`oi-upgraded-card ${display.cls}`}>
        <div className="oi-upgraded-badge">{display.label}</div>
        <div className="metric-grid oi-upgraded-metric-grid">
          <div className="metric">
            <span>Regime</span>
            <strong>{REGIME_LABEL[latest.regime] ?? latest.regime}</strong>
          </div>
          <div className="metric">
            <span>Score</span>
            <strong>
              {ceScore} CE / {peScore} PE
            </strong>
          </div>
          <div className="metric">
            <span>{state === "cooldown" ? "Cooldown left" : "Persistence"}</span>
            <strong>
              {state === "cooldown"
                ? `${cooldownRemainingMin ?? 0} min`
                : `${Math.min(persistence, PERSISTENCE_TARGET)} / ${PERSISTENCE_TARGET}`}
            </strong>
          </div>
          <div className="metric">
            <span>NIFTY vs VWAP</span>
            <strong>
              {latest.niftyPrice?.toFixed(2) ?? "—"} / {latest.vwap?.toFixed(2) ?? "—"}
            </strong>
          </div>
        </div>
        {(state === "holdCe" || state === "holdPe") && exitStreak > 0 ? (
          <p className="pcr-oi-caption" style={{ margin: 0 }}>
            Score has dipped to exit level for {exitStreak}/2 consecutive polls — one more and this exits to
            cooldown, unless it recovers first.
          </p>
        ) : null}
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
          Signal-engine design (upgrade.md phases 1-4), backtested against real NIFTY sessions but not yet validated
          over many days — treat as assistive, not a guarantee. NO TRADE is a valid, intended outcome when the
          evidence doesn&apos;t clear the bar, not a failure state.
        </p>
      </div>
    </div>
  );
}
