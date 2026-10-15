"use client";

import { CandlestickSeries, ColorType, createChart, IChartApi, IPriceLine, ISeriesApi, LineSeries, Time, UTCTimestamp } from "lightweight-charts";
import { Bitcoin, ChevronDown, ChevronRight, Play, RefreshCw, Save, SquareArrowOutUpRight } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { DailyTotalsTable, groupDailyTotals } from "@/components/DailyTotals";
import StrikeDistanceMap from "@/components/StrikeDistanceMap";
import { istTime as noteTime, TradeNote, useTradeMarkers } from "@/components/TradeMarkers";
import {
  closeBtcStrangleLeg,
  enterBtcStrangleNow,
  getBtcSpotChart,
  getBtcStrangleChart,
  getBtcStrangleConfig,
  getBtcStranglePreview,
  getBtcStrangleTrades,
  updateBtcStrangleConfig,
} from "@/lib/api";
import type { BtcStrangleConfig, BtcStrangleLeg, BtcStranglePreview, BtcStrangleTrade } from "@/types/btc-strangle";

const REFRESH_MS = 15000;
const MULTIPLIER_PRESETS = [1.6, 1.7, 1.8, 1.9, 2.0, 2.1, 2.2];
const STOP_LOSS_PRESETS = [50, 80, 100, 120, 150, 200];
const EXIT_REASON_LABEL: Record<string, string> = {
  stop_loss: "Stop loss",
  expiry_buyback: "Bought back before expiry",
  expired: "Expired",
  manual: "Closed manually",
  sl_place_failed: "Closed -- stop could not be placed",
};

function usd(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value < 0 ? "−" : ""}$${Math.abs(value).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function num(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function tone(value: number | null | undefined): string | undefined {
  if (value === null || value === undefined || value === 0) return undefined;
  return value > 0 ? "var(--green)" : "var(--red)";
}

function istDateTime(epoch: number | null | undefined): string {
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

function expiryLabel(code: string | undefined, settlement: number | undefined): string {
  if (!code) return "—";
  return settlement ? `${istDateTime(settlement)} IST` : code;
}

function useSectionExpanded(key: string, defaultOpen: boolean): [boolean, () => void] {
  const storageKey = `btc-strangle:expanded:${key}`;
  const [expanded, setExpanded] = useState(defaultOpen);
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (raw !== null) setExpanded(raw === "1");
    } catch {
      // private window -- just don't remember
    }
  }, [storageKey]);
  function toggle() {
    setExpanded((current) => {
      try {
        window.localStorage.setItem(storageKey, current ? "0" : "1");
      } catch {
        // ignore
      }
      return !current;
    });
  }
  return [expanded, toggle];
}

