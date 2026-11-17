"use client";

import { Gauge, RefreshCw, Save, X } from "lucide-react";
import { useEffect, useState } from "react";

import CollapsibleSection from "@/components/CollapsibleSection";
import { DailyTotalsTable, groupDailyTotals } from "@/components/DailyTotals";
import ToneText from "@/components/ToneText";
import { closeIndexRunwayTrade, getIndexRunwaySignals, getIndexRunwayState, getIndexRunwayTrades, updateIndexRunwayConfig } from "@/lib/api";
import type { RunwayConfig, RunwayFeatures, RunwaySignal, RunwayState, RunwayTrade } from "@/types/index-runway";

const REFRESH_MS = 15000;
const EXIT_LABEL: Record<string, string> = { time: "Hold time up", eod: "End of day", manual: "Closed manually" };

function inr(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value < 0 ? "−" : ""}₹${Math.abs(Math.round(value)).toLocaleString("en-IN")}`;
}

function num(value: unknown, digits = 2): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function signed(value: unknown, digits = 2): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `${value > 0 ? "+" : ""}${num(value, digits)}`;
}

function tone(value: number | null | undefined): string | undefined {
  if (!value) return undefined;
  return value > 0 ? "var(--green)" : "var(--red)";
}

function hhmm(epoch: number | null | undefined): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });
}

// Times are 1-min bar start times, as in the backtest: trigger "10:01→10:02" compares those two bar closes,
// the trade enters at the 10:02 close and exits holdMinutes bars later.
const triggerWindow = (t: number) => `${hhmm(t - 60)}→${hhmm(t)}`;

function pct(n: number, d: number): string {
  return d ? `${((100 * n) / d).toFixed(1)}%` : "—";
}

function todayIst(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

export default function IndexRunwayPage() {
  const [state, setState] = useState<RunwayState | null>(null);
  const [trades, setTrades] = useState<RunwayTrade[]>([]);
  const [signals, setSignals] = useState<RunwaySignal[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    try {
      const [s, t, g] = await Promise.all([getIndexRunwayState(), getIndexRunwayTrades(), getIndexRunwaySignals(todayIst())]);
      setState(s);
      setTrades(t.trades);
      setSignals(g.signals);
      setError(s.error ?? null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load Index Runway.");
    }
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  async function closeTrade(trade: RunwayTrade) {
    if (!window.confirm(`Close paper trade #${trade.id} now at the latest snapshot prices?`)) return;
    setBusy(`close-${trade.id}`);
    try {
      const r = await closeIndexRunwayTrade(trade.id);
      setMessage(r.message ? `${r.status}: ${r.message}` : `Trade #${trade.id}: ${r.status}`);
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Close failed.");
    } finally {
      setBusy(null);
    }
  }

  const config = state?.config;
  const closed = trades.filter((t) => t.status === "CLOSED");

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Gauge size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Index Runway
          </h1>
          <p>
            Forward test of the NIFTY &quot;40 points in 2 minutes&quot; study (paper only). Every 1-min close the page compares the minute with the one before
            it -- index move, India VIX, ATM CE/PE Greeks and IV, and cluster / chain OI -- and opens a paper{" "}
            {config?.tradeMode === "follow" ? "ATM option in the trigger direction" : "long ATM straddle"} when the trigger conditions match, closing it{" "}
            {config?.holdMinutes ?? 2} minutes later. Backtest Jan 2025 – Oct 2026: the default rule was followed by a 40-pt move 6.2% of the time in 2026
            (vs 0.6% for any minute) and did not predict direction, so treat it as a volatility alert being tested.
          </p>
        </div>
        <div className="toolbar" style={{ alignItems: "center" }}>
          <span className="status-live on" style={{ whiteSpace: "nowrap" }}>PAPER</span>
          <span className={`status-live ${config?.enabled && state?.monitorEnabled ? "on" : ""}`} style={{ whiteSpace: "nowrap" }}>
            {!state?.monitorEnabled ? "Monitor off" : config?.enabled ? "Auto entry on" : "Auto entry paused"}
          </span>
          <button type="button" className="button secondary" onClick={load} style={{ whiteSpace: "nowrap" }}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}

      <StatusStrip state={state} />
      <LastCheck state={state} />

      <CollapsibleSection id="runway-open" title={`Open trades (${state?.openTrades.length ?? 0})`}>
        {state?.openTrades.length ? (
          <TradesTable trades={state.openTrades} onClose={closeTrade} busy={busy} />
        ) : (
          <p className="pcr-oi-caption" style={{ margin: 0 }}>
            No open trade. The next one opens on a minute that meets every condition below, between {config?.entryStart ?? "09:16"} and {config?.entryEnd ?? "15:15"}.
          </p>
        )}
      </CollapsibleSection>

      <CollapsibleSection id="runway-signals" title={`Today's signals (${signals.length})`}>
        <SignalsTable signals={signals} />
      </CollapsibleSection>

      <CollapsibleSection id="runway-snapshot" title="Last minute: Greeks and OI" defaultOpen={false}>
        {state?.lastFeatures ? <Snapshot f={state.lastFeatures} /> : <p className="pcr-oi-caption">No snapshot yet -- the first one appears two minutes after the market opens.</p>}
      </CollapsibleSection>

      <CollapsibleSection id="runway-pnl" title="Daily P&L">
        <DailyTotalsTable rows={groupDailyTotals(closed, (t) => t.exitTime, (t) => t.grossPnl, (t) => t.netPnl)} cumulative />
      </CollapsibleSection>

      <CollapsibleSection id="runway-trades" title={`All trades (${trades.length})`} defaultOpen={false}>
        <TradesTable trades={trades} onClose={closeTrade} busy={busy} />
      </CollapsibleSection>

      <EstimateTable config={config ?? null} />
      <SettingsSection config={config ?? null} onSaved={load} />
    </section>
  );
}

