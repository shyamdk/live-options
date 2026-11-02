import type {
  AuthSession,
  AuthStatus,
  BacktestReport,
  ChatMessage,
  DhanSession,
  Journal,
  JournalInsights,
  JournalSession,
  LiveTradeSnapshot,
  MarketCandlesResponse,
  MarketIndicesPayload,
  MarketNewsPayload,
  OiUpgradedPayload,
  PaperTrade,
  PaperTradingSettings,
  PcrOiPayload,
  SuggestConfig,
  TagExitLeg,
  TagLevels,
  TradeLevels,
} from "@/types/live";
import type { SwingConfig, SwingRetro, SwingState } from "@/types/equity-swing";
import type { AlertsPayload, NewAlert, PortalAlert, TelegramStatus } from "@/types/alerts";
import type { GammaBlastSessionDetail, GammaBlastState } from "@/types/gamma-blast";
import type { Ema5CandlesResponse, Ema5Config, Ema5Session, Ema5SessionDetail, Ema5Side, Ema5State } from "@/types/ema5";
import type { AnimeshCandlesResponse, AnimeshSession, AnimeshSessionDetail, AnimeshSide, AnimeshState } from "@/types/animesh";
import type { CreditSpreadState } from "@/types/credit-spread";
import type { SimpleCrossoverConfig, SimpleCrossoverData, SimpleCrossoverSide, SimpleCrossoverTrade } from "@/types/simple-crossover";
import type { ThetaRuntimeConfig, ThetaSession, ThetaSessionDetail, ThetaState } from "@/types/theta";
import type { VarahaPaperConfig, VarahaPaperState, VarahaPaperTrade } from "@/types/varaha-paper";
import type { BtcCalmConfig, BtcCalmState, BtcCalmTrade, BtcCalmTradeDetail } from "@/types/btc-calm";
import type { DishaState } from "@/types/disha";
import type { CalmConfig, CalmState, CalmTrade, CalmTradeDetail } from "@/types/calm-strangle";
import type { NiftyStrangleConfig, NiftyStranglePlan, NiftyStrangleTrade } from "@/types/nifty-strangle";
import type { MeltingConfig, MeltingDaySummary, MeltingState, MeltingTag, MeltingTrade } from "@/types/melting";
import type { MantraAlarm, MantraConfig, MantraMode, MantraPlan, MantraTrade } from "@/types/mantra";
import type { TurtleAlarm, TurtleConfig, TurtleState, TurtleTrade } from "@/types/turtle";
import type { BatmanAnalysis, BatmanConfig, BatmanMode, BatmanPreview, BatmanTrade } from "@/types/batman";
import type { BtcSpotChart, BtcStrangleChart, BtcStrangleConfig, BtcStranglePreview, BtcStrangleTrade } from "@/types/btc-strangle";
import type {
  FullButterflyFilters,
  FullButterflyScan,
  VarahaConfig,
  VarahaHistoryItem,
  VarahaLatestPayload,
  VarahaOverride,
} from "@/types/varaha";
import type { EquityNewsPayload, EquityOptionsReportPayload, EquityPortfolioPayload, EquityTransactionsPayload } from "@/types/equity";

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

export async function getMarketCommodities(): Promise<MarketIndicesPayload> {
  return apiJson<MarketIndicesPayload>("/api/market/commodities", undefined, "Failed to load commodities strip");
}

export async function getMarketNews(): Promise<MarketNewsPayload> {
  return apiJson<MarketNewsPayload>("/api/market/news", undefined, "Failed to load market news");
}

export async function refreshMarketNews(): Promise<MarketNewsPayload> {
  return apiJson<MarketNewsPayload>("/api/market/news/refresh", { method: "POST" }, "Failed to refresh market news");
}

export async function getPcrOiSnapshots(sessionDate?: string): Promise<PcrOiPayload> {
  const query = sessionDate ? `?date=${encodeURIComponent(sessionDate)}` : "";
  return apiJson<PcrOiPayload>(`/api/market/pcr-oi${query}`, undefined, "Failed to load PCR/OI data");
}

export async function refreshPcrOiSnapshots(sessionDate?: string): Promise<PcrOiPayload> {
  const query = sessionDate ? `?date=${encodeURIComponent(sessionDate)}` : "";
  return apiJson<PcrOiPayload>(
    `/api/market/pcr-oi/refresh${query}`,
    { method: "POST" },
    "Failed to refresh PCR/OI data",
  );
}

