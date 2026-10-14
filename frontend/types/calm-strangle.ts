export interface CalmConfig {
  enabled: boolean;
  mode: "paper" | "live";
  lots: number;
  calmPercent: number;
  calmWindow: number;
  strikeMultiple: number;
  stopMultiple: number;
  backstopPercent: number;
  minCredit: number;
  entryStart: string;
  lastEntry: string;
  exitTime: string;
  maxEntries: number;
  maxStops: number;
  skipExpiryDay: boolean;
  earlyExit: boolean;
  stopAfterEarlyExit: boolean;
  europeGuard: boolean;
  europeGuardTime: string;
  lotSize: number;
  quantity: number;
  liveOrdersAllowed: boolean;
}

export interface CalmLegPreview {
  strike: number;
  securityId: string;
  ltp: number | null;
  bid: number | null;
  ask: number | null;
  delta: number | null;
  distancePercent: number;
}

export interface CalmSnapshot {
  error?: string;
  time?: number;
  expiry?: string;
  dte?: number;
  spot?: number;
  atmStrike?: number;
  straddle?: number;
  calmRange?: number | null;
  calmThreshold?: number;
  calm?: boolean;
  windowMinutes?: number;
  legs?: Partial<Record<"CE" | "PE", CalmLegPreview>>;
  credit?: number | null;
  stopBand?: number;
}

export interface CalmQuote {
  ltp?: number | null;
  bid?: number | null;
  ask?: number | null;
}

export interface CalmTrade {
  id: number;
  day: string;
  expiry: string;
  dte: number;
  mode: "paper" | "live";
  trigger: string;
  entryTime: number;
  entrySpot: number;
  straddle: number;
  calmRange: number | null;
  atmStrike: number;
  ceStrike: number;
  peStrike: number;
  lots: number;
  lotSize: number;
  entryCe: number;
  entryPe: number;
  credit: number;
  stopLow: number;
  stopHigh: number;
  backstop: number;
  status: "OPEN" | "CLOSED";
  exitTime: number | null;
  exitReason: string | null;
  exitCe: number | null;
  exitPe: number | null;
  exitSpot: number | null;
  lastCe: number | null;
  lastPe: number | null;
  lastSpot: number | null;
  lastUpdate: number | null;
  best: number | null;
  worst: number | null;
  entryQuotes: Record<string, CalmQuote>;
  exitQuotes: Record<string, CalmQuote>;
  orderIds: Record<string, string | null>;
  notes: string | null;
  earlyTarget: number | null;
  current: number;
  points: number;
  grossPnl: number;
  charges: number;
  netPnl: number;
  premiumCollected: number;
  minutesHeld: number;
}

export interface CalmState {
  config: CalmConfig;
  now: number;
  marketOpen: boolean;
  mode: "paper" | "live";
  snapshot: CalmSnapshot | null;
  spot: { time: number; close: number }[];
  todayTrades: CalmTrade[];
  openTrade: CalmTradeDetail | null;
  entriesToday: number;
  stopsToday: number;
  events: { time: number; kind: string; text: string; tradeId: number | null }[];
}

export interface CalmScenario {
  kind: "move_low" | "move_high" | "backstop" | "early" | "guard" | "time";
  label: string;
  level: number | null;
  distance: number;
  estNet: number;
}

export interface CalmAnalytics {
  payoff: { price: number; expiry: number; today: number }[];
  breakevens: number[];
  ivs: Record<string, number>;
  scenarios: CalmScenario[];
  marks: { time: number; combined: number; spot: number | null }[];
  quantity: number;
}

export type CalmTradeDetail = CalmTrade & CalmAnalytics;
