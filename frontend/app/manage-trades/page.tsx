"use client";

import { CandlestickSeries, ColorType, createChart, IChartApi, ISeriesApi, LineSeries, Time, UTCTimestamp } from "lightweight-charts";
import {
  CandlestickChart,
  ChevronDown,
  ChevronRight,
  LogIn,
  RefreshCcw,
  Save,
  ShieldAlert,
  ShieldCheck,
  SquareArrowOutUpRight,
} from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";

import {
  approveRiskExit,
  closeTrade,
  exitTag,
  updateSuggestConfig,
  getDhanSession,
  getLiveTrades,
  getTradeCandles,
  loginDhan,
  saveTagLevels,
  saveTradeLevels,
} from "@/lib/api";
import { isMarketHoursNow } from "@/lib/marketHours";
import type { DhanSession, LiveTrade, LiveTradeSnapshot, MarketCandle, SuggestConfig, TagSummary } from "@/types/live";
import VarahaPayoffChart from "@/components/VarahaPayoffChart";
import PcrOiPanel from "@/components/PcrOiPanel";

type DraftLevels = {
  stopLoss: string;
  target: string;
  notes: string;
  tag: string;
};

type TagGroup = {
  tag: string;
  openTrades: LiveTrade[];
  closedTrades: LiveTrade[];
  summary?: TagSummary;
};

const moneyFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const TRADE_REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_TRADES_REFRESH_SECONDS, 3);
const SESSION_REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_SESSION_REFRESH_SECONDS, 120);
const RISK_ALERT_REPEAT_MS = 15_000;
const AWAITING_APPROVAL_KINDS = new Set(["stopLossSignal", "targetSignal", "orderFailed"]);
const TRADE_CHART_REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_TRADE_CHART_REFRESH_SECONDS, 20);
const STRATEGY_PRICE_COLOR = "#2368b6";
const STRATEGY_VWAP_COLOR = "#a56513";
type StrategyInterval = "1" | "3" | "5";
const STRATEGY_INTERVAL_OPTIONS: { value: StrategyInterval; label: string }[] = [
  { value: "1", label: "1m" },
  { value: "3", label: "3m" },
  { value: "5", label: "5m" },
];

