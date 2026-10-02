export type PeCeUnderlying = "NIFTY" | "BANKNIFTY" | "SENSEX";
export type PeCeSide = "CE" | "PE";
export type PeCeMode = "paper" | "shadow" | "live";

export interface PeCeCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface PeCeCandlesData {
  underlying?: PeCeUnderlying;
  side?: PeCeSide;
  error?: string;
  strike?: number;
  expiry?: string;
  dte?: number;
  expiryReason?: string;
  bid?: number | null;
  ask?: number | null;
  candles: PeCeCandle[];
  emaFastValues: (number | null)[];
  emaSlowValues: (number | null)[];
  rsiValues: (number | null)[];
  adxValues: (number | null)[];
  trades: PeCeTrade[];
}

export interface PeCeTrade {
  id: number;
  underlying: PeCeUnderlying;
  side: PeCeSide;
  strike: number;
  expiry: string;
  dte: number | null;
  lots: number;
  lotSize: number;
  entryTime: number;
  entryPremium: number;
  stopLossPercent: number;
  targetPercent: number;
  peakPremium: number | null;
  trailStopPremium: number | null;
  status: "open" | "closed";
  exitTime: number | null;
  exitPremium: number | null;
  exitReason: string | null;
  realizedPnl: number | null;
  charges: number | null;
  mode: PeCeMode;
  entryOrderId: string | null;
  exitOrderId: string | null;
  note: string | null;
}

export type PeCeSignalState = "NO_SIGNAL" | "CANDIDATE" | "WAITING_FOR_EXPANSION" | "READY" | "BLOCKED" | "IN_POSITION";

export interface PeCeSignalLogEntry {
  time: number;
  underlying: PeCeUnderlying;
  side: PeCeSide;
  state: PeCeSignalState;
  blockedReason: string | null;
  emaFast: number | null;
  emaSlow: number | null;
  premium: number | null;
  premiumExpansionPercent: number | null;
  spreadPercent: number | null;
  rsi: number | null;
  adx: number | null;
}

export interface PeCeBacktestTrade {
  strike: number;
  entryTime: number;
  entryPremium: number;
  exitTime: number;
  exitPremium: number;
  exitReason: string;
  grossPnl: number;
  charges: number;
  netPnl: number;
}

export interface PeCeBacktestMetrics {
  tradeCount: number;
  netPnl: number;
  winRate: number | null;
  profitFactor: number | null;
  expectancy: number | null;
  maxDrawdown: number;
  avgWin: number | null;
  avgLoss: number | null;
  longestLosingStreak: number;
}

export interface PeCeBacktestResult {
  error?: string;
  underlying?: PeCeUnderlying;
  side?: PeCeSide;
  expiry?: string;
  fromDate?: string;
  toDate?: string;
  strikesVisited?: number[];
  trades: PeCeBacktestTrade[];
  metrics?: PeCeBacktestMetrics;
  limitations?: string[];
}

export interface PeCeRuntimeConfig {
  premiumExpansionFilterEnabled: boolean;
  spreadFilterEnabled: boolean;
}

export interface PeCeStatus {
  monitorEnabled: boolean;
  underlyings: PeCeUnderlying[];
  lots: number;
  stopLossPercent: number;
  targetPercent: number;
  trailArmPercent: number;
  trailPercent: number;
  maxCapitalRupees: number;
  maxDailyLossRupees: number;
  maxTradesPerDay: number;
  cooldownMinutes: number;
  positionMode: "total" | "per_side";
  currentMode: PeCeMode;
  liveEnabled: boolean;
  shadowMode: boolean;
  globalLiveOrderEnabled: boolean;
  telegramAlertsEnabled: boolean;
  openPositions: number;
  todayRealizedPnl: number;
  trades: PeCeTrade[];
}

export interface PeCeReportMetrics {
  tradeCount: number;
  netPnl: number;
  winRate: number | null;
  profitFactor: number | null;
  expectancy: number | null;
  maxDrawdown: number;
  avgWin: number | null;
  avgLoss: number | null;
  longestLosingStreak: number;
}

export interface PeCeReportResult {
  error?: string;
  mode: PeCeMode;
  fromDate: string;
  toDate: string;
  metrics: PeCeReportMetrics;
  metricsBySide: Record<string, PeCeReportMetrics>;
  metricsByUnderlying: Record<string, PeCeReportMetrics>;
  trades: PeCeTrade[];
}
