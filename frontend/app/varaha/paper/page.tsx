"use client";

import { ColorType, createChart, createSeriesMarkers, IChartApi, IPriceLine, ISeriesApi, LineSeries, MouseEventParams, Time, UTCTimestamp } from "lightweight-charts";
import { Play, RefreshCw, Save, Shapes, SquareArrowOutUpRight } from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";

import CollapsibleSection from "@/components/CollapsibleSection";
import { DailyTotalsTable, groupDailyTotals } from "@/components/DailyTotals";
import VarahaPayoffChart from "@/components/VarahaPayoffChart";
import VarahaTabs from "@/components/VarahaTabs";
import {
  closeVarahaPaperTrade,
  enterVarahaPaperNow,
  getVarahaPaperSpotChart,
  getVarahaPaperState,
  getVarahaPaperTrade,
  getVarahaPaperTrades,
  updateVarahaPaperConfig,
} from "@/lib/api";
import type { VarahaPaperConfig, VarahaPaperDecision, VarahaPaperState, VarahaPaperTrade } from "@/types/varaha-paper";

const REFRESH_MS = 30000;
const DIRECTION_LABEL: Record<string, string> = { UP: "UP (bullish)", DOWN: "DOWN (bearish)", NO_CLEAR_DIRECTION: "Flat / no clear direction" };
const DIRECTION_COLOR: Record<string, string> = { UP: "var(--green)", DOWN: "var(--red)", NO_CLEAR_DIRECTION: "var(--blue)" };