export default function ManageTradesPage() {
  const [session, setSession] = useState<DhanSession | null>(null);
  const [snapshot, setSnapshot] = useState<LiveTradeSnapshot | null>(null);
  const [drafts, setDrafts] = useState<Record<string, DraftLevels>>({});
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const notifiedAtRef = useRef<Record<string, number>>({});

  function toggleExpand(tradeId: string) {
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(tradeId)) next.delete(tradeId);
      else next.add(tradeId);
      return next;
    });
  }

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
    for (const group of payload.tagGroups ?? []) {
      if (group.suggestion && !isSnoozed(group.tag)) notifySuggestion(group);
    }
    const trades = payload.groups.options;
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
    const tradeTimer = window.setInterval(() => {
      if (isMarketHoursNow()) loadTrades();
    }, TRADE_REFRESH_MS);
    const sessionTimer = window.setInterval(() => {
      if (isMarketHoursNow()) loadSession();
    }, SESSION_REFRESH_MS);
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
        tag: draft.tag.trim() || null,
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

  async function handleSaveTagLevels(tag: string, target: number | null, stopLoss: number | null) {
    setMessage(null);
    setError(null);
    try {
      await saveTagLevels(tag, { target, stopLoss });
      setMessage(
        target === null && stopLoss === null
          ? `${tag}: tag levels cleared.`
          : `${tag}: armed -- all open legs close automatically when Net P&L reaches the level.`,
      );
      await loadTrades();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to save tag levels.");
    }
  }

  async function handleExitTag(group: TagGroup, viaSuggestion = false) {
    const legs = group.openTrades.map(tradeLabel).join(", ");
    const hint = group.summary?.suggestion;
    const intro = viaSuggestion && hint
      ? `Book profit on "${group.tag}"?\n\nToday's P&L ${money(hint.currentPnl)} is ${hint.capturePercent.toFixed(0)}% of the most it can make today (${money(hint.maxDayProfit)}).\n\nThis closes ALL open legs with market orders:`
      : `Close ALL open legs in "${group.tag}" with market orders?`;
    if (!window.confirm(`${intro}\n\n${legs}\n\nShorts are bought back first, then longs are sold.`)) return;
    setMessage(null);
    setError(null);
    try {
      const result = await exitTag(group.tag, viaSuggestion ? "suggestion" : "manual");
      setMessage(`${group.tag}: close all ${String(result.status ?? "submitted")}${result.message ? ` -- ${result.message}` : ""}.`);
      await loadTrades();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to close tag.");
    }
  }

  function updateDraft(tradeId: string, key: keyof DraftLevels, value: string) {
    setDrafts((current) => ({ ...current, [tradeId]: { ...(current[tradeId] ?? emptyDraft()), [key]: value } }));
  }

  const summary = snapshot?.summary;
  const optionTrades = snapshot?.groups.options ?? [];
  const awaitingApproval = useMemo(() => optionTrades.filter(isAwaitingApproval), [optionTrades]);
  const closedTrades = snapshot?.groups.closed ?? [];
  const closedEquity = closedTrades.filter((trade) => trade.assetClass === "EQUITY");
  const closedOptions = closedTrades.filter((trade) => trade.assetClass === "OPTION");
  const groupsByTag = useMemo(
    () => groupOptionsByTag(optionTrades, closedOptions, snapshot?.tagGroups ?? []),
    [optionTrades, closedOptions, snapshot?.tagGroups],
  );

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

      <PcrOiPanel />

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

      {snapshot?.suggestConfig ? <SuggestSettings config={snapshot.suggestConfig} onSaved={loadTrades} /> : null}

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

      {groupsByTag.map((group) => (
        <TagGroupTable
          key={group.tag}
          group={group}
          drafts={drafts}
          savingId={savingId}
          onDraft={updateDraft}
          onSave={handleSave}
          onClose={handleClose}
          onApprove={handleApprove}
          onSaveTagLevels={handleSaveTagLevels}
          onExitTag={handleExitTag}
          expandedIds={expandedIds}
          onToggleExpand={toggleExpand}
          suggestThreshold={snapshot?.suggestConfig?.enabled ? snapshot.suggestConfig.thresholdPercent : null}
        />
      ))}

      {groupsByTag.some((group) => group.openTrades.length > 0 && isStrangleTag(group.tag)) ? (
        <div className="pcr-oi-section">
          <h3>Strategy Charts</h3>
          <p className="pcr-oi-caption" style={{ margin: 0 }}>
            Short strangles only (tags ending in _ss) -- Strategy Price is the sum of each open leg's LTP, Strategy VWAP is
            the same series volume-weighted (each leg's own traded volume, combined) since session start.
          </p>
          {groupsByTag
            .filter((group) => group.openTrades.length > 0 && isStrangleTag(group.tag))
            .map((group) => (
              <StrategyChartCard key={group.tag} group={group} />
            ))}
        </div>
      ) : null}

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
  const totalQty = trades.reduce((sum, trade) => sum + trade.qty, 0);
  const totalPnl = sumField([...trades, ...closedTrades], "dayPnl");
  const totalInvested =
    trades.reduce((sum, trade) => sum + (trade.avgPrice ?? 0) * trade.qty, 0) +
    closedTrades.reduce(
      (sum, trade) => sum + (trade.entryAvgPrice ?? trade.avgPrice ?? 0) * (trade.closedQty ?? trade.absQty ?? 0),
      0,
    );
  const totalPercent = totalInvested ? (totalPnl / totalInvested) * 100 : null;
  const [expanded, toggleExpanded] = useSectionExpanded(`equity:${title}`);
  return (
    <section className="table-section">
      <SectionToggleTitle title={title} count={totalRows} expanded={expanded} onToggle={toggleExpanded}>
        {!expanded ? (
          <div style={{ fontSize: 13, color: "var(--muted)", whiteSpace: "nowrap", marginLeft: 6 }}>
            P&amp;L <strong className={tone(totalPnl)}>{money(totalPnl)}</strong>
            {totalPercent !== null ? ` (${percent(totalPercent)})` : ""}
          </div>
        ) : null}
      </SectionToggleTitle>
      {expanded ? (
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Side</th>
              <th>Qty</th>
              <th>Avg</th>
              <th>Invested</th>
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
                <td>{money((trade.avgPrice ?? 0) * trade.qty)}</td>
                <td><PriceCell trade={trade} /></td>
                <td className={tone(trade.dayPnl)}>{money(trade.dayPnl)}</td>
                <td className={tone(trade.percentChange)}>{percent(trade.percentChange)}</td>
                <td>{trade.productType || "-"}</td>
              </tr>
            ))}
            {closedTrades.length ? <ClosedSubsectionRow colSpan={9} count={closedTrades.length} /> : null}
            {closedTrades.map((trade) => {
              const closedQty = trade.closedQty ?? trade.absQty ?? 0;
              const entryPrice = trade.entryAvgPrice ?? trade.avgPrice ?? 0;
              return (
                <tr className="closed-row" key={trade.id}>
                  <td>
                    <strong>{trade.tradingSymbol}</strong>
                    <span className="subtext">{trade.exchangeSegment || "-"}</span>
                  </td>
                  <td><Badge tone={trade.side === "BUY" ? "buy" : "sell"}>{trade.side}</Badge></td>
                  <td>{closedQty}</td>
                  <td>{money(entryPrice)}</td>
                  <td>{money(entryPrice * closedQty)}</td>
                  <td>{money(trade.exitAvgPrice ?? trade.ltp)}</td>
                  <td className={tone(trade.dayPnl)}>{money(trade.dayPnl)}</td>
                  <td className={tone(trade.percentChange)}>{percent(trade.percentChange)}</td>
                  <td>{trade.productType || "-"}</td>
                </tr>
              );
            })}
            {!totalRows ? (
              <tr>
                <td colSpan={9}>{loading ? "Loading" : "No equity positions"}</td>
              </tr>
            ) : null}
            {totalRows ? (
              <tr className="totals-row">
                <td>Total</td>
                <td />
                <td>{totalQty}</td>
                <td />
                <td>{money(totalInvested)}</td>
                <td />
                <td className={tone(totalPnl)}>{money(totalPnl)}</td>
                <td className={tone(totalPercent)}>{percent(totalPercent)}</td>
                <td />
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      ) : null}
    </section>
  );
}

