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

import { DailyTotalsTable, groupDailyTotals } from "@/components/DailyTotals";
import {
  getSimpleCrossoverConfig,
  getSimpleCrossoverData,
  getSimpleCrossoverTrades,
  updateSimpleCrossoverConfig,
  updateSimpleCrossoverTradeComment,
} from "@/lib/api";
import type { SimpleCrossoverConfig, SimpleCrossoverData, SimpleCrossoverSide, SimpleCrossoverTrade } from "@/types/simple-crossover";

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
  return value.toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function fmtSigned(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "—";
  const sign = value >= 0 ? "+" : "-";
  return `${sign}${Math.abs(value).toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits })}`;
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
  target_5: "Target +5%",
  target_10: "Target +10%",
  stop_loss: "Stop loss",
  trailing_stop: "Trailing stop",
  eod: "End of day",
};


export default function SimpleCrossoverPage() {
  const [side, setSide] = useState<SimpleCrossoverSide>("CE");
  const [autoSelected, setAutoSelected] = useState(false);
  const [dayDirectionLabel, setDayDirectionLabel] = useState<string | null>(null);
  const lastAutoDirectionRef = useRef<string | null>(null);

  const [config, setConfig] = useState<SimpleCrossoverConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);

  const [trades, setTrades] = useState<SimpleCrossoverTrade[]>([]);
  const [tradesError, setTradesError] = useState<string | null>(null);

  useEffect(() => {
    getSimpleCrossoverConfig()
      .then(setConfig)
      .catch((exc) => setConfigError(exc instanceof Error ? exc.message : "Failed to load strategy settings."));
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadTrades() {
      try {
        const payload = await getSimpleCrossoverTrades();
        if (!cancelled) {
          setTrades(payload.trades);
          setTradesError(null);
        }
      } catch (exc) {
        if (!cancelled) setTradesError(exc instanceof Error ? exc.message : "Failed to load trades.");
      }
    }
    loadTrades();
    const timer = window.setInterval(loadTrades, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  async function saveComment(id: number, comment: string) {
    const updated = await updateSimpleCrossoverTradeComment(id, comment);
    setTrades((prev) => prev.map((t) => (t.id === id ? { ...t, comment: updated.comment } : t)));
  }

  // With the day-direction filter off, the engine evaluates CE and PE
  // independently every poll (each enters only on its own up-crossover), so
  // show both sides next to each other instead of one toggled view.
  const splitView = config !== null && !config.dayDirectionFilterEnabled;

  // Auto-picks the side that matches today's direction (bearish day -> PE,
  // bullish -> CE) the moment the direction is first known or changes --
  // but only then, so it doesn't fight a manual toggle click every refresh
  // while the direction stays the same.
  useEffect(() => {
    if (!dayDirectionLabel || dayDirectionLabel === "Sideways") return;
    const wantedSide: SimpleCrossoverSide = dayDirectionLabel === "Down" ? "PE" : "CE";
    if (lastAutoDirectionRef.current !== dayDirectionLabel) {
      lastAutoDirectionRef.current = dayDirectionLabel;
      setSide(wantedSide);
      setAutoSelected(true);
    }
  }, [dayDirectionLabel]);

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Waypoints size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Simple Cross Over
          </h1>
          <p>
            Paper trade NIFTY options on an upward EMA8/EMA21 crossover. Exit on cross-under, stop loss, staged targets,
            or the 15:30 square-off.
          </p>
        </div>
        {splitView ? null : (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
            <div className="toolbar">
              {(["CE", "PE"] as SimpleCrossoverSide[]).map((s) => (
                <button
                  key={s}
                  type="button"
                  className="button secondary"
                  style={s === side ? { background: "var(--accent, #2368b6)", color: "#fff" } : undefined}
                  onClick={() => {
                    setSide(s);
                    setAutoSelected(false);
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
            {autoSelected ? (
              <span className="pcr-oi-caption">Auto-selected for today&apos;s {dayDirectionLabel?.toLowerCase()} bias</span>
            ) : null}
          </div>
        )}
      </header>

      {splitView ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 560px), 1fr))",
            gap: 12,
            alignItems: "start",
          }}
        >
          {(["CE", "PE"] as SimpleCrossoverSide[]).map((s) => (
            <div key={s} style={{ minWidth: 0 }}>
              <SideMarketPanel side={s} trades={trades.filter((t) => t.side === s)} />
              <PaperTradesSection
                title={`${s} Paper Trades`}
                trades={trades.filter((t) => t.side === s)}
                error={tradesError}
                onSaveComment={saveComment}
                showSide={false}
              />
            </div>
          ))}
        </div>
      ) : (
        <SideMarketPanel side={side} trades={trades.filter((t) => t.side === side)} onDayDirection={setDayDirectionLabel} />
      )}

      <StrategyConditionsPanel config={config} setConfig={setConfig} loadError={configError} />
      {splitView ? null : (
        <PaperTradesSection title="Paper Trades" trades={trades} error={tradesError} onSaveComment={saveComment} showSide />
      )}
    </section>
  );
}

