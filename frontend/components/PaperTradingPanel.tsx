"use client";

import { ChevronDown, ChevronRight, Save } from "lucide-react";
import { useEffect, useState } from "react";

import { getPaperTrades, getPaperTradingSettings, updatePaperTradingSettings } from "@/lib/api";
import type { PaperTrade, PaperTradingSettings } from "@/types/live";

const REFRESH_MS = 60000;

const SIGNAL_TYPE_LABEL: Record<PaperTrade["signalType"], string> = {
  signalVsPrice: "Signal vs Price",
  priceBreakout: "Price Breakout",
};

const EXIT_REASON_LABEL: Record<string, string> = {
  target1: "Target 1",
  target2: "Target 2",
  trail: "Trail",
  stop_loss: "Stop loss",
  eod: "EOD",
};

const PHASE_LABEL: Record<PaperTrade["phase"], string> = {
  OPEN_ALL: "All 3 lots open",
  LOT1_BOOKED: "Lot 1 booked",
  LOT2_BOOKED: "Lot 2 booked, trailing lot 3",
};

const SETTINGS_FIELDS: { key: keyof PaperTradingSettings; label: string; suffix: string }[] = [
  { key: "stopLossPercent", label: "Stop loss", suffix: "%" },
  { key: "target1Percent", label: "Target 1 (lot 1)", suffix: "%" },
  { key: "target2Percent", label: "Target 2 (lot 2)", suffix: "%" },
  { key: "trailPercent", label: "Trail (lot 3)", suffix: "%" },
  { key: "niftyLots", label: "NIFTY lots", suffix: "" },
  { key: "niftyLotSize", label: "NIFTY lot size", suffix: "" },
  { key: "sensexLots", label: "SENSEX lots", suffix: "" },
  { key: "sensexLotSize", label: "SENSEX lot size", suffix: "" },
];

const moneyFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });

function formatTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export default function PaperTradingPanel() {
  const [expanded, setExpanded] = useState(false);
  const [trades, setTrades] = useState<PaperTrade[]>([]);
  const [settings, setSettings] = useState<PaperTradingSettings | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!expanded) return;
    let cancelled = false;

    async function load() {
      try {
        const [tradesRes, settingsRes] = await Promise.all([getPaperTrades(), getPaperTradingSettings()]);
        if (cancelled) return;
        setTrades(tradesRes.trades);
        setSettings(settingsRes);
        setDraft((prev) => (Object.keys(prev).length ? prev : toDraft(settingsRes)));
        setError(null);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load paper trades");
      }
    }

    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [expanded]);

  async function onSaveSettings() {
    setSaving(true);
    setMessage(null);
    try {
      const payload: Partial<PaperTradingSettings> = {};
      for (const field of SETTINGS_FIELDS) {
        const raw = draft[field.key];
        if (raw === undefined || raw === "") continue;
        const value = Number(raw);
        if (Number.isFinite(value)) payload[field.key] = value;
      }
      const saved = await updatePaperTradingSettings(payload);
      setSettings(saved);
      setDraft(toDraft(saved));
      setMessage("Settings saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  const openTrades = trades.filter((t) => t.status === "open");
  const closedTrades = trades.filter((t) => t.status === "closed");
  const totalRealized = closedTrades.reduce((sum, t) => sum + t.realizedPnl, 0);

  return (
    <section className="table-section">
      <div className="section-title pcr-oi-title" onClick={() => setExpanded((v) => !v)}>
        <h2 style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
          <button className="icon-button" type="button" title={expanded ? "Collapse" : "Expand"}>
            {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          </button>
          Paper Trades
        </h2>
        <span className="subtext">Simulated 3-lot entries on Signal vs Price &amp; Price Breakout · no real orders</span>
      </div>
      {expanded ? (
        <>
          {error ? <div className="alert error">{error}</div> : null}
          <div className="pcr-oi-section">
            <h3>Settings</h3>
            <p className="pcr-oi-caption">Applied to new entries only — open trades keep the levels they were entered with.</p>
            <div className="paper-trading-settings-grid">
              {SETTINGS_FIELDS.map((field) => (
                <label key={field.key} className="level-field">
                  {field.label}
                  <input
                    className="level-input"
                    type="number"
                    step="0.5"
                    value={draft[field.key] ?? ""}
                    onChange={(event) => setDraft((prev) => ({ ...prev, [field.key]: event.target.value }))}
                  />
                  <span className="subtext">{field.suffix}</span>
                </label>
              ))}
            </div>
            <div className="pcr-oi-badge-row" style={{ marginTop: 10 }}>
              <button className="button secondary" type="button" onClick={onSaveSettings} disabled={saving}>
                <Save size={14} /> Save settings
              </button>
              {message ? <span className="subtext">{message}</span> : null}
            </div>
          </div>

          <div className="pcr-oi-section">
            <h3>Open Trades ({openTrades.length})</h3>
            {openTrades.length === 0 ? (
              <p className="pcr-oi-caption">No open paper trades.</p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Underlying</th>
                      <th>Side</th>
                      <th>Signal</th>
                      <th>Strike</th>
                      <th>Entry Time</th>
                      <th>Entry Premium</th>
                      <th>Status</th>
                      <th>Remaining Lots</th>
                      <th>Peak Premium</th>
                      <th>SL</th>
                      <th>T1</th>
                      <th>T2</th>
                    </tr>
                  </thead>
                  <tbody>
                    {openTrades.map((trade) => (
                      <tr key={trade.id}>
                        <td>{trade.underlying}</td>
                        <td>
                          <span className={`badge ${trade.side === "CE" ? "buy" : "sell"}`}>{trade.side}</span>
                        </td>
                        <td>{SIGNAL_TYPE_LABEL[trade.signalType]}</td>
                        <td>{trade.strike ?? "—"}</td>
                        <td>{formatTime(trade.entryTime)}</td>
                        <td>{moneyFormat.format(trade.entryPremium)}</td>
                        <td>{PHASE_LABEL[trade.phase]}</td>
                        <td>{trade.remainingLots}</td>
                        <td>{trade.peakPremium != null ? moneyFormat.format(trade.peakPremium) : "—"}</td>
                        <td>{moneyFormat.format(trade.stopLossPrice)}</td>
                        <td>{moneyFormat.format(trade.target1Price)}</td>
                        <td>{moneyFormat.format(trade.target2Price)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="pcr-oi-section">
            <h3>Closed Trades ({closedTrades.length})</h3>
            <p className="pcr-oi-caption">
              Total realized P&amp;L:{" "}
              <strong style={{ color: totalRealized >= 0 ? "var(--green)" : "var(--red)" }}>
                {moneyFormat.format(totalRealized)}
              </strong>
            </p>
            {closedTrades.length === 0 ? (
              <p className="pcr-oi-caption">No closed paper trades yet.</p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Underlying</th>
                      <th>Side</th>
                      <th>Signal</th>
                      <th>Strike</th>
                      <th>Entry Time</th>
                      <th>Entry Premium</th>
                      <th>Exits</th>
                      <th>Realized P&amp;L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {closedTrades.map((trade) => (
                      <tr key={trade.id}>
                        <td>{trade.underlying}</td>
                        <td>
                          <span className={`badge ${trade.side === "CE" ? "buy" : "sell"}`}>{trade.side}</span>
                        </td>
                        <td>{SIGNAL_TYPE_LABEL[trade.signalType]}</td>
                        <td>{trade.strike ?? "—"}</td>
                        <td>{formatTime(trade.entryTime)}</td>
                        <td>{moneyFormat.format(trade.entryPremium)}</td>
                        <td>
                          {trade.legs
                            .map(
                              (leg) =>
                                `${EXIT_REASON_LABEL[leg.exitReason] ?? leg.exitReason} @ ${moneyFormat.format(leg.exitPremium)} (${formatTime(leg.exitTime)})`,
                            )
                            .join(", ")}
                        </td>
                        <td style={{ color: trade.realizedPnl >= 0 ? "var(--green)" : "var(--red)" }}>
                          {moneyFormat.format(trade.realizedPnl)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      ) : null}
    </section>
  );
}

function toDraft(settings: PaperTradingSettings): Record<string, string> {
  const result: Record<string, string> = {};
  for (const field of SETTINGS_FIELDS) {
    result[field.key] = String(settings[field.key]);
  }
  return result;
}
