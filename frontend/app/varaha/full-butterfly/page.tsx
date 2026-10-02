"use client";

import { Search, Shapes } from "lucide-react";
import { useEffect, useState } from "react";

import VarahaPayoffChart from "@/components/VarahaPayoffChart";
import VarahaTabs from "@/components/VarahaTabs";
import { scanFullButterfly } from "@/lib/api";
import type { FullButterflyFilters, FullButterflyResult, FullButterflyScan } from "@/types/varaha";

const DEFAULT_FILTERS: FullButterflyFilters = {
  symmetric: false,
  longPlacement: "any",
  centered: true,
  minShortEm: 1.0,
  wingRatioMin: 0.5,
  wingRatioMax: 1.0,
  requireLiquid: true,
  frontierOnly: true,
  sort: "width",
};

const SORT_LABEL: Record<FullButterflyFilters["sort"], string> = {
  width: "Smallest middle V",
  rr: "Best reward / risk",
  pop: "Highest probability of profit",
  maxLoss: "Smallest max loss",
  maxProfit: "Largest max profit",
};

const WING_RATIO_OPTIONS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0];

function fmtNum(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function fmtInr(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value < 0 ? "−" : ""}₹${fmtNum(Math.abs(value))}`;
}

function fmtExpiry(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function strikesSummary(result: FullButterflyResult): string {
  const pe = result.legs.filter((l) => l.optionType === "PE").map((l) => fmtNum(l.strike));
  const ce = result.legs.filter((l) => l.optionType === "CE").map((l) => fmtNum(l.strike));
  return `PE ${pe.reverse().join(" / ")} · CE ${ce.join(" / ")}`;
}

function numberOrUndefined(value: string): number | undefined {
  if (value.trim() === "") return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export default function FullButterflyBuilderPage() {
  const [filters, setFilters] = useState<FullButterflyFilters>(DEFAULT_FILTERS);
  const [scan, setScan] = useState<FullButterflyScan | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runScan(next: FullButterflyFilters = filters) {
    setLoading(true);
    setError(null);
    try {
      const payload = await scanFullButterfly(next);
      if (payload.error) {
        setError(payload.error);
      } else {
        setScan(payload);
        setSelectedId(payload.results[0]?.id ?? null);
        if (!next.expiry) setFilters((prev) => ({ ...prev, expiry: payload.expiry.expiry }));
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Scan failed.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    runScan(DEFAULT_FILTERS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function update<K extends keyof FullButterflyFilters>(key: K, value: FullButterflyFilters[K]) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  const selected = scan?.results.find((r) => r.id === selectedId) ?? scan?.results[0] ?? null;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Shapes size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Varaha
          </h1>
          <p>
            Full Butterfly builder — scans every PE + CE 1:2:1 combination on the live chain and finds the ones with the
            smallest central loss V for the reward / risk you want. Recommendation only; entry and exit are manual.
          </p>
        </div>
      </header>
      <VarahaTabs />

      {error ? <div className="alert error">{error}</div> : null}

      <FiltersPanel filters={filters} scan={scan} loading={loading} onChange={update} onScan={() => runScan()} onReset={() => { setFilters(DEFAULT_FILTERS); runScan(DEFAULT_FILTERS); }} />

      {scan ? (
        <>
          <ScanSummary scan={scan} />
          {scan.results.length ? (
            <>
              <div className="pcr-oi-section">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 8 }}>
                  <h3 style={{ margin: 0 }}>Middle V width vs reward / risk</h3>
                  <span className="pcr-oi-caption">
                    Blue = best reward / risk for its width (not beaten on both). Click a blue point to open it.
                  </span>
                </div>
                <FrontierScatter scan={scan} selected={selected} onSelect={setSelectedId} />
              </div>
              {selected ? <ResultDetail scan={scan} result={selected} /> : null}
              <ResultsTable scan={scan} selected={selected} onSelect={setSelectedId} />
            </>
          ) : (
            <div className="pcr-oi-section">
              <p style={{ margin: 0 }}>
                No Full Butterfly matches these filters. Try a wider max V, a lower min reward / risk, or moving the profit
                peaks closer (lower min × expected move).
              </p>
            </div>
          )}
        </>
      ) : loading ? (
        <p className="pcr-oi-caption">Scanning the option chain…</p>
      ) : null}
    </section>
  );
}

function FiltersPanel({
  filters,
  scan,
  loading,
  onChange,
  onScan,
  onReset,
}: {
  filters: FullButterflyFilters;
  scan: FullButterflyScan | null;
  loading: boolean;
  onChange: <K extends keyof FullButterflyFilters>(key: K, value: FullButterflyFilters[K]) => void;
  onScan: () => void;
  onReset: () => void;
}) {
  const inputStyle = { width: 90, fontSize: 13, padding: "3px 6px" };
  const field = (label: string, control: React.ReactNode, hint?: string) => (
    <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12, minWidth: 0 }}>
      <span style={{ color: "var(--muted)", fontWeight: 600 }}>{label}</span>
      {control}
      {hint ? <span className="pcr-oi-caption">{hint}</span> : null}
    </label>
  );
  const numberInput = (key: keyof FullButterflyFilters, step: number, placeholder = "any") => (
    <input
      type="number"
      step={step}
      min={0}
      placeholder={placeholder}
      value={(filters[key] as number | undefined) ?? ""}
      onChange={(e) => onChange(key, numberOrUndefined(e.target.value) as never)}
      onKeyDown={(e) => e.key === "Enter" && onScan()}
      style={inputStyle}
    />
  );
  const em = scan?.expectedMove ?? null;

  return (
    <div className="pcr-oi-section">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 8 }}>
        <h3 style={{ margin: 0 }}>Shape the middle part</h3>
        <span className="pcr-oi-caption">
          Middle V width = (CE long − PE long) + 2 × net debit. Max loss = net debit. Peak profit = inner wing − net debit.
        </span>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
          gap: 12,
          marginTop: 10,
          alignItems: "start",
        }}
      >
        {field(
          "Expiry",
          <select
            value={filters.expiry ?? ""}
            onChange={(e) => onChange("expiry", e.target.value || undefined)}
            style={{ fontSize: 13, padding: "3px 6px" }}
          >
            {(scan?.expiries ?? []).map((e) => (
              <option key={e.expiry} value={e.expiry}>
                {fmtExpiry(e.expiry)} ({e.dte === 0 ? "expires today" : `${e.dte}d`}
                {e.tradingDte < 2 && e.dte > 0 ? " · near expiry" : ""})
              </option>
            ))}
          </select>,
        )}
        {field(
          "Max middle V (points)",
          numberInput("maxWidth", 25),
          em ? `Expected move ±${fmtNum(em)}` : undefined,
        )}
        {field("Max middle V (× exp. move)", numberInput("maxWidthEm", 0.1))}
        {field(
          "Profit peaks at least",
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
            {numberInput("minShortEm", 0.25, "0")} × EM
          </span>,
          em && filters.minShortEm ? `≈ ${fmtNum(filters.minShortEm * em)} pts from spot` : "Short strikes' distance",
        )}
        {field(
          "Profit peaks at most",
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
            {numberInput("maxShortEm", 0.25)} × EM
          </span>,
          em && filters.maxShortEm ? `≈ ${fmtNum(filters.maxShortEm * em)} pts from spot` : undefined,
        )}
        {field("Min reward / risk", numberInput("minRr", 0.25))}
        {field("Max loss ₹", numberInput("maxLossInr", 1000), scan ? `Hard limit ₹${fmtNum(scan.maxLossLimitInr)}` : undefined)}
        {field("Min max profit ₹", numberInput("minMaxProfitInr", 1000))}
        {field("Min probability of profit %", numberInput("minPop", 5))}
        {field(
          "Long legs",
          <select
            value={filters.longPlacement}
            onChange={(e) => onChange("longPlacement", e.target.value as FullButterflyFilters["longPlacement"])}
            style={{ fontSize: 13, padding: "3px 6px" }}
          >
            <option value="any">Within ±2 strikes of ATM</option>
            <option value="adjacent">Same or adjacent strikes</option>
            <option value="atm">Both at ATM</option>
          </select>,
        )}
        {field(
          "Wing ratio (outer / inner)",
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <select
              value={filters.wingRatioMin}
              onChange={(e) => onChange("wingRatioMin", Number(e.target.value))}
              style={{ fontSize: 13, padding: "3px 4px" }}
            >
              {WING_RATIO_OPTIONS.map((r) => (
                <option key={r} value={r}>
                  {r.toFixed(1)}
                </option>
              ))}
            </select>
            –
            <select
              value={filters.wingRatioMax}
              onChange={(e) => onChange("wingRatioMax", Number(e.target.value))}
              style={{ fontSize: 13, padding: "3px 4px" }}
            >
              {WING_RATIO_OPTIONS.map((r) => (
                <option key={r} value={r}>
                  {r.toFixed(1)}
                </option>
              ))}
            </select>
          </span>,
          "Below 1.0 turns the far tails into small profits",
        )}
        {field(
          "Sort by",
          <select
            value={filters.sort}
            onChange={(e) => onChange("sort", e.target.value as FullButterflyFilters["sort"])}
            style={{ fontSize: 13, padding: "3px 6px" }}
          >
            {Object.entries(SORT_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>,
        )}
      </div>

      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 12, fontSize: 13 }}>
        {(
          [
            ["centered", "Spot inside the middle V"],
            ["symmetric", "Symmetric wings (same PE / CE shape)"],
            ["frontierOnly", "Best trade-offs only"],
            ["requireLiquid", "Require two-sided quotes (market hours)"],
          ] as [keyof FullButterflyFilters, string][]
        ).map(([key, label]) => (
          <label key={key} style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
            <input type="checkbox" checked={Boolean(filters[key])} onChange={(e) => onChange(key, e.target.checked as never)} />
            {label}
          </label>
        ))}
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button type="button" className="button" onClick={onScan} disabled={loading} style={{ whiteSpace: "nowrap" }}>
          <Search size={14} /> {loading ? "Scanning…" : "Scan"}
        </button>
        <button type="button" className="button secondary" onClick={onReset} disabled={loading}>
          Reset
        </button>
      </div>
    </div>
  );
}

function ScanSummary({ scan }: { scan: FullButterflyScan }) {
  const metrics = [
    { label: "NIFTY", value: fmtNum(scan.spot, 2), caption: `Forward ${fmtNum(scan.forward)}` },
    { label: "Expiry", value: fmtExpiry(scan.expiry.expiry), caption: `${scan.expiry.dte} days · ${scan.expiry.tradingDte} trading` },
    { label: "Expected move", value: scan.expectedMove ? `±${fmtNum(scan.expectedMove)}` : "—", caption: "ATM straddle" },
    { label: "ATM IV", value: scan.atmIv ? `${fmtNum(scan.atmIv * 100, 1)}%` : "—" },
    {
      label: "Quotes",
      value: new Date(scan.quotesAt * 1000).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false }),
      caption: scan.marketOpen ? "Live (cached ≤ 60s)" : "Market closed — last traded",
    },
    { label: "Size", value: `${scan.lots} lot × ${scan.lotSize}`, caption: "Change in Daily decision → Settings" },
    {
      label: "Combinations",
      value: fmtNum(scan.matched),
      caption: `${fmtNum(scan.scanned)} scanned · ${scan.frontierCount} best trade-offs`,
    },
  ];
  return (
    <>
      {scan.warnings.map((w) => (
        <div key={w} className="alert warning">
          {w}
        </div>
      ))}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        {metrics.map((m) => (
          <div key={m.label} className="metric metric-compact" style={{ flex: "1 1 140px" }}>
            <span>{m.label}</span>
            <strong>{m.value}</strong>
            {m.caption ? <span className="pcr-oi-caption">{m.caption}</span> : null}
          </div>
        ))}
      </div>
    </>
  );
}

function FrontierScatter({
  scan,
  selected,
  onSelect,
}: {
  scan: FullButterflyScan;
  selected: FullButterflyResult | null;
  onSelect: (id: string) => void;
}) {
  const [hoverId, setHoverId] = useState<string | null>(null);
  const width = 900;
  const height = 260;
  const pad = { left: 52, right: 16, top: 12, bottom: 36 };
  const points = scan.scatter;
  if (!points.length) return null;
  const xs = points.map((p) => p.width);
  const ys = points.map((p) => p.rr);
  const xMin = Math.min(...xs) * 0.95;
  const xMax = Math.max(...xs) * 1.03;
  const yMin = 0;
  const yMax = Math.max(...ys) * 1.08;
  const x = (v: number) => pad.left + ((v - xMin) / (xMax - xMin || 1)) * (width - pad.left - pad.right);
  const y = (v: number) => pad.top + ((yMax - v) / (yMax - yMin || 1)) * (height - pad.top - pad.bottom);
  const xTicks = Array.from({ length: 6 }, (_, i) => xMin + ((xMax - xMin) * i) / 5);
  const yTicks = Array.from({ length: 5 }, (_, i) => yMin + ((yMax - yMin) * i) / 4);
  const frontierResults = scan.results.slice().sort((a, b) => a.lossWidth - b.lossWidth);
  const hovered = scan.results.find((r) => r.id === hoverId) ?? null;
  const emLine = scan.expectedMove && scan.expectedMove >= xMin && scan.expectedMove <= xMax ? scan.expectedMove : null;

  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: 12, minHeight: 18 }}>
        {hovered
          ? `V ${fmtNum(hovered.lossWidth)} pts · R/R ${fmtNum(hovered.rewardRisk, 2)} · max profit ${fmtInr(hovered.maxProfit)} · max loss ${fmtInr(hovered.maxLoss)} · ${strikesSummary(hovered)}`
          : "Grey = other combinations (sampled). Up-and-left is better: a smaller V with a higher reward / risk."}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto", display: "block" }} role="img" aria-label="Loss width versus reward to risk">
        {yTicks.map((t) => (
          <g key={`y${t}`}>
            <line x1={pad.left} x2={width - pad.right} y1={y(t)} y2={y(t)} stroke="var(--line-soft)" />
            <text x={pad.left - 6} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--muted)">
              {fmtNum(t, 1)}
            </text>
          </g>
        ))}
        {xTicks.map((t) => (
          <text key={`x${t}`} x={x(t)} y={height - 18} textAnchor="middle" fontSize={11} fill="var(--muted)">
            {fmtNum(t)}
          </text>
        ))}
        <text x={(pad.left + width - pad.right) / 2} y={height - 3} textAnchor="middle" fontSize={11} fill="var(--muted)">
          Middle V width (points)
        </text>
        <text x={12} y={height / 2} fontSize={11} fill="var(--muted)" transform={`rotate(-90 12 ${height / 2})`} textAnchor="middle">
          Reward / risk
        </text>
        {emLine ? (
          <g>
            <line x1={x(emLine)} x2={x(emLine)} y1={pad.top} y2={height - pad.bottom} stroke="var(--amber)" strokeDasharray="4 3" />
            <text x={x(emLine) + 4} y={pad.top + 10} fontSize={10} fill="var(--amber)">
              1× expected move
            </text>
          </g>
        ) : null}
        {points
          .filter((p) => !p.frontier)
          .map((p, i) => (
            <circle key={`g${i}`} cx={x(p.width)} cy={y(p.rr)} r={2} fill="var(--muted)" fillOpacity={0.3} />
          ))}
        {frontierResults.length > 1 ? (
          <path
            d={frontierResults.map((r, i) => `${i ? "L" : "M"}${x(r.lossWidth).toFixed(1)},${y(r.rewardRisk).toFixed(1)}`).join(" ")}
            fill="none"
            stroke="var(--blue)"
            strokeOpacity={0.4}
          />
        ) : null}
        {scan.results.map((r) => {
          const active = selected?.id === r.id;
          return (
            <circle
              key={r.id}
              cx={x(r.lossWidth)}
              cy={y(r.rewardRisk)}
              r={active ? 7 : 5}
              fill={active ? "var(--blue)" : "var(--panel)"}
              stroke="var(--blue)"
              strokeWidth={2}
              style={{ cursor: "pointer" }}
              onClick={() => onSelect(r.id)}
              onMouseEnter={() => setHoverId(r.id)}
              onMouseLeave={() => setHoverId(null)}
            />
          );
        })}
      </svg>
    </div>
  );
}

function ResultsTable({
  scan,
  selected,
  onSelect,
}: {
  scan: FullButterflyScan;
  selected: FullButterflyResult | null;
  onSelect: (id: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const rows = showAll ? scan.results : scan.results.slice(0, 10);
  return (
    <div className="pcr-oi-section">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
        <h3 style={{ margin: "0 0 6px" }}>All options ({scan.results.length})</h3>
        {scan.results.length > 10 ? (
          <button type="button" className="button secondary" onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Show top 10" : `Show all ${scan.results.length}`}
          </button>
        ) : null}
      </div>
      <div style={{ overflowX: "auto" }}>
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Middle V</th>
              <th>Loss zone</th>
              <th>Strikes (hedge / short / long)</th>
              <th>Debit</th>
              <th>Max profit</th>
              <th>Max loss</th>
              <th>R/R</th>
              <th>POP</th>
              <th>Profit peaks</th>
              <th>Wing ratio</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const active = selected?.id === r.id;
              return (
                <tr
                  key={r.id}
                  onClick={() => onSelect(r.id)}
                  style={{ cursor: "pointer", background: active ? "var(--blue-soft)" : undefined }}
                >
                  <td>{i + 1}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <strong>{fmtNum(r.lossWidth)}</strong>
                    <span className="pcr-oi-caption"> ({fmtNum(r.lossWidthEm, 2)}× EM)</span>
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {fmtNum(r.lossZone[0])} – {fmtNum(r.lossZone[1])}
                  </td>
                  <td style={{ fontSize: 12, whiteSpace: "nowrap" }}>{strikesSummary(r)}</td>
                  <td>{fmtInr(r.netDebit)}</td>
                  <td style={{ color: "var(--green)" }}>{fmtInr(r.maxProfit)}</td>
                  <td style={{ color: "var(--red)" }}>{fmtInr(r.maxLoss)}</td>
                  <td>{fmtNum(r.rewardRisk, 2)}</td>
                  <td>{fmtNum(r.pop, 1)}%</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    −{fmtNum(r.shortDistances[0])} / +{fmtNum(r.shortDistances[1])}
                  </td>
                  <td>
                    {r.wingRatios[0].toFixed(2)} / {r.wingRatios[1].toFixed(2)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="pcr-oi-caption" style={{ margin: "4px 0 0" }}>
        Priced conservatively (ask for buys, bid for sells when quoted). POP is a lognormal estimate at ATM IV (ignores skew)
        — a guide, not a forecast.
      </p>
    </div>
  );
}

function ResultDetail({ scan, result }: { scan: FullButterflyScan; result: FullButterflyResult }) {
  return (
    <div className="pcr-oi-section">
      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, alignItems: "baseline" }}>
        <h3 style={{ margin: 0 }}>Full Butterfly — {strikesSummary(result)}</h3>
        <span className="pcr-oi-caption">
          {fmtExpiry(scan.expiry.expiry)} · {result.lots} lot × {result.lotSize} · entry charges ≈ {fmtInr(result.charges)}
        </span>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, margin: "10px 0" }}>
        {[
          { label: "Middle V width", value: `${fmtNum(result.lossWidth)} pts`, caption: `${fmtNum(result.lossWidthEm, 2)}× expected move` },
          { label: "Loss zone", value: `${fmtNum(result.lossZone[0])} – ${fmtNum(result.lossZone[1])}` },
          { label: "Net debit (= max loss)", value: fmtInr(result.netDebit), caption: `${fmtNum(result.netDebitPoints, 2)} pts` },
          { label: "Max profit", value: fmtInr(result.maxProfit) },
          { label: "Reward / risk", value: fmtNum(result.rewardRisk, 2) },
          { label: "Probability of profit", value: `${fmtNum(result.pop, 1)}%`, caption: "Lognormal at ATM IV" },
        ].map((m) => (
          <div key={m.label} className="metric metric-compact" style={{ flex: "1 1 140px" }}>
            <span>{m.label}</span>
            <strong>{m.value}</strong>
            {m.caption ? <span className="pcr-oi-caption">{m.caption}</span> : null}
          </div>
        ))}
      </div>

      <VarahaPayoffChart
        chartId={result.id}
        label="Full Butterfly"
        points={result.payoff}
        breakevens={result.breakevens}
        spot={scan.spot}
        expectedMove={scan.expectedMove}
        lossZone={result.lossZone}
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 380px), 1fr))",
          gap: 14,
          marginTop: 14,
        }}
      >
        <div style={{ minWidth: 0, overflowX: "auto" }}>
          <h4 style={{ margin: "0 0 6px", fontSize: 13 }}>Legs</h4>
          <table>
            <thead>
              <tr>
                <th>Action</th>
                <th>Lots</th>
                <th>Strike</th>
                <th>Premium used</th>
                <th>Bid / Ask</th>
                <th>Delta</th>
                <th>IV</th>
                <th>From spot</th>
              </tr>
            </thead>
            <tbody>
              {result.legs.map((leg) => (
                <tr key={`${leg.action}-${leg.strike}-${leg.optionType}`}>
                  <td>
                    <span className={`badge ${leg.action === "BUY" ? "buy" : "sell"}`}>{leg.action}</span>
                  </td>
                  <td>{leg.qty * result.lots}</td>
                  <td>
                    {fmtNum(leg.strike)} {leg.optionType}
                  </td>
                  <td>{fmtNum(leg.price, 2)}</td>
                  <td>{leg.bid != null && leg.ask != null ? `${fmtNum(leg.bid, 2)} / ${fmtNum(leg.ask, 2)}` : "—"}</td>
                  <td>{leg.delta != null ? fmtNum(leg.delta, 2) : "—"}</td>
                  <td>{leg.iv != null ? `${fmtNum(leg.iv, 1)}%` : "—"}</td>
                  <td>
                    {leg.distance >= 0 ? "+" : "−"}
                    {fmtNum(Math.abs(leg.distance))} ({leg.distancePercent >= 0 ? "+" : ""}
                    {fmtNum(leg.distancePercent, 2)}%)
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ minWidth: 0, overflowX: "auto" }}>
          <h4 style={{ margin: "0 0 6px", fontSize: 13 }}>Breakevens and zones at expiry</h4>
          <table>
            <tbody>
              <tr>
                <td>Breakevens</td>
                <td>
                  <strong>{result.breakevens.map((b) => fmtNum(b, 1)).join(" · ") || "—"}</strong>
                </td>
              </tr>
              {result.zones.map((zone, i) => (
                <tr key={i}>
                  <td style={{ color: zone.type === "profit" ? "var(--green)" : "var(--red)" }}>
                    {zone.type === "profit" ? "Profit zone" : "Loss zone"}
                  </td>
                  <td>
                    {zone.from == null ? "below " : `${fmtNum(zone.from)} `}
                    {zone.from != null && zone.to != null ? "– " : ""}
                    {zone.to == null ? (zone.from == null ? "—" : "and above") : fmtNum(zone.to)}
                  </td>
                </tr>
              ))}
              <tr>
                <td>Inner wings (PE / CE)</td>
                <td>
                  {fmtNum(result.innerWings[0])} / {fmtNum(result.innerWings[1])} pts
                </td>
              </tr>
              <tr>
                <td>Gap between long strikes</td>
                <td>{fmtNum(result.longGap)} pts</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
