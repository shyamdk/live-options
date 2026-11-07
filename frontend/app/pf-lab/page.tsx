"use client";

import { Grid3x3, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import CollapsibleSection from "@/components/CollapsibleSection";
import { getPfOverview } from "@/lib/api";
import type { PfOverview } from "@/types/pf-lab";

const MARKETS = ["NIFTY", "BTC", "GOLD"];
const HORIZONS: [string, string][] = [["short", "0.25%"], ["medium", "1%"], ["long", "3%"]];

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function money(v: number | null | undefined, cur: string): string {
  if (v === null || v === undefined) return "—";
  const d = cur === "$" ? 2 : 0;
  return `${v < 0 ? "−" : ""}${cur}${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
}

export default function PfLabOverview() {
  const [data, setData] = useState<PfOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function load() {
    try {
      setData(await getPfOverview());
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load.");
    }
  }
  useEffect(() => {
    load();
  }, []);

  const cell = (m: string, h: string, s: string) => data?.backtest.cells[`${m}|${h}|${s}`];
  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Grid3x3 size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            P&amp;F Lab
          </h1>
          <p>
            Five Point &amp; Figure systems (Double Top/Bottom + 10-column MA, Triple Top/Bottom, Turtle, ABC, VCP) × three horizons (0.25 / 1 / 3 % box on
            daily closes) × NIFTY, BTC and gold. Backtest comparison first, then the nine paper books.
          </p>
        </div>
        <div className="toolbar">
          <button type="button" className="button secondary" onClick={load}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </header>
      {error ? <div className="alert error">{error}</div> : null}

      <CollapsibleSection id="pf-lab-books" title="Paper books">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th />
                {HORIZONS.map(([h, box]) => (
                  <th key={h}>
                    {data?.horizons[h] ?? h} <span className="pcr-oi-caption">({box} box)</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {MARKETS.map((m) => (
                <tr key={m}>
                  <td>
                    <strong>{data?.markets[m]?.label ?? m}</strong> <span className="pcr-oi-caption">{data?.markets[m]?.venue}</span>
                  </td>
                  {HORIZONS.map(([h]) => {
                    const b = data?.books[`${m}|${h}`];
                    return (
                      <td key={h}>
                        <Link href={`/pf-lab/${m.toLowerCase()}/${h}`}>
                          {b ? `${b.open} open · realized ${money(b.realized, b.currency)} · open ${money(b.openPnl, b.currency)}` : "open →"}
                        </Link>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CollapsibleSection>

      <CollapsibleSection id="pf-lab-backtest" title="Backtest comparison — compounded return per year after costs (vs buy & hold)">
        {MARKETS.map((m) => {
          const d = data?.backtest.data[m];
          return (
            <div key={m} style={{ marginBottom: 18 }}>
              <h3 style={{ fontSize: 14, margin: "6px 0" }}>
                {data?.markets[m]?.label ?? m}{" "}
                <span className="pcr-oi-caption">
                  {d ? `${d.from} → ${d.to} · buy & hold ${pct(d.buyHoldLog)}/yr` : ""}
                </span>
              </h3>
              <div className="table-wrap">
                <table style={{ fontSize: 12 }}>
                  <thead>
                    <tr>
                      <th>System</th>
                      {HORIZONS.map(([h, box]) => (
                        <th key={h}>
                          {data?.horizons[h] ?? h} ({box})
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(data?.systems ?? []).map((s) => (
                      <tr key={s.key}>
                        <td>{s.label}</td>
                        {HORIZONS.map(([h]) => {
                          const c = cell(m, h, s.key);
                          const u = c?.underlying;
                          const beats = u?.trades && d?.buyHoldLog !== undefined && (u.logAnnual ?? -99) > d.buyHoldLog;
                          return (
                            <td key={h} style={{ background: beats ? "rgba(46, 160, 67, 0.12)" : undefined }}>
                              {u?.trades ? (
                                <>
                                  <strong style={{ color: (u.logAnnual ?? 0) > 0 ? "var(--green)" : "var(--red)" }}>{pct(u.logAnnual)}</strong>
                                  <span className="pcr-oi-caption">
                                    {" "}
                                    · {u.trades} tr · win {u.win?.toFixed(0)}% · DD {u.maxDD?.toFixed(0)}%
                                  </span>
                                  {c?.spread?.trades ? <div className="pcr-oi-caption">spread model {money(c.spread.annual, "₹")}/yr (1 lot)</div> : null}
                                </>
                              ) : (
                                <span className="pcr-oi-caption">no trades</span>
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })}
        <p className="pcr-oi-caption">
          Green cells beat buy &amp; hold. Returns are compounded per year on one position at a time, after costs (NIFTY 0.03% round trip; BTC / gold 0.16% plus
          assumed funding). NIFTY spread figures are a Black-Scholes model on India VIX, not real option prices. Gold history starts in 2020 (PAXG), so its
          long-term cells rest on very few trades. Generated {data?.backtest.generatedAt ?? "—"}.
        </p>
      </CollapsibleSection>
    </section>
  );
}