function Section({
  id,
  title,
  aside,
  defaultOpen = true,
  children,
}: {
  id: string;
  title: React.ReactNode;
  aside?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [expanded, toggle] = useSectionExpanded(id, defaultOpen);
  return (
    <div className="pcr-oi-section">
      <div style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", flexWrap: "wrap" }} onClick={toggle}>
        <button className="icon-button" type="button" aria-expanded={expanded} title={expanded ? "Collapse" : "Expand"}>
          {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </button>
        <h3 style={{ margin: 0 }}>{title}</h3>
        {aside ? <div style={{ marginLeft: "auto" }} onClick={(e) => e.stopPropagation()}>{aside}</div> : null}
      </div>
      {expanded ? <div style={{ marginTop: 10 }}>{children}</div> : null}
    </div>
  );
}

export default function BtcStranglePage() {
  const [config, setConfig] = useState<BtcStrangleConfig | null>(null);
  const [preview, setPreview] = useState<BtcStranglePreview | null>(null);
  const [trades, setTrades] = useState<BtcStrangleTrade[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    try {
      const [cfg, prev, list] = await Promise.all([getBtcStrangleConfig(), getBtcStranglePreview(), getBtcStrangleTrades()]);
      setConfig(cfg);
      setPreview(prev);
      setTrades(list.trades);
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load BTC Strangle.");
    }
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  async function saveConfig(updates: Partial<BtcStrangleConfig>, note?: string) {
    setBusy("config");
    setError(null);
    try {
      setConfig(await updateBtcStrangleConfig(updates));
      setPreview(await getBtcStranglePreview());
      if (note) setMessage(note);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to save settings.");
    } finally {
      setBusy(null);
    }
  }

  async function enterNow() {
    if (!config) return;
    const live = config.mode === "live";
    if (!window.confirm(live ? "Enter a LIVE strangle on Delta now? This places real sell orders." : "Enter a paper strangle now (outside the schedule)?")) return;
    setBusy("enter");
    setError(null);
    try {
      const result = await enterBtcStrangleNow();
      setMessage(result.message ? `${result.status}: ${result.message}` : `Strangle ${result.status}.`);
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Entry failed.");
    } finally {
      setBusy(null);
    }
  }

  async function closeLeg(trade: BtcStrangleTrade, leg: BtcStrangleLeg) {
    const live = trade.mode === "live";
    if (!window.confirm(`Buy back ${leg.contracts} × ${leg.symbol}${live ? " with a LIVE market order (its stop is cancelled first)" : " (paper)"}?`)) return;
    setBusy(`leg-${leg.id}`);
    try {
      const result = await closeBtcStrangleLeg(leg.id);
      setMessage(`${leg.symbol}: ${result.status}${result.price ? ` @ ${num(result.price)}` : ""}`);
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Close failed.");
    } finally {
      setBusy(null);
    }
  }

  const openTrades = trades.filter((t) => t.status === "OPEN");
  const closedTrades = trades.filter((t) => t.status !== "OPEN");
  const live = config?.mode === "live";

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Bitcoin size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            BTC Strangle
          </h1>
          <p>
            Delta Exchange · sells an OTM BTC call + put nightly at spot ± multiplier × ATM straddle, per-leg stop loss,
            buy-back before the 17:30 IST settlement.
          </p>
        </div>
        <div className="toolbar" style={{ alignItems: "center" }}>
          <span
            className={`status-live ${live ? "warn" : "on"}`}
            title={live ? "Real orders on Delta" : "Simulated fills from the live order book"}
          >
            {live ? "LIVE" : "PAPER"}
          </span>
          <span className={`status-live ${config?.enabled ? "on" : ""}`} style={{ whiteSpace: "nowrap" }}>
            {config?.enabled ? "Auto entry on" : "Auto entry paused"}
          </span>
          <button type="button" className="button secondary" onClick={load} style={{ whiteSpace: "nowrap" }}>
            <RefreshCw size={14} /> Refresh
          </button>
          <button type="button" className="button" onClick={enterNow} disabled={!config || !!busy} style={{ whiteSpace: "nowrap" }}>
            <Play size={14} /> {busy === "enter" ? "Entering…" : "Enter now"}
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}

      <SettingsSection config={config} busy={busy === "config"} onSave={saveConfig} />
      <PlanSection preview={preview} />

      <Section id="open" title={`Open trades (${openTrades.length})`}>
        {openTrades.length ? (
          openTrades.map((trade) => (
            <OpenTradeCard key={trade.id} trade={trade} spot={preview?.spot ?? null} busy={busy} onCloseLeg={closeLeg} />
          ))
        ) : (
          <p className="pcr-oi-caption" style={{ margin: 0 }}>
            No open strangle. Next entry {preview?.entryAt ? istDateTime(preview.entryAt) : "—"} IST.
          </p>
        )}
      </Section>

      <Section id="daily" title="Daily P&L" defaultOpen>
        <DailyTotalsTable
          rows={groupDailyTotals(
            closedTrades.filter((t) => t.status === "CLOSED"),
            (t) => t.closedAt,
            (t) => t.grossPnl,
            (t) => t.netPnl,
          )}
        />
        <p className="pcr-oi-caption" style={{ margin: "4px 0 0" }}>
          USD, grouped by the IST date each strangle fully closed. Net = gross − Delta fees (incl. 18% GST).
        </p>
      </Section>

      <Section id="history" title={`All trades (${trades.length})`} defaultOpen={false}>
        <TradesTable trades={trades} />
      </Section>

      <Section id="spot" title="BTC spot (reference)" aside={<span className="pcr-oi-caption">Delta BTC index (.DEXBTUSD) · refreshes every 30s</span>}>
        <SpotChart trades={trades} />
      </Section>
    </section>
  );
}

function SettingsSection({
  config,
  busy,
  onSave,
}: {
  config: BtcStrangleConfig | null;
  busy: boolean;
  onSave: (updates: Partial<BtcStrangleConfig>, note?: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!config) return;
    setDraft({
      multiplier: String(config.multiplier),
      stopLossPercent: String(config.stopLossPercent),
      contracts: String(config.contracts),
      entryTime: config.entryTime,
      entryWindowEnd: config.entryWindowEnd,
      expiryOffset: String(config.expiryOffset),
      expiryExitTime: config.expiryExitTime,
      buybackThreshold: String(config.buybackThreshold),
      minAvailableBalance: String(config.minAvailableBalance),
    });
  }, [config]);

  if (!config) return null;
  const field = (key: string, label: string, hint?: string, width = 80) => (
    <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12 }}>
      <span style={{ color: "var(--muted)", fontWeight: 600 }}>{label}</span>
      <input
        value={draft[key] ?? ""}
        onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
        style={{ width, fontSize: 13, padding: "3px 6px" }}
      />
      {hint ? <span className="pcr-oi-caption">{hint}</span> : null}
    </label>
  );
  const presets = (key: "multiplier" | "stopLossPercent", values: number[], suffix: string) => (
    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
      {values.map((value) => (
        <button
          key={value}
          type="button"
          className="button secondary"
          style={{
            padding: "2px 8px",
            fontSize: 12,
            ...(Number(draft[key]) === value ? { background: "var(--blue)", color: "#fff" } : {}),
          }}
          onClick={() => setDraft((d) => ({ ...d, [key]: String(value) }))}
        >
          {value}
          {suffix}
        </button>
      ))}
    </div>
  );

  function save() {
    void onSave(
      {
        multiplier: Number(draft.multiplier),
        stopLossPercent: Number(draft.stopLossPercent),
        contracts: Number(draft.contracts),
        entryTime: draft.entryTime,
        entryWindowEnd: draft.entryWindowEnd,
        expiryOffset: Number(draft.expiryOffset),
        expiryExitTime: draft.expiryExitTime,
        buybackThreshold: Number(draft.buybackThreshold),
        minAvailableBalance: Number(draft.minAvailableBalance),
      },
      "Settings saved -- they apply from the next entry.",
    );
  }

  function switchMode() {
    if (!config) return;
    if (config.mode === "paper") {
      if (!config.liveOrdersAllowed) return;
      if (
        !window.confirm(
          `Switch to LIVE? From the next entry real orders are placed on Delta: ${config.contracts} contracts per leg ` +
            `(${(config.contracts * 0.001).toFixed(3)} BTC), stop at ${config.stopLossPercent}% loss. Live entries refuse to start ` +
            `below $${config.minAvailableBalance} available balance. Open paper trades stay paper.`,
        )
      )
        return;
      void onSave({ mode: "live" }, "Mode set to LIVE.");
    } else {
      void onSave({ mode: "paper" }, "Mode set to paper -- open live trades keep being managed until they close.");
    }
  }

  const sizeBtc = Number(draft.contracts || 0) * 0.001;
  return (
    <Section
      id="settings"
      title="Settings"
      aside={
        <span className="pcr-oi-caption">
          {config.multiplier}× straddle · SL {config.stopLossPercent}% · {config.contracts} contracts · entry {config.entryTime} IST
        </span>
      }
      defaultOpen={false}
    >
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 14 }}>
        <div>
          {field("multiplier", "Strike distance (× ATM straddle)")}
          <div style={{ marginTop: 4 }}>{presets("multiplier", MULTIPLIER_PRESETS, "×")}</div>
        </div>
        <div>
          {field("stopLossPercent", "Stop loss per leg (% loss)", "100% = exit at 2× the selling price")}
          <div style={{ marginTop: 4 }}>{presets("stopLossPercent", STOP_LOSS_PRESETS, "%")}</div>
        </div>
        {field("contracts", "Contracts per leg", `${sizeBtc.toFixed(3)} BTC (1 contract = 0.001 BTC)`)}
        <div style={{ display: "flex", gap: 10 }}>
          {field("entryTime", "Entry from (IST)", undefined, 64)}
          {field("entryWindowEnd", "until", undefined, 64)}
        </div>
        {field("expiryOffset", "Expiry", "2 = day-after expiry (~43h hold)", 50)}
        <div style={{ display: "flex", gap: 10 }}>
          {field("expiryExitTime", "Buy back at (IST)", undefined, 64)}
          {field("buybackThreshold", "if worth > $", "else let it expire", 64)}
        </div>
        {field("minAvailableBalance", "Live: min available balance $", "live entry is refused below this", 90)}
      </div>

      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 12, fontSize: 13, alignItems: "center" }}>
        <label style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={config.enabled} onChange={(e) => onSave({ enabled: e.target.checked })} disabled={busy} />
          Automatic nightly entry
        </label>
        <span style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ color: "var(--muted)", fontWeight: 600 }}>If a formula strike isn&apos;t listed:</span>
          {(
            [
              ["skip", "Skip that night"],
              ["one_side", "Sell only the side that fits"],
              ["farthest", "Use the farthest listed strike"],
            ] as const
          ).map(([value, label]) => (
            <label key={value} style={{ display: "flex", gap: 4, alignItems: "center", cursor: "pointer" }}>
              <input type="radio" name="missingStrike" checked={config.missingStrike === value} onChange={() => onSave({ missingStrike: value })} disabled={busy} />
              {label}
            </label>
          ))}
        </span>
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap", alignItems: "center" }}>
        <button type="button" className="button" onClick={save} disabled={busy}>
          <Save size={14} /> Save settings
        </button>
        <button
          type="button"
          className="button secondary"
          onClick={switchMode}
          disabled={busy || (config.mode === "paper" && !config.liveOrdersAllowed)}
          title={!config.liveOrdersAllowed ? "Live orders are disabled on the server (BTC_STRANGLE_LIVE_ORDER_ENABLED)" : undefined}
        >
          {config.mode === "paper" ? "Switch to LIVE" : "Switch to paper"}
        </button>
        <span className="pcr-oi-caption">
          {config.liveOrdersAllowed
            ? "Live trading is allowed on the server."
            : "Live trading is locked on the server (BTC_STRANGLE_LIVE_ORDER_ENABLED=false) -- paper only."}
          {config.deltaCredentials ? "" : " Delta API keys are not configured."}
        </span>
      </div>
    </Section>
  );
}

