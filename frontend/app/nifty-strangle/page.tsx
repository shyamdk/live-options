"use client";

import { ColorType, createChart, IChartApi, IPriceLine, ISeriesApi, LineSeries, Time, UTCTimestamp } from "lightweight-charts";
import { Play, RefreshCw, Save, Spline, SquareArrowOutUpRight } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import CollapsibleSection from "@/components/CollapsibleSection";
import { DailyTotalsTable, groupDailyTotals } from "@/components/DailyTotals";
import StrikeDistanceMap from "@/components/StrikeDistanceMap";
import { istTime, TradeNote, useTradeMarkers } from "@/components/TradeMarkers";
import ToneText from "@/components/ToneText";
import {
  closeNiftyStrangleLeg,
  enterNiftyStrangleNow,
  getNiftyStranglePlan,
  getNiftyStrangleSpotChart,
  getNiftyStrangleTrades,
  updateNiftyStrangleConfig,
} from "@/lib/api";
import type { NiftyStrangleConfig, NiftyStranglePlan, NiftyStrangleTrade } from "@/types/nifty-strangle";
import { cumulativeNet } from "@/lib/cumulative";

const REFRESH_MS = 15000;
const PLAN_REFRESH_MS = 120000;
const EXIT_LABEL: Record<string, string> = {
  stop_loss: "Stop loss",
  expiry_buyback: "Bought back before expiry",
  expired: "Expired",
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
  return new Date(epoch * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
}

function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(`${iso}T00:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", weekday: "short", day: "2-digit", month: "short" });
}

export default function NiftyStranglePage() {
  const [plan, setPlan] = useState<NiftyStranglePlan | null>(null);
  const [config, setConfig] = useState<NiftyStrangleConfig | null>(null);
  const [trades, setTrades] = useState<NiftyStrangleTrade[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function loadTrades() {
    try {
      setTrades((await getNiftyStrangleTrades()).trades);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load trades.");
    }
  }

  async function loadPlan() {
    try {
      const p = await getNiftyStranglePlan();
      setPlan(p);
      setConfig(p.config);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load the plan.");
    }
  }

  useEffect(() => {
    loadTrades();
    loadPlan();
    const t1 = window.setInterval(loadTrades, REFRESH_MS);
    const t2 = window.setInterval(loadPlan, PLAN_REFRESH_MS);
    return () => {
      window.clearInterval(t1);
      window.clearInterval(t2);
    };
  }, []);

  async function saveConfig(updates: Partial<NiftyStrangleConfig>, note?: string) {
    setBusy("config");
    setError(null);
    try {
      setConfig(await updateNiftyStrangleConfig(updates));
      if (note) setMessage(note);
      await loadPlan();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Save failed.");
    } finally {
      setBusy(null);
    }
  }

  async function enterNow() {
    if (!window.confirm(`${config?.mode === "live" ? "LIVE ORDERS: " : ""}Sell the strangle now on the ${day(plan?.expiry)} expiry, outside the 15:15 window?`)) return;
    setBusy("enter");
    try {
      const r = await enterNiftyStrangleNow();
      setMessage(r.message ? `${r.status}: ${r.message}` : `Strangle ${r.status}.`);
      await loadTrades();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Entry failed.");
    } finally {
      setBusy(null);
    }
  }

  async function closeLeg(legId: number, label: string) {
    if (!window.confirm(`Buy back ${label} now?`)) return;
    setBusy(`leg-${legId}`);
    try {
      const r = await closeNiftyStrangleLeg(legId);
      setMessage(`${label}: ${r.status}${r.message ? ` -- ${r.message}` : ""}`);
      await loadTrades();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Close failed.");
    } finally {
      setBusy(null);
    }
  }

  const open = trades.filter((t) => t.status === "OPEN");
  const closed = trades.filter((t) => t.status === "CLOSED");

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Spline size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            NIFTY Strangle
          </h1>
          <p>
            BTC Strangle&apos;s rules on NIFTY weekly options: sell an OTM call + put at spot ± multiplier × ATM straddle at 15:15 the
            day before expiry (stepping in to the farthest strike that still pays the minimum premium), per-leg stop loss, buy back
            on expiry day only if still worth more than the threshold.
          </p>
        </div>
        <div className="toolbar" style={{ alignItems: "center" }}>
          <span
            className={`status-live ${config?.mode === "live" ? "" : "on"}`}
            style={{ whiteSpace: "nowrap", ...(config?.mode === "live" ? { background: "#fde8e8", color: "var(--red)", borderColor: "var(--red)" } : {}) }}
          >
            {config?.mode === "live" ? "LIVE" : "PAPER"}
          </span>
          <span className={`status-live ${config?.enabled ? "on" : ""}`} style={{ whiteSpace: "nowrap" }}>
            {config ? (config.enabled ? "Auto entry on" : "Auto entry paused") : "…"}
          </span>
          <button type="button" className="button secondary" onClick={() => Promise.all([loadTrades(), loadPlan()])} style={{ whiteSpace: "nowrap" }}>
            <RefreshCw size={14} /> Refresh
          </button>
          <button type="button" className="button" onClick={enterNow} disabled={!!busy} style={{ whiteSpace: "nowrap" }}>
            <Play size={14} /> {busy === "enter" ? "Entering…" : "Enter now"}
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}

      {config ? <SettingsSection config={config} busy={busy === "config"} onSave={saveConfig} /> : null}

      <CollapsibleSection
        id="nifty-strangle-plan"
        title="Next entry plan"
        aside={plan?.entryDate ? <span className="pcr-oi-caption">computed live for the {day(plan.entryDate)}, {config?.entryTime} IST entry</span> : null}
      >
        <PlanView plan={plan} />
      </CollapsibleSection>

      <CollapsibleSection id="nifty-strangle-open" title={`Open trades (${open.length})`}>
        {open.length ? (
          open.map((t) => <OpenTrade key={t.id} trade={t} busy={busy} onCloseLeg={closeLeg} />)
        ) : (
          <p className="pcr-oi-caption" style={{ margin: 0 }}>
            No open strangle. Next entry {day(plan?.entryDate)} {config?.entryTime} IST.
          </p>
        )}
      </CollapsibleSection>

      <CollapsibleSection id="nifty-strangle-pnl" title="Daily P&L" defaultOpen={false}>
        <DailyTotalsTable rows={groupDailyTotals(closed, (t) => t.closedAt, (t) => t.grossPnl, (t) => t.netPnl)} />
      </CollapsibleSection>

      <CollapsibleSection id="nifty-strangle-trades" title={`All trades (${trades.length})`}>
        <TradesTable trades={trades} />
      </CollapsibleSection>

      <CollapsibleSection id="nifty-strangle-chart" title="NIFTY spot (5-min, last few sessions)" defaultOpen={false}>
        <SpotChart open={open[0] ?? null} trades={trades} />
      </CollapsibleSection>
    </section>
  );
}

function SettingsSection({
  config,
  busy,
  onSave,
}: {
  config: NiftyStrangleConfig;
  busy: boolean;
  onSave: (updates: Partial<NiftyStrangleConfig>, note?: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  useEffect(() => {
    setDraft({
      multiplier: String(config.multiplier),
      stopLossPercent: String(config.stopLossPercent),
      lots: String(config.lots),
      minPremium: String(config.minPremium),
      entryTime: config.entryTime,
      entryWindowEnd: config.entryWindowEnd,
      expiryExitTime: config.expiryExitTime,
      buybackThreshold: String(config.buybackThreshold),
    });
  }, [config]);

  function save() {
    void onSave(
      {
        multiplier: Number(draft.multiplier),
        stopLossPercent: Number(draft.stopLossPercent),
        lots: Number(draft.lots),
        minPremium: Number(draft.minPremium),
        entryTime: draft.entryTime,
        entryWindowEnd: draft.entryWindowEnd,
        expiryExitTime: draft.expiryExitTime,
        buybackThreshold: Number(draft.buybackThreshold),
      },
      "Settings saved.",
    );
  }

  const field = (key: string, label: string, hint: string, width = 90) => (
    <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12 }}>
      <span style={{ color: "var(--muted)", fontWeight: 600 }}>{label}</span>
      <input value={draft[key] ?? ""} onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))} style={{ width, fontSize: 13, padding: "3px 6px" }} />
      <span className="pcr-oi-caption">{hint}</span>
    </label>
  );
  const chips = (key: string, values: number[], fmt: (v: number) => string) => (
    <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 4 }}>
      {values.map((v) => (
        <button
          key={v}
          type="button"
          className={`button ${Number(draft[key]) === v ? "" : "secondary"}`}
          style={{ padding: "2px 8px", fontSize: 12 }}
          onClick={() => setDraft((d) => ({ ...d, [key]: String(v) }))}
        >
          {fmt(v)}
        </button>
      ))}
    </div>
  );

  return (
    <CollapsibleSection
      id="nifty-strangle-settings"
      title="Settings"
      aside={
        <span className="pcr-oi-caption">
          {config.multiplier}× straddle · SL {config.stopLossPercent}% · {config.lots} lots ({config.quantity}) · min ₹{config.minPremium} · entry {config.entryTime}
        </span>
      }
    >
      <div style={{ display: "flex", gap: 22, flexWrap: "wrap", alignItems: "flex-start" }}>
        <div>
          {field("multiplier", "Strike distance (× ATM straddle)", "")}
          {chips("multiplier", [1.6, 1.8, 2, 2.2, 2.5], (v) => `${v}×`)}
        </div>
        <div>
          {field("stopLossPercent", "Stop loss per leg (% loss)", "100% = exit at 2× the selling price")}
          {chips("stopLossPercent", [50, 100, 150, 200], (v) => `${v}%`)}
        </div>
        {field("lots", "Lots per leg", `${config.lotSize} per lot`, 70)}
        {field("minPremium", "Min premium per leg ₹", "step in until a strike bids at least this", 70)}
        {field("entryTime", "Entry from (IST)", "day before expiry", 70)}
        {field("entryWindowEnd", "until", "retries each poll", 70)}
        {field("expiryExitTime", "Buy back at (IST)", "on expiry day", 70)}
        {field("buybackThreshold", "if worth > ₹", "else let it expire", 70)}
      </div>
      <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", marginTop: 12, fontSize: 13 }}>
        <label style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={config.enabled} onChange={(e) => onSave({ enabled: e.target.checked })} disabled={busy} />
          Automatic entry before each expiry
        </label>
        <button type="button" className="button" onClick={save} disabled={busy}>
          <Save size={14} /> Save settings
        </button>
        <button
          type="button"
          className="button secondary"
          disabled={busy || !config.liveOrdersAllowed}
          onClick={() =>
            config.mode === "live"
              ? onSave({ mode: "paper" }, "Mode set to paper.")
              : window.confirm("Switch NIFTY Strangle to LIVE Dhan orders?") && onSave({ mode: "live" }, "Mode set to LIVE.")
          }
        >
          {config.mode === "live" ? "Switch to paper" : "Switch to LIVE"}
        </button>
        <span className="pcr-oi-caption">
          {config.liveOrdersAllowed
            ? "Live orders are allowed on the server -- market orders (MARGIN product, held overnight); stops are watched by the app."
            : "Live trading is locked on the server (NIFTY_STRANGLE_LIVE_ORDER_ENABLED=false) -- paper only."}
        </span>
      </div>
    </CollapsibleSection>
  );
}

function PlanView({ plan }: { plan: NiftyStranglePlan | null }) {
  if (!plan) return <p className="pcr-oi-caption">Loading the option chain…</p>;
  const legs = plan.legs ?? {};
  return (
    <div>
      {plan.error ? <div className="alert warning" style={{ margin: "0 0 8px" }}>No trade would be placed right now: {plan.error}</div> : null}
      {plan.spot ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {[
            { label: "Entry", value: day(plan.entryDate), caption: `${plan.config.entryTime}–${plan.config.entryWindowEnd} IST` },
            { label: "Expiry", value: day(plan.expiry), caption: `buy back at ${plan.config.expiryExitTime} if > ₹${plan.config.buybackThreshold}` },
            { label: "NIFTY spot", value: num(plan.spot), caption: `ATM ${num(plan.atmStrike, 0)}` },
            { label: "ATM straddle", value: num(plan.straddle), caption: `× ${plan.multiplier} = ${num(plan.distance, 0)} pts` },
            { label: "Credit", value: inr(plan.credit), caption: `${plan.config.lots} lots × ${plan.config.lotSize} per leg` },
            { label: "Net if both expire", value: inr(plan.netIfExpire), caption: `after ₹${num(plan.sellCharges, 0)} sell charges`, color: "var(--green)" },
            { label: "If both legs stop out", value: inr(plan.lossIfBothStopped), caption: "at the stop price (gaps can be worse)", color: "var(--red)" },
          ].map((m) => (
            <div key={m.label} className="metric metric-compact" style={{ flex: "1 1 150px" }}>
              <span>{m.label}</span>
              <strong style={{ color: m.color }}>{m.value}</strong>
              <span className="pcr-oi-caption"><ToneText text={m.caption} /></span>
            </div>
          ))}
        </div>
      ) : null}
      {legs.CE || legs.PE ? (
        <>
          <div style={{ marginTop: 10 }}>
            <StrikeDistanceMap
              id="nifty-strangle-plan"
              spot={plan.spot}
              legs={(["PE", "CE"] as const)
                .filter((s) => legs[s])
                .map((s) => ({ key: s, strike: legs[s]!.strike, label: `${legs[s]!.strike.toLocaleString("en-IN")} ${s}`, short: true }))}
              marks={[0.5, 1, 1.5, 2, 2.5]}
            />
          </div>
          <div style={{ overflowX: "auto", width: 0, minWidth: "100%" }}>
            <table>
              <thead>
                <tr>
                  <th>Leg</th>
                  <th>Formula level</th>
                  <th>Strike</th>
                  <th>From spot</th>
                  <th>Bid / Ask</th>
                  <th>LTP</th>
                  <th>Delta</th>
                  <th>IV</th>
                  <th>OI (lots)</th>
                  <th>Sell at</th>
                  <th>Stop loss</th>
                </tr>
              </thead>
              <tbody>
                {(["PE", "CE"] as const).map((side) => {
                  const leg = legs[side];
                  if (!leg) return null;
                  return (
                    <tr key={side}>
                      <td>
                        <span className="badge sell">SELL {side}</span>
                      </td>
                      <td>{num(leg.target, 0)}</td>
                      <td>
                        <strong>{leg.strike.toLocaleString("en-IN")}</strong>
                        {leg.steppedIn ? <span className="subtext">stepped in from {leg.formulaStrike.toLocaleString("en-IN")} (bid under min)</span> : null}
                      </td>
                      <td>{num(leg.distancePercent)}%</td>
                      <td>
                        {num(leg.bid)} / {num(leg.ask)}
                      </td>
                      <td>{num(leg.ltp)}</td>
                      <td>{num(leg.delta)}</td>
                      <td>{num(leg.iv, 1)}</td>
                      <td>{leg.oiLots.toLocaleString("en-IN")}</td>
                      <td>{num(leg.sellAt)}</td>
                      <td>{num(leg.slPrice)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}

function OpenTrade({ trade: t, busy, onCloseLeg }: { trade: NiftyStrangleTrade; busy: string | null; onCloseLeg: (id: number, label: string) => void }) {
  const live = t.legs.find((l) => l.lastLtp != null);
  return (
    <div className="strategy-chart-card">
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "baseline" }}>
        <strong>
          #{t.id} · expiry {day(t.expiry)} · {t.lots} lots per leg
        </strong>
        <span className="pcr-oi-caption">
          {t.mode.toUpperCase()} · entered {ist(t.entryTime)} at spot {num(t.spot, 0)} · straddle {num(t.straddle)} × {t.multiplier} = {num(t.distance, 0)} pts
        </span>
        <strong style={{ marginLeft: "auto", color: tone(t.grossPnl) }}>
          P&amp;L {inr(t.grossPnl)} <span className="pcr-oi-caption">net {inr(t.netPnl)}</span>
        </strong>
      </div>
      {t.notes ? <p className="pcr-oi-caption">{t.notes}</p> : null}
      <div style={{ overflowX: "auto", width: 0, minWidth: "100%", marginTop: 8 }}>
        <table>
          <thead>
            <tr>
              <th>Leg</th>
              <th>Sold</th>
              <th>Now (bid / ask)</th>
              <th>Stop</th>
              <th>To stop</th>
              <th>P&amp;L</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {t.legs.map((l) => {
              const label = `${l.strike.toLocaleString("en-IN")} ${l.optionType}`;
              const toStop = l.slPrice && l.lastLtp ? (l.slPrice / l.lastLtp - 1) * 100 : null;
              return (
                <tr key={l.id}>
                  <td>
                    <span className="badge sell">SELL</span> {label}
                  </td>
                  <td>{num(l.entryPrice)}</td>
                  <td>
                    {num(l.status === "CLOSED" ? l.exitPrice : l.lastLtp)}{" "}
                    <span className="pcr-oi-caption">
                      ({num(l.lastBid)} / {num(l.lastAsk)})
                    </span>
                  </td>
                  <td>{num(l.slPrice)}</td>
                  <td style={{ color: toStop != null && toStop < 30 ? "var(--red)" : undefined }}>{toStop != null && l.status === "OPEN" ? `+${num(toStop, 0)}%` : "—"}</td>
                  <td style={{ color: tone(l.pnl) }}>{inr(l.pnl)}</td>
                  <td>{l.status === "CLOSED" ? EXIT_LABEL[l.exitReason ?? ""] ?? l.exitReason : l.status}</td>
                  <td>
                    {l.status === "OPEN" ? (
                      <button type="button" className="button secondary" style={{ padding: "2px 8px", fontSize: 12 }} disabled={!!busy} onClick={() => onCloseLeg(l.id, label)}>
                        <SquareArrowOutUpRight size={12} /> Buy back
                      </button>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div style={{ marginTop: 8 }}>
        <StrikeDistanceMap
          id={`nifty-strangle-${t.id}`}
          spot={t.spot}
          legs={t.legs.filter((l) => l.status === "OPEN").map((l) => ({ key: String(l.id), strike: l.strike, label: `${l.strike.toLocaleString("en-IN")} ${l.optionType}`, short: true }))}
          marks={[0.5, 1, 1.5, 2, 2.5]}
        />
        <p className="pcr-oi-caption">Distances shown from the entry spot; last quote {ist(live?.lastUpdate)}.</p>
      </div>
    </div>
  );
}

function TradesTable({ trades }: { trades: NiftyStrangleTrade[] }) {
  if (!trades.length) return <p className="pcr-oi-caption" style={{ margin: 0 }}>No trades yet.</p>;
  return (
    <div style={{ overflowX: "auto", width: 0, minWidth: "100%" }}>
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Mode</th>
            <th>Entered (IST)</th>
            <th>Expiry</th>
            <th>Spot</th>
            <th>Strikes (PE / CE)</th>
            <th>Setup</th>
            <th>Credit</th>
            <th>Exits</th>
            <th>Gross</th>
            <th>Charges</th>
            <th>Net</th>
            <th>Cumulative net</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => {
            const pe = t.legs.find((l) => l.optionType === "PE");
            const ce = t.legs.find((l) => l.optionType === "CE");
            return (
              <tr key={t.id}>
                <td>{t.id}</td>
                <td>{t.mode}</td>
                <td>{ist(t.entryTime)}</td>
                <td>{day(t.expiry)}</td>
                <td>{num(t.spot, 0)}</td>
                <td>
                  {pe ? pe.strike.toLocaleString("en-IN") : "—"} / {ce ? ce.strike.toLocaleString("en-IN") : "—"}
                </td>
                <td className="pcr-oi-caption" style={{ fontStyle: "normal" }}>
                  {t.multiplier}× · SL {t.stopLossPercent}% · {t.lots} lots
                </td>
                <td>{inr(t.credit)}</td>
                <td style={{ fontSize: 12 }}>
                  {t.legs
                    .map((l) => `${l.optionType}: ${l.status === "CLOSED" ? `${EXIT_LABEL[l.exitReason ?? ""] ?? l.exitReason} @ ${num(l.exitPrice)}` : l.status}`)
                    .join(" · ")}
                </td>
                <td style={{ color: tone(t.grossPnl) }}>{inr(t.grossPnl)}</td>
                <td>{inr(t.charges)}</td>
                <td style={{ color: tone(t.netPnl) }}>
                  <strong>{inr(t.netPnl)}</strong>
                </td>
                <td style={{ color: (cumulativeNet(trades, (x) => x.id, (x) => x.entryTime, (x) => x.netPnl, (x) => String(x.status ?? "closed").toUpperCase() === "CLOSED").get(t.id) ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>{cumulativeNet(trades, (x) => x.id, (x) => x.entryTime, (x) => x.netPnl, (x) => String(x.status ?? "closed").toUpperCase() === "CLOSED").get(t.id) != null ? inr(cumulativeNet(trades, (x) => x.id, (x) => x.entryTime, (x) => x.netPnl, (x) => String(x.status ?? "closed").toUpperCase() === "CLOSED").get(t.id) as number) : "—"}</td>
                <td>{t.status}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function istTick(time: Time): string {
  if (typeof time !== "number") return String(time);
  return new Date(time * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
}

const LEG_EXIT: Record<string, string> = { stop_loss: "stop loss hit", expiry_buyback: "bought back before expiry (still worth more than the threshold)", expired: "expired / settled at expiry", manual: "closed manually" };

function niftyStrangleNotes(trades: NiftyStrangleTrade[]): TradeNote[] {
  return trades.flatMap((t) => {
    const legs = t.legs.filter((l) => l.entryPrice != null);
    const entry: TradeNote = {
      time: t.entryTime,
      kind: "entry",
      label: `#${t.id} sell`,
      color: "#b23c35",
      title: `Entry #${t.id} · sold ${legs.map((l) => `${l.strike} ${l.optionType}`).join(" / ")} · ${t.lots} lots`,
      lines: [
        `${istTime(t.entryTime)} · NIFTY ${num(t.spot, 0)} · expiry ${day(t.expiry)}${t.trigger === "manual" ? " · manual" : ""}`,
        `Why: scheduled entry the day before expiry -- strikes at spot ± ${t.multiplier} × ATM straddle ${num(t.straddle)} = ${num(t.distance, 0)} pts`,
        `Credit ${inr(t.credit)} · stop each leg at +${t.stopLossPercent}% (${legs.map((l) => `${l.optionType} ${num(l.slPrice)}`).join(", ")})`,
        t.notes ?? "",
      ],
    };
    const exits: TradeNote[] = legs
      .filter((l) => l.exitTime)
      .map((l) => ({
        time: l.exitTime as number,
        kind: "exit",
        label: `${l.optionType} ${inr(l.pnl)}`,
        color: (l.pnl ?? 0) >= 0 ? "#1b7a4b" : "#b23c35",
        title: `Exit #${t.id} · ${l.strike} ${l.optionType} @ ${num(l.exitPrice)} · ${inr(l.pnl)}`,
        lines: [`${istTime(l.exitTime)} · sold at ${num(l.entryPrice)}`, `Why: ${LEG_EXIT[l.exitReason ?? ""] ?? l.exitReason}`],
      }));
    return [entry, ...exits];
  });
}

