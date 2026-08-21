"use client";

import { FlaskConical, Lightbulb } from "lucide-react";
import { useState } from "react";

import { getOiUpgradedBacktest } from "@/lib/api";
import type { BacktestReport, BacktestSummary } from "@/types/live";

const CHANGES_MADE = [
  {
    title: "Loosened persistence + entry score (was too strict to ever fire)",
    body: "The design doc's literal persistence=3/entry-score=8 produced zero confirmed signals across a full real NIFTY session despite the raw score reaching 8-10 eight times that day. \"3 consecutive polls\" assumed a 2-minute poll cadence in its \"~6 minute\" framing; this app polls every 3 minutes, so 3 reads is closer to 9 minutes. Loosened to persistence=2/entry-score=7 -- still genuine 2-poll confirmation, not a single read.",
  },
  {
    title: "Fixed the backtest to simulate real staged exits",
    body: "The first backtest marked \"exit\" at whatever premium was observed when the signal's own state changed -- which never reflects reality, since paper trading manages every position with its own independent 15%/10%/20%/5% SL/target/trail. Rewrote it to replay that real staged-exit logic against the actual premium path, so results now reflect what a real paper trade would do.",
  },
  {
    title: "Fresh-extreme confirmation (fixes buying the exact bottom)",
    body: "Traced losing trades to the candle level: several PE entries fired within a couple of points of the exact candle low, right before reversal. The 5-minute trend is a lagging average that peaks in \"bearish\" exactly as a decline ends. Price must now itself be a new 8-candle high/low before price confirmation counts, not just trailing-average direction.",
  },
  {
    title: "VIX/IV risk veto (fixes buying into capitulation)",
    body: "A rapid VIX or IV spike (not a moderate rise) now blocks entry outright instead of only losing a score point. One losing trade had IV flagged \"risky\" at the exact entry poll -- a fast IV spike alongside a sharp move is a capitulation signature, not continuation.",
  },
];

const CANDIDATE_IMPROVEMENTS = [
  {
    title: "Avoid the first ~15-20 minutes after open",
    body: "VWAP anchored at 09:15 is unstable early, and the 5-candle trend has few candles to work with in the opening minutes. This app's own Timing Notes already flag the opening range as false-spike-prone for the older signal -- the same logic likely applies here and hasn't been added yet.",
  },
  {
    title: "Volatility-adjusted price-trend threshold",
    body: "PRICE_TREND_EPS is a fixed 5 NIFTY points regardless of how volatile the session is -- 5 points in 5 minutes is a real move on a quiet day and noise on a volatile one. The Price Breakout signal elsewhere in this app already z-scores moves against the day's own recent volatility; the same approach could replace this fixed threshold.",
  },
  {
    title: "Watch for a CE/PE asymmetry as more data comes in",
    body: "Every loss so far has been on the PE side. Too little data to act on yet (see the observations below), but if this holds up over more sessions, consider asymmetric thresholds -- e.g. a stricter entry score or longer persistence specifically for PE -- rather than assuming CE and PE behave the same way.",
  },
  {
    title: "Re-run this analysis regularly as more sessions accumulate",
    body: "Every conclusion here is drawn from a handful of trades over ~6 days -- not enough to trust individual parameter changes. The signal-history logger is live and accumulating every poll; re-running this page in a few weeks, once there are dozens of trades instead of single digits, is what would actually validate (or invalidate) these choices rather than continuing to hand-tune against the same small sample.",
  },
  {
    title: "Extend to SENSEX once NIFTY is validated",
    body: "The engine is NIFTY-only by design for now. Once a larger sample shows the entry logic is genuinely sound (not just fit to this window), the same engine can run independently for SENSEX with its own persistence/cooldown state.",
  },
];

const REASON_LABEL: Record<string, string> = { stop_loss: "Stop loss", trail: "Trail", eod: "EOD" };
const SIDE_LABEL: Record<string, string> = { buyCe: "CE", buyPe: "PE" };