function SideMarketPanel({
  side,
  trades,
  onDayDirection,
}: {
  side: SimpleCrossoverSide;
  trades: SimpleCrossoverTrade[];
  onDayDirection?: (label: string | null) => void;
}) {
  const [data, setData] = useState<SimpleCrossoverData | null>(null);
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
      const payload = await getSimpleCrossoverData(side);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [side]);

  useEffect(() => {
    onDayDirection?.(data?.dayDirection?.label ?? null);
  }, [data?.dayDirection?.label, onDayDirection]);

  const secondsUntilRefresh = Math.max(0, Math.ceil((REFRESH_MS - (nowTick - lastRefreshAt)) / 1000));
  const current = data?.current;
  const lastCrossover = data?.lastCrossover ?? null;
  const dayDirection = data?.dayDirection ?? null;

  return (
    <div className="pcr-oi-section">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <h3 style={{ margin: 0 }}>
          NIFTY {side} {data?.strike ? `${data.strike}` : ""}
          <span className="pcr-oi-caption" style={{ marginLeft: 8 }}>
            {data?.expiry ? `exp ${data.expiry}` : ""}
            {data?.timeframeMinutes ? ` · ${data.timeframeMinutes}-min candles` : ""}
          </span>
        </h3>
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
            {dayDirection ? `${fmtSigned(dayDirection.changePercent)}% from open (${fmtNum(dayDirection.dayOpen)})` : ""}
          </span>
        </div>
        <div className="metric metric-compact" style={{ flex: "1 1 150px" }}>
          <span>Last crossover</span>
          <strong style={{ color: lastCrossover ? (lastCrossover.direction === "up" ? "#168448" : "#c93535") : undefined }}>
            {lastCrossover ? `${lastCrossover.direction === "up" ? "Over" : "Under"} @ ${fmtNum(lastCrossover.price)}` : "—"}
          </strong>
          <span className="pcr-oi-caption">{lastCrossover ? fmtDateTime(lastCrossover.time) : ""}</span>
        </div>
        <div className="metric metric-compact" style={{ flex: "1 1 110px" }}>
          <span>RSI @ last crossover</span>
          <strong>{fmtNum(lastCrossover?.rsi, 1)}</strong>
        </div>
        <div className="metric metric-compact" style={{ flex: "1 1 110px" }}>
          <span>EMA21 (current)</span>
          <strong>{fmtNum(current?.emaSlow)}</strong>
        </div>
        <div className="metric metric-compact" style={{ flex: "1 1 110px" }}>
          <span>EMA8 (current)</span>
          <strong>{fmtNum(current?.emaFast)}</strong>
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
        <SimpleCrossoverChart data={data} trades={trades} />
      </div>
    </div>
  );
}