function PlanSection({ preview }: { preview: BtcStranglePreview | null }) {
  const legs = preview?.legs;
  return (
    <Section
      id="plan"
      title="Next entry plan"
      aside={
        preview?.entryAt ? <span className="pcr-oi-caption">computed live for the {istDateTime(preview.entryAt)} IST entry</span> : null
      }
    >
      {!preview ? (
        <p className="pcr-oi-caption">Loading…</p>
      ) : preview.error ? (
        <div className="alert warning" style={{ margin: 0 }}>
          No trade would be placed right now: {preview.error}
          {preview.expiryCode ? ` (expiry ${preview.expiryCode})` : ""}
        </div>
      ) : (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {[
              { label: "BTC spot", value: usd(preview.spot, 0) },
              { label: "Expiry (settles)", value: expiryLabel(preview.expiryCode, preview.settlement), caption: `${preview.hoursToSettlement}h from entry` },
              { label: "ATM straddle", value: usd(preview.straddle), caption: `${num(preview.atmStrike, 0)} CE ${num(preview.atmCall)} + PE ${num(preview.atmPut)}` },
              { label: "Distance", value: `±${num(preview.distance, 0)}`, caption: `${preview.multiplier}× straddle` },
              { label: "Est. credit", value: usd(preview.estimatedCredit), caption: `${preview.contracts} contracts per leg, at bid` },
            ].map((m) => (
              <div key={m.label} className="metric metric-compact" style={{ flex: "1 1 150px" }}>
                <span>{m.label}</span>
                <strong>{m.value}</strong>
                {m.caption ? <span className="pcr-oi-caption">{m.caption}</span> : null}
              </div>
            ))}
          </div>
          {preview.variant === "one_side" && preview.missingSide ? (
            <div className="alert warning" style={{ margin: "8px 0 0" }}>
              One-sided: the {preview.missingSide} formula strike isn&apos;t listed (needs {preview.missingSide === "PE" ? "≤" : "≥"}{" "}
              {num(preview.missingTarget, 0)}, farthest listed {num(preview.missingFarthestListed, 0)}) -- only the{" "}
              {preview.missingSide === "PE" ? "CE" : "PE"} leg would be sold.
            </div>
          ) : null}
          {preview.fallback ? (
            <div className="alert warning" style={{ margin: "8px 0 0" }}>
              Formula strike isn&apos;t listed on Delta -- using the farthest listed strike (closer than the formula).
            </div>
          ) : null}
          {legs ? (
            <>
              <StrikeDistanceMap
                id="plan"
                spot={preview.spot}
                legs={(["PE", "CE"] as const)
                  .filter((side) => legs[side])
                  .map((side) => ({
                    key: side,
                    strike: legs[side]!.strike,
                    label: `${legs[side]!.strike.toLocaleString("en-US")} ${side}`,
                    short: true,
                  }))}
              />
              <div style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Leg</th>
                      <th>Formula level</th>
                      <th>Strike</th>
                      <th>From spot</th>
                      <th>Bid / Ask</th>
                      <th>Mark</th>
                      <th>IV</th>
                      <th>Sell at</th>
                      <th>Stop loss</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(["PE", "CE"] as const).map((side) => {
                      const quote = legs[side];
                      if (!quote) {
                        return (
                          <tr key={side}>
                            <td>
                              <span className="badge">{side}</span>
                            </td>
                            <td>{num(side === "CE" ? preview.callTarget : preview.putTarget, 0)}</td>
                            <td colSpan={7} className="pcr-oi-caption">
                              not listed on Delta -- skipped
                            </td>
                          </tr>
                        );
                      }
                      const p = preview.preview?.[side];
                      return (
                        <tr key={side}>
                          <td>
                            <span className="badge sell">SELL {side}</span>
                          </td>
                          <td>{num(side === "CE" ? preview.callTarget : preview.putTarget, 0)}</td>
                          <td>
                            <strong>{quote.strike.toLocaleString("en-US")}</strong>
                            <span className="subtext">{quote.symbol}</span>
                          </td>
                          <td>{num(p?.distancePercent, 2)}%</td>
                          <td>
                            {num(quote.bid)} / {num(quote.ask)}
                          </td>
                          <td>{num(quote.mark)}</td>
                          <td>{quote.iv ? `${num(quote.iv * 100)}%` : "—"}</td>
                          <td>{num(p?.entryPrice)}</td>
                          <td>{num(p?.slPrice)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
        </>
      )}
    </Section>
  );
}

function OpenTradeCard({
  trade,
  spot,
  busy,
  onCloseLeg,
}: {
  trade: BtcStrangleTrade;
  spot: number | null;
  busy: string | null;
  onCloseLeg: (trade: BtcStrangleTrade, leg: BtcStrangleLeg) => void;
}) {
  const [expanded, toggle] = useSectionExpanded(`trade-${trade.id}`, true);
  const filledLegs = trade.legs.filter((l) => l.entryPrice);
  return (
    <div className="strategy-chart-card" style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", flexWrap: "wrap" }} onClick={toggle}>
        <button className="icon-button" type="button" aria-expanded={expanded}>
          {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </button>
        <strong>
          #{trade.id} · {trade.mode.toUpperCase()} · expiry {trade.expiryCode}
        </strong>
        <span className="pcr-oi-caption">
          entered {istDateTime(trade.entryTime)} · settles {istDateTime(trade.settlementTime)} IST
        </span>
        <span style={{ marginLeft: "auto", fontSize: 13 }}>
          Credit {usd(trade.credit)} · P&amp;L <strong style={{ color: tone(trade.grossPnl) }}>{usd(trade.grossPnl)}</strong> · Net{" "}
          <strong style={{ color: tone(trade.netPnl) }}>{usd(trade.netPnl)}</strong>
        </span>
      </div>
      <StrikeDistanceMap
        id={`trade-${trade.id}`}
        spot={spot}
        legs={filledLegs.map((l) => ({
          key: String(l.id),
          strike: l.strike,
          label: `${l.strike.toLocaleString("en-US")} ${l.optionType}`,
          short: l.status === "OPEN",
        }))}
      />
      {expanded ? (
        <>
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Leg</th>
                  <th>Contracts</th>
                  <th>Entry</th>
                  <th>Mark</th>
                  <th>Bid / Ask</th>
                  <th>Stop loss</th>
                  <th>P&amp;L</th>
                  <th>%</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {trade.legs.map((leg) => (
                  <tr key={leg.id}>
                    <td>
                      <strong>{leg.symbol}</strong>
                      {leg.error ? <span className="subtext" style={{ color: "var(--red)" }}>{leg.error}</span> : null}
                    </td>
                    <td>
                      {leg.contracts}
                      {leg.contracts !== leg.requestedContracts ? <span className="subtext">of {leg.requestedContracts}</span> : null}
                    </td>
                    <td>{num(leg.entryPrice)}</td>
                    <td>{num(leg.status === "OPEN" ? leg.lastMark : leg.exitPrice)}</td>
                    <td>
                      {num(leg.lastBid)} / {num(leg.lastAsk)}
                    </td>
                    <td>{num(leg.slPrice)}</td>
                    <td style={{ color: tone(leg.pnl) }}>{usd(leg.pnl)}</td>
                    <td style={{ color: tone(leg.pnlPercent) }}>{leg.pnlPercent != null ? `${num(leg.pnlPercent)}%` : "—"}</td>
                    <td>
                      {leg.status === "CLOSED" ? (EXIT_REASON_LABEL[leg.exitReason ?? ""] ?? leg.exitReason) : leg.status}
                    </td>
                    <td>
                      {leg.status === "OPEN" ? (
                        <button
                          type="button"
                          className="icon-button danger"
                          title="Buy back this leg now"
                          onClick={() => onCloseLeg(trade, leg)}
                          disabled={busy === `leg-${leg.id}`}
                        >
                          <SquareArrowOutUpRight size={15} />
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {trade.notes ? <p className="pcr-oi-caption">{trade.notes}</p> : null}
          <StrategyChart trade={trade} />
        </>
      ) : null}
    </div>
  );
}

function StrategyChart({ trade }: { trade: BtcStrangleTrade }) {
  const [resolution, setResolution] = useState("5m");
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceRef = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapRef = useRef<ISeriesApi<"Line"> | null>(null);
  const creditLineRef = useRef<ReturnType<ISeriesApi<"Line">["createPriceLine"]> | null>(null);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: containerRef.current.clientWidth,
      height: 260,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (t: Time) => istTime(t) },
      localization: { timeFormatter: (t: Time) => istTime(t) },
    });
    priceRef.current = chart.addSeries(LineSeries, { color: "#2368b6", lineWidth: 2, title: "Strangle price" });
    vwapRef.current = chart.addSeries(LineSeries, { color: "#a56513", lineWidth: 2, title: "VWAP" });
    chartRef.current = chart;
    const observer = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await getBtcStrangleChart(trade.id, resolution);
        if (cancelled || !priceRef.current || !vwapRef.current) return;
        priceRef.current.setData(data.points.map((p) => ({ time: p.time as UTCTimestamp, value: p.price })));
        vwapRef.current.setData(data.points.map((p) => ({ time: p.time as UTCTimestamp, value: p.vwap })));
        if (creditLineRef.current) priceRef.current.removePriceLine(creditLineRef.current);
        creditLineRef.current = priceRef.current.createPriceLine({
          price: data.entryCredit,
          color: "#168448",
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: "Entry credit",
        });
        setError(null);
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : "Chart failed.");
      }
    }
    load();
    const timer = window.setInterval(load, 60000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [trade.id, resolution]);

  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <span className="pcr-oi-caption">
          Strangle price = sum of the legs&apos; mark prices (a closed leg held at its exit price); VWAP weighted by traded option volume.
        </span>
        <select value={resolution} onChange={(e) => setResolution(e.target.value)} style={{ marginLeft: "auto", fontSize: 12 }}>
          {["1m", "3m", "5m", "15m"].map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </div>
      {error ? <div className="alert error">{error}</div> : null}
      <div ref={containerRef} style={{ width: "100%" }} />
    </div>
  );
}

const SPOT_REFRESH_MS = 30000;

const BAR_SECONDS: Record<string, number> = { "1m": 60, "5m": 300, "15m": 900, "1h": 3600 };

function btcStrangleNotes(trades: BtcStrangleTrade[]): TradeNote[] {
  return trades.flatMap((t) => {
    const legs = t.legs.filter((l) => l.entryPrice != null);
    if (!legs.length) return [];
    const variant = t.variant && t.variant !== "strangle" ? ` (${VARIANT_LABEL[t.variant]})` : "";
    const entry: TradeNote = {
      time: t.entryTime,
      kind: "entry",
      label: `#${t.id} sell`,
      color: "#c93535",
      title: `Entry #${t.id} · sold ${legs.map((l) => `${l.strike} ${l.optionType}`).join(" / ")}${variant}`,
      lines: [
        `${noteTime(t.entryTime)} IST · BTC ${num(t.spot, 0)} · expiry ${t.expiryCode} · ${t.mode}`,
        `Why: nightly ${t.trigger === "manual" ? "manual" : "scheduled"} entry -- strikes at spot ± ${t.multiplier} × ATM straddle ${num(t.straddle, 0)} = ${num(t.distance, 0)}`,
        `Sold ${legs.map((l) => `${l.optionType} @ ${num(l.entryPrice)} (stop ${num(l.slPrice)})`).join(", ")} · ${t.contracts} contracts`,
        t.notes ?? "",
      ],
    };
    const exits: TradeNote[] = legs
      .filter((l) => l.exitTime)
      .map((l) => ({
        time: l.exitTime as number,
        kind: "exit",
        label: `${l.optionType} ${usd(l.pnl ?? null, 0)}`,
        color: (l.pnl ?? 0) >= 0 ? "#168448" : "#c93535",
        title: `Exit #${t.id} · ${l.strike} ${l.optionType} @ ${num(l.exitPrice)} · ${usd(l.pnl ?? null)}`,
        lines: [`${noteTime(l.exitTime)} IST · sold at ${num(l.entryPrice)}`, `Why: ${EXIT_REASON_LABEL[l.exitReason ?? ""] ?? l.exitReason}`],
      }));
    return [entry, ...exits];
  });
}

function SpotChart({ trades }: { trades: BtcStrangleTrade[] }) {
  const [handles, setHandles] = useState<{ chart: IChartApi; series: ISeriesApi<"Candlestick"> } | null>(null);
  const [barTimes, setBarTimes] = useState<number[]>([]);
  const [resolution, setResolution] = useState("5m");
  const [last, setLast] = useState<{ close: number; time: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const linesRef = useRef<IPriceLine[]>([]);
  const fittedRef = useRef<string | null>(null);
  const strikesRef = useRef<number[]>([]);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: containerRef.current.clientWidth,
      height: 320,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (t: Time) => istTime(t) },
      localization: { timeFormatter: (t: Time) => istTime(t) },
    });
    seriesRef.current = chart.addSeries(CandlestickSeries, {
      upColor: "#168448",
      downColor: "#c93535",
      borderVisible: false,
      wickUpColor: "#168448",
      wickDownColor: "#c93535",
      // Keep the open short strikes inside the price scale, not just the
      // candles, so both strike lines are always visible.
      autoscaleInfoProvider: (original: () => { priceRange: { minValue: number; maxValue: number } | null } | null) => {
        const result = original();
        if (!result?.priceRange || !strikesRef.current.length) return result;
        return {
          ...result,
          priceRange: {
            minValue: Math.min(result.priceRange.minValue, ...strikesRef.current),
            maxValue: Math.max(result.priceRange.maxValue, ...strikesRef.current),
          },
        };
      },
    });
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

  const notes = useMemo(() => btcStrangleNotes(trades), [trades]);
  const tooltip = useTradeMarkers(handles?.chart ?? null, handles?.series ?? null, notes, BAR_SECONDS[resolution] ?? 300, barTimes);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await getBtcSpotChart(resolution);
        const series = seriesRef.current;
        if (cancelled || !series) return;
        series.setData(
          data.candles.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })),
        );
        setBarTimes(data.candles.map((c) => c.time));
        strikesRef.current = data.strikes.map((s) => s.strike);
        for (const line of linesRef.current) series.removePriceLine(line);
        linesRef.current = data.strikes.map((s) =>
          series.createPriceLine({
            price: s.strike,
            color: "#c93535",
            lineWidth: 1,
            lineStyle: 2,
            axisLabelVisible: true,
            title: `Short ${s.label}`,
          }),
        );
        // Fit once per resolution so a manual zoom/scroll isn't reset by the 30s refresh.
        if (fittedRef.current !== resolution) {
          chartRef.current?.timeScale().fitContent();
          fittedRef.current = resolution;
        }
        const latest = data.candles[data.candles.length - 1];
        setLast(latest ? { close: latest.close, time: latest.time } : null);
        setError(null);
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : "Spot chart failed.");
      }
    }
    load();
    const timer = window.setInterval(load, SPOT_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [resolution]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6, flexWrap: "wrap" }}>
        <strong style={{ fontSize: 15 }}>{last ? usd(last.close, 1) : "—"}</strong>
        <span className="pcr-oi-caption">{last ? `last candle ${istTime(last.time as Time)} IST` : ""}</span>
        <span className="pcr-oi-caption">Red dashed lines = short strikes of open strangles · ▲ entries, ▼ leg exits -- hover for the reason.</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
          {["1m", "5m", "15m", "1h"].map((r) => (
            <button
              key={r}
              type="button"
              className="button secondary"
              style={{ padding: "2px 8px", fontSize: 12, ...(r === resolution ? { background: "var(--blue)", color: "#fff" } : {}) }}
              onClick={() => setResolution(r)}
            >
              {r}
            </button>
          ))}
        </div>
      </div>
      {error ? <div className="alert error">{error}</div> : null}
      <div style={{ position: "relative" }}>
        <div ref={containerRef} style={{ width: "100%" }} />
        {tooltip}
      </div>
    </div>
  );
}

