"use client";

import { BellRing, Plus, RefreshCw, Send } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { alertTitle } from "@/components/GlobalAlerts";
import { alertAction, createAlert, getAlerts, getEquityPortfolio, testTelegram } from "@/lib/api";
import type { AlertsPayload, PortalAlert } from "@/types/alerts";
import type { EquityHolding } from "@/types/equity";

function ist(epoch: number | null | undefined): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
  });
}

function localDateTimeValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export default function AlertsPage() {
  const [data, setData] = useState<AlertsPayload | null>(null);
  const [holdings, setHoldings] = useState<EquityHolding[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  // price alert form
  const [securityId, setSecurityId] = useState("");
  const [direction, setDirection] = useState<"below" | "above">("below");
  const [price, setPrice] = useState("");
  const [priceNote, setPriceNote] = useState("");
  // reminder form
  const [remindAt, setRemindAt] = useState(localDateTimeValue(new Date(Date.now() + 24 * 3600 * 1000)));
  const [reminderSymbol, setReminderSymbol] = useState("");
  const [reminderNote, setReminderNote] = useState("");

  async function load() {
    try {
      setData(await getAlerts());
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load alerts.");
    }
  }

  useEffect(() => {
    void load();
    void getEquityPortfolio(false)
      .then((p) => setHoldings(p.data))
      .catch(() => undefined);
    const timer = window.setInterval(load, 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const selected = useMemo(() => holdings.find((h) => h.securityId === securityId), [holdings, securityId]);
  const sortedHoldings = useMemo(() => [...holdings].sort((a, b) => a.symbol.localeCompare(b.symbol)), [holdings]);

  async function run(label: string, fn: () => Promise<unknown>, done: string) {
    setBusy(label);
    setMessage(null);
    setError(null);
    try {
      await fn();
      setMessage(done);
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Request failed.");
    } finally {
      setBusy(null);
    }
  }

  async function addPrice() {
    if (!selected || !Number(price)) {
      setError("Pick a stock and a price.");
      return;
    }
    await run(
      "price",
      () => createAlert({ kind: "price", symbol: selected.symbol, securityId: selected.securityId, segment: selected.exchangeSegment ?? "NSE_EQ", direction, price: Number(price), note: priceNote || undefined }),
      `Alert set: ${selected.symbol} ${direction} ${Number(price).toLocaleString("en-IN")}.`,
    );
    setPrice("");
    setPriceNote("");
  }

  async function addReminder() {
    const when = Math.floor(new Date(remindAt).getTime() / 1000);
    if (!when || !reminderNote.trim()) {
      setError("A reminder needs a date/time and a message.");
      return;
    }
    await run("reminder", () => createAlert({ kind: "reminder", remindAt: when, note: reminderNote.trim(), symbol: reminderSymbol || undefined }), `Reminder set for ${ist(when)}.`);
    setReminderNote("");
  }

  const tg = data?.telegram;
  const tgOk = tg?.tokenSet && tg?.chatIdSource && tg?.lastOk !== false;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <BellRing size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Alerts &amp; Reminders
          </h1>
          <p>
            Price alerts on your holdings (checked every 30 s in market hours on live Dhan prices) and date reminders. When one fires you get a
            Telegram message and a full-screen alarm on whichever page of the portal is open, until you acknowledge it.
          </p>
        </div>
        <div className="toolbar">
          <button type="button" className="button secondary" onClick={load}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}

      <div className="pcr-oi-section">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div>
            <h3 style={{ margin: 0 }}>Telegram</h3>
            <p className="pcr-oi-caption" style={{ margin: "2px 0 0" }}>
              {!tg
                ? "Loading…"
                : !tg.tokenSet
                  ? "No bot token on the server (TELEGRAM_BOT_TOKEN)."
                  : !tg.chatIdSource
                    ? `Not connected yet: open Telegram, send /start to @${tg.botUsername ?? "the bot"}, then click "Send test message".`
                    : tg.lastOk === false
                      ? `Last send failed: ${tg.lastError ?? "unknown error"}`
                      : `Connected (chat id ${tg.chatIdSource === "env" ? "from server settings" : "remembered"})${tg.lastAt ? ` · last message ${ist(tg.lastAt)}` : ""}.`}
            </p>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span className={`status-live ${tgOk ? "on" : ""}`}>{tgOk ? "Connected" : "Not connected"}</span>
            <button
              type="button"
              className="button"
              disabled={busy === "tg"}
              onClick={() =>
                run("tg", async () => {
                  const r = await testTelegram();
                  if (!r.sent) throw new Error(`Telegram test not sent: ${r.lastError ?? "unknown error"}`);
                }, "Test message sent -- check Telegram.")
              }
            >
              <Send size={14} /> Send test message
            </button>
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))", gap: 16 }}>
        <div className="pcr-oi-section">
          <h3 style={{ margin: "0 0 8px" }}>New price alert</h3>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <select value={securityId} onChange={(e) => setSecurityId(e.target.value)} style={{ minWidth: 150 }}>
              <option value="">Stock…</option>
              {sortedHoldings.map((h) => (
                <option key={h.securityId} value={h.securityId}>
                  {h.symbol}
                </option>
              ))}
            </select>
            <select value={direction} onChange={(e) => setDirection(e.target.value as "below" | "above")}>
              <option value="below">falls to or below</option>
              <option value="above">rises to or above</option>
            </select>
            <input type="number" step="0.05" placeholder="Price" value={price} onChange={(e) => setPrice(e.target.value)} style={{ width: 110 }} />
          </div>
          {selected ? (
            <p className="pcr-oi-caption" style={{ margin: "6px 0 0" }}>
              {selected.symbol} LTP {selected.ltp?.toLocaleString("en-IN") ?? "—"}
              {selected.entrySignal?.buyBelow ? ` · buy zone below ${selected.entrySignal.buyBelow.toLocaleString("en-IN")}` : ""}
              {selected.entrySignal?.nextAddBelow ? ` · next add below ${selected.entrySignal.nextAddBelow.toLocaleString("en-IN")}` : ""}
            </p>
          ) : null}
          <input placeholder="Note (optional), e.g. add 1/3 position" value={priceNote} onChange={(e) => setPriceNote(e.target.value)} style={{ width: "100%", marginTop: 8 }} />
          <button type="button" className="button" style={{ marginTop: 8 }} disabled={busy === "price"} onClick={addPrice}>
            <Plus size={14} /> Add price alert
          </button>
        </div>

        <div className="pcr-oi-section">
          <h3 style={{ margin: "0 0 8px" }}>New reminder</h3>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <input type="datetime-local" value={remindAt} onChange={(e) => setRemindAt(e.target.value)} />
            <select value={reminderSymbol} onChange={(e) => setReminderSymbol(e.target.value)}>
              <option value="">No stock</option>
              {sortedHoldings.map((h) => (
                <option key={h.securityId} value={h.symbol}>
                  {h.symbol}
                </option>
              ))}
            </select>
          </div>
          <textarea
            placeholder="What to remind you about, e.g. check ITC Q2 results before adding"
            value={reminderNote}
            onChange={(e) => setReminderNote(e.target.value)}
            rows={3}
            style={{ width: "100%", marginTop: 8 }}
          />
          <button type="button" className="button" style={{ marginTop: 8 }} disabled={busy === "reminder"} onClick={addReminder}>
            <Plus size={14} /> Add reminder
          </button>
        </div>
      </div>

      <AlertTable
        title={`Fired -- waiting for you (${data?.pending.length ?? 0})`}
        rows={data?.pending ?? []}
        empty="Nothing waiting."
        actions={(a) => (
          <button type="button" className="button" onClick={() => run(`ack-${a.id}`, () => alertAction(a.id, "acknowledge"), "Acknowledged.")}>
            Acknowledge
          </button>
        )}
      />
      <AlertTable
        title={`Active (${data?.active.length ?? 0})`}
        rows={data?.active ?? []}
        empty="No active alerts or reminders."
        actions={(a) => (
          <button type="button" className="button secondary" onClick={() => run(`dis-${a.id}`, () => alertAction(a.id, "dismiss"), "Alert switched off.")}>
            Cancel
          </button>
        )}
      />
      <AlertTable
        title="History"
        rows={data?.history ?? []}
        empty="No history yet."
        actions={(a) => (
          <button type="button" className="button secondary" onClick={() => run(`re-${a.id}`, () => alertAction(a.id, "rearm"), "Alert re-armed.")}>
            Re-arm
          </button>
        )}
      />
    </section>
  );
}