function SpotChart({ open, trades }: { open: NiftyStrangleTrade | null; trades: NiftyStrangleTrade[] }) {
  const [handles, setHandles] = useState<{ chart: IChartApi; series: ISeriesApi<"Line"> } | null>(null);
  const [barTimes, setBarTimes] = useState<number[]>([]);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const linesRef = useRef<IPriceLine[]>([]);
  const [error, setError] = useState<string | null>(null);

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
    seriesRef.current = chart.addSeries(LineSeries, { color: "#0f6b78", lineWidth: 2, title: "NIFTY" });
    chartRef.current = chart;
    setHandles({ chart, series: seriesRef.current });
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
      linesRef.current = [];
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const r = await getNiftyStrangleSpotChart();
        if (cancelled || !seriesRef.current) return;
        setError(r.error ?? null);
        const seen = new Set<number>();
        const rows = r.candles.filter((c) => (seen.has(c.time) ? false : (seen.add(c.time), true)));
        seriesRef.current.setData(rows.map((c) => ({ time: c.time as UTCTimestamp, value: c.close })));
        setBarTimes(rows.map((c) => c.time));
        for (const line of linesRef.current) seriesRef.current.removePriceLine(line);
        linesRef.current = (open?.legs ?? [])
          .filter((l) => l.status === "OPEN")
          .map((l) =>
            seriesRef.current!.createPriceLine({
              price: l.strike,
              color: "#b23c35",
              lineWidth: 1,
              lineStyle: 2,
              axisLabelVisible: true,
              title: `${l.optionType} ${l.strike}`,
            }),
          );
        chartRef.current?.timeScale().fitContent();
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : "Chart unavailable.");
      }
    }
    load();
    const timer = window.setInterval(load, 60000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [open]);

  const notes = useMemo(() => niftyStrangleNotes(trades), [trades]);
  const tooltip = useTradeMarkers(handles?.chart ?? null, handles?.series ?? null, notes, 300, barTimes);

  return (
    <div>
      {error ? <p className="pcr-oi-caption">{error}</p> : null}
      <p className="pcr-oi-caption" style={{ margin: "0 0 4px" }}>▲ entries, ▼ leg exits -- hover an arrow for the reason · dashed: open legs&apos; strikes</p>
      <div style={{ position: "relative" }}>
        <div ref={containerRef} style={{ width: "100%", height: 260 }} />
        {tooltip}
      </div>
    </div>
  );
}
