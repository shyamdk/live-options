"use client";

import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { useEffect, useState } from "react";

import { getMarketCommodities } from "@/lib/api";
import { isMarketHoursNow } from "@/lib/marketHours";
import type { MarketIndex } from "@/types/live";

const numberFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
// Commodities refresh slower than the main NIFTY/SENSEX strip -- these
// don't need second-by-second freshness for a context panel.
const COMMODITIES_REFRESH_MS = secondsToMs(process.env.NEXT_PUBLIC_COMMODITIES_REFRESH_SECONDS, 60);

function signed(value: number | null | undefined, suffix = "") {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const formatted = `${numberFormat.format(Math.abs(value))}${suffix}`;
  return `${value >= 0 ? "+" : "-"}${formatted}`;
}

export default function CommoditiesStrip() {
  const [indices, setIndices] = useState<MarketIndex[]>([]);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const payload = await getMarketCommodities();
        if (!active) return;
        const hasPrices = payload.indices.some((index) => index.lastPrice !== null && index.lastPrice !== undefined);
        if (hasPrices) setIndices(payload.indices);
        setStatus(payload.stale || payload.warning ? "Commodities data stale" : null);
      } catch {
        if (active) setStatus("Commodities strip unavailable");
      }
    }
    load();
    const timer = window.setInterval(() => {
      if (isMarketHoursNow()) load();
    }, COMMODITIES_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <div className="market-strip">
      {indices.map((index) => {
        const positive = (index.change ?? 0) >= 0;
        return (
          <div className="market-index" key={index.name}>
            <span className="market-name">{index.name}</span>
            <strong>{index.lastPrice === null ? "-" : numberFormat.format(index.lastPrice)}</strong>
            <span className={positive ? "market-up" : "market-down"}>
              {signed(index.change)} ({signed(index.percentChange, "%")})
              {positive ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
            </span>
          </div>
        );
      })}
      {status ? <span className="market-empty">{indices.length ? status : "Commodities strip unavailable"}</span> : null}
    </div>
  );
}

function secondsToMs(value: string | undefined, fallbackSeconds: number): number {
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : fallbackSeconds * 1000;
}
