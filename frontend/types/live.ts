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

export type MarketNewsItem = {
  headline: string;
  impact: "high" | "medium";
  link: string | null;
};

export type MarketNewsPayload = {
  items: MarketNewsItem[];
  generatedAt: string | null;
};

export type ConfidenceLevel = "low" | "medium" | "high" | "extreme";

export type PcrOiSnapshot = {
  time: number;
  spot: number | null;
  pcr: number | null;
  ceOi: number;
  peOi: number;
  ceOiChange: number;
  peOiChange: number;
  ceRoc: number | null;
  peRoc: number | null;
  ceZScore: number | null;
  peZScore: number | null;
  ceConfidence: ConfidenceLevel | null;
  peConfidence: ConfidenceLevel | null;
  ceRocBandUpper: number | null;
  ceRocBandLower: number | null;
  peRocBandUpper: number | null;
  peRocBandLower: number | null;
  atmStrike: number | null;
  cePremium: number | null;
  ceIv: number | null;
  ceDelta: number | null;
  ceVega: number | null;
  pePremium: number | null;
  peIv: number | null;
  peDelta: number | null;
  peVega: number | null;
  oiSkew: number | null;
  pcrDelta: number | null;
  signal: "buyCe" | "buyPe" | "neutral" | null;
  signalConfidence: ConfidenceLevel | null;
  deltaVegaAligned: "CE" | "PE" | null;
  oiRegime: "longBuildup" | "shortBuildup" | "longUnwinding" | "shortCovering" | null;
  indiaVix: number | null;
};

export type PcrOiPayload = {
  sessionDate?: string;
  NIFTY: PcrOiSnapshot[];
  SENSEX: PcrOiSnapshot[];
};

export type MarketCandle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
};

export type MarketCandlesResponse = {
  candles: MarketCandle[];
  intervalMinutes: number;
};

export type DhanSession = {
  hasAccessToken: boolean;
  hasClientId: boolean;
  clientId?: string | null;
  liveOrderEnabled: boolean;
  riskOrderMonitorEnabled?: boolean;
  riskOrderExecutionEnabled?: boolean;
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
  signalKind?: "stopLoss" | "target" | string | null;
  label: string;
  level?: number | null;
  orderStatus?: string | null;
  orderAction?: string | null;
  orderId?: string | null;
  orderAt?: string | null;
  retryAt?: string | null;
  message?: string | null;
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
  tag?: string | null;
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
  entrySide?: "BUY" | "SELL" | string | null;
  status?: "OPEN" | "CLOSED" | string;
  qty: number;
  absQty: number;
  closedQty?: number | null;
  buyQty?: number | null;
  sellQty?: number | null;
  buyAvg?: number | null;
  sellAvg?: number | null;
  avgPrice?: number | null;
  entryAvgPrice?: number | null;
  exitAvgPrice?: number | null;
  ltp?: number | null;
  ltpDerived?: boolean | null;
  ltpStale?: boolean | null;
  positionOpenPnl?: number | null;
  pnlSource?: string | null;
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
  closedCount: number;
  equityCount: number;
  optionsCount: number;
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
    closed: LiveTrade[];
    equity: LiveTrade[];
    options: LiveTrade[];
  };
};

export type Journal = {
  tradeDate: string;
  strategyDetails: string;
  howIFelt: string;
  whatHappened: string;
  lessonsLearnt: string;
  comments: string;
  createdAt: string | null;
  updatedAt: string | null;
};

export type DailyTradeSummary = {
  tradeDate: string;
  tradesCount: number;
  dayPnl: number | null;
  netPnl: number | null;
  realizedPnl: number | null;
  charges: number | null;
  updatedAt: string;
};

export type JournalSession = {
  tradeDate: string;
  summary: DailyTradeSummary | null;
  journal: Journal;
};

export type JournalInsights = {
  bullets: string[];
  generatedAt: string | null;
};