export async function getOiUpgradedSignal(sessionDate?: string): Promise<OiUpgradedPayload> {
  const query = sessionDate ? `?date=${encodeURIComponent(sessionDate)}` : "";
  return apiJson<OiUpgradedPayload>(`/api/market/oi-upgraded${query}`, undefined, "Failed to load upgraded OI signal");
}

export async function refreshOiUpgradedSignal(sessionDate?: string): Promise<OiUpgradedPayload> {
  const query = sessionDate ? `?date=${encodeURIComponent(sessionDate)}` : "";
  return apiJson<OiUpgradedPayload>(
    `/api/market/oi-upgraded/refresh${query}`,
    { method: "POST" },
    "Failed to refresh upgraded OI signal",
  );
}

export async function getOiUpgradedBacktest(): Promise<BacktestReport> {
  return apiJson<BacktestReport>("/api/market/oi-upgraded/backtest", undefined, "Failed to load the backtest report");
}

export async function getPcrOiSessionDates(): Promise<string[]> {
  const payload = await apiJson<{ dates: string[] }>(
    "/api/market/pcr-oi/sessions",
    undefined,
    "Failed to load PCR/OI session list",
  );
  return payload.dates;
}

export async function getTradeCandles(params: {
  securityId: string;
  exchangeSegment: string;
  instrument: string;
  interval?: string;
  date?: string;
}): Promise<MarketCandlesResponse> {
  const query = new URLSearchParams({
    securityId: params.securityId,
    exchangeSegment: params.exchangeSegment,
    instrument: params.instrument,
    interval: params.interval ?? "5",
  });
  if (params.date) query.set("date", params.date);
  return apiJson<MarketCandlesResponse>(`/api/market/candles?${query.toString()}`, undefined, "Failed to load chart candles");
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

export async function saveTradeLevels(tradeId: string, levels: Pick<TradeLevels, "stopLoss" | "target" | "notes" | "tag">) {
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

export async function saveTagLevels(tag: string, levels: { target: number | null; stopLoss: number | null }) {
  return apiJson<{ levels: TagLevels }>(
    `/api/trades/tags/${encodeURIComponent(tag)}/levels`,
    { method: "PUT", body: JSON.stringify(levels) },
    "Failed to save tag levels",
  );
}

export async function exitTag(tag: string, reason: "manual" | "suggestion" = "manual") {
  return apiJson<{ tag: string; status: string; message?: string; legs?: TagExitLeg[] }>(
    `/api/trades/tags/${encodeURIComponent(tag)}/exit?reason=${reason}`,
    { method: "POST" },
    "Failed to close tag",
  );
}

export async function updateSuggestConfig(updates: Partial<SuggestConfig>): Promise<SuggestConfig> {
  return apiJson<SuggestConfig>(
    "/api/trades/suggestions/config",
    { method: "PUT", body: JSON.stringify(updates) },
    "Failed to save suggestion settings",
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

export async function getAnimeshState(): Promise<AnimeshState> {
  return apiJson<AnimeshState>("/api/animesh/state", undefined, "Failed to load animesh-scalping state");
}

export async function getAnimeshCandles(side: AnimeshSide): Promise<AnimeshCandlesResponse> {
  return apiJson<AnimeshCandlesResponse>(`/api/animesh/candles?side=${side}`, undefined, "Failed to load animesh-scalping candles");
}

export async function approveAnimeshSignal(signalId: number) {
  return apiJson<Record<string, unknown>>(
    `/api/animesh/signals/${signalId}/approve`,
    { method: "POST" },
    "Failed to approve animesh-scalping signal",
  );
}

export async function getAnimeshSessions() {
  return apiJson<{ sessions: AnimeshSession[] }>("/api/animesh/sessions", undefined, "Failed to load animesh-scalping sessions");
}

export async function getAnimeshSessionDetail(sessionId: string): Promise<AnimeshSessionDetail> {
  return apiJson<AnimeshSessionDetail>(
    `/api/animesh/sessions/${encodeURIComponent(sessionId)}`,
    undefined,
    "Failed to load animesh-scalping session detail",
  );
}

export async function getThetaState(): Promise<ThetaState> {
  return apiJson<ThetaState>("/api/theta/state", undefined, "Failed to load Theta Book state");
}

export async function getThetaConfig(): Promise<ThetaRuntimeConfig> {
  return apiJson<ThetaRuntimeConfig>("/api/theta/config", undefined, "Failed to load Theta Book config");
}

export async function updateThetaConfig(updates: Partial<ThetaRuntimeConfig>): Promise<ThetaRuntimeConfig> {
  return apiJson<ThetaRuntimeConfig>(
    "/api/theta/config",
    { method: "PUT", body: JSON.stringify(updates) },
    "Failed to update Theta Book config",
  );
}

export async function approveThetaSignal(signalId: number) {
  return apiJson<Record<string, unknown>>(
    `/api/theta/signals/${signalId}/approve`,
    { method: "POST" },
    "Failed to approve Theta Book signal",
  );
}

export async function rejectThetaSignal(signalId: number) {
  return apiJson<Record<string, unknown>>(
    `/api/theta/signals/${signalId}/reject`,
    { method: "POST" },
    "Failed to reject Theta Book signal",
  );
}

export async function getThetaSessions() {
  return apiJson<{ sessions: ThetaSession[] }>("/api/theta/sessions", undefined, "Failed to load Theta Book sessions");
}

export async function getThetaSessionDetail(sessionId: string): Promise<ThetaSessionDetail> {
  return apiJson<ThetaSessionDetail>(
    `/api/theta/sessions/${encodeURIComponent(sessionId)}`,
    undefined,
    "Failed to load Theta Book session detail",
  );
}

export async function getCreditSpreadState(): Promise<CreditSpreadState> {
  return apiJson<CreditSpreadState>("/api/credit-spread/state", undefined, "Failed to load credit spread state");
}

export async function approveCreditSpreadSignal(signalId: number) {
  return apiJson<Record<string, unknown>>(
    `/api/credit-spread/signals/${signalId}/approve`,
    { method: "POST" },
    "Failed to approve credit spread signal",
  );
}

export async function evaluateCreditSpread() {
  return apiJson<Record<string, unknown>>(
    "/api/credit-spread/evaluate",
    { method: "POST" },
    "Failed to evaluate credit spread",
  );
}

export async function exitCreditSpread() {
  return apiJson<Record<string, unknown>>(
    "/api/credit-spread/exit",
    { method: "POST" },
    "Failed to exit credit spread position",
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

export async function getPaperTrades(): Promise<{ trades: PaperTrade[] }> {
  return apiJson<{ trades: PaperTrade[] }>("/api/paper-trading/trades", undefined, "Failed to load paper trades");
}

export async function getPaperTradingSettings(): Promise<PaperTradingSettings> {
  return apiJson<PaperTradingSettings>(
    "/api/paper-trading/settings",
    undefined,
    "Failed to load paper trading settings",
  );
}

export async function updatePaperTradingSettings(
  fields: Partial<PaperTradingSettings>,
): Promise<PaperTradingSettings> {
  return apiJson<PaperTradingSettings>(
    "/api/paper-trading/settings",
    { method: "PUT", body: JSON.stringify(fields) },
    "Failed to save paper trading settings",
  );
}

export async function getSimpleCrossoverConfig(): Promise<SimpleCrossoverConfig> {
  return apiJson<SimpleCrossoverConfig>(
    "/api/simple-crossover/config",
    undefined,
    "Failed to load Simple Cross Over config",
  );
}

export async function updateSimpleCrossoverConfig(
  updates: Partial<SimpleCrossoverConfig>,
): Promise<SimpleCrossoverConfig> {
  return apiJson<SimpleCrossoverConfig>(
    "/api/simple-crossover/config",
    { method: "PUT", body: JSON.stringify(updates) },
    "Failed to update Simple Cross Over config",
  );
}

export async function getSimpleCrossoverData(side: SimpleCrossoverSide): Promise<SimpleCrossoverData> {
  return apiJson<SimpleCrossoverData>(
    `/api/simple-crossover/data?side=${side}`,
    undefined,
    "Failed to load Simple Cross Over data",
  );
}

export async function getSimpleCrossoverTrades(): Promise<{ trades: SimpleCrossoverTrade[] }> {
  return apiJson<{ trades: SimpleCrossoverTrade[] }>(
    "/api/simple-crossover/trades",
    undefined,
    "Failed to load Simple Cross Over trades",
  );
}

export async function updateSimpleCrossoverTradeComment(tradeId: number, comment: string): Promise<SimpleCrossoverTrade> {
  return apiJson<SimpleCrossoverTrade>(
    `/api/simple-crossover/trades/${tradeId}/comment`,
    { method: "PUT", body: JSON.stringify({ comment }) },
    "Failed to save comment",
  );
}

export async function askAssistant(question: string, history: ChatMessage[]): Promise<{ answer: string }> {
  return apiJson<{ answer: string }>(
    "/api/assistant/ask",
    { method: "POST", body: JSON.stringify({ question, history }) },
    "Failed to reach the assistant",
  );
}

// The first Equity load of the day is cold: /portfolio fans out per holding
// (holdings -> quotes -> ~25 Screener scrapes + ~25 Dhan historical calls),
// which measured ~90s locally. 30000ms (the rest of this app's implicit
// browser default) aborted those first loads; 100000ms comfortably covers a
// cold fan-out while still failing fast if the backend is actually down.
const EQUITY_FETCH_TIMEOUT_MS = 100000;

async function fetchEquity(url: URL, label: string, init: RequestInit = {}): Promise<Response> {
  const token = getAuthToken();
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), EQUITY_FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      cache: "no-store",
      ...init,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init.headers ?? {}),
      },
    });
    if (response.status === 401) clearAuthToken();
    return response;
  } catch (exc) {
    if (exc instanceof DOMException && exc.name === "AbortError") {
      throw new Error(`Timed out loading ${label} from ${API_BASE}. The page will keep working with the data that arrived.`);
    }
    if (exc instanceof TypeError) {
      throw new Error(`Failed to reach backend for ${label} at ${API_BASE}.`);
    }
    throw exc;
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function getEquityPortfolio(refresh = false): Promise<EquityPortfolioPayload> {
  const url = new URL("/api/equity/portfolio", API_BASE);
  if (refresh) url.searchParams.set("refresh", "true");
  const response = await fetchEquity(url, "equity portfolio");
  if (!response.ok) {
    throw new Error(`Failed to load equity portfolio: ${response.status}`);
  }
  return response.json();
}

export async function getEquityTransactions(options: {
  fromDate?: string;
  toDate?: string;
  refresh?: boolean;
} = {}): Promise<EquityTransactionsPayload> {
  const url = new URL("/api/equity/transactions", API_BASE);
  if (options.fromDate) url.searchParams.set("fromDate", options.fromDate);
  if (options.toDate) url.searchParams.set("toDate", options.toDate);
  if (options.refresh) url.searchParams.set("refresh", "true");
  const response = await fetchEquity(url, "equity transactions");
  if (!response.ok) {
    throw new Error(`Failed to load equity transactions: ${response.status}`);
  }
  return response.json();
}

export async function getEquityNews(refresh = false): Promise<EquityNewsPayload> {
  const url = new URL("/api/equity/news", API_BASE);
  if (refresh) url.searchParams.set("refresh", "true");
  const response = await fetchEquity(url, "equity news");
  if (!response.ok) {
    throw new Error(`Failed to load equity news: ${response.status}`);
  }
  return response.json();
}

export async function refreshEquity(payload: {
  scope: "portfolio" | "transactions" | "news" | "all";
  fromDate?: string;
  toDate?: string;
}): Promise<Record<string, unknown>> {
  const response = await fetchEquity(new URL("/api/equity/refresh", API_BASE), "equity refresh", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`Failed to refresh equity data: ${response.status}`);
  }
  return response.json();
}

export async function getEquityOptionsReport(): Promise<EquityOptionsReportPayload> {
  return apiJson<EquityOptionsReportPayload>(
    "/api/equity/options-report",
    undefined,
    "Failed to load options report",
  );
}

export async function getLowestPriceOverrides(): Promise<Record<string, number>> {
  return apiJson<Record<string, number>>(
    "/api/equity/lowest-price-overrides",
    undefined,
    "Failed to load lowest-price overrides",
  );
}

export async function setLowestPriceOverride(securityId: string, price: number | null): Promise<{ securityId: string; price: number | null }> {
  return apiJson<{ securityId: string; price: number | null }>(
    `/api/equity/lowest-price-overrides/${encodeURIComponent(securityId)}`,
    { method: "PUT", body: JSON.stringify({ price }) },
    "Failed to save lowest-price override",
  );
}

export async function getVarahaLatest(): Promise<VarahaLatestPayload> {
  return apiJson<VarahaLatestPayload>("/api/varaha/latest", undefined, "Failed to load Varaha recommendation");
}

export async function runVaraha(): Promise<VarahaLatestPayload> {
  return apiJson<VarahaLatestPayload>("/api/varaha/run", { method: "POST" }, "Failed to run Varaha");
}

export async function setVarahaOverride(value: VarahaOverride): Promise<VarahaLatestPayload> {
  return apiJson<VarahaLatestPayload>(
    "/api/varaha/override",
    { method: "PUT", body: JSON.stringify({ value }) },
    "Failed to set direction override",
  );
}

export async function updateVarahaConfig(updates: Partial<Pick<VarahaConfig, "lots" | "maxLossInr">>): Promise<VarahaConfig> {
  return apiJson<VarahaConfig>(
    "/api/varaha/config",
    { method: "PUT", body: JSON.stringify(updates) },
    "Failed to update Varaha settings",
  );
}

export async function getVarahaHistory(): Promise<{ items: VarahaHistoryItem[] }> {
  return apiJson<{ items: VarahaHistoryItem[] }>("/api/varaha/history", undefined, "Failed to load Varaha history");
}

export async function scanFullButterfly(filters: FullButterflyFilters): Promise<FullButterflyScan> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  return apiJson<FullButterflyScan>(`/api/varaha/full-butterfly?${params}`, undefined, "Full Butterfly scan failed");
}

