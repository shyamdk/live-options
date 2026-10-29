"use client";

import { ColorType, createChart, createSeriesMarkers, IChartApi, IPriceLine, ISeriesApi, LineSeries, Time, UTCTimestamp } from "lightweight-charts";
import { MoonStar, Play, RefreshCw, Save, SquareArrowOutUpRight } from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";

import CollapsibleSection from "@/components/CollapsibleSection";
import { DailyTotalsTable, groupDailyTotals } from "@/components/DailyTotals";
import StrikeDistanceMap from "@/components/StrikeDistanceMap";
import { istTime, TradeNote, useTradeMarkers } from "@/components/TradeMarkers";
import { closeBtcCalmTrade, enterBtcCalmNow, getBtcCalmState, getBtcCalmTrade, getBtcCalmTrades, updateBtcCalmConfig } from "@/lib/api";
import type { BtcCalmBook, BtcCalmConfig, BtcCalmState, BtcCalmTrade, BtcCalmTradeDetail } from "@/types/btc-calm";

const REFRESH_MS = 15000;

function usd(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}
function num(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function tone(v: number | null | undefined): string | undefined {
  if (!v) return undefined;
  return v > 0 ? "var(--green)" : "var(--red)";
}
function ist(epoch: number | null | undefined, withDay = false): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    ...(withDay ? { day: "2-digit", month: "short" } : {}),
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
function tick(t: Time): string {
  return typeof t === "number" ? ist(t, true) : String(t);
}

export default function BtcCalmStranglePage() {
  const [state, setState] = useState<BtcCalmState | null>(null);
  const [trades, setTrades] = useState<BtcCalmTrade[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const [s, t] = await Promise.all([getBtcCalmState(), getBtcCalmTrades()]);
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

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <MoonStar size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            BTC Calm Strangle
          </h1>
          <p>
            Calm Strangle on Delta BTC daily options (17:30 IST settlement): only between {config?.windowStart ?? "22:00"}–{config?.windowEnd ?? "06:00"} IST, when
            BTC&apos;s last {config?.calmWindow ?? 15} minutes move less than {config?.calmPercent ?? 15}% of the ATM straddle, sell CE/PE at ±
            {config?.strikeMultiple ?? 1.5}× straddle; exit if BTC moves {config?.stopMultiple ?? 1.5}× straddle, the premium hits its exit-time value early,
            or {Math.round((config?.exitBeforeMinutes ?? 240) / 60)} h before settlement.
          </p>
        </div>
        <div className="toolbar" style={{ alignItems: "center" }}>
          <span className="status-live on" style={{ whiteSpace: "nowrap" }}>{state?.mode === "live" ? "LIVE" : "PAPER"}</span>
          <span className={`status-live ${config?.enabled ? "on" : ""}`} style={{ whiteSpace: "nowrap" }}>{config ? (config.enabled ? "Auto entry on" : "Auto entry paused") : "…"}</span>
          <button type="button" className="button secondary" onClick={load} style={{ whiteSpace: "nowrap" }}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}

      <StatusStrip state={state} />

      <CollapsibleSection id="btc-calm-chart" title="BTC (last 6 hours, 1-min)" aside={<span className="pcr-oi-caption">▲ entries, ▼ exits -- hover an arrow for the reason · dashed: open position&apos;s stop band</span>}>
        <SpotChart state={state} trades={trades} />
      </CollapsibleSection>

      {state
        ? Object.entries(state.books).map(([key, book]) => (
            <BookSection
              key={key}
              bookKey={key}
              book={book}
              state={state}
              trades={trades.filter((t) => (t.book ?? "standard") === key)}
              busy={busy}
              onEnter={() =>
                window.confirm(`${book.label}: sell the BTC strangle now, without waiting for the calm test or the window?`) &&
                act(async () => {
                  const r = await enterBtcCalmNow(key);
                  return r.message ? `${book.label}: ${r.status} -- ${r.message}` : `${book.label}: strangle ${r.status}.`;
                })
              }
              onClose={(id) =>
                window.confirm(`Buy back #${id} now?`) &&
                act(async () => {
                  const r = await closeBtcCalmTrade(id);
                  return `#${id}: ${r.status}`;
                })
              }
            />
          ))
        : null}

      <p className="pcr-oi-caption">
        Backtest reference (8 Apr – 13 Oct 2026, 0.5 BTC/leg, 4% slippage): hold to 13:30 +$1,964 (max drawdown −$740); exit 06:00 +$1,235 (max drawdown −$361).
      </p>

      <CollapsibleSection id="btc-calm-log" title={`Log (${state?.events.length ?? 0})`} defaultOpen={false}>
        <table style={{ fontSize: 12 }}>
          <tbody>
            {(state?.events ?? []).map((e, i) => (
              <tr key={i}>
                <td style={{ whiteSpace: "nowrap" }}>{ist(e.time, true)}</td>
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

function BookSection({
  bookKey,
  book,
  state,
  trades,
  busy,
  onEnter,
  onClose,
}: {
  bookKey: string;
  book: BtcCalmBook;
  state: BtcCalmState;
  trades: BtcCalmTrade[];
  busy: boolean;
  onEnter: () => void;
  onClose: (id: number) => void;
}) {
  const closed = trades.filter((t) => t.status === "CLOSED");
  const net = closed.reduce((a, t) => a + t.netPnl, 0);
  const wins = closed.filter((t) => t.netPnl > 0).length;
  return (
    <CollapsibleSection
      id={`btc-calm-book-${bookKey}`}
      title={`${book.label} — ${trades.length} trades · net ${usd(net)}`}
      aside={
        <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span className="pcr-oi-caption">
            {book.enabled ? "on" : "paused"} · exits {book.exitBy ? ist(book.exitBy, true) : "—"} IST · this session {book.entriesThisSession}/
            {state.config.maxEntries} entries, {book.stopsThisSession}/{state.config.maxStops} stops
            {closed.length ? ` · ${Math.round((wins / closed.length) * 100)}% winners` : ""}
          </span>
          <button type="button" className="button secondary" style={{ padding: "2px 8px", fontSize: 12, whiteSpace: "nowrap" }} disabled={busy || !!book.openTrade} onClick={onEnter}>
            <Play size={12} /> Enter now
          </button>
        </span>
      }
    >
      {book.openTrade ? (
        <OpenPosition trade={book.openTrade} busy={busy} onClose={() => onClose(book.openTrade!.id)} />
      ) : (
        <NextEntry state={state} />
      )}
      <h4 style={{ margin: "14px 0 4px", fontSize: 13 }}>Trades</h4>
      <TradesTable trades={trades} />
      <h4 style={{ margin: "14px 0 4px", fontSize: 13 }}>Daily P&amp;L</h4>
      <DailyTotalsTable
        rows={groupDailyTotals(closed, (t) => t.exitTime, (t) => t.grossPnl, (t) => t.netPnl)}
        formatAmount={(v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}$${Math.abs(v).toFixed(2)}`}
      />
    </CollapsibleSection>
  );
}

function Metric({ label, value, caption, color }: { label: string; value: string; caption?: string; color?: string }) {
  return (
    <div className="metric metric-compact" style={{ flex: "1 1 150px" }}>
      <span>{label}</span>
      <strong style={{ color }}>{value}</strong>
      {caption ? <span className="pcr-oi-caption">{caption}</span> : null}
    </div>
  );
}

function StatusStrip({ state }: { state: BtcCalmState | null }) {
  const s = state?.snapshot;
  const c = state?.config;
  const ratio = s?.calmRange != null && s?.calmThreshold ? s.calmRange / s.calmThreshold : null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
      <Metric label="Session expiry" value={s?.expiry ?? "—"} caption={s?.settlement ? `settles ${ist(s.settlement, true)} IST · exit by ${ist(s.exitBy, true)}` : s?.error ?? ""} />
      <Metric label="BTC" value={num(s?.spot, 0)} caption={s?.atmStrike ? `ATM ${num(s.atmStrike, 0)} · ${ist(s.time)}` : ""} />
      <Metric label="ATM straddle" value={usd(s?.straddle, 0)} caption="move priced in to settlement" />
      <div className="metric metric-compact" style={{ flex: "1 1 220px" }}>
        <span>Calm test (last {c?.calmWindow ?? 15} min)</span>
        <strong style={{ color: s?.calm ? "var(--green)" : "var(--red)" }}>
          {s?.calm ? "CALM" : "moving"} · {num(s?.calmRange, 0)} / {num(s?.calmThreshold, 0)}
        </strong>
        <div style={{ height: 6, borderRadius: 3, background: "var(--line-soft)", marginTop: 4 }}>
          <div style={{ width: `${Math.min(100, (ratio ?? 0) * 50)}%`, height: 6, borderRadius: 3, background: (ratio ?? 2) <= 1 ? "var(--green)" : "var(--red)" }} />
        </div>
      </div>
      <Metric
        label="Entry window"
        value={state?.inWindow ? "OPEN" : "closed"}
        caption={`${c?.windowStart ?? ""}–${c?.windowEnd ?? ""} IST`}
        color={state?.inWindow ? "var(--green)" : undefined}
      />
      <Metric
        label="Books"
        value={Object.values(state?.books ?? {}).map((b) => `${b.label}: ${b.openTrade ? "open" : "flat"}`).join(" · ") || "—"}
        caption={`${c?.contracts ?? 500} contracts (${c?.btcPerLeg ?? 0.5} BTC) per leg in each book`}
      />
    </div>
  );
}

function NextEntry({ state }: { state: BtcCalmState | null }) {
  const s = state?.snapshot;
  if (!s || s.error) return <p className="pcr-oi-caption">{s?.error ?? "Loading…"}</p>;
  const legs = s.legs ?? {};
  const btc = state?.config.btcPerLeg ?? 0.5;
  return (
    <div>
      <p className="pcr-oi-caption" style={{ marginTop: 0 }}>
        No open position. When the calm test passes inside the window it would sell, right now:
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        <Metric label="PE" value={legs.PE ? `${legs.PE.symbol} @ ${num(legs.PE.bid)}` : "—"} caption={legs.PE ? `${legs.PE.distancePercent}% below · Δ ${num(legs.PE.delta, 2)}` : ""} />
        <Metric label="CE" value={legs.CE ? `${legs.CE.symbol} @ ${num(legs.CE.bid)}` : "—"} caption={legs.CE ? `${legs.CE.distancePercent}% above · Δ ${num(legs.CE.delta, 2)}` : ""} />
        <Metric label="Credit" value={s.credit ? `${num(s.credit)} per BTC` : "—"} caption={s.credit ? `${usd(s.credit * btc)} on ${btc} BTC/leg` : ""} />
        <Metric label="Stop band" value={`± ${num(s.stopBand, 0)}`} caption={`BTC ${num((s.spot ?? 0) - (s.stopBand ?? 0), 0)} – ${num((s.spot ?? 0) + (s.stopBand ?? 0), 0)}`} />
      </div>
    </div>
  );
}

function OpenPosition({ trade: t, busy, onClose }: { trade: BtcCalmTradeDetail; busy: boolean; onClose: () => void }) {
  const spot = t.lastSpot ?? t.entrySpot;
  const hhmm = (sec: number) => `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
  return (
    <div className="strategy-chart-card">
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "baseline" }}>
        <strong>
          #{t.id} · SHORT {t.peSymbol} / {t.ceSymbol}
        </strong>
        <span className="pcr-oi-caption">
          {t.mode.toUpperCase()} · entered {ist(t.entryTime, true)} at BTC {num(t.entrySpot, 0)}
        </span>
        <button type="button" className="button secondary" onClick={onClose} disabled={busy} style={{ marginLeft: "auto" }}>
          <SquareArrowOutUpRight size={14} /> Buy back now
        </button>
      </div>
      <div style={{ overflowX: "auto", width: 0, minWidth: "100%", marginTop: 10 }}>
        <table style={{ fontSize: 12 }}>
          <thead>
            <tr>
              <th>Leg</th>
              <th>Contracts</th>
              <th>BTC</th>
              <th>Sold at</th>
              <th>Now</th>
              <th>IV at entry</th>
              <th>Premium received</th>
              <th>P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {(["PE", "CE"] as const).map((side) => {
              const sold = side === "PE" ? t.entryPe : t.entryCe;
              const now = side === "PE" ? t.lastPe : t.lastCe;
              return (
                <tr key={side}>
                  <td>
                    <span className="badge sell">SELL</span> {side === "PE" ? t.peSymbol : t.ceSymbol}
                  </td>
                  <td>{t.contracts}</td>
                  <td>{t.btcPerLeg}</td>
                  <td>{num(sold)}</td>
                  <td>{num(now)}</td>
                  <td>{num(t.ivs?.[side])}%</td>
                  <td>{usd(sold * t.btcPerLeg)}</td>
                  <td style={{ color: tone(now != null ? sold - now : null) }}>{now != null ? usd((sold - now) * t.btcPerLeg) : "—"}</td>
                </tr>
              );
            })}
            <tr>
              <td>
                <strong>Strangle</strong>
              </td>
              <td>{t.contracts} + {t.contracts}</td>
              <td>{t.btcPerLeg * 2}</td>
              <td>{num(t.credit)}</td>
              <td>{num(t.current)}</td>
              <td />
              <td>{usd(t.premiumCollected)}</td>
              <td style={{ color: tone(t.grossPnl) }}>
                <strong>{usd(t.grossPnl)}</strong> <span className="pcr-oi-caption">net {usd(t.netPnl)}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <h4 style={{ margin: "12px 0 4px", fontSize: 13 }}>How this trade exits (first to happen; both legs bought back together)</h4>
      <div style={{ overflowX: "auto", width: 0, minWidth: "100%" }}>
        <table style={{ fontSize: 12 }}>
          <thead>
            <tr>
              <th>Exit</th>
              <th>Trigger</th>
              <th>How far now</th>
              <th>Estimated net if it happens now</th>
            </tr>
          </thead>
          <tbody>
            {t.scenarios.map((sc) => (
              <tr key={sc.kind}>
                <td>{sc.kind.startsWith("move") ? "BTC move stop" : sc.kind === "backstop" ? "Premium backstop" : sc.kind === "early" ? "Book early" : "Time exit"}</td>
                <td>{sc.label}</td>
                <td>
                  {sc.kind === "time"
                    ? `in ${hhmm(sc.distance)}`
                    : sc.kind === "early"
                      ? sc.distance <= 0
                        ? "reached"
                        : `${num(sc.distance)} more decay`
                      : sc.kind === "backstop"
                        ? `${num(sc.distance)} (premium +${num((t.backstop / t.current - 1) * 100, 0)}%)`
                        : `${num(sc.distance, 0)} (${num((sc.distance / spot) * 100, 2)}%)`}
                </td>
                <td style={{ color: tone(sc.estNet) }}>{usd(sc.estNet)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 420px), 1fr))", gap: 12, marginTop: 12 }}>
        <div style={{ minWidth: 0 }}>
          <h4 style={{ margin: "0 0 4px", fontSize: 13 }}>Payoff (blue: at the exit time · grey: at settlement)</h4>
          <PayoffChart trade={t} />
        </div>
        <div style={{ minWidth: 0 }}>
          <h4 style={{ margin: "0 0 4px", fontSize: 13 }}>Combined premium since entry</h4>
          <PremiumChart trade={t} />
        </div>
      </div>
      <div style={{ marginTop: 10 }}>
        <StrikeDistanceMap
          id={`btc-calm-${t.id}`}
          spot={spot}
          legs={[
            { key: "pe", strike: t.peStrike, label: `${t.peStrike} PE`, short: true },
            { key: "ce", strike: t.ceStrike, label: `${t.ceStrike} CE`, short: true },
          ]}
          marks={[0.5, 1, 1.5, 2, 2.5]}
        />
      </div>
    </div>
  );
}

function PayoffChart({ trade: t }: { trade: BtcCalmTradeDetail }) {
  const [hover, setHover] = useState<number | null>(null);
  const pts = t.payoff;
  if (pts.length < 2) return null;
  const W = 560;
  const H = 240;
  const pad = { l: 56, r: 10, t: 12, b: 24 };
  const xMin = pts[0].price;
  const xMax = pts[pts.length - 1].price;
  const vals = pts.flatMap((p) => [p.expiry, p.today]);
  const yMax = Math.max(0, ...vals) * 1.1 || 1;
  const yMin = Math.min(0, ...vals) * 1.05;
  const x = (v: number) => pad.l + ((v - xMin) / (xMax - xMin)) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + ((yMax - v) / (yMax - yMin)) * (H - pad.t - pad.b);
  const path = (k: "expiry" | "today") => pts.map((p, i) => `${i ? "L" : "M"}${x(p.price).toFixed(1)},${y(p[k]).toFixed(1)}`).join(" ");
  const spot = t.lastSpot ?? t.entrySpot;
  const h = hover != null ? pts[hover] : null;
  return (
    <div>
      <div style={{ fontSize: 11, minHeight: 16 }}>
        {h ? (
          <>
            BTC {num(h.price, 0)} · at exit <strong style={{ color: tone(h.today) }}>{usd(h.today)}</strong> · at settlement {usd(h.expiry)}
          </>
        ) : (
          <span className="pcr-oi-caption">shaded = stop band · breakevens at settlement {t.breakevens.map((b) => num(b, 0)).join(" / ")}</span>
        )}
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: "100%", height: "auto", background: "var(--panel)" }}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const price = xMin + ((((e.clientX - r.left) / r.width) * W - pad.l) / (W - pad.l - pad.r)) * (xMax - xMin);
          let best = 0;
          pts.forEach((p, i) => {
            if (Math.abs(p.price - price) < Math.abs(pts[best].price - price)) best = i;
          });
          setHover(best);
        }}
      >
        <rect x={x(t.stopLow)} y={pad.t} width={Math.max(0, x(t.stopHigh) - x(t.stopLow))} height={H - pad.t - pad.b} fill="rgba(22,132,72,0.06)" />
        <line x1={pad.l} x2={W - pad.r} y1={y(0)} y2={y(0)} stroke="var(--muted)" />
        {[yMin, yMax].map((v) => (
          <text key={v} x={pad.l - 4} y={y(v) + 3} fontSize={9} fill="var(--muted)" textAnchor="end">
            {usd(v, 0)}
          </text>
        ))}
        {[
          { v: t.peStrike, label: `${t.peStrike} PE` },
          { v: t.ceStrike, label: `${t.ceStrike} CE` },
        ].map((m) => (
          <g key={m.label}>
            <line x1={x(m.v)} x2={x(m.v)} y1={pad.t} y2={H - pad.b} stroke="#7a8494" strokeDasharray="2 2" />
            <text x={x(m.v)} y={pad.t + 9} fontSize={9} fill="#7a8494" textAnchor="middle">
              {m.label}
            </text>
          </g>
        ))}
        <path d={path("expiry")} fill="none" stroke="#9aa3af" strokeWidth={1.5} />
        <path d={path("today")} fill="none" stroke="#0f6b78" strokeWidth={2} />
        <line x1={x(spot)} x2={x(spot)} y1={pad.t} y2={H - pad.b} stroke="#0f6b78" />
        <text x={x(spot)} y={H - 6} fontSize={9} fill="#0f6b78" textAnchor="middle">
          BTC {num(spot, 0)}
        </text>
        {h ? <circle cx={x(h.price)} cy={y(h.today)} r={3} fill="#0f6b78" /> : null}
      </svg>
    </div>
  );
}

function PremiumChart({ trade: t }: { trade: BtcCalmTradeDetail }) {
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
      height: 220,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: tick },
      localization: { timeFormatter: tick },
    });
    seriesRef.current = chart.addSeries(LineSeries, { color: "#b23c35", lineWidth: 2, title: "Premium" });
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
    const seen = new Set<number>();
    series.setData(t.marks.filter((m) => (seen.has(m.time) ? false : (seen.add(m.time), true))).map((m) => ({ time: m.time as UTCTimestamp, value: m.combined })));
    for (const l of linesRef.current) series.removePriceLine(l);
    linesRef.current = [
      series.createPriceLine({ price: t.credit, color: "#7a8494", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "sold" }),
      ...(t.earlyTarget != null ? [series.createPriceLine({ price: t.earlyTarget, color: "#1b7a4b", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "book early" })] : []),
    ];
    chartRef.current?.timeScale().fitContent();
  }, [t]);
  return <div ref={ref} style={{ width: "100%", height: 220 }} />;
}

