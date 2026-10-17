"use client";

import { ArrowDown, ArrowDownToLine, ArrowUp, ArrowUpDown, ChevronDown, ChevronRight, History, LineChart, Newspaper, RefreshCw, Save, Search, WalletCards, X } from "lucide-react";
import { Fragment, useEffect, useMemo, useState } from "react";

import {
  getEquityNews,
  getEquityOptionsReport,
  getEquityPortfolio,
  getEquityTransactions,
  getLowestPriceOverrides,
  setLowestPriceOverride,
} from "@/lib/api";
import type {
  EquityHolding,
  EquityNewsItem,
  EquityNewsPayload,
  EquityOptionsPeriod,
  EquityOptionsReportPayload,
  EquityPortfolioPayload,
  EquityTransaction,
  EquityTransactionsPayload,
} from "@/types/equity";
import EquityHoldingsHistory from "@/components/EquityHoldingsHistory";
import EquityEntrySignals, { EntryBadge, entryRank } from "@/components/EquityEntrySignals";

type EquityTab = "portfolio" | "history" | "lowest" | "transactions" | "options" | "research";
type SortDirection = "asc" | "desc";
type SortValue = string | number | boolean | Date | null | undefined;
type SortState<Key extends string> = { key: Key; direction: SortDirection };
type SortColumn<Row, Key extends string> = {
  key: Key;
  label: string;
  value: (row: Row) => SortValue;
};
type PortfolioRow = EquityHolding & {
  leastBuyPrice?: number | null;
  isManualLowest?: boolean;
  priceGap?: number | null;
  priceGapPercent?: number | null;
};

type PortfolioSortKey =
  | "stock"
  | "qty"
  | "avgBuy"
  | "leastBuyPrice"
  | "ltp"
  | "priceGap"
  | "priceGapPercent"
  | "invested"
  | "marketValue"
  | "pnl"
  | "pnlPercent"
  | "exposure"
  | "pe"
  | "medianPe"
  | "roce"
  | "debtToEquity"
  | "sma20"
  | "sma50"
  | "sma200"
  | "score"
  | "rsi"
  | "recommendation"
  | "entry";
type TransactionSortKey = "date" | "stock" | "side" | "qty" | "price" | "value" | "charges" | "product" | "order" | "tradeId";
type LowestSortKey = "stock" | "leastBuyPrice" | "priceGapPercent" | "recommendation";
type ResearchSortKey = "stock" | "score" | "action" | "reasons" | "risks" | "guruChecks";

const portfolioColumns: SortColumn<PortfolioRow, PortfolioSortKey>[] = [
  { key: "stock", label: "Stock", value: (row) => row.symbol || row.tradingSymbol || "" },
  { key: "qty", label: "Qty", value: (row) => row.totalQty },
  { key: "avgBuy", label: "Avg Buy", value: (row) => row.avgCostPrice },
  { key: "leastBuyPrice", label: "Lowest Buy", value: (row) => row.leastBuyPrice },
  { key: "ltp", label: "LTP", value: (row) => row.ltp },
  { key: "priceGap", label: "Gap", value: (row) => row.priceGap },
  { key: "priceGapPercent", label: "Gap %", value: (row) => row.priceGapPercent },
  { key: "invested", label: "Invested", value: (row) => row.investedValue },
  { key: "marketValue", label: "Market Value", value: (row) => row.marketValue },
  { key: "pnl", label: "P&L", value: (row) => row.pnl },
  { key: "pnlPercent", label: "P&L %", value: (row) => row.pnlPercent },
  { key: "exposure", label: "Exposure", value: (row) => row.exposurePercent },
  { key: "pe", label: "PE", value: (row) => row.fundamentals?.pe },
  { key: "medianPe", label: "3Yrs PE", value: (row) => row.fundamentals?.medianPe },
  { key: "roce", label: "ROCE", value: (row) => row.fundamentals?.roce },
  { key: "debtToEquity", label: "D/E", value: (row) => row.fundamentals?.debtToEquity },
  { key: "sma20", label: "SMA20", value: (row) => row.technicals?.sma20 },
  { key: "sma50", label: "SMA50", value: (row) => row.technicals?.sma50 },
  { key: "sma200", label: "SMA200", value: (row) => row.technicals?.sma200 },
  { key: "rsi", label: "RSI", value: (row) => row.technicals?.rsi14 },
  { key: "score", label: "Score", value: (row) => row.recommendation?.score },
  { key: "recommendation", label: "Recommendation", value: (row) => row.recommendation?.action },
  { key: "entry", label: "Entry", value: (row) => entryRank(row.entrySignal) },
];

const transactionColumns: SortColumn<EquityTransaction, TransactionSortKey>[] = [
  { key: "date", label: "Date", value: (row) => row.exchangeTime || row.updateTime || row.createTime },
  { key: "stock", label: "Stock", value: (row) => row.symbol || row.tradingSymbol || row.customSymbol || "" },
  { key: "side", label: "Side", value: (row) => row.transactionType },
  { key: "qty", label: "Qty", value: (row) => row.quantity },
  { key: "price", label: "Price", value: (row) => row.price },
  { key: "value", label: "Value", value: (row) => row.value },
  { key: "charges", label: "Charges", value: (row) => row.charges },
  { key: "product", label: "Product", value: (row) => row.productType },
  { key: "order", label: "Order", value: (row) => row.orderId },
  { key: "tradeId", label: "Trade ID", value: (row) => row.exchangeTradeId },
];