export async function getBtcStrangleConfig(): Promise<BtcStrangleConfig> {
  return apiJson<BtcStrangleConfig>("/api/btc-strangle/config", undefined, "Failed to load BTC Strangle settings");
}

export async function updateBtcStrangleConfig(updates: Partial<BtcStrangleConfig>): Promise<BtcStrangleConfig> {
  return apiJson<BtcStrangleConfig>(
    "/api/btc-strangle/config",
    { method: "PUT", body: JSON.stringify(updates) },
    "Failed to save BTC Strangle settings",
  );
}

export async function getBtcStranglePreview(): Promise<BtcStranglePreview> {
  return apiJson<BtcStranglePreview>("/api/btc-strangle/preview", undefined, "Failed to load tonight's plan");
}

export async function getBtcStrangleTrades(): Promise<{ trades: BtcStrangleTrade[] }> {
  return apiJson<{ trades: BtcStrangleTrade[] }>("/api/btc-strangle/trades", undefined, "Failed to load BTC Strangle trades");
}

export async function enterBtcStrangleNow(): Promise<{ status: string; message?: string; trade?: BtcStrangleTrade }> {
  return apiJson("/api/btc-strangle/enter", { method: "POST" }, "Failed to enter BTC Strangle");
}

export async function closeBtcStrangleLeg(legId: number): Promise<{ status: string; message?: string; price?: number }> {
  return apiJson(`/api/btc-strangle/legs/${legId}/close`, { method: "POST" }, "Failed to close leg");
}

