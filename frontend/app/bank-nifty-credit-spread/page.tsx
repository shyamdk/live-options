"use client";

import { DoorOpen, Layers, RefreshCcw, SearchCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { approveCreditSpreadSignal, evaluateCreditSpread, exitCreditSpread, getCreditSpreadState } from "@/lib/api";
import type { CreditSpreadPosition, CreditSpreadSignal, CreditSpreadState } from "@/types/credit-spread";

const money = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const STATE_REFRESH_MS = 15000;

function fmt(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return digits === 2 ? money.format(value) : value.toFixed(digits);
}

function pnlClass(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  return value >= 0 ? "positive" : "negative";
}

export default function BankNiftyCreditSpreadPage() {
  const [state, setState] = useState<CreditSpreadState | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function loadState() {
    try {
      setState(await getCreditSpreadState());
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load credit spread state.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadState();
    const timer = window.setInterval(loadState, STATE_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  async function run(label: string, action: () => Promise<Record<string, unknown>>, confirmText?: string) {
    if (confirmText && !window.confirm(confirmText)) return;
    setBusy(label);
    setMessage(null);
    setError(null);
    try {
      const result = await action();
      const status = String(result.status ?? "done");
      const detail = result.message ? `: ${result.message}` : "";
      setMessage(`${label} — ${status}${detail}`);
      await loadState();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : `${label} failed.`);
    } finally {
      setBusy(null);
    }
  }

  const mode = state?.mode ?? "PAPER";
  const position = state?.openPosition ?? null;
  const mtm = state?.mtm ?? null;
  const evaluation = state?.lastEvaluation ?? null;
  const config = state?.config;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Layers size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Bank Nifty Credit Spread
          </h1>
          <p>Monthly bear call spread — sell futures-ATM CE, buy the ₹{config?.hedgePremiumTarget ?? 100} hedge, exit at T-{config?.exitTradingDaysBeforeExpiry ?? 10} trading days</p>
        </div>
        <div className="toolbar">
          <span className={mode === "LIVE" ? "status-live on" : "status-live"}>{mode}</span>
          <button
            className="button"
            type="button"
            disabled={busy !== null}
            onClick={() => run("Evaluate now", evaluateCreditSpread)}
          >
            <SearchCheck size={15} /> Evaluate now
          </button>
          {position ? (
            <button
              className="button"
              type="button"
              disabled={busy !== null}
              onClick={() =>
                run("Manual exit", exitCreditSpread, "Close the open spread now at market? This exits BOTH legs immediately.")
              }
            >
              <DoorOpen size={15} /> Exit position
            </button>
          ) : null}
          <button className="icon-button" type="button" title="Refresh" onClick={loadState} disabled={loading}>
            <RefreshCcw size={16} />
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}
      {message ? <div className="alert success">{message}</div> : null}
      {state?.lastError ? <div className="alert error">Engine error: {state.lastError}</div> : null}

      <div className="metric-grid">
        <div className="metric">
          <span className="subtext">Front expiry</span>
          <strong>{state?.frontExpiry ?? "—"}</strong>
        </div>
        <div className="metric">
          <span className="subtext">Series started</span>
          <strong>{state?.seriesStartDate ?? "—"}</strong>
        </div>
        <div className="metric">
          <span className="subtext">Trading days to expiry</span>
          <strong>{state?.remainingTradingDays ?? "—"}</strong>
        </div>
        <div className="metric">
          <span className="subtext">Planned exit (T-{config?.exitTradingDaysBeforeExpiry ?? 10})</span>
          <strong>{state?.plannedExitDate ?? "—"} {config?.exitTime ?? "09:20"}</strong>
        </div>
        <div className="metric">
          <span className="subtext">Quantity</span>
          <strong>
            {config ? config.lotSize * config.lots : "—"} ({config?.lots ?? 1} lot)
          </strong>
        </div>
        <div className="metric">
          <span className="subtext">Capital base</span>
          <strong>₹{config ? money.format(config.capitalBase) : "—"}</strong>
        </div>
      </div>

      {position ? (
        <section className="table-section">
          <div className="section-title">
            <h2>Open Position — {position.id}</h2>
            <span className={pnlClass(mtm?.unrealizedPnl)}>
              {mtm ? `₹${money.format(mtm.unrealizedPnl)} (${fmt(mtm.capturePercent, 1)}% of credit)` : "MTM pending"}
            </span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Leg</th>
                  <th>Strike</th>
                  <th>Entry</th>
                  <th>LTP</th>
                  <th>P&L / share</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>SELL CE</td>
                  <td>{fmt(position.sellStrike, 0)}</td>
                  <td>{fmt(position.sellEntryPrice)}</td>
                  <td>{fmt(mtm?.sellLtp)}</td>
                  <td className={pnlClass(mtm?.sellLtp != null ? position.sellEntryPrice - mtm.sellLtp : null)}>
                    {mtm?.sellLtp != null ? fmt(position.sellEntryPrice - mtm.sellLtp) : "—"}
                  </td>
                </tr>
                <tr>
                  <td>BUY CE (hedge)</td>
                  <td>{fmt(position.hedgeStrike, 0)}</td>
                  <td>{fmt(position.hedgeEntryPrice)}</td>
                  <td>{fmt(mtm?.hedgeLtp)}</td>
                  <td className={pnlClass(mtm?.hedgeLtp != null && position.hedgeEntryPrice != null ? mtm.hedgeLtp - position.hedgeEntryPrice : null)}>
                    {mtm?.hedgeLtp != null && position.hedgeEntryPrice != null ? fmt(mtm.hedgeLtp - position.hedgeEntryPrice) : "—"}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div className="compact-list">
            <div className="compact-row">
              <span>Net credit {fmt(position.netCredit)} × {position.qty} = ₹{money.format(position.netCredit * position.qty)} max profit</span>
              <span>Entry {position.entryAt} | spot {fmt(position.entrySpot)} | synth fut {fmt(position.entrySyntheticFuture)} | VIX {fmt(position.entryVix)}</span>
            </div>
            <div className="compact-row">
              <span>Exit plan: {position.plannedExitDate} at {config?.exitTime} (T-{config?.exitTradingDaysBeforeExpiry}), profit target {config?.profitTargetPercent}% of credit</span>
              <span>{mtm ? `Last mark ${mtm.at}, spot ${fmt(mtm.spot)}` : ""}</span>
            </div>
          </div>
        </section>
      ) : (
        <section className="table-section">
          <div className="section-title">
            <h2>Entry Preview</h2>
            <span>{evaluation ? `evaluated ${evaluation.at}` : "no evaluation yet"}</span>
          </div>
          {evaluation ? (
            <>
              <div className="metric-grid">
                <div className="metric">
                  <span className="subtext">Spot</span>
                  <strong>{fmt(evaluation.selection.spot)}</strong>
                </div>
                <div className="metric">
                  <span className="subtext">Synthetic future</span>
                  <strong>{fmt(evaluation.selection.syntheticFuture)}</strong>
                </div>
                <div className="metric">
                  <span className="subtext">SELL</span>
                  <strong>
                    {fmt(evaluation.selection.sell.strike, 0)} CE @ {fmt(evaluation.selection.sell.price)}
                  </strong>
                </div>
                <div className="metric">
                  <span className="subtext">HEDGE</span>
                  <strong>
                    {evaluation.selection.hedge
                      ? `${fmt(evaluation.selection.hedge.strike, 0)} CE @ ${fmt(evaluation.selection.hedge.price)}`
                      : "not found"}
                  </strong>
                </div>
                <div className="metric">
                  <span className="subtext">Net credit</span>
                  <strong>
                    {fmt(evaluation.selection.netCredit)} ({fmt(evaluation.selection.creditPercentOfWidth, 1)}% of width)
                  </strong>
                </div>
                <div className="metric">
                  <span className="subtext">India VIX</span>
                  <strong>{fmt(evaluation.vix)}</strong>
                </div>
              </div>
              {evaluation.blockers.length ? (
                <div className="alert error">
                  Entry blocked: {evaluation.blockers.join(" | ")}
                </div>
              ) : (
                <div className="alert success">All entry checks pass for expiry {evaluation.expiry}.</div>
              )}
            </>
          ) : (
            <div className="empty-state">
              No evaluation yet. The engine evaluates automatically on the first trading day after monthly expiry from{" "}
              {config?.entryTime ?? "09:45"}, or press “Evaluate now”.
            </div>
          )}
        </section>
      )}

      {state?.pendingSignals.length ? (
        <section className="table-section">
          <div className="section-title">
            <h2>Pending Signals</h2>
            <span>{state.pendingSignals.length}</span>
          </div>
          <div className="compact-list">
            {state.pendingSignals.map((signal: CreditSpreadSignal) => (
              <div className="compact-row" key={signal.id}>
                <span>
                  #{signal.id} {signal.kind} — {String((signal.payload ?? {}).detail ?? (signal.payload ?? {}).reason ?? "")}{" "}
                  ({signal.createdAt})
                </span>
                <button
                  className="button"
                  type="button"
                  disabled={busy !== null}
                  onClick={() =>
                    run(
                      `Approve #${signal.id}`,
                      () => approveCreditSpreadSignal(signal.id),
                      `Approve ${signal.kind} signal #${signal.id}? This ${mode === "LIVE" ? "sends real Dhan orders" : "simulates a paper fill"} immediately.`,
                    )
                  }
                >
                  Approve
                </button>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="table-section">
        <div className="section-title">
          <h2>Position History</h2>
          <span>
            {state?.positions.length ?? 0} | realized ₹
            {money.format((state?.positions ?? []).reduce((acc, p) => acc + (p.realizedPnl ?? 0), 0))}
          </span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Position</th>
                <th>Mode</th>
                <th>Qty</th>
                <th>Sell / Hedge</th>
                <th>Credit</th>
                <th>Entry</th>
                <th>Exit</th>
                <th>Reason</th>
                <th>P&L</th>
              </tr>
            </thead>
            <tbody>
              {(state?.positions ?? []).map((p: CreditSpreadPosition) => (
                <tr key={p.id} className={p.status === "CLOSED" ? "closed-row" : ""}>
                  <td>{p.id}</td>
                  <td>{p.mode}</td>
                  <td>{p.qty}</td>
                  <td>
                    {fmt(p.sellStrike, 0)} / {fmt(p.hedgeStrike, 0)}
                  </td>
                  <td>{fmt(p.netCredit)}</td>
                  <td>{p.entryAt}</td>
                  <td>{p.exitAt ?? "open"}</td>
                  <td>{p.exitReason ?? "—"}</td>
                  <td className={pnlClass(p.realizedPnl)}>{p.realizedPnl != null ? `₹${money.format(p.realizedPnl)}` : "—"}</td>
                </tr>
              ))}
              {!state?.positions.length ? (
                <tr>
                  <td colSpan={9} className="empty-state">
                    No positions yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="table-section">
        <div className="section-title">
          <h2>Event Log</h2>
          <span>{state?.events.length ?? 0}</span>
        </div>
        <div className="compact-list">
          {(state?.events ?? []).map((event) => (
            <div className="compact-row" key={event.id}>
              <span>
                <span className="badge">{event.eventType}</span> {event.message}
              </span>
              <span className="subtext">{event.createdAt}</span>
            </div>
          ))}
          {!state?.events.length ? <div className="empty-state">No events yet.</div> : null}
        </div>
      </section>
    </section>
  );
}
