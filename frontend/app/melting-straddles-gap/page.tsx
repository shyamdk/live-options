"use client";

import { ColorType, createChart, createSeriesMarkers, IChartApi, ISeriesApi, LineSeries, Time, UTCTimestamp } from "lightweight-charts";
import { Droplets, Play, RefreshCw, Save, ShieldAlert, SquareArrowOutUpRight, XOctagon } from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";

import CollapsibleSection from "@/components/CollapsibleSection";
import { istTime, TradeNote, useTradeMarkers } from "@/components/TradeMarkers";
import { DailyTotalsTable, groupDailyTotals } from "@/components/DailyTotals";
import ToneText from "@/components/ToneText";
import {
  closeMeltingGapTrade as closeMeltingTrade,
  enterMeltingGapNow as enterMeltingNow,
  getMeltingGapDays as getMeltingDays,
  getMeltingGapState as getMeltingState,
  getMeltingGapTrades as getMeltingTrades,
  squareOffMeltingGap as squareOffMelting,
  updateMeltingGapConfig as updateMeltingConfig,
} from "@/lib/api";
import type {
  MeltingColumn,
  MeltingConfig,
  MeltingDaySummary,
  MeltingFill,
  MeltingState,
  MeltingStraddle,
  MeltingTag,
  MeltingTrade,
} from "@/types/melting";
import { cumulativeNet } from "@/lib/cumulative";

const REFRESH_MS = 10000;
const TAG_COLOR: Record<string, string> = { LOWER: "#b23c35", ATM: "#0f6b78", HIGHER: "#1b7a4b" };

function inr(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value < 0 ? "−" : ""}₹${Math.abs(Math.round(value)).toLocaleString("en-IN")}`;
}

function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function signed(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(digits)}`;
}

function tone(value: number | null | undefined): string | undefined {
  if (!value) return undefined;
  return value > 0 ? "var(--green)" : "var(--red)";
}

function clock(epoch: number | null | undefined, seconds = false): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleTimeString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    ...(seconds ? { second: "2-digit" } : {}),
    hour12: false,
  });
}