export async function getBtcStrangleChart(tradeId: number, resolution: string): Promise<BtcStrangleChart> {
  return apiJson<BtcStrangleChart>(
    `/api/btc-strangle/trades/${tradeId}/chart?resolution=${resolution}`,
    undefined,
    "Failed to load strategy chart",
  );
}

export async function getBtcSpotChart(resolution: string): Promise<BtcSpotChart> {
  return apiJson<BtcSpotChart>(`/api/btc-strangle/spot-chart?resolution=${resolution}`, undefined, "Failed to load BTC spot chart");
}

export async function getBatmanConfig(mode: BatmanMode): Promise<BatmanConfig> {
  return apiJson<BatmanConfig>(`/api/batman/${mode}/config`, undefined, "Failed to load Batman settings");
}

export async function updateBatmanConfig(mode: BatmanMode, updates: Record<string, unknown>): Promise<BatmanConfig> {
  return apiJson<BatmanConfig>(`/api/batman/${mode}/config`, { method: "PUT", body: JSON.stringify(updates) }, "Failed to save Batman settings");
}

export async function getBatmanPreview(mode: BatmanMode): Promise<BatmanPreview> {
  return apiJson<BatmanPreview>(`/api/batman/${mode}/preview`, undefined, "Failed to load Batman plan");
}

