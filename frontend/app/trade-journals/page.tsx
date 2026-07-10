"use client";

import { RefreshCcw, Save, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { getJournalInsights, getRecentJournalSessions, refreshJournalInsights, saveJournalEntry } from "@/lib/api";
import type { Journal, JournalInsights, JournalSession } from "@/types/live";

const moneyFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const WEEKDAY_FORMAT = new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "2-digit", month: "short" });

type DraftFields = Pick<Journal, "strategyDetails" | "howIFelt" | "whatHappened" | "lessonsLearnt" | "comments">;

export default function TradeJournalsPage() {
  const [sessions, setSessions] = useState<JournalSession[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [draft, setDraft] = useState<DraftFields>(emptyDraft());
  const [insights, setInsights] = useState<JournalInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [refreshingInsights, setRefreshingInsights] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [sessionsPayload, insightsPayload] = await Promise.all([getRecentJournalSessions(), getJournalInsights()]);
      setSessions(sessionsPayload.sessions);
      setInsights(insightsPayload);
      const fallbackDate = sessionsPayload.sessions[sessionsPayload.sessions.length - 1]?.tradeDate ?? null;
      setSelectedDate((current) => current ?? fallbackDate);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load trade journals.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    const session = sessions.find((item) => item.tradeDate === selectedDate);
    setDraft(session ? draftFromJournal(session.journal) : emptyDraft());
  }, [selectedDate, sessions]);

  async function handleSave() {
    if (!selectedDate) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const result = await saveJournalEntry(selectedDate, draft);
      setSessions((current) => current.map((item) => (item.tradeDate === selectedDate ? { ...item, journal: result.journal } : item)));
      setMessage(`${selectedDate} journal saved.`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to save journal.");
    } finally {
      setSaving(false);
    }
  }

  async function handleRefreshInsights() {
    setRefreshingInsights(true);
    setError(null);
    try {
      setInsights(await refreshJournalInsights());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to refresh insights.");
    } finally {
      setRefreshingInsights(false);
    }
  }

  const selectedSession = useMemo(() => sessions.find((item) => item.tradeDate === selectedDate) ?? null, [sessions, selectedDate]);

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>Trade Journals</h1>
          <p>Last 7 trading sessions</p>
        </div>
        <div className="toolbar">
          <button className="icon-button" type="button" title="Refresh" onClick={load} disabled={loading}>
            <RefreshCcw size={16} />
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}

      <section className="alert success journal-insights">
        <div className="journal-insights-header">
          <strong>
            <Sparkles size={15} /> AI Lessons Reminder
          </strong>
          <button className="icon-button" type="button" title="Refresh insights now" onClick={handleRefreshInsights} disabled={refreshingInsights}>
            <RefreshCcw size={14} />
          </button>
        </div>
        {insights?.bullets.length ? (
          <ul className="journal-insights-list">
            {insights.bullets.map((bullet) => (
              <li key={bullet}>{bullet}</li>
            ))}
          </ul>
        ) : (
          <p className="subtext">No insights yet — write a few journal entries, then refresh.</p>
        )}
        {insights?.generatedAt ? <span className="subtext">Updated {insights.generatedAt}</span> : null}
      </section>

      <div className="journal-day-tabs">
        {sessions.map((session) => (
          <button
            key={session.tradeDate}
            type="button"
            className={`journal-day-tab ${session.tradeDate === selectedDate ? "active" : ""}`}
            onClick={() => setSelectedDate(session.tradeDate)}
          >
            <span className="journal-day-date">{formatWeekday(session.tradeDate)}</span>
            <span className="subtext">{session.summary ? `${session.summary.tradesCount} trades` : "No data"}</span>
            <span className={tone(session.summary?.dayPnl)}>{money(session.summary?.dayPnl)}</span>
          </button>
        ))}
      </div>

      {selectedSession ? (
        <>
          <div className="metric-grid">
            <Metric label="Date" value={selectedSession.tradeDate} />
            <Metric label="Trades" value={String(selectedSession.summary?.tradesCount ?? 0)} />
            <Metric label="Day P&L" value={money(selectedSession.summary?.dayPnl)} tone={tone(selectedSession.summary?.dayPnl)} />
            <Metric label="Net P&L" value={money(selectedSession.summary?.netPnl)} tone={tone(selectedSession.summary?.netPnl)} />
            <Metric label="Charges" value={money(selectedSession.summary?.charges)} />
          </div>

          <section className="journal-grid">
            <label className="field-panel">
              <span>Strategy</span>
              <textarea value={draft.strategyDetails} onChange={(event) => updateDraft("strategyDetails", event.target.value)} />
            </label>
            <label className="field-panel">
              <span>How I felt</span>
              <textarea value={draft.howIFelt} onChange={(event) => updateDraft("howIFelt", event.target.value)} />
            </label>
            <label className="field-panel">
              <span>What happened</span>
              <textarea value={draft.whatHappened} onChange={(event) => updateDraft("whatHappened", event.target.value)} />
            </label>
            <label className="field-panel">
              <span>Lessons Learnt</span>
              <textarea value={draft.lessonsLearnt} onChange={(event) => updateDraft("lessonsLearnt", event.target.value)} />
            </label>
            <label className="field-panel">
              <span>Comments</span>
              <textarea value={draft.comments} onChange={(event) => updateDraft("comments", event.target.value)} />
            </label>
          </section>

          <div className="toolbar">
            <button className="button" type="button" onClick={handleSave} disabled={saving}>
              <Save size={16} />
              Save {selectedSession.tradeDate}
            </button>
          </div>
        </>
      ) : !loading ? (
        <div className="empty-state">No sessions available.</div>
      ) : null}
    </section>
  );

  function updateDraft(key: keyof DraftFields, value: string) {
    setDraft((current) => ({ ...current, [key]: value }));
  }
}

function Metric({ label, value, tone: metricTone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={metricTone}>{value}</strong>
    </div>
  );
}

function draftFromJournal(journal: Journal): DraftFields {
  return {
    strategyDetails: journal.strategyDetails,
    howIFelt: journal.howIFelt,
    whatHappened: journal.whatHappened,
    lessonsLearnt: journal.lessonsLearnt,
    comments: journal.comments,
  };
}

function emptyDraft(): DraftFields {
  return { strategyDetails: "", howIFelt: "", whatHappened: "", lessonsLearnt: "", comments: "" };
}

function formatWeekday(isoDate: string): string {
  const parsed = new Date(`${isoDate}T00:00:00`);
  return WEEKDAY_FORMAT.format(parsed);
}

function money(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return moneyFormat.format(value);
}

function tone(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value) || value === 0) return "";
  return value > 0 ? "positive" : "negative";
}
