"use client";

import { LogIn, RefreshCcw, Save, ShieldAlert, ShieldCheck, SquareArrowOutUpRight } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { approveRiskExit, closeTrade, getDhanSession, getLiveTrades, loginDhan, saveTradeLevels } from "@/lib/api";
import type { DhanSession, LiveTrade, LiveTradeSnapshot } from "@/types/live";

type DraftLevels = {
  stopLoss: string;
  target: string;
  notes: string;
};

const moneyFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const TRADE_REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_TRADES_REFRESH_SECONDS, 3);
const SESSION_REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_SESSION_REFRESH_SECONDS, 120);
const RISK_ALERT_REPEAT_MS = 15_000;
const AWAITING_APPROVAL_KINDS = new Set(["stopLossSignal", "targetSignal", "orderFailed"]);

export default function ManageTradesPage() {
  const [session, setSession] = useState<DhanSession | null>(null);
  const [snapshot, setSnapshot] = useState<LiveTradeSnapshot | null>(null);
  const [drafts, setDrafts] = useState<Record<string, DraftLevels>>({});
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const notifiedAtRef = useRef<Record<string, number>>({});

  async function loadSession() {
    try {
      setSession(await getDhanSession());
    } catch {
      // Trade refresh should not fail just because the status pill could not update.
    }
  }

  async function loadTrades() {
    setLoading(true);
    setError(null);
    try {
      const tradePayload = await getLiveTrades();
      setSnapshot(tradePayload);
      setDrafts(draftsFromSnapshot(tradePayload));
      checkRiskAlerts(tradePayload);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load trades.");
    } finally {
      setLoading(false);
    }
  }

  async function load() {
    await Promise.all([loadSession(), loadTrades()]);
  }

  function checkRiskAlerts(payload: LiveTradeSnapshot) {
    const trades = [...payload.groups.optionsBuy, ...payload.groups.optionsSell];
    const now = Date.now();
    for (const trade of trades) {
      if (!isAwaitingApproval(trade)) continue;
      const key = `${trade.id}:${trade.riskStatus?.signalKind ?? ""}:${trade.riskStatus?.level ?? ""}`;
      const lastNotified = notifiedAtRef.current[key];
      if (lastNotified && now - lastNotified < RISK_ALERT_REPEAT_MS) continue;
      notifiedAtRef.current[key] = now;
      notifyRiskSignal(trade);
    }
  }

  useEffect(() => {
    if (typeof window !== "undefined" && "Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
    load();
    const tradeTimer = window.setInterval(loadTrades, TRADE_REFRESH_MS);
    const sessionTimer = window.setInterval(loadSession, SESSION_REFRESH_MS);
    return () => {
      window.clearInterval(tradeTimer);
      window.clearInterval(sessionTimer);
    };
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
        stopLoss: stopLossDraftNumber(trade, draft.stopLoss),
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

  async function handleApprove(trade: LiveTrade) {
    const kindLabel = riskSignalKind(trade) === "target" ? "Target" : "Stop Loss";
    if (!window.confirm(`Approve ${kindLabel} exit for ${tradeLabel(trade)}? This sends a market order to Dhan.`)) return;
    setSavingId(trade.id);
    setMessage(null);
    setError(null);
    try {
      const result = await approveRiskExit(trade.id);
      const status = String(result.status ?? "submitted");
      setMessage(`${tradeLabel(trade)} ${kindLabel} exit ${status}.`);
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to approve risk exit.");
    } finally {
      setSavingId(null);
    }
  }

  function updateDraft(tradeId: string, key: keyof DraftLevels, value: string) {
    setDrafts((current) => ({ ...current, [tradeId]: { ...(current[tradeId] ?? emptyDraft()), [key]: value } }));
  }

  const summary = snapshot?.summary;
  const optionTrades = useMemo(() => [...(snapshot?.groups.optionsBuy ?? []), ...(snapshot?.groups.optionsSell ?? [])], [snapshot]);
  const awaitingApproval = useMemo(() => optionTrades.filter(isAwaitingApproval), [optionTrades]);
  const closedTrades = snapshot?.groups.closed ?? [];
  const closedEquity = closedTrades.filter((trade) => trade.assetClass === "EQUITY");
  const closedOptionsBuy = closedTrades.filter((trade) => trade.assetClass === "OPTION" && trade.side === "BUY");
  const closedOptionsSell = closedTrades.filter((trade) => trade.assetClass === "OPTION" && trade.side === "SELL");

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
      {awaitingApproval.length ? (
        <div className="alert warning risk-approval-banner">
          <strong>
            {awaitingApproval.length} position{awaitingApproval.length > 1 ? "s" : ""} awaiting SL/Target approval
          </strong>
          <ul>
            {awaitingApproval.map((trade) => (
              <li key={trade.id}>
                {tradeLabel(trade)} — {trade.riskStatus?.label} @ {money(trade.riskStatus?.level)} (LTP {money(trade.ltp)})
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="status-row">
        <span className={session?.hasAccessToken && session?.hasClientId ? "status-dot ok" : "status-dot warn"} />
        <span>Dhan {session?.hasAccessToken && session?.hasClientId ? "connected" : "not verified"}</span>
        <span className={session?.liveOrderEnabled ? "status-live on" : "status-live"}>Live orders {session?.liveOrderEnabled ? "on" : "off"}</span>
        <span className={riskOrdersArmed(session) ? "status-live on" : "status-live"}>
          Risk orders {riskOrderLabel(session)}
        </span>
      </div>

      <div className="metric-grid">
        <Metric label="Day P&L" value={money(summary?.dayPnl)} tone={tone(summary?.dayPnl)} />
        <Metric label="Net P&L" value={money(summary?.estimatedNetPnl)} tone={tone(summary?.estimatedNetPnl)} />
        <Metric label="Charges" value={money(summary?.estimatedCharges)} />
        <Metric label="Open P&L" value={money(summary?.openPnl)} tone={tone(summary?.openPnl)} />
        <Metric label="Realized" value={money(summary?.realizedPnl)} tone={tone(summary?.realizedPnl)} />
        <Metric label="Positions" value={String(summary?.totalPositions ?? 0)} />
        <Metric label="Closed" value={String(summary?.closedCount ?? 0)} />
        <Metric label="Levels" value={String(summary?.configuredLevels ?? 0)} />
      </div>

      <TradeTable title="Equity" trades={snapshot?.groups.equity ?? []} closedTrades={closedEquity} loading={loading} />

      <OptionTradeTable
        title="Options Buy"
        trades={snapshot?.groups.optionsBuy ?? []}
        closedTrades={closedOptionsBuy}
        drafts={drafts}
        savingId={savingId}
        loading={loading}
        onDraft={updateDraft}
        onSave={handleSave}
        onClose={handleClose}
        onApprove={handleApprove}
        showRemainingProfit={false}
      />

      <OptionTradeTable
        title="Options Sell"
        trades={snapshot?.groups.optionsSell ?? []}
        closedTrades={closedOptionsSell}
        drafts={drafts}
        savingId={savingId}
        loading={loading}
        onDraft={updateDraft}
        onSave={handleSave}
        onClose={handleClose}
        onApprove={handleApprove}
        showRemainingProfit
      />

      {!loading && !closedTrades.length && !optionTrades.length && !snapshot?.groups.equity.length ? <div className="empty-state">No positions returned by Dhan.</div> : null}
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

function TradeTable({ title, trades, closedTrades, loading }: { title: string; trades: LiveTrade[]; closedTrades: LiveTrade[]; loading: boolean }) {
  const totalRows = trades.length + closedTrades.length;
  return (
    <section className="table-section">
      <div className="section-title">
        <h2>{title}</h2>
        <span>{totalRows}</span>
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
            {closedTrades.length ? <ClosedSubsectionRow colSpan={8} count={closedTrades.length} /> : null}
            {closedTrades.map((trade) => (
              <tr className="closed-row" key={trade.id}>
                <td>
                  <strong>{trade.tradingSymbol}</strong>
                  <span className="subtext">{trade.exchangeSegment || "-"}</span>
                </td>
                <td><Badge tone={trade.side === "BUY" ? "buy" : "sell"}>{trade.side}</Badge></td>
                <td>{trade.closedQty ?? trade.absQty}</td>
                <td>{money(trade.entryAvgPrice ?? trade.avgPrice)}</td>
                <td>{money(trade.exitAvgPrice ?? trade.ltp)}</td>
                <td className={tone(trade.dayPnl)}>{money(trade.dayPnl)}</td>
                <td className={tone(trade.percentChange)}>{percent(trade.percentChange)}</td>
                <td>{trade.productType || "-"}</td>
              </tr>
            ))}
            {!totalRows ? (
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
  closedTrades,
  drafts,
  savingId,
  loading,
  onDraft,
  onSave,
  onClose,
  onApprove,
  showRemainingProfit,
}: {
  title: string;
  trades: LiveTrade[];
  closedTrades: LiveTrade[];
  drafts: Record<string, DraftLevels>;
  savingId: string | null;
  loading: boolean;
  onDraft: (tradeId: string, key: keyof DraftLevels, value: string) => void;
  onSave: (trade: LiveTrade) => void;
  onClose: (trade: LiveTrade) => void;
  onApprove: (trade: LiveTrade) => void;
  showRemainingProfit: boolean;
}) {
  const columnCount = showRemainingProfit ? 16 : 14;
  const totalRows = trades.length + closedTrades.length;
  return (
    <section className="table-section">
      <div className="section-title">
        <h2>{title}</h2>
        <span>{totalRows}</span>
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
              <th>SL %</th>
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
                    <div className="level-field">
                      <input
                        className="level-input"
                        inputMode="text"
                        placeholder="%"
                        value={draft.stopLoss}
                        onChange={(event) => onDraft(trade.id, "stopLoss", event.target.value)}
                      />
                      <span className="level-preview">{stopLossPreview(trade, draft.stopLoss)}</span>
                    </div>
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
                    <span className={`risk-pill ${trade.riskStatus?.kind ?? "none"}`} title={trade.riskStatus?.message ?? undefined}>
                      {riskSignalKind(trade) === "stopLoss" ? <ShieldAlert size={13} /> : null}
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
                      {isAwaitingApproval(trade) ? (
                        <button
                          className="icon-button approve"
                          type="button"
                          title={`Approve ${riskSignalKind(trade) === "target" ? "Target" : "SL"} exit`}
                          onClick={() => onApprove(trade)}
                          disabled={busy}
                        >
                          <ShieldCheck size={15} />
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              );
            })}
            {closedTrades.length ? <ClosedSubsectionRow colSpan={columnCount} count={closedTrades.length} /> : null}
            {closedTrades.map((trade) => (
              <ClosedOptionRow key={trade.id} trade={trade} showRemainingProfit={showRemainingProfit} />
            ))}
            {!totalRows ? (
              <tr>
                <td colSpan={columnCount}>{loading ? "Loading" : "No option positions"}</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ClosedSubsectionRow({ colSpan, count }: { colSpan: number; count: number }) {
  return (
    <tr className="subsection-row">
      <td colSpan={colSpan}>Closed Trades <span>{count}</span></td>
    </tr>
  );
}

function ClosedOptionRow({ trade, showRemainingProfit }: { trade: LiveTrade; showRemainingProfit: boolean }) {
  return (
    <tr className="closed-row">
      <td>
        <strong>{tradeLabel(trade)}</strong>
        <span className="subtext">{trade.expiry || "-"} · {trade.productType || "-"}</span>
      </td>
      <td><Badge tone={trade.side === "BUY" ? "buy" : "sell"}>{trade.side}</Badge></td>
      <td>{trade.closedQty ?? trade.absQty}</td>
      <td>{money(trade.entryAvgPrice ?? trade.avgPrice)}</td>
      <td>{money(trade.exitAvgPrice ?? trade.ltp)}</td>
      <td className={tone(trade.dayPnl)}>{money(trade.dayPnl)}</td>
      <td className={tone(trade.estimatedNetPnl)}>{money(trade.estimatedNetPnl)}</td>
      <td>{money(trade.estimatedCharges)}</td>
      <td className={tone(trade.percentChange)}>{percent(trade.percentChange)}</td>
      {showRemainingProfit ? <td>-</td> : null}
      {showRemainingProfit ? <td>-</td> : null}
      <td>-</td>
      <td>-</td>
      <td>-</td>
      <td><span className="risk-pill closed">Closed</span></td>
      <td>-</td>
    </tr>
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
      {!trade.ltpStale && trade.ltpDerived ? <span className="subtext">derived</span> : null}
    </>
  );
}

function draftsFromSnapshot(snapshot: LiveTradeSnapshot): Record<string, DraftLevels> {
  const rows = [...snapshot.groups.optionsBuy, ...snapshot.groups.optionsSell];
  return Object.fromEntries(rows.map((trade) => [trade.id, {
    stopLoss: stopLossLevelText(trade),
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

function stopLossDraftNumber(trade: LiveTrade, value: string): number | null {
  const percentValue = stopLossPercentValue(value);
  return percentValue === null ? null : stopLossFromPercent(trade, percentValue);
}

function stopLossPreview(trade: LiveTrade, value: string): string {
  const percentValue = stopLossPercentValue(value);
  if (percentValue === null) return "";
  const stopLoss = stopLossFromPercent(trade, percentValue);
  return stopLoss === null ? "" : `SL ${money(stopLoss)}`;
}

function stopLossPercentValue(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed.replace("%", "").replace(",", "").trim());
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function stopLossFromPercent(trade: LiveTrade, percentValue: number): number | null {
  const avgPrice = trade.avgPrice;
  if (avgPrice === null || avgPrice === undefined || Number.isNaN(avgPrice) || avgPrice < 0) return null;
  const multiplier = trade.qty < 0 ? 1 + (percentValue / 100) : 1 - (percentValue / 100);
  return roundLevel(Math.max(avgPrice * multiplier, 0));
}

function stopLossLevelText(trade: LiveTrade): string {
  const stopLoss = trade.levels?.stopLoss;
  const avgPrice = trade.avgPrice;
  if (stopLoss === null || stopLoss === undefined || avgPrice === null || avgPrice === undefined || avgPrice <= 0) {
    return valueText(stopLoss);
  }
  const percentValue = trade.qty < 0 ? ((stopLoss / avgPrice) - 1) * 100 : (1 - (stopLoss / avgPrice)) * 100;
  return percentValue >= 0 ? trimNumber(roundLevel(percentValue)) : valueText(stopLoss);
}

function roundLevel(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function trimNumber(value: number): string {
  return String(value).replace(/\.?0+$/, "");
}

function tradeLabel(trade: LiveTrade): string {
  const strike = trade.strikePrice ? String(trade.strikePrice).replace(/\.0$/, "") : trade.tradingSymbol;
  return `${trade.symbol} ${strike} ${trade.optionSide ?? ""}`.trim();
}

function riskOrdersArmed(session: DhanSession | null): boolean {
  return Boolean(session?.riskOrderMonitorEnabled && session?.riskOrderExecutionEnabled && session?.liveOrderEnabled);
}

function riskOrderLabel(session: DhanSession | null): string {
  if (!session?.riskOrderMonitorEnabled) return "off";
  if (riskOrdersArmed(session)) return "armed";
  return "dry-run";
}

function riskSignalKind(trade: LiveTrade): string | null {
  return trade.riskStatus?.signalKind ?? trade.riskStatus?.kind ?? null;
}

function isAwaitingApproval(trade: LiveTrade): boolean {
  return AWAITING_APPROVAL_KINDS.has(trade.riskStatus?.kind ?? "");
}

function notifyRiskSignal(trade: LiveTrade): void {
  if (typeof window === "undefined" || !("Notification" in window) || Notification.permission !== "granted") return;
  const kindLabel = riskSignalKind(trade) === "target" ? "Target" : "Stop Loss";
  try {
    new Notification(`${kindLabel} reached — approval needed`, {
      body: `${tradeLabel(trade)} · LTP ${money(trade.ltp)} · Level ${money(trade.riskStatus?.level)}`,
      tag: trade.id,
    });
  } catch {
    // Notification constructor can throw in unsupported contexts; ignore.
  }
}

function money(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return moneyFormat.format(value);
}

function secondsToMs(value: string | undefined, fallbackSeconds: number): number {
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : fallbackSeconds * 1000;
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
