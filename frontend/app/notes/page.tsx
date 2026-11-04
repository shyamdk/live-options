"use client";

import { NotebookPen, Pencil, RefreshCw, Save, Search, Sparkles, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import CollapsibleSection from "@/components/CollapsibleSection";
import { createNote, deleteNote, getNotes, getNotesSummary, refreshNotesSummary, updateNote } from "@/lib/api";
import type { Note, NoteInput, NotesSummary } from "@/types/notes";

function todayIst(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
}

function dayLabel(day: string): string {
  return new Date(`${day}T12:00:00+05:30`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}

function stamp(epoch: number): string {
  return new Date(epoch * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
}

const parseTags = (text: string) => text.split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);
const emptyDraft = (): NoteInput & { tagText: string } => ({ day: todayIst(), title: "", body: "", tags: [], tagText: "" });

export default function NotesPage() {
  const [notes, setNotes] = useState<Note[]>([]);
  const [summary, setSummary] = useState<NotesSummary | null>(null);
  const [draft, setDraft] = useState(emptyDraft());
  const [editingId, setEditingId] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const [n, s] = await Promise.all([getNotes(), getNotesSummary()]);
      setNotes(n.notes);
      setSummary(s);
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load notes.");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function save() {
    if (!draft.body.trim()) return;
    setBusy("save");
    try {
      const body: NoteInput = { day: draft.day, title: draft.title, body: draft.body, tags: parseTags(draft.tagText) };
      if (editingId) await updateNote(editingId, body);
      else await createNote(body);
      setDraft(emptyDraft());
      setEditingId(null);
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Save failed.");
    } finally {
      setBusy(null);
    }
  }

  function edit(note: Note) {
    setEditingId(note.id);
    setDraft({ day: note.day, title: note.title, body: note.body, tags: note.tags, tagText: note.tags.join(", ") });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function remove(note: Note) {
    if (!window.confirm(`Delete the note from ${dayLabel(note.day)}${note.title ? ` ("${note.title}")` : ""}?`)) return;
    setBusy(`del-${note.id}`);
    try {
      await deleteNote(note.id);
      if (editingId === note.id) {
        setEditingId(null);
        setDraft(emptyDraft());
      }
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Delete failed.");
    } finally {
      setBusy(null);
    }
  }

  async function refresh() {
    setBusy("summary");
    try {
      setSummary(await refreshNotesSummary());
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Summary failed.");
    } finally {
      setBusy(null);
    }
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return notes.filter(
      (n) => (!tagFilter || n.tags.includes(tagFilter)) && (!q || `${n.title} ${n.body} ${n.tags.join(" ")}`.toLowerCase().includes(q)),
    );
  }, [notes, query, tagFilter]);

  const byDay = useMemo(() => {
    const groups = new Map<string, Note[]>();
    for (const n of filtered) groups.set(n.day, [...(groups.get(n.day) ?? []), n]);
    return [...groups.entries()];
  }, [filtered]);

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <NotebookPen size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Notes
          </h1>
          <p>Notes and learnings by date. The summary on top is built from your notes only, when you press Refresh summary.</p>
        </div>
        <div className="toolbar" style={{ alignItems: "center" }}>
          <button type="button" className="button secondary" onClick={load} style={{ whiteSpace: "nowrap" }}>
            <RefreshCw size={14} /> Reload
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}

      <SummaryPanel summary={summary} busy={busy === "summary"} onRefresh={refresh} onTag={setTagFilter} />

      <section className="table-section">
        <div className="section-title">
          <h2>{editingId ? `Edit note #${editingId}` : "New note"}</h2>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12 }}>
            <span style={{ color: "var(--muted)", fontWeight: 600 }}>Date</span>
            <input type="date" value={draft.day} onChange={(e) => setDraft((d) => ({ ...d, day: e.target.value }))} style={{ fontSize: 13, padding: "3px 6px" }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12, flex: "2 1 220px" }}>
            <span style={{ color: "var(--muted)", fontWeight: 600 }}>Title (optional)</span>
            <input value={draft.title} onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))} placeholder="e.g. Calm Strangle loss on gap day" style={{ fontSize: 13, padding: "3px 6px" }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12, flex: "1 1 180px" }}>
            <span style={{ color: "var(--muted)", fontWeight: 600 }}>Tags (comma separated)</span>
            <input value={draft.tagText} onChange={(e) => setDraft((d) => ({ ...d, tagText: e.target.value }))} placeholder="nifty, discipline" style={{ fontSize: 13, padding: "3px 6px" }} />
          </label>
        </div>
        <textarea
          value={draft.body}
          onChange={(e) => setDraft((d) => ({ ...d, body: e.target.value }))}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) save();
          }}
          placeholder="What happened, what you learnt, what to do differently…"
          rows={6}
          style={{ width: "100%", boxSizing: "border-box", fontSize: 14, padding: 8, fontFamily: "inherit", lineHeight: 1.5 }}
        />
        <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center", flexWrap: "wrap" }}>
          <button type="button" className="button" onClick={save} disabled={busy === "save" || !draft.body.trim()}>
            <Save size={14} /> {editingId ? "Save changes" : "Add note"}
          </button>
          {editingId ? (
            <button type="button" className="button secondary" onClick={() => (setEditingId(null), setDraft(emptyDraft()))}>
              <X size={14} /> Cancel
            </button>
          ) : null}
          <span className="pcr-oi-caption">⌘/Ctrl + Enter to save</span>
        </div>
      </section>

      <section className="table-section">
        <div className="section-title" style={{ flexWrap: "wrap", gap: 8 }}>
          <h2>All notes</h2>
          <span>{filtered.length}</span>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: "auto" }}>
            <Search size={14} />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search notes" style={{ fontSize: 13, padding: "3px 6px", width: 180 }} />
            {tagFilter ? (
              <button type="button" className="badge" onClick={() => setTagFilter(null)} title="Clear tag filter" style={{ cursor: "pointer" }}>
                #{tagFilter} ✕
              </button>
            ) : null}
          </div>
        </div>
        {!byDay.length ? <div className="empty-state">{notes.length ? "No notes match." : "No notes yet -- add your first one above."}</div> : null}
        {byDay.map(([day, items]) => (
          <div key={day} style={{ marginBottom: 14 }}>
            <h3 style={{ fontSize: 13, color: "var(--muted)", margin: "10px 0 6px", fontWeight: 600 }}>{dayLabel(day)}</h3>
            {items.map((n) => (
              <article key={n.id} className="metric" style={{ display: "block", marginBottom: 8, padding: "10px 12px" }}>
                <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                  {n.title ? <strong style={{ fontSize: 14 }}>{n.title}</strong> : null}
                  {n.tags.map((t) => (
                    <button key={t} type="button" className="badge" onClick={() => setTagFilter(t)} style={{ cursor: "pointer" }}>
                      #{t}
                    </button>
                  ))}
                  <span className="pcr-oi-caption" style={{ marginLeft: "auto" }}>
                    {n.updatedAt !== n.createdAt ? `edited ${stamp(n.updatedAt)}` : stamp(n.createdAt)}
                  </span>
                  <button type="button" className="icon-button" title="Edit" onClick={() => edit(n)}>
                    <Pencil size={14} />
                  </button>
                  <button type="button" className="icon-button" title="Delete" onClick={() => remove(n)} disabled={busy === `del-${n.id}`}>
                    <Trash2 size={14} />
                  </button>
                </div>
                <div style={{ whiteSpace: "pre-wrap", fontSize: 14, lineHeight: 1.55, marginTop: 6 }}>{n.body}</div>
              </article>
            ))}
          </div>
        ))}
      </section>
    </section>
  );
}