function TagGroupTable({
  group,
  drafts,
  savingId,
  onDraft,
  onSave,
  onClose,
  onApprove,
  onSaveTagLevels,
  onExitTag,
  expandedIds,
  onToggleExpand,
  suggestThreshold,
}: {
  suggestThreshold: number | null;
  group: TagGroup;
  drafts: Record<string, DraftLevels>;
  savingId: string | null;
  onDraft: (tradeId: string, key: keyof DraftLevels, value: string) => void;
  onSave: (trade: LiveTrade) => void;
  onClose: (trade: LiveTrade) => void;
  onApprove: (trade: LiveTrade) => void;
  onSaveTagLevels: (tag: string, target: number | null, stopLoss: number | null) => Promise<void>;
  onExitTag: (group: TagGroup, viaSuggestion?: boolean) => Promise<void>;
  expandedIds: Set<string>;
  onToggleExpand: (tradeId: string) => void;
}) {
  const columnCount = 17;
  const allRows = [...group.openTrades, ...group.closedTrades];
  const totalRows = allRows.length;
  const groupDayPnl = group.summary?.dayPnl ?? sumField(allRows, "dayPnl");
  const groupCharges = group.summary?.charges ?? sumField(allRows, "estimatedCharges");
  const groupNetPnl = group.summary?.netPnl ?? sumField(allRows, "estimatedNetPnl");
  const groupRemaining = group.summary?.remainingPremium ?? sumField(allRows, "profitRemaining");

  const [expanded, toggleExpanded] = useSectionExpanded(`tag:${group.tag}`);
  return (
    <section className="table-section">
      <SectionToggleTitle title={group.tag} count={totalRows} expanded={expanded} onToggle={toggleExpanded} />
      <div className="gb-status-row">
        <span>
          Day P&amp;L: <strong className={tone(groupDayPnl)}>{money(groupDayPnl)}</strong>
        </span>
        <span>Charges: {money(groupCharges)}</span>
        <span>
          Net: <strong className={tone(groupNetPnl)}>{money(groupNetPnl)}</strong>
        </span>
        <span>Remaining Premium: {money(groupRemaining)}</span>
      </div>
      {group.summary?.suggestion && group.openTrades.length ? (
        <SuggestionBanner group={group} onAccept={() => onExitTag(group, true)} />
      ) : null}
      {group.summary ? (
        <TagLevelsBar group={group} summary={group.summary} onSave={onSaveTagLevels} onExit={onExitTag} />
      ) : null}
      {group.summary?.payoff && group.openTrades.length ? <TagPayoffPanel group={group} threshold={suggestThreshold} /> : null}
      {expanded ? (
      <div className="table-wrap">
        <table className="wide-table">
          <thead>
            <tr>
              <th>Tag</th>
              <th>Strike</th>
              <th>Side</th>
              <th>Qty</th>
              <th>Avg</th>
              <th>LTP</th>
              <th>P&L</th>
              <th>Net</th>
              <th>Charges</th>
              <th>%</th>
              <th>Remaining</th>
              <th>Remain %</th>
              <th>Spot Dist</th>
              <th>SL %</th>
              <th>Target</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {group.openTrades.map((trade) => {
              const draft = drafts[trade.id] ?? emptyDraft();
              const busy = savingId === trade.id;
              const expanded = expandedIds.has(trade.id);
              return (
                <Fragment key={trade.id}>
                <tr>
                  <td>
                    <input
                      className="level-input"
                      inputMode="text"
                      placeholder={trade.defaultTag ?? "tag"}
                      value={draft.tag}
                      onChange={(event) => onDraft(trade.id, "tag", event.target.value)}
                    />
                  </td>
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
                  <td>{money(trade.profitRemaining)}</td>
                  <td>{plainPercent(trade.profitRemainingPercent)}</td>
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
                      <button
                        className={`icon-button ${expanded ? "approve" : ""}`}
                        type="button"
                        title="Show 5m chart"
                        onClick={() => onToggleExpand(trade.id)}
                      >
                        <CandlestickChart size={15} />
                      </button>
                    </div>
                  </td>
                </tr>
                {expanded ? (
                  <tr className="chart-row">
                    <td colSpan={columnCount}>
                      <TradeChart trade={trade} />
                    </td>
                  </tr>
                ) : null}
                </Fragment>
              );
            })}
            {group.closedTrades.length ? <ClosedSubsectionRow colSpan={columnCount} count={group.closedTrades.length} /> : null}
            {group.closedTrades.map((trade) => (
              <ClosedOptionRow
                key={trade.id}
                trade={trade}
                draft={drafts[trade.id] ?? emptyDraft()}
                busy={savingId === trade.id}
                columnCount={columnCount}
                onDraft={onDraft}
                onSave={onSave}
                expanded={expandedIds.has(trade.id)}
                onToggleExpand={onToggleExpand}
              />
            ))}
          </tbody>
        </table>
      </div>
      ) : null}
    </section>
  );
}

const SNOOZE_MS = 30 * 60 * 1000;
const notifiedSuggestions = new Set<string>();

function snoozeKey(tag: string): string {
  return `manage-trades:suggest-snooze:${tag}`;
}

function isSnoozed(tag: string): boolean {
  try {
    return Number(window.localStorage.getItem(snoozeKey(tag)) || 0) > Date.now();
  } catch {
    return false;
  }
}

function notifySuggestion(group: TagSummary): void {
  const key = `${new Date().toDateString()}:${group.tag}`;
  if (notifiedSuggestions.has(key)) return;
  notifiedSuggestions.add(key);
  if (typeof window === "undefined" || !("Notification" in window) || Notification.permission !== "granted") return;
  try {
    new Notification(`Book profit on ${group.tag}?`, { body: group.suggestion?.text ?? "", tag: `suggest-${group.tag}` });
  } catch {
    // ignore
  }
}

