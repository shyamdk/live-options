"use client";

import { Play, RefreshCw, Save, SquareArrowOutUpRight, Turtle } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import AlarmOverlay from "@/components/AlarmOverlay";
import CollapsibleSection from "@/components/CollapsibleSection";
import { DailyTotalsTable, groupDailyTotals } from "@/components/DailyTotals";
import {
  acknowledgeTurtleA1Alarm as acknowledgeTurtleAlarm,
  closeTurtleA1Trade as closeTurtleTrade,
  enterTurtleA1Now as enterTurtleNow,
  getTurtleA1Alarms as getTurtleAlarms,
  getTurtleA1State as getTurtleState,
  getTurtleA1Trades as getTurtleTrades,
  updateTurtleA1Config as updateTurtleConfig,
} from "@/lib/api";
import { MarkerTooltip, TradeNote } from "@/components/TradeMarkers";
import ToneText from "@/components/ToneText";
import type { PnfColumn, PnfSignal, TurtleAlarm, TurtleConfig, TurtleState, TurtleTrade } from "@/types/turtle";

const REFRESH_MS = 20000;
const EXIT_LABEL: Record<string, string> = {
  profit_target: "75% decay target",
  trend_flip: "P&F RSI < 50",
  calendar: "3-day calendar rule",
  manual: "Closed manually",
};

