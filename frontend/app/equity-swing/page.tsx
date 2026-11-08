"use client";

import { Play, RefreshCw, Save, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import CollapsibleSection from "@/components/CollapsibleSection";
import SwingRetrospectives from "@/components/SwingRetrospectives";
import ToneText from "@/components/ToneText";
import { getSwingState, rebalanceSwingNow, syncSwingData, updateSwingConfig } from "@/lib/api";
import type { SwingConfig, SwingState, SwingTrade } from "@/types/equity-swing";

const REFRESH_MS = 60_000;

function inr(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value < 0 ? "−" : ""}₹${Math.abs(value).toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function tone(value: number | null | undefined): string | undefined {
  if (!value) return undefined;
  return value > 0 ? "var(--green)" : "var(--red)";
}

function day(epoch: number | null | undefined): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "2-digit" });
}

function stamp(epoch: number): string {
  return new Date(epoch * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
}

function Metric({ label, value, caption, color }: { label: string; value: string; caption?: string; color?: string }) {
  return (
    <div className="metric metric-compact" style={{ flex: "1 1 150px" }}>
      <span>{label}</span>
      <strong style={{ color }}>{value}</strong>
      {caption ? <small className="pcr-oi-caption"><ToneText text={caption} /></small> : null}
    </div>
  );
}

export default function EquitySwingPage() {
  const [state, setState] = useState<SwingState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    try {
      setState(await getSwingState());
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load Equity-Swing.");
    }
  }

  useEffect(() => {
    void load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  async function run(label: string, fn: () => Promise<unknown>, done: string) {
    setBusy(label);
    setError(null);
    setMessage(null);
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

  const config = state?.config;
  const s = state?.summary;
  const reg = state?.regime;
  const latest = state?.latest;
  const heldSymbols = useMemo(() => new Set(state?.open.map((t) => t.symbol) ?? []), [state?.open]);

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <TrendingUp size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Equity-Swing
          </h1>
          <p>
            Weekly momentum rotation on the NIFTY 200: every Friday after the close the strongest quality stocks (1- and 3-month returns,
            adjusted for volatility, above their SMA200) are ranked; the top{" "}
            {config?.positions ?? 8} are bought at Monday&apos;s open and each is
            sold when it falls to rank {config?.exitRank ?? 20} or after {config?.maxHoldWeeks || "—"} weeks. Paper first; live orders go to Angel One.
          </p>
        </div>
        <div className="toolbar" style={{ alignItems: "center" }}>
          <span className={`status-live ${config?.mode === "live" ? "on" : ""}`} style={{ whiteSpace: "nowrap" }}>
            {config?.mode === "live" ? "LIVE (Angel One)" : "PAPER"}
          </span>
          <span className={`status-live ${config?.enabled ? "on" : ""}`}>{config?.enabled ? "Auto on" : "Auto paused"}</span>
          <button type="button" className="button secondary" onClick={load}>
            <RefreshCw size={14} /> Refresh
          </button>
          <button type="button" className="button secondary" style={{ whiteSpace: "nowrap" }} disabled={!!busy} onClick={() => run("sync", syncSwingData, "Daily candles updated.")}>
            {busy === "sync" ? "Syncing…" : "Sync prices"}
          </button>
          <button
            type="button"
            className="button"
            style={{ whiteSpace: "nowrap" }}
            disabled={!!busy}
            onClick={() => {
              if (window.confirm("Rank now and plan this week's sells/buys? Orders go in at the next session's open (or on the next poll if the market is open)."))
                void run("rank", rebalanceSwingNow, "Ranked -- the plan is below and on Telegram.");
            }}
          >
            <Play size={14} /> {busy === "rank" ? "Ranking…" : "Rank & plan now"}
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        <Metric label="Equity" value={inr(s?.equity)} caption={`capital ${inr(s?.capital)}`} />
        <Metric label="P&L" value={inr(s?.pnl)} caption={s ? `${num(s.pnlPercent)}% · realized ${inr(s.realized)}` : ""} color={tone(s?.pnl)} />
        <Metric label="Cash" value={inr(s?.cash)} caption={`invested ${inr(s?.holdingsValue)}`} />
        <Metric label="Positions" value={`${state?.open.length ?? 0} / ${config?.positions ?? 8}`} caption={s?.closedTrades ? `${s.closedTrades} closed · ${s.winRate}% winners` : "no closed trades yet"} />
        <Metric
          label="Market filter"
          value={reg?.ok ? "Buys allowed" : config?.regimeFilter ? "No new buys" : "Filter off"}
          caption={reg?.nifty && reg?.sma200 ? `NIFTY ${num(reg.nifty, 0)} vs SMA200 ${num(reg.sma200, 0)}` : "no data yet"}
          color={reg?.ok || !config?.regimeFilter ? "var(--green)" : "var(--amber)"}
        />
        <Metric label="Next ranking" value={s?.nextRebalance ?? "—"} caption={`after ${config?.rebalanceAfter ?? "16:15"} · prices to ${s?.barsSyncedFor ?? "—"}`} />
      </div>

      <CollapsibleSection id="swing-holdings" title={`Holdings (${state?.open.length ?? 0})`}>
        <TradeTable rows={state?.open ?? []} kind="open" />
      </CollapsibleSection>

      <CollapsibleSection id="swing-plan" title={`Next session (${(state?.planned.length ?? 0) + (state?.open.filter((t) => t.status === "PENDING_EXIT").length ?? 0)} orders)`}>
        {latest?.plan.note ? <div className="alert warning">{latest.plan.note}</div> : null}
        {state && !state.planned.length && !state.open.some((t) => t.status === "PENDING_EXIT") ? (
          <p className="pcr-oi-caption" style={{ margin: 0 }}>
            Nothing planned. The next ranking runs on {s?.nextRebalance} after {config?.rebalanceAfter}.
          </p>
        ) : null}
        {state?.open.filter((t) => t.status === "PENDING_EXIT").map((t) => (
          <div key={`x${t.id}`} style={{ fontSize: 13, margin: "2px 0" }}>
            <strong style={{ color: "var(--red)" }}>SELL</strong> {t.symbol} ({t.qty}) -- {t.exitReason}
          </div>
        ))}
        {state?.planned.map((t) => (
          <div key={`b${t.id}`} style={{ fontSize: 13, margin: "2px 0" }}>
            <strong style={{ color: "var(--green)" }}>BUY</strong> {t.symbol} -- {t.entryReason}
          </div>
        ))}
        {latest?.plan.skipped.length ? (
          <div className="pcr-oi-caption" style={{ marginTop: 6 }}>
            Skipped: {latest.plan.skipped.map((x) => `${x.symbol} (rank ${x.rank}: ${x.reason})`).join(" · ")}
          </div>
        ) : null}
      </CollapsibleSection>

      <CollapsibleSection
        id="swing-ranking"
        title={latest ? `Ranking ${latest.week} (${latest.eligible} of ${latest.universe} eligible)` : "Ranking"}
        defaultOpen={false}
      >
        {latest ? (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Stock</th>
                  <th>Score</th>
                  <th>1 month</th>
                  <th>3 months</th>
                  <th>Volatility</th>
                  <th>Close</th>
                  <th>vs SMA200</th>
                  <th>Gate</th>
                </tr>
              </thead>
              <tbody>
                {latest.ranking.map((r) => {
                  const gate = latest.gates[r.symbol];
                  const q = gate?.quality;
                  return (
                    <tr key={r.symbol} style={heldSymbols.has(r.symbol) ? { background: "rgba(35,104,182,0.06)" } : undefined}>
                      <td>{r.rank ?? "—"}</td>
                      <td>
                        <strong>{r.symbol}</strong> {heldSymbols.has(r.symbol) ? <span className="pcr-oi-caption">held</span> : null}
                      </td>
                      <td>{num(r.score, 3)}</td>
                      <td style={{ color: tone(r.returns["21"]) }}>{num(r.returns["21"], 1)}%</td>
                      <td style={{ color: tone(r.returns["63"]) }}>{num(r.returns["63"], 1)}%</td>
                      <td>{num(r.vol, 1)}%</td>
                      <td>{num(r.close)}</td>
                      <td>{r.sma200 ? `${num((r.close / r.sma200 - 1) * 100, 1)}%` : "—"}</td>
                      <td style={{ fontSize: 12 }}>{q === undefined ? "" : q === "pass" ? "quality ✓" : `✗ ${(q as string[]).join("; ")}`}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="pcr-oi-caption">No ranking yet. Click &quot;Rank &amp; plan now&quot;, or wait for Friday&apos;s run.</p>
        )}
      </CollapsibleSection>

      <CollapsibleSection id="swing-curve" title="Equity curve vs NIFTY">
        <EquityCurve rows={state?.equityCurve ?? []} />
      </CollapsibleSection>

      <CollapsibleSection id="swing-closed" title={`Closed trades (${state?.closed.length ?? 0})`} defaultOpen={false}>
        <TradeTable rows={state?.closed ?? []} kind="closed" />
      </CollapsibleSection>

      <CollapsibleSection id="swing-log" title="Activity log" defaultOpen={false}>
        {(state?.events ?? []).map((e) => (
          <div key={e.id} style={{ fontSize: 12, margin: "3px 0" }}>
            <span className="pcr-oi-caption">{stamp(e.time)} · {e.kind}</span> {e.text}
          </div>
        ))}
      </CollapsibleSection>

      <SwingRetrospectives onApplied={load} />

      {config ? <Settings config={config} onSaved={load} /> : null}

      <div className="pcr-oi-section">
        <h3 style={{ margin: "0 0 6px" }}>What the back-test says (₹5L, delivery costs + 0.1% slippage)</h3>
        <p className="pcr-oi-caption" style={{ margin: 0 }}>
          These settings made 31.4% a year from Jan 2022 to Oct 2026 (worst drop −19.2%, about 4-week median hold), but 21.7% a year when the
          test starts three months earlier, in Oct 2021, near a market top -- the start date matters. Random NIFTY 200 picks made far less, NIFTY
          made about 5% a year. Most of the gain came in the 2022–24 bull market; since mid-2024 it made roughly 8–10% a year, and in the last six
          months the market filter kept it out entirely (NIFTY below its SMA200). Today&apos;s NIFTY 200 list flatters every back-test and
          short-term gains are taxed at 20%, so expect less. The monthly retrospective re-checks all of this on the latest data.
        </p>
      </div>
    </section>
  );
}

function TradeTable({ rows, kind }: { rows: SwingTrade[]; kind: "open" | "closed" }) {
  if (!rows.length) return <p className="pcr-oi-caption" style={{ margin: 0 }}>{kind === "open" ? "No positions." : "No closed trades yet."}</p>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>Stock</th>
            <th>Qty</th>
            <th>Bought</th>
            <th>Buy price</th>
            <th>{kind === "open" ? "LTP" : "Sold"}</th>
            {kind === "closed" ? <th>Sell price</th> : null}
            <th>P&amp;L</th>
            <th>Held</th>
            {kind === "open" ? <th>Rank now</th> : null}
            <th>Why bought</th>
            <th>{kind === "open" ? "Status" : "Why sold"}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.id}>
              <td>
                <strong>{t.symbol}</strong>
                <div className="pcr-oi-caption">{t.industry}</div>
              </td>
              <td>{t.qty}</td>
              <td>{day(t.entryTime)}</td>
              <td>{num(t.entryPrice)}</td>
              <td>{kind === "open" ? num(t.lastPrice) : day(t.exitTime)}</td>
              {kind === "closed" ? <td>{num(t.exitPrice)}</td> : null}
              <td style={{ color: tone(t.pnl) }}>
                {inr(t.pnl)} <span className="pcr-oi-caption">({num(t.pnlPercent, 1)}%)</span>
              </td>
              <td>{t.heldWeeks != null ? `${t.heldWeeks} w` : "—"}</td>
              {kind === "open" ? <td>{t.lastRank ?? t.entryRank ?? "—"}</td> : null}
              <td style={{ fontSize: 12, maxWidth: 300 }}>{t.entryReason}</td>
              <td style={{ fontSize: 12, maxWidth: 260, color: t.status === "PENDING_EXIT" ? "var(--red)" : undefined }}>
                {kind === "open" ? (t.status === "PENDING_EXIT" ? `selling next open: ${t.exitReason}` : "holding") : t.exitReason}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EquityCurve({ rows }: { rows: SwingState["equityCurve"] }) {
  if (rows.length < 2) return <p className="pcr-oi-caption" style={{ margin: 0 }}>The curve starts after the first trading days are recorded (each evening after 15:45).</p>;
  const w = 900, h = 220, pad = 40;
  const eq0 = rows[0].equity, n0 = rows.find((r) => r.nifty)?.nifty ?? null;
  const eqs = rows.map((r) => (r.equity / eq0) * 100);
  const nfs = rows.map((r) => (r.nifty && n0 ? (r.nifty / n0) * 100 : null));
  const all = [...eqs, ...nfs.filter((x): x is number => x !== null)];
  const lo = Math.min(...all) - 1, hi = Math.max(...all) + 1;
  const x = (i: number) => pad + (i / (rows.length - 1)) * (w - pad - 10);
  const y = (v: number) => 10 + ((hi - v) / (hi - lo)) * (h - 30);
  const path = (vals: (number | null)[]) => vals.map((v, i) => (v === null ? "" : `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)).join(" ");
  return (
    <div>
      <div style={{ fontSize: 12, display: "flex", gap: 14 }}>
        <span><span style={{ color: "var(--blue)", fontWeight: 700 }}>━</span> Equity-Swing ({num(eqs[eqs.length - 1] - 100, 1)}%)</span>
        <span><span style={{ color: "var(--muted)", fontWeight: 700 }}>━</span> NIFTY 50 ({nfs[nfs.length - 1] !== null ? num((nfs[nfs.length - 1] as number) - 100, 1) : "—"}%)</span>
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ maxWidth: w }}>
        <line x1={pad} x2={w - 10} y1={y(100)} y2={y(100)} stroke="var(--line)" strokeDasharray="4 3" />
        <text x={pad - 6} y={y(100) + 4} textAnchor="end" fontSize={10} fill="var(--muted)">100</text>
        <path d={path(nfs)} fill="none" stroke="var(--muted)" strokeWidth={1.5} />
        <path d={path(eqs)} fill="none" stroke="var(--blue)" strokeWidth={2} />
        <text x={pad} y={h - 4} fontSize={10} fill="var(--muted)">{rows[0].day}</text>
        <text x={w - 10} y={h - 4} textAnchor="end" fontSize={10} fill="var(--muted)">{rows[rows.length - 1].day}</text>
      </svg>
    </div>
  );
}

const FIELDS: Array<{ key: keyof SwingConfig; label: string; hint?: string; text?: boolean }> = [
  { key: "capital", label: "Capital ₹" },
  { key: "positions", label: "Positions", hint: "back-test 8" },
  { key: "fillDepth", label: "Fill from ranks down to", hint: "when top names are blocked" },
  { key: "exitRank", label: "Sell at rank", hint: "back-test 20" },
  { key: "maxHoldWeeks", label: "Max hold (weeks)", hint: "8; 0 = no cap" },
  { key: "cooldownWeeks", label: "Cool-down after cap (weeks)", hint: "4" },
  { key: "lookbacks", label: "Lookbacks (trading days)", hint: "21,63", text: true },
  { key: "slippagePercent", label: "Paper slippage %", hint: "0.1" },
  { key: "rebalanceAfter", label: "Rank after (Fri)", hint: "16:15", text: true },
  { key: "executeAt", label: "Execute at (next day)", hint: "09:20", text: true },
];
const TOGGLES: Array<{ key: keyof SwingConfig; label: string }> = [
  { key: "enabled", label: "Automatic weekly rotation" },
  { key: "regimeFilter", label: "No new buys while NIFTY < SMA200" },
  { key: "requireSma200", label: "Only stocks above their SMA200" },
  { key: "qualityFilter", label: "Quality gate (ROCE/ROE, debt, pledge, growth)" },
  { key: "newsFilter", label: "Block company-specific bad news" },
];

function Settings({ config, onSaved }: { config: SwingConfig; onSaved: () => Promise<void> }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setDraft(Object.fromEntries(FIELDS.map((f) => [f.key, String(config[f.key] ?? "")]))), [config]);
  async function save(updates: Partial<Record<keyof SwingConfig, unknown>>) {
    setSaving(true);
    setError(null);
    try {
      await updateSwingConfig(updates as Partial<SwingConfig>);
      await onSaved();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }
  return (
    <CollapsibleSection id="swing-settings" title="Settings" defaultOpen={false}>
      {error ? <div className="alert error">{error}</div> : null}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 10 }}>
        {FIELDS.map((f) => (
          <label key={f.key} style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12 }}>
            <span>{f.label}</span>
            <input value={draft[f.key] ?? ""} onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })} />
            {f.hint ? <small className="pcr-oi-caption">{f.hint}</small> : null}
          </label>
        ))}
      </div>
      <button
        type="button"
        className="button"
        style={{ marginTop: 10 }}
        disabled={saving}
        onClick={() => save(Object.fromEntries(FIELDS.map((f) => [f.key, f.text ? draft[f.key] : Number(draft[f.key])])))}
      >
        <Save size={14} /> Save
      </button>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16, marginTop: 12, fontSize: 13 }}>
        {TOGGLES.map((t) => (
          <label key={t.key} style={{ display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
            <input type="checkbox" checked={Boolean(config[t.key])} disabled={saving} onChange={(e) => save({ [t.key]: e.target.checked })} />
            {t.label}
          </label>
        ))}
      </div>
      <div style={{ marginTop: 12, fontSize: 13 }}>
        Mode:{" "}
        <select value={config.mode} disabled={saving} onChange={(e) => save({ mode: e.target.value })}>
          <option value="paper">Paper</option>
          <option value="live" disabled={!config.liveOrdersAllowed || !config.angelConfigured}>
            Live (Angel One)
          </option>
        </select>{" "}
        <span className="pcr-oi-caption">
          {!config.angelConfigured
            ? "Angel One credentials are not on the server yet."
            : !config.liveOrdersAllowed
              ? "Live orders are switched off on the server (EQUITY_SWING_LIVE_ORDER_ENABLED)."
              : "Live orders allowed."}
        </span>
      </div>
    </CollapsibleSection>
  );
}
