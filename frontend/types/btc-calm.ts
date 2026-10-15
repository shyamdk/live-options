export interface BtcCalmConfig {
  enabled: boolean;
  mode: "paper" | "live";
  contracts: number;
  calmPercent: number;
  calmWindow: number;
  strikeMultiple: number;
  stopMultiple: number;
  backstopPercent: number;
  minCredit: number;
  windowStart: string;
  windowEnd: string;
  exitBeforeMinutes: number;
  maxEntries: number;
  maxStops: number;
  earlyExit: boolean;
  books: Record<string, { label: string; enabled: boolean; exitBeforeMinutes: number }>;
  btcPerLeg: number;
  liveOrdersAllowed: boolean;
}

export interface BtcCalmLegPreview {
  symbol: string;
  strike: number;
  bid: number | null;
  ask: number | null;
  mark: number | null;
  iv: number | null;
  delta: number | null;
  distancePercent: number;
}

export interface BtcCalmSnapshot {
  error?: string;
  time?: number;
  expiry?: string;
  settlement?: number;
  exitBy?: number;
  exitByBooks?: Record<string, number>;
  spot?: number;
  atmStrike?: number;
  straddle?: number;
  calmRange?: number | null;
  calmThreshold?: number;
  calm?: boolean;
  legs?: Partial<Record<"CE" | "PE", BtcCalmLegPreview>>;
  credit?: number | null;
  stopBand?: number;
}

export interface BtcCalmTrade {
  id: number;
  book: string;
  expiry: string;
  settlement: number;
  mode: "paper" | "live";
  trigger: string;
  entryTime: number;
  entrySpot: number;
  straddle: number;
  calmRange: number | null;
  atmStrike: number;
  ceStrike: number;
  peStrike: number;
  ceSymbol: string;
  peSymbol: string;
  contracts: number;
  btcPerLeg: number;
  entryCe: number;
  entryPe: number;
  credit: number;
  stopLow: number;
  stopHigh: number;
  backstop: number;
  earlyTarget: number | null;
  exitBy: number;
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
  entryQuotes: Record<string, { bid?: number | null; ask?: number | null; mark?: number | null; iv?: number | null }>;
  exitQuotes: Record<string, { bid?: number | null; ask?: number | null; mark?: number | null }>;
  orderIds: Record<string, string | null>;
  current: number;
  points: number;
  grossPnl: number;
  fees: number;
  netPnl: number;
  premiumCollected: number;
  minutesHeld: number;
}

export interface BtcCalmScenario {
  kind: "move_low" | "move_high" | "backstop" | "early" | "time";
  label: string;
  distance: number;
  estNet: number;
}

export interface BtcCalmTradeDetail extends BtcCalmTrade {
  payoff: { price: number; expiry: number; today: number }[];
  breakevens: number[];
  ivs: Record<string, number>;
  scenarios: BtcCalmScenario[];
  marks: { time: number; combined: number; spot: number | null }[];
}

export interface BtcCalmState {
  config: BtcCalmConfig;
  now: number;
  inWindow: boolean;
  mode: "paper" | "live";
  snapshot: BtcCalmSnapshot;
  spot: { time: number; close: number }[];
  books: Record<string, BtcCalmBook>;
  events: { time: number; kind: string; text: string }[];
}

export interface BtcCalmBook {
  label: string;
  enabled: boolean;
  exitBeforeMinutes: number;
  exitBy: number | null;
  openTrade: BtcCalmTradeDetail | null;
  sessionTrades: BtcCalmTrade[];
  entriesThisSession: number;
  stopsThisSession: number;
}
