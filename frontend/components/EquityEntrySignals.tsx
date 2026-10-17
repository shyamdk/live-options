"use client";

import { BellRing } from "lucide-react";
import { useState } from "react";

import { createAlert } from "@/lib/api";
import type { EquityEntrySignal, EquityHolding } from "@/types/equity";

/** "Is now a good time to buy/add?" -- separate from the long-term recommendation. */

const STATE_ORDER: Record<string, number> = { BUY_ZONE: 0, ADD_ZONE: 1, BLOCKED: 2, NEUTRAL: 3, NOT_QUALITY: 4, NO_DATA: 5 };
const STATE_STYLE: Record<string, { bg: string; fg: string }> = {
  BUY_ZONE: { bg: "rgba(22,132,72,0.14)", fg: "var(--green)" },
  ADD_ZONE: { bg: "rgba(22,132,72,0.14)", fg: "var(--green)" },
  BLOCKED: { bg: "rgba(196,127,23,0.15)", fg: "var(--amber)" },
  NEUTRAL: { bg: "rgba(120,130,145,0.12)", fg: "var(--muted)" },
  NOT_QUALITY: { bg: "rgba(201,53,53,0.10)", fg: "var(--red)" },
  NO_DATA: { bg: "rgba(120,130,145,0.08)", fg: "var(--muted)" },
};

export function entryRank(signal: EquityEntrySignal | null | undefined): number {
  return STATE_ORDER[signal?.state ?? "NO_DATA"] ?? 9;
}

function fmt(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function EntryBadge({ signal }: { signal?: EquityEntrySignal | null }) {
  if (!signal) return <span className="pcr-oi-caption">—</span>;
  const style = STATE_STYLE[signal.state] ?? STATE_STYLE.NO_DATA;
  const tip = [...(signal.blocks ?? []), ...(signal.reasons ?? [])].join("\n");
  return (
    <span
      title={tip}
      style={{ background: style.bg, color: style.fg, padding: "2px 8px", borderRadius: 10, fontSize: 12, fontWeight: 600, whiteSpace: "nowrap", cursor: "help" }}
    >
      {signal.label}
    </span>
  );
}

function AlertButton({ holding }: { holding: EquityHolding }) {
  const s = holding.entrySignal;
  const target = s?.nextAddBelow && s.lastBuy ? s.nextAddBelow : s?.buyBelow;
  const [state, setState] = useState<"idle" | "busy" | "done" | "error">("idle");
  if (!target) return null;
  async function add() {
    setState("busy");
    try {
      await createAlert({
        kind: "price", symbol: holding.symbol, securityId: holding.securityId, segment: holding.exchangeSegment ?? "NSE_EQ",
        direction: "below", price: target!, source: "entry_signal",
        note: `${holding.symbol} reached ${s?.nextAddBelow && s.lastBuy ? "the next add level (8% below the last buy)" : "the buy zone (5% under SMA200)"}: check the Entry signal before buying one tranche.`,
      });
      setState("done");
    } catch {
      setState("error");
    }
  }
  return (
    <button
      type="button"
      className="button secondary"
      title={`Alert me (portal + Telegram) when ${holding.symbol} falls to ${target.toLocaleString("en-IN")}`}
      onClick={add}
      disabled={state === "busy" || state === "done"}
      style={{ padding: "2px 8px", whiteSpace: "nowrap" }}
    >
      <BellRing size={13} /> {state === "done" ? "Alert set" : state === "error" ? "Retry" : `Alert at ${target.toLocaleString("en-IN")}`}
    </button>
  );
}

export default function EquityEntrySignals({ holdings }: { holdings: EquityHolding[] }) {
  const rows = holdings
    .filter((h) => h.entrySignal && ["BUY_ZONE", "ADD_ZONE", "BLOCKED"].includes(h.entrySignal.state))
    .sort((a, b) => entryRank(a.entrySignal) - entryRank(b.entrySignal) || (a.entrySignal?.distanceToSma200Percent ?? 0) - (b.entrySignal?.distanceToSma200Percent ?? 0));
  const counts = holdings.reduce<Record<string, number>>((acc, h) => {
    const s = h.entrySignal?.state ?? "NO_DATA";
    acc[s] = (acc[s] ?? 0) + 1;
    return acc;
  }, {});
  return (
    <div className="pcr-oi-section">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 8 }}>
        <h3 style={{ margin: 0 }}>Entry signals: is now a good time to buy?</h3>
        <span className="pcr-oi-caption">
          {counts.BUY_ZONE ?? 0} buy · {counts.ADD_ZONE ?? 0} add · {counts.BLOCKED ?? 0} in zone but blocked · {counts.NEUTRAL ?? 0} no edge ·{" "}
          {counts.NOT_QUALITY ?? 0} fail quality
        </span>
      </div>
      <p className="pcr-oi-caption" style={{ margin: "4px 0 10px" }}>
        Separate from the long-term recommendation. A quality share is in the buy zone when RSI(14) is under 30 or the price is 5%+ below its
        SMA200. On your holdings&apos; prices (2021–2026) those entries beat buying on any day by +3–7% over 6 months, while buying after a
        confirmed uptrend didn&apos;t. Blocks: company-specific bad news, results within a week, over 8% of the portfolio, a buy in the last 14 days,
        or less than 8% below the last buy. Buy in tranches (about a third at a time). Hover a badge for the details.
      </p>
      <div style={{ overflowX: "auto" }}>
        <table>
          <thead>
            <tr>
              <th>Stock</th>
              <th>Signal</th>
              <th>LTP</th>
              <th>Buy zone below</th>
              <th>vs SMA200</th>
              <th>RSI(14)</th>
              <th>Last buy</th>
              <th>Next add below</th>
              <th>Why / what&apos;s blocking</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((h) => {
              const s = h.entrySignal!;
              return (
                <tr key={h.id}>
                  <td>
                    <strong>{h.symbol}</strong>
                  </td>
                  <td>
                    <EntryBadge signal={s} />
                  </td>
                  <td>{fmt(h.ltp)}</td>
                  <td>{fmt(s.buyBelow)}</td>
                  <td>{s.distanceToSma200Percent !== null && s.distanceToSma200Percent !== undefined ? `${s.distanceToSma200Percent > 0 ? "+" : ""}${s.distanceToSma200Percent}%` : "—"}</td>
                  <td>{fmt(s.rsi, 0)}</td>
                  <td>{s.lastBuy ? `${fmt(s.lastBuy.price)} · ${s.lastBuy.date}` : "—"}</td>
                  <td>{fmt(s.nextAddBelow)}</td>
                  <td style={{ fontSize: 12, maxWidth: 420 }}>{[...(s.blocks ?? []), ...(s.reasons ?? [])].slice(0, 3).join(" ")}</td>
                  <td>
                    <AlertButton holding={h} />
                  </td>
                </tr>
              );
            })}
            {!rows.length ? (
              <tr>
                <td colSpan={10} className="pcr-oi-caption">
                  No holding is in the buy zone right now.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