export type OiState = "bullish" | "bearish" | "mixed" | "unwinding" | "buildingBoth";
export type TrendState = "bullish" | "neutral" | "bearish";
export type FilterState = "supportive" | "neutral" | "risky";
export type UpgradedSignal = "buyCe" | "buyPe" | "noTrade";
export type UpgradedRegime = "trendingBullish" | "trendingBearish" | "range" | "transition";
export type UpgradedState =
  | "noTrade"
  | "bullishWatch"
  | "buyCe"
  | "holdCe"
  | "bearishWatch"
  | "buyPe"
  | "holdPe"
  | "cooldown";

export type SignalReason = {
  label: string;
  met: boolean;
  value: string | null;
};

export type OiUpgradedPoint = {
  time: number;
  spot: number | null;
  pcr: number | null;
  ceOi: number;
  peOi: number;
  ceOiChange: number;
  peOiChange: number;
  atmStrike: number | null;
  cePremium: number | null;
  ceIv: number | null;
  pePremium: number | null;
  peIv: number | null;
  indiaVix: number | null;
  pcrChange6m: number | null;
  pcrChange12m: number | null;
  pcrState: TrendState;
  ceOiMomentum6m: number | null;
  peOiMomentum6m: number | null;
  oiState: OiState;
  niftyPrice: number | null;
  vwap: number | null;
  priceTrend5m: number | null;
  priceState: TrendState;
  cePremiumRising: boolean;
  pePremiumRising: boolean;
  vixState: FilterState;
  ceIvState: FilterState;
  peIvState: FilterState;
  ceScore: number;
  peScore: number;
  rawSignal: UpgradedSignal;
  regime: UpgradedRegime;
  state: UpgradedState;
  persistence: number;
  exitStreak: number;
  cooldownUntil: number | null;
  signal: UpgradedSignal;
  reasons: SignalReason[];
};

export type OiUpgradedPayload = {
  sessionDate: string;
  NIFTY: OiUpgradedPoint[];
};

export type BacktestSummary = {
  count: number;
  avgPnlPct: number | null;
  winRate: number | null;
  totalPnlPct: number | null;
};

export type BacktestDay = {
  date: string;
  new: BacktestSummary;
  old: BacktestSummary;
};

export type BacktestTrade = {
  date: string;
  side: "buyCe" | "buyPe";
  entryTime: number;
  exitTime: number | null;
  reason: "stop_loss" | "trail" | "eod";
  pnlPct: number;
};

export type BacktestReport = {
  days: BacktestDay[];
  totals: { new: BacktestSummary; old: BacktestSummary };
  newTrades: BacktestTrade[];
  breakdowns: {
    bySide: Record<string, BacktestSummary>;
    byReason: Record<string, BacktestSummary>;
  };
  observations: string[];
};

export type PaperTradeLeg = {
  id: number;
  tradeId: number;
  lotNumber: number;
  qty: number;
  exitTime: number;
  exitPremium: number;
  exitReason: "target1" | "target2" | "trail" | "stop_loss" | "eod";
  pnlPoints: number;
  pnlAmount: number;
};

export type PaperTrade = {
  id: number;
  underlying: "NIFTY" | "SENSEX";
  side: "CE" | "PE";
  signalType: "signalVsPrice" | "priceBreakout";
  strike: number | null;
  expiry: string | null;
  securityId: string | null;
  exchangeSegment: string | null;
  entryTime: number;
  entryPremium: number;
  lots: number;
  lotSize: number;
  stopLossPercent: number;
  target1Percent: number;
  target2Percent: number;
  trailPercent: number;
  stopLossPrice: number;
  target1Price: number;
  target2Price: number;
  phase: "OPEN_ALL" | "LOT1_BOOKED" | "LOT2_BOOKED";
  peakPremium: number | null;
  remainingLots: number;
  status: "open" | "closed";
  realizedPnl: number;
  closedAt: number | null;
  createdAt: string;
  legs: PaperTradeLeg[];
};

export type PaperTradingSettings = {
  stopLossPercent: number;
  target1Percent: number;
  target2Percent: number;
  trailPercent: number;
  niftyLots: number;
  niftyLotSize: number;
  sensexLots: number;
  sensexLotSize: number;
};
