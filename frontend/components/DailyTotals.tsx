"use client";

export interface DailyTotalRow {
  dateKey: string;
  label: string;
  trades: number;
  gross: number;
  net: number | null;
}

/**
 * Groups closed trades by IST calendar date and sums gross/net P&L per day.
 * `getExitTime`/`getGross`/`getNet` are accessors so this works across the
 * different trade shapes each paper-trading page already has (pStrategy's
 * pnlAmountInr/netPnlAmountInr, pStrategy-Nifty's realizedPnl/netRealizedPnl,
 * etc.) without forcing a shared trade type on all of them.
 *
 * `getNet` returning null for every trade (no charges modeled yet, e.g.
 * Crypto-Swing/Nifty-Swing today) makes the day's `net` null too, so the
 * table can fall back to showing gross only rather than a misleading zero.
 */
export function groupDailyTotals<T>(
  trades: T[],
  getExitTime: (t: T) => number | null,
  getGross: (t: T) => number | null,
  getNet: (t: T) => number | null,
): DailyTotalRow[] {
  const byDate = new Map<string, { label: string; trades: number; gross: number; net: number; netKnown: boolean }>();

  for (const t of trades) {
    const exitTime = getExitTime(t);
    if (!exitTime) continue;
    const date = new Date(exitTime * 1000);
    // "en-CA" gives a plain YYYY-MM-DD string -- sorts correctly as text
    // and is a clean grouping key, unlike a locale-formatted display string.
    const dateKey = date.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
    const label = date.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric" });

    const gross = getGross(t) ?? 0;
    const net = getNet(t);
    const existing = byDate.get(dateKey);
    if (existing) {
      existing.trades += 1;
      existing.gross += gross;
      if (net !== null) {
        existing.net += net;
        existing.netKnown = true;
      }
    } else {
      byDate.set(dateKey, { label, trades: 1, gross, net: net ?? 0, netKnown: net !== null });
    }
  }

  return Array.from(byDate.entries())
    .map(([dateKey, v]) => ({ dateKey, label: v.label, trades: v.trades, gross: v.gross, net: v.netKnown ? v.net : null }))
    .sort((a, b) => (a.dateKey < b.dateKey ? 1 : -1)); // newest day first
}

function fmtInrSigned(value: number): string {
  const sign = value >= 0 ? "+" : "-";
  return `${sign}₹${Math.abs(value).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

export function fmtUsdSigned(value: number): string {
  const sign = value >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(value).toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

export function DailyTotalsTable({
  rows,
  label = "Day",
  formatAmount = fmtInrSigned,
}: {
  rows: DailyTotalRow[];
  label?: string;
  formatAmount?: (value: number) => string;
}) {
  if (rows.length === 0) return null;
  const hasAnyNet = rows.some((r) => r.net !== null);
  return (
    <div style={{ overflowX: "auto", margin: "8px 0 16px" }}>
      <table>
        <thead>
          <tr>
            <th>{label}</th>
            <th>Trades</th>
            <th>Gross P&amp;L</th>
            {hasAnyNet ? <th>Net P&amp;L</th> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.dateKey}>
              <td>{r.label}</td>
              <td>{r.trades}</td>
              <td style={{ color: r.gross >= 0 ? "var(--green)" : "var(--red)" }}>{formatAmount(r.gross)}</td>
              {hasAnyNet ? (
                <td style={{ color: (r.net ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                  {r.net !== null ? formatAmount(r.net) : <span className="pcr-oi-caption">—</span>}
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
