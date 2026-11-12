"use client";

import { ColorType, createChart, IChartApi, ISeriesApi, LineSeries, Time, UTCTimestamp } from "lightweight-charts";
import { Activity, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import CollapsibleSection from "@/components/CollapsibleSection";
import { getOrderFlowState } from "@/lib/api";
import { isMarketHoursNow } from "@/lib/marketHours";
import type { OrderFlowState } from "@/types/order-flow";

const fmt = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d }));
const clock = (t: number) => new Date(t * 1000).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });
const tone = (v: number | null | undefined) => (!v ? undefined : v > 0 ? "var(--green)" : "var(--red)");

export default function OrderFlowPage() {
  const [state, setState] = useState<OrderFlowState | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function load() {
    try {
      setState(await getOrderFlowState());
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load.");
    }
  }
  useEffect(() => {
    load();
    const id = window.setInterval(() => isMarketHoursNow() && load(), 15000);
    return () => window.clearInterval(id);
  }, []);
  const rec = state?.recording;
  const fut = state?.today.futures ?? [];
  const last = fut[fut.length - 1];
  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Activity size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Order Flow (recording)
          </h1>
          <p>
            Research data collection, no signals. Dhan&apos;s live feed for the NIFTY near-month future and the weekly ATM ±3 strikes (CE + PE) is turned into
            1-minute bars: buyer- vs seller-initiated volume (delta), the book&apos;s pending buy / sell quantity, top-of-book sizes, spread, OI, and a
            volume-by-price footprint for the future. There is no historical order-flow data, so after a few months of recording we can test whether any of it
            predicts NIFTY or option moves.
          </p>
        </div>
        <div className="toolbar">
          <span className={`status-live ${rec?.connected ? "on" : ""}`}>{rec?.connected ? "Recording" : "Idle"}</span>
          <button type="button" className="button secondary" onClick={load}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </header>
      {error ? <div className="alert error">{error}</div> : null}
      {rec?.error ? <div className="alert warning">Feed: {rec.error}</div> : null}

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <Tile label="Feed" value={rec?.connected ? "Connected" : "Not connected"} caption={state?.secondsSincePacket !== null && state?.secondsSincePacket !== undefined ? `last packet ${fmt(state.secondsSincePacket, 1)} s ago` : "records 09:14–15:31 on trading days"} />
        <Tile label="Instruments" value={String(state?.instruments.length ?? 0)} caption={rec?.centre ? `options centred on ${fmt(rec.centre)}` : ""} />
        <Tile label="Minutes today" value={fmt(state?.today.minutes)} caption={`${fmt(rec?.packets)} packets this session`} />
        <Tile label="Futures cumulative delta" value={fmt(last?.cumDelta)} caption={last ? `NIFTY fut ${fmt(last.close, 1)} at ${clock(last.time)}` : ""} color={tone(last?.cumDelta)} />
        <Tile label="Days recorded" value={String(state?.days.length ?? 0)} caption={state?.days[state.days.length - 1]?.day ? `since ${state.days[state.days.length - 1].day}` : ""} />
      </div>

      <CollapsibleSection id="of-chart" title="NIFTY future: price vs cumulative delta (today)">
        {fut.length ? <DeltaChart data={fut} /> : <p className="pcr-oi-caption">No futures minutes recorded today yet.</p>}
      </CollapsibleSection>

      <CollapsibleSection id="of-kind" title="Aggressor volume today">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Instrument</th>
                <th>Buyer-initiated</th>
                <th>Seller-initiated</th>
                <th>Delta</th>
                <th>Buy share</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(state?.today.byKind ?? {}).map(([k, v]) => (
                <tr key={k}>
                  <td>{k === "FUT" ? "NIFTY future" : k === "CE" ? "ATM ±3 calls" : k === "PE" ? "ATM ±3 puts" : k}</td>
                  <td>{fmt(v.buy)}</td>
                  <td>{fmt(v.sell)}</td>
                  <td style={{ color: tone(v.buy - v.sell) }}>{fmt(v.buy - v.sell)}</td>
                  <td>{v.buy + v.sell ? `${fmt((v.buy / (v.buy + v.sell)) * 100, 1)}%` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSection>

      <CollapsibleSection id="of-last" title="Latest futures minutes" defaultOpen={false}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Minute</th>
                <th>Close</th>
                <th>Volume</th>
                <th>Delta</th>
                <th>Book buy / sell</th>
                <th>Bid / ask size</th>
                <th>Spread</th>
                <th>OI</th>
              </tr>
            </thead>
            <tbody>
              {(state?.today.lastFutures ?? []).map((r) => (
                <tr key={r.minute_ts}>
                  <td>{clock(r.minute_ts)}</td>
                  <td>{fmt(r.close, 1)}</td>
                  <td>{fmt(r.volume)}</td>
                  <td style={{ color: tone(r.buy_vol - r.sell_vol) }}>{fmt(r.buy_vol - r.sell_vol)}</td>
                  <td>
                    {fmt(r.book_buy)} / {fmt(r.book_sell)}
                  </td>
                  <td>
                    {fmt(r.bid_qty)} / {fmt(r.ask_qty)}
                  </td>
                  <td>{fmt(r.spread, 2)}</td>
                  <td>{fmt(r.oi)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSection>

      <CollapsibleSection id="of-days" title={`Recorded days (${state?.days.length ?? 0})`} defaultOpen={false}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Day</th>
                <th>Minutes</th>
                <th>Instruments</th>
                <th>Volume</th>
              </tr>
            </thead>
            <tbody>
              {(state?.days ?? []).map((d) => (
                <tr key={d.day}>
                  <td>{d.day}</td>
                  <td>{fmt(d.minutes)}</td>
                  <td>{d.instruments}</td>
                  <td>{fmt(d.volume)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSection>
    </section>
  );
}

function Tile({ label, value, caption, color }: { label: string; value: string; caption?: string; color?: string }) {
  return (
    <div className="metric metric-compact" style={{ flex: "1 1 160px" }}>
      <span>{label}</span>
      <strong style={{ color }}>{value}</strong>
      {caption ? <span className="pcr-oi-caption">{caption}</span> : null}
    </div>
  );
}

function DeltaChart({ data }: { data: OrderFlowState["today"]["futures"] }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceRef = useRef<ISeriesApi<"Line"> | null>(null);
  const deltaRef = useRef<ISeriesApi<"Line"> | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    const tick = (t: Time) => (typeof t === "number" ? clock(t) : String(t));
    const chart = createChart(ref.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#17212b" },
      grid: { vertLines: { color: "#eef1f0" }, horzLines: { color: "#eef1f0" } },
      width: ref.current.clientWidth,
      height: 300,
      rightPriceScale: { visible: true },
      leftPriceScale: { visible: true },
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: tick },
      localization: { timeFormatter: tick },
    });
    priceRef.current = chart.addSeries(LineSeries, { color: "#0f6b78", lineWidth: 2, title: "NIFTY fut", priceScaleId: "right" });
    deltaRef.current = chart.addSeries(LineSeries, { color: "#c58a00", lineWidth: 1, title: "cum. delta", priceScaleId: "left" });
    chartRef.current = chart;
    const resize = () => ref.current && chart.applyOptions({ width: ref.current.clientWidth });
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.remove();
    };
  }, []);
  useEffect(() => {
    priceRef.current?.setData(data.map((d) => ({ time: d.time as UTCTimestamp, value: d.close })));
    deltaRef.current?.setData(data.map((d) => ({ time: d.time as UTCTimestamp, value: d.cumDelta })));
  }, [data]);
  return <div ref={ref} style={{ width: "100%" }} />;
}