function istTime(time: Time): string {
  if (typeof time !== "number") return String(time);
  return new Date(time * 1000).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

const VARIANT_LABEL: Record<string, string> = { strangle: "Full strangle", one_side: "One-sided", farthest: "Farthest strike" };

function VariantSummary({ trades }: { trades: BtcStrangleTrade[] }) {
  const closed = trades.filter((t) => t.status === "CLOSED");
  const groups = (["strangle", "one_side", "farthest"] as const)
    .map((v) => {
      const rows = closed.filter((t) => (t.variant ?? "strangle") === v);
      return { v, n: rows.length, wins: rows.filter((t) => t.netPnl > 0).length, net: rows.reduce((a, t) => a + t.netPnl, 0) };
    })
    .filter((g) => g.n || g.v === "strangle");
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
      {groups.map((g) => (
        <div key={g.v} className="metric metric-compact" style={{ flex: "0 1 220px" }}>
          <span>{VARIANT_LABEL[g.v]}</span>
          <strong style={{ color: tone(g.net) }}>{usd(g.net)}</strong>
          <span className="pcr-oi-caption">
            {g.n} closed · {g.n ? `${Math.round((g.wins / g.n) * 100)}% winners` : "—"}
          </span>
        </div>
      ))}
    </div>
  );
}