function SuggestionBanner({ group, onAccept }: { group: TagGroup; onAccept: () => Promise<void> }) {
  const hint = group.summary?.suggestion;
  const [snoozed, setSnoozed] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setSnoozed(isSnoozed(group.tag));
    const timer = window.setInterval(() => setSnoozed(isSnoozed(group.tag)), 30_000);
    return () => window.clearInterval(timer);
  }, [group.tag]);
  if (!hint || snoozed) return null;
  function snooze() {
    try {
      window.localStorage.setItem(snoozeKey(group.tag), String(Date.now() + SNOOZE_MS));
    } catch {
      // ignore
    }
    setSnoozed(true);
  }
  async function accept() {
    setBusy(true);
    try {
      await onAccept();
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="alert warning" style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", margin: "6px 0" }}>
      <div style={{ flex: 1, minWidth: 260 }}>
        <strong>💡 Profit-booking suggestion ({hint.capturePercent.toFixed(0)}% of today&apos;s max)</strong>
        <div style={{ fontSize: 13 }}>{hint.text}</div>
      </div>
      <button type="button" className="button" onClick={accept} disabled={busy}>
        {busy ? "Booking…" : "Book profit (close all legs)"}
      </button>
      <button type="button" className="button secondary" onClick={snooze} disabled={busy}>
        Not now (30 min)
      </button>
    </div>
  );
}

function TagPayoffPanel({ group, threshold }: { group: TagGroup; threshold: number | null }) {
  const payoff = group.summary?.payoff;
  const [expanded, toggle] = useSectionExpanded(`payoff:${group.tag}`);
  if (!payoff) return null;
  if (payoff.error) {
    return <p className="pcr-oi-caption" style={{ margin: "4px 0" }}>Payoff: {payoff.error}</p>;
  }
  const capture = payoff.capturePercent;
  return (
    <div style={{ margin: "6px 0" }}>
      <div className="gb-status-row" style={{ alignItems: "center" }}>
        <button type="button" className="button secondary" onClick={toggle} style={{ padding: "2px 10px" }}>
          {expanded ? "Hide payoff" : "Show payoff"}
        </button>
        <span>
          Today&apos;s P&amp;L: <strong className={tone(payoff.currentPnl)}>{money(payoff.currentPnl)}</strong>
        </span>
        <span>
          Max day profit: <strong>{money(payoff.maxDayProfit)}</strong> (index ≈ {Math.round(payoff.maxDayProfitAt ?? 0).toLocaleString("en-IN")})
        </span>
        <span>
          Captured: <strong>{capture !== null && capture !== undefined ? `${capture.toFixed(0)}%` : "—"}</strong>
        </span>
        {threshold && payoff.maxDayProfit && payoff.maxDayProfit > 0 ? (() => {
          const target = (payoff.maxDayProfit * threshold) / 100;
          const toGo = target - (payoff.currentPnl ?? 0);
          const progress = Math.max(0, Math.min(1, (payoff.currentPnl ?? 0) / target));
          return (
            <span title={`The profit-booking suggestion appears when today's P&L reaches ${threshold}% of the max day profit.`}>
              Suggestion at <strong>{money(target)}</strong> ({threshold}% of {money(payoff.maxDayProfit)}) ·{" "}
              {toGo > 0 ? <>{money(toGo)} to go</> : <strong style={{ color: "var(--green)" }}>reached</strong>}
              <span
                style={{ display: "inline-block", width: 90, height: 6, marginLeft: 8, verticalAlign: "middle", background: "var(--line)", borderRadius: 3, overflow: "hidden" }}
              >
                <span style={{ display: "block", width: `${progress * 100}%`, height: "100%", background: progress >= 1 ? "var(--green)" : "var(--blue)" }} />
              </span>
            </span>
          );
        })() : null}
        <span className="pcr-oi-caption">counted {payoff.basis}; before charges</span>
      </div>
      {expanded && payoff.points?.length ? (
        <VarahaPayoffChart
          chartId={`tag-payoff-${group.tag}`}
          label={`${group.tag} payoff`}
          points={payoff.points}
          breakevens={payoff.breakevens ?? []}
          spot={payoff.spot ?? 0}
          expectedMove={null}
          todayLabel="Today at 15:30 close (max day profit = its peak)"
        />
      ) : null}
    </div>
  );
}