export async function enterBatmanNow(mode: BatmanMode): Promise<{ status: string; message?: string; trade?: BatmanTrade }> {
  return apiJson(`/api/batman/${mode}/enter`, { method: "POST" }, "Batman entry failed");
}

export async function getBatmanTrades(): Promise<{ trades: BatmanTrade[] }> {
  return apiJson<{ trades: BatmanTrade[] }>("/api/batman/trades", undefined, "Failed to load Batman trades");
}

export async function getBatmanTrade(id: number): Promise<BatmanTrade> {
  return apiJson<BatmanTrade>(`/api/batman/trades/${id}`, undefined, "Failed to load Batman trade");
}

export async function closeBatmanTrade(id: number): Promise<{ status: string; message?: string }> {
  return apiJson(`/api/batman/trades/${id}/close`, { method: "POST" }, "Failed to close Batman trade");
}

export async function analyzeBatman(params: Record<string, string | number | null | undefined>): Promise<BatmanAnalysis> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    query.set(key, String(value));
  }
  return apiJson<BatmanAnalysis>(`/api/batman/analyze?${query}`, undefined, "Batman analysis failed");
}

export async function getTurtleState(): Promise<TurtleState> {
  return apiJson<TurtleState>("/api/define-turtle/state", undefined, "Failed to load Define Turtle");
}

