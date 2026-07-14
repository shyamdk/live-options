"use client";

import { RefreshCcw, ShieldCheck, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { approveGammaBlastSignal, getGammaBlastSessionDetail, getGammaBlastSessions, getGammaBlastState } from "@/lib/api";
import type {
  GammaBlastEvent,
  GammaBlastIndexState,
  GammaBlastSessionDetail,
  GammaBlastState,
  GammaBlastStrikeRow,
  GammaBlastTrade,
  GammaBlastWallStrike,
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

  return (
    <section className="gb-panel gb-panel-active">
      <div className="section-title">
        <h2>{index}</h2>
        <span className={`risk-pill ${data.wsConnected ? "target" : "stopLoss"}`}>
          {data.wsConnected ? "Live" : "Reconnecting"}
        </span>
      </div>
      <div className="gb-status-row">
        <span>
          Spot: <strong>{money(data.spot)}</strong>
        </span>
        <span>Session open: {money(data.sessionOpen)}</span>
        <span className={data.quietDay?.isQuiet ? "positive" : "negative"}>
          {data.quietDay === null || data.quietDay === undefined
            ? "Quiet-day: waiting for spot…"
            : data.quietDay.isQuiet
              ? `Quiet day (moved ${money(data.quietDay.movePercent)}%)`
              : `Not quiet — moved ${money(data.quietDay.movePercent)}%`}
        </span>
        <span className={data.entryWindowOk ? "positive" : ""}>
          Entry window {data.entryWindow} IST — {data.entryWindowOk ? "open" : "closed"}
        </span>
        <span className="subtext">Force exit {data.forceExitTime} IST</span>
      </div>

      <WallSummary walls={data.walls} />

      <StrikesTable strikes={data.strikes} walls={data.walls} />

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

function WallSummary({ walls }: { walls: { callWall: GammaBlastWallStrike | null; putWall: GammaBlastWallStrike | null } | null | undefined }) {
  if (!walls || (!walls.callWall && !walls.putWall)) {
    return <p className="subtext">Waiting for OI data to identify walls…</p>;
  }
  return (
    <div className="gb-wall-summary">
      <WallCard label="Call wall (resistance)" strike={walls.callWall} className="gb-wall-call" />
      <WallCard label="Put wall (support)" strike={walls.putWall} className="gb-wall-put" />
    </div>
  );
}

function WallCard({ label, strike, className }: { label: string; strike: GammaBlastWallStrike | null; className: string }) {
  if (!strike) {
    return (
      <div className={`gb-wall-card ${className}`}>
        <span className="subtext">{label}</span>
        <p className="subtext">No qualifying strike yet</p>
      </div>
    );
  }
  return (
    <div className={`gb-wall-card ${className}`}>
      <span className="subtext">{label}</span>
      <strong>
        {strike.strike} {strike.optionSide}
      </strong>
      <span>OI {formatOi(strike.oi ?? 0)}</span>
      <span>
        {strike.distancePoints !== null && strike.distancePoints !== undefined
          ? `${strike.distancePoints > 0 ? "+" : ""}${money(strike.distancePoints)} pts (${strike.distancePercent}%) from spot`
          : "-"}
      </span>
      <span className="gb-greeks">
        Δ {greek(strike.delta)} · Γ {greek(strike.gamma, 4)} · Θ {greek(strike.theta)} · V {greek(strike.vega)}
        {strike.iv !== null && strike.iv !== undefined ? ` · IV ${money(strike.iv)}%` : ""}
      </span>
    </div>
  );
}

function StrikesTable({
  strikes,
  walls,
}: {
  strikes: GammaBlastStrikeRow[];
  walls: { callWall: GammaBlastWallStrike | null; putWall: GammaBlastWallStrike | null } | null | undefined;
}) {
  if (!strikes.length) return null;
  const wallSecurityIds = new Set([walls?.callWall?.securityId, walls?.putWall?.securityId].filter(Boolean));
  return (
    <div className="table-wrap gb-subtable">
      <table>
        <thead>
          <tr>
            <th>Strike</th>
            <th>Side</th>
            <th>LTP</th>
            <th>OI</th>
            <th>Dist</th>
            <th>Delta</th>
            <th>Gamma</th>
            <th>Theta</th>
            <th>Vega</th>
            <th>IV</th>
          </tr>
        </thead>
        <tbody>
          {strikes.map((row) => (
            <tr key={row.securityId} className={wallSecurityIds.has(row.securityId) ? (row.optionSide === "CE" ? "gb-wall-call" : "gb-wall-put") : ""}>
              <td>{row.strike}</td>
              <td>
                <span className={`badge ${row.optionSide === "CE" ? "buy" : "sell"}`}>{row.optionSide}</span>
              </td>
              <td>{money(row.ltp)}</td>
              <td>{formatOi(row.oi ?? 0)}</td>
              <td>
                {row.distancePoints !== null && row.distancePoints !== undefined
                  ? `${row.distancePoints > 0 ? "+" : ""}${row.distancePoints.toFixed(0)}`
                  : "-"}
              </td>
              <td>{greek(row.delta)}</td>
              <td>{greek(row.gamma, 4)}</td>
              <td>{greek(row.theta)}</td>
              <td>{greek(row.vega)}</td>
              <td>{row.iv !== null && row.iv !== undefined ? `${money(row.iv)}%` : "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function greek(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toFixed(decimals);
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