function SummaryPanel({ summary, busy, onRefresh, onTag }: { summary: NotesSummary | null; busy: boolean; onRefresh: () => void; onTag: (t: string) => void }) {
  if (!summary) return null;
  const { stats, digest } = summary;
  const list = (title: string, items: string[]) =>
    items.length ? (
      <div style={{ flex: "1 1 280px" }}>
        <h3 style={{ fontSize: 13, margin: "8px 0 4px" }}>{title}</h3>
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 14, lineHeight: 1.5 }}>
          {items.map((x, i) => (
            <li key={i}>{x}</li>
          ))}
        </ul>
      </div>
    ) : null;
  return (
    <CollapsibleSection
      id="notes-summary"
      title="Summary"
      aside={
        <button type="button" className="button secondary" onClick={onRefresh} disabled={busy || !summary.aiAvailable || !stats.notes} style={{ whiteSpace: "nowrap" }}>
          <Sparkles size={14} /> {busy ? "Summarising…" : "Refresh summary"}
        </button>
      }
    >
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
        <div className="metric metric-compact" style={{ flex: "1 1 130px" }}>
          <span>Notes</span>
          <strong>{stats.notes}</strong>
          <span className="pcr-oi-caption">on {stats.days} days</span>
        </div>
        <div className="metric metric-compact" style={{ flex: "1 1 130px" }}>
          <span>Span</span>
          <strong style={{ fontSize: 15 }}>{stats.first ? `${stats.first} → ${stats.last}` : "—"}</strong>
        </div>
        <div className="metric metric-compact" style={{ flex: "2 1 260px" }}>
          <span>By month</span>
          <strong style={{ fontSize: 13, fontWeight: 500 }}>{stats.byMonth.map((m) => `${m.month}: ${m.count}`).join(" · ") || "—"}</strong>
        </div>
      </div>
      {stats.topTags.length ? (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
          {stats.topTags.map((t) => (
            <button key={t.tag} type="button" className="badge" onClick={() => onTag(t.tag)} style={{ cursor: "pointer" }}>
              #{t.tag} · {t.count}
            </button>
          ))}
        </div>
      ) : null}
      {!summary.aiAvailable ? <div className="pcr-oi-caption">AI summary needs OPENAI_API_KEY on the server.</div> : null}
      {digest ? (
        <>
          {digest.stale ? <div className="alert warning">Notes have changed since this summary -- press Refresh summary to update it.</div> : null}
          {digest.overview ? <p style={{ fontSize: 14, lineHeight: 1.55, margin: "4px 0 6px" }}>{digest.overview}</p> : null}
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
            {list("Key learnings", digest.keyLearnings)}
            {list("My rules", digest.rules)}
            {list("Recurring mistakes", digest.recurringMistakes)}
            {list("Open questions / to check", digest.openQuestions)}
          </div>
          <div className="pcr-oi-caption" style={{ marginTop: 8 }}>
            Generated {stamp(digest.generatedAt)} from {digest.notesUsed} of {digest.noteCount} notes ({digest.model}). Built only from your notes -- check it against them.
          </div>
        </>
      ) : stats.notes ? (
        <div className="pcr-oi-caption">No summary yet -- press Refresh summary.</div>
      ) : null}
    </CollapsibleSection>
  );
}