export async function getTurtleTrades(): Promise<{ trades: TurtleTrade[] }> {
  return apiJson<{ trades: TurtleTrade[] }>("/api/define-turtle/trades", undefined, "Failed to load Define Turtle trades");
}

export async function updateTurtleConfig(updates: Partial<TurtleConfig>): Promise<TurtleConfig> {
  return apiJson<TurtleConfig>("/api/define-turtle/config", { method: "PUT", body: JSON.stringify(updates) }, "Failed to save settings");
}

export async function enterTurtleNow(): Promise<{ status: string; message?: string; trade?: TurtleTrade }> {
  return apiJson("/api/define-turtle/enter", { method: "POST" }, "Entry failed");
}

export async function closeTurtleTrade(id: number): Promise<{ status: string; message?: string }> {
  return apiJson(`/api/define-turtle/trades/${id}/close`, { method: "POST" }, "Close failed");
}

export async function getTurtleAlarms(): Promise<{ alarms: TurtleAlarm[] }> {
  return apiJson<{ alarms: TurtleAlarm[] }>("/api/define-turtle/alarms", undefined, "Failed to load alarms");
}

export async function acknowledgeTurtleAlarm(id: number): Promise<{ status: string }> {
  return apiJson(`/api/define-turtle/alarms/${id}/ack`, { method: "POST" }, "Failed to acknowledge alarm");
}

export async function getMantraConfig(mode: MantraMode): Promise<MantraConfig> {
  return apiJson<MantraConfig>(`/api/mantra/${mode}/config`, undefined, "Failed to load Mantra settings");
}

export async function updateMantraConfig(mode: MantraMode, updates: Record<string, unknown>): Promise<MantraConfig> {
  return apiJson<MantraConfig>(`/api/mantra/${mode}/config`, { method: "PUT", body: JSON.stringify(updates) }, "Failed to save Mantra settings");
}

export async function getMantraPlan(mode: MantraMode): Promise<MantraPlan> {
  return apiJson<MantraPlan>(`/api/mantra/${mode}/plan`, undefined, "Failed to load Mantra plan");
}

export async function enterMantraNow(mode: MantraMode): Promise<{ status: string; message?: string; tradeId?: number }> {
  return apiJson(`/api/mantra/${mode}/enter`, { method: "POST" }, "Mantra entry failed");
}

export async function getMantraTrades(): Promise<{ trades: MantraTrade[]; alarms: MantraAlarm[] }> {
  return apiJson<{ trades: MantraTrade[]; alarms: MantraAlarm[] }>("/api/mantra/trades", undefined, "Failed to load Mantra trades");
}

export async function getMantraTrade(id: number): Promise<MantraTrade> {
  return apiJson<MantraTrade>(`/api/mantra/trades/${id}`, undefined, "Failed to load Mantra trade");
}

export async function closeMantraTrade(id: number): Promise<{ status: string; message?: string }> {
  return apiJson(`/api/mantra/trades/${id}/close`, { method: "POST" }, "Failed to close Mantra trade");
}

export async function getMantraAlarms(): Promise<{ alarms: MantraAlarm[] }> {
  return apiJson<{ alarms: MantraAlarm[] }>("/api/mantra/alarms", undefined, "Failed to load Mantra alarms");
}

export async function acknowledgeMantraAlarm(id: number): Promise<{ status: string }> {
  return apiJson(`/api/mantra/alarms/${id}/ack`, { method: "POST" }, "Failed to acknowledge alarm");
}

export async function getMeltingState(): Promise<MeltingState> {
  return apiJson<MeltingState>("/api/melting/state", undefined, "Failed to load Melting Straddles");
}

export async function updateMeltingConfig(updates: Record<string, unknown>): Promise<MeltingConfig> {
  return apiJson<MeltingConfig>("/api/melting/config", { method: "PUT", body: JSON.stringify(updates) }, "Failed to save Melting Straddles settings");
}

export async function getMeltingTrades(): Promise<{ trades: MeltingTrade[] }> {
  return apiJson<{ trades: MeltingTrade[] }>("/api/melting/trades", undefined, "Failed to load Melting Straddles trades");
}

export async function getMeltingTrade(id: number): Promise<MeltingTrade> {
  return apiJson<MeltingTrade>(`/api/melting/trades/${id}`, undefined, "Failed to load the trade");
}

export async function closeMeltingTrade(id: number): Promise<{ status: string; message?: string }> {
  return apiJson(`/api/melting/trades/${id}/close`, { method: "POST" }, "Failed to close the straddle");
}