function btcCalmNotes(trades: BtcCalmTrade[], config?: BtcCalmConfig): TradeNote[] {
  return trades.flatMap((t) => {
    const book = config?.books?.[t.book]?.label ?? t.book;
    return [
      {
        time: t.entryTime,
        kind: "entry" as const,
        label: `#${t.id} ${t.book === "early" ? "06:00" : "13:30"}`,
        color: "#b23c35",
        title: `Entry #${t.id} [${book}] · sold ${t.peStrike} PE / ${t.ceStrike} CE`,
        lines: [
          `${istTime(t.entryTime)} IST · BTC ${num(t.entrySpot, 0)}${t.trigger === "manual" ? " · manual entry" : ""}`,
          t.trigger === "manual"
            ? "Why: entered manually (Enter now)"
            : `Why: BTC calm in the overnight window -- last ${config?.calmWindow ?? 15} min range ${num(t.calmRange, 0)} ≤ ${config?.calmPercent ?? 15}% of the ATM straddle ${usd(t.straddle, 0)}`,
          `Strikes at ±${config?.strikeMultiple ?? 1.5}× straddle · credit ${num(t.credit)} per BTC (${usd(t.premiumCollected)} on ${t.btcPerLeg} BTC/leg)`,
          `Stops: BTC ${num(t.stopLow, 0)} / ${num(t.stopHigh, 0)} · backstop ${num(t.backstop)} · book early at ${num(t.earlyTarget)} · time exit ${istTime(t.exitBy)}`,
        ],
      },
      ...(t.exitTime
        ? [
            {
              time: t.exitTime,
              kind: "exit" as const,
              label: usd(t.netPnl, 0),
              color: t.netPnl >= 0 ? "#1b7a4b" : "#b23c35",
              title: `Exit #${t.id} [${book}] · ${usd(t.netPnl)} net`,
              lines: [
                `${istTime(t.exitTime)} IST · BTC ${num(t.exitSpot, 0)} · ${num(t.points)} per BTC`,
                `Why: ${t.exitReason ?? "—"}`,
                `held ${t.minutesHeld} min · fees ${usd(t.fees)}`,
              ],
            },
          ]
        : []),
    ];
  });
}

