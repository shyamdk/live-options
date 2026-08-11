"use client";

import { useEffect, useState } from "react";

import { getMarketNews } from "@/lib/api";
import type { MarketNewsItem } from "@/types/live";

const NEWS_REFRESH_MS = 180000;

export default function MarketNewsTicker() {
  const [items, setItems] = useState<MarketNewsItem[]>([]);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const payload = await getMarketNews();
        if (active) setItems(payload.items);
      } catch {
        // Stay silent -- the market strip above already surfaces connectivity issues.
      }
    }
    load();
    const timer = window.setInterval(load, NEWS_REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  if (!items.length) return null;

  const track = (
    <span className="news-ticker-track-inner">
      {items.map((item, index) => (
        <a
          key={`${index}-${item.headline}`}
          className={`news-ticker-item ${item.impact}`}
          href={item.link ?? undefined}
          target={item.link ? "_blank" : undefined}
          rel={item.link ? "noopener noreferrer" : undefined}
        >
          {item.headline}
        </a>
      ))}
    </span>
  );

  return (
    <div className="news-ticker">
      <div className="news-ticker-track">
        {track}
        {track}
      </div>
    </div>
  );
}
