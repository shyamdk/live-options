export type MarketIndex = {
  name: string;
  lastPrice: number | null;
  change: number | null;
  percentChange: number | null;
};

export type MarketIndicesPayload = {
  source: string;
  stale?: boolean | null;
  warning?: string | null;
  updatedAt?: string | number | null;
  indices: MarketIndex[];
};

export type DhanSession = {
  hasAccessToken: boolean;
  hasClientId: boolean;
  clientId?: string | null;
  liveOrderEnabled: boolean;
};

export type AuthStatus = {
  enabled: boolean;
  configured: boolean;
  username: string;
  sessionHours: number;
};

export type AuthSession = AuthStatus & {
  authenticated: boolean;
  user?: string | null;
};

export type RiskStatus = {
  kind: "none" | "stopLoss" | "target" | string;
  label: string;
  level?: number | null;
};

export type TradeLevels = {
  tradeId?: string | null;
  symbol?: string | null;
  expiry?: string | null;
  strikePrice?: number | null;
  optionSide?: string | null;
  stopLoss?: number | null;
  target?: number | null;
  notes?: string | null;
  updatedAt?: string | null;
};

export type LiveTrade = {
  id: string;
  assetClass: "EQUITY" | "OPTION" | string;
  symbol: string;
  tradingSymbol: string;
  securityId?: string | null;
  exchangeSegment?: string | null;
  productType?: string | null;
  instrument?: string | null;
  expiry?: string | null;
  strikePrice?: number | null;
  optionSide?: "CE" | "PE" | string | null;
  side: "BUY" | "SELL" | string;
  qty: number;
  absQty: number;
  avgPrice?: number | null;
  ltp?: number | null;
  ltpStale?: boolean | null;
  openPnl: number;
  realizedPnl: number;
  dayPnl: number;
  estimatedCharges?: number | null;
  estimatedNetPnl?: number | null;
  percentChange?: number | null;
  maxProfit?: number | null;
  profitRemaining?: number | null;
  profitRemainingPercent?: number | null;
  spotPrice?: number | null;
  spotDistancePoints?: number | null;
  spotDistancePercent?: number | null;
  spotDistanceSignedPoints?: number | null;
  spotDistanceAlert?: boolean | null;
  charges?: Record<string, unknown> | null;
  levels?: TradeLevels;
  riskStatus?: RiskStatus;
};

export type LiveTradeSummary = {
  totalPositions: number;
  equityCount: number;
  optionsBuyCount: number;
  optionsSellCount: number;
  openPnl: number;
  realizedPnl: number;
  dayPnl: number;
  estimatedCharges: number;
  estimatedNetPnl: number;
  configuredLevels: number;
  stopLossHits: number;
  targetHits: number;
};

export type LiveTradeSnapshot = {
  source: string;
  warning?: string | null;
  updatedAt: string;
  summary: LiveTradeSummary;
  groups: {
    equity: LiveTrade[];
    optionsBuy: LiveTrade[];
    optionsSell: LiveTrade[];
  };
};

export type Journal = {
  tradeDate: string;
  strategyDetails: string;
  lessonsLearnt: string;
  createdAt: string;
  updatedAt: string;
};

export type TodayJournalPayload = {
  tradeDate: string;
  journal: Journal;
  summary: LiveTradeSummary;
  snapshot: LiveTradeSnapshot;
};