function AlertTable({ title, rows, empty, actions }: { title: string; rows: PortalAlert[]; empty: string; actions: (a: PortalAlert) => React.ReactNode }) {
  return (
    <div className="pcr-oi-section">
      <h3 style={{ margin: "0 0 8px" }}>{title}</h3>
      <div style={{ overflowX: "auto" }}>
        <table>
          <thead>
            <tr>
              <th>Alert</th>
              <th>When / level</th>
              <th>Note</th>
              <th>Created</th>
              <th>Fired</th>
              <th>Telegram</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id}>
                <td>
                  <strong>{a.kind === "price" ? "🔔 " : "⏰ "}{alertTitle(a)}</strong>
                  {a.source === "entry_signal" ? <div className="pcr-oi-caption">from Entry signals</div> : null}
                </td>
                <td>{a.kind === "price" ? `${a.direction} ${a.price?.toLocaleString("en-IN")}` : ist(a.remindAt)}</td>
                <td style={{ maxWidth: 360 }}>{a.note ?? "—"}</td>
                <td>{ist(a.createdAt)}</td>
                <td>{a.triggeredAt ? `${ist(a.triggeredAt)}${a.triggerPrice ? ` @ ${a.triggerPrice.toLocaleString("en-IN")}` : ""}` : "—"}</td>
                <td>{a.telegramSent === null || a.telegramSent === undefined ? "—" : a.telegramSent ? "sent" : "not sent"}</td>
                <td>{a.status}</td>
                <td>{actions(a)}</td>
              </tr>
            ))}
            {!rows.length ? (
              <tr>
                <td colSpan={8} className="pcr-oi-caption">
                  {empty}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
