"use client";

import { Play, RefreshCw, Shapes } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import VarahaPayoffChart from "@/components/VarahaPayoffChart";
import VarahaTabs from "@/components/VarahaTabs";
import { getVarahaHistory, getVarahaLatest, runVaraha, setVarahaOverride, updateVarahaConfig } from "@/lib/api";
import type {
  VarahaCandidate,
  VarahaCheck,
  VarahaConfig,
  VarahaHistoryItem,
  VarahaOverride,
  VarahaRecommendation,
  VarahaResult,
} from "@/types/varaha";

const REFRESH_MS = 60000;

const MOVE_LABEL: Record<string, string> = { BIG_MOVE: "Large move", WATCH: "Elevated / Watch", LOW: "Low / Normal" };
const MOVE_COLOR: Record<string, string> = { BIG_MOVE: "var(--green)", WATCH: "var(--amber)", LOW: "var(--muted)" };
const DIRECTION_LABEL: Record<string, string> = { UP: "Bullish", DOWN: "Bearish", NO_CLEAR_DIRECTION: "No clear direction" };
const DIRECTION_COLOR: Record<string, string> = { UP: "var(--green)", DOWN: "var(--red)", NO_CLEAR_DIRECTION: "var(--amber)" };
const STATUS_LABEL: Record<string, string> = { VALID: "Valid", WATCH: "Watch", NO_TRADE: "No trade" };
const STATUS_COLOR: Record<string, string> = { VALID: "var(--green)", WATCH: "var(--amber)", NO_TRADE: "var(--red)" };
const CHECK_COLOR: Record<string, string> = { PASS: "var(--green)", WATCH: "var(--amber)", FAIL: "var(--red)" };
const OVERRIDE_OPTIONS: { value: VarahaOverride; label: string }[] = [
  { value: "AUTO", label: "Auto" },
  { value: "UP", label: "Up → CE Butterfly" },
  { value: "DOWN", label: "Down → PE Butterfly" },
  { value: "NO_DIRECTION", label: "No direction → Full Butterfly" },
];
const TRIGGER_LABEL: Record<string, string> = { scheduled: "Scheduled (T-30)", manual: "Manual run", override: "Override re-run" };
const AI_SECTION_LABEL: [keyof NonNullable<NonNullable<VarahaResult["ai"]>["sections"]>, string][] = [
  ["marketView", "Market view"],
  ["whyThisStrategy", "Why this strategy"],
  ["keyStrikes", "Key strikes"],
  ["risk", "Risk"],
  ["expectedMove", "Expected move"],
  ["whatCouldGoWrong", "What could go wrong"],
  ["invalidation", "What invalidates the setup"],
  ["alternative", "Alternative candidate"],
  ["overrideComment", "On the manual override"],
];