function dayLabel(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(`${iso}T00:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", weekday: "short", day: "2-digit", month: "short" });
}

function istTick(time: Time): string {
  if (typeof time !== "number") return String(time);
  return clock(time);
}

export default function MeltingStraddlesGapPage() {
  const [state, setState] = useState<MeltingState | null>(null);
  const [trades, setTrades] = useState<MeltingTrade[]>([]);
  const [days, setDays] = useState<MeltingDaySummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    try {
      const [s, t, d] = await Promise.all([getMeltingState(), getMeltingTrades(), getMeltingDays()]);
      setState(s);
      setTrades(t.trades);
      setDays(d.days);
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load Melting Straddles.");
    }
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  async function run(key: string, action: () => Promise<string>) {
    setBusy(key);
    try {
      setMessage(await action());
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Action failed.");
    } finally {
      setBusy(null);
    }
  }

  function enter(tag: MeltingTag) {
    const live = state?.mode === "live";
    if (!window.confirm(`${live ? "LIVE ORDERS: " : ""}Sell the ${tag} straddle now at market, without waiting for a signal?`)) return;
    run(`enter-${tag}`, async () => {
      const r = await enterMeltingNow(tag);
      return r.message ? `${r.status}: ${r.message}` : `${tag} straddle ${r.status}.`;
    });
  }

  function close(trade: MeltingTrade) {
    if (!window.confirm(`${trade.mode === "live" ? "LIVE ORDERS: " : ""}Buy back #${trade.id} ${trade.tag} ${trade.strike} straddle (${trade.lotsOpen} lots) now?`)) return;
    run(`close-${trade.id}`, async () => {
      const r = await closeMeltingTrade(trade.id);
      return `#${trade.id}: ${r.status}${r.message ? ` -- ${r.message}` : ""}`;
    });
  }

  function squareOff() {
    if (!window.confirm("Square off ALL open Melting straddles now?")) return;
    run("squareoff", async () => {
      const r = await squareOffMelting();
      return `Squared off ${r.closed} straddle(s).`;
    });
  }

  const config = state?.config;
  const closed = trades.filter((t) => t.status === "CLOSED");

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Droplets size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Melting Straddles - Gap
          </h1>
          <p>
            Intraday straddle decay: NIFTY on Fri/Mon/Tue, Sensex on Wed/Thu. Three straddles (ATM, ±200 / ±500) fixed at the open;
            sell when the combined premium prints a P&amp;F sell pattern below its VWAP; hard stop 10 / 30 pts, VWAP exit, book 25% at
            every 10 / 30 pts with a trailing stop, flat at 14:00. See docs/strategies/melting-straddles.md.
          </p>
          <p>
            <strong>Gap filter (the only difference from Melting Straddles):</strong> if NIFTY opens {config?.gapPercent ?? 0.3}% or more away from
            the previous close (up or down), the day is braked at 09:15 and no straddles are sold. Backtest Jan 2025 – Oct 2026, NIFTY Fri/Mon/Tue,
            4 lots: as built −₹91k (max drawdown −₹1.33L); with the 0.3% filter +₹35k (−₹48k); every threshold from 0.2% to 0.5% helped in both
            years. Paper only, NIFTY only (Sensex off — the filter was not tested there). Runs alongside Melting Straddles on its own trades.
          </p>
        </div>
        <div className="toolbar" style={{ alignItems: "center" }}>
          <span
            className={`status-live ${state?.mode === "live" ? "" : "on"}`}
            style={{ whiteSpace: "nowrap", ...(state?.mode === "live" ? { background: "#fde8e8", color: "var(--red)", borderColor: "var(--red)" } : {}) }}
          >
            {state?.mode === "live" ? "LIVE ORDERS" : "PAPER"}
          </span>
          <span className={`status-live ${config?.enabled ? "on" : ""}`} style={{ whiteSpace: "nowrap" }}>
            {config ? (config.enabled ? "Auto entry on" : "Auto entry paused") : "…"}
          </span>
          <button type="button" className="button secondary" onClick={load} style={{ whiteSpace: "nowrap" }}>
            <RefreshCw size={14} /> Refresh
          </button>
          <button type="button" className="button secondary" onClick={squareOff} disabled={!!busy || !state?.openTrades.length} style={{ whiteSpace: "nowrap" }}>
            <XOctagon size={14} /> Square off all
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}
      {state?.attention.length ? (
        <div className="alert error">
          <ShieldAlert size={14} style={{ verticalAlign: "-2px", marginRight: 6 }} />
          <strong>Manual action needed:</strong>{" "}
          {state.attention.map((t) => (
            <span key={t.id}>
              #{t.id} {t.needsAttention}{" "}
            </span>
          ))}
        </div>
      ) : null}

      <PaperTotals trades={closed} />

      <StatusStrip state={state} />

      <CollapsibleSection id="meltgap-straddles" title="Today's straddles" aside={<span className="pcr-oi-caption">combined premium = CE + PE · VWAP = VWAP(CE) + VWAP(PE)</span>}>
        {state?.day && state.straddles.length ? (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(300px, 100%), 1fr))", gap: 10 }}>
              {state.straddles.map((s) => (
                <StraddleCard
                  key={s.tag}
                  straddle={s}
                  config={config}
                  indexName={state.day!.indexName}
                  open={state.openTrades.find((t) => t.tag === s.tag) ?? null}
                  busy={busy === `enter-${s.tag}`}
                  onEnter={() => enter(s.tag)}
                />
              ))}
            </div>
            <PremiumChart straddles={state.straddles} trades={state.todayTrades} />
          </>
        ) : (
          <p className="pcr-oi-caption" style={{ margin: 0 }}>
            {state?.plan ?? "Loading…"} Straddles are fixed after the 09:15 candle on a trading day.
          </p>
        )}
      </CollapsibleSection>

      <CollapsibleSection id="meltgap-open" title={`Open positions (${state?.openTrades.length ?? 0})`}>
        {state?.openTrades.length ? (
          state.openTrades.map((t) => <OpenPosition key={t.id} trade={t} busy={busy === `close-${t.id}`} onClose={() => close(t)} />)
        ) : (
          <p className="pcr-oi-caption" style={{ margin: 0 }}>
            No open straddle. Entries {config?.entryStart}–{config?.entryEnd}, max {config?.maxOpen} at a time, {config?.lotsPerStraddle} lots each.
          </p>
        )}
      </CollapsibleSection>

      <CollapsibleSection id="meltgap-today" title={`Today's trades (${state?.todayTrades.length ?? 0})`}>
        <TradesTable trades={state?.todayTrades ?? []} />
      </CollapsibleSection>

      <CollapsibleSection id="meltgap-events" title={`Today's log (${state?.events.length ?? 0})`} defaultOpen={false}>
        <EventLog events={state?.events ?? []} />
      </CollapsibleSection>

      <CollapsibleSection id="meltgap-days" title="Daily P&L">
        <DaysTable days={days} />
        <div style={{ marginTop: 10 }}>
          <DailyTotalsTable rows={groupDailyTotals(closed, (t) => t.exitTime, (t) => t.grossPnl, (t) => t.netPnl)} />
        </div>
      </CollapsibleSection>

      <CollapsibleSection id="meltgap-history" title={`All trades (${trades.length})`} defaultOpen={false}>
        <TradesTable trades={trades} showDay />
      </CollapsibleSection>

      <SettingsSection config={config ?? null} onSaved={load} />
    </section>
  );
}

// Running totals of every closed paper trade, so the page answers "how is
// this doing overall" without adding up the daily table by hand.
function PaperTotals({ trades }: { trades: MeltingTrade[] }) {
  const paper = trades.filter((t) => t.mode === "paper");
  if (!paper.length) return null;
  const sum = (rows: MeltingTrade[], key: "grossPnl" | "charges" | "netPnl") => rows.reduce((a, t) => a + (t[key] ?? 0), 0);
  const gross = sum(paper, "grossPnl");
  const charges = sum(paper, "charges");
  const net = sum(paper, "netPnl");
  const wins = paper.filter((t) => t.netPnl > 0).length;
  const days = [...new Set(paper.map((t) => t.day))].sort();
  const byIndex = ["NIFTY", "SENSEX"]
    .map((ix) => ({ ix, rows: paper.filter((t) => t.indexName === ix) }))
    .filter((g) => g.rows.length);
  return (
    <div className="metric-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 150px), 1fr))" }}>
      <Metric label="Paper trades" value={String(paper.length)} caption={`${wins} won · ${days.length} days (${dayLabel(days[0])} – ${dayLabel(days[days.length - 1])})`} />
      <Metric label="Gross P&L" value={inr(gross)} caption="before charges" color={tone(gross)} />
      <Metric label="Charges" value={inr(charges)} caption={gross > 0 ? `${Math.round((charges / gross) * 100)}% of gross` : "brokerage, STT, exchange, GST"} />
      <Metric label="Net P&L" value={inr(net)} caption={`${inr(net / paper.length)} per trade`} color={tone(net)} />
      {byIndex.map(({ ix, rows }) => (
        <Metric
          key={ix}
          label={`${ix} net`}
          value={inr(sum(rows, "netPnl"))}
          caption={`${rows.length} trades · gross ${inr(sum(rows, "grossPnl"))} · charges ${inr(sum(rows, "charges"))}`}
          color={tone(sum(rows, "netPnl"))}
        />
      ))}
    </div>
  );
}