function StrategyConditionsPanel({
  config,
  setConfig,
  loadError,
}: {
  config: SimpleCrossoverConfig | null;
  setConfig: (value: SimpleCrossoverConfig) => void;
  loadError: string | null;
}) {
  const [stopLossDraft, setStopLossDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (config) setStopLossDraft(String(config.stopLossPercent));
  }, [config]);

  async function save(updates: Partial<SimpleCrossoverConfig>) {
    setSaving(true);
    setError(null);
    try {
      const updated = await updateSimpleCrossoverConfig(updates);
      setConfig(updated);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to update strategy settings.");
    } finally {
      setSaving(false);
    }
  }

  function saveStopLoss() {
    const value = Number(stopLossDraft);
    if (!config || !Number.isFinite(value) || value <= 0 || value >= 100 || value === config.stopLossPercent) return;
    void save({ stopLossPercent: value });
  }

  const shownError = error ?? loadError;

  return (
    <div className="pcr-oi-section">
      <h3 style={{ margin: "0 0 4px" }}>Entry &amp; exit conditions</h3>
      {shownError ? <div className="alert error">{shownError}</div> : null}

      <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={config?.dayDirectionFilterEnabled ?? false}
          disabled={!config || saving}
          onChange={() => void save({ dayDirectionFilterEnabled: !config?.dayDirectionFilterEnabled })}
        />
        Require day direction to match side (Up -&gt; CE only, Down -&gt; PE only)
      </label>
      <p className="pcr-oi-caption" style={{ margin: "4px 0 10px" }}>
        {config?.dayDirectionFilterEnabled
          ? "Entries follow the selected side; sideways days are blocked unless enabled below."
          : "Both sides: CE and PE each enter only on their own upward crossover, regardless of day direction, shown side by side above."}
      </p>

      <label style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: 20, opacity: config?.dayDirectionFilterEnabled ? 1 : 0.5 }}>
        <input
          type="checkbox"
          checked={config?.tradeOnSideways ?? false}
          disabled={!config || saving || !config.dayDirectionFilterEnabled}
          onChange={() => void save({ tradeOnSideways: !config?.tradeOnSideways })}
        />
        Trade on Sideways days too
      </label>

      <h4 style={{ margin: "14px 0 6px", fontSize: 13 }}>Candle timeframe</h4>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        {([1, 3] as const).map((minutes) => (
          <button
            key={minutes}
            type="button"
            className="button secondary"
            disabled={!config || saving}
            style={config?.timeframeMinutes === minutes ? { background: "var(--accent, #2368b6)", color: "#fff" } : undefined}
            onClick={() => config?.timeframeMinutes !== minutes && void save({ timeframeMinutes: minutes })}
          >
            {minutes} min
          </button>
        ))}
      </div>
      <p className="pcr-oi-caption" style={{ margin: "4px 0 0" }}>
        EMA8/EMA21 crossover entries and cross-under exits use completed candles of this size (3 min is built from 1-min
        candles, aligned to 09:15). Fewer, slower signals on 3 min. Open trades keep the timeframe they entered on.
      </p>

      <h4 style={{ margin: "14px 0 6px", fontSize: 13 }}>Stop loss</h4>
      <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
        Fixed stop loss
        <input
          type="number"
          min="0.1"
          max="99.9"
          step="0.5"
          value={stopLossDraft}
          onChange={(event) => setStopLossDraft(event.target.value)}
          onBlur={saveStopLoss}
          onKeyDown={(event) => event.key === "Enter" && saveStopLoss()}
          disabled={!config || saving}
          style={{ width: 76, fontSize: 12, padding: "2px 6px" }}
        />
        %
      </label>
      <p className="pcr-oi-caption" style={{ margin: "4px 0 0" }}>
        Applies to open lots until the final lot enters trailing mode. Three 65-unit lots per entry; scale out at +5% and +10%, then trail the last lot in +5% steps. All remaining lots close at 15:30.
      </p>
    </div>
  );
}

