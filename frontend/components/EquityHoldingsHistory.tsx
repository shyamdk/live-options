"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useMemo, useState } from "react";

import type { EquityHolding, EquityTransaction } from "@/types/equity";

/**
 * Holdings & History tab: one row per holding; expanding it shows every
 * buy/sell Dhan has for that share (live trade history + imported CSV
 * reports), the buy lots still held (first-in-first-out), and how much of
 * the current quantity the history explains.
 */

type Lot = { date: string; qty: number; price: number };
type SellMatch = { date: string; qty: number; price: number; realized: number };
type History = {
  trades: EquityTransaction[];
  openLots: Lot[];
  sells: SellMatch[];
  boughtQty: number;
  soldQty: number;
  realized: number;
  firstDate: string | null;
  lastBuyDate: string | null;
  unexplainedQty: number; // held quantity the history doesn't cover (older than the imported reports)
  excessQty: number; // history explains more than is held (missing sells or unadjusted corporate action)
  duplicatesDropped: number;
};

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

function tradeDate(t: EquityTransaction): string {
  return String(t.exchangeTime || t.updateTime || t.createTime || "");
}

function shortDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return value.slice(0, 10);
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function daysSince(value: string): number | null {
  const d = new Date(value.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return null;
  return Math.max(0, Math.round((Date.now() - d.getTime()) / 86_400_000));
}

function belongsTo(t: EquityTransaction, h: EquityHolding): boolean {
  if (h.securityId && String(t.securityId) === String(h.securityId)) return true;
  return Boolean(h.isin && t.isin && t.isin === h.isin);
}

/**
 * The imported Dhan CSV reports hold one aggregated row per share, day and
 * side, while the live trade-history API returns each fill. Where both cover
 * the same day the purchase appears twice: drop an aggregated row whose
 * quantity equals the other fills of that day/side at the same average price.
 */
function dropDailyAggregates(trades: EquityTransaction[]): { kept: EquityTransaction[]; dropped: number } {
  const groups = new Map<string, EquityTransaction[]>();
  for (const t of trades) {
    const key = `${tradeDate(t).slice(0, 10)}|${String(t.transactionType).toUpperCase()}`;
    groups.set(key, [...(groups.get(key) ?? []), t]);
  }
  const drop = new Set<string>();
  for (const rows of groups.values()) {
    if (rows.length < 2) continue;
    for (const candidate of rows) {
      const others = rows.filter((r) => r !== candidate && !drop.has(r.id));
      const qty = others.reduce((sum, r) => sum + r.quantity, 0);
      if (!others.length || qty !== candidate.quantity) continue;
      const avg = others.reduce((sum, r) => sum + r.quantity * Number(r.price ?? 0), 0) / qty;
      if (Math.abs(avg - Number(candidate.price ?? 0)) <= Math.max(0.05, avg * 0.005)) drop.add(candidate.id);
    }
  }
  return { kept: trades.filter((t) => !drop.has(t.id)), dropped: drop.size };
}

export function buildHistory(holding: EquityHolding, transactions: EquityTransaction[]): History {
  const { kept: trades, dropped } = dropDailyAggregates(
    transactions.filter((t) => belongsTo(t, holding) && t.quantity > 0).sort((a, b) => tradeDate(a).localeCompare(tradeDate(b))),
  );
  const lots: Lot[] = [];
  const sells: SellMatch[] = [];
  let boughtQty = 0;
  let soldQty = 0;
  let realized = 0;
  for (const t of trades) {
    const price = Number(t.price ?? 0);
    if (String(t.transactionType).toUpperCase() === "BUY") {
      lots.push({ date: tradeDate(t), qty: t.quantity, price });
      boughtQty += t.quantity;
      continue;
    }
    soldQty += t.quantity;
    let remaining = t.quantity;
    let matchedPnl = 0;
    while (remaining > 0 && lots.length) {
      const lot = lots[0];
      const take = Math.min(lot.qty, remaining);
      matchedPnl += (price - lot.price) * take;
      lot.qty -= take;
      remaining -= take;
      if (lot.qty === 0) lots.shift();
    }
    // sells with no matching buy in the history were bought before it starts
    sells.push({ date: tradeDate(t), qty: t.quantity, price, realized: matchedPnl });
    realized += matchedPnl;
  }
  const openQty = lots.reduce((sum, lot) => sum + lot.qty, 0);
  const buys = trades.filter((t) => String(t.transactionType).toUpperCase() === "BUY");
  return {
    trades,
    openLots: lots,
    sells,
    boughtQty,
    soldQty,
    realized,
    firstDate: trades.length ? tradeDate(trades[0]) : null,
    lastBuyDate: buys.length ? tradeDate(buys[buys.length - 1]) : null,
    unexplainedQty: Math.max(0, Number(holding.totalQty || 0) - openQty),
    excessQty: Math.max(0, openQty - Number(holding.totalQty || 0)),
    duplicatesDropped: dropped,
  };
}

export default function EquityHoldingsHistory({ holdings, transactions }: { holdings: EquityHolding[]; transactions: EquityTransaction[] }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const rows = useMemo(
    () =>
      holdings
        .map((h) => ({ holding: h, history: buildHistory(h, transactions) }))
        .filter(({ holding }) => !filter || holding.symbol.toLowerCase().includes(filter.toLowerCase()))
        .sort((a, b) => (b.holding.marketValue ?? 0) - (a.holding.marketValue ?? 0)),
    [holdings, transactions, filter],
  );
  const earliest = useMemo(
    () => transactions.map(tradeDate).filter(Boolean).sort()[0] ?? null,
    [transactions],
  );

  function toggle(id: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="pcr-oi-section">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 8 }}>
        <div>
          <h3 style={{ margin: 0 }}>Holdings &amp; history</h3>
          <p className="pcr-oi-caption" style={{ margin: "2px 0 0" }}>
            Click a share to see every buy and sell, and the buy lots still held (first in, first out). History available from{" "}
            {shortDate(earliest)}; shares bought before that show as &quot;not in history&quot;. Splits and bonus issues are not adjusted.
          </p>
        </div>
        <input placeholder="Filter shares…" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 180 }} />
      </div>
      <div style={{ overflowX: "auto" }}>
        <table>
          <thead>
            <tr>
              <th style={{ width: 28 }} />
              <th>Share</th>
              <th>Qty</th>
              <th>Avg cost</th>
              <th>LTP</th>
              <th>Invested</th>
              <th>Value</th>
              <th>P&amp;L</th>
              <th>Trades</th>
              <th>First trade</th>
              <th>Last buy</th>
              <th>Covered by history</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ holding: h, history }) => {
              const open = expanded.has(h.id);
              const coveredQty = Number(h.totalQty || 0) - history.unexplainedQty;
              return (
                <Fragment key={h.id}>
                  <tr onClick={() => toggle(h.id)} style={{ cursor: "pointer" }}>
                    <td>{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</td>
                    <td>
                      <strong>{h.symbol}</strong>
                      <div className="pcr-oi-caption">{h.recommendation?.action ?? ""}</div>
                    </td>
                    <td>{h.totalQty}</td>
                    <td>{num(h.avgCostPrice)}</td>
                    <td>{num(h.ltp)}</td>
                    <td>{inr(h.investedValue)}</td>
                    <td>{inr(h.marketValue)}</td>
                    <td style={{ color: tone(h.pnl) }}>
                      {inr(h.pnl)} <span className="pcr-oi-caption">({num(h.pnlPercent, 1)}%)</span>
                    </td>
                    <td>{history.trades.length}</td>
                    <td>{shortDate(history.firstDate)}</td>
                    <td>{shortDate(history.lastBuyDate)}</td>
                    <td style={{ color: history.unexplainedQty || history.excessQty ? "var(--amber)" : undefined }}>
                      {history.excessQty ? `history +${history.excessQty} too many` : history.unexplainedQty ? `${coveredQty} of ${h.totalQty}` : "all"}
                    </td>
                  </tr>
                  {open ? (
                    <tr>
                      <td />
                      <td colSpan={11} style={{ background: "var(--panel)", padding: "8px 10px 14px" }}>
                        <HoldingDetail holding={h} history={history} />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
            {!rows.length ? (
              <tr>
                <td colSpan={12} className="pcr-oi-caption">
                  No holdings.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function HoldingDetail({ holding, history }: { holding: EquityHolding; history: History }) {
  const ltp = holding.ltp ?? null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="gb-status-row">
        <span>Bought {history.boughtQty} · sold {history.soldQty} in the history</span>
        <span>
          Realized (FIFO): <strong style={{ color: tone(history.realized) }}>{inr(history.realized)}</strong>
        </span>
        {history.duplicatesDropped ? (
          <span className="pcr-oi-caption">
            {history.duplicatesDropped} duplicate daily-total row{history.duplicatesDropped > 1 ? "s" : ""} from the imported reports hidden
          </span>
        ) : null}
        {history.excessQty ? (
          <span style={{ color: "var(--amber)" }}>
            History adds up to {history.excessQty} more shares than you hold: a sell is missing from the history, or a split/bonus isn&apos;t
            adjusted. The lots below may include shares already sold.
          </span>
        ) : null}
        {history.unexplainedQty ? (
          <span style={{ color: "var(--amber)" }}>
            {history.unexplainedQty} share{history.unexplainedQty > 1 ? "s" : ""} not in history (bought before it starts, or a corporate action)
          </span>
        ) : null}
      </div>

      <div>
        <strong style={{ fontSize: 13 }}>Lots still held</strong>
        <table style={{ marginTop: 4 }}>
          <thead>
            <tr>
              <th>Bought on</th>
              <th>Qty</th>
              <th>Buy price</th>
              <th>Cost</th>
              <th>Value now</th>
              <th>P&amp;L</th>
              <th>Held</th>
            </tr>
          </thead>
          <tbody>
            {history.openLots.map((lot, i) => {
              const pnl = ltp !== null ? (ltp - lot.price) * lot.qty : null;
              const held = daysSince(lot.date);
              return (
                <tr key={i}>
                  <td>{shortDate(lot.date)}</td>
                  <td>{lot.qty}</td>
                  <td>{num(lot.price)}</td>
                  <td>{inr(lot.price * lot.qty)}</td>
                  <td>{ltp !== null ? inr(ltp * lot.qty) : "—"}</td>
                  <td style={{ color: tone(pnl) }}>
                    {inr(pnl)} {pnl !== null && lot.price ? <span className="pcr-oi-caption">({num((ltp! / lot.price - 1) * 100, 1)}%)</span> : null}
                  </td>
                  <td>{held !== null ? `${held} d` : "—"}</td>
                </tr>
              );
            })}
            {history.unexplainedQty ? (
              <tr>
                <td className="pcr-oi-caption">before history</td>
                <td>{history.unexplainedQty}</td>
                <td colSpan={5} className="pcr-oi-caption">
                  buy date and price not available; Dhan&apos;s average cost {num(holding.avgCostPrice)} includes them
                </td>
              </tr>
            ) : null}
            {!history.openLots.length && !history.unexplainedQty ? (
              <tr>
                <td colSpan={7} className="pcr-oi-caption">
                  No open lots.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div>
        <strong style={{ fontSize: 13 }}>All transactions ({history.trades.length})</strong>
        <table style={{ marginTop: 4 }}>
          <thead>
            <tr>
              <th>Date</th>
              <th>Side</th>
              <th>Qty</th>
              <th>Price</th>
              <th>Value</th>
              <th>Charges</th>
              <th>Realized (FIFO)</th>
            </tr>
          </thead>
          <tbody>
            {[...history.trades].reverse().map((t) => {
              const side = String(t.transactionType).toUpperCase();
              const sell = side === "SELL" ? history.sells.find((s) => s.date === tradeDate(t) && s.qty === t.quantity) : null;
              return (
                <tr key={t.id}>
                  <td>{tradeDate(t).replace("T", " ").slice(0, 16) || "—"}</td>
                  <td style={{ color: side === "BUY" ? "var(--green)" : "var(--red)", fontWeight: 600 }}>{side}</td>
                  <td>{t.quantity}</td>
                  <td>{num(t.price)}</td>
                  <td>{inr(t.value)}</td>
                  <td>{t.charges ? inr(t.charges, 2) : "—"}</td>
                  <td style={{ color: tone(sell?.realized) }}>{sell ? inr(sell.realized) : ""}</td>
                </tr>
              );
            })}
            {!history.trades.length ? (
              <tr>
                <td colSpan={7} className="pcr-oi-caption">
                  No transactions for this share in the available history.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