function StatusStrip({ state }: { state: RunwayState | null }) {
  const f = state?.lastFeatures;
  const s = state?.stats;
  const metrics = [
    { label: "NIFTY (last 1-min close)", value: num(f?.spotNow), caption: state?.lastCheck ? `${hhmm(state.lastCheck)} bar` : "" },
    { label: "Trigger-minute move", value: f ? `${signed(f.trigPts, 1)} pts` : "—", color: tone(f?.trigPts), caption: f ? `5-min range ${num(f.range5, 1)} pts` : "" },
    { label: "India VIX", value: num(f?.vixNow), caption: f ? `${signed(f.vixChg)} in the minute` : "" },
    { label: "ATM IV change", value: signed(f?.ivChgAvg), caption: f ? `ATM ${num(f.atmStrike, 0)} · CE ${signed(f.CE_iv_chg)} / PE ${signed(f.PE_iv_chg)}` : "" },
    {
      label: "Live signal hit rate",
      value: s ? pct(s.signalHits, s.signalsScored) : "—",
      caption: s ? `${s.signalHits} of ${s.signalsScored} signals reached 40 pts · backtest 6.2%` : "",
    },
    {
      label: "Any-minute hit rate",
      value: s ? pct(s.hits, s.scored) : "—",
      caption: s ? `${s.scored.toLocaleString("en-IN")} minutes over ${s.days} day${s.days === 1 ? "" : "s"} · backtest 0.6%` : "",
    },
    { label: "Market", value: state?.marketOpen ? "Open" : "Closed", caption: "checked at every 1-min close" },
  ];
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
      {metrics.map((m) => (
        <div key={m.label} className="metric metric-compact" style={{ flex: "1 1 160px" }}>
          <span>{m.label}</span>
          <strong style={{ color: m.color }}>{m.value}</strong>
          {m.caption ? <span className="pcr-oi-caption"><ToneText text={m.caption} /></span> : null}
        </div>
      ))}
    </div>
  );
}