function inr(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v < 0 ? "−" : ""}₹${Math.abs(Math.round(v)).toLocaleString("en-IN")}`;
}
function num(v: number | null | undefined, d = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
}
function signed(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}`;
}
function tone(v: number | null | undefined): string | undefined {
  if (!v) return undefined;
  return v > 0 ? "var(--green)" : "var(--red)";
}
function ist(e: number | null | undefined, day = true): string {
  if (!e) return "—";
  return new Date(e * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", ...(day ? { day: "2-digit", month: "short" } : {}), hour: "2-digit", minute: "2-digit", hour12: false });
}
function dayLabel(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(`${iso}T00:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", weekday: "short", day: "2-digit", month: "short" });
}

export default function VarahaPaperPage() {
  const [state, setState] = useState<VarahaPaperState | null>(null);
  const [trades, setTrades] = useState<VarahaPaperTrade[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const [s, t] = await Promise.all([getVarahaPaperState(), getVarahaPaperTrades()]);
      setState(s);
      setTrades(t.trades);
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load.");
    }
  }
  useEffect(() => {
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  async function act(fn: () => Promise<string>) {
    setBusy(true);
    try {
      setMessage(await fn());
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Action failed.");
    } finally {
      setBusy(false);
    }
  }

  const config = state?.config;
  const closed = trades.filter((t) => t.status === "CLOSED");
  const net = closed.reduce((a, t) => a + t.netPnl, 0);
  const wins = closed.filter((t) => t.netPnl > 0).length;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Shapes size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Varaha
          </h1>
          <p>
            Paper trades from the {config?.decisionTime ?? "15:00"} daily decision: UP → CE butterfly, DOWN → PE butterfly, flat → defined-risk strangle (iron
            condor). One position at a time, {config?.lots ?? 5} lots. Exits: target / stop, a direction flip at the next decision, or{" "}
            {config?.exitTime ?? "15:15"} the day before expiry.
          </p>
        </div>
        <div className="toolbar" style={{ alignItems: "center" }}>
          <span className="status-live on" style={{ whiteSpace: "nowrap" }}>{state?.mode === "live" ? "LIVE" : "PAPER"}</span>
          <span className={`status-live ${config?.enabled ? "on" : ""}`} style={{ whiteSpace: "nowrap" }}>
            {config ? (config.enabled ? "Auto trading on" : "Auto trading paused") : "…"}
          </span>
          <button type="button" className="button secondary" onClick={load} style={{ whiteSpace: "nowrap" }}>
            <RefreshCw size={14} /> Refresh
          </button>
          <button
            type="button"
            className="button"
            disabled={busy || !!state?.openTrade}
            style={{ whiteSpace: "nowrap" }}
            onClick={() =>
              window.confirm("Enter the paper trade for the latest Varaha decision now?") &&
              act(async () => {
                const r = await enterVarahaPaperNow();
                return r.message ? `${r.status}: ${r.message}` : `Trade ${r.status}.`;
              })
            }
          >
            <Play size={14} /> Enter now
          </button>
        </div>
      </header>
      <VarahaTabs />

      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}
      {state?.openTrade?.needsAttention ? <div className="alert error">Manual action needed: {state.openTrade.needsAttention}</div> : null}

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        <Metric label="Paper results" value={inr(net)} caption={`${closed.length} closed · ${closed.length ? Math.round((wins / closed.length) * 100) : 0}% winners`} color={tone(net)} />
        <Metric label="Open position" value={state?.openTrade ? state.openTrade.structureLabel : "None"} caption={state?.openTrade ? `#${state.openTrade.id} · exp ${dayLabel(state.openTrade.expiry)}` : `next entry at the ${config?.decisionTime ?? "15:00"} decision`} />
        <Metric label="Size" value={`${config?.lots ?? 5} lots`} caption={`${(config?.lots ?? 5) * (config?.lotSize ?? 65)} qty per leg-unit · max-loss cap ${inr(config?.maxLossInr)}`} />
        <Metric label="Market" value={state?.marketOpen ? "Open" : "Closed"} caption="positions checked every 30 s" />
      </div>

      <CollapsibleSection id="varaha-paper-chart" title="NIFTY with paper entries and exits" aside={<span className="pcr-oi-caption">hover an arrow for the reason</span>}>
        <TradesChart trades={trades} open={state?.openTrade ?? null} />
      </CollapsibleSection>

      <CollapsibleSection id="varaha-paper-decision" title="Latest decision → paper trade" aside={state?.preview ? <span className="pcr-oi-caption">{dayLabel(state.preview.sessionDate)} · rec #{state.preview.decision.recId} ({state.preview.decision.trigger})</span> : null}>
        <DecisionView state={state} />
      </CollapsibleSection>

      <CollapsibleSection id="varaha-paper-open" title={`Open position (${state?.openTrade ? 1 : 0})`}>
        {state?.openTrade ? (
          <OpenTrade
            trade={state.openTrade}
            config={config!}
            busy={busy}
            onClose={() =>
              window.confirm(`Close #${state.openTrade!.id} now?`) &&
              act(async () => {
                const r = await closeVarahaPaperTrade(state.openTrade!.id);
                return `#${state.openTrade!.id}: ${r.status}`;
              })
            }
          />
        ) : (
          <p className="pcr-oi-caption" style={{ margin: 0 }}>
            No open position. The next one opens after the {config?.decisionTime ?? "15:00"} decision (shown above).
          </p>
        )}
      </CollapsibleSection>

      <CollapsibleSection id="varaha-paper-trades" title={`All paper trades (${trades.length})`}>
        <TradesTable trades={trades} />
      </CollapsibleSection>

      <CollapsibleSection id="varaha-paper-pnl" title="Daily P&L" defaultOpen={false}>
        <DailyTotalsTable rows={groupDailyTotals(closed, (t) => t.exitTime, (t) => t.grossPnl, (t) => t.netPnl)} />
      </CollapsibleSection>

      <CollapsibleSection id="varaha-paper-log" title={`Log (${state?.events.length ?? 0})`} defaultOpen={false}>
        <table style={{ fontSize: 12 }}>
          <tbody>
            {(state?.events ?? []).map((e, i) => (
              <tr key={i}>
                <td style={{ whiteSpace: "nowrap" }}>{ist(e.time)}</td>
                <td>{e.kind}</td>
                <td>{e.text}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CollapsibleSection>

      {config ? <Settings config={config} onSaved={load} /> : null}
    </section>
  );
}

function Metric({ label, value, caption, color }: { label: string; value: string; caption?: string; color?: string }) {
  return (
    <div className="metric metric-compact" style={{ flex: "1 1 160px" }}>
      <span>{label}</span>
      <strong style={{ color }}>{value}</strong>
      {caption ? <span className="pcr-oi-caption">{caption}</span> : null}
    </div>
  );
}

function DecisionMetrics({ d }: { d: VarahaPaperDecision }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      <Metric
        label="Direction used"
        value={DIRECTION_LABEL[d.effective ?? ""] ?? d.effective ?? "—"}
        caption={d.override ? `manual override ${d.override} (engine said ${d.direction})` : `engine call · threshold ${num(d.threshold, 0)}%`}
        color={DIRECTION_COLOR[d.effective ?? ""]}
      />
      <Metric label="Bullish / bearish signals" value={`${d.bullish ?? "—"} / ${d.bearish ?? "—"}`} caption={`confidence ${num(d.bullishConfidence, 0)}% / ${num(d.bearishConfidence, 0)}% · neutral ${d.neutral ?? "—"}`} />
      <Metric label="Move class" value={d.moveClass ?? "—"} caption={`score ${d.moveScore ?? "—"}/${d.maxMoveScore ?? "—"} · expected move ±${num(d.expectedMove, 0)}`} />
      <Metric label="Engine's own pick" value={d.engineStructure ?? "—"} caption={`recommendation status ${d.status ?? "—"}`} />
    </div>
  );
}

function DecisionView({ state }: { state: VarahaPaperState | null }) {
  const p = state?.preview;
  if (!p) return <p className="pcr-oi-caption">No Varaha decision stored yet.</p>;
  const c = p.candidate;
  return (
    <div>
      <DecisionMetrics d={p.decision} />
      <p style={{ margin: "10px 0 6px", fontSize: 13 }}>
        <strong>Paper trade:</strong> {p.structureLabel ?? "none"} — {p.why}
      </p>
      {c ? (
        <div style={{ overflowX: "auto", width: 0, minWidth: "100%" }}>
          <table style={{ fontSize: 12 }}>
            <thead>
              <tr>
                <th>Leg</th>
                <th>Ratio</th>
                <th>Strike</th>
                <th>Price (bid / ask)</th>
                <th>Delta</th>
              </tr>
            </thead>
            <tbody>
              {c.legs.map((l, i) => (
                <tr key={i}>
                  <td>
                    <span className={`badge ${l.action === "BUY" ? "buy" : "sell"}`}>{l.action}</span> {l.optionType}
                  </td>
                  <td>×{l.qty}</td>
                  <td>{l.strike.toLocaleString("en-IN")}</td>
                  <td>
                    {num(l.price)} <span className="pcr-oi-caption">({num(l.bid)} / {num(l.ask)})</span>
                  </td>
                  <td>{num(l.delta)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="pcr-oi-caption">
            {c.variantLabel} · expiry {dayLabel(c.expiry)} · {c.premiumType.toLowerCase()} {num(Math.abs(c.netPremiumPoints))} pts · max profit {inr(Math.abs(c.maxProfit))} / max loss{" "}
            {inr(Math.abs(c.maxLoss))} at {c.lots} lot{c.lots > 1 ? "s" : ""} (paper trade scales to the configured lots) · breakevens {c.breakevens.map((b) => num(b, 0)).join(" / ")}
          </p>
        </div>
      ) : null}
    </div>
  );
}

function OpenTrade({ trade: t, config, busy, onClose }: { trade: VarahaPaperTrade; config: VarahaPaperConfig; busy: boolean; onClose: () => void }) {
  const mult = t.lots * t.lotSize;
  const toTarget = t.targetPoints - t.pnlPoints;
  const toStop = t.pnlPoints - t.stopPoints;
  const flipRule =
    t.structure === "CE_BUTTERFLY" ? "closes if the decision turns DOWN" : t.structure === "PE_BUTTERFLY" ? "closes if the decision turns UP" : "closes if the decision is UP or DOWN (no longer flat)";
  return (
    <div className="strategy-chart-card">
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "baseline" }}>
        <strong>
          #{t.id} · {t.structureLabel} · {t.variantLabel} · exp {dayLabel(t.expiry)}
        </strong>
        <span className="pcr-oi-caption">
          {t.mode.toUpperCase()} · direction <span style={{ color: DIRECTION_COLOR[t.direction] }}>{DIRECTION_LABEL[t.direction] ?? t.direction}</span> · entered {ist(t.entryTime)} at NIFTY{" "}
          {num(t.entrySpot, 0)} ({t.trigger})
        </span>
        <button type="button" className="button secondary" onClick={onClose} disabled={busy} style={{ marginLeft: "auto" }}>
          <SquareArrowOutUpRight size={14} /> Close now
        </button>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 10 }}>
        <Metric label={t.premiumType === "DEBIT" ? "Debit paid" : "Credit received"} value={`${num(Math.abs(t.entryValue))} pts`} caption={inr(Math.abs(t.entryValue) * mult)} />
        <Metric label="P&L now" value={inr(t.grossPnl)} caption={`${signed(t.pnlPoints)} pts · net ${inr(t.netPnl)} · ${ist(t.lastUpdate)}`} color={tone(t.grossPnl)} />
        <Metric label="Best / worst" value={`${signed(t.bestPoints)} / ${signed(t.worstPoints)}`} caption="pts seen" />
        <Metric label="Max profit / loss" value={`${inr(t.maxProfit)} / ${inr(-t.maxLoss)}`} caption={`breakevens ${t.breakevens.map((b) => num(b, 0)).join(" / ")}`} />
        <Metric label="NIFTY" value={num(t.lastSpot, 0)} caption={`entry ${num(t.entrySpot, 0)}`} />
      </div>
      <h4 style={{ margin: "12px 0 4px", fontSize: 13 }}>Legs ({t.lots} lots × {t.lotSize})</h4>
      <div style={{ overflowX: "auto", width: 0, minWidth: "100%" }}>
        <table style={{ fontSize: 12 }}>
          <thead>
            <tr>
              <th>Leg</th>
              <th>Strike</th>
              <th>Qty</th>
              <th>Entry (bid / ask / ltp)</th>
              <th>Now (bid / ask / ltp)</th>
              <th>P&amp;L</th>
              <th>Order</th>
            </tr>
          </thead>
          <tbody>
            {t.legs.map((l) => (
              <tr key={l.id}>
                <td>
                  <span className={`badge ${l.action === "BUY" ? "buy" : "sell"}`}>{l.action}</span> {l.optionType} ×{l.ratio}
                </td>
                <td>{l.strike.toLocaleString("en-IN")}</td>
                <td>{l.quantity}</td>
                <td>
                  <strong>{num(l.entryPrice)}</strong> <span className="pcr-oi-caption">({num(l.entryBid)} / {num(l.entryAsk)} / {num(l.entryLtp)})</span>
                </td>
                <td>
                  <strong>{num(l.lastLtp)}</strong> <span className="pcr-oi-caption">({num(l.lastBid)} / {num(l.lastAsk)})</span>
                </td>
                <td style={{ color: tone(l.pnl) }}>{inr(l.pnl)}</td>
                <td className="pcr-oi-caption">{l.entryOrderId ?? "paper"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h4 style={{ margin: "12px 0 4px", fontSize: 13 }}>How this trade exits (first to happen)</h4>
      <div style={{ overflowX: "auto", width: 0, minWidth: "100%" }}>
        <table style={{ fontSize: 12 }}>
          <thead>
            <tr>
              <th>Exit</th>
              <th>Rule</th>
              <th>Distance now</th>
              <th>Result if it fires</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Target</td>
              <td>
                {t.premiumType === "DEBIT" ? `+${config.butterflyTargetPercent}% of max profit` : `+${config.condorTargetPercent}% of the credit`} = +{num(t.targetPoints)} pts
              </td>
              <td>{toTarget <= 0 ? "reached" : `${num(toTarget)} pts to go`}</td>
              <td style={{ color: "var(--green)" }}>{inr(t.target)}</td>
            </tr>
            <tr>
              <td>Stop loss</td>
              <td>
                {t.premiumType === "DEBIT" ? `−${config.butterflyStopPercent}% of the debit` : `costs ${config.condorStopMultiple}× the credit to close`} = {num(t.stopPoints)} pts
              </td>
              <td>{toStop <= 0 ? "hit" : `${num(toStop)} pts away`}</td>
              <td style={{ color: "var(--red)" }}>{inr(t.stop)}</td>
            </tr>
            <tr>
              <td>Direction re-check</td>
              <td>
                at the next {config.decisionTime} decision, {flipRule}
                {config.flipExit ? "" : " (switched off)"}
              </td>
              <td>daily</td>
              <td>current P&amp;L</td>
            </tr>
            <tr>
              <td>Time</td>
              <td>{ist(t.exitBy)} IST (day before expiry)</td>
              <td>{t.exitBy > Date.now() / 1000 ? `in ${Math.floor((t.exitBy - Date.now() / 1000) / 3600)} h` : "due"}</td>
              <td>current P&amp;L</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 440px), 1fr))", gap: 12, marginTop: 12 }}>
        <div style={{ minWidth: 0 }}>
          {t.payoff?.length ? (
            <VarahaPayoffChart chartId={`varaha-paper-${t.id}`} label={`${t.structureLabel} (${t.lots} lots)`} points={t.payoff} breakevens={t.breakevens} spot={t.lastSpot ?? t.entrySpot} expectedMove={t.decision.expectedMove} />
          ) : null}
        </div>
        <div style={{ minWidth: 0 }}>
          <h4 style={{ margin: "0 0 4px", fontSize: 13 }}>P&amp;L since entry (₹)</h4>
          <PnlChart trade={t} />
        </div>
      </div>
      <h4 style={{ margin: "12px 0 4px", fontSize: 13 }}>Why this trade</h4>
      <DecisionMetrics d={t.decision} />
      <p className="pcr-oi-caption">{t.decision.why}</p>
    </div>
  );
}

type ChartNote = { kind: "entry" | "exit"; trade: VarahaPaperTrade };

const SHORT_NAME: Record<string, string> = { CE_BUTTERFLY: "CE bfly", PE_BUTTERFLY: "PE bfly", IRON_CONDOR: "strangle" };

function TradesChart({ trades, open }: { trades: VarahaPaperTrade[]; open: VarahaPaperTrade | null }) {
  const [picked, setPicked] = useState<number | null>(null);
  const oldest = trades.length ? Math.min(...trades.map((t) => t.entryTime)) : null;
  const days = picked ?? (oldest ? Math.min(60, Math.max(5, Math.ceil((Date.now() / 1000 - oldest) / 86400) + 1)) : 10);
  const [tip, setTip] = useState<{ x: number; y: number; notes: ChartNote[] } | null>(null);
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const markersRef = useRef<ReturnType<typeof createSeriesMarkers<Time>> | null>(null);
  const linesRef = useRef<IPriceLine[]>([]);
  const notesRef = useRef<Map<number, ChartNote[]>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const bucket = (t: number) => Math.floor(t / 300) * 300;

  useEffect(() => {
    if (!ref.current || chartRef.current) return;
    const chart = createChart(ref.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#17212b" },
      grid: { vertLines: { color: "#e8edeb" }, horzLines: { color: "#e8edeb" } },
      width: ref.current.clientWidth,
      height: 300,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: tick },
      localization: { timeFormatter: tick },
    });
    seriesRef.current = chart.addSeries(LineSeries, { color: "#0f6b78", lineWidth: 2, title: "NIFTY" });
    markersRef.current = createSeriesMarkers(seriesRef.current, []);
    chartRef.current = chart;
    const onMove = (param: MouseEventParams<Time>) => {
      if (!param.point || param.time === undefined) {
        setTip(null);
        return;
      }
      const t = Number(param.time);
      // markers sit on 5-min buckets; accept the hovered bucket or one either side
      const notes = [t, t - 300, t + 300].flatMap((k) => notesRef.current.get(k) ?? []);
      setTip(notes.length ? { x: param.point.x, y: param.point.y, notes } : null);
    };
    chart.subscribeCrosshairMove(onMove);
    const observer = new ResizeObserver(() => ref.current && chart.applyOptions({ width: ref.current.clientWidth }));
    observer.observe(ref.current);
    return () => {
      chart.unsubscribeCrosshairMove(onMove);
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      linesRef.current = [];
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    getVarahaPaperSpotChart(days)
      .then((r) => {
        if (cancelled || !seriesRef.current) return;
        setError(r.error ?? null);
        const seen = new Set<number>();
        seriesRef.current.setData(r.candles.filter((c) => (seen.has(c.time) ? false : (seen.add(c.time), true))).map((c) => ({ time: c.time as UTCTimestamp, value: c.close })));
        const first = r.candles[0]?.time ?? 0;
        const notes = new Map<number, ChartNote[]>();
        const markers = [];
        for (const t of trades) {
          if (t.entryTime >= first) {
            const k = bucket(t.entryTime);
            notes.set(k, [...(notes.get(k) ?? []), { kind: "entry", trade: t }]);
            markers.push({
              time: k as UTCTimestamp,
              position: "belowBar" as const,
              color: t.direction === "UP" ? "#1b7a4b" : t.direction === "DOWN" ? "#b23c35" : "#0f6b78",
              shape: "arrowUp" as const,
              text: `#${t.id} ${SHORT_NAME[t.structure] ?? t.structure}`,
            });
          }
          if (t.exitTime && t.exitTime >= first) {
            const k = bucket(t.exitTime);
            notes.set(k, [...(notes.get(k) ?? []), { kind: "exit", trade: t }]);
            markers.push({ time: k as UTCTimestamp, position: "aboveBar" as const, color: t.netPnl >= 0 ? "#1b7a4b" : "#b23c35", shape: "arrowDown" as const, text: `#${t.id} ${inr(t.netPnl)}` });
          }
        }
        notesRef.current = notes;
        markersRef.current?.setMarkers(markers.sort((a, b) => (a.time as number) - (b.time as number)));
        for (const l of linesRef.current) seriesRef.current.removePriceLine(l);
        linesRef.current = open
          ? open.breakevens.map((b) => seriesRef.current!.createPriceLine({ price: b, color: "#b7791f", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: `#${open.id} breakeven` }))
          : [];
        chartRef.current?.timeScale().fitContent();
      })
      .catch((exc) => !cancelled && setError(exc instanceof Error ? exc.message : "Chart unavailable."));
    return () => {
      cancelled = true;
    };
  }, [days, trades, open]);

  return (
    <div>
      <div style={{ display: "flex", gap: 6, marginBottom: 6, alignItems: "center", flexWrap: "wrap" }}>
        {[5, 10, 20, 60].map((d) => (
          <button key={d} type="button" className={`button ${d === days ? "" : "secondary"}`} style={{ padding: "2px 10px", fontSize: 12 }} onClick={() => setPicked(d)}>
            {d}d
          </button>
        ))}
        <span className="pcr-oi-caption">showing {days} days · ▲ entry (green UP · red DOWN · blue flat) · ▼ exit (net ₹) · dashed: open trade&apos;s breakevens</span>
        {error ? <span className="pcr-oi-caption" style={{ color: "var(--red)" }}>{error}</span> : null}
      </div>
      <div style={{ position: "relative" }}>
        <div ref={ref} style={{ width: "100%", height: 300 }} />
        {tip ? (
          <div
            style={{
              position: "absolute",
              left: Math.min(tip.x + 14, (ref.current?.clientWidth ?? 600) - 330),
              top: Math.max(0, tip.y - 20),
              width: 320,
              background: "var(--surface, #fff)",
              border: "1px solid var(--line)",
              borderRadius: 6,
              boxShadow: "0 4px 14px rgba(0,0,0,0.12)",
              padding: "8px 10px",
              fontSize: 12,
              zIndex: 5,
              pointerEvents: "none",
            }}
          >
            {tip.notes.map((n, i) => (
              <div key={i} style={{ marginBottom: i < tip.notes.length - 1 ? 8 : 0 }}>
                {n.kind === "entry" ? (
                  <>
                    <strong style={{ color: DIRECTION_COLOR[n.trade.direction] }}>
                      ▲ Entry #{n.trade.id} · {n.trade.structureLabel}
                    </strong>
                    <div>
                      {ist(n.trade.entryTime)} · NIFTY {num(n.trade.entrySpot, 0)} · {n.trade.premiumType === "DEBIT" ? "debit" : "credit"} {num(Math.abs(n.trade.entryValue))} pts
                    </div>
                    <div>
                      <strong>Why:</strong> direction {DIRECTION_LABEL[n.trade.direction] ?? n.trade.direction}
                      {n.trade.decision.override ? ` (override; engine said ${n.trade.decision.direction})` : ""} · move {n.trade.decision.moveClass} ({n.trade.decision.moveScore}/
                      {n.trade.decision.maxMoveScore}) · bullish {n.trade.decision.bullish} / bearish {n.trade.decision.bearish}
                    </div>
                    <div className="pcr-oi-caption" style={{ fontStyle: "normal" }}>{n.trade.decision.why}</div>
                  </>
                ) : (
                  <>
                    <strong style={{ color: n.trade.netPnl >= 0 ? "var(--green)" : "var(--red)" }}>
                      ▼ Exit #{n.trade.id} · {inr(n.trade.netPnl)} net
                    </strong>
                    <div>
                      {ist(n.trade.exitTime)} · NIFTY {num(n.trade.exitSpot, 0)} · {signed(n.trade.pnlPoints)} pts
                    </div>
                    <div>
                      <strong>Why:</strong> {n.trade.exitReason}
                    </div>
                    <div className="pcr-oi-caption" style={{ fontStyle: "normal" }}>
                      {n.trade.structureLabel} held {Math.round(((n.trade.exitTime ?? 0) - n.trade.entryTime) / 3600)} h · target {num(n.trade.targetPoints)} / stop {num(n.trade.stopPoints)} pts
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function tick(t: Time): string {
  return typeof t === "number" ? ist(t) : String(t);
}

function PnlChart({ trade: t }: { trade: VarahaPaperTrade }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const linesRef = useRef<IPriceLine[]>([]);
  useEffect(() => {
    if (!ref.current || chartRef.current) return;
    const chart = createChart(ref.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#17212b" },
      grid: { vertLines: { color: "#e8edeb" }, horzLines: { color: "#e8edeb" } },
      width: ref.current.clientWidth,
      height: 240,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: tick },
      localization: { timeFormatter: tick },
    });
    seriesRef.current = chart.addSeries(LineSeries, { color: "#0f6b78", lineWidth: 2, title: "P&L ₹" });
    chartRef.current = chart;
    const observer = new ResizeObserver(() => ref.current && chart.applyOptions({ width: ref.current.clientWidth }));
    observer.observe(ref.current);
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
    if (!series) return;
    const mult = t.lots * t.lotSize;
    const seen = new Set<number>();
    series.setData((t.marks ?? []).filter((m) => (seen.has(m.time) ? false : (seen.add(m.time), true))).map((m) => ({ time: m.time as UTCTimestamp, value: m.pnl_points * mult })));
    for (const l of linesRef.current) series.removePriceLine(l);
    linesRef.current = [
      series.createPriceLine({ price: t.target, color: "#1b7a4b", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "target" }),
      series.createPriceLine({ price: t.stop, color: "#b23c35", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "stop" }),
    ];
    chartRef.current?.timeScale().fitContent();
  }, [t]);
  return <div ref={ref} style={{ width: "100%", height: 240 }} />;
}

function TradesTable({ trades }: { trades: VarahaPaperTrade[] }) {
  const [open, setOpen] = useState<number | null>(null);
  const [detail, setDetail] = useState<VarahaPaperTrade | null>(null);
  useEffect(() => {
    if (open == null) {
      setDetail(null);
      return;
    }
    getVarahaPaperTrade(open).then(setDetail).catch(() => undefined);
  }, [open]);
  if (!trades.length) return <p className="pcr-oi-caption" style={{ margin: 0 }}>No paper trades yet.</p>;
  return (
    <div style={{ overflowX: "auto", width: 0, minWidth: "100%" }}>
      <p className="pcr-oi-caption" style={{ marginTop: 0 }}>click a row for the decision, every leg&apos;s entry/exit quotes, the payoff and the log</p>
      <table style={{ fontSize: 12 }}>
        <thead>
          <tr>
            <th>#</th>
            <th>Decision</th>
            <th>Direction</th>
            <th>Structure</th>
            <th>Strikes</th>
            <th>Expiry</th>
            <th>Entry</th>
            <th>Debit / credit</th>
            <th>Exit</th>
            <th>Reason</th>
            <th>P&amp;L pts</th>
            <th>Gross</th>
            <th>Charges</th>
            <th>Net</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <Fragment key={t.id}>
              <tr onClick={() => setOpen(open === t.id ? null : t.id)} style={{ cursor: "pointer" }}>
                <td>{t.id}</td>
                <td>{dayLabel(t.sessionDate)}</td>
                <td style={{ color: DIRECTION_COLOR[t.direction] }}>{t.direction === "NO_CLEAR_DIRECTION" ? "FLAT" : t.direction}</td>
                <td>
                  {t.structureLabel} <span className="pcr-oi-caption">{t.variantLabel}</span>
                </td>
                <td className="pcr-oi-caption">{t.legs.map((l) => `${l.action === "BUY" ? "+" : "−"}${l.ratio}×${l.strike}${l.optionType}`).join(" ")}</td>
                <td>{dayLabel(t.expiry)}</td>
                <td>{ist(t.entryTime)}</td>
                <td>
                  {t.premiumType === "DEBIT" ? "D" : "C"} {num(Math.abs(t.entryValue))}
                </td>
                <td>{t.status === "OPEN" ? "open" : ist(t.exitTime)}</td>
                <td>{t.exitReason ?? "—"}</td>
                <td style={{ color: tone(t.pnlPoints) }}>{signed(t.pnlPoints)}</td>
                <td style={{ color: tone(t.grossPnl) }}>{inr(t.grossPnl)}</td>
                <td>{inr(t.charges)}</td>
                <td style={{ color: tone(t.netPnl) }}>
                  <strong>{inr(t.netPnl)}</strong>
                </td>
              </tr>
              {open === t.id ? (
                <tr>
                  <td colSpan={14} style={{ background: "var(--panel)" }}>
                    {t.needsAttention ? <div className="alert error">{t.needsAttention}</div> : null}
                    <DecisionMetrics d={t.decision} />
                    <p className="pcr-oi-caption">{t.decision.why}</p>
                    <table style={{ fontSize: 12 }}>
                      <thead>
                        <tr>
                          <th>Leg</th>
                          <th>Qty</th>
                          <th>Entry (bid/ask/ltp)</th>
                          <th>Exit (bid/ask/ltp)</th>
                          <th>P&amp;L</th>
                          <th>Orders</th>
                        </tr>
                      </thead>
                      <tbody>
                        {t.legs.map((l) => (
                          <tr key={l.id}>
                            <td>
                              {l.action} {l.strike} {l.optionType} ×{l.ratio}
                            </td>
                            <td>{l.quantity}</td>
                            <td>
                              {num(l.entryPrice)} ({num(l.entryBid)}/{num(l.entryAsk)}/{num(l.entryLtp)})
                            </td>
                            <td>
                              {num(l.exitPrice)} ({num(l.exitBid)}/{num(l.exitAsk)}/{num(l.exitLtp)})
                            </td>
                            <td style={{ color: tone(l.pnl) }}>{inr(l.pnl)}</td>
                            <td className="pcr-oi-caption">
                              {l.entryOrderId ?? "paper"} / {l.exitOrderId ?? "paper"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <p className="pcr-oi-caption">
                      target {num(t.targetPoints)} pts ({inr(t.target)}) · stop {num(t.stopPoints)} pts ({inr(t.stop)}) · best {signed(t.bestPoints)} / worst {signed(t.worstPoints)} · NIFTY{" "}
                      {num(t.entrySpot, 0)} → {num(t.exitSpot ?? t.lastSpot, 0)} · {t.mode}
                    </p>
                    {detail?.payoff?.length ? (
                      <VarahaPayoffChart chartId={`varaha-paper-hist-${t.id}`} label={t.structureLabel} points={detail.payoff} breakevens={detail.breakevens} spot={detail.exitSpot ?? detail.entrySpot} expectedMove={null} />
                    ) : null}
                    {detail?.events?.length ? (
                      <table style={{ fontSize: 12, marginTop: 6 }}>
                        <tbody>
                          {detail.events.map((e, i) => (
                            <tr key={i}>
                              <td style={{ whiteSpace: "nowrap" }}>{ist(e.time)}</td>
                              <td>{e.kind}</td>
                              <td>{e.text}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : null}
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

const FIELDS: { key: keyof VarahaPaperConfig; label: string; hint: string; text?: boolean }[] = [
  { key: "lots", label: "Lots", hint: "5" },
  { key: "butterflyTargetPercent", label: "Butterfly target (% of max profit)", hint: "50" },
  { key: "butterflyStopPercent", label: "Butterfly stop (% of debit)", hint: "50" },
  { key: "condorTargetPercent", label: "Strangle target (% of credit)", hint: "50" },
  { key: "condorStopMultiple", label: "Strangle stop (× credit to close)", hint: "2" },
  { key: "exitTime", label: "Day-before-expiry exit time", hint: "15:15", text: true },
  { key: "maxLossInr", label: "Max-loss cap per trade ₹", hint: "150000" },
];

function Settings({ config, onSaved }: { config: VarahaPaperConfig; onSaved: () => void }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setDraft(Object.fromEntries(FIELDS.map((f) => [f.key, String(config[f.key])]))), [config]);
  async function save(updates?: Partial<VarahaPaperConfig>) {
    setSaving(true);
    setError(null);
    try {
      await updateVarahaPaperConfig(updates ?? (Object.fromEntries(FIELDS.map((f) => [f.key, f.text ? draft[f.key] : Number(draft[f.key])])) as Partial<VarahaPaperConfig>));
      onSaved();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }
  return (
    <CollapsibleSection id="varaha-paper-settings" title="Settings" defaultOpen={false}>
      {error ? <div className="alert error">{error}</div> : null}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12 }}>
        {FIELDS.map((f) => (
          <label key={f.key} style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12 }}>
            <span style={{ color: "var(--muted)", fontWeight: 600 }}>{f.label}</span>
            <input value={draft[f.key] ?? ""} onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))} style={{ width: 100, fontSize: 13, padding: "3px 6px" }} />
            <span className="pcr-oi-caption">default {f.hint}</span>
          </label>
        ))}
      </div>
      <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", marginTop: 12, fontSize: 13 }}>
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={config.enabled} onChange={(e) => save({ enabled: e.target.checked })} disabled={saving} />
          Automatic trading at each decision
        </label>
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={config.flipExit} onChange={(e) => save({ flipExit: e.target.checked })} disabled={saving} />
          Close on a direction flip at the daily decision
        </label>
        <button type="button" className="button" onClick={() => save()} disabled={saving}>
          <Save size={14} /> Save settings
        </button>
        <button
          type="button"
          className="button secondary"
          disabled={saving || !config.liveOrdersAllowed}
          onClick={() => (config.mode === "live" ? save({ mode: "paper" }) : window.confirm("Switch Varaha to LIVE Dhan orders?") && save({ mode: "live" }))}
        >
          {config.mode === "live" ? "Switch to paper" : "Switch to LIVE"}
        </button>
        <span className="pcr-oi-caption">
          {config.liveOrdersAllowed
            ? "Live orders allowed on the server -- market orders, buys first, MARGIN product (held overnight)."
            : "Live trading is locked on the server (VARAHA_LIVE_ORDER_ENABLED=false) -- paper only."}
        </span>
      </div>
    </CollapsibleSection>
  );
}
