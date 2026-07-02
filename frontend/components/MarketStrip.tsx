"use client";

import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { useEffect, useState } from "react";

import { getMarketIndices } from "@/lib/api";
import type { MarketIndex } from "@/types/live";

const numberFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });

function signed(value: number | null | undefined, suffix = "") {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const formatted = `${numberFormat.format(Math.abs(value))}${suffix}`;
  return `${value >= 0 ? "+" : "-"}${formatted}`;
}

export default function MarketStrip() {
  const [indices, setIndices] = useState<MarketIndex[]>([]);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const payload = await getMarketIndices();
        if (active) setIndices(payload.indices);
      } catch {
        if (active) setIndices([]);
      }
    }
    load();
    const timer = window.setInterval(load, 10000);
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
      {!indices.length ? <span className="market-empty">Market strip unavailable</span> : null}
    </div>
  );
}

