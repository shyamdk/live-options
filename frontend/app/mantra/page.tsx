"use client";

import { ColorType, createChart, IChartApi, IPriceLine, ISeriesApi, LineSeries, Time, UTCTimestamp } from "lightweight-charts";
import { Infinity as InfinityIcon, Play, RefreshCw, Save, SquareArrowOutUpRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import AlarmOverlay from "@/components/AlarmOverlay";
import CollapsibleSection from "@/components/CollapsibleSection";
import { DailyTotalsTable, groupDailyTotals } from "@/components/DailyTotals";
import StrikeDistanceMap from "@/components/StrikeDistanceMap";
import {
  acknowledgeMantraAlarm,
  closeMantraTrade,
  enterMantraNow,
  getMantraAlarms,
  getMantraPlan,
  getMantraTrade,
  getMantraTrades,
  updateMantraConfig,
} from "@/lib/api";
import type { MantraAlarm, MantraConfig, MantraMode, MantraPlan, MantraTrade } from "@/types/mantra";

const REFRESH_MS = 20000;
const PLAN_REFRESH_MS = 120000;
const EXIT_LABEL: Record<string, string> = {
  target: "Target hit",
  stop_loss: "Global stop loss",
  pre_expiry: "Day-before-expiry exit",
  unstable_straddle: "Unstable straddle",
  manual: "Closed manually",
};

const SETTING_FIELDS: { key: string; label: string; hint?: Record<MantraMode, string> }[] = [
  { key: "capital", label: "Capital ₹", hint: { monthly: "lots = capital ÷ per-lot allocation", weekly: "lots = capital ÷ per-lot allocation" } },
  { key: "capitalPerLot", label: "Allocation per lot ₹", hint: { monthly: "doc: ₹5L (Rule of 3)", weekly: "₹5L" } },
  { key: "targetPremium", label: "Target premium per side ₹", hint: { monthly: "doc: ₹100", weekly: "₹40 (same delta on ~8 DTE)" } },
  { key: "minDte", label: "Min days to expiry at entry", hint: { monthly: "43", weekly: "7" } },
  { key: "maxDte", label: "Max days to expiry at entry", hint: { monthly: "50", weekly: "13" } },
  { key: "targetPercent", label: "Target % of credit", hint: { monthly: "80", weekly: "80" } },
  { key: "stopPercent", label: "Global stop % of credit", hint: { monthly: "100 (1:1)", weekly: "100 (1:1)" } },
  { key: "rollLadder", label: "Roll ladder (% of credit)", hint: { monthly: "11,19,33,62", weekly: "11,19,33,62" } },
  { key: "unstableDte", label: "Unstable straddle window (days)", hint: { monthly: "7", weekly: "2" } },
  { key: "unstableRatio", label: "Unstable premium ratio", hint: { monthly: "3×", weekly: "3×" } },
  { key: "maxSpreadPercent", label: "Max bid/ask spread %", hint: { monthly: "5", weekly: "5" } },
  { key: "minOiLots", label: "Min OI (lots)", hint: { monthly: "1000", weekly: "1000" } },
  { key: "gapPercent", label: "Gap protocol %", hint: { monthly: "1.5 -- wait till 09:17", weekly: "1.5 -- wait till 09:17" } },
];

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
  return new Date(epoch * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
}

function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(`${iso}T00:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", weekday: "short", day: "2-digit", month: "short", year: "numeric" });
}

function istShort(time: Time): string {
  if (typeof time !== "number") return String(time);
  return new Date(time * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
}

export default function MantraPage() {
  const [tab, setTab] = useState<MantraMode>("monthly");
  const [plans, setPlans] = useState<Partial<Record<MantraMode, MantraPlan>>>({});
  const [trades, setTrades] = useState<MantraTrade[]>([]);
  const [alarms, setAlarms] = useState<MantraAlarm[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    try {
      const fromUrl = new URLSearchParams(window.location.search).get("tab");
      const saved = fromUrl ?? window.localStorage.getItem("mantra:tab");
      if (saved === "monthly" || saved === "weekly") setTab(saved);
    } catch {
      // ignore
    }
  }, []);

  function switchTab(next: MantraMode) {
    setTab(next);
    try {
      window.localStorage.setItem("mantra:tab", next);
    } catch {
      // ignore
    }
  }

  async function loadTrades() {
    try {
      const r = await getMantraTrades();
      setTrades(r.trades);
      setAlarms(r.alarms);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load Mantra trades.");
    }
  }

  async function loadPlan(mode: MantraMode) {
    try {
      const p = await getMantraPlan(mode);
      setPlans((current) => ({ ...current, [mode]: p }));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load the entry plan.");
    }
  }

  useEffect(() => {
    loadTrades();
    const timer = window.setInterval(loadTrades, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    loadPlan(tab);
    const timer = window.setInterval(() => loadPlan(tab), PLAN_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [tab]);

  async function enterNow() {
    if (!window.confirm(`Open a paper ${tab} strangle now at current prices (skips the Monday 15:00 window and liquidity check)?`)) return;
    setBusy("enter");
    try {
      const r = await enterMantraNow(tab);
      setMessage(r.message ? `${r.status}: ${r.message}` : `Strangle ${r.status}.`);
      await Promise.all([loadTrades(), loadPlan(tab)]);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Entry failed.");
    } finally {
      setBusy(null);
    }
  }

  async function closeTrade(trade: MantraTrade) {
    if (!window.confirm(`Close ${trade.mode} strangle #${trade.id} now (paper)?`)) return;
    setBusy(`close-${trade.id}`);
    try {
      const r = await closeMantraTrade(trade.id);
      setMessage(`Strangle #${trade.id}: ${r.status}${r.message ? ` -- ${r.message}` : ""}`);
      await loadTrades();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Close failed.");
    } finally {
      setBusy(null);
    }
  }

  const plan = plans[tab];
  const config = plan?.config;
  const modeTrades = trades.filter((t) => t.mode === tab);
  const open = modeTrades.filter((t) => t.status === "OPEN");
  const closed = modeTrades.filter((t) => t.status === "CLOSED");
  const openCount = (m: MantraMode) => trades.filter((t) => t.mode === m && t.status === "OPEN").length;

  return (
    <section className="page">
      <AlarmOverlay title="Mantra alarm" alarms={alarms} acknowledge={acknowledgeMantraAlarm} onAcknowledged={loadTrades} />
      <header className="page-header">
        <div>
          <h1>
            <InfinityIcon size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Mantra
          </h1>
          <p>
            NIFTY short strangle with roll-in adjustments. Monthly: ₹100 strikes 43–50 days out; weekly: ₹40 strikes on next
            week&apos;s expiry. Entered Monday 15:00; 80% target, 1:1 global stop, roll ladder, straddle conversion, exit the day before
            expiry. Paper trading -- see mantra.md.
          </p>
        </div>
        <div className="toolbar" style={{ alignItems: "center" }}>
          <span className="status-live on" style={{ whiteSpace: "nowrap" }}>PAPER</span>
          <span className={`status-live ${config?.enabled ? "on" : ""}`} style={{ whiteSpace: "nowrap" }}>
            {config ? (config.enabled ? "Auto entry on" : "Auto entry paused") : "…"}
          </span>
          <button type="button" className="button secondary" onClick={() => Promise.all([loadTrades(), loadPlan(tab)])} style={{ whiteSpace: "nowrap" }}>
            <RefreshCw size={14} /> Refresh
          </button>
          <button type="button" className="button" onClick={enterNow} disabled={!!busy} style={{ whiteSpace: "nowrap" }}>
            <Play size={14} /> {busy === "enter" ? "Entering…" : `Enter ${tab} now`}
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}

      <nav style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--line)", marginBottom: 14 }}>
        {(["monthly", "weekly"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => switchTab(t)}
            style={{
              padding: "8px 14px",
              fontSize: 14,
              fontWeight: t === tab ? 600 : 500,
              color: t === tab ? "var(--blue)" : "var(--muted)",
              background: "none",
              border: "none",
              borderBottom: `2px solid ${t === tab ? "var(--blue)" : "transparent"}`,
              marginBottom: -1,
              cursor: "pointer",
            }}
          >
            {t === "monthly" ? "Monthly" : "Weekly"} (paper){openCount(t) ? ` · ${openCount(t)} open` : ""}
          </button>
        ))}
      </nav>

      <CollapsibleSection id={`mantra-${tab}-open`} title={`Open strangle (${open.length})`}>
        {open.length ? (
          open.map((trade) => <OpenStrangle key={trade.id} trade={trade} busy={busy === `close-${trade.id}`} onClose={() => closeTrade(trade)} />)
        ) : (
          <p className="pcr-oi-caption" style={{ margin: 0 }}>
            No open {tab} strangle. The next one opens on {plan?.monday ? day(plan.monday) : "the next qualifying Monday"} at 15:00.
          </p>
        )}
      </CollapsibleSection>

      <CollapsibleSection id={`mantra-${tab}-plan`} title="Next entry plan" aside={<span className="pcr-oi-caption">live chain, refreshed every 2 min</span>}>
        <PlanView plan={plan} />
      </CollapsibleSection>

      <CollapsibleSection id={`mantra-${tab}-pnl`} title="Daily P&L">
        <DailyTotalsTable rows={groupDailyTotals(closed, (t) => t.exitTime, (t) => t.grossPnl, (t) => t.netPnl)} />
      </CollapsibleSection>

      <CollapsibleSection id={`mantra-${tab}-trades`} title={`All ${tab} trades (${modeTrades.length})`} defaultOpen={false}>
        <TradesTable trades={modeTrades} />
      </CollapsibleSection>

      <AlarmHistory refreshKey={alarms.length} />
      <SettingsSection mode={tab} config={config ?? null} onSaved={() => loadPlan(tab)} />
    </section>
  );
}