function inr(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value < 0 ? "−" : ""}₹${Math.abs(Math.round(value)).toLocaleString("en-IN")}`;
}

function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function tone(value: number | null | undefined): string | undefined {
  if (!value) return undefined;
  return value > 0 ? "var(--green)" : "var(--red)";
}

function ist(epoch: number | null | undefined): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export default function DefineTurtleA1Page() {
  const [state, setState] = useState<TurtleState | null>(null);
  const [trades, setTrades] = useState<TurtleTrade[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    try {
      const [s, t] = await Promise.all([getTurtleState(), getTurtleTrades()]);
      setState(s);
      setTrades(t.trades);
      setError(s.error ?? null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load Define Turtle.");
    }
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  async function enterNow() {
    const live = state?.config.mode === "live" && state?.config.liveOrdersAllowed;
    if (!window.confirm(`${live ? "LIVE ORDERS: " : ""}Open a ${live ? "REAL" : "paper"} put credit spread now, without waiting for a Turtle Follow-Through signal?`)) return;
    setBusy("enter");
    try {
      const r = await enterTurtleNow();
      setMessage(r.message ? `${r.status}: ${r.message}` : `Spread ${r.status}.`);
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Entry failed.");
    } finally {
      setBusy(null);
    }
  }

  async function closeTrade(trade: TurtleTrade) {
    if (!window.confirm(`${trade.mode === "live" ? "LIVE ORDERS: buy back" : "Close"} spread #${trade.id} now (${trade.mode === "live" ? "real Dhan market orders" : "paper"})?`)) return;
    setBusy(`close-${trade.id}`);
    try {
      const r = await closeTurtleTrade(trade.id);
      setMessage(`Spread #${trade.id}: ${r.status}`);
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Close failed.");
    } finally {
      setBusy(null);
    }
  }

  const config = state?.config;
  const liveNow = config?.mode === "live" && config?.liveOrdersAllowed;
  const attention = (state?.openTrades ?? []).filter((t) => t.needsAttention);
  const closed = trades.filter((t) => t.status === "CLOSED");

  return (
    <section className="page">
      <AlarmOverlay title="Define Turtle A1 alarm" alarms={state?.alarms ?? []} acknowledge={acknowledgeTurtleAlarm} onAcknowledged={load} />
      <header className="page-header">
        <div>
          <h1>
            <Turtle size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Define Turtle A1
          </h1>
          <p>
            NIFTY Point &amp; Figure RSI(14) &gt; 50 + Turtle Follow-Through → next-week put credit spread (sell ATM, buy 300
            lower). Exits: 75% decay, RSI &lt; 50, or 3 days before expiry. Same rules as Define Turtle, with its own trades (the
            Define Turtle page stays paper). Paper by default; in Live mode new spreads place real Angel One MARKET orders (CARRYFORWARD,
            held overnight; hedge bought first, short bought back first). Market data from Dhan -- see docs/strategies/define-turtle.md.
          </p>
        </div>
        <div className="toolbar" style={{ alignItems: "center" }}>
          <span
            className={`status-live ${liveNow ? "" : "on"}`}
            style={{ whiteSpace: "nowrap", ...(liveNow ? { background: "#fde8e8", color: "var(--red)", borderColor: "var(--red)" } : {}) }}
          >
            {liveNow ? `LIVE ORDERS · ${config?.broker === "angel" ? "Angel One" : "Dhan"}` : "PAPER"}
          </span>
          <span className={`status-live ${config?.enabled ? "on" : ""}`} style={{ whiteSpace: "nowrap" }}>
            {config?.enabled ? "Auto entry on" : "Auto entry paused"}
          </span>
          <button type="button" className="button secondary" onClick={load} style={{ whiteSpace: "nowrap" }}>
            <RefreshCw size={14} /> Refresh
          </button>
          <button type="button" className="button" onClick={enterNow} disabled={!!busy} style={{ whiteSpace: "nowrap" }}>
            <Play size={14} /> {busy === "enter" ? "Entering…" : "Enter now"}
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}
      {attention.length ? (
        <div className="alert error">
          <strong>Live order needs attention:</strong>{" "}
          {attention.map((t) => (
            <span key={t.id}>
              #{t.id} {t.needsAttention}{" "}
            </span>
          ))}
        </div>
      ) : null}

      <StatusStrip state={state} />

      <CollapsibleSection
        id="turtlea1-chart"
        title="Point & Figure (NIFTY, 1-min closes)"
        aside={
          state?.chart ? (
            <span className="pcr-oi-caption">
              {config?.boxPercent}% box (≈{num(state.chart.boxPoints, 1)} pts) · {config?.reversal}-box reversal · last{" "}
              {Math.min(state.chart.columns.length, VISIBLE_COLUMNS)} columns
            </span>
          ) : null
        }
      >
        {state?.chart && config ? <PnfChart columns={state.chart.columns} signals={state.chart.signals} config={config} trades={trades} /> : <p className="pcr-oi-caption">Loading…</p>}
      </CollapsibleSection>

      <CollapsibleSection id="turtlea1-open" title={`Open spread (${state?.openTrades.length ?? 0})`}>
        {state?.openTrades.length ? (
          state.openTrades.map((trade) => (
            <OpenSpread key={trade.id} trade={trade} config={config} busy={busy === `close-${trade.id}`} onClose={() => closeTrade(trade)} />
          ))
        ) : (
          <p className="pcr-oi-caption" style={{ margin: 0 }}>
            No open spread. The next one opens on a Turtle Follow-Through Bullish with P&amp;F RSI above {config?.rsiThreshold ?? 50}.
          </p>
        )}
      </CollapsibleSection>

      <CollapsibleSection id="turtlea1-pnl" title="Daily P&L">
        <DailyTotalsTable rows={groupDailyTotals(closed, (t) => t.exitTime, (t) => t.grossPnl, (t) => t.netPnl)} cumulative />
      </CollapsibleSection>

      <CollapsibleSection id="turtlea1-trades" title={`All trades (${trades.length})`} defaultOpen={false}>
        <TradesTable trades={trades} />
      </CollapsibleSection>

      <AlarmHistory />
      <SettingsSection config={config ?? null} onSaved={load} />
    </section>
  );
}