function fmtNum(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function fmtSigned(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return `${value >= 0 ? "+" : "−"}${fmtNum(Math.abs(value), digits)}`;
}

function fmtInr(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value < 0 ? "−" : ""}₹${fmtNum(Math.abs(value))}`;
}

function fmtEpoch(epoch: number | null | undefined): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function fmtExpiry(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export default function VarahaPage() {
  const [recommendation, setRecommendation] = useState<VarahaRecommendation | null>(null);
  const [override, setOverride] = useState<VarahaOverride>("AUTO");
  const [config, setConfig] = useState<VarahaConfig | null>(null);
  const [history, setHistory] = useState<VarahaHistoryItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const [latest, hist] = await Promise.all([getVarahaLatest(), getVarahaHistory()]);
      setRecommendation(latest.recommendation);
      setOverride(latest.override);
      if (latest.config) setConfig(latest.config);
      setHistory(hist.items);
      setError(null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load Varaha.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  async function act(label: string, fn: () => Promise<{ recommendation: VarahaRecommendation | null; override: VarahaOverride }>) {
    setBusy(label);
    setError(null);
    try {
      const payload = await fn();
      setRecommendation(payload.recommendation);
      setOverride(payload.override);
      setSelectedId(null);
      setHistory((await getVarahaHistory()).items);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Request failed.");
    } finally {
      setBusy(null);
    }
  }

  const result = recommendation?.result ?? null;
  const candidates = result?.candidates ?? [];
  const topIds = result?.topIds ?? candidates.slice(0, 3).map((c) => c.id);
  const top = candidates.filter((c) => topIds.includes(c.id));
  const rest = candidates.filter((c) => !topIds.includes(c.id));
  const selected = useMemo(
    () => candidates.find((c) => c.id === selectedId) ?? top[0] ?? null,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [recommendation, selectedId],
  );

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <Shapes size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            Varaha
          </h1>
          <p>
            NIFTY adaptive daily strategy — recommendation only. At {config?.decisionTime ?? "15:00"} (T-30) the engine scores
            the expected move and direction, builds candidate butterflies / condors, removes any that fail a hard risk gate,
            and the AI ranks the rest. Entry and exit are manual.
          </p>
        </div>
        <div className="toolbar">
          <button type="button" className="button secondary" style={{ whiteSpace: "nowrap" }} onClick={load} disabled={loading || !!busy}>
            <RefreshCw size={14} /> Refresh
          </button>
          <button type="button" className="button" style={{ whiteSpace: "nowrap" }} onClick={() => act("run", runVaraha)} disabled={!!busy}>
            <Play size={14} /> {busy === "run" ? "Running… (~30s)" : "Run now"}
          </button>
        </div>
      </header>
      <VarahaTabs />

      {error ? <div className="alert error">{error}</div> : null}
      {loading && !recommendation ? <p className="pcr-oi-caption">Loading…</p> : null}
      {!loading && !recommendation ? (
        <div className="pcr-oi-section">
          <p style={{ margin: 0 }}>
            No recommendation yet. The engine runs automatically at {config?.decisionTime ?? "15:00"} on trading days, or use
            <strong> Run now</strong> for an on-demand snapshot.
          </p>
        </div>
      ) : null}

      {recommendation && result ? (
        <>
          <SummaryStrip recommendation={recommendation} />
          <StatusBanner result={result} />
          <DecisionCard
            result={result}
            override={override}
            busy={busy}
            onOverride={(value) => act(`override-${value}`, () => setVarahaOverride(value))}
          />

          {top.length ? (
            <div className="pcr-oi-section">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 8 }}>
                <h3 style={{ margin: 0 }}>Best options</h3>
                <span className="pcr-oi-caption">
                  {result.rankingSource === "AI"
                    ? `Ranked by AI (${result.ai?.model ?? "OpenAI"}) among candidates that passed every hard gate`
                    : `Ranked by deterministic score — AI ranking unavailable${result.ai?.error ? `: ${result.ai.error}` : ""}`}
                </span>
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 300px), 1fr))",
                  gap: 10,
                  marginTop: 10,
                }}
              >
                {top.map((candidate, index) => (
                  <CandidateCard
                    key={candidate.id}
                    candidate={candidate}
                    rank={index + 1}
                    ai={result.rankingSource === "AI"}
                    active={selected?.id === candidate.id}
                    onSelect={() => setSelectedId(candidate.id)}
                  />
                ))}
              </div>
            </div>
          ) : null}

          {selected ? <CandidateDetail candidate={selected} result={result} /> : null}
          <AiPanel result={result} />
          <ScoreDetails result={result} />
          {rest.length || result.rejected.length ? (
            <OtherCandidates rest={rest} result={result} onSelect={(id) => setSelectedId(id)} />
          ) : null}
        </>
      ) : null}

      <SettingsPanel config={config} onSaved={setConfig} />
      <HistoryPanel history={history} />
    </section>
  );
}

function SummaryStrip({ recommendation }: { recommendation: VarahaRecommendation }) {
  const result = recommendation.result;
  const move = result.move;
  const expiry = result.expiries[0];
  const metrics: { label: string; value: string; caption?: string }[] = [
    { label: "NIFTY (snapshot)", value: fmtNum(result.spot, 2), caption: fmtEpoch(result.takenAt) },
    { label: "Run", value: TRIGGER_LABEL[recommendation.trigger] ?? recommendation.trigger, caption: recommendation.sessionDate },
    {
      label: "Expiry",
      value: expiry ? fmtExpiry(expiry.expiry) : "—",
      caption: expiry ? `${expiry.dte} days · ${expiry.tradingDte} trading` : "",
    },
    { label: "Expected move", value: move?.expectedMove ? `±${fmtNum(move.expectedMove)}` : "—", caption: "ATM straddle to expiry" },
    { label: "ATM IV", value: move?.atmIv ? `${fmtNum(move.atmIv * 100, 1)}%` : "—" },
    {
      label: "India VIX",
      value: fmtNum(move?.vix, 2),
      caption: move?.vixPercentile != null ? `1y percentile ${fmtNum(move.vixPercentile)}` : "",
    },
    { label: "PCR (OI)", value: fmtNum(result.pcr, 2) },
    {
      label: "Market regime",
      value: move ? MOVE_LABEL[move.classification] : "—",
      caption: move ? `Move score ${move.moveScore} / ${move.maxScore}` : "",
    },
  ];
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
      {metrics.map((m) => (
        <div key={m.label} className="metric metric-compact" style={{ flex: "1 1 140px" }}>
          <span>{m.label}</span>
          <strong>{m.value}</strong>
          {m.caption ? <span className="pcr-oi-caption">{m.caption}</span> : null}
        </div>
      ))}
    </div>
  );
}

function StatusBanner({ result }: { result: VarahaResult }) {
  return (
    <>
      {!result.marketOpen ? (
        <div className="alert warning">
          Snapshot taken outside market hours — quotes are end-of-day / indicative, and bid/ask may be missing.
        </div>
      ) : null}
      {result.warnings.length ? (
        <div className="alert warning">
          {result.warnings.map((w) => (
            <div key={w}>{w}</div>
          ))}
        </div>
      ) : null}
      {result.status === "NO_TRADE" ? <div className="alert error">No trade — {result.statusReason}</div> : null}
    </>
  );
}

function DecisionCard({
  result,
  override,
  busy,
  onOverride,
}: {
  result: VarahaResult;
  override: VarahaOverride;
  busy: string | null;
  onOverride: (value: VarahaOverride) => void;
}) {
  const move = result.move;
  const direction = result.direction;
  const bigMove = move?.classification === "BIG_MOVE";
  const overridden = direction?.manualOverride && direction.effective !== direction.classification;
  const strategyLabel =
    result.status === "NO_TRADE"
      ? "No trade"
      : result.status === "WATCH"
        ? "Best options for review (not a confirmed big move)"
        : (result.selectedStructureLabel ?? "—");

  return (
    <div className="pcr-oi-section">
      <h3 style={{ margin: "0 0 10px" }}>Decision</h3>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))", gap: 10 }}>
        <div className="metric">
          <span>Move expectation</span>
          <strong style={{ color: move ? MOVE_COLOR[move.classification] : undefined }}>
            {move ? MOVE_LABEL[move.classification] : "—"}
          </strong>
          <span className="pcr-oi-caption">
            {move
              ? `Score ${move.moveScore} / ${move.maxScore} (big ≥ ${move.bigMoveScore}, watch ≥ ${move.watchScore})`
              : ""}
          </span>
        </div>
        <div className="metric">
          <span>Direction</span>
          <strong style={{ color: direction ? DIRECTION_COLOR[direction.effective] : undefined }}>
            {direction ? DIRECTION_LABEL[direction.effective] : "—"}
          </strong>
          <span className="pcr-oi-caption">
            {direction
              ? overridden
                ? `Manual override — engine: ${DIRECTION_LABEL[direction.classification]} (${fmtNum(direction.bullishConfidence)}% / ${fmtNum(direction.bearishConfidence)}%)`
                : `Bullish ${fmtNum(direction.bullishConfidence)}% · Bearish ${fmtNum(direction.bearishConfidence)}% (needs ≥ ${fmtNum(direction.threshold)}%)`
              : ""}
          </span>
        </div>
        <div className="metric">
          <span>Selected strategy</span>
          <strong style={{ color: STATUS_COLOR[result.status] }}>{strategyLabel}</strong>
          <span className="pcr-oi-caption">
            Status: {STATUS_LABEL[result.status]} — {result.statusReason}
          </span>
        </div>
      </div>

      <div style={{ marginTop: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <strong style={{ fontSize: 13, marginRight: 4 }}>Direction override</strong>
          {OVERRIDE_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className="button secondary"
              disabled={!bigMove || !!busy}
              style={option.value === override ? { background: "var(--blue)", color: "#fff" } : undefined}
              onClick={() => option.value !== override && onOverride(option.value)}
            >
              {busy === `override-${option.value}` ? "Re-running…" : option.label}
            </button>
          ))}
        </div>
        <p className="pcr-oi-caption" style={{ margin: "4px 0 0" }}>
          {bigMove
            ? "Changes direction only and re-runs today's T-30 snapshot. Hard gates still apply; resets to Auto tomorrow."
            : `Only available on big-move days (today: ${move ? MOVE_LABEL[move.classification] : "no assessment"}).`}
        </p>
      </div>
    </div>
  );
}

function CandidateCard({
  candidate,
  rank,
  ai,
  active,
  onSelect,
}: {
  candidate: VarahaCandidate;
  rank: number;
  ai: boolean;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      style={{
        textAlign: "left",
        background: active ? "var(--blue-soft)" : "var(--panel)",
        border: `1px solid ${active ? "var(--blue)" : "var(--line)"}`,
        borderRadius: 8,
        padding: 12,
        cursor: "pointer",
        font: "inherit",
        color: "inherit",
        minWidth: 0,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
        <strong>
          #{rank} {candidate.structureLabel}
        </strong>
        <span className="pcr-oi-caption">{rank === 1 ? (ai ? "AI pick" : "Top score") : "Alternative"}</span>
      </div>
      <div className="pcr-oi-caption" style={{ margin: "2px 0 8px" }}>
        {candidate.variantLabel} · {fmtExpiry(candidate.expiry)} ({candidate.dte}d)
      </div>
      <div style={{ fontSize: 12, lineHeight: 1.6 }}>
        {candidate.legs.map((leg) => (
          <div key={`${leg.action}-${leg.strike}-${leg.optionType}`}>
            <span style={{ color: leg.action === "BUY" ? "var(--green)" : "var(--red)", fontWeight: 600 }}>
              {leg.action === "BUY" ? "B" : "S"} ×{leg.qty}
            </span>{" "}
            {fmtNum(leg.strike)} {leg.optionType} @ {fmtNum(leg.price, 2)}
            <span className="pcr-oi-caption"> ({fmtSigned(leg.distance)})</span>
          </div>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "2px 10px", fontSize: 12, marginTop: 8 }}>
        <span>{candidate.premiumType === "DEBIT" ? "Debit" : "Credit"}</span>
        <strong>{fmtInr(Math.abs(candidate.netPremium))}</strong>
        <span>Max profit</span>
        <strong style={{ color: "var(--green)" }}>{fmtInr(candidate.maxProfit)}</strong>
        <span>Max loss</span>
        <strong style={{ color: "var(--red)" }}>{fmtInr(candidate.maxLoss)}</strong>
        <span>Reward / risk</span>
        <strong>{fmtNum(candidate.rewardRisk, 2)}</strong>
        <span>Breakevens</span>
        <strong>{candidate.breakevens.map((b) => fmtNum(b)).join(", ") || "—"}</strong>
        <span>Watch items</span>
        <strong style={{ color: candidate.watchItems.length ? "var(--amber)" : "var(--green)" }}>
          {candidate.watchItems.length || "None"}
        </strong>
      </div>
      {candidate.aiReason ? (
        <p style={{ fontSize: 12, margin: "8px 0 0", color: "var(--muted)" }}>{candidate.aiReason}</p>
      ) : null}
    </button>
  );
}

function CandidateDetail({ candidate, result }: { candidate: VarahaCandidate; result: VarahaResult }) {
  const em = result.move?.expectedMove ?? null;
  return (
    <div className="pcr-oi-section">
      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, alignItems: "baseline" }}>
        <h3 style={{ margin: 0 }}>
          {candidate.structureLabel} — {candidate.variantLabel}
        </h3>
        <span className="pcr-oi-caption">
          {fmtExpiry(candidate.expiry)} · {candidate.lots} lot × {candidate.lotSize} · entry charges ≈ {fmtInr(candidate.charges)} · net
          Δ {fmtNum(candidate.netDelta, 1)}
        </span>
      </div>

      <div style={{ overflowX: "auto", marginTop: 8 }}>
        <table>
          <thead>
            <tr>
              <th>Action</th>
              <th>Qty (lots)</th>
              <th>Strike</th>
              <th>Premium used</th>
              <th>LTP</th>
              <th>Bid / Ask</th>
              <th>Delta</th>
              <th>IV</th>
              <th>From spot</th>
              <th>% from spot</th>
              <th>× Exp. move</th>
            </tr>
          </thead>
          <tbody>
            {candidate.legs.map((leg) => (
              <tr key={`${leg.action}-${leg.strike}-${leg.optionType}`}>
                <td>
                  <span className={`badge ${leg.action === "BUY" ? "buy" : "sell"}`}>{leg.action}</span>
                </td>
                <td>{leg.qty * candidate.lots}</td>
                <td>
                  {fmtNum(leg.strike)} {leg.optionType}
                </td>
                <td>{fmtNum(leg.price, 2)}</td>
                <td>{fmtNum(leg.ltp, 2)}</td>
                <td>
                  {leg.bid != null && leg.ask != null ? `${fmtNum(leg.bid, 2)} / ${fmtNum(leg.ask, 2)}` : "—"}
                </td>
                <td>{leg.delta != null ? fmtNum(leg.delta, 2) : "—"}</td>
                <td>{leg.iv != null ? `${fmtNum(leg.iv, 1)}%` : "—"}</td>
                <td>{fmtSigned(leg.distance, 1)}</td>
                <td>{fmtSigned(leg.distancePercent, 2)}%</td>
                <td>{leg.emMultiple != null ? `${fmtSigned(leg.emMultiple, 2)}×` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="pcr-oi-caption" style={{ margin: "4px 0 0" }}>
        Premium used = ask for buys, bid for sells when a two-sided quote exists (LTP otherwise), so max loss is conservative.
      </p>

      <div style={{ marginTop: 14 }}>
        {candidate.payoff ? (
          <VarahaPayoffChart
            chartId={candidate.id}
            label={candidate.structureLabel}
            points={candidate.payoff}
            breakevens={candidate.breakevens}
            spot={result.spot ?? 0}
            expectedMove={em}
          />
        ) : (
          <p className="pcr-oi-caption">Payoff chart is drawn for the top 3 candidates only.</p>
        )}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))",
          gap: 14,
          marginTop: 14,
        }}
      >
        <div style={{ minWidth: 0, overflowX: "auto" }}>
          <ValidityPanel checks={candidate.checks} />
        </div>
        <div style={{ minWidth: 0, overflowX: "auto" }}>
          <h4 style={{ margin: "0 0 6px", fontSize: 13 }}>Payoff at expiry</h4>
          <table>
            <tbody>
              <tr>
                <td>{candidate.premiumType === "DEBIT" ? "Net debit" : "Net credit"}</td>
                <td>{fmtInr(Math.abs(candidate.netPremium))}</td>
              </tr>
              <tr>
                <td>Max profit</td>
                <td style={{ color: "var(--green)" }}>{fmtInr(candidate.maxProfit)}</td>
              </tr>
              <tr>
                <td>Max loss</td>
                <td style={{ color: "var(--red)" }}>{fmtInr(candidate.maxLoss)}</td>
              </tr>
              <tr>
                <td>Reward / risk</td>
                <td>{fmtNum(candidate.rewardRisk, 2)}</td>
              </tr>
              <tr>
                <td>Breakevens</td>
                <td>{candidate.breakevens.map((b) => fmtNum(b, 1)).join(" · ") || "—"}</td>
              </tr>
              {candidate.centralLossWidth != null ? (
                <tr>
                  <td>Central loss width</td>
                  <td>
                    {fmtNum(candidate.centralLossWidth)} pts ({fmtNum(candidate.lossWidthEmRatio, 2)}× expected move)
                  </td>
                </tr>
              ) : null}
              {candidate.zones.map((zone, i) => (
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
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function ValidityPanel({ checks }: { checks: VarahaCheck[] }) {
  const hard = checks.filter((c) => c.hard);
  const soft = checks.filter((c) => !c.hard);
  const renderRows = (rows: VarahaCheck[]) =>
    rows.map((check) => (
      <tr key={check.key}>
        <td>{check.label}</td>
        <td style={{ color: CHECK_COLOR[check.status], fontWeight: 600 }}>{check.status}</td>
        <td className="pcr-oi-caption" style={{ fontStyle: "normal" }}>
          {check.detail}
        </td>
      </tr>
    ));
  const hardFailed = hard.some((c) => c.status === "FAIL");
  return (
    <div>
      <h4 style={{ margin: "0 0 6px", fontSize: 13 }}>
        Validity —{" "}
        <span style={{ color: hardFailed ? "var(--red)" : "var(--green)" }}>{hardFailed ? "INVALID" : "VALID"}</span>
      </h4>
      <table>
        <tbody>
          <tr>
            <th colSpan={3}>Hard gates (deterministic)</th>
          </tr>
          {renderRows(hard)}
          <tr>
            <th colSpan={3}>Soft checks (used for ranking)</th>
          </tr>
          {renderRows(soft)}
        </tbody>
      </table>
    </div>
  );
}

function AiPanel({ result }: { result: VarahaResult }) {
  const sections = result.ai?.sections;
  return (
    <div className="pcr-oi-section">
      <h3 style={{ margin: "0 0 6px" }}>AI analysis</h3>
      {sections ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 320px), 1fr))", gap: "10px 18px" }}>
          {AI_SECTION_LABEL.filter(([key]) => sections[key]).map(([key, label]) => (
            <div key={key}>
              <h4 style={{ margin: "0 0 2px", fontSize: 13 }}>{label}</h4>
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5 }}>{sections[key]}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="pcr-oi-caption" style={{ margin: 0 }}>
          {result.ai?.error ?? "No AI analysis for this run (no candidates to rank)."}
        </p>
      )}
      <p className="pcr-oi-caption" style={{ margin: "8px 0 0" }}>
        The AI only ranks and explains candidates the engine built. It cannot add strikes or override a hard gate.
      </p>
    </div>
  );
}

function ScoreDetails({ result }: { result: VarahaResult }) {
  const move = result.move;
  const direction = result.direction;
  if (!move || !direction) return null;
  return (
    <div className="pcr-oi-section">
      <h3 style={{ margin: "0 0 8px" }}>How the decision was scored</h3>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 420px), 1fr))", gap: 16 }}>
        <div style={{ overflowX: "auto" }}>
          <h4 style={{ margin: "0 0 6px", fontSize: 13 }}>
            Move score {move.moveScore} / {move.maxScore} → {MOVE_LABEL[move.classification]}
          </h4>
          <table>
            <thead>
              <tr>
                <th>Component</th>
                <th>Value</th>
                <th>Score</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {move.components.map((c) => (
                <tr key={c.key}>
                  <td>{c.label}</td>
                  <td>{c.value}</td>
                  <td>
                    {c.score} / {c.max}
                  </td>
                  <td className="pcr-oi-caption" style={{ fontStyle: "normal" }}>
                    {c.detail}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ overflowX: "auto" }}>
          <h4 style={{ margin: "0 0 6px", fontSize: 13 }}>
            Direction: {direction.bullish} bullish · {direction.bearish} bearish · {direction.neutral} neutral →{" "}
            {DIRECTION_LABEL[direction.classification]}
          </h4>
          <table>
            <thead>
              <tr>
                <th>Signal</th>
                <th>Vote</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {direction.signals.map((s) => (
                <tr key={s.key}>
                  <td>{s.label}</td>
                  <td
                    style={{
                      color: s.vote == null ? "var(--muted)" : s.vote > 0 ? "var(--green)" : s.vote < 0 ? "var(--red)" : "var(--muted)",
                      fontWeight: 600,
                    }}
                  >
                    {s.vote == null ? "n/a" : s.vote > 0 ? "Bullish" : s.vote < 0 ? "Bearish" : "Neutral"}
                  </td>
                  <td className="pcr-oi-caption" style={{ fontStyle: "normal" }}>
                    {s.detail}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {result.events.length ? (
        <p className="pcr-oi-caption" style={{ margin: "8px 0 0" }}>
          Events considered: {result.events.map((e) => `${e.headline} (${e.impact})`).join(" · ")}
        </p>
      ) : null}
    </div>
  );
}

function OtherCandidates({ rest, result, onSelect }: { rest: VarahaCandidate[]; result: VarahaResult; onSelect: (id: string) => void }) {
  return (
    <div className="pcr-oi-section">
      <details>
        <summary style={{ cursor: "pointer", fontWeight: 600 }}>
          Other candidates ({rest.length} passed hard gates · {result.rejected.length} rejected)
        </summary>
        {rest.length ? (
          <div style={{ overflowX: "auto", marginTop: 8 }}>
            <table>
              <thead>
                <tr>
                  <th>Structure</th>
                  <th>Variant</th>
                  <th>Expiry</th>
                  <th>Legs</th>
                  <th>Debit / credit</th>
                  <th>Max profit</th>
                  <th>Max loss</th>
                  <th>R/R</th>
                  <th>Watch items</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rest.map((c) => (
                  <tr key={c.id}>
                    <td>{c.structureLabel}</td>
                    <td>{c.variantLabel}</td>
                    <td>{fmtExpiry(c.expiry)}</td>
                    <td style={{ fontSize: 12 }}>
                      {c.legs.map((l) => `${l.action === "BUY" ? "+" : "−"}${l.qty} ${fmtNum(l.strike)}${l.optionType}`).join(" ")}
                    </td>
                    <td>{fmtInr(c.netPremium)}</td>
                    <td style={{ color: "var(--green)" }}>{fmtInr(c.maxProfit)}</td>
                    <td style={{ color: "var(--red)" }}>{fmtInr(c.maxLoss)}</td>
                    <td>{fmtNum(c.rewardRisk, 2)}</td>
                    <td>{c.watchItems.length}</td>
                    <td>
                      <button type="button" className="button secondary" onClick={() => onSelect(c.id)}>
                        View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {result.rejected.length ? (
          <div style={{ marginTop: 10 }}>
            <h4 style={{ margin: "0 0 4px", fontSize: 13 }}>Rejected by a hard gate</h4>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
              {result.rejected.map((r) => (
                <li key={r.id}>
                  {r.structureLabel} · {r.variantLabel} · {fmtExpiry(r.expiry)} — {r.reasons.join("; ")}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </details>
    </div>
  );
}

function SettingsPanel({ config, onSaved }: { config: VarahaConfig | null; onSaved: (config: VarahaConfig) => void }) {
  const [lots, setLots] = useState("");
  const [maxLoss, setMaxLoss] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (config) {
      setLots(String(config.lots));
      setMaxLoss(String(config.maxLossInr));
    }
  }, [config]);

  async function save() {
    const lotsValue = Number(lots);
    const lossValue = Number(maxLoss);
    if (!Number.isInteger(lotsValue) || lotsValue < 1 || !(lossValue > 0)) {
      setError("Lots must be a whole number ≥ 1 and max loss must be positive.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      onSaved(await updateVarahaConfig({ lots: lotsValue, maxLossInr: lossValue }));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to save settings.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="pcr-oi-section">
      <h3 style={{ margin: "0 0 6px" }}>Settings</h3>
      {error ? <div className="alert error">{error}</div> : null}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
          Lots
          <input type="number" min={1} step={1} value={lots} onChange={(e) => setLots(e.target.value)} style={{ width: 70 }} />
        </label>
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
          Max loss limit ₹
          <input type="number" min={1} step={1000} value={maxLoss} onChange={(e) => setMaxLoss(e.target.value)} style={{ width: 110 }} />
        </label>
        <button type="button" className="button secondary" onClick={save} disabled={!config || saving}>
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
      <p className="pcr-oi-caption" style={{ margin: "6px 0 0" }}>
        Applies from the next run. Max loss is a hard gate. Thresholds (DTE {config?.minDte}–{config?.maxDte}, big move ≥{" "}
        {config?.bigMoveScore}, watch ≥ {config?.watchScore}, direction ≥ {config?.directionConfidencePercent}%, min R/R{" "}
        {config?.minRewardRisk}, loss width ≤ {config?.lossWidthEmTarget}× EM) are research starting points set in the backend
        config.
        {config && !config.aiEnabled ? " OpenAI key not configured — ranking will use the deterministic fallback." : ""}
      </p>
    </div>
  );
}

function HistoryPanel({ history }: { history: VarahaHistoryItem[] }) {
  if (!history.length) return null;
  return (
    <div className="pcr-oi-section">
      <h3 style={{ margin: "0 0 6px" }}>Recent recommendations</h3>
      <div style={{ overflowX: "auto" }}>
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Run</th>
              <th>Spot</th>
              <th>Move</th>
              <th>Engine direction</th>
              <th>Override</th>
              <th>Status</th>
              <th>Top candidate</th>
              <th>Max profit / loss</th>
              <th>Ranking</th>
            </tr>
          </thead>
          <tbody>
            {history.map((item) => (
              <tr key={item.id}>
                <td>{item.sessionDate}</td>
                <td>{TRIGGER_LABEL[item.trigger] ?? item.trigger}</td>
                <td>{fmtNum(item.spot, 1)}</td>
                <td>{item.moveClass ? `${MOVE_LABEL[item.moveClass]} (${item.moveScore})` : "—"}</td>
                <td>{item.engineDirection ? DIRECTION_LABEL[item.engineDirection] : "—"}</td>
                <td>{item.manualOverride ?? "—"}</td>
                <td style={{ color: item.status ? STATUS_COLOR[item.status] : undefined }}>
                  {item.status ? STATUS_LABEL[item.status] : "—"}
                </td>
                <td>
                  {item.topCandidate
                    ? `${item.topCandidate.structureLabel} · ${item.topCandidate.variantLabel} · ${fmtExpiry(item.topCandidate.expiry)}`
                    : "—"}
                </td>
                <td>
                  {item.topCandidate ? `${fmtInr(item.topCandidate.maxProfit)} / ${fmtInr(item.topCandidate.maxLoss)}` : "—"}
                </td>
                <td>{item.rankingSource ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