const lowestColumns: SortColumn<PortfolioRow, LowestSortKey>[] = [
  { key: "stock", label: "Stock", value: (row) => row.symbol || row.tradingSymbol || "" },
  { key: "leastBuyPrice", label: "Lowest Price", value: (row) => row.leastBuyPrice },
  { key: "priceGapPercent", label: "Gap %", value: (row) => row.priceGapPercent },
  { key: "recommendation", label: "Recommendation", value: (row) => row.recommendation?.score },
];

const researchColumns: SortColumn<EquityHolding, ResearchSortKey>[] = [
  { key: "stock", label: "Stock", value: (row) => row.symbol },
  { key: "score", label: "Score", value: (row) => row.recommendation?.score },
  { key: "action", label: "Action", value: (row) => row.recommendation?.action },
  { key: "reasons", label: "Reasons", value: (row) => row.recommendation?.reasons.join(" ") },
  { key: "risks", label: "Risks", value: (row) => row.recommendation?.risks.join(" ") },
  {
    key: "guruChecks",
    label: "Guru Checks",
    value: (row) => row.recommendation?.guruSignals.map((signal) => `${signal.name} ${signal.status}`).join(" "),
  },
];

const numberFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
const compactFormat = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 2 });

function money(value?: number | null, compact = false): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "-";
  return compact ? compactFormat.format(value) : numberFormat.format(value);
}

function percent(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "-";
  return `${value > 0 ? "+" : ""}${numberFormat.format(value)}%`;
}

