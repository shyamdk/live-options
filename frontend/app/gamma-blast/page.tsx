"use client";

import { RefreshCcw, ShieldCheck, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { approveGammaBlastSignal, getGammaBlastSessionDetail, getGammaBlastSessions, getGammaBlastState } from "@/lib/api";
import type {
  GammaBlastEvent,
  GammaBlastIndexState,
  GammaBlastSessionDetail,
  GammaBlastState,
  GammaBlastTrade,
  GammaBlastWallStrike,
  GammaBlastWalls,
} from "@/types/gamma-blast";

const moneyFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const STATE_REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_GAMMA_BLAST_REFRESH_SECONDS, 3);
const INDICES = ["NIFTY", "SENSEX"] as const;

export default function GammaBlastPage() {
  const [state, setState] = useState<GammaBlastState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [approvingId, setApprovingId] = useState<number | null>(null);
  const [sessions, setSessions] = useState<GammaBlastSessionDetail["session"][]>([]);
  const [selectedDetail, setSelectedDetail] = useState<GammaBlastSessionDetail | null>(null);

  async function loadState() {
    try {
      setState(await getGammaBlastState());
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load Gamma Blast state.");
    } finally {
      setLoading(false);
    }
  }

  async function loadSessions() {
    try {
      const payload = await getGammaBlastSessions();
      setSessions(payload.sessions);
    } catch {
      // Session history is secondary; ignore failures here.
    }
  }

  useEffect(() => {
    loadState();
    loadSessions();
    const timer = window.setInterval(loadState, STATE_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  async function handleApprove(signalId: number, label: string) {
    if (!window.confirm(`Approve ${label}? This sends an order (or simulates a paper fill) immediately.`)) return;
    setApprovingId(signalId);
    setMessage(null);
    setError(null);
    try {
      const result = await approveGammaBlastSignal(signalId);
      setMessage(`Signal #${signalId} ${String(result.status ?? "processed")}.`);
      await loadState();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to approve signal.");
    } finally {
      setApprovingId(null);
    }
  }

  async function openSession(sessionId: string) {
    try {
      setSelectedDetail(await getGammaBlastSessionDetail(sessionId));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load session detail.");
    }
  }

  const mode = state?.mode ?? "PAPER";

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>Gamma Blast</h1>
          <p>Expiry-day OI-wall breakout monitor</p>
        </div>
        <div className="toolbar">
          <span className={mode === "LIVE" ? "status-live on" : "status-live"}>{mode}</span>
          <button className="icon-button" type="button" title="Refresh" onClick={loadState} disabled={loading}>
            <RefreshCcw size={16} />
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}

      <div className="gb-index-grid">
        {INDICES.map((index) => (
          <IndexPanel
            key={index}
            index={index}
            data={state?.indices[index] ?? { status: "NOT_STARTED" }}
            approvingId={approvingId}
            onApprove={handleApprove}
          />
        ))}
      </div>

      <section className="table-section">
        <div className="section-title">
          <h2>Past Sessions</h2>
          <span>{sessions.length}</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Index</th>
                <th>Mode</th>
                <th>Status</th>
                <th>Spot Open</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((session) => (
                <tr key={session.id}>
                  <td>{session.sessionDate}</td>
                  <td>{session.indexSymbol}</td>
                  <td>{session.mode}</td>
                  <td>{session.status}</td>
                  <td>{money(session.spotOpen)}</td>
                  <td>
                    <button className="icon-button" type="button" title="View session" onClick={() => openSession(session.id)}>
                      <Zap size={14} />
                    </button>
                  </td>
                </tr>
              ))}
              {!sessions.length ? (
                <tr>
                  <td colSpan={6}>No sessions yet.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      {selectedDetail ? <SessionDetailCard detail={selectedDetail} onClose={() => setSelectedDetail(null)} /> : null}
    </section>
  );
}

function IndexPanel({
  index,
  data,
  approvingId,
  onApprove,
}: {
  index: string;
  data: GammaBlastIndexState;
  approvingId: number | null;
  onApprove: (signalId: number, label: string) => void;
}) {
  if (data.status === "NOT_STARTED") {
    return (
      <section className="gb-panel">
        <div className="section-title">
          <h2>{index}</h2>
          <span className="risk-pill">Not started</span>
        </div>
        <p className="subtext">No session today — waiting for expiry day and market hours.</p>
      </section>
    );
  }

  const wallBars = buildWallBars(data.walls, data.spot);

  return (
    <section className="gb-panel">
      <div className="section-title">
        <h2>{index}</h2>
        <span className={`risk-pill ${data.wsConnected ? "target" : "stopLoss"}`}>
          {data.wsConnected ? "Live" : "Reconnecting"}
        </span>
      </div>
      <div className="gb-status-row">
        <span>Spot: {money(data.spot)}</span>
        <span>Open: {money(data.sessionOpen)}</span>
        <span className={data.quietDay?.isQuiet ? "positive" : "negative"}>
          {data.quietDay?.isQuiet ? "Quiet day" : "Not quiet"}
          {data.quietDay?.movePercent !== null && data.quietDay?.movePercent !== undefined
            ? ` (${data.quietDay.movePercent.toFixed(2)}%)`
            : ""}
        </span>
      </div>

      {wallBars.length ? (
        <div className="gb-wall-chart" role="img" aria-label={`${index} open interest by strike`}>
          {wallBars.map((bar) => (
            <div key={`${bar.strike}-${bar.side}`} className={`gb-wall-row ${bar.highlight ?? ""}`}>
              <span className="gb-wall-strike">
                {bar.strike} {bar.side}
              </span>
              <span className="gb-wall-bar-track">
                <span className="gb-wall-bar-fill" style={{ width: `${bar.widthPercent}%` }} />
              </span>
              <span className="gb-wall-oi">{formatOi(bar.oi)}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="subtext">Waiting for OI data…</p>
      )}

      {data.pendingSignals.length ? (
        <div className="alert warning">
          <strong>{data.pendingSignals.length} signal(s) awaiting approval</strong>
          <ul className="gb-signal-list">
            {data.pendingSignals.map((signal) => (
              <li key={signal.id}>
                <span>
                  {signal.kind} · {signal.optionSide ?? ""} {signal.strike ?? ""} · level {money(signal.level)}
                </span>
                <button
                  className="icon-button approve"
                  type="button"
                  title="Approve"
                  onClick={() => onApprove(signal.id, `${signal.kind} ${signal.optionSide ?? ""} ${signal.strike ?? ""}`)}
                  disabled={approvingId === signal.id}
                >
                  <ShieldCheck size={15} />
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <OpenTradesTable trades={data.openTrades} />
      <EventTimeline events={data.events} />
    </section>
  );
}

function OpenTradesTable({ trades }: { trades: GammaBlastTrade[] }) {
  if (!trades.length) return null;
  return (
    <div className="table-wrap gb-subtable">
      <table>
        <thead>
          <tr>
            <th>Strike</th>
            <th>Qty</th>
            <th>Entry</th>
            <th>Mode</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => (
            <tr key={trade.id}>
              <td>
                {trade.strike} {trade.optionSide}
              </td>
              <td>{trade.entryQty}</td>
              <td>{money(trade.entryPrice)}</td>
              <td>{trade.mode}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EventTimeline({ events }: { events: GammaBlastEvent[] }) {
  if (!events.length) return null;
  const recent = events.slice(-15).reverse();
  return (
    <div className="gb-timeline">
      {recent.map((event) => (
        <div key={event.id} className="gb-timeline-row">
          <span className="subtext">{formatTime(event.createdAt)}</span>
          <span>{event.message}</span>
        </div>
      ))}
    </div>
  );
}

function SessionDetailCard({ detail, onClose }: { detail: GammaBlastSessionDetail; onClose: () => void }) {
  return (
    <section className="table-section">
      <div className="section-title">
        <h2>
          {detail.session.indexSymbol} — {detail.session.sessionDate}
        </h2>
        <button className="icon-button" type="button" onClick={onClose} title="Close">
          ×
        </button>
      </div>
      {detail.retrospective ? (
        <div className="alert success">
          <strong>Retrospective</strong>
          <p style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>{detail.retrospective.summary}</p>
        </div>
      ) : (
        <p className="subtext">No retrospective generated yet for this session.</p>
      )}
      <EventTimeline events={detail.events} />
    </section>
  );
}

function buildWallBars(
  walls: GammaBlastWalls | null | undefined,
  spot: number | null | undefined,
): { strike: number; side: string; oi: number; widthPercent: number; highlight?: string }[] {
  const entries: GammaBlastWallStrike[] = [];
  if (walls?.callWall) entries.push(walls.callWall);
  if (walls?.putWall) entries.push(walls.putWall);
  if (!entries.length) return [];
  const maxOi = Math.max(...entries.map((e) => e.oi ?? 0), 1);
  return entries
    .sort((a, b) => a.strike - b.strike)
    .map((entry) => ({
      strike: entry.strike,
      side: entry.optionSide,
      oi: entry.oi ?? 0,
      widthPercent: Math.max(4, ((entry.oi ?? 0) / maxOi) * 100),
      highlight: entry.optionSide === "CE" ? "gb-wall-call" : "gb-wall-put",
    }));
}

function formatOi(value: number): string {
  if (value >= 10000000) return `${(value / 10000000).toFixed(1)}Cr`;
  if (value >= 100000) return `${(value / 100000).toFixed(1)}L`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
  return String(value);
}

function formatTime(iso: string): string {
  const parts = iso.split("T");
  return parts[1] ?? iso;
}

function money(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return moneyFormat.format(value);
}

function secondsToMs(value: string | undefined, fallbackSeconds: number): number {
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : fallbackSeconds * 1000;
}