function Metric({ label, value, caption, color }: { label: string; value: string; caption?: string; color?: string }) {
  return (
    <div className="metric metric-compact" style={{ flex: "1 1 150px" }}>
      <span>{label}</span>
      <strong style={{ color }}>{value}</strong>
      {caption ? <span className="pcr-oi-caption"><ToneText text={caption} /></span> : null}
    </div>
  );
}

function StatusStrip({ state }: { state: MeltingState | null }) {
  const day = state?.day;
  const config = state?.config;
  const idx = day ? config?.[day.indexName] : null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
      <Metric
        label="Today"
        value={day ? `${day.indexName} · ${day.dte === 0 ? "expiry day" : `${day.dte}d to expiry`}` : "No trading"}
        caption={day ? `expiry ${dayLabel(day.expiry)} · lot ${day.lotSize}` : state?.plan ?? ""}
      />
      <Metric label="Index open (09:15)" value={day ? num(day.spotOpen) : "—"} caption={day ? `ATM ${day.atm.toLocaleString("en-IN")}` : ""} />
      <Metric
        label="Opening gap"
        value={day?.gapPercent != null ? `${day.gapPercent >= 0 ? "+" : ""}${day.gapPercent.toFixed(2)}%` : "—"}
        caption={
          !config?.gapFilter
            ? "gap filter off"
            : day?.gapPercent == null
              ? `skip the day at ±${(config.gapPercent ?? 0.3)}% or more`
              : Math.abs(day.gapPercent) >= (config.gapPercent ?? 0.3)
                ? `≥ ${(config.gapPercent ?? 0.3)}% — no trading today`
                : `under ${(config.gapPercent ?? 0.3)}% — trading allowed`
        }
        color={config?.gapFilter && day?.gapPercent != null && Math.abs(day.gapPercent) >= (config.gapPercent ?? 0.3) ? "var(--red)" : undefined}
      />
      <Metric
        label="Open / max"
        value={`${state?.openTrades.length ?? 0} / ${config?.maxOpen ?? "—"}`}
        caption={`${config?.lotsPerStraddle ?? "—"} lots per straddle`}
      />
      <Metric
        label="Hard stops today"
        value={`${day?.stops ?? 0} / ${config?.maxStops ?? "—"}`}
        caption={idx ? `stop ${idx.stopPoints} pts · book every ${idx.stepPoints}` : ""}
        color={(day?.stops ?? 0) >= (config?.maxStops ?? 3) ? "var(--red)" : undefined}
      />
      <Metric
        label="Entries"
        value={day?.brakedAt ? "Braked" : config?.enabled ? "Active" : "Paused"}
        caption={day?.brakedAt ? `${day.brakeReason} (${clock(day.brakedAt)})` : `${config?.entryStart ?? ""}–${config?.entryEnd ?? ""}, flat ${config?.exitTime ?? ""}`}
        color={day?.brakedAt ? "var(--red)" : undefined}
      />
      <Metric
        label="Day net"
        value={inr(state?.dayNet)}
        caption={idx && config ? `brake at −${idx.brakePoints} pts × ${config.lotsPerStraddle} lots = ${inr(-idx.brakePoints * idx.lotSize * config.lotsPerStraddle)}` : ""}
        color={tone(state?.dayNet)}
      />
      <Metric label="Market" value={state?.marketOpen ? "Open" : "Closed"} caption={`checked every 10 s · ${clock(state?.now, true)}`} />
    </div>
  );
}

function StraddleCard({
  straddle: s,
  config,
  indexName,
  open,
  busy,
  onEnter,
}: {
  straddle: MeltingStraddle;
  config?: MeltingConfig;
  indexName: string;
  open: MeltingTrade | null;
  busy: boolean;
  onEnter: () => void;
}) {
  const gap = s.vwap != null && s.combined != null ? s.vwap - s.combined : null;
  const stop = config?.[indexName as "NIFTY" | "SENSEX"]?.stopPoints ?? 10;
  const below = gap != null && gap > 0;
  const inRange = below && gap! <= stop;
  const lastSignal = s.signals[s.signals.length - 1];
  return (
    <div className="strategy-chart-card" style={{ borderTop: `3px solid ${TAG_COLOR[s.tag]}`, minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <strong>
          {s.tag} · {s.strike.toLocaleString("en-IN")}
        </strong>
        {open ? (
          <span className="status-live on" style={{ fontSize: 11 }}>
            #{open.id} open
          </span>
        ) : null}
        <button type="button" className="button secondary" onClick={onEnter} disabled={busy || !!open} style={{ marginLeft: "auto", padding: "2px 8px", fontSize: 12 }}>
          <Play size={12} /> Sell now
        </button>
      </div>
      <div style={{ marginTop: 6, fontSize: 12, display: "grid", gap: 3 }}>
        <Row label="Combined (1-min close)">
          <strong>{num(s.combined)}</strong> <span className="pcr-oi-caption">{clock(s.lastMinute)}</span>
        </Row>
        <Row label="VWAP">
          {num(s.vwap)} <span className="pcr-oi-caption">exch. ATP {num(s.live.exchangeVwap)}</span>
        </Row>
        <Row label="vs VWAP" color={gap == null ? undefined : below ? (inRange ? "var(--green)" : "var(--amber)") : "var(--red)"}>
          {gap == null ? "—" : below ? `${num(gap)} below${inRange ? " · in range" : ` · > ${stop} away`}` : `${num(-gap)} above · no entries`}
        </Row>
        <Row label="CE ltp · bid / ask">
          {num(s.live.ce.ltp)} · {num(s.live.ce.bid)} / {num(s.live.ce.ask)}
        </Row>
        <Row label="PE ltp · bid / ask">
          {num(s.live.pe.ltp)} · {num(s.live.pe.bid)} / {num(s.live.pe.ask)}
        </Row>
        <Row label="Live combined">{num(s.live.combined)}</Row>
        <Row label="P&F">
          {s.columns.length} cols · box ≈ {num(s.boxPoints)} pts
        </Row>
        <Row label="Last pattern">{lastSignal ? `${lastSignal.kind} @ ${num(lastSignal.price)} (${clock(lastSignal.time)})` : "—"}</Row>
      </div>
      <PnfMini columns={s.columns} vwap={s.vwap} />
    </div>
  );
}

function Row({ label, color, children }: { label: string; color?: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, borderBottom: "1px solid var(--line-soft)", paddingBottom: 2 }}>
      <span style={{ color: "var(--muted)" }}>{label}</span>
      <span style={{ textAlign: "right", color }}>{children}</span>
    </div>
  );
}