function TradesTable({ trades }: { trades: BtcStrangleTrade[] }) {
  if (!trades.length) return <p className="pcr-oi-caption" style={{ margin: 0 }}>No trades yet.</p>;
  return (
    <div style={{ overflowX: "auto" }}>
      <VariantSummary trades={trades} />
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
            <th>Fees</th>
            <th>Net</th>
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
                <td>{istDateTime(t.entryTime)}</td>
                <td>{t.expiryCode}</td>
                <td>{num(t.spot, 0)}</td>
                <td>
                  {pe ? pe.strike.toLocaleString("en-US") : "—"} / {ce ? ce.strike.toLocaleString("en-US") : "—"}
                </td>
                <td className="pcr-oi-caption" style={{ fontStyle: "normal" }}>
                  {t.multiplier}× · SL {t.stopLossPercent}% · {t.contracts}
                  {t.variant && t.variant !== "strangle" ? (
                    <span className="badge" style={{ marginLeft: 6 }} title={t.notes ?? ""}>
                      {VARIANT_LABEL[t.variant]}
                    </span>
                  ) : null}
                </td>
                <td>{usd(t.credit)}</td>
                <td style={{ fontSize: 12 }}>
                  {t.legs
                    .map((l) => `${l.optionType}: ${l.status === "CLOSED" ? `${EXIT_REASON_LABEL[l.exitReason ?? ""] ?? l.exitReason} @ ${num(l.exitPrice)}` : l.status}`)
                    .join(" · ")}
                </td>
                <td style={{ color: tone(t.grossPnl) }}>{usd(t.grossPnl)}</td>
                <td>{usd(t.fees)}</td>
                <td style={{ color: tone(t.netPnl) }}>
                  <strong>{usd(t.netPnl)}</strong>
                </td>
                <td>{t.status}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
