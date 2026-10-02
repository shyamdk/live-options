"use client";

import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  IChartApi,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  LineSeries,
  SeriesMarker,
  Time,
  UTCTimestamp,
} from "lightweight-charts";
import { Maximize2, Minimize2, RefreshCw, Save, Waypoints } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { DailyTotalsTable, fmtUsdSigned, groupDailyTotals } from "@/components/DailyTotals";
import {
  getSimpleCrossoverXautConfig,
  getSimpleCrossoverXautData,
  getSimpleCrossoverXautTrades,
  updateSimpleCrossoverXautConfig,
  updateSimpleCrossoverXautTradeComment,
} from "@/lib/api";
import type { SimpleCrossoverXautConfig, SimpleCrossoverXautData, SimpleCrossoverXautTrade } from "@/types/simple-crossover-xaut";

const REFRESH_MS = 20000;

function fmtDateTime(epochSeconds: number | null | undefined): string {
  if (!epochSeconds) return "—";
  return new Date(epochSeconds * 1000).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function fmtSigned(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "—";
  const sign = value >= 0 ? "+" : "-";
  return `${sign}${Math.abs(value).toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits })}`;
}

function fmtUsdSignedOrDash(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return fmtUsdSigned(value);
}

function fmtDateOnly(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short" });
}

function fmtTimeOnly(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

const DIRECTION_COLOR: Record<string, string> = { Up: "#168448", Down: "#c93535", Sideways: "#8391a3" };
const GAP_TREND_LABEL: Record<string, string> = { increasing: "Increasing", decreasing: "Decreasing", flat: "Flat" };
const EXIT_REASON_LABEL: Record<string, string> = {
  cross_under: "Cross-under",
  cross_over: "Cross-over",
  rsi_peak: "RSI peak",
  rsi_trough: "RSI trough",
  day_boundary: "Day boundary (midnight IST)",
};

export default function SimpleCrossoverXautPage() {
  const [data, setData] = useState<SimpleCrossoverXautData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshAt, setLastRefreshAt] = useState(Date.now());
  const [nowTick, setNowTick] = useState(Date.now());

  useEffect(() => {
    const tick = window.setInterval(() => setNowTick(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, []);

  async function load() {
    setLoading(true);
    setLastRefreshAt(Date.now());
    try {
      const payload = await getSimpleCrossoverXautData();
      setData(payload);
      setError(payload.error ?? null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load data.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  const secondsUntilRefresh = Math.max(0, Math.ceil((REFRESH_MS - (nowTick - lastRefreshAt)) / 1000));
  const current = data?.current;
  const lastCrossover = data?.lastCrossover ?? null;
  const dayDirection = data?.dayDirection ?? null;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Waypoints size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Simple Cross Over - XAUT
          </h1>
          <p>
            EMA8/EMA21 crossover on XAUTUSD (Delta Exchange), 24/7. Up day -&gt; long on an up-crossover; Down day -&gt;
            short on a down-crossover, both requiring the candle to touch (or be within tolerance of) EMA21. No
            stop-loss/target -- signal-only, paper trades.
          </p>
        </div>
      </header>

      <div className="pcr-oi-section">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ margin: 0 }}>XAUTUSD</h3>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="pcr-oi-caption">Auto-refreshes in {secondsUntilRefresh}s</span>
            <button type="button" className="button secondary" onClick={load} disabled={loading}>
              <RefreshCw size={14} /> {loading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        </div>
        {error ? <div className="alert error">{error}</div> : null}

        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
          <div className="metric metric-compact" style={{ flex: "1 1 150px" }}>
            <span>Day direction</span>
            <strong style={{ color: dayDirection ? DIRECTION_COLOR[dayDirection.label] : undefined }}>
              {dayDirection ? dayDirection.label : "—"}
            </strong>
            <span className="pcr-oi-caption">
              {dayDirection ? `${fmtSigned(dayDirection.changePercent)}% from open ($${fmtNum(dayDirection.dayOpen)})` : ""}
            </span>
          </div>
          <div className="metric metric-compact" style={{ flex: "1 1 150px" }}>
            <span>Last crossover</span>
            <strong style={{ color: lastCrossover ? (lastCrossover.direction === "up" ? "#168448" : "#c93535") : undefined }}>
              {lastCrossover ? `${lastCrossover.direction === "up" ? "Over" : "Under"} @ $${fmtNum(lastCrossover.price)}` : "—"}
            </strong>
            <span className="pcr-oi-caption">{lastCrossover ? fmtDateTime(lastCrossover.time) : ""}</span>
          </div>
          <div className="metric metric-compact" style={{ flex: "1 1 110px" }}>
            <span>RSI @ last crossover</span>
            <strong>{fmtNum(lastCrossover?.rsi, 1)}</strong>
          </div>
          <div className="metric metric-compact" style={{ flex: "1 1 110px" }}>
            <span>EMA21 (current)</span>
            <strong>${fmtNum(current?.emaSlow)}</strong>
          </div>
          <div className="metric metric-compact" style={{ flex: "1 1 110px" }}>
            <span>EMA8 (current)</span>
            <strong>${fmtNum(current?.emaFast)}</strong>
          </div>
          <div className="metric metric-compact" style={{ flex: "1 1 110px" }}>
            <span>RSI(8) (current)</span>
            <strong>{fmtNum(current?.rsi, 1)}</strong>
          </div>
          <div className="metric metric-compact" style={{ flex: "1 1 110px" }}>
            <span>RSI SMA(5) (current)</span>
            <strong>{fmtNum(current?.rsiSma, 1)}</strong>
          </div>
          <div className="metric metric-compact" style={{ flex: "1 1 150px" }}>
            <span>EMA gap (8 − 21)</span>
            <strong style={{ color: current?.gap != null ? (current.gap >= 0 ? "#168448" : "#c93535") : undefined }}>
              {fmtSigned(current?.gap)}
            </strong>
            <span className="pcr-oi-caption">
              {data?.gapTrend ? `${GAP_TREND_LABEL[data.gapTrend] ?? data.gapTrend} (last 3)` : ""}
            </span>
          </div>
        </div>

        <div style={{ marginTop: 12 }}>
          <SimpleCrossoverXautChart data={data} />
        </div>
      </div>

      <StrategyConditionsPanel />
      <PaperTradesSection />
    </section>
  );
}

function StrategyConditionsPanel() {
  const [config, setConfig] = useState<SimpleCrossoverXautConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [longDraft, setLongDraft] = useState("");
  const [shortDraft, setShortDraft] = useState("");
  const [marginDraft, setMarginDraft] = useState("");
  const [leverageDraft, setLeverageDraft] = useState("");
  const [minGapDraft, setMinGapDraft] = useState("");
  const [maxGapDraft, setMaxGapDraft] = useState("");

  useEffect(() => {
    getSimpleCrossoverXautConfig()
      .then((c) => {
        setConfig(c);
        setLongDraft(String(c.rsiLongExitThreshold));
        setShortDraft(String(c.rsiShortExitThreshold));
        setMarginDraft(String(c.marginPerTrade));
        setLeverageDraft(String(c.leverage));
        setMinGapDraft(String(c.minEntryGap));
        setMaxGapDraft(String(c.maxEntryGap));
      })
      .catch((exc) => setError(exc instanceof Error ? exc.message : "Failed to load filter config."));
  }, []);

  async function save(updates: Partial<SimpleCrossoverXautConfig>) {
    setSaving(true);
    setError(null);
    try {
      const updated = await updateSimpleCrossoverXautConfig(updates);
      setConfig(updated);
      setLongDraft(String(updated.rsiLongExitThreshold));
      setShortDraft(String(updated.rsiShortExitThreshold));
      setMarginDraft(String(updated.marginPerTrade));
      setLeverageDraft(String(updated.leverage));
      setMinGapDraft(String(updated.minEntryGap));
      setMaxGapDraft(String(updated.maxEntryGap));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to update filter config.");
    } finally {
      setSaving(false);
    }
  }

  function saveLongThreshold() {
    const value = Number(longDraft);
    if (!config || Number.isNaN(value) || value === config.rsiLongExitThreshold) return;
    save({ rsiLongExitThreshold: value });
  }

  function saveShortThreshold() {
    const value = Number(shortDraft);
    if (!config || Number.isNaN(value) || value === config.rsiShortExitThreshold) return;
    save({ rsiShortExitThreshold: value });
  }

  function saveMargin() {
    const value = Number(marginDraft);
    if (!config || Number.isNaN(value) || value <= 0 || value === config.marginPerTrade) return;
    save({ marginPerTrade: value });
  }

  function saveLeverage() {
    const value = Number(leverageDraft);
    if (!config || Number.isNaN(value) || value <= 0 || value === config.leverage) return;
    save({ leverage: value });
  }

  function saveMinGap() {
    const value = Number(minGapDraft);
    if (!config || Number.isNaN(value) || value < 0 || value === config.minEntryGap) return;
    save({ minEntryGap: value });
  }

  function saveMaxGap() {
    const value = Number(maxGapDraft);
    if (!config || Number.isNaN(value) || value < 0 || value === config.maxEntryGap) return;
    save({ maxEntryGap: value });
  }

  return (
    <div className="pcr-oi-section">
      <h3 style={{ margin: "0 0 4px" }}>Entry &amp; exit conditions</h3>
      {error ? <div className="alert error">{error}</div> : null}

      <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={config?.dayDirectionFilterEnabled ?? false}
          disabled={!config || saving}
          onChange={() => save({ dayDirectionFilterEnabled: !config?.dayDirectionFilterEnabled })}
        />
        Require day direction to match side (Up -&gt; long only, Down -&gt; short only)
      </label>
      <p className="pcr-oi-caption" style={{ margin: "4px 0 10px" }}>
        {config?.dayDirectionFilterEnabled
          ? "On -- entries only taken on the side matching today's direction; Sideways days take no entries."
          : "Off -- long and short are each evaluated independently every tick; whichever side's own crossover condition is satisfied enters, regardless of day direction."}
      </p>

      <label
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          cursor: config?.dayDirectionFilterEnabled ? "pointer" : "default",
          opacity: config?.dayDirectionFilterEnabled ? 1 : 0.5,
          marginLeft: 20,
        }}
      >
        <input
          type="checkbox"
          checked={config?.tradeOnSideways ?? false}
          disabled={!config || saving || !config.dayDirectionFilterEnabled}
          onChange={() => save({ tradeOnSideways: !config?.tradeOnSideways })}
        />
        Trade on Sideways days too
      </label>
      <p className="pcr-oi-caption" style={{ margin: "4px 0 10px", marginLeft: 20, opacity: config?.dayDirectionFilterEnabled ? 1 : 0.5 }}>
        {config?.tradeOnSideways
          ? "On -- Sideways days evaluate long and short independently, same as with the direction match off; Up/Down days still gate to a single side."
          : "Off -- Sideways days take no entries at all (only applies while the day-direction filter above is on)."}
      </p>

      <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={config?.rsiExitEnabled ?? false}
          disabled={!config || saving}
          onChange={() => save({ rsiExitEnabled: !config?.rsiExitEnabled })}
        />
        Exit on RSI extreme
      </label>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", margin: "6px 0 0", opacity: config?.rsiExitEnabled ? 1 : 0.5 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
          Long exit RSI &gt;=
          <input
            type="number"
            value={longDraft}
            onChange={(e) => setLongDraft(e.target.value)}
            onBlur={saveLongThreshold}
            onKeyDown={(e) => e.key === "Enter" && saveLongThreshold()}
            disabled={!config || !config.rsiExitEnabled || saving}
            style={{ width: 70, fontSize: 12, padding: "2px 6px" }}
          />
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
          Short exit RSI &lt;=
          <input
            type="number"
            value={shortDraft}
            onChange={(e) => setShortDraft(e.target.value)}
            onBlur={saveShortThreshold}
            onKeyDown={(e) => e.key === "Enter" && saveShortThreshold()}
            disabled={!config || !config.rsiExitEnabled || saving}
            style={{ width: 70, fontSize: 12, padding: "2px 6px" }}
          />
        </label>
      </div>
      <p className="pcr-oi-caption" style={{ margin: "6px 0 0" }}>
        Long exits when RSI rises to or above the threshold; short exits when RSI falls to or below the threshold.
        Cross-under/cross-over and the midnight square-off still apply either way.
      </p>

      <h4 style={{ margin: "14px 0 6px", fontSize: 13 }}>Position sizing</h4>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
          Margin per trade $
          <input
            type="number"
            value={marginDraft}
            onChange={(e) => setMarginDraft(e.target.value)}
            onBlur={saveMargin}
            onKeyDown={(e) => e.key === "Enter" && saveMargin()}
            disabled={!config || saving}
            style={{ width: 80, fontSize: 12, padding: "2px 6px" }}
          />
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
          Leverage
          <input
            type="number"
            value={leverageDraft}
            onChange={(e) => setLeverageDraft(e.target.value)}
            onBlur={saveLeverage}
            onKeyDown={(e) => e.key === "Enter" && saveLeverage()}
            disabled={!config || saving}
            style={{ width: 70, fontSize: 12, padding: "2px 6px" }}
          />
          x
        </label>
      </div>
      <p className="pcr-oi-caption" style={{ margin: "6px 0 0" }}>
        Quantity at entry = margin &times; leverage / entry price (Delta lets XAUTUSD go up to 50x). Charges are a
        fixed % of notional, so they scale with $ P&amp;L the same way regardless of size -- bigger margin or
        leverage changes the dollar amounts but not the fee-to-P&amp;L ratio. Only affects new entries; open/closed
        trades keep the margin and leverage they were opened with.
      </p>

      <h4 style={{ margin: "14px 0 6px", fontSize: 13 }}>Entry EMA-gap filter</h4>
      <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={config?.entryGapFilterEnabled ?? false}
          disabled={!config || saving}
          onChange={() => save({ entryGapFilterEnabled: !config?.entryGapFilterEnabled })}
        />
        Only enter when the EMA8-EMA21 gap is in range
      </label>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", margin: "6px 0 0", opacity: config?.entryGapFilterEnabled ? 1 : 0.5 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
          Min gap
          <input
            type="number"
            step="0.01"
            value={minGapDraft}
            onChange={(e) => setMinGapDraft(e.target.value)}
            onBlur={saveMinGap}
            onKeyDown={(e) => e.key === "Enter" && saveMinGap()}
            disabled={!config || !config.entryGapFilterEnabled || saving}
            style={{ width: 70, fontSize: 12, padding: "2px 6px" }}
          />
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
          Max gap
          <input
            type="number"
            step="0.01"
            value={maxGapDraft}
            onChange={(e) => setMaxGapDraft(e.target.value)}
            onBlur={saveMaxGap}
            onKeyDown={(e) => e.key === "Enter" && saveMaxGap()}
            disabled={!config || !config.entryGapFilterEnabled || saving}
            style={{ width: 70, fontSize: 12, padding: "2px 6px" }}
          />
        </label>
      </div>
      <p className="pcr-oi-caption" style={{ margin: "6px 0 0" }}>
        Based on this engine&apos;s own first 36 trades: a gap below min was a weak/barely-confirmed cross (10-13%
        win rate), a gap above max was already-extended/chasing (10-14% win rate) -- the 0.06-0.15 band in between
        won 64% of the time. Rejects the entry (logged) if the gap falls outside this range; cross-under/cross-over
        and end-of-day/midnight close are unaffected.
      </p>
    </div>
  );
}

function PaperTradesSection() {
  const [trades, setTrades] = useState<SimpleCrossoverXautTrade[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const payload = await getSimpleCrossoverXautTrades();
        if (!cancelled) {
          setTrades(payload.trades);
          setError(null);
        }
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : "Failed to load trades.");
      }
    }
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  async function saveComment(id: number, comment: string) {
    const updated = await updateSimpleCrossoverXautTradeComment(id, comment);
    setTrades((prev) => prev.map((t) => (t.id === id ? updated : t)));
  }

  const open = trades.filter((t) => t.status === "open");
  const closed = trades.filter((t) => t.status === "closed");

  return (
    <div className="pcr-oi-section">
      <h3 style={{ margin: "0 0 6px" }}>Paper Trades</h3>
      <p className="pcr-oi-caption" style={{ margin: "0 0 8px" }}>
        Long exits on cross-under or RSI &gt;= exit threshold; short exits on cross-over or RSI &lt;= exit threshold;
        either squares off at midnight IST regardless. Charges are Delta Exchange&apos;s published XAUTUSD taker fee
        (0.01% per leg&apos;s notional) on both legs; open trades show an estimate as if exiting right now.
      </p>
      {error ? <div className="alert error">{error}</div> : null}

      <DailyTotalsTable
        rows={groupDailyTotals(
          closed,
          (t) => t.exitTime,
          (t) => t.realizedPnl,
          (t) => t.netPnl,
        )}
        formatAmount={fmtUsdSigned}
      />

      <h4 style={{ margin: "12px 0 4px", fontSize: 13 }}>Open Trades ({open.length})</h4>
      {open.length === 0 ? (
        <p className="pcr-oi-caption">No open trades.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Time</th>
                <th>Side</th>
                <th>Qty</th>
                <th>Margin</th>
                <th>Entry</th>
                <th>Current</th>
                <th>Current P&amp;L</th>
                <th>Est. Charges</th>
                <th>Est. Net P&amp;L</th>
                <th>Est. Net %</th>
                <th>EMA Gap</th>
                <th>Comment</th>
              </tr>
            </thead>
            <tbody>
              {open.map((t) => {
                const currentPnl =
                  t.currentPrice != null
                    ? t.side === "long"
                      ? (t.currentPrice - t.entryPrice) * t.quantity
                      : (t.entryPrice - t.currentPrice) * t.quantity
                    : null;
                return (
                  <tr key={t.id}>
                    <td>{fmtDateOnly(t.entryTime)}</td>
                    <td>{fmtTimeOnly(t.entryTime)}</td>
                    <td>
                      <span className={`badge ${t.side === "long" ? "buy" : "sell"}`}>{t.side}</span>
                    </td>
                    <td>{fmtNum(t.quantity, 4)}</td>
                    <td>{t.margin != null ? `$${fmtNum(t.margin, 0)} @ ${fmtNum(t.leverage ?? 0, 0)}x` : "—"}</td>
                    <td>${fmtNum(t.entryPrice)}</td>
                    <td>{t.currentPrice != null ? `$${fmtNum(t.currentPrice)}` : "—"}</td>
                    <td style={{ color: currentPnl != null ? (currentPnl >= 0 ? "var(--green)" : "var(--red)") : undefined }}>
                      {currentPnl != null ? fmtUsdSigned(currentPnl) : "—"}
                    </td>
                    <td>{t.charges != null ? `$${fmtNum(t.charges)}` : "—"}</td>
                    <td style={{ color: t.netPnl != null ? (t.netPnl >= 0 ? "var(--green)" : "var(--red)") : undefined }}>
                      {t.netPnl != null ? fmtUsdSigned(t.netPnl) : "—"}
                    </td>
                    <td style={{ color: t.netPnlPercent != null ? (t.netPnlPercent >= 0 ? "var(--green)" : "var(--red)") : undefined }}>
                      {t.netPnlPercent != null ? `${fmtSigned(t.netPnlPercent, 2)}%` : "—"}
                    </td>
                    <td>{fmtSigned(t.entryEmaGap)}</td>
                    <td>
                      <CommentCell value={t.comment} onSave={(v) => saveComment(t.id, v)} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <h4 style={{ margin: "16px 0 4px", fontSize: 13 }}>Closed Trades ({closed.length})</h4>
      {closed.length === 0 ? (
        <p className="pcr-oi-caption">No closed trades yet.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Entry Time</th>
                <th>Exit Time</th>
                <th>Side</th>
                <th>Qty</th>
                <th>Margin</th>
                <th>Entry</th>
                <th>Exit</th>
                <th>Exit Reason</th>
                <th>Realized P&amp;L</th>
                <th>Charges</th>
                <th>Net P&amp;L</th>
                <th>Net %</th>
                <th>EMA Gap</th>
                <th>Comment</th>
              </tr>
            </thead>
            <tbody>
              {closed.map((t) => (
                <tr key={t.id}>
                  <td>{fmtDateOnly(t.entryTime)}</td>
                  <td>{fmtTimeOnly(t.entryTime)}</td>
                  <td>{t.exitTime != null ? fmtTimeOnly(t.exitTime) : "—"}</td>
                  <td>
                    <span className={`badge ${t.side === "long" ? "buy" : "sell"}`}>{t.side}</span>
                  </td>
                  <td>{fmtNum(t.quantity, 4)}</td>
                  <td>{t.margin != null ? `$${fmtNum(t.margin, 0)} @ ${fmtNum(t.leverage ?? 0, 0)}x` : "—"}</td>
                  <td>${fmtNum(t.entryPrice)}</td>
                  <td>{t.exitPrice != null ? `$${fmtNum(t.exitPrice)}` : "—"}</td>
                  <td>{t.exitReason ? EXIT_REASON_LABEL[t.exitReason] ?? t.exitReason : "—"}</td>
                  <td style={{ color: (t.realizedPnl ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                    {fmtUsdSignedOrDash(t.realizedPnl)}
                  </td>
                  <td>{t.charges != null ? `$${fmtNum(t.charges)}` : "—"}</td>
                  <td style={{ color: (t.netPnl ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                    {fmtUsdSignedOrDash(t.netPnl)}
                  </td>
                  <td style={{ color: (t.netPnlPercent ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                    {t.netPnlPercent != null ? `${fmtSigned(t.netPnlPercent, 2)}%` : "—"}
                  </td>
                  <td>{fmtSigned(t.entryEmaGap)}</td>
                  <td>
                    <CommentCell value={t.comment} onSave={(v) => saveComment(t.id, v)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CommentCell({ value, onSave }: { value: string | null; onSave: (v: string) => Promise<void> }) {
  const [draft, setDraft] = useState(value ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(value ?? "");
  }, [value]);

  const dirty = draft !== (value ?? "");

  async function save() {
    if (!dirty || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onSave(draft);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to save comment.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 160 }}>
      <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              save();
            }
          }}
          onBlur={save}
          placeholder="Add a note…"
          style={{ flex: 1, fontSize: 12, padding: "2px 6px" }}
        />
        <button type="button" className="icon-button" title="Save" onClick={save} disabled={!dirty || saving}>
          <Save size={13} />
        </button>
      </div>
      {error ? <span style={{ fontSize: 11, color: "var(--red)" }}>{error}</span> : null}
    </div>
  );
}

function SimpleCrossoverXautChart({ data }: { data: SimpleCrossoverXautData | null }) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    function onFullscreenChange() {
      setIsFullscreen(document.fullscreenElement === wrapperRef.current);
    }
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, []);

  async function toggleFullscreen() {
    if (!wrapperRef.current) return;
    if (document.fullscreenElement) {
      await document.exitFullscreen();
    } else {
      await wrapperRef.current.requestFullscreen();
    }
  }

  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const emaFastSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const emaSlowSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const rsiSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const rsiSmaSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const rsiOverboughtBandRef = useRef<ISeriesApi<"Area"> | null>(null);
  const rsiOversoldBandRef = useRef<ISeriesApi<"Area"> | null>(null);
  const gapSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#252a32" },
      grid: { vertLines: { color: "#edf0f4" }, horzLines: { color: "#edf0f4" } },
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight || 320,
      timeScale: { timeVisible: true, secondsVisible: false, tickMarkFormatter: (time: Time) => formatIstTime(time) },
      localization: { timeFormatter: (time: Time) => formatIstTime(time) },
    });
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#168448",
      downColor: "#c93535",
      borderVisible: false,
      wickUpColor: "#168448",
      wickDownColor: "#c93535",
    });
    const emaFast = chart.addSeries(LineSeries, { color: "#e58a1a", lineWidth: 2, title: "EMA8" });
    const emaSlow = chart.addSeries(LineSeries, { color: "#2f8f3e", lineWidth: 2, title: "EMA21" });

    const gapSeries = chart.addSeries(LineSeries, { color: "#5b6b7c", lineWidth: 2, title: "EMA Gap" }, 1);
    gapSeries.createPriceLine({ price: 0, color: "#8391a3", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "0" });

    const rsiOverboughtBand = chart.addSeries(
      AreaSeries,
      {
        topColor: "rgba(22, 132, 72, 0.12)",
        bottomColor: "rgba(22, 132, 72, 0.12)",
        lineVisible: false,
        invertFilledArea: true,
        crosshairMarkerVisible: false,
        lastValueVisible: false,
        priceLineVisible: false,
      },
      2,
    );
    const rsiOversoldBand = chart.addSeries(
      AreaSeries,
      {
        topColor: "rgba(201, 53, 53, 0.12)",
        bottomColor: "rgba(201, 53, 53, 0.12)",
        lineVisible: false,
        crosshairMarkerVisible: false,
        lastValueVisible: false,
        priceLineVisible: false,
      },
      2,
    );

    const rsiSeries = chart.addSeries(LineSeries, { color: "#7b5fc7", lineWidth: 2, title: "RSI(8)" }, 2);
    rsiSeries.createPriceLine({ price: 70, color: "#c93535", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "70" });
    rsiSeries.createPriceLine({ price: 30, color: "#168448", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "30" });
    const rsiSmaSeries = chart.addSeries(LineSeries, { color: "#2b8fd6", lineWidth: 2, title: "RSI SMA(5)" }, 2);

    chart.panes()[1]?.setHeight(80);
    chart.panes()[2]?.setHeight(110);

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    emaFastSeriesRef.current = emaFast;
    emaSlowSeriesRef.current = emaSlow;
    gapSeriesRef.current = gapSeries;
    rsiSeriesRef.current = rsiSeries;
    rsiSmaSeriesRef.current = rsiSmaSeries;
    rsiOverboughtBandRef.current = rsiOverboughtBand;
    rsiOversoldBandRef.current = rsiOversoldBand;
    markersRef.current = createSeriesMarkers(candleSeries, []);

    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth, height: containerRef.current.clientHeight });
      }
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      markersRef.current?.detach();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      emaFastSeriesRef.current = null;
      emaSlowSeriesRef.current = null;
      gapSeriesRef.current = null;
      rsiSeriesRef.current = null;
      rsiSmaSeriesRef.current = null;
      rsiOverboughtBandRef.current = null;
      rsiOversoldBandRef.current = null;
      markersRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!data || !candleSeriesRef.current) return;
    const times = data.candles.map((c) => c.time as UTCTimestamp);
    candleSeriesRef.current.setData(
      data.candles.map((c) => ({ time: c.time as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })),
    );
    emaFastSeriesRef.current?.setData(numericSeries(times, data.emaFastValues));
    emaSlowSeriesRef.current?.setData(numericSeries(times, data.emaSlowValues));
    gapSeriesRef.current?.setData(numericSeries(times, data.gapValues));
    rsiSeriesRef.current?.setData(numericSeries(times, data.rsiValues));
    rsiSmaSeriesRef.current?.setData(numericSeries(times, data.rsiSmaValues));
    rsiOverboughtBandRef.current?.setData(times.map((time) => ({ time, value: 70 })));
    rsiOversoldBandRef.current?.setData(times.map((time) => ({ time, value: 30 })));

    if (markersRef.current) {
      const markers: SeriesMarker<Time>[] = data.crossovers.map((c) => ({
        time: c.time as UTCTimestamp,
        position: c.direction === "up" ? "belowBar" : "aboveBar",
        color: c.direction === "up" ? "#168448" : "#c93535",
        shape: c.direction === "up" ? "arrowUp" : "arrowDown",
        text: c.direction === "up" ? "Over" : "Under",
      }));
      markersRef.current.setMarkers(markers);
    }
  }, [data]);

  return (
    <div
      ref={wrapperRef}
      style={
        isFullscreen
          ? { width: "100%", height: "100vh", display: "flex", flexDirection: "column", background: "#fff", padding: 12 }
          : { width: "100%" }
      }
    >
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: isFullscreen ? 8 : 4 }}>
        <button type="button" className="icon-button" title={isFullscreen ? "Exit full screen" : "Full screen"} onClick={toggleFullscreen}>
          {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        </button>
      </div>
      <div ref={containerRef} style={isFullscreen ? { width: "100%", flex: 1 } : { width: "100%", height: 320 }} />
    </div>
  );
}

function numericSeries(times: UTCTimestamp[], values: (number | null)[]): { time: UTCTimestamp; value: number }[] {
  return values
    .map((value, i) => (value === null ? null : { time: times[i], value }))
    .filter((point): point is { time: UTCTimestamp; value: number } => point !== null);
}

function formatIstTime(time: Time): string {
  if (typeof time !== "number") return String(time);
  return new Date(time * 1000).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
