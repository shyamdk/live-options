"use client";

import { Grid3x3, Play, RefreshCw, Save, XOctagon } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import CollapsibleSection from "@/components/CollapsibleSection";
import PfColumnsChart from "@/components/PfColumnsChart";
import { closePfTrade, getPfState, runPfMarket, updatePfConfig } from "@/lib/api";
import type { PfState, PfTrade } from "@/types/pf-lab";

const REFRESH_MS = 60000;

function money(value: number | null | undefined, cur: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const digits = cur === "$" ? 2 : 0;
  return `${value < 0 ? "−" : ""}${cur}${Math.abs(value).toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

function tone(value: number | null | undefined): string | undefined {
  if (!value) return undefined;
  return value > 0 ? "var(--green)" : "var(--red)";
}

function day(epoch: number | null | undefined, withTime = false): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "2-digit",
    ...(withTime ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}),
  });
}

const sideLabel = (side: number) => (side === 1 ? "LONG" : side === -1 ? "SHORT" : "flat");
const sideTone = (side: number) => (side === 1 ? "var(--green)" : side === -1 ? "var(--red)" : "var(--muted)");

export default function PfLabPage() {
  const params = useParams<{ market: string; horizon: string }>();
  const market = String(params.market).toUpperCase();
  const horizon = String(params.horizon).toLowerCase();
  const [state, setState] = useState<PfState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    try {
      setState(await getPfState(market, horizon));
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load.");
    }
  }

  useEffect(() => {
    load();
    const id = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [market, horizon]);

  async function runNow() {
    if (!window.confirm(`Run ${market} now? Every ${market} book (all three horizons) moves to its system's current signal at current prices (paper).`)) return;
    setBusy("run");
    try {
      const r = await runPfMarket(market);
      setMessage(r.changes?.length ? `Changes: ${r.changes.join("; ")}` : r.message || "No changes -- every book already matches its signal.");
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Run failed.");
    } finally {
      setBusy(null);
    }
  }

  async function close(t: PfTrade) {
    if (!window.confirm(`Close #${t.id} ${t.instrument} (paper)? The system may re-open it on the next daily run if its signal is still on.`)) return;
    setBusy(`close-${t.id}`);
    try {
      await closePfTrade(t.id);
      await load();
    } finally {
      setBusy(null);
    }
  }

  const cur = state?.currency ?? (market === "NIFTY" ? "₹" : "$");
  const open = (state?.trades ?? []).filter((t) => t.status === "OPEN");
  const closed = (state?.trades ?? []).filter((t) => t.status === "CLOSED");
  const realized = closed.reduce((s, t) => s + (t.pnl ?? 0), 0);
  const openPnl = open.reduce((s, t) => s + (t.pnl ?? 0), 0);
  const label = state ? `P&F ${state.meta.label} · ${state.horizonLabel}` : `P&F ${market} · ${horizon}`;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Grid3x3 size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            {label}
          </h1>
          <p>
            Five Point &amp; Figure systems from the Definedge transcripts on {state?.meta.label ?? market} daily closes, {state?.chart?.boxPercent ?? "—"}% box × 3
            reversal, paper traded as {market === "NIFTY" ? "NIFTY option credit spreads in the signal's direction (Dhan quotes)" : `${state?.meta.instrument ?? ""} perpetual, long and short (Delta prices)`}.
            Signals update once a day ({market === "NIFTY" ? "15:25 IST" : "05:35 IST, after the UTC daily close"}). <Link href="/pf-lab">All 9 books →</Link>
          </p>
        </div>
        <div className="toolbar" style={{ alignItems: "center" }}>
          <span className="status-live on" style={{ whiteSpace: "nowrap" }}>PAPER</span>
          <button type="button" className="button secondary" onClick={load} style={{ whiteSpace: "nowrap" }}>
            <RefreshCw size={14} /> Refresh
          </button>
          <button type="button" className="button" onClick={runNow} disabled={!!busy} style={{ whiteSpace: "nowrap" }}>
            <Play size={14} /> {busy === "run" ? "Running…" : "Run now"}
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
        <div className="metric metric-compact" style={{ flex: "1 1 150px" }}>
          <span>Last close</span>
          <strong>{num(state?.chart?.lastClose)}</strong>
          <span className="pcr-oi-caption">{day(state?.chart?.lastTime)}</span>
        </div>
        <div className="metric metric-compact" style={{ flex: "1 1 150px" }}>
          <span>10-column average</span>
          <strong>{num(state?.chart?.ma)}</strong>
          <span className="pcr-oi-caption">{state?.chart && state.chart.ma ? (state.chart.lastClose > state.chart.ma ? "price above" : "price below") : ""}</span>
        </div>
        <div className="metric metric-compact" style={{ flex: "1 1 150px" }}>
          <span>Open P&amp;L</span>
          <strong style={{ color: tone(openPnl) }}>{money(openPnl, cur)}</strong>
          <span className="pcr-oi-caption">{open.length} open</span>
        </div>
        <div className="metric metric-compact" style={{ flex: "1 1 150px" }}>
          <span>Realized (net)</span>
          <strong style={{ color: tone(realized) }}>{money(realized, cur)}</strong>
          <span className="pcr-oi-caption">{closed.length} closed</span>
        </div>
        <div className="metric metric-compact" style={{ flex: "1 1 150px" }}>
          <span>Last run</span>
          <strong style={{ fontSize: 15 }}>{day(state?.lastRun, true)}</strong>
          <span className="pcr-oi-caption">buy &amp; hold backtest: {pct(state?.backtestData?.buyHoldLog)}/yr</span>
        </div>
      </div>

      <CollapsibleSection id={`pf-${market}-${horizon}-systems`} title="Systems — today's signal, paper book and backtest">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>System</th>
                <th>Signal now</th>
                <th>Paper position</th>
                <th>Open P&amp;L</th>
                <th>Realized</th>
                <th>Backtest /yr (compounded)</th>
                <th>Trades / yr</th>
                <th>Win</th>
                <th>Max DD</th>
                {market === "NIFTY" ? <th>Spread model /yr (1 lot)</th> : null}
              </tr>
            </thead>
            <tbody>
              {(state?.systems ?? []).map((s) => {
                const sig = state?.signals?.[s.key];
                const bt = state?.backtest?.[s.key]?.underlying;
                const sp = state?.backtest?.[s.key]?.spread;
                const pos = open.find((t) => t.system === s.key);
                const tot = state?.totals?.[s.key];
                const enabled = state?.config.systems.includes(s.key);
                return (
                  <tr key={s.key} style={enabled ? undefined : { opacity: 0.5 }}>
                    <td>
                      <strong>{s.label}</strong>
                      {enabled ? null : <span className="pcr-oi-caption"> (off)</span>}
                    </td>
                    <td style={{ color: sideTone(sig?.side ?? 0), fontWeight: 600 }}>
                      {sideLabel(sig?.side ?? 0)}
                      {sig?.since ? <span className="pcr-oi-caption" style={{ fontWeight: 400 }}> since {day(sig.since)} @ {num(sig.at, 0)}</span> : null}
                    </td>
                    <td>{pos ? `${pos.instrument}${pos.expiry ? ` · ${pos.expiry}` : ""}` : "—"}</td>
                    <td style={{ color: tone(pos?.pnl) }}>{pos ? money(pos.pnl, cur) : "—"}</td>
                    <td style={{ color: tone(tot?.realized) }}>{tot?.closedCount ? money(tot.realized, cur) : "—"}</td>
                    <td style={{ color: tone(bt?.logAnnual) }}>{bt?.trades ? pct(bt.logAnnual) : "no trades"}</td>
                    <td>{bt?.perYear ?? "—"}</td>
                    <td>{bt?.win !== undefined ? `${bt.win.toFixed(0)}%` : "—"}</td>
                    <td>{bt?.maxDD !== undefined ? `${bt.maxDD.toFixed(0)}%` : "—"}</td>
                    {market === "NIFTY" ? <td style={{ color: tone(sp?.annual) }}>{sp?.trades ? money(sp.annual, "₹") : "—"}</td> : null}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="pcr-oi-caption" style={{ marginTop: 8 }}>
          Backtest: {state?.backtestData ? `${state.backtestData.from} → ${state.backtestData.to}` : "—"}, signals on daily closes, after costs
          {market === "NIFTY" ? "; underlying % is NIFTY futures-like, the spread column is a Black-Scholes model on India VIX (not real option prices)" : "; Binance daily closes, Delta fees + an assumed funding cost"}.
          Buy &amp; hold over the same period: {pct(state?.backtestData?.buyHoldLog)}/yr compounded. Max DD is in % of one position's notional.
        </p>
      </CollapsibleSection>

      {state?.chart ? (
        <CollapsibleSection id={`pf-${market}-${horizon}-chart`} title={`P&F chart — last ${state.chart.columns.length} columns (${state.chart.boxPercent}% × 3)`}
          aside={<span className="pcr-oi-caption">dashed line = 10-column average · dot = last close</span>}>
          <PfColumnsChart columns={state.chart.columns} ma={state.chart.ma} lastClose={state.chart.lastClose} />
        </CollapsibleSection>
      ) : (
        <div className="alert warning">No chart yet — the first daily run loads the history.</div>
      )}

      <CollapsibleSection id={`pf-${market}-${horizon}-open`} title={`Open positions (${open.length})`}>
        <TradeTable trades={open} cur={cur} systems={state?.systems ?? []} onClose={close} busy={busy} />
      </CollapsibleSection>

      <CollapsibleSection id={`pf-${market}-${horizon}-closed`} title={`Closed trades (${closed.length})`} defaultOpen={false}>
        <TradeTable trades={closed} cur={cur} systems={state?.systems ?? []} />
      </CollapsibleSection>

      <CollapsibleSection id={`pf-${market}-${horizon}-log`} title={`Log (${state?.events.length ?? 0})`} defaultOpen={false}>
        <div className="table-wrap">
          <table style={{ fontSize: 12 }}>
            <tbody>
              {(state?.events ?? []).map((e) => (
                <tr key={e.id}>
                  <td style={{ whiteSpace: "nowrap" }}>{day(e.time, true)}</td>
                  <td>{e.system ?? ""}</td>
                  <td style={{ color: e.kind === "error" ? "var(--red)" : undefined }}>{e.kind}</td>
                  <td>{e.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSection>

      {state ? <Settings state={state} onSaved={load} /> : null}
    </section>
  );
}

function TradeTable({ trades, cur, systems, onClose, busy }: { trades: PfTrade[]; cur: string; systems: { key: string; label: string }[]; onClose?: (t: PfTrade) => void; busy?: string | null }) {
  if (!trades.length) return <div className="empty-state">None.</div>;
  const name = (k: string) => systems.find((s) => s.key === k)?.label ?? k;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>System</th>
            <th>Side</th>
            <th>Instrument</th>
            <th>Opened</th>
            <th>Underlying in → out</th>
            <th>Entry</th>
            <th>{onClose ? "Now" : "Exit"}</th>
            <th>P&amp;L (net)</th>
            <th>{onClose ? "" : "Reason"}</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr key={t.id}>
              <td>{t.id}</td>
              <td>{name(t.system)}</td>
              <td style={{ color: sideTone(t.side), fontWeight: 600 }}>{sideLabel(t.side)}</td>
              <td>
                {t.instrument}
                {t.expiry ? <span className="pcr-oi-caption"> · {t.expiry}</span> : null}
                <div className="pcr-oi-caption">qty {t.qty} · {t.trigger}</div>
              </td>
              <td>{day(t.openedAt, true)}</td>
              <td>
                {num(t.underlyingEntry, 0)} → {t.underlyingExit ? num(t.underlyingExit, 0) : "…"}
              </td>
              <td>{num(t.entryPrice)}</td>
              <td>{onClose ? num(t.lastValue) : num(t.exitPrice)}</td>
              <td style={{ color: tone(t.pnl) }}>{money(t.pnl, cur)}</td>
              <td>
                {onClose ? (
                  <button type="button" className="button secondary" onClick={() => onClose(t)} disabled={busy === `close-${t.id}`}>
                    <XOctagon size={13} /> Close
                  </button>
                ) : (
                  <span className="pcr-oi-caption">{t.exitReason}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Settings({ state, onSaved }: { state: PfState; onSaved: () => void }) {
  const [size, setSize] = useState(String(state.market === "NIFTY" ? state.config.lots : state.config.notionalUsd));
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => setSize(String(state.market === "NIFTY" ? state.config.lots : state.config.notionalUsd)), [state.market, state.config.lots, state.config.notionalUsd]);
  async function save(updates: Record<string, unknown>) {
    setErr(null);
    try {
      await updatePfConfig(state.market, state.horizon, updates);
      onSaved();
    } catch (exc) {
      setErr(exc instanceof Error ? exc.message : "Save failed.");
    }
  }
  return (
    <CollapsibleSection id={`pf-${state.market}-${state.horizon}-settings`} title="Settings" defaultOpen={false}>
      {err ? <div className="alert error">{err}</div> : null}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center", fontSize: 13 }}>
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={state.config.enabled} onChange={(e) => save({ enabled: e.target.checked })} />
          Book active (unticked: positions close on the next run)
        </label>
        {state.systems.map((s) => (
          <label key={s.key} style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={state.config.systems.includes(s.key)} onChange={(e) => save({ systems: { [s.key]: e.target.checked } })} />
            {s.label}
          </label>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 12, fontSize: 13 }}>
        <span>{state.market === "NIFTY" ? "Lots per spread" : "Notional per position (USD)"}</span>
        <input value={size} onChange={(e) => setSize(e.target.value)} style={{ width: 90, fontSize: 13, padding: "3px 6px" }} />
        <button type="button" className="button" onClick={() => save(state.market === "NIFTY" ? { lots: Number(size) } : { notionalUsd: Number(size) })}>
          <Save size={14} /> Save
        </button>
        <span className="pcr-oi-caption">applies to new positions</span>
      </div>
    </CollapsibleSection>
  );
}
