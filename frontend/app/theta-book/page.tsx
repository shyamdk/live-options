"use client";

import { Coins, RefreshCcw } from "lucide-react";
import { useEffect, useState } from "react";

import { approveThetaSignal, getThetaConfig, getThetaState, rejectThetaSignal, updateThetaConfig } from "@/lib/api";
import type { ThetaPosition, ThetaRuntimeConfig, ThetaSignal, ThetaState, ThetaUnderlying } from "@/types/theta";

const money = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const STATE_REFRESH_MS = 10000;
const UNDERLYINGS: ThetaUnderlying[] = ["NIFTY", "SENSEX"];

const DAY_TYPE_LABEL: Record<string, string> = {
  expiry: "Expiry day",
  t1: "T-1",
  t2: "T-2",
  too_far: "Too far",
};

function fmt(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

function pnlClass(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  return value >= 0 ? "positive" : "negative";
}

export default function ThetaBookPage() {
  const [state, setState] = useState<ThetaState | null>(null);
  const [config, setConfig] = useState<ThetaRuntimeConfig | null>(null);
  const [configDraft, setConfigDraft] = useState<{ maxConcurrentMargin: string; maxDailyLoss: string }>({
    maxConcurrentMargin: "",
    maxDailyLoss: "",
  });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function loadState() {
    try {
      setState(await getThetaState());
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load Theta Book state.");
    } finally {
      setLoading(false);
    }
  }

  async function loadConfig() {
    try {
      const cfg = await getThetaConfig();
      setConfig(cfg);
      setConfigDraft({ maxConcurrentMargin: String(cfg.maxConcurrentMargin), maxDailyLoss: String(cfg.maxDailyLoss) });
    } catch {
      // config is a secondary concern; state polling already surfaces errors
    }
  }

  useEffect(() => {
    loadState();
    loadConfig();
    const timer = window.setInterval(loadState, STATE_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  async function run(label: string, action: () => Promise<Record<string, unknown>>, confirmText?: string) {
    if (confirmText && !window.confirm(confirmText)) return;
    setBusy(label);
    setMessage(null);
    setError(null);
    try {
      const result = await action();
      const status = String(result.status ?? "done");
      const detail = result.message ? `: ${result.message}` : "";
      setMessage(`${label} — ${status}${detail}`);
      await loadState();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : `${label} failed.`);
    } finally {
      setBusy(null);
    }
  }

  async function saveConfig() {
    setBusy("Save config");
    setError(null);
    try {
      const updates: Partial<ThetaRuntimeConfig> = {};
      const margin = Number(configDraft.maxConcurrentMargin);
      const loss = Number(configDraft.maxDailyLoss);
      if (Number.isFinite(margin) && margin > 0) updates.maxConcurrentMargin = margin;
      if (Number.isFinite(loss) && loss > 0) updates.maxDailyLoss = loss;
      const updated = await updateThetaConfig(updates);
      setConfig(updated);
      setMessage("Config saved.");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to save config.");
    } finally {
      setBusy(null);
    }
  }

  const mode = state?.mode ?? "PAPER";
  const running = state?.status === "RUNNING";
  const halted = running && state.status === "RUNNING" ? state.halted : false;
  const pendingSignals: ThetaSignal[] = running ? state.pendingSignals : [];
  const openPositions: ThetaPosition[] = running ? state.openPositions : [];
  const closedPositions: ThetaPosition[] = running ? state.closedPositions : [];
  const marginUsed = running ? state.marginUsed : 0;
  const marginCap = running ? state.marginCap : config?.maxConcurrentMargin ?? 0;
  const realizedPnl = running ? state.realizedPnl : 0;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Coins size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Theta Book
          </h1>
          <p>Safe-distance theta selling — NIFTY (Tue) &amp; SENSEX (Thu) weekly expiries, scale-in on richening premium, distance/premium stops</p>
        </div>
        <div className="toolbar">
          <span className={mode === "LIVE" ? "status-live on" : "status-live"}>{mode}</span>
          {halted ? <span className="badge negative">HALTED — daily loss cap hit</span> : null}
          <button className="icon-button" type="button" title="Refresh" onClick={loadState} disabled={loading}>
            <RefreshCcw size={16} />
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}

      <div className="metric-grid">
        <div className="metric">
          <span className="subtext">Status</span>
          <strong>{running ? "Running" : "Not started"}</strong>
        </div>
        <div className="metric">
          <span className="subtext">Realized P&amp;L today</span>
          <strong className={pnlClass(realizedPnl)}>₹{money.format(realizedPnl)}</strong>
        </div>
        <div className="metric">
          <span className="subtext">Margin used / cap</span>
          <strong>
            ₹{money.format(marginUsed)} / ₹{money.format(marginCap)}
          </strong>
        </div>
        <div className="metric">
          <span className="subtext">Open positions</span>
          <strong>{openPositions.length}</strong>
        </div>
      </div>

      <section className="table-section">
        <div className="section-title">
          <h2>Underlyings</h2>
        </div>
        <div className="metric-grid">
          {UNDERLYINGS.map((u) => {
            const info = running ? state.underlyings[u] : null;
            return (
              <div className="metric" key={u}>
                <span className="subtext">{u}</span>
                <strong>
                  {info?.dayType ? DAY_TYPE_LABEL[info.dayType] ?? info.dayType : "—"} · spot {fmt(info?.spot ?? null, u === "NIFTY" ? 1 : 0)}
                </strong>
                <span className="subtext">
                  {info?.expiry ?? "—"} {info?.confirmedFlat ? "· flat confirmed" : ""}
                </span>
              </div>
            );
          })}
        </div>
      </section>

      {pendingSignals.length ? (
        <section className="table-section">
          <div className="section-title">
            <h2>Pending Signals</h2>
            <span>{pendingSignals.length}</span>
          </div>
          <div className="compact-list">
            {pendingSignals.map((signal) => (
              <div className="compact-row" key={signal.id}>
                <span>
                  #{signal.id} {signal.underlying} {signal.side} {signal.kind} — strike {fmt(signal.strike, 0)}{" "}
                  {signal.payload?.reason ? `(${String(signal.payload.reason)})` : ""} ({signal.createdAt})
                </span>
                <span className="toolbar">
                  <button
                    className="button"
                    type="button"
                    disabled={busy !== null}
                    onClick={() =>
                      run(
                        `Approve #${signal.id}`,
                        () => approveThetaSignal(signal.id),
                        `Approve ${signal.kind} signal #${signal.id}? This ${mode === "LIVE" ? "sends real Dhan orders" : "simulates a paper fill"} immediately.`,
                      )
                    }
                  >
                    Approve
                  </button>
                  <button
                    className="button secondary"
                    type="button"
                    disabled={busy !== null}
                    onClick={() => run(`Reject #${signal.id}`, () => rejectThetaSignal(signal.id))}
                  >
                    Reject
                  </button>
                </span>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="table-section">
        <div className="section-title">
          <h2>Open Positions</h2>
          <span>{openPositions.length}</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Underlying</th>
                <th>Side</th>
                <th>Strike</th>
                <th>Day type</th>
                <th>Tranches</th>
                <th>Qty</th>
                <th>Avg entry</th>
                <th>LTP</th>
                <th>Distance %</th>
                <th>Unrealized P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {openPositions.map((p) => (
                <tr key={p.id}>
                  <td>{p.underlying}</td>
                  <td>{p.side}</td>
                  <td>{fmt(p.strike, 0)}</td>
                  <td>{p.dayType ? DAY_TYPE_LABEL[p.dayType] ?? p.dayType : "—"}</td>
                  <td>{p.trancheCount}</td>
                  <td>{p.totalQty}</td>
                  <td>{fmt(p.avgEntryPremium)}</td>
                  <td>{fmt(p.currentPremium)}</td>
                  <td>{fmt(p.distancePct)}</td>
                  <td className={pnlClass(p.unrealizedPnl)}>{p.unrealizedPnl != null ? `₹${money.format(p.unrealizedPnl)}` : "—"}</td>
                </tr>
              ))}
              {!openPositions.length ? (
                <tr>
                  <td colSpan={10} className="empty-state">
                    No open positions.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="table-section">
        <div className="section-title">
          <h2>Closed Today</h2>
          <span>
            {closedPositions.length} | realized ₹{money.format(closedPositions.reduce((acc, p) => acc + (p.realizedPnl ?? 0), 0))}
          </span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Underlying</th>
                <th>Side</th>
                <th>Strike</th>
                <th>Tranches</th>
                <th>Qty</th>
                <th>Avg entry</th>
                <th>Reason</th>
                <th>P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {closedPositions.map((p) => (
                <tr key={p.id} className="closed-row">
                  <td>{p.underlying}</td>
                  <td>{p.side}</td>
                  <td>{fmt(p.strike, 0)}</td>
                  <td>{p.trancheCount}</td>
                  <td>{p.totalQty}</td>
                  <td>{fmt(p.avgEntryPremium)}</td>
                  <td>{p.closeReason ?? "—"}</td>
                  <td className={pnlClass(p.realizedPnl)}>{p.realizedPnl != null ? `₹${money.format(p.realizedPnl)}` : "—"}</td>
                </tr>
              ))}
              {!closedPositions.length ? (
                <tr>
                  <td colSpan={8} className="empty-state">
                    No closed positions yet today.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="table-section">
        <div className="section-title">
          <h2>Config</h2>
          <span className="subtext">Estimated margin, not a live broker figure — calibrate against your own margin statement</span>
        </div>
        <div className="compact-list">
          <div className="compact-row">
            <label>
              Max concurrent margin (₹)
              <input
                className="ema5-config-input wide"
                type="number"
                value={configDraft.maxConcurrentMargin}
                onChange={(e) => setConfigDraft((d) => ({ ...d, maxConcurrentMargin: e.target.value }))}
              />
            </label>
            <label>
              Max daily loss (₹)
              <input
                className="ema5-config-input wide"
                type="number"
                value={configDraft.maxDailyLoss}
                onChange={(e) => setConfigDraft((d) => ({ ...d, maxDailyLoss: e.target.value }))}
              />
            </label>
            <button className="button" type="button" disabled={busy !== null} onClick={saveConfig}>
              Save
            </button>
          </div>
        </div>
      </section>

      <section className="table-section">
        <div className="section-title">
          <h2>Event Log</h2>
          <span>{running ? state.events.length : 0}</span>
        </div>
        <div className="compact-list">
          {(running ? state.events : []).map((event) => (
            <div className="compact-row" key={event.id}>
              <span>
                <span className="badge">{event.eventType}</span> {event.message}
              </span>
              <span className="subtext">{event.createdAt}</span>
            </div>
          ))}
          {!running || !state.events.length ? <div className="empty-state">No events yet.</div> : null}
        </div>
      </section>
    </section>
  );
}