function SpotChart({ state, trades }: { state: BtcCalmState | null; trades: BtcCalmTrade[] }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const linesRef = useRef<IPriceLine[]>([]);
  const [handles, setHandles] = useState<{ chart: IChartApi; series: ISeriesApi<"Line"> } | null>(null);
  useEffect(() => {
    if (!ref.current || chartRef.current) return;
    const chart = createChart(ref.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#17212b" },
      grid: { vertLines: { color: "#e8edeb" }, horzLines: { color: "#e8edeb" } },
      width: ref.current.clientWidth,
      height: 260,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: tick },
      localization: { timeFormatter: tick },
    });
    seriesRef.current = chart.addSeries(LineSeries, { color: "#f2a900", lineWidth: 2, title: "BTC" });
    chartRef.current = chart;
    setHandles({ chart, series: seriesRef.current });
    const observer = new ResizeObserver(() => ref.current && chart.applyOptions({ width: ref.current.clientWidth }));
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      setHandles(null);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      linesRef.current = [];
    };
  }, []);
  const barTimes = useMemo(() => (state?.spot ?? []).map((c) => c.time), [state?.spot]);
  const notes = useMemo(() => btcCalmNotes(trades, state?.config), [trades, state?.config]);
  const tooltip = useTradeMarkers(handles?.chart ?? null, handles?.series ?? null, notes, 60, barTimes);
  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !state) return;
    series.setData(state.spot.map((c) => ({ time: c.time as UTCTimestamp, value: c.close })));
    for (const l of linesRef.current) series.removePriceLine(l);
    const o = Object.values(state.books).map((b) => b.openTrade).find(Boolean) ?? null;
    linesRef.current = o
      ? [
          series.createPriceLine({ price: o.stopHigh, color: "#b23c35", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "stop" }),
          series.createPriceLine({ price: o.stopLow, color: "#b23c35", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "stop" }),
        ]
      : [];
    chartRef.current?.timeScale().fitContent();
  }, [state]);
  return (
    <div style={{ position: "relative" }}>
      <div ref={ref} style={{ width: "100%", height: 260 }} />
      {tooltip}
    </div>
  );
}

