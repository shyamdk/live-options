"use client";

import { BarChart3 } from "lucide-react";
import { useEffect, useState } from "react";

import {
  ChartHandle,
  CE_COLOR,
  Legend,
  linkCrosshairs,
  NIFTY_COLOR,
  OiChangeChart,
  PcrChart,
  PE_COLOR,
  SENSEX_COLOR,
} from "@/components/PcrOiPanel";
import { getPcrOiSessionDates, getPcrOiSnapshots } from "@/lib/api";
import type { PcrOiPayload } from "@/types/live";

const REFRESH_MS = 120000;
type Underlying = "NIFTY" | "SENSEX";

export default function OiAnalysisPage() {
  const [underlying, setUnderlying] = useState<Underlying>("NIFTY");
  const [data, setData] = useState<PcrOiPayload>({ NIFTY: [], SENSEX: [] });
  const [error, setError] = useState<string | null>(null);
  const [sessionDates, setSessionDates] = useState<string[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [pcrHandle, setPcrHandle] = useState<ChartHandle | null>(null);
  const [oiHandle, setOiHandle] = useState<ChartHandle | null>(null);

  useEffect(() => {
    if (sessionDates.length) return;
    let active = true;
    getPcrOiSessionDates()
      .then((dates) => {
        if (active) setSessionDates(dates);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [sessionDates.length]);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const payload = await getPcrOiSnapshots(selectedDate ?? undefined);
        if (active) {
          setData(payload);
          setError(null);
        }
      } catch (exc) {
        if (active) setError(exc instanceof Error ? exc.message : "Failed to load PCR/OI data.");
      }
    }
    load();
    if (selectedDate !== null) {
      return () => {
        active = false;
      };
    }
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [selectedDate]);

  useEffect(() => {
    if (!pcrHandle || !oiHandle) return;
    return linkCrosshairs([pcrHandle, oiHandle]);
  }, [pcrHandle, oiHandle]);

  const points = data[underlying];
  const color = underlying === "NIFTY" ? NIFTY_COLOR : SENSEX_COLOR;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>
            <BarChart3 size={20} style={{ verticalAlign: "-3px", marginRight: 8 }} />
            OI Analysis
          </h1>
          <p>Full-width PCR and Change in OI, one underlying at a time, for reading fine intraday moves precisely.</p>
        </div>
        <div className="toolbar">
          <label className="subtext" htmlFor="oi-analysis-underlying-select">
            Underlying
          </label>
          <select
            id="oi-analysis-underlying-select"
            className="pcr-oi-session-select"
            value={underlying}
            onChange={(event) => {
              setUnderlying(event.target.value as Underlying);
              setPcrHandle(null);
              setOiHandle(null);
            }}
          >
            <option value="NIFTY">NIFTY</option>
            <option value="SENSEX">SENSEX</option>
          </select>
          <label className="subtext" htmlFor="oi-analysis-session-select">
            Session
          </label>
          <select
            id="oi-analysis-session-select"
            className="pcr-oi-session-select"
            value={selectedDate ?? ""}
            onChange={(event) => setSelectedDate(event.target.value || null)}
          >
            <option value="">Today (live)</option>
            {sessionDates.map((date) => (
              <option key={date} value={date}>
                {date}
              </option>
            ))}
          </select>
          {selectedDate ? (
            <span className="pcr-oi-caption" style={{ margin: 0 }}>
              Viewing a past session — not live, no auto-refresh.
            </span>
          ) : null}
        </div>
      </header>

      {error ? <div className="alert error">{error}</div> : null}

      <div className="pcr-oi-section">
        <h3>Put-Call Ratio — {underlying}</h3>
        <PcrChart title={underlying} color={color} points={points} onReady={setPcrHandle} height={440} />
      </div>

      <div className="pcr-oi-section">
        <h3>Change in OI — {underlying}</h3>
        <p className="pcr-oi-caption">Y-axis in lakhs (1 L = 100,000 contracts) for legible fine-grained moves.</p>
        <Legend items={[{ label: "CE chg OI", color: CE_COLOR }, { label: "PE chg OI", color: PE_COLOR }]} />
        <OiChangeChart title={underlying} points={points} onReady={setOiHandle} height={440} />
      </div>
    </section>
  );
}