function LastCheck({ state }: { state: RunwayState | null }) {
  if (!state) return null;
  const est = state.lastFeatures?.estimate;
  return (
    <div className="metric" style={{ marginBottom: 12, display: "block" }}>
      <span>
        Last check {state.lastCheck ? `(trigger ${triggerWindow(state.lastCheck)})` : ""} --{" "}
        <strong style={{ color: state.lastMatched ? "var(--green)" : undefined }}>{state.lastMatched ? "conditions met" : "no signal"}</strong>
      </span>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 18px", marginTop: 6, fontSize: 13 }}>
        {state.lastReasons.length ? state.lastReasons.map((r) => <span key={r} style={{ color: r.startsWith("✓") ? "var(--green)" : r.startsWith("✗") ? "var(--muted)" : undefined }}>{r}</span>) : <span className="pcr-oi-caption">Waiting for the first completed minute.</span>}
      </div>
      {est ? (
        <div className="pcr-oi-caption" style={{ marginTop: 6 }}>
          Backtest estimate for a trigger this size: median move {num(est.median, 1)} pts, 1 in 4 above {num(est.p75, 1)} pts, {num(est.hit40, 1)}% reached 40 pts.
        </div>
      ) : null}
      {state.skipped ? <div className="pcr-oi-caption" style={{ marginTop: 4 }}>{state.skipped}</div> : null}
    </div>
  );
}

function legsText(t: RunwayTrade): string {
  return t.legs.map((l) => `${num(l.strike, 0)} ${l.option} ${num(l.entry)}→${l.exit == null ? "…" : num(l.exit)}`).join(" + ");
}