function TradesTable({ trades }: { trades: BtcCalmTrade[] }) {
  const [open, setOpen] = useState<number | null>(null);
  const [detail, setDetail] = useState<BtcCalmTradeDetail | null>(null);
  useEffect(() => {
    if (open == null) return setDetail(null);
    getBtcCalmTrade(open).then(setDetail).catch(() => undefined);
  }, [open]);
  if (!trades.length) return <p className="pcr-oi-caption" style={{ margin: 0 }}>No trades yet.</p>;
  const net = trades.reduce((a, t) => a + t.netPnl, 0);
  return (
    <div style={{ overflowX: "auto", width: 0, minWidth: "100%" }}>
      <p className="pcr-oi-caption" style={{ marginTop: 0 }}>
        net <strong style={{ color: tone(net) }}>{usd(net)}</strong> · click a row for charts, quotes and order ids
      </p>
      <table style={{ fontSize: 12 }}>
        <thead>
          <tr>
            <th>#</th>
            <th>Expiry</th>
            <th>Entry (IST)</th>
            <th>BTC</th>
            <th>PE / CE</th>
            <th>Credit</th>
            <th>Exit</th>
            <th>Reason</th>
            <th>Held</th>
            <th>Gross</th>
            <th>Fees</th>
            <th>Net</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <Fragment key={t.id}>
              <tr onClick={() => setOpen(open === t.id ? null : t.id)} style={{ cursor: "pointer" }}>
                <td>{t.id}</td>
                <td>{t.expiry}</td>
                <td>{ist(t.entryTime, true)}</td>
                <td>{num(t.entrySpot, 0)}</td>
                <td>
                  {t.peStrike} / {t.ceStrike}
                </td>
                <td>{num(t.credit)}</td>
                <td>{t.status === "OPEN" ? "open" : ist(t.exitTime, true)}</td>
                <td>{t.exitReason ?? "—"}</td>
                <td>{t.minutesHeld}m</td>
                <td style={{ color: tone(t.grossPnl) }}>{usd(t.grossPnl)}</td>
                <td>{usd(t.fees)}</td>
                <td style={{ color: tone(t.netPnl) }}>
                  <strong>{usd(t.netPnl)}</strong>
                </td>
              </tr>
              {open === t.id ? (
                <tr>
                  <td colSpan={12} style={{ background: "var(--panel)" }}>
                    <div className="pcr-oi-caption" style={{ fontStyle: "normal" }}>
                      {(["PE", "CE"] as const).map((s) => (
                        <div key={s}>
                          {s}: sold {num(s === "PE" ? t.entryPe : t.entryCe)} (bid/ask/mark {num(t.entryQuotes[s]?.bid)}/{num(t.entryQuotes[s]?.ask)}/{num(t.entryQuotes[s]?.mark)}) ·
                          bought {num(s === "PE" ? t.exitPe : t.exitCe)}
                        </div>
                      ))}
                      <div>
                        stop band {num(t.stopLow, 0)}–{num(t.stopHigh, 0)} · backstop {num(t.backstop)} · book-early {num(t.earlyTarget)} · orders{" "}
                        {Object.entries(t.orderIds).map(([k, v]) => `${k}:${v ?? "—"}`).join(" ")}
                      </div>
                    </div>
                    {detail ? (
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 420px), 1fr))", gap: 12, marginTop: 8 }}>
                        <PayoffChart trade={detail} />
                        <PremiumChart trade={detail} />
                      </div>
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

const FIELDS: { key: keyof BtcCalmConfig; label: string; hint: string; text?: boolean }[] = [
  { key: "contracts", label: "Contracts per leg", hint: "500 = 0.5 BTC" },
  { key: "calmPercent", label: "Calm: range ≤ % of straddle", hint: "15" },
  { key: "calmWindow", label: "Calm window (minutes)", hint: "15" },
  { key: "strikeMultiple", label: "Strikes at ± × straddle", hint: "1.5" },
  { key: "stopMultiple", label: "Stop: BTC move × straddle", hint: "1.5" },
  { key: "backstopPercent", label: "Premium backstop %", hint: "150" },
  { key: "minCredit", label: "Min credit (per BTC)", hint: "20" },
  { key: "windowStart", label: "Entry window from (IST)", hint: "22:00", text: true },
  { key: "windowEnd", label: "Entry window until (IST)", hint: "06:00", text: true },
  { key: "exitBeforeMinutes", label: "Hold-to-13:30 book: exit before settlement (min)", hint: "240" },
  { key: "maxEntries", label: "Max entries / session", hint: "3" },
  { key: "maxStops", label: "Max stops / session", hint: "2" },
];

function Settings({ config, onSaved }: { config: BtcCalmConfig; onSaved: () => void }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setDraft(Object.fromEntries(FIELDS.map((f) => [f.key, String(config[f.key])]))), [config]);
  async function save(updates?: Partial<BtcCalmConfig>) {
    setSaving(true);
    setError(null);
    try {
      await updateBtcCalmConfig(updates ?? (Object.fromEntries(FIELDS.map((f) => [f.key, f.text ? draft[f.key] : Number(draft[f.key])])) as Partial<BtcCalmConfig>));
      onSaved();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }
  return (
    <CollapsibleSection id="btc-calm-settings" title="Settings" defaultOpen={false}>
      {error ? <div className="alert error">{error}</div> : null}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12 }}>
        {FIELDS.map((f) => (
          <label key={f.key} style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12 }}>
            <span style={{ color: "var(--muted)", fontWeight: 600 }}>{f.label}</span>
            <input value={draft[f.key] ?? ""} onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))} style={{ width: 90, fontSize: 13, padding: "3px 6px" }} />
            <span className="pcr-oi-caption">backtest: {f.hint}</span>
          </label>
        ))}
      </div>
      <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", marginTop: 12, fontSize: 13 }}>
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={config.enabled} onChange={(e) => save({ enabled: e.target.checked })} disabled={saving} />
          Automatic entries
        </label>
        {Object.entries(config.books).map(([key, b]) => (
          <label key={key} style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={b.enabled} onChange={(e) => save({ books: { [key]: { enabled: e.target.checked } } } as unknown as Partial<BtcCalmConfig>)} disabled={saving} />
            {b.label} book (exits {b.exitBeforeMinutes} min before settlement)
          </label>
        ))}
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={config.earlyExit} onChange={(e) => save({ earlyExit: e.target.checked })} disabled={saving} />
          Book early at the exit-time value (then done for the session)
        </label>
        <button type="button" className="button" onClick={() => save()} disabled={saving}>
          <Save size={14} /> Save settings
        </button>
        <span className="pcr-oi-caption">{config.liveOrdersAllowed ? "Live orders allowed on the server." : "Live trading is locked on the server (BTC_CALM_LIVE_ORDER_ENABLED=false) -- paper only."}</span>
      </div>
    </CollapsibleSection>
  );
}
