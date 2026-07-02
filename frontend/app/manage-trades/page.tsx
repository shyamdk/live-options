"use client";

import { LogIn, RefreshCcw, Save, ShieldAlert, SquareArrowOutUpRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { closeTrade, getDhanSession, getLiveTrades, loginDhan, saveTradeLevels } from "@/lib/api";
import type { DhanSession, LiveTrade, LiveTradeSnapshot } from "@/types/live";

type DraftLevels = {
  stopLoss: string;
  target: string;
  notes: string;
};

const moneyFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });

export default function ManageTradesPage() {
  const [session, setSession] = useState<DhanSession | null>(null);
  const [snapshot, setSnapshot] = useState<LiveTradeSnapshot | null>(null);
  const [drafts, setDrafts] = useState<Record<string, DraftLevels>>({});
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [sessionPayload, tradePayload] = await Promise.all([getDhanSession(), getLiveTrades()]);
      setSession(sessionPayload);
      setSnapshot(tradePayload);
      setDrafts(draftsFromSnapshot(tradePayload));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load trades.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 15000);
    return () => window.clearInterval(timer);
  }, []);

  async function handleLogin(forceRefresh = false) {
    setMessage(null);
    setError(null);
    try {
      await loginDhan(forceRefresh);
      setMessage("Dhan login verified.");
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Dhan login failed.");
    }
  }

  async function handleSave(trade: LiveTrade) {
    setSavingId(trade.id);
    setMessage(null);
    setError(null);
    try {
      const draft = drafts[trade.id] ?? emptyDraft();
      await saveTradeLevels(trade.id, {
        stopLoss: draftNumber(draft.stopLoss),
        target: draftNumber(draft.target),
        notes: draft.notes,
      });
      setMessage(`${tradeLabel(trade)} levels saved.`);
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to save levels.");
    } finally {
      setSavingId(null);
    }
  }

  async function handleClose(trade: LiveTrade) {
    if (!window.confirm(`Close ${tradeLabel(trade)} quantity ${trade.absQty}?`)) return;
    setSavingId(trade.id);
    setMessage(null);
    setError(null);
    try {
      const result = await closeTrade(trade.id);
      const status = String(result.status ?? "submitted");
      setMessage(`${tradeLabel(trade)} close ${status}.`);
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to close trade.");
    } finally {
      setSavingId(null);
    }
  }

  function updateDraft(tradeId: string, key: keyof DraftLevels, value: string) {
    setDrafts((current) => ({ ...current, [tradeId]: { ...(current[tradeId] ?? emptyDraft()), [key]: value } }));
  }

  const summary = snapshot?.summary;
  const optionTrades = useMemo(() => [...(snapshot?.groups.optionsBuy ?? []), ...(snapshot?.groups.optionsSell ?? [])], [snapshot]);

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>Manage Trades</h1>
          <p>{snapshot?.updatedAt ? `Updated ${snapshot.updatedAt}` : "Live Dhan positions"}</p>
        </div>
        <div className="toolbar">
          <button className="button secondary" type="button" onClick={() => handleLogin(false)} disabled={loading}>
            <LogIn size={16} />
            Login
          </button>
          <button className="icon-button" type="button" title="Refresh trades" onClick={load} disabled={loading}>
            <RefreshCcw size={16} />
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {snapshot?.warning ? <div className="alert warning">{snapshot.warning}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}

      <div className="status-row">
        <span className={session?.hasAccessToken && session?.hasClientId ? "status-dot ok" : "status-dot warn"} />
        <span>Dhan {session?.hasAccessToken && session?.hasClientId ? "connected" : "not verified"}</span>
        <span className={session?.liveOrderEnabled ? "status-live on" : "status-live"}>Live orders {session?.liveOrderEnabled ? "on" : "off"}</span>
      </div>

      <div className="metric-grid">
        <Metric label="Day P&L" value={money(summary?.dayPnl)} tone={tone(summary?.dayPnl)} />
        <Metric label="Net P&L" value={money(summary?.estimatedNetPnl)} tone={tone(summary?.estimatedNetPnl)} />
        <Metric label="Charges" value={money(summary?.estimatedCharges)} />
        <Metric label="Open P&L" value={money(summary?.openPnl)} tone={tone(summary?.openPnl)} />
        <Metric label="Realized" value={money(summary?.realizedPnl)} tone={tone(summary?.realizedPnl)} />
        <Metric label="Positions" value={String(summary?.totalPositions ?? 0)} />
        <Metric label="Levels" value={String(summary?.configuredLevels ?? 0)} />
      </div>

      <TradeTable title="Equity" trades={snapshot?.groups.equity ?? []} loading={loading} />

      <OptionTradeTable
        title="Options Buy"
        trades={snapshot?.groups.optionsBuy ?? []}
        drafts={drafts}
        savingId={savingId}
        loading={loading}
        onDraft={updateDraft}
        onSave={handleSave}
        onClose={handleClose}
        showRemainingProfit={false}
      />

      <OptionTradeTable
        title="Options Sell"
        trades={snapshot?.groups.optionsSell ?? []}
        drafts={drafts}
        savingId={savingId}
        loading={loading}
        onDraft={updateDraft}
        onSave={handleSave}
        onClose={handleClose}
        showRemainingProfit
      />

      {!loading && !optionTrades.length && !snapshot?.groups.equity.length ? <div className="empty-state">No live positions returned by Dhan.</div> : null}
    </section>
  );
}

