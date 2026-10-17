"use client";

import { RotateCcw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import CollapsibleSection from "@/components/CollapsibleSection";
import { applySwingRetro, getSwingRetros, startSwingRetro } from "@/lib/api";
import type { SwingRetro } from "@/types/equity-swing";

function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

function inr(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${v < 0 ? "−" : ""}₹${Math.abs(Math.round(v)).toLocaleString("en-IN")}`;
}

function when(epoch: number): string {
  return new Date(epoch * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
}

/**
 * Retrospectives: review what happened, re-test the settings on the latest
 * data, and suggest a change only when it beats the current setting on both
 * the full history and the last ~6 months. Runs monthly and on demand.
 */
export default function SwingRetrospectives({ onApplied }: { onApplied: () => Promise<void> }) {
  const [retros, setRetros] = useState<SwingRetro[]>([]);
  const [running, setRunning] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const poll = useRef<number | null>(null);

  async function load() {
    try {
      const r = await getSwingRetros();
      setRetros(r.retros);
      setRunning(r.running);
      return r.running;
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load retrospectives.");
      return null;
    }
  }

  useEffect(() => {
    void load();
    return () => {
      if (poll.current) window.clearInterval(poll.current);
    };
  }, []);

  async function start() {
    setError(null);
    setMessage(null);
    try {
      await startSwingRetro();
      setRunning(Math.floor(Date.now() / 1000));
      if (poll.current) window.clearInterval(poll.current);
      poll.current = window.setInterval(async () => {
        const still = await load();
        if (!still && poll.current) {
          window.clearInterval(poll.current);
          poll.current = null;
          setSelected(null);
          setMessage("Retrospective finished -- see the results below (also sent on Telegram).");
        }
      }, 4000);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to start.");
    }
  }

  async function apply(r: SwingRetro, label: string) {
    if (!window.confirm(`Apply "${label}" to Equity-Swing? It takes effect from the next weekly ranking.`)) return;
    try {
      await applySwingRetro(r.id, label);
      setMessage(`Applied ${label}.`);
      await load();
      await onApplied();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Apply failed.");
    }
  }

  const current = retros.find((r) => r.id === selected) ?? retros[0];

  return (
    <CollapsibleSection
      id="swing-retros"
      title={`Retrospectives (${retros.length})`}
      aside={
        <button type="button" className="button" onClick={start} disabled={!!running} style={{ whiteSpace: "nowrap" }}>
          <RotateCcw size={14} /> {running ? "Running…" : "Run retrospective"}
        </button>
      }
    >
      <p className="pcr-oi-caption" style={{ margin: "0 0 8px" }}>
        Runs automatically on the first trading day of each month, or now with the button. It reviews the real trades, re-runs the back-test
        for the current settings and nearby alternatives on the full stored history and the last ~6 months, and suggests a change only when it
        beats the current setting by 2+ points a year on <strong>both</strong>. Nothing changes until you click Apply.
      </p>
      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}
      {!current ? <p className="pcr-oi-caption">No retrospective yet.</p> : <RetroView retro={current} onApply={(label) => apply(current, label)} />}
      {retros.length > 1 ? (
        <div style={{ marginTop: 14 }}>
          <strong style={{ fontSize: 13 }}>History</strong>
          <table style={{ marginTop: 4 }}>
            <thead>
              <tr>
                <th>#</th>
                <th>Date</th>
                <th>Run</th>
                <th>Back-test a year</th>
                <th>Since start vs NIFTY</th>
                <th>Suggestions</th>
                <th>Applied</th>
              </tr>
            </thead>
            <tbody>
              {retros.map((r) => (
                <tr key={r.id} onClick={() => setSelected(r.id)} style={{ cursor: "pointer", fontWeight: r.id === current?.id ? 600 : undefined }}>
                  <td>{r.id}</td>
                  <td>{when(r.createdAt)}</td>
                  <td>{r.trigger}</td>
                  <td>{pct(r.retest.current?.full.cagr)}</td>
                  <td>{r.review.sinceStart ? `${pct(r.review.sinceStart.strategy)} vs ${pct(r.review.sinceStart.nifty)}` : "—"}</td>
                  <td>{(r.retest.variants ?? []).filter((v) => v.suggest).length || "none"}</td>
                  <td>{r.decisions.map((d) => d.applied).join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </CollapsibleSection>
  );
}

function RetroView({ retro, onApply }: { retro: SwingRetro; onApply: (label: string) => void }) {
  const rv = retro.review;
  const t = retro.retest;
  const applied = new Set(retro.decisions.map((d) => d.applied));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="pcr-oi-caption">
        #{retro.id} · {when(retro.createdAt)} · {retro.trigger}
      </div>
      <div>
        <strong style={{ fontSize: 13 }}>What happened</strong>
        <div className="gb-status-row" style={{ marginTop: 4 }}>
          <span>{rv.closedTrades} closed trades · {rv.openPositions} open</span>
          <span>Realized {inr(rv.realized)}</span>
          <span>Winners {rv.winRate ?? "—"}%</span>
          <span>Avg win {inr(rv.avgWin)} / loss {inr(rv.avgLoss)}</span>
          <span>Median hold {rv.medianHoldWeeks ?? "—"} weeks</span>
          {rv.sinceStart ? (
            <span>
              Since {rv.sinceStart.from}: <strong>{pct(rv.sinceStart.strategy)}</strong> vs NIFTY {pct(rv.sinceStart.nifty)}
            </span>
          ) : null}
        </div>
        {rv.closedTrades ? (
          <div className="pcr-oi-caption" style={{ marginTop: 4 }}>
            {(["byExit", "byEntryRank", "bySector"] as const).map((k) => (
              <div key={k}>
                {k === "byExit" ? "By exit" : k === "byEntryRank" ? "By entry rank" : "By sector"}:{" "}
                {Object.entries(rv[k]).map(([name, g]) => `${name} ${g.trades} trades ${inr(g.pnl)} (${g.winRate}% win)`).join(" · ")}
              </div>
            ))}
          </div>
        ) : null}
      </div>
      {t.error ? (
        <div className="alert warning">{t.error}</div>
      ) : t.current ? (
        <div>
          <strong style={{ fontSize: 13 }}>Re-test on the latest data</strong>
          <p className="pcr-oi-caption" style={{ margin: "2px 0 6px" }}>
            Full history {t.window?.from} → {t.window?.to}: current settings {pct(t.current.full.cagr)} a year (worst drop{" "}
            {pct(t.current.full.maxDrawdown)}), NIFTY {pct(t.current.full.niftyCagr)}, random picks under the same rules {pct(t.random?.median)} (
            {pct(t.random?.min)} to {pct(t.random?.max)}). Last ~6 months from {t.window?.recentFrom}: {pct(t.current.recent.cagr)} annualised.
          </p>
          {t.recentNote ? <div className="alert warning" style={{ margin: "4px 0" }}>{t.recentNote}</div> : null}
          <table>
            <thead>
              <tr>
                <th>Change</th>
                <th>Full history</th>
                <th>vs current</th>
                <th>Last ~6 months</th>
                <th>vs current</th>
                <th>Worst drop</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(t.variants ?? []).map((v) => (
                <tr key={v.label} style={v.suggest ? { background: "rgba(22,132,72,0.08)" } : undefined}>
                  <td>{v.label}</td>
                  <td>{pct(v.full.cagr)}</td>
                  <td style={{ color: v.gainFull > 0 ? "var(--green)" : v.gainFull < 0 ? "var(--red)" : undefined }}>{pct(v.gainFull)}</td>
                  <td>{pct(v.recent.cagr)}</td>
                  <td style={{ color: v.gainRecent > 0 ? "var(--green)" : v.gainRecent < 0 ? "var(--red)" : undefined }}>{pct(v.gainRecent)}</td>
                  <td>{pct(v.full.maxDrawdown)}</td>
                  <td>
                    {applied.has(v.label) ? (
                      <span className="pcr-oi-caption">applied</span>
                    ) : v.suggest ? (
                      <button type="button" className="button" style={{ padding: "2px 10px" }} onClick={() => onApply(v.label)}>
                        Apply
                      </button>
                    ) : (
                      <span className="pcr-oi-caption">not recommended</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!(t.variants ?? []).some((v) => v.suggest) ? (
            <p className="pcr-oi-caption" style={{ margin: "6px 0 0" }}>
              No change recommended: nothing beat the current settings by 2+ points a year on both the full history and the recent months.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
