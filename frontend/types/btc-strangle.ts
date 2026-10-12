export type BtcStrangleMode = "paper" | "live";

export interface BtcStrangleConfig {
  enabled: boolean;
  mode: BtcStrangleMode;
  multiplier: number;
  stopLossPercent: number;
  contracts: number;
  entryTime: string;
  entryWindowEnd: string;
  expiryOffset: number;
  expiryExitTime: string;
  buybackThreshold: number;
  minAvailableBalance: number;
  useFarthestStrike: boolean;
  missingStrike: BtcMissingStrike;
  liveOrdersAllowed: boolean;
  deltaCredentials: boolean;
}

export type BtcMissingStrike = "skip" | "farthest" | "one_side";
export type BtcStrangleVariant = "strangle" | "farthest" | "one_side";

export interface BtcOptionQuote {
  symbol: string;
  productId: number;
  strike: number;
  bid: number | null;
  ask: number | null;
  mark: number | null;
  iv: number | null;
  delta: number | null;
  oi: number | null;
}

export interface BtcStranglePreview {
  error?: string;
  config: BtcStrangleConfig;
  entryAt?: number;
  expiryCode?: string;
  settlement?: number;
  hoursToSettlement?: number;
  spot?: number;
  atmStrike?: number;
  atmCall?: number;
  atmPut?: number;
  straddle?: number;
  multiplier?: number;
  distance?: number;
  callTarget?: number;
  putTarget?: number;
  fallback?: boolean;
  variant?: BtcStrangleVariant;
  missingSide?: "CE" | "PE" | null;
  missingTarget?: number | null;
  missingFarthestListed?: number | null;
  legs?: Partial<Record<"CE" | "PE", BtcOptionQuote>>;
  preview?: Partial<Record<"CE" | "PE", { entryPrice: number; slPrice: number | null; distancePercent: number }>>;
  contracts?: number;
  estimatedCredit?: number;
}

export interface BtcStrangleLeg {
  id: number;
  tradeId: number;
  optionType: "CE" | "PE";
  symbol: string;
  productId: number;
  strike: number;
  requestedContracts: number;
  contracts: number;
  entryPrice: number | null;
  slPrice: number | null;
  status: "PENDING" | "OPEN" | "CLOSED" | "NOT_FILLED";
  exitPrice: number | null;
  exitTime: number | null;
  exitReason: string | null;
  entryOrderId: string | null;
  slOrderId: string | null;
  exitOrderId: string | null;
  entryFee: number;
  exitFee: number;
  lastMark: number | null;
  lastBid: number | null;
  lastAsk: number | null;
  lastUpdate: number | null;
  error: string | null;
  pnl?: number;
  pnlPercent?: number;
}

export interface BtcStrangleTrade {
  id: number;
  mode: BtcStrangleMode;
  sessionDate: string;
  expiryCode: string;
  settlementTime: number;
  entryTime: number;
  spot: number;
  atmStrike: number | null;
  straddle: number;
  multiplier: number;
  distance: number;
  stopLossPercent: number;
  contracts: number;
  status: "OPEN" | "CLOSED" | "FAILED";
  trigger: string;
  notes: string | null;
  variant?: BtcStrangleVariant;
  closedAt: number | null;
  legs: BtcStrangleLeg[];
  credit: number;
  grossPnl: number;
  fees: number;
  netPnl: number;
}

export interface BtcStrangleChart {
  error?: string;
  tradeId: number;
  points: { time: number; price: number; vwap: number }[];
  entryCredit: number;
}

export interface BtcSpotChart {
  symbol: string;
  candles: { time: number; open: number; high: number; low: number; close: number }[];
  strikes: { strike: number; label: string; optionType: "CE" | "PE" }[];
}