function PaperTradesSection({
  title,
  trades,
  error,
  onSaveComment,
  showSide,
}: {
  title: string;
  trades: SimpleCrossoverTrade[];
  error: string | null;
  onSaveComment: (id: number, comment: string) => Promise<void>;
  showSide: boolean;
}) {
  const open = trades.filter((t) => t.status === "open");
  const closed = trades.filter((t) => t.status === "closed");

  return (
    <div className="pcr-oi-section">
      <h3 style={{ margin: "0 0 6px" }}>{title}</h3>
      <p className="pcr-oi-caption" style={{ margin: "0 0 8px" }}>
        Three 65-unit lots per entry: sell one at +5%, one at +10%, then trail the last lot in +5% steps. The configurable
        stop applies to open lots until the final lot enters trailing mode. Open-trade charges and net P&amp;L include
        an estimated exit at the current premium.
      </p>
      {error ? <div className="alert error">{error}</div> : null}

      <DailyTotalsTable
        rows={groupDailyTotals(
          closed,
          (t) => t.exitTime,
          (t) => t.realizedPnl,
          (t) => t.netPnl,
        )}
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
                <th>TF</th>
                {showSide ? <th>Side</th> : null}
                <th>Strike</th>
                <th>Lots left (qty)</th>
                <th>Entry</th>
                <th>Current</th>
                <th>Active stop</th>
                <th>Targets</th>
                <th>Realized P&amp;L</th>
                <th>Unrealized P&amp;L</th>
                <th>Est. Charges</th>
                <th>Est. Net P&amp;L</th>
                <th>Comment</th>
              </tr>
            </thead>
            <tbody>
              {open.map((t) => {
                const stopLabel = t.target2Hit ? "Trail" : "Fixed";
                const stopPrice = t.target2Hit ? t.trailingStopPrice : t.stopLossPrice;
                return (
                  <tr key={t.id}>
                    <td>{fmtDateOnly(t.entryTime)}</td>
                    <td>
                      <EntryTimeCell trade={t} />
                    </td>
                    <td>{t.timeframeMinutes ?? 1}m</td>
                    {showSide ? (
                      <td>
                        <span className={`badge ${t.side === "CE" ? "buy" : "sell"}`}>{t.side}</span>
                      </td>
                    ) : null}
                    <td>{t.strike}</td>
                    <td>{t.remainingLots} ({t.remainingQuantity})</td>
                    <td>{fmtNum(t.entryPremium)}</td>
                    <td>{fmtNum(t.currentPremium)}</td>
                    <td>{stopPrice != null ? `${stopLabel} ${fmtNum(stopPrice)}` : "—"}</td>
                    <td>{`${t.target1Hit ? "+5% sold" : "+5% pending"} · ${t.target2Hit ? "+10% sold" : "+10% pending"}`}</td>
                    <td style={{ color: (t.realizedPnl ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>{fmtSigned(t.realizedPnl)}</td>
                    <td style={{ color: t.unrealizedPnl != null ? (t.unrealizedPnl >= 0 ? "var(--green)" : "var(--red)") : undefined }}>
                      {fmtSigned(t.unrealizedPnl)}
                    </td>
                    <td>{t.charges != null ? `₹${fmtNum(t.charges)}` : "—"}</td>
                    <td style={{ color: t.netPnl != null ? (t.netPnl >= 0 ? "var(--green)" : "var(--red)") : undefined }}>
                      {t.netPnl != null ? fmtSigned(t.netPnl) : "—"}
                    </td>
                    <td>
                      <CommentCell value={t.comment} onSave={(v) => onSaveComment(t.id, v)} />
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
                <th>TF</th>
                {showSide ? <th>Side</th> : null}
                <th>Strike</th>
                <th>Entry</th>
                <th>Exit</th>
                <th>Exit Reason</th>
                <th>Exit Legs</th>
                <th>Realized P&amp;L</th>
                <th>Charges</th>
                <th>Net P&amp;L</th>
                <th>Comment</th>
              </tr>
            </thead>
            <tbody>
              {closed.map((t) => (
                <tr key={t.id}>
                  <td>{fmtDateOnly(t.entryTime)}</td>
                  <td>
                      <EntryTimeCell trade={t} />
                    </td>
                  <td>{t.exitTime != null ? fmtTimeOnly(t.exitTime) : "—"}</td>
                  <td>{t.timeframeMinutes ?? 1}m</td>
                  {showSide ? (
                    <td>
                      <span className={`badge ${t.side === "CE" ? "buy" : "sell"}`}>{t.side}</span>
                    </td>
                  ) : null}
                  <td>{t.strike}</td>
                  <td>{fmtNum(t.entryPremium)}</td>
                  <td>{fmtNum(t.exitPremium)}</td>
                  <td>{t.exitReason ? EXIT_REASON_LABEL[t.exitReason] ?? t.exitReason : "—"}</td>
                  <td>
                    {t.exitLegs.length
                      ? t.exitLegs.map((leg) => `${leg.lots}L ${EXIT_REASON_LABEL[leg.exitReason] ?? leg.exitReason} @ ${fmtNum(leg.exitPremium)}`).join(" · ")
                      : "—"}
                  </td>
                  <td style={{ color: (t.realizedPnl ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>{fmtSigned(t.realizedPnl)}</td>
                  <td>{t.charges != null ? `₹${fmtNum(t.charges)}` : "—"}</td>
                  <td style={{ color: (t.netPnl ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                    {t.netPnl != null ? fmtSigned(t.netPnl) : "—"}
                  </td>
                  <td>
                    <CommentCell value={t.comment} onSave={(v) => onSaveComment(t.id, v)} />
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

// Entry time plus the crossover candle that triggered it and how many
// seconds after that candle closed the entry went in.
function EntryTimeCell({ trade: t }: { trade: SimpleCrossoverTrade }) {
  if (!t.signalTime) return <>{fmtTimeOnly(t.entryTime)}</>;
  const lag = t.entryTime - (t.signalTime + (t.timeframeMinutes ?? 1) * 60);
  return (
    <>
      {fmtTimeOnly(t.entryTime)}
      <span className="subtext" title={`Crossover candle ${fmtTimeOnly(t.signalTime)} closed at ${fmtNum(t.signalClose)} (${t.signalSource === "live" ? "live price" : "Dhan candle"})`}>
        cross {fmtTimeOnly(t.signalTime)} @ {fmtNum(t.signalClose)} · +{lag}s
      </span>
    </>
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

function SimpleCrossoverChart({ data, trades }: { data: SimpleCrossoverData | null; trades: SimpleCrossoverTrade[] }) {
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

    // EMA gap pane (pane 1, between price and RSI) -- 0 is the middle
    // reference line: positive means EMA8 above EMA21, negative the
    // opposite.
    const gapSeries = chart.addSeries(LineSeries, { color: "#5b6b7c", lineWidth: 2, title: "EMA Gap" }, 1);
    gapSeries.createPriceLine({ price: 0, color: "#8391a3", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "0" });

    // Static overbought/oversold reference zones -- a constant line at
    // 70/30 filled toward the pane's top/bottom edge (invertFilledArea
    // flips the fill to go up instead of lightweight-charts' default
    // "down to the bottom"), added before the RSI/SMA lines so they sit
    // behind them. Always shaded regardless of where RSI actually is right
    // now, matching the standard RSI-chart convention. Pane 2 (RSI), after
    // the EMA gap pane.
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
      markersRef.current.setMarkers(tradeMarkers(data, trades));
    }
  }, [data, trades]);

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

// Paper-trade entries and every exit (staged targets included) on the
// option this chart shows, each snapped to the candle it happened in.
function tradeMarkers(data: SimpleCrossoverData, trades: SimpleCrossoverTrade[]): SeriesMarker<Time>[] {
  const times = data.candles.map((c) => c.time);
  if (!times.length) return [];
  const first = times[0];
  const last = times[times.length - 1] + 60 * (data.timeframeMinutes ?? 1);
  const candleAt = (t: number): number | null => {
    if (t < first || t >= last) return null;
    let lo = 0;
    let hi = times.length - 1;
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2);
      if (times[mid] <= t) lo = mid;
      else hi = mid - 1;
    }
    return times[lo];
  };
  const markers: SeriesMarker<Time>[] = [];
  for (const t of trades) {
    if (t.strike !== data.strike || t.expiry !== data.expiry) continue;
    const entryAt = candleAt(t.entryTime);
    if (entryAt != null) {
      markers.push({
        time: entryAt as UTCTimestamp,
        position: "belowBar",
        color: "#168448",
        shape: "arrowUp",
        text: `Entry @ ${fmtNum(t.entryPremium)}`,
      });
    }
    const exits = t.exitLegs.length
      ? t.exitLegs.map((l) => ({ time: l.exitTime, price: l.exitPremium }))
      : t.exitTime && t.exitPremium != null
        ? [{ time: t.exitTime, price: t.exitPremium }]
        : [];
    for (const e of exits) {
      const exitAt = candleAt(e.time);
      if (exitAt == null) continue;
      markers.push({
        time: exitAt as UTCTimestamp,
        position: "aboveBar",
        color: "#c93535",
        shape: "arrowDown",
        text: `Exit @ ${fmtNum(e.price)}`,
      });
    }
  }
  return markers.sort((a, b) => (a.time as number) - (b.time as number));
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