function PnfMini({ columns, vwap }: { columns: MeltingColumn[]; vwap: number | null }) {
  const cols = columns.slice(-36);
  if (!cols.length) return <p className="pcr-oi-caption">P&amp;F builds from the first minutes.</p>;
  const lo = Math.min(...cols.map((c) => c.bottom));
  const hi = Math.max(...cols.map((c) => c.top));
  const levels = hi - lo + 1;
  const cell = Math.max(3, Math.min(9, Math.floor(150 / levels)));
  const w = 10;
  const width = cols.length * w + 40;
  const height = levels * cell + 8;
  const y = (level: number) => 4 + (hi - level) * cell;
  const priceOf = (level: number) => {
    const c = cols.find((x) => x.top === level) ?? cols.find((x) => x.bottom === level);
    return c ? (c.top === level ? c.topPrice : c.bottomPrice) : null;
  };
  // VWAP as a level: interpolate on the log scale between known column prices
  const ref = cols[cols.length - 1];
  const boxLog = ref.top !== ref.bottom ? (Math.log(ref.topPrice) - Math.log(ref.bottomPrice)) / (ref.top - ref.bottom) : null;
  const vwapLevel = vwap && boxLog ? ref.bottom + (Math.log(vwap) - Math.log(ref.bottomPrice)) / boxLog : null;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet" style={{ width: "100%", height: 170, marginTop: 6, background: "var(--panel)" }} role="img" aria-label="P&F chart">
      {vwapLevel != null && vwapLevel >= lo - 2 && vwapLevel <= hi + 2 ? (
        <>
          <line x1={0} x2={width - 36} y1={y(vwapLevel) + cell / 2} y2={y(vwapLevel) + cell / 2} stroke="var(--amber)" strokeDasharray="3 2" />
          <text x={width - 34} y={y(vwapLevel) + cell / 2 + 3} fontSize={8} fill="var(--amber)">
            VWAP
          </text>
        </>
      ) : null}
      {cols.map((c, i) => {
        const cx = i * w + w / 2;
        const marks = [];
        for (let level = c.bottom; level <= c.top; level++) {
          const cy = y(level) + cell / 2;
          const r = cell / 2 - 0.5;
          marks.push(
            c.type === "X" ? (
              <g key={level} stroke="var(--green)" strokeWidth={1}>
                <line x1={cx - r} y1={cy - r} x2={cx + r} y2={cy + r} />
                <line x1={cx - r} y1={cy + r} x2={cx + r} y2={cy - r} />
              </g>
            ) : (
              <circle key={level} cx={cx} cy={cy} r={r} fill="none" stroke="var(--red)" strokeWidth={1} />
            ),
          );
        }
        return (
          <g key={c.index}>
            <title>{`${c.type} ${c.bottomPrice.toFixed(1)}–${c.topPrice.toFixed(1)} · ${clock(c.start)}–${clock(c.end)}${c.signals.length ? ` · ${c.signals.join(", ")}` : ""}`}</title>
            {marks}
            {c.signals.length ? (
              <text x={cx} y={y(c.bottom) + cell + 7} textAnchor="middle" fontSize={8} fill="var(--blue)" fontWeight={700}>
                ▼
              </text>
            ) : null}
          </g>
        );
      })}
      <text x={width - 34} y={10} fontSize={8} fill="var(--muted)">
        {num(priceOf(hi), 1)}
      </text>
      <text x={width - 34} y={height - 2} fontSize={8} fill="var(--muted)">
        {num(priceOf(lo), 1)}
      </text>
    </svg>
  );
}

function meltingNotes(trades: MeltingTrade[]): TradeNote[] {
  return trades.flatMap((t) =>
    (t.fills ?? []).map((f) =>
      f.side === "SELL"
        ? {
            time: f.time,
            kind: "entry" as const,
            label: `#${t.id} sell`,
            color: "#b23c35",
            title: `Entry #${t.id} · sold ${t.tag} ${t.strike} straddle × ${f.lots} lots @ ${num(f.combined)}`,
            lines: [
              `${istTime(f.time)} · CE ${num(f.cePrice)} + PE ${num(f.pePrice)} · ${t.mode}`,
              t.trigger === "manual" ? "Why: entered manually (Sell now)" : `Why: ${t.signal} on the P&F chart below VWAP ${num(t.signalVwap)} (signal close ${num(t.signalPrice)})`,
              `Stop ${num(t.initialSl)} · books every ${t.step} pts`,
            ],
          }
        : {
            time: f.time,
            kind: f.action === "EXIT" ? ("exit" as const) : ("adjust" as const),
            label: f.action,
            color: (f.points ?? 0) >= 0 ? "#1b7a4b" : "#b23c35",
            title: `${f.action === "EXIT" ? "Exit" : "Booked " + f.lots + " lot"} #${t.id} · ${inr(f.pnl)}`,
            lines: [`${istTime(f.time)} · bought back @ ${num(f.combined)} (CE ${num(f.cePrice)} + PE ${num(f.pePrice)})`, `Why: ${f.reason}`, `${signed((f.points ?? 0) / Math.max(f.lots, 1))} pts/lot`],
          },
    ),
  );
}