export async function squareOffMelting(): Promise<{ status: string; closed: number }> {
  return apiJson("/api/melting/square-off", { method: "POST" }, "Square-off failed");
}

export async function enterMeltingNow(tag: MeltingTag): Promise<{ status: string; message?: string; tradeId?: number }> {
  return apiJson(`/api/melting/enter/${tag}`, { method: "POST" }, "Entry failed");
}

export async function getMeltingDays(): Promise<{ days: MeltingDaySummary[] }> {
  return apiJson<{ days: MeltingDaySummary[] }>("/api/melting/days", undefined, "Failed to load daily P&L");
}

export async function getNiftyStranglePlan(): Promise<NiftyStranglePlan> {
  return apiJson<NiftyStranglePlan>("/api/nifty-strangle/plan", undefined, "Failed to load the NIFTY Strangle plan");
}

export async function getNiftyStrangleConfig(): Promise<NiftyStrangleConfig> {
  return apiJson<NiftyStrangleConfig>("/api/nifty-strangle/config", undefined, "Failed to load NIFTY Strangle settings");
}

export async function updateNiftyStrangleConfig(updates: Partial<NiftyStrangleConfig>): Promise<NiftyStrangleConfig> {
  return apiJson<NiftyStrangleConfig>("/api/nifty-strangle/config", { method: "PUT", body: JSON.stringify(updates) }, "Failed to save NIFTY Strangle settings");
}

export async function enterNiftyStrangleNow(): Promise<{ status: string; message?: string; tradeId?: number }> {
  return apiJson("/api/nifty-strangle/enter", { method: "POST" }, "NIFTY Strangle entry failed");
}

export async function getNiftyStrangleTrades(): Promise<{ trades: NiftyStrangleTrade[] }> {
  return apiJson<{ trades: NiftyStrangleTrade[] }>("/api/nifty-strangle/trades", undefined, "Failed to load NIFTY Strangle trades");
}

export async function closeNiftyStrangleLeg(legId: number): Promise<{ status: string; message?: string }> {
  return apiJson(`/api/nifty-strangle/legs/${legId}/close`, { method: "POST" }, "Failed to close the leg");
}

export async function getNiftyStrangleSpotChart(): Promise<{ candles: { time: number; close: number }[]; error?: string }> {
  return apiJson("/api/nifty-strangle/spot-chart", undefined, "Failed to load the NIFTY chart");
}

export async function getDishaState(): Promise<DishaState> {
  return apiJson<DishaState>("/api/disha/state", undefined, "Failed to load Disha");
}

export async function getCalmState(): Promise<CalmState> {
  return apiJson<CalmState>("/api/calm-strangle/state", undefined, "Failed to load Calm Strangle");
}

export async function updateCalmConfig(updates: Partial<CalmConfig>): Promise<CalmConfig> {
  return apiJson<CalmConfig>("/api/calm-strangle/config", { method: "PUT", body: JSON.stringify(updates) }, "Failed to save Calm Strangle settings");
}

export async function getCalmTrades(): Promise<{ trades: CalmTrade[] }> {
  return apiJson<{ trades: CalmTrade[] }>("/api/calm-strangle/trades", undefined, "Failed to load Calm Strangle trades");
}

export async function enterCalmNow(): Promise<{ status: string; message?: string; tradeId?: number }> {
  return apiJson("/api/calm-strangle/enter", { method: "POST" }, "Calm Strangle entry failed");
}

export async function closeCalmTrade(id: number): Promise<{ status: string; message?: string }> {
  return apiJson(`/api/calm-strangle/trades/${id}/close`, { method: "POST" }, "Failed to close the strangle");
}

export async function getCalmTrade(id: number): Promise<CalmTradeDetail> {
  return apiJson<CalmTradeDetail>(`/api/calm-strangle/trades/${id}`, undefined, "Failed to load the trade");
}

export async function getBtcCalmState(): Promise<BtcCalmState> {
  return apiJson<BtcCalmState>("/api/btc-calm/state", undefined, "Failed to load BTC Calm Strangle");
}

export async function updateBtcCalmConfig(updates: Partial<BtcCalmConfig>): Promise<BtcCalmConfig> {
  return apiJson<BtcCalmConfig>("/api/btc-calm/config", { method: "PUT", body: JSON.stringify(updates) }, "Failed to save BTC Calm settings");
}

export async function getBtcCalmTrades(): Promise<{ trades: BtcCalmTrade[] }> {
  return apiJson<{ trades: BtcCalmTrade[] }>("/api/btc-calm/trades", undefined, "Failed to load BTC Calm trades");
}