function SuggestSettings({ config, onSaved }: { config: SuggestConfig; onSaved: () => Promise<void> }) {
  const [threshold, setThreshold] = useState(String(config.thresholdPercent));
  const [busy, setBusy] = useState(false);
  useEffect(() => setThreshold(String(config.thresholdPercent)), [config.thresholdPercent]);
  async function save(updates: Partial<SuggestConfig>) {
    setBusy(true);
    try {
      await updateSuggestConfig(updates);
      await onSaved();
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="status-row" style={{ flexWrap: "wrap", gap: 10 }}>
      <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <input type="checkbox" checked={config.enabled} disabled={busy} onChange={(e) => save({ enabled: e.target.checked })} />
        Profit-booking suggestions
      </label>
      <span>when today&apos;s P&amp;L reaches</span>
      <input
        type="number"
        min={10}
        max={100}
        step={1}
        value={threshold}
        onChange={(e) => setThreshold(e.target.value)}
        style={{ width: 64 }}
        disabled={busy}
      />
      <span>% of the max day profit</span>
      <button
        type="button"
        className="button secondary"
        disabled={busy || Number(threshold) === config.thresholdPercent || !(Number(threshold) >= 10 && Number(threshold) <= 100)}
        onClick={() => save({ thresholdPercent: Number(threshold) })}
      >
        Save
      </button>
    </div>
  );
}

function TagLevelsBar({
  group,
  summary,
  onSave,
  onExit,
}: {
  group: TagGroup;
  summary: TagSummary;
  onSave: (tag: string, target: number | null, stopLoss: number | null) => Promise<void>;
  onExit: (group: TagGroup) => Promise<void>;
}) {
  const levels = summary.levels;
  const [target, setTarget] = useState(valueText(levels.target));
  const [stopLoss, setStopLoss] = useState(valueText(levels.stopLoss));
  const [busy, setBusy] = useState(false);

  // Re-seed the inputs only when the saved levels change, not on every 3s
  // refresh, so typing isn't overwritten.
  useEffect(() => {
    setTarget(valueText(levels.target));
    setStopLoss(valueText(levels.stopLoss));
  }, [levels.updatedAt, levels.target, levels.stopLoss]);

  async function save(clear = false) {
    const targetValue = clear ? null : draftNumber(target);
    const stopValue = clear ? null : draftNumber(stopLoss);
    if (!clear && targetValue === null && stopValue === null) return;
    if (
      !clear &&
      !window.confirm(
        `Arm "${summary.tag}"?\n\nWhen its Net P&L reaches ${targetValue !== null ? `+${money(targetValue)}` : "-"} (target)` +
          ` or ${stopValue !== null ? `-${money(Math.abs(stopValue))}` : "-"} (stop loss), ALL open legs in this tag are closed` +
          " automatically with market orders -- no approval step.",
      )
    )
      return;
    setBusy(true);
    try {
      await onSave(summary.tag, targetValue, stopValue);
    } finally {
      setBusy(false);
    }
  }

  async function closeAll() {
    setBusy(true);
    try {
      await onExit(group);
    } finally {
      setBusy(false);
    }
  }

  const status = levels.status;
  const statusText =
    status === "ARMED"
      ? `Armed · auto exit${summary.toTarget !== null ? ` · ${money(summary.toTarget)} to target` : ""}${summary.toStopLoss !== null ? ` · ${money(summary.toStopLoss)} above stop` : ""}`
      : status === "TRIGGERING"
        ? "Exiting…"
        : status === "DONE"
          ? `${levels.triggerKind === "stopLoss" ? "Stop loss" : levels.triggerKind === "manual" ? "Closed manually" : "Target"} hit · all legs closed${levels.triggeredAt ? ` at ${levels.triggeredAt.slice(11, 16)}` : ""} (net ${money(levels.triggerNet)})`
          : status === "PARTIAL" || status === "FAILED"
            ? `Exit ${status.toLowerCase()} -- ${(levels.result?.legs ?? []).filter((leg) => !leg.ok).map((leg) => `${leg.label}: ${leg.message ?? leg.status}`).join("; ")}`
            : "No tag target / stop loss";
  const statusTone = status === "ARMED" ? "on" : status === "PARTIAL" || status === "FAILED" ? "warn" : "";

  return (
    <div className="gb-status-row" style={{ flexWrap: "wrap", alignItems: "center", gap: 10 }}>
      <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
        Tag target (Net) ₹
        <input
          className="level-input"
          inputMode="decimal"
          placeholder="e.g. 5000"
          value={target}
          onChange={(event) => setTarget(event.target.value)}
          style={{ width: 90 }}
        />
      </span>
      <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
        Stop loss (Net) −₹
        <input
          className="level-input"
          inputMode="decimal"
          placeholder="e.g. 3000"
          value={stopLoss}
          onChange={(event) => setStopLoss(event.target.value)}
          style={{ width: 90 }}
        />
      </span>
      <button className="icon-button" type="button" title="Save & arm tag levels" onClick={() => save(false)} disabled={busy}>
        <Save size={15} />
      </button>
      {levels.target !== null || levels.stopLoss !== null ? (
        <button className="button secondary" type="button" onClick={() => save(true)} disabled={busy}>
          Clear
        </button>
      ) : null}
      {group.openTrades.length ? (
        <button className="button secondary" type="button" onClick={closeAll} disabled={busy} title="Close every open leg in this tag now">
          <SquareArrowOutUpRight size={14} /> Close all
        </button>
      ) : null}
      <span className={`status-live ${statusTone}`} title={levels.result ? JSON.stringify(levels.result.legs) : undefined}>
        {statusText}
      </span>
    </div>
  );
}

// Sections start collapsed; the choice is remembered per section in this
// browser (localStorage can throw in private windows -- then it just
// isn't remembered).
function useSectionExpanded(key: string): [boolean, () => void] {
  const storageKey = `manage-trades:expanded:${key}`;
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    try {
      setExpanded(window.localStorage.getItem(storageKey) === "1");
    } catch {
      // ignore
    }
  }, [storageKey]);
  function toggle() {
    setExpanded((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(storageKey, next ? "1" : "0");
      } catch {
        // ignore
      }
      return next;
    });
  }
  return [expanded, toggle];
}

