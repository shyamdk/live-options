import type {
  AuthSession,
  AuthStatus,
  DhanSession,
  Journal,
  JournalInsights,
  JournalSession,
  LiveTradeSnapshot,
  MarketIndicesPayload,
  TradeLevels,
} from "@/types/live";
import type { GammaBlastSessionDetail, GammaBlastState } from "@/types/gamma-blast";
import type { Ema5CandlesResponse, Ema5Config, Ema5Session, Ema5SessionDetail, Ema5Side, Ema5State } from "@/types/ema5";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8001";
const AUTH_TOKEN_KEY = "live-options-auth-token";

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(AUTH_TOKEN_KEY);
}

export function setAuthToken(token: string): void {
  window.localStorage.setItem(AUTH_TOKEN_KEY, token);
}

export function clearAuthToken(): void {
  if (typeof window !== "undefined") window.localStorage.removeItem(AUTH_TOKEN_KEY);
}

async function apiJson<T>(path: string, init?: RequestInit, fallback = "Request failed"): Promise<T> {
  const token = getAuthToken();
  const response = await fetch(new URL(path, API_BASE), {
    cache: "no-store",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    if (response.status === 401) clearAuthToken();
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

export async function getAuthStatus(): Promise<AuthStatus> {
  return apiJson<AuthStatus>("/api/auth/status", undefined, "Failed to load auth status");
}

export async function getAuthSession(): Promise<AuthSession> {
  return apiJson<AuthSession>("/api/auth/session", undefined, "Failed to load auth session");
}

export async function loginApp(username: string, password: string): Promise<AuthSession> {
  const payload = await apiJson<AuthSession & { token: string }>(
    "/api/auth/login",
    { method: "POST", body: JSON.stringify({ username, password }) },
    "Login failed",
  );
  setAuthToken(payload.token);
  return payload;
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

export async function approveRiskExit(tradeId: string) {
  return apiJson<Record<string, unknown>>(
    `/api/trades/${encodeURIComponent(tradeId)}/risk/approve`,
    { method: "POST" },
    "Failed to approve risk exit",
  );
}

export async function getGammaBlastState(): Promise<GammaBlastState> {
  return apiJson<GammaBlastState>("/api/gamma-blast/state", undefined, "Failed to load Gamma Blast state");
}

export async function approveGammaBlastSignal(signalId: number) {
  return apiJson<Record<string, unknown>>(
    `/api/gamma-blast/signals/${signalId}/approve`,
    { method: "POST" },
    "Failed to approve Gamma Blast signal",
  );
}

export async function getGammaBlastSessions() {
  return apiJson<{ sessions: GammaBlastSessionDetail["session"][] }>(
    "/api/gamma-blast/sessions",
    undefined,
    "Failed to load Gamma Blast sessions",
  );
}

export async function getGammaBlastSessionDetail(sessionId: string): Promise<GammaBlastSessionDetail> {
  return apiJson<GammaBlastSessionDetail>(
    `/api/gamma-blast/sessions/${encodeURIComponent(sessionId)}`,
    undefined,
    "Failed to load Gamma Blast session detail",
  );
}

export async function getEma5State(): Promise<Ema5State> {
  return apiJson<Ema5State>("/api/ema5/state", undefined, "Failed to load ema5 state");
}

export async function getEma5Candles(side: Ema5Side): Promise<Ema5CandlesResponse> {
  return apiJson<Ema5CandlesResponse>(`/api/ema5/candles?side=${side}`, undefined, "Failed to load ema5 candles");
}

export async function getEma5Config(): Promise<Ema5Config> {
  return apiJson<Ema5Config>("/api/ema5/config", undefined, "Failed to load ema5 config");
}

export async function updateEma5Config(maxTradesPerDaySide: number): Promise<Ema5Config> {
  return apiJson<Ema5Config>(
    "/api/ema5/config",
    { method: "PUT", body: JSON.stringify({ maxTradesPerDaySide }) },
    "Failed to update ema5 config",
  );
}

export async function approveEma5Signal(signalId: number) {
  return apiJson<Record<string, unknown>>(
    `/api/ema5/signals/${signalId}/approve`,
    { method: "POST" },
    "Failed to approve ema5 signal",
  );
}

export async function getEma5Sessions() {
  return apiJson<{ sessions: Ema5Session[] }>("/api/ema5/sessions", undefined, "Failed to load ema5 sessions");
}

export async function getEma5SessionDetail(sessionId: string): Promise<Ema5SessionDetail> {
  return apiJson<Ema5SessionDetail>(
    `/api/ema5/sessions/${encodeURIComponent(sessionId)}`,
    undefined,
    "Failed to load ema5 session detail",
  );
}

export async function getRecentJournalSessions(): Promise<{ sessions: JournalSession[] }> {
  return apiJson<{ sessions: JournalSession[] }>("/api/journals/recent", undefined, "Failed to load trade journals");
}

export async function saveJournalEntry(
  tradeDate: string,
  fields: Pick<Journal, "strategyDetails" | "howIFelt" | "whatHappened" | "lessonsLearnt" | "comments">,
) {
  return apiJson<{ journal: Journal }>(
    `/api/journals/${encodeURIComponent(tradeDate)}`,
    { method: "PUT", body: JSON.stringify(fields) },
    "Failed to save journal",
  );
}

export async function getJournalInsights(): Promise<JournalInsights> {
  return apiJson<JournalInsights>("/api/journals/insights", undefined, "Failed to load journal insights");
}

export async function refreshJournalInsights(): Promise<JournalInsights> {
  return apiJson<JournalInsights>(
    "/api/journals/insights/refresh",
    { method: "POST" },
    "Failed to refresh journal insights",
  );
}