function StatusStrip({ state }: { state: TurtleState | null }) {
  const rsi = state?.chart?.rsi;
  const threshold = state?.config.rsiThreshold ?? 50;
  const ft = state?.lastFollowThrough;
  const metrics = [
    { label: "NIFTY (last 1-min close)", value: num(state?.lastCandle?.close), caption: state?.lastCandle ? ist(state.lastCandle.time) : "" },
    {
      label: "P&F RSI(14)",
      value: num(rsi),
      caption: rsi == null ? "" : rsi > threshold ? `above ${threshold} -- trend filter ON` : `at/below ${threshold} -- no entries`,
      color: rsi == null ? undefined : rsi > threshold ? "var(--green)" : "var(--red)",
    },
    {
      label: "Last Follow-Through",
      value: ft ? `${num(ft.price, 0)} @ ${ist(ft.time)}` : "—",
      caption: ft ? `RSI then ${num(ft.rsi)}` : "",
    },
    { label: "Next-week expiry", value: state?.nextWeekExpiry ?? "—", caption: "spreads go on this series" },
    { label: "Size", value: `${state?.config.lots ?? "—"} lots`, caption: `₹${(state?.config.capitalPerLot ?? 150000).toLocaleString("en-IN")} per lot of ${inr(state?.config.capital)}` },
    { label: "Market", value: state?.marketOpen ? "Open" : "Closed", caption: "signals are checked every 1-min close" },
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

const VISIBLE_COLUMNS = 45;

function turtleNotes(t: TurtleTrade): TradeNote[] {
  const notes: TradeNote[] = [
    {
      time: t.entryTime,
      kind: "entry",
      label: "IN",
      color: "var(--blue)",
      title: `Entry #${t.id} · put credit spread · exp ${t.expiry}`,
      lines: [
        `${ist(t.entryTime)} · NIFTY ${num(t.spot, 0)} · sold ${t.shortStrike} PE @ ${num(t.shortEntry)}, bought ${t.longStrike} PE @ ${num(t.longEntry)} · ${t.lots} lots`,
        t.trigger === "manual"
          ? "Why: entered manually"
          : `Why: Turtle Follow-Through on the P&F chart${t.signalTime ? ` at ${ist(t.signalTime)}` : ""} with RSI ${num(t.signalRsi)} above the threshold`,
        `Credit ${num(t.creditPoints)} pts (${inr(t.credit)}) · max loss ${inr(t.maxLoss)}`,
      ],
    },
  ];
  if (t.exitTime) {
    notes.push({
      time: t.exitTime,
      kind: "exit",
      label: "OUT",
      color: t.netPnl >= 0 ? "var(--green)" : "var(--red)",
      title: `Exit #${t.id} · ${inr(t.netPnl)} net`,
      lines: [
        `${ist(t.exitTime)} · bought back ${t.shortStrike} PE @ ${num(t.shortExit)}, sold ${t.longStrike} PE @ ${num(t.longExit)}`,
        `Why: ${EXIT_LABEL[t.exitReason ?? ""] ?? t.exitReason ?? "—"}`,
      ],
    });
  }
  return notes;
}

function PnfChart({ columns: allColumns, signals, config, trades }: { columns: PnfColumn[]; signals: PnfSignal[]; config: TurtleConfig; trades: TurtleTrade[] }) {
  const [hover, setHover] = useState<PnfColumn | null>(null);
  const [tip, setTip] = useState<{ x: number; y: number; notes: TradeNote[] } | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const columns = allColumns.slice(-VISIBLE_COLUMNS);
  if (!columns.length) return <p className="pcr-oi-caption">Not enough data yet.</p>;
  const boxLog = Math.log(1 + config.boxPercent / 100);
  const minLevel = Math.min(...columns.map((c) => c.bottom));
  const maxLevel = Math.max(...columns.map((c) => c.top));
  const levels = maxLevel - minLevel + 1;
  const cell = Math.max(4, Math.min(12, Math.floor(460 / levels)));
  const colWidth = Math.max(cell, 18);
  const left = 64;
  const top = 18;
  const chartHeight = levels * cell;
  const rsiHeight = 80;
  const width = left + columns.length * colWidth + 16;
  const height = top + chartHeight + 20 + rsiHeight + 24;
  const priceAt = (level: number) => Math.exp(level * boxLog);
  const y = (level: number) => top + (maxLevel - level) * cell;
  const x = (i: number) => left + i * colWidth;
  const ftColumns = new Set(signals.filter((s) => s.kind === "turtle_follow_through").map((s) => s.column));
  const labelEvery = Math.max(1, Math.ceil(levels / 10));
  const rsiTop = top + chartHeight + 20;
  const rsiY = (v: number) => rsiTop + (1 - v / 100) * rsiHeight;
  const rsiPoints = columns
    .map((c, i) => (c.rsi == null ? null : `${(x(i) + colWidth / 2).toFixed(1)},${rsiY(c.rsi).toFixed(1)}`))
    .filter(Boolean)
    .join(" ");
  // trade entries/exits, pinned to the column that was being drawn at the time
  const columnAt = (t: number): number => {
    if (t < columns[0].start) return -1;
    let found = -1;
    columns.forEach((c, i) => {
      if (c.start <= t) found = i;
    });
    return found;
  };
  const tradeNotesByColumn = new Map<number, TradeNote[]>();
  for (const note of trades.flatMap(turtleNotes)) {
    const i = columnAt(note.time);
    if (i >= 0) tradeNotesByColumn.set(i, [...(tradeNotesByColumn.get(i) ?? []), note]);
  }
  const showTip = (e: React.MouseEvent, notes: TradeNote[]) => {
    const box = wrapRef.current?.getBoundingClientRect();
    if (box) setTip({ x: e.clientX - box.left + (wrapRef.current?.scrollLeft ?? 0), y: e.clientY - box.top, notes });
  };

  return (
    <div ref={wrapRef} style={{ overflowX: "auto", position: "relative" }}>
      <div style={{ fontSize: 12, minHeight: 18 }}>
        {hover
          ? `Column #${hover.index} ${hover.type}: ${num(hover.bottomPrice, 0)} – ${num(hover.topPrice, 0)} · ${ist(hover.start)} → ${ist(hover.end)} · RSI ${num(hover.rsi)}${hover.turtle ? " · Turtle Breakout" : ""}${hover.followThrough ? " · Follow-Through" : ""}`
          : "X = rising column, O = falling. T = Turtle Breakout (above the last 5 columns' highs); ▲ = Turtle Follow-Through (green when RSI > 50); ▲IN / ▼OUT = paper spread entry / exit -- hover for the reason."}
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        style={{ display: "block", width: "100%", minWidth: 640, height: "auto", background: "var(--panel)" }}
        role="img"
        aria-label="Point and figure chart"
      >
        {Array.from({ length: levels }, (_, k) => maxLevel - k)
          .filter((level) => (maxLevel - level) % labelEvery === 0)
          .map((level) => (
            <g key={`p${level}`}>
              <line x1={left} x2={width - 8} y1={y(level) + cell / 2} y2={y(level) + cell / 2} stroke="var(--line-soft)" />
              <text x={left - 6} y={y(level) + cell / 2 + 4} textAnchor="end" fontSize={10} fill="var(--muted)">
                {Math.round(priceAt(level)).toLocaleString("en-IN")}
              </text>
            </g>
          ))}
        {columns.map((c, i) => {
          const cx = x(i) + colWidth / 2;
          const boxes = [];
          for (let level = c.bottom; level <= c.top; level++) {
            const cy = y(level) + cell / 2;
            const r = cell / 2 - 0.8;
            if (cell >= 6) {
              boxes.push(
                c.type === "X" ? (
                  <g key={level} stroke="var(--green)" strokeWidth={1.2}>
                    <line x1={cx - r} y1={cy - r} x2={cx + r} y2={cy + r} />
                    <line x1={cx - r} y1={cy + r} x2={cx + r} y2={cy - r} />
                  </g>
                ) : (
                  <circle key={level} cx={cx} cy={cy} r={r} fill="none" stroke="var(--red)" strokeWidth={1.2} />
                ),
              );
            } else {
              boxes.push(
                <rect key={level} x={cx - r} y={cy - r} width={r * 2} height={r * 2} fill={c.type === "X" ? "var(--green)" : "var(--red)"} opacity={0.75} />,
              );
            }
          }
          const ftValid = ftColumns.has(c.index) && (c.rsi ?? 0) > config.rsiThreshold;
          return (
            <g key={c.index} onMouseEnter={() => setHover(c)} onMouseLeave={() => setHover(null)} style={{ cursor: "default" }}>
              <rect x={x(i)} y={top} width={colWidth} height={chartHeight} fill="transparent" />
              {boxes}
              {c.turtle ? (
                <text x={cx} y={y(c.top) - 3} textAnchor="middle" fontSize={9} fontWeight={700} fill="var(--blue)">
                  T
                </text>
              ) : null}
              {ftColumns.has(c.index) ? (
                <text x={cx} y={y(c.top) - (c.turtle ? 12 : 3)} textAnchor="middle" fontSize={11} fontWeight={700} fill={ftValid ? "var(--green)" : "var(--muted)"}>
                  ▲
                </text>
              ) : null}
              {(tradeNotesByColumn.get(i) ?? []).map((note, k) => (
                <g
                  key={`n${k}`}
                  onMouseMove={(e) => showTip(e, [note])}
                  onMouseLeave={() => setTip(null)}
                  style={{ cursor: "pointer" }}
                  transform={`translate(${cx}, ${Math.min(y(c.bottom) + cell + 9 + k * 13, top + chartHeight + 12)})`}
                >
                  <rect x={-12} y={-6} width={24} height={12} rx={3} fill={note.color} />
                  <text y={3} textAnchor="middle" fontSize={8} fontWeight={700} fill="#fff">
                    {note.kind === "entry" ? "▲IN" : "▼OUT"}
                  </text>
                </g>
              ))}
            </g>
          );
        })}
        <text x={left - 6} y={rsiTop + 8} textAnchor="end" fontSize={10} fill="var(--muted)">
          RSI
        </text>
        <line x1={left} x2={width - 8} y1={rsiY(config.rsiThreshold)} y2={rsiY(config.rsiThreshold)} stroke="var(--amber)" strokeDasharray="4 3" />
        <text x={left - 6} y={rsiY(config.rsiThreshold) + 4} textAnchor="end" fontSize={10} fill="var(--amber)">
          {config.rsiThreshold}
        </text>
        <rect x={left} y={rsiTop} width={width - left - 8} height={rsiHeight} fill="none" stroke="var(--line)" />
        {rsiPoints ? <polyline points={rsiPoints} fill="none" stroke="var(--blue)" strokeWidth={1.5} /> : null}
        {columns.length ? (
          <>
            <text x={left} y={height - 6} fontSize={10} fill="var(--muted)">
              {ist(columns[0].start)}
            </text>
            <text x={width - 8} y={height - 6} textAnchor="end" fontSize={10} fill="var(--muted)">
              {ist(columns[columns.length - 1].end)}
            </text>
          </>
        ) : null}
      </svg>
      {tip ? <MarkerTooltip x={tip.x} y={tip.y} notes={tip.notes} /> : null}
    </div>
  );
}

function OpenSpread({ trade, config, busy, onClose }: { trade: TurtleTrade; config?: TurtleConfig; busy: boolean; onClose: () => void }) {
  const target = config?.profitDecayPercent ?? 75;
  const decay = trade.lastDecay ?? 0;
  const progress = Math.max(0, Math.min(decay / target, 1)) * 100;
  return (
    <div className="strategy-chart-card">
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "baseline" }}>
        <strong>
          #{trade.id} · SELL {trade.shortStrike} PE / BUY {trade.longStrike} PE · exp {trade.expiry}
        </strong>
        <span className="pcr-oi-caption">
          {trade.lots} lots · entered {ist(trade.entryTime)} at {num(trade.spot, 0)} ({trade.trigger}
          {trade.signalRsi ? `, RSI ${num(trade.signalRsi)}` : ""})
        </span>
        <button type="button" className="button secondary" onClick={onClose} disabled={busy} style={{ marginLeft: "auto" }}>
          <SquareArrowOutUpRight size={14} /> Close spread
        </button>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 10 }}>
        {[
          { label: "Credit received", value: `${num(trade.creditPoints)} pts`, caption: inr(trade.credit) },
          { label: "Cost to close now", value: `${num(trade.lastCost)} pts`, caption: `updated ${ist(trade.lastUpdate)}` },
          { label: "P&L", value: inr(trade.grossPnl), caption: `net after est. charges ${inr(trade.netPnl)}`, color: tone(trade.grossPnl) },
          { label: "Max loss (capped)", value: inr(trade.maxLoss), caption: "spread width − credit" },
          { label: "P&F RSI now", value: num(trade.lastRsi), caption: `exit below ${config?.rsiThreshold ?? 50}`, color: (trade.lastRsi ?? 100) < (config?.rsiThreshold ?? 50) ? "var(--red)" : undefined },
          { label: "Days to expiry", value: String(trade.daysToExpiry), caption: `calendar exit at ≤ ${config?.calendarExitDays ?? 3}`, color: trade.daysToExpiry <= (config?.calendarExitDays ?? 3) + 1 ? "var(--amber)" : undefined },
        ].map((m) => (
          <div key={m.label} className="metric metric-compact" style={{ flex: "1 1 150px" }}>
            <span>{m.label}</span>
            <strong style={{ color: m.color }}>{m.value}</strong>
            <span className="pcr-oi-caption"><ToneText text={m.caption} /></span>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
          <span>Premium decay {num(decay, 1)}%</span>
          <span>target {target}%</span>
        </div>
        <div style={{ height: 8, borderRadius: 4, background: "var(--line-soft)", marginTop: 4 }}>
          <div style={{ width: `${progress}%`, height: 8, borderRadius: 4, background: decay >= 0 ? "var(--green)" : "var(--red)" }} />
        </div>
      </div>
    </div>
  );
}

/** Running total of net P&L over closed trades, oldest first: trade id -> cumulative net. */
function cumulativeNet(trades: { id: number; status: string; entryTime: number; netPnl: number }[]): Map<number, number> {
  const out = new Map<number, number>();
  let total = 0;
  for (const t of [...trades].filter((x) => x.status === "CLOSED").sort((a, b) => a.entryTime - b.entryTime || a.id - b.id)) {
    total += t.netPnl;
    out.set(t.id, total);
  }
  return out;
}

function TradesTable({ trades }: { trades: TurtleTrade[] }) {
  if (!trades.length) return <p className="pcr-oi-caption" style={{ margin: 0 }}>No trades yet.</p>;
  const cum = cumulativeNet(trades);
  return (
    <div style={{ overflowX: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Entered</th>
            <th>Mode</th>
            <th>Trigger</th>
            <th>Spread</th>
            <th>Lots</th>
            <th>Credit</th>
            <th>Exited</th>
            <th>Reason</th>
            <th>Gross</th>
            <th>Charges</th>
            <th>Net</th>
            <th>Cumulative net</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr key={t.id}>
              <td>{t.id}</td>
              <td>{ist(t.entryTime)}</td>
              <td style={t.mode === "live" ? { color: "var(--red)", fontWeight: 600 } : undefined}>{t.mode === "live" ? `LIVE · ${t.broker === "angel" ? "Angel" : "Dhan"}` : "paper"}</td>
              <td>
                {t.trigger}
                {t.signalRsi ? ` (RSI ${num(t.signalRsi, 1)})` : ""}
              </td>
              <td>
                {t.shortStrike}/{t.longStrike} PE · {t.expiry}
              </td>
              <td>{t.lots}</td>
              <td>
                {num(t.creditPoints)} pts · {inr(t.credit)}
              </td>
              <td>{t.status === "OPEN" ? "open" : ist(t.exitTime)}</td>
              <td>{t.exitReason ? EXIT_LABEL[t.exitReason] ?? t.exitReason : "—"}</td>
              <td style={{ color: tone(t.grossPnl) }}>{inr(t.grossPnl)}</td>
              <td>{inr(t.charges)}</td>
              <td style={{ color: tone(t.netPnl) }}>
                <strong>{inr(t.netPnl)}</strong>
              </td>
              <td style={{ color: tone(cum.get(t.id)) }}>{cum.has(t.id) ? inr(cum.get(t.id)) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AlarmHistory() {
  const [alarms, setAlarms] = useState<TurtleAlarm[]>([]);
  useEffect(() => {
    getTurtleAlarms()
      .then((r) => setAlarms(r.alarms))
      .catch(() => undefined);
  }, []);
  return (
    <CollapsibleSection id="turtlea1-alarms" title={`Alarm history (${alarms.length})`} defaultOpen={false}>
      {alarms.length ? (
        <table>
          <thead>
            <tr>
              <th>When</th>
              <th>Alarm</th>
              <th>Acknowledged</th>
            </tr>
          </thead>
          <tbody>
            {alarms.map((a) => (
              <tr key={a.id}>
                <td>{ist(a.createdAt)}</td>
                <td>{a.title}</td>
                <td>{a.acknowledgedAt ? ist(a.acknowledgedAt) : "not yet"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="pcr-oi-caption" style={{ margin: 0 }}>No alarms yet.</p>
      )}
    </CollapsibleSection>
  );
}

const SETTING_FIELDS: { key: keyof TurtleConfig; label: string; hint?: string }[] = [
  { key: "capital", label: "Capital ₹", hint: "lots = capital ÷ per-lot allocation" },
  { key: "capitalPerLot", label: "Allocation per lot ₹", hint: "PDF: ₹1.5L" },
  { key: "boxPercent", label: "P&F box %", hint: "0.02 or 0.03" },
  { key: "reversal", label: "Reversal (boxes)", hint: "3" },
  { key: "turtleLookback", label: "Turtle lookback (columns)", hint: "5" },
  { key: "rsiPeriod", label: "RSI period", hint: "14" },
  { key: "rsiThreshold", label: "RSI threshold", hint: "50" },
  { key: "spreadWidth", label: "Spread width (pts)", hint: "300" },
  { key: "profitDecayPercent", label: "Profit target (% decay)", hint: "75" },
  { key: "calendarExitDays", label: "Calendar exit (days to expiry)", hint: "3" },
];

function SettingsSection({ config, onSaved }: { config: TurtleConfig | null; onSaved: () => void }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  useEffect(() => {
    if (config) setDraft(Object.fromEntries(SETTING_FIELDS.map((f) => [f.key, String(config[f.key])])));
  }, [config]);
  if (!config) return null;

  async function save(extra?: Partial<TurtleConfig>) {
    setSaving(true);
    setSaveError(null);
    try {
      await updateTurtleConfig(extra ?? Object.fromEntries(SETTING_FIELDS.map((f) => [f.key, Number(draft[f.key])])));
      onSaved();
    } catch (exc) {
      setSaveError(exc instanceof Error ? exc.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <CollapsibleSection id="turtlea1-settings" title="Settings" defaultOpen={false}>
      {saveError ? <div className="alert error">{saveError}</div> : null}
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", marginBottom: 12, fontSize: 13 }}>
        <span>Mode:</span>
        <button type="button" className={`button ${config.mode === "paper" ? "" : "secondary"}`} onClick={() => save({ mode: "paper" })} disabled={saving}>
          Paper
        </button>
        <button
          type="button"
          className={`button ${config.mode === "live" ? "" : "secondary"}`}
          onClick={() => {
            if (window.confirm(`Switch Define Turtle A1 to LIVE: the next signal will place real ${config.broker === "angel" ? "Angel One" : "Dhan"} market orders for ${config.lots} lots (${config.lots * config.lotSize} qty per leg). Spreads already open stay paper. Continue?`)) save({ mode: "live" });
          }}
          disabled={saving || !config.liveOrdersAllowed}
          title={config.liveOrdersAllowed ? "" : "Set TURTLE_A1_LIVE_ORDER_ENABLED=true (and LIVE_ORDER_ENABLED=true, plus the ANGEL_* keys) on the server first"}
        >
          Live
        </button>
        <span className="pcr-oi-caption">
          {config.liveOrdersAllowed
            ? `Live orders go to ${config.broker === "angel" ? "Angel One (CARRYFORWARD)" : "Dhan (MARGIN)"} -- overnight market orders, ${config.lots} lots (${config.lots * config.lotSize} qty per leg). Market data stays on Dhan.`
            : `Live orders are switched off on the server (TURTLE_A1_LIVE_ORDER_ENABLED, or the ANGEL_* keys are missing). Broker: Angel One.`}
        </span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 12 }}>
        {SETTING_FIELDS.map((f) => (
          <label key={f.key} style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12 }}>
            <span style={{ color: "var(--muted)", fontWeight: 600 }}>{f.label}</span>
            <input value={draft[f.key] ?? ""} onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))} style={{ width: 110, fontSize: 13, padding: "3px 6px" }} />
            {f.hint ? <span className="pcr-oi-caption">{f.hint}</span> : null}
          </label>
        ))}
      </div>
      <div style={{ display: "flex", gap: 16, alignItems: "center", marginTop: 12, fontSize: 13 }}>
        <label style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={config.enabled} onChange={(e) => save({ enabled: e.target.checked })} disabled={saving} />
          Automatic entry on signals
        </label>
        <button type="button" className="button" onClick={() => save()} disabled={saving}>
          <Save size={14} /> Save settings
        </button>
      </div>
    </CollapsibleSection>
  );
}