function PremiumChart({ straddles, trades }: { straddles: MeltingStraddle[]; trades: MeltingTrade[] }) {
  const [tag, setTag] = useState<MeltingTag>("ATM");
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<{ combined: ISeriesApi<"Line">; vwap: ISeriesApi<"Line"> } | null>(null);
  const [handles, setHandles] = useState<{ chart: IChartApi; series: ISeriesApi<"Line"> } | null>(null);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#17212b" },
      grid: { vertLines: { color: "#e8edeb" }, horzLines: { color: "#e8edeb" } },
      width: containerRef.current.clientWidth,
      height: 260,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (t: Time) => istTick(t) },
      localization: { timeFormatter: (t: Time) => istTick(t) },
    });
    const combined = chart.addSeries(LineSeries, { color: "#0f6b78", lineWidth: 2, title: "Combined" });
    const vwap = chart.addSeries(LineSeries, { color: "#b7791f", lineWidth: 1, lineStyle: 2, title: "VWAP" });
    seriesRef.current = { combined, vwap };
    chartRef.current = chart;
    setHandles({ chart, series: combined });
    const observer = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      setHandles(null);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  const current = straddles.find((x) => x.tag === tag);
  const barTimes = useMemo(() => (current?.series ?? []).map((p) => p.time), [current]);
  const notes = useMemo(() => meltingNotes(trades.filter((t) => t.tag === tag)), [trades, tag]);
  const tooltip = useTradeMarkers(handles?.chart ?? null, handles?.series ?? null, notes, 60, barTimes);

  useEffect(() => {
    const s = straddles.find((x) => x.tag === tag);
    if (!seriesRef.current || !s) return;
    seriesRef.current.combined.applyOptions({ color: TAG_COLOR[tag] });
    seriesRef.current.combined.setData(s.series.map((p) => ({ time: p.time as UTCTimestamp, value: p.combined })));
    seriesRef.current.vwap.setData(s.series.filter((p) => p.vwap != null).map((p) => ({ time: p.time as UTCTimestamp, value: p.vwap as number })));
    chartRef.current?.timeScale().fitContent();
  }, [straddles, trades, tag]);

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
        {straddles.map((s) => (
          <button
            key={s.tag}
            type="button"
            className={`button ${s.tag === tag ? "" : "secondary"}`}
            style={{ padding: "2px 10px", fontSize: 12 }}
            onClick={() => setTag(s.tag)}
          >
            {s.tag} {s.strike}
          </button>
        ))}
        <span className="pcr-oi-caption" style={{ alignSelf: "center" }}>
          combined premium vs VWAP · ▲ entries, ● bookings, ▼ exits -- hover for the reason
        </span>
      </div>
      <div style={{ position: "relative" }}>
        <div ref={containerRef} style={{ width: "100%", height: 260 }} />
        {tooltip}
      </div>
    </div>
  );
}

function OpenPosition({ trade: t, busy, onClose }: { trade: MeltingTrade; busy: boolean; onClose: () => void }) {
  const live = t.lastPrice ?? t.entryPrice;
  const lo = t.entryPrice - 3 * t.step;
  const hi = t.sl;
  const pos = (v: number) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
  return (
    <div className="strategy-chart-card" style={{ borderLeft: `3px solid ${TAG_COLOR[t.tag]}` }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "baseline" }}>
        <strong>
          #{t.id} · SHORT {t.tag} {t.strike.toLocaleString("en-IN")} straddle · {t.lotsOpen}/{t.lots} lots open
        </strong>
        <span className="pcr-oi-caption">
          {t.mode.toUpperCase()} · {t.signal} at {clock(t.signalTime)} ({num(t.signalPrice)} vs VWAP {num(t.signalVwap)}) · entered {clock(t.entryTime, true)}
        </span>
        <button type="button" className="button secondary" onClick={onClose} disabled={busy} style={{ marginLeft: "auto" }}>
          <SquareArrowOutUpRight size={14} /> Buy back now
        </button>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 10 }}>
        <Metric label="Entry (sold)" value={num(t.entryPrice)} caption={`CE ${num(t.entryCe)} + PE ${num(t.entryPe)} · ${inr(t.premiumCollected)}`} />
        <Metric label="Live combined" value={num(live)} caption={`CE ${num(t.lastCe)} + PE ${num(t.lastPe)} · ${clock(t.lastUpdate, true)}`} />
        <Metric label="Decay" value={`${signed(t.decay)} pts`} caption={`best ${signed(t.mfe)} · worst ${signed(t.mae)}`} color={tone(t.decay)} />
        <Metric label="Stop" value={num(t.sl)} caption={t.hits ? `trailed after ${t.hits} booking${t.hits > 1 ? "s" : ""} (initial ${num(t.initialSl)})` : "hard stop"} color="var(--red)" />
        <Metric label="Next booking" value={t.nextTarget != null ? num(t.nextTarget) : "runner"} caption={t.nextTarget != null ? `+${(t.hits + 1) * t.step} pts decay` : "exits on P&F reversal / VWAP / 14:00"} color="var(--green)" />
        <Metric label="VWAP (last minute)" value={num(t.lastVwap)} caption="close ≥ VWAP exits everything" />
        <Metric label="P&L" value={inr(t.grossPnl)} caption={`booked ${inr(t.realizedPnl)} · open ${inr(t.unrealizedPnl)} · net ${inr(t.netPnl)}`} color={tone(t.grossPnl)} />
        <Metric label="Held" value={`${t.minutesHeld} min`} caption={`charges so far ${inr(t.charges)}`} />
      </div>
      <div style={{ marginTop: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
          <span style={{ color: "var(--green)" }}>+{3 * t.step} pts ({num(lo)})</span>
          <span>combined {num(live)}</span>
          <span style={{ color: "var(--red)" }}>stop {num(hi)}</span>
        </div>
        <div style={{ position: "relative", height: 10, borderRadius: 5, background: "var(--line-soft)", marginTop: 4 }}>
          {[1, 2, 3].map((k) => (
            <div key={k} title={`book ${k}`} style={{ position: "absolute", left: `${pos(t.entryPrice - k * t.step)}%`, top: -2, width: 2, height: 14, background: "var(--green)", opacity: k <= t.hits ? 0.35 : 1 }} />
          ))}
          <div title="entry" style={{ position: "absolute", left: `${pos(t.entryPrice)}%`, top: -3, width: 2, height: 16, background: "var(--muted)" }} />
          <div style={{ position: "absolute", left: `calc(${pos(live)}% - 6px)`, top: -1, width: 12, height: 12, borderRadius: 6, background: live <= t.entryPrice ? "var(--green)" : "var(--red)" }} />
        </div>
      </div>
      <FillsTable fills={t.fills ?? []} entry={t.entryPrice} />
    </div>
  );
}

