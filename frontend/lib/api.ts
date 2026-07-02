import type {
  DhanSession,
  LiveTradeSnapshot,
  MarketIndicesPayload,
  TodayJournalPayload,
  TradeLevels,
} from "@/types/live";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function apiJson<T>(path: string, init?: RequestInit, fallback = "Request failed"): Promise<T> {
  const response = await fetch(new URL(path, API_BASE), {
    cache: "no-store",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = `${fallback}: ${response.status}`;
    try {
      const payload = await response.json();
      detail = payload?.detail ? `${fallback}: ${payload.detail}` : detail;
    } catch {
      // Keep status fallback.
    }
    throw new Error(detail);
  }
  return response.json();
}

export async function getMarketIndices(): Promise<MarketIndicesPayload> {
  return apiJson<MarketIndicesPayload>("/api/market/indices", undefined, "Failed to load market strip");
}

export async function getDhanSession(): Promise<DhanSession> {
  return apiJson<DhanSession>("/api/dhan/session", undefined, "Failed to load Dhan session");
}

export async function loginDhan(forceRefresh = false): Promise<Record<string, unknown>> {
  return apiJson<Record<string, unknown>>(
    "/api/dhan/login",
    { method: "POST", body: JSON.stringify({ forceRefresh }) },
    "Dhan login failed",
  );
}

export async function getLiveTrades(): Promise<LiveTradeSnapshot> {
  return apiJson<LiveTradeSnapshot>("/api/trades/live", undefined, "Failed to load live trades");
}

export async function saveTradeLevels(tradeId: string, levels: Pick<TradeLevels, "stopLoss" | "target" | "notes">) {
  return apiJson<{ tradeId: string; levels: TradeLevels }>(
    `/api/trades/${encodeURIComponent(tradeId)}/levels`,
    { method: "PUT", body: JSON.stringify(levels) },
    "Failed to save trade levels",
  );
}

export async function closeTrade(tradeId: string, quantity?: number) {
  return apiJson<Record<string, unknown>>(
    `/api/trades/${encodeURIComponent(tradeId)}/close`,
    { method: "POST", body: JSON.stringify({ quantity }) },
    "Failed to close trade",
  );
}

export async function getTodayJournal(): Promise<TodayJournalPayload> {
  return apiJson<TodayJournalPayload>("/api/journals/today", undefined, "Failed to load trade journal");
}

export async function saveJournal(tradeDate: string, strategyDetails: string, lessonsLearnt: string) {
  return apiJson<{ journal: TodayJournalPayload["journal"] }>(
    `/api/journals/${encodeURIComponent(tradeDate)}`,
    { method: "PUT", body: JSON.stringify({ strategyDetails, lessonsLearnt }) },
    "Failed to save journal",
  );
}