function SectionToggleTitle({
  title,
  count,
  expanded,
  onToggle,
  children,
}: {
  title: string;
  count: number;
  expanded: boolean;
  onToggle: () => void;
  children?: React.ReactNode;
}) {
  return (
    <div className="section-title" style={{ cursor: "pointer" }} onClick={onToggle}>
      <button className="icon-button" type="button" title={expanded ? "Collapse" : "Expand"} aria-expanded={expanded}>
        {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
      </button>
      <h2>{title}</h2>
      <span>{count}</span>
      {children}
    </div>
  );
}

function ClosedSubsectionRow({ colSpan, count }: { colSpan: number; count: number }) {
  return (
    <tr className="subsection-row">
      <td colSpan={colSpan}>Closed Trades <span>{count}</span></td>
    </tr>
  );
}

function ClosedOptionRow({
  trade,
  draft,
  busy,
  columnCount,
  onDraft,
  onSave,
  expanded,
  onToggleExpand,
}: {
  trade: LiveTrade;
  draft: DraftLevels;
  busy: boolean;
  columnCount: number;
  onDraft: (tradeId: string, key: keyof DraftLevels, value: string) => void;
  onSave: (trade: LiveTrade) => void;
  expanded: boolean;
  onToggleExpand: (tradeId: string) => void;
}) {
  return (
    <Fragment>
    <tr className="closed-row">
      <td>
        <div className="row-actions">
          <input
            className="level-input"
            inputMode="text"
            placeholder={trade.defaultTag ?? "tag"}
            value={draft.tag}
            onChange={(event) => onDraft(trade.id, "tag", event.target.value)}
          />
          <button className="icon-button" type="button" title="Save tag" onClick={() => onSave(trade)} disabled={busy}>
            <Save size={13} />
          </button>
        </div>
      </td>
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
      <td>-</td>
      <td>-</td>
      <td>-</td>
      <td>-</td>
      <td>-</td>
      <td><span className="risk-pill closed">Closed</span></td>
      <td>
        <button
          className={`icon-button ${expanded ? "approve" : ""}`}
          type="button"
          title="Show 5m chart"
          onClick={() => onToggleExpand(trade.id)}
        >
          <CandlestickChart size={15} />
        </button>
      </td>
    </tr>
    {expanded ? (
      <tr className="chart-row">
        <td colSpan={columnCount}>
          <TradeChart trade={trade} />
        </td>
      </tr>
    ) : null}
    </Fragment>
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

function TradeChart({ trade }: { trade: LiveTrade }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const [candles, setCandles] = useState<MarketCandle[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!trade.securityId || !trade.exchangeSegment) {
      setError("Missing security id / exchange segment for this position.");
      return;
    }
    let cancelled = false;
    async function load() {
      try {
        const payload = await getTradeCandles({
          securityId: trade.securityId as string,
          exchangeSegment: trade.exchangeSegment as string,
          instrument: trade.instrument || "OPTIDX",
          interval: "5",
        });
        if (cancelled) return;
        setCandles(payload.candles);
        setError(null);
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : "Failed to load candles.");
      }
    }
    load();
    const timer = window.setInterval(() => {
      if (isMarketHoursNow()) load();
    }, TRADE_CHART_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [trade.securityId, trade.exchangeSegment, trade.instrument]);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: containerRef.current.clientWidth,
      height: 260,
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time: Time) => formatIstTime(time),
      },
      localization: { timeFormatter: (time: Time) => formatIstTime(time) },
    });
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#168448",
      downColor: "#c93535",
      borderVisible: false,
      wickUpColor: "#168448",
      wickDownColor: "#c93535",
    });
    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;

    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!candleSeriesRef.current) return;
    candleSeriesRef.current.setData(
      candles.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })),
    );
  }, [candles]);

  useEffect(() => {
    const series = candleSeriesRef.current;
    if (!series) return;
    series.priceLines().forEach((line) => series.removePriceLine(line));
    const entryPrice = trade.entryAvgPrice ?? trade.avgPrice;
    if (entryPrice !== null && entryPrice !== undefined) {
      series.createPriceLine({ price: entryPrice, color: "#6f7785", title: "Entry" });
    }
    if (trade.status === "CLOSED" && trade.exitAvgPrice !== null && trade.exitAvgPrice !== undefined) {
      series.createPriceLine({ price: trade.exitAvgPrice, color: "#2368b6", title: "Exit" });
    }
    if (trade.levels?.stopLoss !== null && trade.levels?.stopLoss !== undefined) {
      series.createPriceLine({ price: trade.levels.stopLoss, color: "#c93535", title: "SL" });
    }
    if (trade.levels?.target !== null && trade.levels?.target !== undefined) {
      series.createPriceLine({ price: trade.levels.target, color: "#168448", title: "Target" });
    }
  }, [trade.entryAvgPrice, trade.avgPrice, trade.exitAvgPrice, trade.status, trade.levels?.stopLoss, trade.levels?.target]);

  return (
    <div>
      <div className="subtext">5m candles — {tradeLabel(trade)}</div>
      {error ? <div className="alert error">{error}</div> : null}
      <div ref={containerRef} style={{ width: "100%" }} />
    </div>
  );
}

type StrategyPoint = { time: number; price: number; volume: number };

/** Sums each leg's close (Strategy Price) and volume at matching 1-minute
 * timestamps. Only keeps timestamps where every leg reported a candle --
 * a partial sum from a mid-session gap in just one leg would silently
 * understate the combined price rather than reflect a real reading.
 */
function combineLegCandles(legCandleArrays: MarketCandle[][]): StrategyPoint[] {
  const byTime = new Map<number, { price: number; volume: number; legCount: number }>();
  for (const candles of legCandleArrays) {
    for (const candle of candles) {
      const existing = byTime.get(candle.time) ?? { price: 0, volume: 0, legCount: 0 };
      existing.price += candle.close;
      existing.volume += candle.volume ?? 0;
      existing.legCount += 1;
      byTime.set(candle.time, existing);
    }
  }
  return Array.from(byTime.entries())
    .filter(([, v]) => v.legCount === legCandleArrays.length)
    .map(([time, v]) => ({ time, price: v.price, volume: v.volume }))
    .sort((a, b) => a.time - b.time);
}