function toneColor(value?: number | null): string | undefined {
  if (!value) return undefined;
  return value > 0 ? "var(--green)" : "var(--red)";
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function EquityView() {
  const [activeTab, setActiveTab] = useState<EquityTab>("portfolio");
  const [portfolio, setPortfolio] = useState<EquityPortfolioPayload | null>(null);
  const [transactions, setTransactions] = useState<EquityTransactionsPayload | null>(null);
  const [news, setNews] = useState<EquityNewsPayload | null>(null);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState(today());
  const [loading, setLoading] = useState(false);
  const [refreshingNews, setRefreshingNews] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lowestPriceOverrides, setLowestPriceOverrides] = useState<Record<string, number>>({});
  const [optionsReport, setOptionsReport] = useState<EquityOptionsReportPayload | null>(null);
  const [optionsReportError, setOptionsReportError] = useState<string | null>(null);

  async function loadPortfolio(refresh = false) {
    const next = await getEquityPortfolio(refresh);
    setPortfolio(next);
  }

  async function loadLowestPriceOverrides(isRetry = false) {
    try {
      setLowestPriceOverrides(await getLowestPriceOverrides());
    } catch {
      // Same transient-auth hiccup the main retry effect below recovers
      // from for portfolio/transactions -- this fetch isn't tied to that
      // shared error/portfolio state (a failure here shouldn't show a
      // scary banner for what's a non-critical enhancement), so it gets
      // its own one-shot retry instead.
      if (!isRetry) {
        window.setTimeout(() => loadLowestPriceOverrides(true), 2500);
      }
    }
  }

  async function saveLowestPriceOverride(securityId: string, price: number | null) {
    const result = await setLowestPriceOverride(securityId, price);
    setLowestPriceOverrides((current) => {
      const next = { ...current };
      if (result.price === null) {
        delete next[securityId];
      } else {
        next[securityId] = result.price;
      }
      return next;
    });
  }

  async function loadTransactions(refresh = false) {
    const next = await getEquityTransactions({ fromDate: fromDate || undefined, toDate: toDate || undefined, refresh });
    setTransactions(next);
  }

  async function load(refresh = false) {
    setLoading(true);
    setError(null);
    void loadTransactions(refresh).catch((exc) => {
      setError((current) => [current, exc instanceof Error ? exc.message : "Failed to load equity transactions."].filter(Boolean).join(" | "));
    });
    try {
      await loadPortfolio(refresh);
    } catch (exc) {
      setError((current) => [current, exc instanceof Error ? exc.message : "Failed to load equity portfolio."].filter(Boolean).join(" | "));
    } finally {
      setLoading(false);
    }
  }

  async function refreshNews() {
    setRefreshingNews(true);
    setError(null);
    try {
      const next = await getEquityNews(true);
      setNews(next);
      await loadPortfolio(true);
      setActiveTab("research");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to refresh equity news.");
    } finally {
      setRefreshingNews(false);
    }
  }

  async function loadOptionsReport() {
    try {
      setOptionsReport(await getEquityOptionsReport());
      setOptionsReportError(null);
    } catch (exc) {
      setOptionsReportError(exc instanceof Error ? exc.message : "Failed to load options report.");
    }
  }

  useEffect(() => {
    load(false);
    void loadLowestPriceOverrides();
    void loadOptionsReport();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A transient failure on the very first load (auth session still
  // settling, a momentary network blip) would otherwise leave the page
  // stuck showing nothing -- retry once automatically rather than making
  // the user hit refresh themselves.
  useEffect(() => {
    if (!error || portfolio) return;
    const timer = window.setTimeout(() => {
      load(false);
    }, 2500);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [error, portfolio]);

  const holdings = portfolio?.data ?? [];
  const newsRows = news?.data ?? holdings.map((holding) => holding.news).filter(Boolean);
  const portfolioRows = useMemo(
    () => buildPortfolioRows(holdings, transactions?.data ?? [], lowestPriceOverrides),
    [holdings, transactions?.data, lowestPriceOverrides],
  );

  return (
    <section className="page equity-page">
      <header className="page-header">
        <div>
          <h1>
            <WalletCards size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Equity
          </h1>
          <p>{portfolio ? `${portfolio.count} portfolio stocks` : "Portfolio loading"}</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div className="metric-compact">
            <span>Market Value</span>
            <strong>{money(portfolio?.summary.marketValue, true)}</strong>
          </div>
          <div className="metric-compact">
            <span>Invested</span>
            <strong>{money(portfolio?.summary.totalInvested, true)}</strong>
          </div>
          <div className="metric-compact">
            <span>P&amp;L</span>
            <strong style={{ color: toneColor(portfolio?.summary.pnl) }}>{money(portfolio?.summary.pnl, true)}</strong>
          </div>
          <div className="metric-compact">
            <span>P&amp;L %</span>
            <strong style={{ color: toneColor(portfolio?.summary.pnlPercent) }}>{percent(portfolio?.summary.pnlPercent)}</strong>
          </div>
          <button className="icon-button" title="Refresh equity data" onClick={() => load(true)} disabled={loading}>
            <RefreshCw size={16} />
          </button>
          <button className="button secondary" onClick={refreshNews} disabled={refreshingNews}>
            <Newspaper size={15} />
            News
          </button>
        </div>
      </header>

      {portfolio?.warning ? <div className="alert warning">{portfolio.warning}</div> : null}
      {transactions?.warning ? <div className="alert warning">{transactions.warning}</div> : null}
      {error ? <div className="alert warning">{error}</div> : null}

      <div className="toolbar" role="tablist" aria-label="Equity sections" style={{ marginBottom: 12 }}>
        <button
          className="button secondary"
          style={activeTab === "portfolio" ? { background: "var(--accent, #2368b6)", color: "#fff" } : undefined}
          onClick={() => setActiveTab("portfolio")}
        >
          <WalletCards size={15} style={{ verticalAlign: "-2px", marginRight: 6 }} />
          Portfolio
        </button>
        <button
          className="button secondary"
          style={activeTab === "history" ? { background: "var(--accent, #2368b6)", color: "#fff" } : undefined}
          onClick={() => setActiveTab("history")}
        >
          <History size={15} style={{ verticalAlign: "-2px", marginRight: 6 }} />
          Holdings &amp; History
        </button>
        <button
          className="button secondary"
          style={activeTab === "lowest" ? { background: "var(--accent, #2368b6)", color: "#fff" } : undefined}
          onClick={() => setActiveTab("lowest")}
        >
          <ArrowDownToLine size={15} style={{ verticalAlign: "-2px", marginRight: 6 }} />
          Lowest
        </button>
        <button
          className="button secondary"
          style={activeTab === "transactions" ? { background: "var(--accent, #2368b6)", color: "#fff" } : undefined}
          onClick={() => setActiveTab("transactions")}
        >
          <RefreshCw size={15} style={{ verticalAlign: "-2px", marginRight: 6 }} />
          All Transactions
        </button>
        <button
          className="button secondary"
          style={activeTab === "options" ? { background: "var(--accent, #2368b6)", color: "#fff" } : undefined}
          onClick={() => setActiveTab("options")}
        >
          <LineChart size={15} style={{ verticalAlign: "-2px", marginRight: 6 }} />
          Options Report
        </button>
        <button
          className="button secondary"
          style={activeTab === "research" ? { background: "var(--accent, #2368b6)", color: "#fff" } : undefined}
          onClick={() => setActiveTab("research")}
        >
          <Search size={15} style={{ verticalAlign: "-2px", marginRight: 6 }} />
          Research &amp; News
        </button>
      </div>

      {activeTab === "portfolio" ? <PortfolioPanel holdings={portfolioRows} /> : null}
      {activeTab === "history" ? <EquityHoldingsHistory holdings={holdings} transactions={transactions?.data ?? []} /> : null}
      {activeTab === "lowest" ? <LowestPricePanel holdings={portfolioRows} onSaveOverride={saveLowestPriceOverride} /> : null}
      {activeTab === "transactions" ? (
        <TransactionsPanel
          payload={transactions}
          fromDate={fromDate}
          toDate={toDate}
          loading={loading}
          onFromDate={setFromDate}
          onToDate={setToDate}
          onLoad={() => loadTransactions(true)}
        />
      ) : null}
      {activeTab === "options" ? <OptionsReportPanel report={optionsReport} error={optionsReportError} /> : null}
      {activeTab === "research" ? <ResearchPanel holdings={holdings} newsRows={newsRows} /> : null}
    </section>
  );
}

function PortfolioPanel({ holdings }: { holdings: PortfolioRow[] }) {
  const { stockHoldings, etfHoldings } = useMemo(() => splitPortfolioHoldings(holdings), [holdings]);
  const preferredHoldings = useMemo(() => holdings.filter(isPotentialOrAccumulate), [holdings]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <EquityEntrySignals holdings={holdings} />
      <RecommendationNote />
      <PortfolioTable
        title="Potential Buy / Accumulate"
        holdings={preferredHoldings}
        emptyLabel="No Potential Buy or Accumulate recommendations right now."
      />
      <PortfolioTable title="Stocks" holdings={stockHoldings} emptyLabel="No stock holdings returned by Dhan." />
      <PortfolioTable title="ETFs" holdings={etfHoldings} emptyLabel="No ETF holdings returned by Dhan." />
    </div>
  );
}

function RecommendationNote() {
  const rows = [
    { label: "A / Potential Buy", detail: "75-100 score. Strong valuation, quality, trend and risk profile." },
    { label: "B / Accumulate", detail: "62-74 score. Constructive setup, but not as clean as A." },
    { label: "C / Hold / Watch", detail: "45-61 score. Mixed signals; monitor before adding." },
    { label: "D / Review", detail: "30-44 score. Weakness or risk flags need active review." },
    { label: "E / Avoid / Reduce", detail: "0-29 score. Major valuation, quality, trend or news risk." },
  ];

  return (
    <div className="pcr-oi-section">
      <h3 style={{ margin: "0 0 6px" }}>Recommendation guide</h3>
      <p className="pcr-oi-caption" style={{ margin: "0 0 10px" }}>
        Long-term oriented score starts at 50 and adjusts for valuation, quality, balance-sheet risk, growth, timing trend and recent news.
        PE versus 3Yrs PE/industry, ROCE/ROE, debt, pledge and 3Y growth are the long-term core; SMA20/SMA50/SMA200 and news are timing/risk overlays.
        Potential Buy requires independent long-term gates for quality, leverage, growth durability, valuation and business risk, plus a reasonable timing setup.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 14 }}>
        {rows.map((row) => (
          <span key={row.label} title={row.detail} className="equity-grade-legend-item">
            <b>{row.label}</b> {row.detail}
          </span>
        ))}
      </div>
    </div>
  );
}

function PortfolioTable({ title, holdings, emptyLabel }: { title: string; holdings: PortfolioRow[]; emptyLabel: string }) {
  const { sortedRows, sort, toggleSort } = useSortableRows(holdings, portfolioColumns, { key: "marketValue", direction: "desc" });
  const [selectedHolding, setSelectedHolding] = useState<PortfolioRow | null>(null);

  return (
    <div className="pcr-oi-section">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>{title}</h3>
        <span className="pcr-oi-caption" style={{ margin: 0 }}>{holdings.length} holdings</span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table>
          <thead>
            <tr>
              {portfolioColumns.map((column) => (
                <SortableHeader key={column.key} column={column} sort={sort} onSort={toggleSort} />
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((holding) => (
              <tr key={holding.id || holding.securityId}>
                <td>
                  <div>{holding.symbol || holding.tradingSymbol}</div>
                  <div className="pcr-oi-caption" style={{ margin: 0 }}>{holding.isin || holding.securityId}</div>
                </td>
                <td>{money(holding.totalQty)}</td>
                <td>{money(holding.avgCostPrice)}</td>
                <td>{money(holding.leastBuyPrice)}</td>
                <td>{money(holding.ltp)}</td>
                <td style={{ color: toneColor(holding.priceGap) }}>{money(holding.priceGap)}</td>
                <td style={{ color: toneColor(holding.priceGapPercent) }}>{percent(holding.priceGapPercent)}</td>
                <td>{money(holding.investedValue)}</td>
                <td>{money(holding.marketValue)}</td>
                <td style={{ color: toneColor(holding.pnl) }}>{money(holding.pnl)}</td>
                <td style={{ color: toneColor(holding.pnlPercent) }}>{percent(holding.pnlPercent)}</td>
                <td>{percent(holding.exposurePercent)}</td>
                <td>{money(holding.fundamentals?.pe)}</td>
                <td>{money(holding.fundamentals?.medianPe)}</td>
                <td>{percent(holding.fundamentals?.roce)}</td>
                <td>{money(holding.fundamentals?.debtToEquity)}</td>
                <td>{money(holding.technicals?.sma20)}</td>
                <td>{money(holding.technicals?.sma50)}</td>
                <td>{money(holding.technicals?.sma200)}</td>
                <td>{holding.technicals?.rsi14 != null ? holding.technicals.rsi14.toFixed(0) : "—"}</td>
                <td>
                  <span className={`equity-grade equity-grade-${holding.recommendation.grade.toLowerCase()}`}>
                    {holding.recommendation.grade} {money(holding.recommendation.score)}
                  </span>
                </td>
                <td>
                  <RecommendationButton holding={holding} onClick={() => setSelectedHolding(holding)} />
                </td>
                <td>
                  <EntryBadge signal={holding.entrySignal} />
                </td>
              </tr>
            ))}
            {!holdings.length ? (
              <tr>
                <td colSpan={portfolioColumns.length} className="pcr-oi-caption">{emptyLabel}</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      {selectedHolding ? <RecommendationReasonDialog holding={selectedHolding} onClose={() => setSelectedHolding(null)} /> : null}
    </div>
  );
}

function LowestPricePanel({
  holdings,
  onSaveOverride,
}: {
  holdings: PortfolioRow[];
  onSaveOverride: (securityId: string, price: number | null) => Promise<void>;
}) {
  const { sortedRows, sort, toggleSort } = useSortableRows(holdings, lowestColumns, { key: "priceGapPercent", direction: "asc" });

  return (
    <div className="pcr-oi-section">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>Lowest buy price</h3>
        <span className="pcr-oi-caption" style={{ margin: 0 }}>{holdings.length} holdings</span>
      </div>
      <p className="pcr-oi-caption" style={{ margin: "0 0 10px" }}>
        Lowest price ever paid for each holding, from your BUY transaction history (matched by security id, then ISIN,
        then symbol) -- not the average buy price. Gap % is LTP vs that lowest price, so a negative gap means the
        stock is currently trading below the lowest price you&apos;ve ever bought it at. Sorted by Gap % ascending by
        default. Dhan&apos;s trade-history API doesn&apos;t serve records older than roughly the last 2-3 months
        regardless of the date range requested (confirmed by testing; undocumented) -- for anything bought before
        that window, type the price in yourself and click save; it&apos;s remembered from then on. Mutual funds
        aren&apos;t included yet -- Dhan&apos;s API has no mutual fund holdings endpoint at all.
      </p>
      <div style={{ overflowX: "auto" }}>
        <table>
          <thead>
            <tr>
              {lowestColumns.map((column) => (
                <SortableHeader key={column.key} column={column} sort={sort} onSort={toggleSort} />
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((holding) => (
              <tr key={holding.id || holding.securityId}>
                <td>
                  <div>{holding.symbol || holding.tradingSymbol}</div>
                  <div className="pcr-oi-caption" style={{ margin: 0 }}>{holding.isin || holding.securityId}</div>
                </td>
                <td>
                  <LowestPriceCell
                    value={holding.leastBuyPrice ?? null}
                    isManual={Boolean(holding.isManualLowest)}
                    onSave={(price) => onSaveOverride(holding.securityId, price)}
                  />
                </td>
                <td style={{ color: toneColor(holding.priceGapPercent) }}>{percent(holding.priceGapPercent)}</td>
                <td>
                  <span className={`equity-grade equity-grade-${holding.recommendation.grade.toLowerCase()}`}>
                    {holding.recommendation.grade} {money(holding.recommendation.score)}
                  </span>{" "}
                  {holding.recommendation.action}
                </td>
              </tr>
            ))}
            {!holdings.length ? (
              <tr>
                <td colSpan={lowestColumns.length} className="pcr-oi-caption">No holdings returned by Dhan.</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LowestPriceCell({
  value,
  isManual,
  onSave,
}: {
  value: number | null;
  isManual: boolean;
  onSave: (price: number | null) => Promise<void>;
}) {
  const [draft, setDraft] = useState(value != null ? String(value) : "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(value != null ? String(value) : "");
  }, [value]);

  const dirty = draft !== (value != null ? String(value) : "");

  async function save() {
    if (!dirty || saving) return;
    const parsed = draft.trim() === "" ? null : Number(draft);
    if (parsed !== null && Number.isNaN(parsed)) {
      setError("Not a valid number.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave(parsed);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to save.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 140 }}>
      <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
        <input
          type="number"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              save();
            }
          }}
          onBlur={save}
          placeholder="No BUY trades found"
          style={{ flex: 1, fontSize: 12, padding: "2px 6px", minWidth: 90 }}
        />
        <button type="button" className="icon-button" title="Save" onClick={save} disabled={!dirty || saving}>
          <Save size={13} />
        </button>
      </div>
      {isManual ? <span className="pcr-oi-caption" style={{ margin: 0 }}>manual</span> : null}
      {error ? <span style={{ fontSize: 11, color: "var(--red)" }}>{error}</span> : null}
    </div>
  );
}

function OptionsReportPanel({ report, error }: { report: EquityOptionsReportPayload | null; error: string | null }) {
  const [grouping, setGrouping] = useState<"monthly" | "yearly">("yearly");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  if (error) {
    return (
      <div className="pcr-oi-section">
        <div className="alert warning">{error}</div>
      </div>
    );
  }

  const periods = report ? (grouping === "yearly" ? report.yearly : report.monthly) : [];

  return (
    <div className="pcr-oi-section">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, flexWrap: "wrap", gap: 8 }}>
        <h3 style={{ margin: 0 }}>Options P&amp;L report</h3>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span className="pcr-oi-caption" style={{ margin: 0 }}>{report?.count ?? 0} option leg-days</span>
          <button
            className="button secondary"
            style={grouping === "yearly" ? { background: "var(--accent, #2368b6)", color: "#fff" } : undefined}
            onClick={() => setGrouping("yearly")}
          >
            Financial Year
          </button>
          <button
            className="button secondary"
            style={grouping === "monthly" ? { background: "var(--accent, #2368b6)", color: "#fff" } : undefined}
            onClick={() => setGrouping("monthly")}
          >
            Month
          </button>
        </div>
      </div>
      <p className="pcr-oi-caption" style={{ margin: "0 0 10px" }}>
        Built from Dhan&apos;s per-scrip-per-day &quot;Global Transaction Report&quot; CSVs, imported via
        scripts/import_dhan_csv.py -- Dhan&apos;s live API has no options trade-history endpoint, so this data only
        exists here because it was backfilled from a manual export. Gross P&amp;L is Sell Value minus Buy Value minus
        that day&apos;s charges, per leg. Click a row to see the breakdown by underlying.
      </p>
      {report && report.totals.trades > 0 ? (
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginBottom: 12 }}>
          <div className="metric-compact">
            <span>Total Trades</span>
            <strong>{report.totals.trades}</strong>
          </div>
          <div className="metric-compact">
            <span>Total Charges</span>
            <strong>{money(report.totals.charges)}</strong>
          </div>
          <div className="metric-compact">
            <span>Gross P&amp;L</span>
            <strong style={{ color: toneColor(report.totals.grossPnl) }}>{money(report.totals.grossPnl)}</strong>
          </div>
        </div>
      ) : null}
      <div style={{ overflowX: "auto" }}>
        <table>
          <thead>
            <tr>
              <th />
              <th>{grouping === "yearly" ? "Financial Year" : "Month"}</th>
              <th>Trades</th>
              <th>Buy Value</th>
              <th>Sell Value</th>
              <th>Charges</th>
              <th>Gross P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {periods.map((entry: EquityOptionsPeriod) => {
              const isOpen = expanded[entry.period] ?? false;
              const underlyings = Object.entries(entry.byUnderlying).sort((a, b) => b[1].trades - a[1].trades);
              return (
                <Fragment key={entry.period}>
                  <tr
                    style={{ cursor: "pointer" }}
                    onClick={() => setExpanded((current) => ({ ...current, [entry.period]: !isOpen }))}
                  >
                    <td>{isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
                    <td>{entry.period}</td>
                    <td>{entry.trades}</td>
                    <td>{money(entry.buyValue)}</td>
                    <td>{money(entry.sellValue)}</td>
                    <td>{money(entry.charges)}</td>
                    <td style={{ color: toneColor(entry.grossPnl) }}>{money(entry.grossPnl)}</td>
                  </tr>
                  {isOpen
                    ? underlyings.map(([name, bucket]) => (
                        <tr key={`${entry.period}-${name}`} className="pcr-oi-caption">
                          <td />
                          <td style={{ paddingLeft: 20 }}>{name}</td>
                          <td>{bucket.trades}</td>
                          <td>{money(bucket.buyValue)}</td>
                          <td>{money(bucket.sellValue)}</td>
                          <td>{money(bucket.charges)}</td>
                          <td style={{ color: toneColor(bucket.grossPnl) }}>{money(bucket.grossPnl)}</td>
                        </tr>
                      ))
                    : null}
                </Fragment>
              );
            })}
            {!periods.length ? (
              <tr>
                <td colSpan={7} className="pcr-oi-caption">No options transactions imported yet.</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TransactionsPanel({
  payload,
  fromDate,
  toDate,
  loading,
  onFromDate,
  onToDate,
  onLoad,
}: {
  payload: EquityTransactionsPayload | null;
  fromDate: string;
  toDate: string;
  loading: boolean;
  onFromDate: (value: string) => void;
  onToDate: (value: string) => void;
  onLoad: () => void;
}) {
  const rows = payload?.data ?? [];
  const { sortedRows, sort, toggleSort } = useSortableRows(rows, transactionColumns, { key: "date", direction: "desc" });

  return (
    <div className="pcr-oi-section">
      <div style={{ display: "flex", gap: 16, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 12 }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12 }}>
          <span>From</span>
          <input type="date" value={fromDate} onChange={(event) => onFromDate(event.target.value)} />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12 }}>
          <span>To</span>
          <input type="date" value={toDate} onChange={(event) => onToDate(event.target.value)} />
        </label>
        <button className="button secondary" onClick={onLoad} disabled={loading}>
          <RefreshCw size={15} />
          Load
        </button>
        <div className="metric-compact">
          <span>Buy Value</span>
          <strong>{money(payload?.summary.buyValue, true)}</strong>
        </div>
        <div className="metric-compact">
          <span>Sell Value</span>
          <strong>{money(payload?.summary.sellValue, true)}</strong>
        </div>
        <div className="metric-compact">
          <span>Charges</span>
          <strong>{money(payload?.summary.charges)}</strong>
        </div>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table>
          <thead>
            <tr>
              {transactionColumns.map((column) => (
                <SortableHeader key={column.key} column={column} sort={sort} onSort={toggleSort} />
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((row) => (
              <TransactionRow key={row.id} row={row} />
            ))}
            {!rows.length ? (
              <tr>
                <td colSpan={transactionColumns.length} className="pcr-oi-caption">No equity transactions found for current portfolio stocks.</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TransactionRow({ row }: { row: EquityTransaction }) {
  return (
    <tr>
      <td>{row.exchangeTime || row.updateTime || row.createTime || "-"}</td>
      <td>
        <div>{row.symbol || row.tradingSymbol || row.customSymbol}</div>
        <div className="pcr-oi-caption" style={{ margin: 0 }}>{row.isin || row.securityId}</div>
      </td>
      <td>
        <span className={`badge ${row.transactionType === "BUY" ? "buy" : "sell"}`}>
          {row.transactionType === "BUY" ? "B" : "S"}
        </span>
      </td>
      <td>{money(row.quantity)}</td>
      <td>{money(row.price)}</td>
      <td>{money(row.value)}</td>
      <td>{money(row.charges)}</td>
      <td>{row.productType || "-"}</td>
      <td>{row.orderId || "-"}</td>
      <td>{row.exchangeTradeId || "-"}</td>
    </tr>
  );
}

function ResearchPanel({ holdings, newsRows }: { holdings: EquityHolding[]; newsRows: EquityNewsItem[] }) {
  const { sortedRows, sort, toggleSort } = useSortableRows(holdings, researchColumns, { key: "score", direction: "desc" });
  const [selectedHolding, setSelectedHolding] = useState<EquityHolding | null>(null);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="pcr-oi-section">
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                {researchColumns.map((column) => (
                  <SortableHeader key={column.key} column={column} sort={sort} onSort={toggleSort} />
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((holding) => (
                <tr key={holding.id || holding.securityId}>
                  <td>
                    <div>{holding.symbol}</div>
                    <div className="pcr-oi-caption" style={{ margin: 0 }}>{holding.news?.sentiment || "neutral"} news</div>
                  </td>
                  <td>
                    <span className={`equity-grade equity-grade-${holding.recommendation.grade.toLowerCase()}`}>
                      {holding.recommendation.grade} {money(holding.recommendation.score)}
                    </span>
                  </td>
                  <td><RecommendationButton holding={holding} onClick={() => setSelectedHolding(holding)} /></td>
                  <td><ReasonList rows={holding.recommendation.reasons} /></td>
                  <td><ReasonList rows={holding.recommendation.risks} mutedFallback="No major rule risk." /></td>
                  <td>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {holding.recommendation.guruSignals.map((signal) => (
                        <span key={signal.name} className={`equity-guru-chip ${signal.status}`}>{signal.name}</span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {selectedHolding ? <RecommendationReasonDialog holding={selectedHolding} onClose={() => setSelectedHolding(null)} /> : null}
      </div>
      <div className="equity-news-grid">
        {newsRows.map((item) => (
          <article key={item.symbol} className="pcr-oi-section equity-news-card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
              <strong>{item.symbol}</strong>
              <span className={`equity-sentiment-pill ${item.sentiment}`}>{item.sentiment}</span>
            </div>
            <p style={{ margin: "0 0 8px", fontSize: 13 }}>{item.summary}</p>
            {item.warning ? <p className="pcr-oi-caption" style={{ margin: "0 0 8px" }}>{item.warning}</p> : null}
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {item.headlines.slice(0, 4).map((headline, index) => (
                <a
                  key={`${headline.url || headline.title}:${index}`}
                  href={headline.url || "#"}
                  target="_blank"
                  rel="noreferrer"
                  style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 12 }}
                >
                  <span>{headline.title}</span>
                  <small className="pcr-oi-caption" style={{ margin: 0 }}>{headline.source || headline.date || "source"}</small>
                </a>
              ))}
              {!item.headlines.length ? <span className="pcr-oi-caption">No headlines cached.</span> : null}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function RecommendationButton({ holding, onClick }: { holding: EquityHolding; onClick: () => void }) {
  const symbol = holding.symbol || holding.tradingSymbol || holding.securityId;

  return (
    <button
      type="button"
      className="button secondary"
      onClick={onClick}
      aria-haspopup="dialog"
      aria-label={`Show ${symbol} recommendation reasoning`}
      style={{ fontSize: 12, padding: "4px 8px" }}
    >
      {holding.recommendation.action}
    </button>
  );
}

function RecommendationReasonDialog({ holding, onClose }: { holding: EquityHolding; onClose: () => void }) {
  const recommendation = holding.recommendation;
  const symbol = holding.symbol || holding.tradingSymbol || holding.securityId;
  const longTermGates = recommendation.longTermGates ?? [];
  const titleId = `equity-recommendation-${String(holding.id || holding.securityId || symbol).replace(/[^A-Za-z0-9_-]/g, "-")}-title`;

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div className="pcr-oi-modal-backdrop" onClick={onClose}>
      <div className="pcr-oi-modal" role="dialog" aria-modal="true" aria-labelledby={titleId} onClick={(event) => event.stopPropagation()}>
        <div className="pcr-oi-modal-head">
          <div>
            <span className="pcr-oi-caption" style={{ margin: 0 }}>{symbol}</span>
            <h3 id={titleId}>{recommendation.action}</h3>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className={`equity-grade equity-grade-${recommendation.grade.toLowerCase()}`}>
              {recommendation.grade} {money(recommendation.score)}
            </span>
            <button type="button" className="icon-button" title="Close" onClick={onClose} autoFocus>
              <X size={16} />
            </button>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10, marginBottom: 14 }}>
          <DialogMetric label="Valuation" value={`PE ${money(holding.fundamentals?.pe)} vs 3Yrs PE ${money(holding.fundamentals?.medianPe)}`} />
          <DialogMetric label="Quality" value={`ROCE ${percent(holding.fundamentals?.roce)} | D/E ${money(holding.fundamentals?.debtToEquity)}`} />
          <DialogMetric label="Trend" value={`SMA20 ${money(holding.technicals?.sma20)} | SMA50 ${money(holding.technicals?.sma50)} | SMA200 ${money(holding.technicals?.sma200)}`} />
          <DialogMetric label="News" value={holding.news?.sentiment || "neutral"} />
        </div>

        <DialogList title="Reasons" rows={recommendation.reasons} fallback="No positive recommendation rules fired." />
        <DialogList title="Risks" rows={recommendation.risks} fallback="No major rule risk." />

        {longTermGates.length ? (
          <section style={{ marginTop: 14 }}>
            <h4 style={{ margin: "0 0 8px" }}>Long-Term Gates</h4>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 8 }}>
              {longTermGates.map((gate) => (
                <div
                  key={gate.key}
                  style={{
                    border: `1px solid ${gate.passed ? "var(--green)" : "var(--red)"}`,
                    borderRadius: 8,
                    padding: 8,
                    fontSize: 12,
                  }}
                >
                  <strong style={{ color: gate.passed ? "var(--green)" : "var(--red)" }}>{gate.passed ? "Pass" : "Watch"}</strong>
                  <div>{gate.label}</div>
                  <div className="pcr-oi-caption" style={{ margin: 0 }}>{gate.detail}</div>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        {recommendation.guruSignals.length ? (
          <section style={{ marginTop: 14 }}>
            <h4 style={{ margin: "0 0 8px" }}>Guru Checks</h4>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 8 }}>
              {recommendation.guruSignals.map((signal, index) => (
                <div
                  key={`${signal.name}:${index}`}
                  style={{
                    border: `1px solid ${signal.status === "pass" ? "var(--green)" : "var(--muted)"}`,
                    borderRadius: 8,
                    padding: 8,
                    fontSize: 12,
                  }}
                >
                  <strong>{signal.name}</strong>
                  <div className="pcr-oi-caption" style={{ margin: 0 }}>{signal.detail}</div>
                </div>
              ))}
            </div>
          </section>
        ) : null}
      </div>
    </div>
  );
}

function DialogMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong style={{ fontSize: 13 }}>{value}</strong>
    </div>
  );
}

function DialogList({ title, rows, fallback }: { title: string; rows: string[]; fallback: string }) {
  return (
    <section style={{ marginTop: 10 }}>
      <h4 style={{ margin: "0 0 6px" }}>{title}</h4>
      {rows.length ? (
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
          {rows.map((row, index) => (
            <li key={`${row}:${index}`}>{row}</li>
          ))}
        </ul>
      ) : (
        <p className="pcr-oi-caption" style={{ margin: 0 }}>{fallback}</p>
      )}
    </section>
  );
}

function splitPortfolioHoldings(holdings: PortfolioRow[]): { stockHoldings: PortfolioRow[]; etfHoldings: PortfolioRow[] } {
  const stockHoldings: PortfolioRow[] = [];
  const etfHoldings: PortfolioRow[] = [];
  for (const holding of holdings) {
    if (isEtfHolding(holding)) {
      etfHoldings.push(holding);
    } else {
      stockHoldings.push(holding);
    }
  }
  return { stockHoldings, etfHoldings };
}

function isEtfHolding(holding: EquityHolding): boolean {
  const symbol = String(holding.symbol || holding.tradingSymbol || "").toUpperCase();
  const tradingSymbol = String(holding.tradingSymbol || "").toUpperCase();
  const text = `${symbol} ${tradingSymbol}`.replace(/[\s_-]+/g, "");
  return (
    text.includes("ETF") ||
    text.includes("BEES") ||
    text.includes("NIFTYETF") ||
    text.includes("SENSEXETF") ||
    text.includes("GOLDETF") ||
    text.includes("SILVERETF") ||
    text.endsWith("IETF")
  );
}

function isPotentialOrAccumulate(holding: PortfolioRow): boolean {
  const action = String(holding.recommendation?.action || "").toLowerCase();
  return action.includes("potential buy") || action.includes("accumulate");
}

function buildPortfolioRows(
  holdings: EquityHolding[],
  transactions: EquityTransaction[],
  overrides: Record<string, number> = {},
): PortfolioRow[] {
  const leastBuyByKey = new Map<string, number>();
  for (const transaction of transactions) {
    if (transaction.transactionType !== "BUY") continue;
    const price = transaction.price;
    if (price === undefined || price === null || Number.isNaN(price)) continue;
    const key = portfolioInstrumentKey(transaction.securityId, transaction.isin, transaction.symbol || transaction.tradingSymbol || transaction.customSymbol);
    if (!key) continue;
    const current = leastBuyByKey.get(key);
    if (current === undefined || price < current) {
      leastBuyByKey.set(key, price);
    }
  }

  return holdings.map((holding) => {
    const key = portfolioInstrumentKey(holding.securityId, holding.isin, holding.symbol || holding.tradingSymbol);
    // Manual override wins -- Dhan's trade-history API doesn't serve records
    // older than roughly the last 2-3 months regardless of the date range
    // requested (confirmed by testing, undocumented), so anything bought
    // before that window has no auto-detected value at all.
    const override = holding.securityId ? overrides[holding.securityId] : undefined;
    const detected = key ? leastBuyByKey.get(key) : undefined;
    const leastBuyPrice = override ?? detected;
    const ltp = holding.ltp;
    const gap = ltp !== undefined && ltp !== null && leastBuyPrice !== undefined ? round2(ltp - leastBuyPrice) : null;
    return {
      ...holding,
      leastBuyPrice: leastBuyPrice ?? null,
      isManualLowest: override !== undefined,
      priceGap: gap,
      priceGapPercent: gap !== null && leastBuyPrice ? round2((gap / leastBuyPrice) * 100) : null,
    };
  });
}

function portfolioInstrumentKey(securityId?: string | null, isin?: string | null, symbol?: string | null): string {
  if (securityId) return `security:${securityId}`;
  if (isin) return `isin:${isin.toUpperCase()}`;
  return symbol ? `symbol:${symbol.toUpperCase().replace(/\s+/g, "")}` : "";
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

function SortableHeader<Row, Key extends string>({
  column,
  sort,
  onSort,
}: {
  column: SortColumn<Row, Key>;
  sort: SortState<Key>;
  onSort: (key: Key) => void;
}) {
  const active = sort.key === column.key;
  const ariaSort = active ? (sort.direction === "asc" ? "ascending" : "descending") : "none";
  const Icon = active ? (sort.direction === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;

  return (
    <th aria-sort={ariaSort}>
      <button className={`equity-sortable-th ${active ? "active" : ""}`} type="button" onClick={() => onSort(column.key)}>
        <span>{column.label}</span>
        <Icon size={13} aria-hidden="true" />
      </button>
    </th>
  );
}

function useSortableRows<Row, Key extends string>(
  rows: Row[],
  columns: SortColumn<Row, Key>[],
  initialSort: SortState<Key>,
) {
  const [sort, setSort] = useState<SortState<Key>>(initialSort);

  const sortedRows = useMemo(() => {
    const column = columns.find((item) => item.key === sort.key);
    if (!column) return rows;
    return [...rows].sort((left, right) => compareSortValues(column.value(left), column.value(right), sort.direction));
  }, [rows, columns, sort]);

  function toggleSort(key: Key) {
    setSort((current) => ({
      key,
      direction: current.key === key && current.direction === "asc" ? "desc" : "asc",
    }));
  }

  return { sortedRows, sort, toggleSort };
}

function compareSortValues(left: SortValue, right: SortValue, direction: SortDirection): number {
  const leftEmpty = left === undefined || left === null || left === "";
  const rightEmpty = right === undefined || right === null || right === "";
  if (leftEmpty && rightEmpty) return 0;
  if (leftEmpty) return 1;
  if (rightEmpty) return -1;

  const order = compareNormalizedValues(left, right);
  return direction === "asc" ? order : -order;
}

function compareNormalizedValues(left: Exclude<SortValue, null | undefined>, right: Exclude<SortValue, null | undefined>): number {
  if (left instanceof Date || right instanceof Date) {
    const leftTime = left instanceof Date ? left.getTime() : Date.parse(String(left));
    const rightTime = right instanceof Date ? right.getTime() : Date.parse(String(right));
    if (!Number.isNaN(leftTime) && !Number.isNaN(rightTime)) return leftTime - rightTime;
  }

  if (typeof left === "number" && typeof right === "number") {
    return left - right;
  }

  if (typeof left === "boolean" || typeof right === "boolean") {
    return Number(left) - Number(right);
  }

  return String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: "base" });
}

function ReasonList({ rows, mutedFallback = "-" }: { rows: string[]; mutedFallback?: string }) {
  if (!rows.length) return <span className="pcr-oi-caption">{mutedFallback}</span>;
  return (
    <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12 }}>
      {rows.slice(0, 4).map((row) => (
        <li key={row}>{row}</li>
      ))}
    </ul>
  );
}