function FillsTable({ fills, entry }: { fills: MeltingFill[]; entry: number }) {
  if (!fills.length) return null;
  return (
    <div style={{ overflowX: "auto", marginTop: 10, width: 0, minWidth: "100%" }}>
      <table style={{ fontSize: 12 }}>
        <thead>
          <tr>
            <th>Time</th>
            <th>Action</th>
            <th>Lots / qty</th>
            <th>CE fill (bid/ask/ltp)</th>
            <th>PE fill (bid/ask/ltp)</th>
            <th>Combined</th>
            <th>Trigger price</th>
            <th>Slippage</th>
            <th>Pts/lot</th>
            <th>P&amp;L</th>
            <th>Charges</th>
            <th>Reason</th>
            <th>Orders</th>
          </tr>
        </thead>
        <tbody>
          {fills.map((f) => (
            <tr key={f.id}>
              <td style={{ whiteSpace: "nowrap" }}>{clock(f.time, true)}</td>
              <td>
                {f.side} {f.action}
              </td>
              <td>
                {f.lots} / {f.quantity}
              </td>
              <td style={{ whiteSpace: "nowrap" }}>
                <strong>{num(f.cePrice)}</strong> <span className="pcr-oi-caption">({num(f.ceBid)}/{num(f.ceAsk)}/{num(f.ceLtp)})</span>
              </td>
              <td style={{ whiteSpace: "nowrap" }}>
                <strong>{num(f.pePrice)}</strong> <span className="pcr-oi-caption">({num(f.peBid)}/{num(f.peAsk)}/{num(f.peLtp)})</span>
              </td>
              <td>{num(f.combined)}</td>
              <td>{num(f.referencePrice)}</td>
              <td style={{ color: f.slippage == null ? undefined : (f.side === "SELL" ? f.slippage >= 0 : f.slippage <= 0) ? "var(--green)" : "var(--red)" }}>{signed(f.slippage)}</td>
              <td style={{ color: tone(f.side === "BUY" ? entry - f.combined : null) }}>{f.side === "BUY" ? signed(entry - f.combined) : "—"}</td>
              <td style={{ color: tone(f.pnl) }}>{f.pnl == null ? "—" : inr(f.pnl)}</td>
              <td>{inr(f.charges)}</td>
              <td>{f.reason}</td>
              <td className="pcr-oi-caption" style={{ whiteSpace: "nowrap" }}>
                {f.mode.toUpperCase()} {f.orderStatus ?? ""}
                {f.ceOrderId || f.peOrderId ? ` · ${f.ceOrderId ?? "—"} / ${f.peOrderId ?? "—"}` : ""}
                {f.note ? ` · ${f.note}` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TradesTable({ trades, showDay = false }: { trades: MeltingTrade[]; showDay?: boolean }) {
  const [expanded, setExpanded] = useState<number | null>(null);
  if (!trades.length) return <p className="pcr-oi-caption" style={{ margin: 0 }}>No trades yet.</p>;
  const totals = trades.reduce((a, t) => ({ gross: a.gross + t.grossPnl, charges: a.charges + t.charges, net: a.net + t.netPnl, pts: a.pts + t.pointsPerLot }), {
    gross: 0,
    charges: 0,
    net: 0,
    pts: 0,
  });
  const wins = trades.filter((t) => t.status === "CLOSED" && t.netPnl > 0).length;
  const closedCount = trades.filter((t) => t.status === "CLOSED").length;
  return (
    <div style={{ overflowX: "auto", width: 0, minWidth: "100%" }}>
      <p className="pcr-oi-caption" style={{ marginTop: 0 }}>
        {trades.length} trades · {closedCount ? `${Math.round((wins / closedCount) * 100)}% winners` : "—"} · {signed(totals.pts)} pts/lot · gross {inr(totals.gross)} ·
        charges {inr(totals.charges)} · <strong style={{ color: tone(totals.net) }}>net {inr(totals.net)}</strong> · click a row for every fill
      </p>
      <table style={{ fontSize: 12 }}>
        <thead>
          <tr>
            <th>#</th>
            {showDay ? <th>Day</th> : null}
            <th>Index</th>
            <th>Straddle</th>
            <th>Mode</th>
            <th>Signal</th>
            <th>Entry</th>
            <th>Sold</th>
            <th>Lots</th>
            <th>Bookings</th>
            <th>Exit</th>
            <th>Reason</th>
            <th>Held</th>
            <th>Best / worst</th>
            <th>Pts/lot</th>
            <th>Gross</th>
            <th>Charges</th>
            <th>Net</th>
            <th>Cumulative net</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <Fragment key={t.id}>
              <tr onClick={() => setExpanded(expanded === t.id ? null : t.id)} style={{ cursor: "pointer", background: t.needsAttention ? "#fdecec" : undefined }}>
                <td>{t.id}</td>
                {showDay ? <td>{dayLabel(t.day)}</td> : null}
                <td>
                  {t.indexName} <span className="pcr-oi-caption">{t.dte === 0 ? "exp" : `${t.dte}d`}</span>
                </td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <span style={{ color: TAG_COLOR[t.tag], fontWeight: 600 }}>{t.tag}</span> {t.strike}
                </td>
                <td>{t.mode}</td>
                <td>
                  {t.signal}
                  {t.trigger === "manual" ? " (manual)" : ""}
                </td>
                <td>{clock(t.entryTime)}</td>
                <td>
                  {num(t.entryPrice)} <span className="pcr-oi-caption">VWAP {num(t.signalVwap)}</span>
                </td>
                <td>
                  {t.lots}
                  {t.status === "OPEN" ? ` (${t.lotsOpen} open)` : ""}
                </td>
                <td>{t.hits}</td>
                <td>{t.status === "OPEN" ? "open" : clock(t.exitTime)}</td>
                <td>{t.exitReason ?? "—"}</td>
                <td>{t.minutesHeld}m</td>
                <td>
                  {signed(t.mfe)} / {signed(t.mae)}
                </td>
                <td style={{ color: tone(t.pointsPerLot) }}>{signed(t.pointsPerLot)}</td>
                <td style={{ color: tone(t.grossPnl) }}>{inr(t.grossPnl)}</td>
                <td>{inr(t.charges)}</td>
                <td style={{ color: tone(t.netPnl) }}>
                  <strong>{inr(t.netPnl)}</strong>
                </td>
                <td style={{ color: (cumulativeNet(trades, (x) => x.id, (x) => x.entryTime, (x) => x.netPnl, (x) => String(x.status ?? "closed").toUpperCase() === "CLOSED").get(t.id) ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>{cumulativeNet(trades, (x) => x.id, (x) => x.entryTime, (x) => x.netPnl, (x) => String(x.status ?? "closed").toUpperCase() === "CLOSED").get(t.id) != null ? inr(cumulativeNet(trades, (x) => x.id, (x) => x.entryTime, (x) => x.netPnl, (x) => String(x.status ?? "closed").toUpperCase() === "CLOSED").get(t.id) as number) : "—"}</td>
              </tr>
              {expanded === t.id ? (
                <tr>
                  <td colSpan={showDay ? 19 : 18} style={{ background: "var(--panel)" }}>
                    {t.needsAttention ? <div className="alert error">{t.needsAttention}</div> : null}
                    <div className="pcr-oi-caption">
                      CE {t.ceSecurityId} / PE {t.peSecurityId} ({t.exchangeSegment}) · expiry {t.expiry} · lot size {t.lotSize} · initial stop {num(t.initialSl)} · final stop{" "}
                      {num(t.sl)} · booking step {t.step} pts · premium collected {inr(t.premiumCollected)}
                    </div>
                    <FillsTable fills={t.fills ?? []} entry={t.entryPrice} />
                  </td>
                </tr>
              ) : null}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EventLog({ events }: { events: MeltingState["events"] }) {
  if (!events.length) return <p className="pcr-oi-caption" style={{ margin: 0 }}>Nothing yet today.</p>;
  return (
    <table style={{ fontSize: 12 }}>
      <tbody>
        {events.map((e) => (
          <tr key={e.id}>
            <td style={{ whiteSpace: "nowrap" }}>{clock(e.time, true)}</td>
            <td style={{ color: e.kind.includes("error") || e.kind === "brake" ? "var(--red)" : undefined }}>{e.kind}</td>
            <td>{e.text}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DaysTable({ days }: { days: MeltingDaySummary[] }) {
  if (!days.length) return <p className="pcr-oi-caption" style={{ margin: 0 }}>No trading days yet.</p>;
  let running = 0;
  const rows = [...days].reverse().map((d) => {
    running += d.netPnl;
    return { ...d, cumulative: running };
  });
  return (
    <div style={{ overflowX: "auto", width: 0, minWidth: "100%" }}>
      <table style={{ fontSize: 12 }}>
        <thead>
          <tr>
            <th>Day</th>
            <th>Index</th>
            <th>Expiry</th>
            <th>Open</th>
            <th>Straddles</th>
            <th>Trades</th>
            <th>Winners</th>
            <th>Stops</th>
            <th>Gap</th>
            <th>Brake</th>
            <th>Pts/lot</th>
            <th>Gross</th>
            <th>Charges</th>
            <th>Net</th>
            <th>Cumulative</th>
          </tr>
        </thead>
        <tbody>
          {rows.reverse().map((d) => (
            <tr key={d.day}>
              <td>{dayLabel(d.day)}</td>
              <td>{d.indexName}</td>
              <td>
                {dayLabel(d.expiry)} <span className="pcr-oi-caption">({d.dte === 0 ? "expiry day" : `${d.dte}d`})</span>
              </td>
              <td>{num(d.spotOpen)}</td>
              <td className="pcr-oi-caption">{Object.values(d.straddles).map((s) => s.strike).join(" / ")}</td>
              <td>{d.trades}</td>
              <td>{d.wins}</td>
              <td>{d.stops}</td>
              <td>{d.gapPercent != null ? `${d.gapPercent >= 0 ? "+" : ""}${d.gapPercent.toFixed(2)}%` : "—"}</td>
              <td className="pcr-oi-caption">{d.brakeReason ?? "—"}</td>
              <td style={{ color: tone(d.points) }}>{signed(d.points)}</td>
              <td style={{ color: tone(d.grossPnl) }}>{inr(d.grossPnl)}</td>
              <td>{inr(d.charges)}</td>
              <td style={{ color: tone(d.netPnl) }}>
                <strong>{inr(d.netPnl)}</strong>
              </td>
              <td style={{ color: tone(d.cumulative) }}>{inr(d.cumulative)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const COMMON_FIELDS: { key: string; label: string; hint: string }[] = [
  { key: "lotsPerStraddle", label: "Lots per straddle", hint: "4 → 25% = 1 lot" },
  { key: "maxOpen", label: "Max straddles open", hint: "2 (tranche A + B)" },
  { key: "boxPercent", label: "P&F box %", hint: "0.5" },
  { key: "reversal", label: "Reversal (boxes)", hint: "3" },
  { key: "entryStart", label: "Entries from", hint: "09:30" },
  { key: "entryEnd", label: "Entries until", hint: "13:45" },
  { key: "exitTime", label: "Flat at", hint: "14:00" },
  { key: "maxStops", label: "Brake after hard stops", hint: "3" },
  { key: "patterns", label: "Sell patterns", hint: "DOUBLE_BOTTOM,TURTLE,ANCHOR_FT,HIGH_POLE_FT" },
  { key: "turtleLookback", label: "Turtle lookback (cols)", hint: "5" },
  { key: "anchorLookback", label: "Anchor lookback (cols)", hint: "10" },
  { key: "tallMultiple", label: "Tall column (× median)", hint: "2" },
  { key: "signalMaxAgeMinutes", label: "Signal max age (min)", hint: "2" },
  { key: "gapPercent", label: "Skip day if gap ≥ (%)", hint: "0.3 (tested 0.2–0.5)" },
];
const INDEX_FIELDS: { key: string; label: string }[] = [
  { key: "tradeDays", label: "Trade days" },
  { key: "maxDaysToExpiry", label: "Max days to expiry" },
  { key: "strikeStep", label: "ATM rounding" },
  { key: "offset", label: "Higher/Lower offset" },
  { key: "stopPoints", label: "Hard stop (pts)" },
  { key: "stepPoints", label: "Booking step (pts)" },
  { key: "brakePoints", label: "Daily brake (pts/lot)" },
];

function SettingsSection({ config, onSaved }: { config: MeltingConfig | null; onSaved: () => void }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!config) return;
    const d: Record<string, string> = {};
    for (const f of COMMON_FIELDS) d[f.key] = String((config as unknown as Record<string, unknown>)[f.key] ?? "");
    for (const idx of ["NIFTY", "SENSEX"] as const) for (const f of INDEX_FIELDS) d[`${idx}.${f.key}`] = String((config[idx] as unknown as Record<string, unknown>)[f.key] ?? "");
    setDraft(d);
  }, [config]);
  if (!config) return null;

  async function save(extra?: Record<string, unknown>) {
    setSaving(true);
    setError(null);
    try {
      if (extra) {
        await updateMeltingConfig(extra);
      } else {
        const body: Record<string, unknown> = {};
        const textKeys = new Set(["entryStart", "entryEnd", "exitTime", "patterns", "tradeDays"]);
        for (const f of COMMON_FIELDS) body[f.key] = textKeys.has(f.key) ? draft[f.key] : Number(draft[f.key]);
        for (const idx of ["NIFTY", "SENSEX"]) {
          body[idx] = Object.fromEntries(INDEX_FIELDS.map((f) => [f.key, textKeys.has(f.key) ? draft[`${idx}.${f.key}`] : Number(draft[`${idx}.${f.key}`])]));
        }
        await updateMeltingConfig(body);
      }
      onSaved();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  const input = (key: string, width = 110) => (
    <input value={draft[key] ?? ""} onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))} style={{ width, fontSize: 13, padding: "3px 6px" }} />
  );

  return (
    <CollapsibleSection id="meltgap-settings" title="Settings" defaultOpen={false}>
      {error ? <div className="alert error">{error}</div> : null}
      <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", marginBottom: 12, fontSize: 13 }}>
        <label style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={config.enabled} onChange={(e) => save({ enabled: e.target.checked })} disabled={saving} />
          Automatic entries
        </label>
        <label style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={config.gapFilter} onChange={(e) => save({ gapFilter: e.target.checked })} disabled={saving} />
          Gap filter
        </label>
        <span className="pcr-oi-caption">Paper only — this page never places orders.</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 12 }}>
        {COMMON_FIELDS.map((f) => (
          <label key={f.key} style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12 }}>
            <span style={{ color: "var(--muted)", fontWeight: 600 }}>{f.label}</span>
            {input(f.key, f.key === "patterns" ? 300 : 110)}
            <span className="pcr-oi-caption">{f.hint}</span>
          </label>
        ))}
      </div>
      <div style={{ overflowX: "auto", marginTop: 14, width: 0, minWidth: "100%" }}>
        <table style={{ fontSize: 12 }}>
          <thead>
            <tr>
              <th />
              {INDEX_FIELDS.map((f) => (
                <th key={f.key}>{f.label}</th>
              ))}
              <th>On</th>
            </tr>
          </thead>
          <tbody>
            {(["NIFTY", "SENSEX"] as const).map((idx) => (
              <tr key={idx}>
                <td>
                  <strong>{idx}</strong> <span className="pcr-oi-caption">lot {config[idx].lotSize}</span>
                </td>
                {INDEX_FIELDS.map((f) => (
                  <td key={f.key}>{input(`${idx}.${f.key}`, f.key === "tradeDays" ? 110 : 70)}</td>
                ))}
                <td>
                  <input type="checkbox" checked={config[idx].enabled} onChange={(e) => save({ [idx]: { enabled: e.target.checked } })} disabled={saving} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ marginTop: 12 }}>
        <button type="button" className="button" onClick={() => save()} disabled={saving}>
          <Save size={14} /> Save settings
        </button>
      </div>
    </CollapsibleSection>
  );
}