function resampleStrategyPoints(points: StrategyPoint[], groupSize: number): StrategyPoint[] {
  if (groupSize <= 1) return points;
  const out: StrategyPoint[] = [];
  for (let i = 0; i < points.length; i += groupSize) {
    const group = points.slice(i, i + groupSize);
    if (!group.length) continue;
    out.push({
      time: group[0].time,
      price: group[group.length - 1].price,
      volume: group.reduce((sum, p) => sum + p.volume, 0),
    });
  }
  return out;
}

function withStrategyVwap(points: StrategyPoint[]): { time: number; price: number; vwap: number }[] {
  let cumPriceVolume = 0;
  let cumVolume = 0;
  return points.map((p) => {
    cumPriceVolume += p.price * p.volume;
    cumVolume += p.volume;
    return { time: p.time, price: p.price, vwap: cumVolume > 0 ? cumPriceVolume / cumVolume : p.price };
  });
}

function StrategyChartCard({ group }: { group: TagGroup }) {
  const [expanded, setExpanded] = useState(false);
  const [chartInterval, setChartInterval] = useState<StrategyInterval>("5");
  const [series, setSeries] = useState<{ time: number; price: number; vwap: number }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  const legs = useMemo(
    () => group.openTrades.filter((trade) => trade.securityId && trade.exchangeSegment),
    [group.openTrades],
  );
  const legsKey = legs.map((trade) => trade.securityId).join(",");

  useEffect(() => {
    if (!expanded || !legs.length) return;
    let cancelled = false;
    async function load() {
      try {
        const results = await Promise.all(
          legs.map((trade) =>
            getTradeCandles({
              securityId: trade.securityId as string,
              exchangeSegment: trade.exchangeSegment as string,
              instrument: trade.instrument || "OPTIDX",
              interval: "1",
            }),
          ),
        );
        if (cancelled) return;
        const combined = combineLegCandles(results.map((r) => r.candles));
        const resampled = resampleStrategyPoints(combined, Number(chartInterval));
        setSeries(withStrategyVwap(resampled));
        setError(null);
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : "Failed to load strategy candles.");
      }
    }
    load();
    const timer = window.setInterval(() => {
      if (isMarketHoursNow()) load();
    }, TRADE_CHART_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expanded, chartInterval, legsKey]);

  useEffect(() => {
    if (!expanded || !containerRef.current || chartRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: containerRef.current.clientWidth,
      height: 280,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (time: Time) => formatIstTime(time) },
      localization: { timeFormatter: (time: Time) => formatIstTime(time) },
    });
    priceSeriesRef.current = chart.addSeries(LineSeries, { color: STRATEGY_PRICE_COLOR, lineWidth: 2, title: "Strategy Price" });
    vwapSeriesRef.current = chart.addSeries(LineSeries, { color: STRATEGY_VWAP_COLOR, lineWidth: 2, title: "Strategy VWAP" });
    chartRef.current = chart;

    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      priceSeriesRef.current = null;
      vwapSeriesRef.current = null;
    };
  }, [expanded]);

  useEffect(() => {
    priceSeriesRef.current?.setData(series.map((p) => ({ time: p.time as UTCTimestamp, value: p.price })));
    vwapSeriesRef.current?.setData(series.map((p) => ({ time: p.time as UTCTimestamp, value: p.vwap })));
  }, [series]);

  return (
    <div className="strategy-chart-card">
      <div className="section-title pcr-oi-title" onClick={() => setExpanded((v) => !v)}>
        <h2 style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 15 }}>
          <button className="icon-button" type="button" title={expanded ? "Collapse" : "Expand"}>
            {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          </button>
          {group.tag}
        </h2>
        <span className="subtext">
          {legs.length} open leg{legs.length === 1 ? "" : "s"} — {legs.map((trade) => tradeLabel(trade)).join(", ")}
        </span>
      </div>
      <StrikeMap tag={group.tag} legs={group.openTrades} />
      {expanded ? (
        <div onClick={(event) => event.stopPropagation()}>
          {!legs.length ? (
            <p className="pcr-oi-caption">No open legs with a resolvable security id in this group.</p>
          ) : (
            <>
              <div className="pcr-oi-session-row" style={{ marginTop: 0 }}>
                <label className="subtext" htmlFor={`strategy-interval-${group.tag}`}>
                  Refresh
                </label>
                <select
                  id={`strategy-interval-${group.tag}`}
                  className="pcr-oi-session-select"
                  value={chartInterval}
                  onChange={(event) => setChartInterval(event.target.value as StrategyInterval)}
                >
                  {STRATEGY_INTERVAL_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
              {error ? <div className="alert error">{error}</div> : null}
              <div ref={containerRef} style={{ width: "100%" }} />
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}

// Compact number line of the tag's open strikes around spot: green guide
// marks every 0.5% out to 2.5% either side (above the line), each strike
// labelled with its distance from spot (below the line).
const STRIKE_MAP_PERCENT_MARKS = [0.5, 1, 1.5, 2, 2.5];

function StrikeMap({ tag, legs }: { tag: string; legs: LiveTrade[] }) {
  const spot = legs.find((leg) => leg.spotPrice)?.spotPrice ?? null;
  if (!spot) return null;
  const strikes = legs
    .filter((leg) => leg.strikePrice != null)
    .map((leg) => {
      const strike = Number(leg.strikePrice);
      const distance = (Math.abs(strike - spot) / spot) * 100;
      return {
        key: leg.id,
        strike,
        text: `${strike.toLocaleString("en-IN")} ${leg.optionSide ?? ""} (${distance.toFixed(2)}%)`,
        color: leg.qty < 0 ? "var(--red)" : "var(--green)",
      };
    });
  if (!strikes.length) return null;

  const width = 900;
  const maxMark = Math.max(...STRIKE_MAP_PERCENT_MARKS) / 100;
  const values = [spot * (1 - maxMark), spot * (1 + maxMark), ...strikes.map((s) => s.strike)];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min) * 0.04;
  const x = (value: number) => 16 + ((value - (min - pad)) / (max - min + 2 * pad)) * (width - 32);

  // Below-line labels: drop to a second row when one would collide with the
  // previous label (close strikes).
  const labelMinGap = 110;
  let lastAt = -Infinity;
  let lastRow = 1;
  const labels = strikes
    .map((s) => ({ ...s, at: x(s.strike) }))
    .sort((a, b) => a.at - b.at)
    .map((item) => {
      const row = item.at - lastAt < labelMinGap && lastRow === 0 ? 1 : 0;
      lastAt = item.at;
      lastRow = row;
      return { ...item, row };
    });
  const axisY = 26;
  const labelsY = axisY + 17;
  const height = labelsY + (labels.some((l) => l.row === 1) ? 14 : 0) + 6;

  return (
    <div style={{ margin: "2px 0 8px", maxWidth: 980 }}>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto", display: "block" }} role="img" aria-label={`${tag} strikes relative to spot`}>
        <line x1={8} x2={width - 8} y1={axisY} y2={axisY} stroke="var(--text)" strokeWidth={1} />
        {STRIKE_MAP_PERCENT_MARKS.flatMap((mark) => [-1, 1].map((sign) => {
          const at = x(spot * (1 + (sign * mark) / 100));
          return (
            <g key={`mark-${sign}-${mark}`}>
              <line x1={at} x2={at} y1={axisY - 5} y2={axisY} stroke="var(--green)" strokeWidth={1} />
              <text x={at} y={axisY - 8} textAnchor="middle" fontSize={9} fill="var(--green)">
                {mark}%
              </text>
            </g>
          );
        }))}
        <line x1={x(spot)} x2={x(spot)} y1={axisY - 9} y2={axisY + 6} stroke="var(--blue)" strokeWidth={2.5} />
        <text x={x(spot)} y={axisY - 12} textAnchor="middle" fontSize={10} fontWeight={700} fill="var(--blue)">
          SPOT {Math.round(spot).toLocaleString("en-IN")}
        </text>
        {labels.map((item) => (
          <g key={`strike-${item.key}`}>
            <line x1={item.at} x2={item.at} y1={axisY - 5} y2={axisY + 5} stroke={item.color} strokeWidth={2} />
            <text x={item.at} y={labelsY + item.row * 14} textAnchor="middle" fontSize={10} fill={item.color}>
              {item.text}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function formatCandleTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatIstTime(time: Time): string {
  if (typeof time !== "number") return String(time);
  return formatCandleTime(time);
}

function draftsFromSnapshot(snapshot: LiveTradeSnapshot): Record<string, DraftLevels> {
  const rows = [...snapshot.groups.options, ...snapshot.groups.closed.filter((trade) => trade.assetClass === "OPTION")];
  return Object.fromEntries(rows.map((trade) => [trade.id, {
    stopLoss: stopLossLevelText(trade),
    target: valueText(trade.levels?.target),
    notes: trade.levels?.notes ?? "",
    tag: trade.levels?.tag ?? "",
  }]));
}

function emptyDraft(): DraftLevels {
  return { stopLoss: "", target: "", notes: "", tag: "" };
}

const UNTAGGED = "Untagged";

// The backend assigns every option position an effective tag: the one typed
// in, else the underlying ("nifty" / "sensex"), with "_ss" for a detected
// short strangle. Older payloads without it fall back to the saved tag.
function tagOf(trade: LiveTrade): string {
  return trade.tag?.trim() || trade.levels?.tag?.trim() || UNTAGGED;
}

function isStrangleTag(tag: string): boolean {
  return tag.toLowerCase().endsWith("_ss");
}

function groupOptionsByTag(openTrades: LiveTrade[], closedTrades: LiveTrade[], summaries: TagSummary[]): TagGroup[] {
  const map = new Map<string, TagGroup>();
  function ensure(tag: string): TagGroup {
    let group = map.get(tag);
    if (!group) {
      group = { tag, openTrades: [], closedTrades: [] };
      map.set(tag, group);
    }
    return group;
  }
  for (const trade of openTrades) ensure(tagOf(trade)).openTrades.push(trade);
  for (const trade of closedTrades) ensure(tagOf(trade)).closedTrades.push(trade);
  for (const summary of summaries) {
    const group = map.get(summary.tag);
    if (group) group.summary = summary;
  }

  const groups = Array.from(map.values());
  groups.sort((a, b) => {
    if (a.tag === UNTAGGED) return b.tag === UNTAGGED ? 0 : 1;
    if (b.tag === UNTAGGED) return -1;
    return a.tag.localeCompare(b.tag);
  });
  return groups;
}

function sumField(trades: LiveTrade[], field: "dayPnl" | "estimatedCharges" | "estimatedNetPnl" | "profitRemaining"): number {
  return roundLevel(trades.reduce((total, trade) => total + (Number(trade[field]) || 0), 0));
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
