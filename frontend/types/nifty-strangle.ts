export interface NiftyStrangleConfig {
  enabled: boolean;
  mode: "paper" | "live";
  multiplier: number;
  stopLossPercent: number;
  lots: number;
  minPremium: number;
  entryTime: string;
  entryWindowEnd: string;
  expiryExitTime: string;
  buybackThreshold: number;
  lotSize: number;
  quantity: number;
  liveOrdersAllowed: boolean;
  book: "plain" | "hedged" | "sensex";
  broker: "dhan" | "kite";
  index?: "NIFTY" | "SENSEX";
  skipEventWeeks: boolean;
  wingDistance: number;
  kite?: KiteStatus;
}

export interface KiteStatus {
  configured: boolean;
  connected: boolean;
  loginUrl: string | null;
  user: string | null;
  loggedInAt: string | null;
  autoLogin?: boolean;
  autoLoginResult?: string | null;
  margins?: { net: number | null; cash: number | null; collateral: number | null; used: number | null };
  error?: string;
}

export interface MarketEvent {
  id: number;
  day: string;
  name: string;
  kind: string;
  source: string;
  note: string | null;
}

export interface NiftyStranglePlanWing {
  strike: number;
  securityId: string;
  ltp: number | null;
  bid: number | null;
  ask: number | null;
  iv: number | null;
  delta: number | null;
  oiLots: number;
  distancePercent: number;
  buyAt?: number;
}

export interface NiftyStranglePlanLeg {
  strike: number;
  formulaStrike: number;
  steppedIn: boolean;
  securityId: string;
  ltp: number | null;
  bid: number | null;
  ask: number | null;
  iv: number | null;
  delta: number | null;
  oiLots: number;
  distancePercent: number;
  target: number;
  sellAt?: number;
  slPrice?: number;
}

export interface NiftyStranglePlan {
  config: NiftyStrangleConfig;
  error?: string;
  entryDate?: string;
  expiry?: string;
  spot?: number;
  atmStrike?: number;
  straddle?: number;
  multiplier?: number;
  distance?: number;
  legs?: Partial<Record<"CE" | "PE", NiftyStranglePlanLeg>>;
  wings?: Partial<Record<"CE" | "PE", NiftyStranglePlanWing>>;
  events?: { day: string; name: string; kind: string }[];
  eventSkip?: boolean;
  wingCost?: number;
  netCredit?: number;
  maxLossPerSide?: number;
  credit?: number;
  sellCharges?: number;
  netIfExpire?: number;
  lossIfBothStopped?: number;
}

export interface NiftyStrangleLeg {
  id: number;
  role: "short" | "wing";
  symbol: string | null;
  optionType: "CE" | "PE";
  strike: number;
  formulaStrike: number | null;
  securityId: string;
  quantity: number;
  entryPrice: number | null;
  entryBid: number | null;
  entryAsk: number | null;
  slPrice: number | null;
  status: "PENDING" | "OPEN" | "CLOSED" | "NOT_FILLED";
  exitPrice: number | null;
  exitTime: number | null;
  exitReason: string | null;
  entryOrderId: string | null;
  exitOrderId: string | null;
  lastLtp: number | null;
  lastBid: number | null;
  lastAsk: number | null;
  lastUpdate: number | null;
  error: string | null;
  charges: number;
  pnl?: number;
}

export interface NiftyStrangleTrade {
  id: number;
  book: "plain" | "hedged" | "sensex";
  broker: string | null;
  mode: "paper" | "live";
  trigger: string;
  entryDate: string;
  expiry: string;
  entryTime: number;
  spot: number;
  atmStrike: number;
  straddle: number;
  multiplier: number;
  distance: number;
  stopLossPercent: number;
  lots: number;
  lotSize: number;
  status: "OPEN" | "CLOSED" | "FAILED" | "SKIPPED";
  notes: string | null;
  closedAt: number | null;
  legs: NiftyStrangleLeg[];
  credit: number;
  grossPnl: number;
  charges: number;
  netPnl: number;
}
