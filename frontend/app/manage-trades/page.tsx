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

import { approveRiskExit, closeTrade, getDhanSession, getLiveTrades, getTradeCandles, loginDhan, saveTradeLevels } from "@/lib/api";
import { isMarketHoursNow } from "@/lib/marketHours";
import type { DhanSession, LiveTrade, LiveTradeSnapshot, MarketCandle } from "@/types/live";
import PaperTradingPanel from "@/components/PaperTradingPanel";
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

  function updateDraft(tradeId: string, key: keyof DraftLevels, value: string) {
    setDrafts((current) => ({ ...current, [tradeId]: { ...(current[tradeId] ?? emptyDraft()), [key]: value } }));
  }

  const summary = snapshot?.summary;
  const optionTrades = snapshot?.groups.options ?? [];
  const awaitingApproval = useMemo(() => optionTrades.filter(isAwaitingApproval), [optionTrades]);
  const closedTrades = snapshot?.groups.closed ?? [];
  const closedEquity = closedTrades.filter((trade) => trade.assetClass === "EQUITY");
  const closedOptions = closedTrades.filter((trade) => trade.assetClass === "OPTION");
  const groupsByTag = useMemo(() => groupOptionsByTag(optionTrades, closedOptions), [optionTrades, closedOptions]);

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

      <PaperTradingPanel />

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
          expandedIds={expandedIds}
          onToggleExpand={toggleExpand}
        />
      ))}

      {groupsByTag.some((group) => group.openTrades.length > 0) ? (
        <div className="pcr-oi-section">
          <h3>Strategy Charts</h3>
          <p className="pcr-oi-caption" style={{ margin: 0 }}>
            One combined chart per label -- Strategy Price is the sum of each open leg's LTP, Strategy VWAP is the
            same series volume-weighted (each leg's own traded volume, combined) since session start.
          </p>
          {groupsByTag
            .filter((group) => group.openTrades.length > 0)
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

function TagGroupTable({
  group,
  drafts,
  savingId,
  onDraft,
  onSave,
  onClose,
  onApprove,
  expandedIds,
  onToggleExpand,
}: {
  group: TagGroup;
  drafts: Record<string, DraftLevels>;
  savingId: string | null;
  onDraft: (tradeId: string, key: keyof DraftLevels, value: string) => void;
  onSave: (trade: LiveTrade) => void;
  onClose: (trade: LiveTrade) => void;
  onApprove: (trade: LiveTrade) => void;
  expandedIds: Set<string>;
  onToggleExpand: (tradeId: string) => void;
}) {
  const columnCount = 17;
  const allRows = [...group.openTrades, ...group.closedTrades];
  const totalRows = allRows.length;
  const groupDayPnl = sumField(allRows, "dayPnl");
  const groupCharges = sumField(allRows, "estimatedCharges");
  const groupNetPnl = sumField(allRows, "estimatedNetPnl");
  const groupRemaining = sumField(allRows, "profitRemaining");

  return (
    <section className="table-section">
      <div className="section-title">
        <h2>{group.tag}</h2>
        <span>{totalRows}</span>
      </div>
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
                      placeholder="tag"
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
            placeholder="tag"
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

function tagOf(trade: LiveTrade): string {
  return trade.levels?.tag?.trim() || UNTAGGED;
}

function groupOptionsByTag(openTrades: LiveTrade[], closedTrades: LiveTrade[]): TagGroup[] {
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