function fmtPct(value: number | null): string {
  return value === null ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

function fmtRate(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(0)}%`;
}

export default function OiImprovementsPage() {
  const [report, setReport] = useState<BacktestReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleRun() {
    setLoading(true);
    setError(null);
    try {
      setReport(await getOiUpgradedBacktest());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to run the analysis.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Lightbulb size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            OI Improvements
          </h1>
          <p>
            Results summary for the OI - Upgraded signal engine, what&apos;s already been fixed from real losing
            trades, and candidate ideas for what to try next -- a durable page to check back on instead of a
            one-off session check.
          </p>
        </div>
        <div className="toolbar">
          <button type="button" className="button secondary" onClick={handleRun} disabled={loading}>
            <FlaskConical size={14} /> {loading ? "Running…" : "Run analysis"}
          </button>
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}

      <div className="pcr-oi-section">
        <h3>Changes already made</h3>
        <div className="oi-upgraded-legend">
          {CHANGES_MADE.map((item) => (
            <div key={item.title} className="oi-upgraded-legend-item">
              <strong>{item.title}</strong>
              <p>{item.body}</p>
            </div>
          ))}
        </div>
      </div>

      {report ? (
        <>
          <div className="pcr-oi-section">
            <h3>Results summary</h3>
            <div className="metric-grid oi-upgraded-metric-grid">
              <div className="metric">
                <span>New engine trades</span>
                <strong>{report.totals.new.count}</strong>
              </div>
              <div className="metric">
                <span>New engine avg / win rate</span>
                <strong>
                  {fmtPct(report.totals.new.avgPnlPct)} / {fmtRate(report.totals.new.winRate)}
                </strong>
              </div>
              <div className="metric">
                <span>Old engine trades</span>
                <strong>{report.totals.old.count}</strong>
              </div>
              <div className="metric">
                <span>Old engine avg / win rate</span>
                <strong>
                  {fmtPct(report.totals.old.avgPnlPct)} / {fmtRate(report.totals.old.winRate)}
                </strong>
              </div>
            </div>
          </div>

          <div className="pcr-oi-section">
            <h3>Data-driven observations</h3>
            <p className="pcr-oi-caption" style={{ margin: 0 }}>
              Computed directly from the backtested trades below -- facts, not fitted rules. Sample sizes are small;
              read these as leads to watch, not conclusions.
            </p>
            <ul className="pcr-oi-rules">
              {report.observations.map((obs) => (
                <li key={obs}>{obs}</li>
              ))}
            </ul>
          </div>

          {report.newTrades.length > 0 ? (
            <>
              <div className="pcr-oi-section">
                <h3>Breakdown — by side</h3>
                <BreakdownTable breakdown={report.breakdowns.bySide} labels={SIDE_LABEL} />
              </div>

              <div className="pcr-oi-section">
                <h3>Breakdown — by exit reason</h3>
                <BreakdownTable breakdown={report.breakdowns.byReason} labels={REASON_LABEL} />
              </div>

              <div className="pcr-oi-section">
                <h3>New engine — trade detail</h3>
                <div style={{ overflowX: "auto" }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Side</th>
                        <th>Entry</th>
                        <th>Exit reason</th>
                        <th>P&amp;L %</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.newTrades.map((trade) => (
                        <tr key={`${trade.date}-${trade.entryTime}`}>
                          <td>{trade.date}</td>
                          <td>
                            <span className={`badge ${trade.side === "buyCe" ? "buy" : "sell"}`}>{SIDE_LABEL[trade.side]}</span>
                          </td>
                          <td>
                            {new Date(trade.entryTime * 1000).toLocaleTimeString("en-IN", {
                              timeZone: "Asia/Kolkata",
                              hour: "2-digit",
                              minute: "2-digit",
                              hour12: false,
                            })}
                          </td>
                          <td>{REASON_LABEL[trade.reason] ?? trade.reason}</td>
                          <td style={{ color: trade.pnlPct >= 0 ? "var(--green)" : "var(--red)" }}>{fmtPct(trade.pnlPct)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          ) : null}
        </>
      ) : (
        <div className="pcr-oi-section">
          <p className="pcr-oi-caption">Click "Run analysis" to compute the current results summary.</p>
        </div>
      )}

      <div className="pcr-oi-section">
        <h3>Candidate next improvements</h3>
        <p className="pcr-oi-caption" style={{ margin: 0 }}>
          Ideas, not commitments -- each needs more data or explicit sign-off before being implemented.
        </p>
        <div className="oi-upgraded-legend">
          {CANDIDATE_IMPROVEMENTS.map((item) => (
            <div key={item.title} className="oi-upgraded-legend-item">
              <strong>{item.title}</strong>
              <p>{item.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function BreakdownTable({ breakdown, labels }: { breakdown: Record<string, BacktestSummary>; labels: Record<string, string> }) {
  const keys = Object.keys(breakdown);
  if (keys.length === 0) {
    return <p className="pcr-oi-caption">No trades yet.</p>;
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>Group</th>
            <th>Trades</th>
            <th>Avg %</th>
            <th>Win rate</th>
            <th>Total %</th>
          </tr>
        </thead>
        <tbody>
          {keys.map((key) => (
            <tr key={key}>
              <td>{labels[key] ?? key}</td>
              <td>{breakdown[key].count}</td>
              <td>{fmtPct(breakdown[key].avgPnlPct)}</td>
              <td>{fmtRate(breakdown[key].winRate)}</td>
              <td>{fmtPct(breakdown[key].totalPnlPct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