function Metrics({ items }: { items: { label: string; value: string; caption?: string; color?: string }[] }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      {items.map((m) => (
        <div key={m.label} className="metric metric-compact" style={{ flex: "1 1 150px" }}>
          <span>{m.label}</span>
          <strong style={{ color: m.color }}>{m.value}</strong>
          {m.caption ? <span className="pcr-oi-caption">{m.caption}</span> : null}
        </div>
      ))}
    </div>
  );
}

function PlanView({ plan }: { plan: MantraPlan | undefined }) {
  if (!plan) return <p className="pcr-oi-caption">Loading the option chain…</p>;
  if (plan.error) return <div className="alert error" style={{ margin: 0 }}>{plan.error}</div>;
  const legs = plan.legs ? [plan.legs.CE, plan.legs.PE].map((leg, i) => ({ ...leg, type: i === 0 ? "CE" : "PE" })) : [];
  return (
    <div>
      <Metrics
        items={[
          { label: "Entry", value: day(plan.monday), caption: "15:00–15:15 IST; Tue 09:20 if deferred" },
          { label: "Series", value: day(plan.series), caption: `${plan.dte} days to expiry at entry` },
          { label: "Size", value: `${plan.config.lots} lots × ${plan.config.lotSize}`, caption: `₹${plan.config.capitalPerLot.toLocaleString("en-IN")} per lot of ${inr(plan.config.capital)}` },
          { label: "Credit (at today's bid)", value: inr(plan.credit), caption: `${num(plan.creditPoints)} pts` },
          { label: "Target", value: inr(plan.target), caption: `${plan.config.targetPercent}% of credit`, color: "var(--green)" },
          { label: "Global stop", value: inr(plan.stop ? -plan.stop : null), caption: `${plan.config.stopPercent}% of credit`, color: "var(--red)" },
          { label: "Square-off by", value: day(plan.exitBy), caption: "15:15 on the trading day before expiry" },
        ]}
      />
      <div style={{ overflowX: "auto", marginTop: 10 }}>
        <table>
          <thead>
            <tr>
              <th>Leg</th>
              <th>Strike</th>
              <th>From spot</th>
              <th>LTP</th>
              <th>Bid / Ask</th>
              <th>Delta</th>
              <th>IV</th>
              <th>OI (lots)</th>
              <th>Liquidity</th>
            </tr>
          </thead>
          <tbody>
            {legs.map((leg) => (
              <tr key={leg.type}>
                <td>SELL {leg.type}</td>
                <td>
                  <strong>{leg.strike.toLocaleString("en-IN")}</strong>
                </td>
                <td>{num(leg.distancePercent)}%</td>
                <td>{num(leg.ltp)}</td>
                <td>
                  {num(leg.bid)} / {num(leg.ask)}
                </td>
                <td>{num(leg.delta)}</td>
                <td>{num(leg.iv, 1)}</td>
                <td>{leg.oiLots.toLocaleString("en-IN")}</td>
                <td style={{ color: leg.liquidityOk ? "var(--green)" : "var(--amber)" }}>{leg.liquidityOk ? "OK" : leg.liquidity}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="pcr-oi-caption" style={{ marginBottom: 4 }}>
        Rolls at MTM loss of{" "}
        {(plan.rollLevels ?? []).map((v, i) => (
          <span key={i}>
            {i ? " → " : ""}
            {inr(-v)}
          </span>
        ))}
        . Strikes are re-picked from the live chain at entry; if liquidity fails, entry retries each minute until 15:14 and then moves
        to Tuesday 09:20. Spot now {num(plan.spot)}.
      </p>
      {plan.spot && plan.legs ? (
        <StrikeDistanceMap
          id="mantra-plan-map"
          spot={plan.spot}
          legs={[
            { key: "ce", strike: plan.legs.CE.strike, label: `${plan.legs.CE.strike.toLocaleString("en-IN")} CE`, short: true },
            { key: "pe", strike: plan.legs.PE.strike, label: `${plan.legs.PE.strike.toLocaleString("en-IN")} PE`, short: true },
          ]}
          marks={plan.config.mode === "monthly" ? [2, 4, 6, 8] : [1, 2, 3, 4]}
        />
      ) : null}
    </div>
  );
}

function OpenStrangle({ trade, busy, onClose }: { trade: MantraTrade; busy: boolean; onClose: () => void }) {
  const [detail, setDetail] = useState<MantraTrade | null>(null);
  useEffect(() => {
    let cancelled = false;
    getMantraTrade(trade.id)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [trade.id, trade.lastUpdate]);

  const openLegs = trade.legs.filter((l) => l.status === "OPEN");
  const mtm = trade.grossPnl;
  const spot = trade.lastSpot ?? trade.spot;
  return (
    <div className="strategy-chart-card">
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "baseline" }}>
        <strong>
          #{trade.id} · {trade.state === "STRADDLE" ? "Short straddle" : "Short strangle"}{" "}
          {openLegs.map((l) => `${l.strike} ${l.optionType}`).join(" / ")} · exp {day(trade.expiry)}
        </strong>
        <span className="pcr-oi-caption">
          {trade.lots} lots · entered {ist(trade.entryTime)} at {num(trade.spot, 0)} ({trade.trigger}) · {trade.rolls} roll{trade.rolls === 1 ? "" : "s"}
        </span>
        <button type="button" className="button secondary" onClick={onClose} disabled={busy} style={{ marginLeft: "auto" }}>
          <SquareArrowOutUpRight size={14} /> Close strangle
        </button>
      </div>
      <div style={{ marginTop: 10 }}>
        <Metrics
          items={[
            { label: "Initial credit", value: inr(trade.credit), caption: `${num(trade.creditPoints)} pts` },
            { label: "MTM (incl. booked)", value: inr(mtm), caption: `net of charges ${inr(trade.netPnl)} · ${ist(trade.lastUpdate)}`, color: tone(mtm) },
            { label: "Booked from rolls", value: inr(trade.booked), color: tone(trade.booked) },
            {
              label: "Next roll at",
              value: trade.nextRollAt == null ? (trade.state === "STRADDLE" ? "straddle -- no rolls" : "ladder used") : inr(trade.nextRollAt),
              caption: trade.state === "STRADDLE" ? "unstable-straddle exit armed" : `roll ${trade.rolls + 1} of 4`,
            },
            { label: "NIFTY", value: num(spot), caption: `entry ${num(trade.spot)}` },
            {
              label: "Days to expiry",
              value: String(trade.daysToExpiry),
              caption: `square-off ${day(trade.exitBy)} 15:15`,
              color: trade.daysToExpiry <= 2 ? "var(--amber)" : undefined,
            },
          ]}
        />
      </div>
      <MtmBar mtm={mtm} target={trade.target} stop={trade.stop} nextRollAt={trade.nextRollAt} />
      <div style={{ overflowX: "auto", marginTop: 10 }}>
        <table>
          <thead>
            <tr>
              <th>Leg</th>
              <th>Status</th>
              <th>Sold</th>
              <th>Now / bought back</th>
              <th>P&L</th>
              <th>Opened</th>
              <th>Closed</th>
            </tr>
          </thead>
          <tbody>
            {trade.legs.map((leg) => {
              const price = leg.status === "OPEN" ? leg.lastAsk ?? leg.lastLtp : leg.exit;
              const pnl = price == null ? null : (leg.entry - price) * trade.lots * trade.lotSize;
              return (
                <tr key={leg.id} style={{ opacity: leg.status === "OPEN" ? 1 : 0.6 }}>
                  <td>
                    SELL {leg.strike} {leg.optionType}
                    {leg.rollNo ? <span className="pcr-oi-caption"> (roll {leg.rollNo})</span> : null}
                  </td>
                  <td>{leg.status === "OPEN" ? "open" : "closed"}</td>
                  <td>{num(leg.entry)}</td>
                  <td>{num(price)}</td>
                  <td style={{ color: tone(pnl) }}>{inr(pnl)}</td>
                  <td>{ist(leg.openedAt)}</td>
                  <td>{ist(leg.closedAt)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div style={{ marginTop: 10 }}>
        <StrikeDistanceMap
          id={`mantra-map-${trade.id}`}
          spot={spot}
          legs={openLegs.map((l) => ({ key: String(l.id), strike: l.strike, label: `${l.strike.toLocaleString("en-IN")} ${l.optionType}`, short: true }))}
          marks={trade.mode === "monthly" ? [2, 4, 6, 8] : [1, 2, 3, 4]}
        />
      </div>
      {detail?.mtmHistory?.length ? (
        <div style={{ marginTop: 10 }}>
          <MtmChart trade={detail} />
        </div>
      ) : null}
      <EventsLog trade={trade} />
    </div>
  );
}

// Horizontal bar from −stop (left) to +target (right), zero in the middle of
// its own range, with roll levels ticked on the loss side.
function MtmBar({ mtm, target, stop, nextRollAt }: { mtm: number; target: number; stop: number; nextRollAt: number | null }) {
  const lo = -stop;
  const hi = target;
  const pos = (v: number) => ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * 100;
  const zero = pos(0);
  const at = pos(mtm);
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
        <span style={{ color: "var(--red)" }}>stop {inr(lo)}</span>
        <span>MTM {inr(mtm)}</span>
        <span style={{ color: "var(--green)" }}>target {inr(hi)}</span>
      </div>
      <div style={{ position: "relative", height: 10, borderRadius: 5, background: "var(--line-soft)", marginTop: 4 }}>
        <div
          style={{
            position: "absolute",
            left: `${Math.min(zero, at)}%`,
            width: `${Math.abs(at - zero)}%`,
            height: 10,
            borderRadius: 5,
            background: mtm >= 0 ? "var(--green)" : "var(--red)",
          }}
        />
        <div style={{ position: "absolute", left: `${zero}%`, top: -3, width: 2, height: 16, background: "var(--muted)" }} />
        {nextRollAt != null ? (
          <div title={`next roll at ${inr(nextRollAt)}`} style={{ position: "absolute", left: `${pos(nextRollAt)}%`, top: -3, width: 2, height: 16, background: "var(--amber)" }} />
        ) : null}
      </div>
      {nextRollAt != null ? (
        <div className="pcr-oi-caption" style={{ marginTop: 2 }}>
          amber tick = next roll at {inr(nextRollAt)}
        </div>
      ) : null}
    </div>
  );
}

function MtmChart({ trade }: { trade: MantraTrade }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const linesRef = useRef<IPriceLine[]>([]);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: containerRef.current.clientWidth,
      height: 220,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (t: Time) => istShort(t) },
      localization: { timeFormatter: (t: Time) => istShort(t) },
    });
    seriesRef.current = chart.addSeries(LineSeries, { color: "#2368b6", lineWidth: 2, title: "MTM ₹" });
    chartRef.current = chart;
    const observer = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      linesRef.current = [];
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !trade.mtmHistory) return;
    const seen = new Set<number>();
    const points = trade.mtmHistory.filter((p) => (seen.has(p.time) ? false : (seen.add(p.time), true)));
    series.setData(points.map((p) => ({ time: p.time as UTCTimestamp, value: p.mtm })));
    for (const line of linesRef.current) series.removePriceLine(line);
    linesRef.current = [
      series.createPriceLine({ price: trade.target, color: "#168448", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "Target" }),
      series.createPriceLine({ price: -trade.stop, color: "#c93535", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "Stop" }),
      ...(trade.nextRollAt != null
        ? [series.createPriceLine({ price: trade.nextRollAt, color: "#b7791f", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "Next roll" })]
        : []),
    ];
  }, [trade]);

  return <div ref={containerRef} style={{ width: "100%", height: 220 }} />;
}

