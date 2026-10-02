"use client";

import { ColorType, createChart, IChartApi, IPriceLine, ISeriesApi, LineSeries, Time, UTCTimestamp } from "lightweight-charts";
import { Moon, Play, RefreshCw, Save, SquareArrowOutUpRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import CollapsibleSection from "@/components/CollapsibleSection";
import { DailyTotalsTable, groupDailyTotals } from "@/components/DailyTotals";
import StrikeDistanceMap from "@/components/StrikeDistanceMap";
import VarahaPayoffChart from "@/components/VarahaPayoffChart";
import {
  closeBatmanTrade,
  enterBatmanNow,
  getBatmanConfig,
  getBatmanPreview,
  getBatmanTrade,
  getBatmanTrades,
  updateBatmanConfig,
} from "@/lib/api";
import type { BatmanConfig, BatmanMode, BatmanPreview, BatmanTrade } from "@/types/batman";

const REFRESH_MS = 60000;
const EXIT_LABEL: Record<string, string> = {
  target: "Target hit",
  stop_loss: "Stop loss",
  time_exit: "Time exit",
  manual: "Closed manually",
};

const SETTING_FIELDS: Record<BatmanMode, { key: string; label: string; hint?: string }[]> = {
  monthly: [
    { key: "capital", label: "Capital ₹", hint: "% target / stop / credit are of this" },
    { key: "baseLots", label: "Base lots (x)", hint: "x / 3x / 2x per side -- rulebook 3 / 9 / 6" },
    { key: "entryTime", label: "Entry time", hint: "on the last Friday before monthly expiry" },
    { key: "buyOffset", label: "Buy strike from spot (pts)", hint: "rulebook 400" },
    { key: "sellGap", label: "Sell gap (pts)", hint: "rulebook 200" },
    { key: "hedgeGap", label: "Outer hedge gap (pts)", hint: "rulebook 800" },
    { key: "creditCapPercent", label: "Max credit %", hint: "Filter 1 -- rulebook 6%" },
    { key: "shiftStep", label: "Shift step (pts)", hint: "move buy strikes out by this until credit ≤ cap" },
    { key: "balanceMove", label: "T+0 balance move (pts)", hint: "Filter 2 -- rulebook ±500" },
    { key: "maxExtraCallLots", label: "Max extra outer CE lots" },
    { key: "targetPercent", label: "Target %", hint: "rulebook +2.0%" },
    { key: "stopPercent", label: "Stop loss %", hint: "rulebook -2.5%" },
    { key: "maxHoldDays", label: "Max hold (calendar days)", hint: "rulebook 10–15" },
  ],
  weekly: [
    { key: "capital", label: "Capital ₹" },
    { key: "baseLots", label: "Base lots (x)" },
    { key: "entryTime", label: "Entry time", hint: "every Friday" },
    { key: "minDte", label: "Min days to expiry", hint: "8 = the Tuesday after next (~11 days)" },
    { key: "buyEm", label: "Buy strike (× exp. move)", hint: "monthly rulebook ≈ 0.6" },
    { key: "sellEm", label: "Sell gap (× exp. move)", hint: "≈ 0.25–0.3" },
    { key: "hedgeEm", label: "Outer hedge gap (× exp. move)", hint: "≈ 1.2" },
    { key: "creditCapPercent", label: "Max credit %", hint: "4% for weekly" },
    { key: "shiftStep", label: "Shift step (pts)" },
    { key: "balanceEm", label: "T+0 balance move (× exp. move)", hint: "0.67" },
    { key: "maxExtraCallLots", label: "Max extra outer CE lots" },
    { key: "targetPercent", label: "Target %", hint: "+1.0%" },
    { key: "stopPercent", label: "Stop loss %", hint: "-1.25%" },
    { key: "exitDaysBeforeExpiry", label: "Exit days before expiry", hint: "5 = Thursday before expiry week" },
  ],
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

function istDateTime(epoch: number | null | undefined): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function fmtDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-IN", { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
}

export default function BatmanPage() {
  const mode: BatmanMode = "monthly"; // weekly was built but switched off
  const [preview, setPreview] = useState<BatmanPreview | null>(null);
  const [config, setConfig] = useState<BatmanConfig | null>(null);
  const [trades, setTrades] = useState<BatmanTrade[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function load(currentMode: BatmanMode = mode) {
    try {
      const [cfg, prev, list] = await Promise.all([getBatmanConfig(currentMode), getBatmanPreview(currentMode), getBatmanTrades()]);
      setConfig(cfg);
      setPreview(prev);
      setTrades(list.trades);
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load Batman.");
    }
  }

  useEffect(() => {
    setPreview(null);
    load(mode);
    const timer = window.setInterval(() => load(mode), REFRESH_MS);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  async function enterNow() {
    if (!window.confirm(`Enter a ${mode} Batman now (paper), outside its schedule?`)) return;
    setBusy("enter");
    try {
      const result = await enterBatmanNow(mode);
      setMessage(result.message ? `${result.status}: ${result.message}` : `Batman ${mode} ${result.status}.`);
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Entry failed.");
    } finally {
      setBusy(null);
    }
  }

  async function closeTrade(trade: BatmanTrade) {
    if (!window.confirm(`Close ALL legs of Batman #${trade.id} now (paper)?`)) return;
    setBusy(`close-${trade.id}`);
    try {
      const result = await closeBatmanTrade(trade.id);
      setMessage(`Batman #${trade.id}: ${result.status}${result.message ? ` -- ${result.message}` : ""}`);
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Close failed.");
    } finally {
      setBusy(null);
    }
  }

  async function saveConfig(updates: Record<string, unknown>) {
    setBusy("config");
    try {
      setConfig(await updateBatmanConfig(mode, updates));
      setMessage("Settings saved -- they apply from the next entry.");
      setPreview(await getBatmanPreview(mode));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to save settings.");
    } finally {
      setBusy(null);
    }
  }

  const modeTrades = trades.filter((t) => t.mode === mode);
  const openTrades = modeTrades.filter((t) => t.status === "OPEN");
  const closedTrades = modeTrades.filter((t) => t.status === "CLOSED");

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Moon size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Batman
          </h1>
          <p>
            NIFTY monthly 1:3:2 double ratio spread, 100% hedged, zero adjustments -- per the Batman rulebook. Paper trading --
            simulated fills from the live Dhan chain.
          </p>
        </div>
        <div className="toolbar" style={{ alignItems: "center" }}>
          <span className="status-live on" style={{ whiteSpace: "nowrap" }}>PAPER</span>
          <span className={`status-live ${config?.enabled ? "on" : ""}`} style={{ whiteSpace: "nowrap" }}>
            {config?.enabled ? "Auto entry on" : "Auto entry paused"}
          </span>
          <button type="button" className="button secondary" onClick={() => load()} style={{ whiteSpace: "nowrap" }}>
            <RefreshCw size={14} /> Refresh
          </button>
          <button type="button" className="button" onClick={enterNow} disabled={!!busy} style={{ whiteSpace: "nowrap" }}>
            <Play size={14} /> {busy === "enter" ? "Entering…" : "Enter now"}
          </button>
        </div>
      </header>


      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}

      <PlanSection mode={mode} preview={preview} />

      <CollapsibleSection id={`batman-open-${mode}`} title={`Open trade (${openTrades.length})`}>
        {openTrades.length ? (
          openTrades.map((trade) => (
            <OpenTrade key={trade.id} trade={trade} busy={busy === `close-${trade.id}`} onClose={() => closeTrade(trade)} />
          ))
        ) : (
          <p className="pcr-oi-caption" style={{ margin: 0 }}>
            No open {mode} Batman. Next entry {preview?.entryAt ? istDateTime(preview.entryAt) : "—"} IST.
          </p>
        )}
      </CollapsibleSection>

      <CollapsibleSection id={`batman-pnl-${mode}`} title="P&L by exit day">
        <DailyTotalsTable
          rows={groupDailyTotals(closedTrades, (t) => t.exitTime, (t) => t.grossPnl, (t) => t.netPnl)}
        />
      </CollapsibleSection>

      <CollapsibleSection id={`batman-history-${mode}`} title={`All ${mode} trades (${modeTrades.length})`} defaultOpen={false}>
        <TradesTable trades={modeTrades} />
      </CollapsibleSection>

      <SettingsSection mode={mode} config={config} busy={busy === "config"} onSave={saveConfig} />
    </section>
  );
}

function PlanSection({ mode, preview }: { mode: BatmanMode; preview: BatmanPreview | null }) {
  return (
    <CollapsibleSection
      id={`batman-plan-${mode}`}
      title="Next entry plan"
      aside={preview?.entryAt ? <span className="pcr-oi-caption">built from the live chain right now</span> : null}
    >
      {!preview ? (
        <p className="pcr-oi-caption">Loading…</p>
      ) : preview.error ? (
        <div className="alert warning" style={{ margin: 0 }}>
          {preview.error}
        </div>
      ) : (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {[
              { label: "Entry", value: istDateTime(preview.entryAt), caption: mode === "monthly" ? `last Friday before ${fmtDate(preview.currentMonthly)}` : "every Friday" },
              { label: "Series", value: fmtDate(preview.series), caption: `${preview.daysToExpiryAtEntry} days to expiry at entry` },
              { label: "Exit by", value: istDateTime(preview.exitBy), caption: "if target/stop not hit first" },
              { label: "NIFTY", value: num(preview.spot), caption: preview.expectedMove ? `expected move ±${num(preview.expectedMove, 0)}` : undefined },
              {
                label: "Net credit",
                value: `${inr(preview.credit)} (${num(preview.creditPercent)}%)`,
                caption: `${preview.creditOk ? "≤" : "ABOVE"} ${preview.config.creditCapPercent}% cap${preview.creditShifts ? ` after ${preview.creditShifts} shift(s)` : ""}`,
              },
              {
                label: "Over-hedge",
                value: `+${preview.extraCallLots} outer CE lots`,
                caption: `T+0 at ±${num(preview.balanceMove, 0)}: ${num(preview.t0DownPercent)}% / ${num(preview.t0UpPercent)}%`,
              },
              { label: "Target / stop", value: `+${inr(preview.targetAmount)} / −${inr(preview.stopAmount)}`, caption: `${preview.config.targetPercent}% / ${preview.config.stopPercent}% of ${inr(preview.config.capital as number)}` },
            ].map((m) => (
              <div key={m.label} className="metric metric-compact" style={{ flex: "1 1 170px" }}>
                <span>{m.label}</span>
                <strong>{m.value}</strong>
                {m.caption ? <span className="pcr-oi-caption">{m.caption}</span> : null}
              </div>
            ))}
          </div>
          {preview.creditOk === false ? (
            <div className="alert warning" style={{ margin: "8px 0 0" }}>
              Credit is still above the cap -- no entry would be placed right now.
            </div>
          ) : null}
          {preview.events?.length ? (
            <div className="alert warning" style={{ margin: "8px 0 0" }}>
              High-impact events on the calendar: {preview.events.join(" · ")}
            </div>
          ) : null}
          {preview.legs ? (
            <>
              <StrikeDistanceMap
                id={`batman-${mode}`}
                spot={preview.spot}
                marks={[1, 2, 3, 4, 5, 6]}
                legs={preview.legs.map((l) => ({
                  key: `${l.optionType}${l.strike}`,
                  strike: l.strike,
                  label: `${l.action === "SELL" ? "S" : "B"}${l.qty} ${l.strike.toLocaleString("en-IN")} ${l.optionType}`,
                  short: l.action === "SELL",
                }))}
              />
              <LegsTable legs={preview.legs} />
              {preview.payoff ? (
                <div style={{ marginTop: 12 }}>
                  <VarahaPayoffChart
                    chartId={`batman-plan-${mode}`}
                    label="Batman"
                    points={preview.payoff}
                    breakevens={preview.breakevens ?? []}
                    spot={preview.spot ?? 0}
                    expectedMove={preview.expectedMove ?? null}
                  />
                  <p className="pcr-oi-caption" style={{ margin: "4px 0 0" }}>
                    Max at expiry: profit {inr(preview.expiryMaxProfit)}, loss {inr(preview.expiryMaxLoss)} -- the position is never held to
                    expiry; target, stop and time exit cap the real outcome.
                  </p>
                </div>
              ) : null}
              {preview.balanceTable?.length ? (
                <details style={{ marginTop: 8 }}>
                  <summary style={{ cursor: "pointer", fontSize: 13 }}>Filter 2 -- over-hedge trials</summary>
                  <table style={{ marginTop: 6 }}>
                    <thead>
                      <tr>
                        <th>Extra outer CE lots</th>
                        <th>T+0 at −{num(preview.balanceMove, 0)}</th>
                        <th>T+0 at +{num(preview.balanceMove, 0)}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.balanceTable.map((row) => (
                        <tr key={row.extraCallLots} style={row.extraCallLots === preview.extraCallLots ? { background: "var(--blue-soft)" } : undefined}>
                          <td>+{row.extraCallLots}</td>
                          <td>{inr(row.t0Down)}</td>
                          <td>{inr(row.t0Up)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              ) : null}
            </>
          ) : null}
        </>
      )}
    </CollapsibleSection>
  );
}

function LegsTable({ legs }: { legs: BatmanPreview["legs"] }) {
  if (!legs) return null;
  return (
    <div style={{ overflowX: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>Leg</th>
            <th>Lots</th>
            <th>Strike</th>
            <th>From spot</th>
            <th>Bid / Ask</th>
            <th>Fill</th>
            <th>IV</th>
          </tr>
        </thead>
        <tbody>
          {legs.map((leg) => (
            <tr key={`${leg.optionType}${leg.strike}`}>
              <td>
                <span className={`badge ${leg.action === "BUY" ? "buy" : "sell"}`}>
                  {leg.action} {leg.optionType}
                </span>{" "}
                <span className="pcr-oi-caption">{leg.role}</span>
              </td>
              <td>{leg.qty}</td>
              <td>{leg.strike.toLocaleString("en-IN")}</td>
              <td>
                {leg.distance >= 0 ? "+" : ""}
                {num(leg.distance, 0)} ({num(leg.distancePercent)}%)
              </td>
              <td>
                {num(leg.bid)} / {num(leg.ask)}
              </td>
              <td>{num(leg.price)}</td>
              <td>{leg.iv ? `${num(leg.iv, 1)}%` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OpenTrade({ trade, busy, onClose }: { trade: BatmanTrade; busy: boolean; onClose: () => void }) {
  const [detail, setDetail] = useState<BatmanTrade | null>(null);
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const d = await getBatmanTrade(trade.id);
        if (!cancelled) setDetail(d);
      } catch {
        // keep the last good detail
      }
    }
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [trade.id, trade.lastUpdate]);

  const mtm = trade.lastMtm ?? 0;
  const span = trade.targetAmount + trade.stopAmount;
  const position = Math.min(Math.max((mtm + trade.stopAmount) / span, 0), 1) * 100;
  return (
    <div className="strategy-chart-card">
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "baseline" }}>
        <strong>
          #{trade.id} · series {fmtDate(trade.expiry)}
        </strong>
        <span className="pcr-oi-caption">
          entered {istDateTime(trade.entryTime)} at {num(trade.spot)} · exit by {istDateTime(trade.exitBy)} · credit {inr(trade.credit)} (
          {num(trade.creditPercent)}%) · +{trade.extraCallLots} outer CE
        </span>
        <button type="button" className="button secondary" onClick={onClose} disabled={busy} style={{ marginLeft: "auto" }}>
          <SquareArrowOutUpRight size={14} /> Close all legs
        </button>
      </div>
      <div style={{ margin: "10px 0" }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
          <span style={{ color: "var(--red)" }}>Stop −{inr(trade.stopAmount)}</span>
          <span>
            MTM <strong style={{ color: tone(mtm) }}>{inr(mtm)}</strong> ({num(trade.returnPercent)}%) · net after est. charges{" "}
            <strong style={{ color: tone(trade.netPnl) }}>{inr(trade.netPnl)}</strong>
          </span>
          <span style={{ color: "var(--green)" }}>Target +{inr(trade.targetAmount)}</span>
        </div>
        <div style={{ position: "relative", height: 8, borderRadius: 4, background: "linear-gradient(90deg, var(--red-soft), var(--line-soft) 50%, var(--green-soft))", marginTop: 4 }}>
          <div style={{ position: "absolute", left: `${(trade.stopAmount / span) * 100}%`, top: -2, width: 1, height: 12, background: "var(--muted)" }} />
          <div style={{ position: "absolute", left: `calc(${position}% - 6px)`, top: -3, width: 12, height: 14, borderRadius: 3, background: tone(mtm) ?? "var(--blue)" }} />
        </div>
        <p className="pcr-oi-caption" style={{ margin: "4px 0 0" }}>
          MTM at last traded prices, checked every minute in market hours; all legs exit on target, stop or the exit-by time.
        </p>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table>
          <thead>
            <tr>
              <th>Leg</th>
              <th>Lots</th>
              <th>Strike</th>
              <th>Entry</th>
              <th>LTP</th>
              <th>Bid / Ask</th>
              <th>P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {trade.legs.map((leg) => {
              const sign = leg.action === "BUY" ? 1 : -1;
              const pnl = leg.lastLtp != null ? sign * (leg.lastLtp - leg.entryPrice) * leg.lots * trade.lotSize : null;
              return (
                <tr key={leg.id}>
                  <td>
                    <span className={`badge ${leg.action === "BUY" ? "buy" : "sell"}`}>
                      {leg.action} {leg.optionType}
                    </span>{" "}
                    <span className="pcr-oi-caption">{leg.role}</span>
                  </td>
                  <td>{leg.lots}</td>
                  <td>{leg.strike.toLocaleString("en-IN")}</td>
                  <td>{num(leg.entryPrice)}</td>
                  <td>{num(leg.lastLtp)}</td>
                  <td>
                    {num(leg.lastBid)} / {num(leg.lastAsk)}
                  </td>
                  <td style={{ color: tone(pnl) }}>{inr(pnl)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {detail?.mtmHistory?.length ? <MtmChart trade={detail} /> : null}
      {detail?.payoff ? (
        <div style={{ marginTop: 12 }}>
          <VarahaPayoffChart
            chartId={`batman-trade-${trade.id}`}
            label="Batman"
            points={detail.payoff}
            breakevens={detail.breakevens ?? []}
            spot={detail.currentSpot ?? trade.spot}
            expectedMove={null}
          />
        </div>
      ) : null}
      {trade.notes ? <p className="pcr-oi-caption">{trade.notes}</p> : null}
    </div>
  );
}

function MtmChart({ trade }: { trade: BatmanTrade }) {
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
    series.setData(trade.mtmHistory.map((p) => ({ time: p.time as UTCTimestamp, value: p.mtm })));
    for (const line of linesRef.current) series.removePriceLine(line);
    linesRef.current = [
      series.createPriceLine({ price: trade.targetAmount, color: "#168448", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "Target" }),
      series.createPriceLine({ price: -trade.stopAmount, color: "#c93535", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "Stop" }),
    ];
  }, [trade]);

  return <div ref={containerRef} style={{ width: "100%", marginTop: 12 }} />;
}

function istShort(time: Time): string {
  if (typeof time !== "number") return String(time);
  return new Date(time * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
}

function TradesTable({ trades }: { trades: BatmanTrade[] }) {
  if (!trades.length) return <p className="pcr-oi-caption" style={{ margin: 0 }}>No trades yet.</p>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Entered</th>
            <th>Series</th>
            <th>Spot</th>
            <th>Structure</th>
            <th>Credit</th>
            <th>Exited</th>
            <th>Reason</th>
            <th>Gross</th>
            <th>Return</th>
            <th>Charges</th>
            <th>Net</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr key={t.id}>
              <td>{t.id}</td>
              <td>{istDateTime(t.entryTime)}</td>
              <td>{t.expiry}</td>
              <td>{num(t.spot, 0)}</td>
              <td className="pcr-oi-caption" style={{ fontStyle: "normal" }}>
                ±{num(t.buyOffset, 0)} / {num(t.sellGap, 0)} / {num(t.hedgeGap, 0)} · {t.baseLots}/{t.baseLots * 3}/{t.baseLots * 2}
                {t.extraCallLots ? ` +${t.extraCallLots} CE` : ""}
              </td>
              <td>
                {inr(t.credit)} ({num(t.creditPercent)}%)
              </td>
              <td>{t.status === "OPEN" ? "open" : istDateTime(t.exitTime)}</td>
              <td>{t.exitReason ? EXIT_LABEL[t.exitReason] ?? t.exitReason : "—"}</td>
              <td style={{ color: tone(t.grossPnl) }}>{inr(t.grossPnl)}</td>
              <td style={{ color: tone(t.returnPercent) }}>{num(t.returnPercent)}%</td>
              <td>{inr(t.estimatedCharges)}</td>
              <td style={{ color: tone(t.netPnl) }}>
                <strong>{inr(t.netPnl)}</strong>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SettingsSection({
  mode,
  config,
  busy,
  onSave,
}: {
  mode: BatmanMode;
  config: BatmanConfig | null;
  busy: boolean;
  onSave: (updates: Record<string, unknown>) => Promise<void>;
}) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  useEffect(() => {
    if (config) setDraft(Object.fromEntries(SETTING_FIELDS[mode].map((f) => [f.key, String(config[f.key] ?? "")])));
  }, [config, mode]);
  if (!config) return null;

  function save() {
    const updates: Record<string, unknown> = {};
    for (const field of SETTING_FIELDS[mode]) {
      const raw = draft[field.key];
      updates[field.key] = field.key === "entryTime" ? raw : Number(raw);
    }
    void onSave(updates);
  }

  return (
    <CollapsibleSection id={`batman-settings-${mode}`} title="Settings" defaultOpen={false}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: 12 }}>
        {SETTING_FIELDS[mode].map((field) => (
          <label key={field.key} style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12 }}>
            <span style={{ color: "var(--muted)", fontWeight: 600 }}>{field.label}</span>
            <input
              value={draft[field.key] ?? ""}
              onChange={(e) => setDraft((d) => ({ ...d, [field.key]: e.target.value }))}
              style={{ width: 110, fontSize: 13, padding: "3px 6px" }}
            />
            {field.hint ? <span className="pcr-oi-caption">{field.hint}</span> : null}
          </label>
        ))}
      </div>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center", marginTop: 12, fontSize: 13 }}>
        <label style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={Boolean(config.enabled)} onChange={(e) => onSave({ enabled: e.target.checked })} disabled={busy} />
          Automatic {mode} entry
        </label>
        <label style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={Boolean(config.overHedge)} onChange={(e) => onSave({ overHedge: e.target.checked })} disabled={busy} />
          Call over-hedge (Filter 2)
        </label>
        <button type="button" className="button" onClick={save} disabled={busy}>
          <Save size={14} /> Save settings
        </button>
      </div>
    </CollapsibleSection>
  );
}