function TradesTable({ trades, onClose, busy }: { trades: RunwayTrade[]; onClose: (t: RunwayTrade) => void; busy: string | null }) {
  if (!trades.length) return <p className="pcr-oi-caption" style={{ margin: 0 }}>No trades yet.</p>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Trigger</th>
            <th>Trigger pts</th>
            <th>VIX</th>
            <th>IV chg</th>
            <th>Legs (entry→exit)</th>
            <th>Lots</th>
            <th>Est. move</th>
            <th>Actual move</th>
            <th>40 pts?</th>
            <th>Exit</th>
            <th>Gross</th>
            <th>Charges</th>
            <th>Net</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr key={t.id}>
              <td>{t.id}</td>
              <td>
                {t.day.slice(5)} {triggerWindow(t.signalTime)}
              </td>
              <td style={{ color: tone(t.trigPts) }}>{signed(t.trigPts, 1)}</td>
              <td>
                {num(t.vix)} <span className="pcr-oi-caption">({signed(t.vixChg)})</span>
              </td>
              <td>{signed(t.ivChg)}</td>
              <td>
                {t.mode === "straddle" ? "Straddle " : "Follow "}
                {legsText(t)}
              </td>
              <td>{t.lots}</td>
              <td>{t.estMove == null ? "—" : `${num(t.estMove, 0)}–${num(t.estP75, 0)}`}</td>
              <td style={{ color: tone(t.actualMove) }}>{signed(t.actualMove, 1)}</td>
              <td>{t.hit40 == null ? "—" : t.hit40 ? "Yes" : "No"}</td>
              <td>{t.status === "OPEN" ? `due ${hhmm(t.exitDue)} bar` : `${hhmm(t.exitTime)} bar · ${EXIT_LABEL[t.exitReason ?? ""] ?? t.exitReason}`}</td>
              <td style={{ color: tone(t.grossPnl) }}>{inr(t.grossPnl)}</td>
              <td>{inr(t.charges)}</td>
              <td style={{ color: tone(t.netPnl) }}>{inr(t.netPnl)}</td>
              <td>
                {t.status === "OPEN" ? (
                  <button type="button" className="button secondary" onClick={() => onClose(t)} disabled={busy === `close-${t.id}`}>
                    <X size={13} /> Close
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SignalsTable({ signals }: { signals: RunwaySignal[] }) {
  if (!signals.length) return <p className="pcr-oi-caption" style={{ margin: 0 }}>No signals today yet.</p>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>Trigger</th>
            <th>NIFTY</th>
            <th>Trigger pts</th>
            <th>5-min range</th>
            <th>VIX (chg)</th>
            <th>ATM IV chg</th>
            <th>Cluster OI 3-min CE / PE</th>
            <th>Est. move</th>
            <th>Next 2 min</th>
            <th>40 pts?</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((s) => (
            <tr key={s.time}>
              <td>{triggerWindow(s.time)}</td>
              <td>{num(s.close)}</td>
              <td style={{ color: tone(s.trigPts) }}>{signed(s.trigPts, 1)}</td>
              <td>{num(s.range5, 1)}</td>
              <td>
                {num(s.vix)} ({signed(s.vixChg)})
              </td>
              <td>{signed(s.ivChg)}</td>
              <td>
                {signed(s.clCeRoc3, 1)}% / {signed(s.clPeRoc3, 1)}%
              </td>
              <td>{s.estimate ? `${num(s.estimate.median, 0)}–${num(s.estimate.p75, 0)}` : "—"}</td>
              <td style={{ color: tone(s.fwdMove) }}>{s.fwdMove == null ? "pending" : `${signed(s.fwdMove, 1)} (${s.fwdMinutes} min)`}</td>
              <td>{s.hit40 == null ? "—" : s.hit40 ? "Yes" : "No"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const GREEKS: [string, string, number][] = [
  ["ltp", "Price", 2],
  ["iv", "IV", 2],
  ["delta", "Delta", 4],
  ["gamma", "Gamma", 5],
  ["theta", "Theta /day", 2],
  ["vega", "Vega", 3],
  ["rho", "Rho", 3],
];
const OI_GROUPS: [string, string][] = [
  ["cl", "Cluster (ATM ±1)"],
  ["cl3", "Wide cluster (ATM ±3)"],
  ["chain", "Chain (ATM ±10)"],
];

function Snapshot({ f }: { f: RunwayFeatures }) {
  const v = (k: string) => f[k] as number | null | undefined;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 16 }}>
      <div style={{ overflowX: "auto" }}>
        <p className="pcr-oi-caption" style={{ marginTop: 0 }}>
          ATM {num(f.atmStrike, 0)} (fixed at the previous minute) · {num(f.dteMinutes / 60, 1)} h to expiry · Greeks from the chain IV (Black-Scholes, as in the backtest)
        </p>
        <table>
          <thead>
            <tr>
              <th />
              <th>CE prev</th>
              <th>CE now</th>
              <th>CE chg</th>
              <th>PE prev</th>
              <th>PE now</th>
              <th>PE chg</th>
            </tr>
          </thead>
          <tbody>
            {GREEKS.map(([key, label, d]) => (
              <tr key={key}>
                <td>{label}</td>
                <td>{num(v(`CE_${key}_prev`), d)}</td>
                <td>{num(v(`CE_${key}_now`), d)}</td>
                <td style={{ color: tone(v(`CE_${key}_chg`)) }}>{signed(v(`CE_${key}_chg`), d)}</td>
                <td>{num(v(`PE_${key}_prev`), d)}</td>
                <td>{num(v(`PE_${key}_now`), d)}</td>
                <td style={{ color: tone(v(`PE_${key}_chg`)) }}>{signed(v(`PE_${key}_chg`), d)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ overflowX: "auto" }}>
        <p className="pcr-oi-caption" style={{ marginTop: 0 }}>
          OI on the same strikes in both minutes. {f.oiUpdated ? "OI updated this minute." : "OI did not change this minute (no new snapshot from the exchange)."}
        </p>
        <table>
          <thead>
            <tr>
              <th />
              <th>Side</th>
              <th>Now</th>
              <th>1-min chg</th>
              <th>1-min %</th>
              <th>3-min %</th>
              <th>PCR</th>
            </tr>
          </thead>
          <tbody>
            {OI_GROUPS.flatMap(([g, label]) =>
              ["CE", "PE"].map((side, i) => (
                <tr key={`${g}${side}`}>
                  <td>{i === 0 ? label : ""}</td>
                  <td>{side}</td>
                  <td>{num(v(`${g}_${side}_oi_now`), 0)}</td>
                  <td style={{ color: tone(v(`${g}_${side}_oi_chg`)) }}>{signed(v(`${g}_${side}_oi_chg`), 0)}</td>
                  <td>{signed(v(`${g}_${side}_oi_roc_pct`))}</td>
                  <td>{signed(v(`${g}_${side}_oi_roc3_pct`))}</td>
                  <td>{i === 0 ? num(v(`${g}_pcr`)) : ""}</td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EstimateTable({ config }: { config: RunwayConfig | null }) {
  if (!config) return null;
  return (
    <CollapsibleSection id="runway-estimates" title="Move estimate (backtest of the default rule)" defaultOpen={false}>
      <table>
        <thead>
          <tr>
            <th>Trigger-minute move</th>
            <th>Median next-2-min move</th>
            <th>1 in 4 moves above</th>
            <th>Reached 40 pts</th>
          </tr>
        </thead>
        <tbody>
          {config.estimates.map((e) => (
            <tr key={e.from}>
              <td>{e.to == null ? `${e.from}+ pts` : `${e.from}–${e.to} pts`}</td>
              <td>{num(e.median, 1)} pts</td>
              <td>{num(e.p75, 1)} pts</td>
              <td>{num(e.hit40, 1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="pcr-oi-caption">
        Sizes are in either direction: the trigger minute matched the move&apos;s direction only about half the time. Signals with a trigger move below 15 pts get no estimate.
      </p>
    </CollapsibleSection>
  );
}

const SETTING_FIELDS: { key: keyof RunwayConfig; label: string; hint?: string; text?: boolean }[] = [
  { key: "minAbsTrigPts", label: "Min trigger-minute move (pts)", hint: "absolute index move, T-1 → T" },
  { key: "minVix", label: "Min India VIX", hint: "0 = off" },
  { key: "minAbsIvChg", label: "Min ATM IV change", hint: "CE/PE average, absolute; 0 = off" },
  { key: "minRange5", label: "Min 5-min range (pts)", hint: "sum of 1-min moves; 0 = off" },
  { key: "lots", label: "Lots", hint: "65 per lot" },
  { key: "holdMinutes", label: "Hold (minutes)" },
  { key: "maxOpen", label: "Max open trades" },
  { key: "entryStart", label: "Entries from", text: true },
  { key: "entryEnd", label: "Entries until", text: true },
];

function SettingsSection({ config, onSaved }: { config: RunwayConfig | null; onSaved: () => void }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (config) setDraft(Object.fromEntries(SETTING_FIELDS.map((f) => [f.key, String(config[f.key])])));
  }, [config]);
  if (!config) return null;

  async function save(extra?: Partial<RunwayConfig>) {
    setSaving(true);
    setErr(null);
    try {
      await updateIndexRunwayConfig(extra ?? Object.fromEntries(SETTING_FIELDS.map((f) => [f.key, f.text ? draft[f.key] : Number(draft[f.key])])));
      onSaved();
    } catch (exc) {
      setErr(exc instanceof Error ? exc.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <CollapsibleSection id="runway-settings" title="Settings" defaultOpen={false}>
      {err ? <div className="alert error">{err}</div> : null}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 12 }}>
        {SETTING_FIELDS.map((f) => (
          <label key={f.key} style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12 }}>
            <span style={{ color: "var(--muted)", fontWeight: 600 }}>{f.label}</span>
            <input value={draft[f.key] ?? ""} onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))} style={{ width: 110, fontSize: 13, padding: "3px 6px" }} />
            {f.hint ? <span className="pcr-oi-caption">{f.hint}</span> : null}
          </label>
        ))}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "center", marginTop: 12, fontSize: 13 }}>
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
          Trade
          <select value={config.tradeMode} onChange={(e) => save({ tradeMode: e.target.value as RunwayConfig["tradeMode"] })} disabled={saving}>
            <option value="straddle">Long ATM straddle</option>
            <option value="follow">ATM option in the trigger direction</option>
          </select>
        </label>
        <label style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={config.enabled} onChange={(e) => save({ enabled: e.target.checked })} disabled={saving} />
          Automatic paper entry on signals
        </label>
        <label style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={config.notify} onChange={(e) => save({ notify: e.target.checked })} disabled={saving} />
          Telegram on each entry
        </label>
        <button type="button" className="button" onClick={() => save()} disabled={saving}>
          <Save size={14} /> Save settings
        </button>
      </div>
      <p className="pcr-oi-caption">Every enabled condition must hold. Signals are still logged and scored while automatic entry is paused.</p>
    </CollapsibleSection>
  );
}
