"use client";

import { RefreshCcw, Save } from "lucide-react";
import { useEffect, useState } from "react";

import { getTodayJournal, saveJournal } from "@/lib/api";
import type { TodayJournalPayload } from "@/types/live";

const moneyFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });

export default function TradeJournalsPage() {
  const [payload, setPayload] = useState<TodayJournalPayload | null>(null);
  const [strategyDetails, setStrategyDetails] = useState("");
  const [lessonsLearnt, setLessonsLearnt] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const next = await getTodayJournal();
      setPayload(next);
      setStrategyDetails(next.journal.strategyDetails);
      setLessonsLearnt(next.journal.lessonsLearnt);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load journal.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleSave() {
    if (!payload) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const result = await saveJournal(payload.tradeDate, strategyDetails, lessonsLearnt);
      setPayload((current) => current ? { ...current, journal: result.journal } : current);
      setMessage("Journal saved.");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to save journal.");
    } finally {
      setSaving(false);
    }
  }

  const summary = payload?.summary;
  const dayTrades = [
    ...(payload?.snapshot.groups.closed ?? []),
    ...(payload?.snapshot.groups.equity ?? []),
    ...(payload?.snapshot.groups.optionsBuy ?? []),
    ...(payload?.snapshot.groups.optionsSell ?? []),
  ];

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>Trade Journals</h1>
          <p>{payload?.tradeDate ?? "Today"}</p>
        </div>
        <div className="toolbar">
          <button className="icon-button" type="button" title="Refresh journal" onClick={load} disabled={loading}>
            <RefreshCcw size={16} />
          </button>
          <button className="button" type="button" onClick={handleSave} disabled={saving || !payload}>
            <Save size={16} />
            Save
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {payload?.snapshot.warning ? <div className="alert warning">{payload.snapshot.warning}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}

      <div className="metric-grid">
        <Metric label="Day P&L" value={money(summary?.dayPnl)} tone={tone(summary?.dayPnl)} />
        <Metric label="Net P&L" value={money(summary?.estimatedNetPnl)} tone={tone(summary?.estimatedNetPnl)} />
        <Metric label="Charges" value={money(summary?.estimatedCharges)} />
        <Metric label="Open P&L" value={money(summary?.openPnl)} tone={tone(summary?.openPnl)} />
        <Metric label="Realized" value={money(summary?.realizedPnl)} tone={tone(summary?.realizedPnl)} />
        <Metric label="Closed" value={String(summary?.closedCount ?? 0)} />
        <Metric label="Equity" value={String(summary?.equityCount ?? 0)} />
        <Metric label="Opt Buy" value={String(summary?.optionsBuyCount ?? 0)} />
        <Metric label="Opt Sell" value={String(summary?.optionsSellCount ?? 0)} />
      </div>

      <section className="journal-grid">
        <label className="field-panel">
          <span>Strategy Details</span>
          <textarea value={strategyDetails} onChange={(event) => setStrategyDetails(event.target.value)} />
        </label>
        <label className="field-panel">
          <span>Lessons Learnt</span>
          <textarea value={lessonsLearnt} onChange={(event) => setLessonsLearnt(event.target.value)} />
        </label>
      </section>

      <section className="table-section">
        <div className="section-title">
          <h2>Day Positions</h2>
          <span>{summary?.totalPositions ?? 0}</span>
        </div>
        <div className="compact-list">
          {dayTrades.map((trade) => (
            <div className="compact-row" key={trade.id}>
              <strong>{trade.tradingSymbol || `${trade.symbol} ${trade.strikePrice ?? ""} ${trade.optionSide ?? ""}`}</strong>
              <span>{trade.status === "CLOSED" ? "CLOSED" : trade.side} {trade.status === "CLOSED" ? (trade.closedQty ?? trade.absQty) : trade.qty}</span>
              <span>{money(trade.ltp)}</span>
              <span className={tone(trade.dayPnl)}>{money(trade.dayPnl)}</span>
            </div>
          ))}
          {!loading && !summary?.totalPositions ? <div className="empty-state">No positions for the day.</div> : null}
        </div>
      </section>
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

function money(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return moneyFormat.format(value);
}

function tone(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value) || value === 0) return "";
  return value > 0 ? "positive" : "negative";
}