function Metric({ label, value, tone: metricTone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={metricTone}>{value}</strong>
    </div>
  );
}

function TradeTable({ title, trades, loading }: { title: string; trades: LiveTrade[]; loading: boolean }) {
  return (
    <section className="table-section">
      <div className="section-title">
        <h2>{title}</h2>
        <span>{trades.length}</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Side</th>
              <th>Qty</th>
              <th>Avg</th>
              <th>LTP</th>
              <th>P&L</th>
              <th>%</th>
              <th>Product</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade) => (
              <tr key={trade.id}>
                <td>
                  <strong>{trade.tradingSymbol}</strong>
                  <span className="subtext">{trade.exchangeSegment || "-"}</span>
                </td>
                <td><Badge tone={trade.side === "BUY" ? "buy" : "sell"}>{trade.side}</Badge></td>
                <td>{trade.qty}</td>
                <td>{money(trade.avgPrice)}</td>
                <td><PriceCell trade={trade} /></td>
                <td className={tone(trade.dayPnl)}>{money(trade.dayPnl)}</td>
                <td className={tone(trade.percentChange)}>{percent(trade.percentChange)}</td>
                <td>{trade.productType || "-"}</td>
              </tr>
            ))}
            {!trades.length ? (
              <tr>
                <td colSpan={8}>{loading ? "Loading" : "No equity positions"}</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function OptionTradeTable({
  title,
  trades,
  drafts,
  savingId,
  loading,
  onDraft,
  onSave,
  onClose,
  showRemainingProfit,
}: {
  title: string;
  trades: LiveTrade[];
  drafts: Record<string, DraftLevels>;
  savingId: string | null;
  loading: boolean;
  onDraft: (tradeId: string, key: keyof DraftLevels, value: string) => void;
  onSave: (trade: LiveTrade) => void;
  onClose: (trade: LiveTrade) => void;
  showRemainingProfit: boolean;
}) {
  const emptyColSpan = showRemainingProfit ? 16 : 13;
  return (
    <section className="table-section">
      <div className="section-title">
        <h2>{title}</h2>
        <span>{trades.length}</span>
      </div>
      <div className="table-wrap">
        <table className={showRemainingProfit ? "wide-table" : ""}>
          <thead>
            <tr>
              <th>Strike</th>
              <th>Side</th>
              <th>Qty</th>
              <th>Avg</th>
              <th>LTP</th>
              <th>P&L</th>
              <th>Net</th>
              <th>Charges</th>
              <th>%</th>
              {showRemainingProfit ? <th>Remaining</th> : null}
              {showRemainingProfit ? <th>Remain %</th> : null}
              <th>Spot Dist</th>
              <th>SL</th>
              <th>Target</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade) => {
              const draft = drafts[trade.id] ?? emptyDraft();
              const busy = savingId === trade.id;
              return (
                <tr key={trade.id}>
                  <td>
                    <strong>{tradeLabel(trade)}</strong>
                    <span className="subtext">{trade.expiry || "-"} · {trade.productType || "-"}</span>
                  </td>
                  <td><Badge tone={trade.side === "BUY" ? "buy" : "sell"}>{trade.side}</Badge></td>
                  <td>{trade.qty}</td>
                  <td>{money(trade.avgPrice)}</td>
                  <td><PriceCell trade={trade} /></td>
                  <td className={tone(trade.dayPnl)}>{money(trade.dayPnl)}</td>
                  <td className={tone(trade.estimatedNetPnl)}>{money(trade.estimatedNetPnl)}</td>
                  <td>{money(trade.estimatedCharges)}</td>
                  <td className={tone(trade.percentChange)}>{percent(trade.percentChange)}</td>
                  {showRemainingProfit ? <td>{money(trade.profitRemaining)}</td> : null}
                  {showRemainingProfit ? <td>{plainPercent(trade.profitRemainingPercent)}</td> : null}
                  <td className={spotDistanceClass(trade)}>
                    {plainPercent(trade.spotDistancePercent)}
                    <span className="subtext">{trade.spotDistancePoints === null || trade.spotDistancePoints === undefined ? "-" : `${money(trade.spotDistancePoints)} pts`}</span>
                  </td>
                  <td>
                    <input
                      className="level-input"
                      inputMode="decimal"
                      value={draft.stopLoss}
                      onChange={(event) => onDraft(trade.id, "stopLoss", event.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      className="level-input"
                      inputMode="decimal"
                      value={draft.target}
                      onChange={(event) => onDraft(trade.id, "target", event.target.value)}
                    />
                  </td>
                  <td>
                    <span className={`risk-pill ${trade.riskStatus?.kind ?? "none"}`}>
                      {(trade.riskStatus?.kind === "stopLoss") ? <ShieldAlert size={13} /> : null}
                      {trade.riskStatus?.label ?? "Monitoring"}
                    </span>
                  </td>
                  <td>
                    <div className="row-actions">
                      <button className="icon-button" type="button" title="Save levels" onClick={() => onSave(trade)} disabled={busy}>
                        <Save size={15} />
                      </button>
                      <button className="icon-button danger" type="button" title="Close position" onClick={() => onClose(trade)} disabled={busy}>
                        <SquareArrowOutUpRight size={15} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {!trades.length ? (
              <tr>
                <td colSpan={emptyColSpan}>{loading ? "Loading" : "No option positions"}</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Badge({ tone: badgeTone, children }: { tone: "buy" | "sell"; children: React.ReactNode }) {
  return <span className={`badge ${badgeTone}`}>{children}</span>;
}

function PriceCell({ trade }: { trade: LiveTrade }) {
  return (
    <>
      {money(trade.ltp)}
      {trade.ltpStale ? <span className="subtext">stale</span> : null}
    </>
  );
}

function draftsFromSnapshot(snapshot: LiveTradeSnapshot): Record<string, DraftLevels> {
  const rows = [...snapshot.groups.optionsBuy, ...snapshot.groups.optionsSell];
  return Object.fromEntries(rows.map((trade) => [trade.id, {
    stopLoss: valueText(trade.levels?.stopLoss),
    target: valueText(trade.levels?.target),
    notes: trade.levels?.notes ?? "",
  }]));
}

function emptyDraft(): DraftLevels {
  return { stopLoss: "", target: "", notes: "" };
}

function valueText(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

function draftNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function tradeLabel(trade: LiveTrade): string {
  const strike = trade.strikePrice ? String(trade.strikePrice).replace(/\.0$/, "") : trade.tradingSymbol;
  return `${trade.symbol} ${strike} ${trade.optionSide ?? ""}`.trim();
}

function money(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return moneyFormat.format(value);
}

function percent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${value >= 0 ? "+" : ""}${moneyFormat.format(value)}%`;
}

function plainPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${moneyFormat.format(value)}%`;
}

function spotDistanceClass(trade: LiveTrade): string {
  return `spot-distance-cell ${trade.spotDistanceAlert ? "negative" : ""}`.trim();
}

function tone(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value) || value === 0) return "";
  return value > 0 ? "positive" : "negative";
}