function EventsLog({ trade }: { trade: MantraTrade }) {
  if (!trade.events.length) return null;
  return (
    <details style={{ marginTop: 10 }}>
      <summary style={{ cursor: "pointer", fontSize: 13, fontWeight: 600 }}>Events ({trade.events.length})</summary>
      <table style={{ marginTop: 6 }}>
        <tbody>
          {[...trade.events].reverse().map((e, i) => (
            <tr key={i}>
              <td style={{ whiteSpace: "nowrap" }}>{ist(e.time)}</td>
              <td>{e.kind}</td>
              <td>{e.text}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function TradesTable({ trades }: { trades: MantraTrade[] }) {
  if (!trades.length) return <p className="pcr-oi-caption" style={{ margin: 0 }}>No trades yet.</p>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Entered</th>
            <th>Series</th>
            <th>Initial strikes</th>
            <th>Lots</th>
            <th>Credit</th>
            <th>Rolls</th>
            <th>Final</th>
            <th>Exited</th>
            <th>Reason</th>
            <th>Gross</th>
            <th>Charges</th>
            <th>Net</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => {
            const initial = t.legs.filter((l) => !l.rollNo);
            return (
              <tr key={t.id}>
                <td>{t.id}</td>
                <td>
                  {ist(t.entryTime)} <span className="pcr-oi-caption">({t.trigger})</span>
                </td>
                <td>{t.expiry}</td>
                <td>{initial.map((l) => `${l.strike} ${l.optionType}`).join(" / ")}</td>
                <td>{t.lots}</td>
                <td>{inr(t.credit)}</td>
                <td>{t.rolls}</td>
                <td>{t.state === "STRADDLE" ? "straddle" : "strangle"}</td>
                <td>{t.status === "OPEN" ? "open" : ist(t.exitTime)}</td>
                <td>{t.exitReason ? EXIT_LABEL[t.exitReason] ?? t.exitReason : "—"}</td>
                <td style={{ color: tone(t.grossPnl) }}>{inr(t.grossPnl)}</td>
                <td>{inr(t.charges)}</td>
                <td style={{ color: tone(t.netPnl) }}>
                  <strong>{inr(t.netPnl)}</strong>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function AlarmHistory({ refreshKey }: { refreshKey: number }) {
  const [alarms, setAlarms] = useState<MantraAlarm[]>([]);
  useEffect(() => {
    getMantraAlarms()
      .then((r) => setAlarms(r.alarms))
      .catch(() => undefined);
  }, [refreshKey]);
  return (
    <CollapsibleSection id="mantra-alarms" title={`Alarm history (${alarms.length})`} defaultOpen={false}>
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
        <p className="pcr-oi-caption" style={{ margin: 0 }}>
          No alarms yet. Stop-loss and unstable-straddle exits raise a full-screen alarm here plus a Telegram message.
        </p>
      )}
    </CollapsibleSection>
  );
}

function SettingsSection({ mode, config, onSaved }: { mode: MantraMode; config: MantraConfig | null; onSaved: () => void }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (config) setDraft(Object.fromEntries(SETTING_FIELDS.map((f) => [f.key, String(config[f.key] ?? "")])));
  }, [config]);
  if (!config) return null;

  async function save(extra?: Record<string, unknown>) {
    setSaving(true);
    setError(null);
    try {
      await updateMantraConfig(
        mode,
        extra ?? Object.fromEntries(SETTING_FIELDS.map((f) => [f.key, f.key === "rollLadder" ? draft[f.key] : Number(draft[f.key])])),
      );
      onSaved();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <CollapsibleSection id={`mantra-${mode}-settings`} title={`${mode === "monthly" ? "Monthly" : "Weekly"} settings`} defaultOpen={false}>
      {error ? <div className="alert error">{error}</div> : null}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 12 }}>
        {SETTING_FIELDS.map((f) => (
          <label key={f.key} style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12 }}>
            <span style={{ color: "var(--muted)", fontWeight: 600 }}>{f.label}</span>
            <input
              value={draft[f.key] ?? ""}
              onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
              style={{ width: f.key === "rollLadder" ? 130 : 110, fontSize: 13, padding: "3px 6px" }}
            />
            {f.hint ? <span className="pcr-oi-caption">{f.hint[mode]}</span> : null}
          </label>
        ))}
      </div>
      <div style={{ display: "flex", gap: 16, alignItems: "center", marginTop: 12, fontSize: 13 }}>
        <label style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={config.enabled} onChange={(e) => save({ enabled: e.target.checked })} disabled={saving} />
          Automatic Monday entry ({mode})
        </label>
        <button type="button" className="button" onClick={() => save()} disabled={saving}>
          <Save size={14} /> Save settings
        </button>
      </div>
    </CollapsibleSection>
  );
}