export async function getBtcCalmTrade(id: number): Promise<BtcCalmTradeDetail> {
  return apiJson<BtcCalmTradeDetail>(`/api/btc-calm/trades/${id}`, undefined, "Failed to load the trade");
}

export async function enterBtcCalmNow(book = "standard"): Promise<{ status: string; message?: string; tradeId?: number }> {
  return apiJson(`/api/btc-calm/enter?book=${book}`, { method: "POST" }, "BTC Calm entry failed");
}

export async function closeBtcCalmTrade(id: number): Promise<{ status: string; message?: string }> {
  return apiJson(`/api/btc-calm/trades/${id}/close`, { method: "POST" }, "Failed to close the strangle");
}

export async function getVarahaPaperState(): Promise<VarahaPaperState> {
  return apiJson<VarahaPaperState>("/api/varaha/paper/state", undefined, "Failed to load Varaha paper trading");
}

export async function updateVarahaPaperConfig(updates: Partial<VarahaPaperConfig>): Promise<VarahaPaperConfig> {
  return apiJson<VarahaPaperConfig>("/api/varaha/paper/config", { method: "PUT", body: JSON.stringify(updates) }, "Failed to save Varaha paper settings");
}

export async function getVarahaPaperTrades(): Promise<{ trades: VarahaPaperTrade[] }> {
  return apiJson<{ trades: VarahaPaperTrade[] }>("/api/varaha/paper/trades", undefined, "Failed to load Varaha paper trades");
}

export async function getVarahaPaperTrade(id: number): Promise<VarahaPaperTrade> {
  return apiJson<VarahaPaperTrade>(`/api/varaha/paper/trades/${id}`, undefined, "Failed to load the trade");
}

export async function enterVarahaPaperNow(): Promise<{ status: string; message?: string; tradeId?: number }> {
  return apiJson("/api/varaha/paper/enter", { method: "POST" }, "Varaha paper entry failed");
}

export async function closeVarahaPaperTrade(id: number): Promise<{ status: string; message?: string }> {
  return apiJson(`/api/varaha/paper/trades/${id}/close`, { method: "POST" }, "Failed to close the trade");
}

export async function getVarahaPaperSpotChart(days: number): Promise<{ candles: { time: number; close: number }[]; error?: string }> {
  return apiJson(`/api/varaha/paper/spot-chart?days=${days}`, undefined, "Failed to load the NIFTY chart");
}

export async function getAlerts(): Promise<AlertsPayload> {
  return apiJson<AlertsPayload>("/api/alerts", undefined, "Failed to load alerts");
}

export async function createAlert(alert: NewAlert): Promise<PortalAlert> {
  return apiJson<PortalAlert>("/api/alerts", { method: "POST", body: JSON.stringify(alert) }, "Failed to create alert");
}

export async function alertAction(id: number, action: "acknowledge" | "dismiss" | "rearm"): Promise<PortalAlert> {
  return apiJson<PortalAlert>(`/api/alerts/${id}/${action}`, { method: "POST" }, "Alert update failed");
}

export async function testTelegram(): Promise<TelegramStatus & { sent: boolean }> {
  return apiJson(`/api/alerts/telegram-test`, { method: "POST" }, "Telegram test failed");
}

export async function getSwingState(): Promise<SwingState> {
  return apiJson<SwingState>("/api/equity-swing/state", undefined, "Failed to load Equity-Swing");
}

export async function updateSwingConfig(updates: Partial<SwingConfig>): Promise<SwingConfig> {
  return apiJson<SwingConfig>("/api/equity-swing/config", { method: "PUT", body: JSON.stringify(updates) }, "Failed to save settings");
}

export async function syncSwingData(): Promise<{ series: number; failed: number }> {
  return apiJson("/api/equity-swing/sync", { method: "POST" }, "Data sync failed");
}

export async function rebalanceSwingNow(): Promise<unknown> {
  return apiJson("/api/equity-swing/rebalance", { method: "POST" }, "Ranking failed");
}

export async function getSwingRetros(): Promise<{ running: number | null; retros: SwingRetro[] }> {
  return apiJson("/api/equity-swing/retros", undefined, "Failed to load retrospectives");
}

export async function startSwingRetro(): Promise<{ status: string }> {
  return apiJson("/api/equity-swing/retros", { method: "POST" }, "Failed to start the retrospective");
}

export async function applySwingRetro(id: number, label: string): Promise<SwingConfig> {
  return apiJson<SwingConfig>(`/api/equity-swing/retros/${id}/apply`, { method: "POST", body: JSON.stringify({ label }) }, "Failed to apply");
}
