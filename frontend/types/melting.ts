export type MeltingTag = "LOWER" | "ATM" | "HIGHER";

export interface MeltingIndexConfig {
  enabled: boolean;
  tradeDays: string;
  maxDaysToExpiry: number;
  strikeStep: number;
  offset: number;
  stopPoints: number;
  stepPoints: number;
  brakePoints: number;
  lotSize: number;
}

export interface MeltingConfig {
  enabled: boolean;
  mode: "paper" | "live";
  boxPercent: number;
  reversal: number;
  lotsPerStraddle: number;
  maxOpen: number;
  entryStart: string;
  entryEnd: string;
  exitTime: string;
  maxStops: number;
  patterns: string;
  turtleLookback: number;
  anchorLookback: number;
  tallMultiple: number;
  signalMaxAgeMinutes: number;
  NIFTY: MeltingIndexConfig;
  SENSEX: MeltingIndexConfig;
  liveOrdersAllowed: boolean;
  patternList: string[];
}

export interface MeltingDay {
  day: string;
  indexName: "NIFTY" | "SENSEX";
  expiry: string;
  dte: number;
  spotOpen: number;
  atm: number;
  straddles: Record<string, { strike: number; ceSecurityId: string; peSecurityId: string }>;
  lotSize: number;
  exchangeSegment: string;
  stops: number;
  brakedAt: number | null;
  brakeReason: string | null;
}

export interface MeltingQuote {
  ltp?: number | null;
  bid?: number | null;
  ask?: number | null;
  atp?: number | null;
  volume?: number | null;
}

export interface MeltingColumn {
  index: number;
  type: "X" | "O";
  top: number;
  bottom: number;
  topPrice: number;
  bottomPrice: number;
  start: number;
  end: number;
  signals: string[];
}

export interface MeltingStraddle {
  tag: MeltingTag;
  strike: number;
  ceSecurityId: string;
  peSecurityId: string;
  combined: number | null;
  vwap: number | null;
  lastMinute: number | null;
  live: { ce: MeltingQuote; pe: MeltingQuote; combined: number | null; exchangeVwap: number | null };
  series: { time: number; combined: number; vwap: number | null }[];
  columns: MeltingColumn[];
  boxPoints: number | null;
  signals: { kind: string; time: number; column: number; price: number }[];
}

export interface MeltingFill {
  id: number;
  tradeId: number;
  time: number;
  action: string;
  side: "SELL" | "BUY";
  lots: number;
  quantity: number;
  cePrice: number;
  pePrice: number;
  combined: number;
  ceBid: number | null;
  ceAsk: number | null;
  ceLtp: number | null;
  peBid: number | null;
  peAsk: number | null;
  peLtp: number | null;
  referencePrice: number | null;
  slippage: number | null;
  points: number | null;
  pnl: number | null;
  charges: number;
  reason: string;
  mode: string;
  ceOrderId: string | null;
  peOrderId: string | null;
  orderStatus: string | null;
  note: string | null;
}

export interface MeltingTrade {
  id: number;
  day: string;
  indexName: string;
  expiry: string;
  dte: number;
  tag: MeltingTag;
  strike: number;
  ceSecurityId: string;
  peSecurityId: string;
  exchangeSegment: string;
  mode: "paper" | "live";
  trigger: string;
  signal: string;
  signalTime: number;
  signalPrice: number;
  signalVwap: number;
  lotSize: number;
  lots: number;
  lotsOpen: number;
  entryTime: number;
  entryCe: number;
  entryPe: number;
  entryPrice: number;
  initialSl: number;
  sl: number;
  step: number;
  hits: number;
  status: "OPEN" | "CLOSED";
  exitTime: number | null;
  exitReason: string | null;
  bookedPoints: number;
  charges: number;
  lastCe: number | null;
  lastPe: number | null;
  lastPrice: number | null;
  lastVwap: number | null;
  lastUpdate: number | null;
  bestPrice: number | null;
  worstPrice: number | null;
  needsAttention: string | null;
  realizedPnl: number;
  unrealizedPnl: number;
  grossPnl: number;
  netPnl: number;
  pointsPerLot: number;
  premiumCollected: number;
  decay: number;
  nextTarget: number | null;
  mfe: number;
  mae: number;
  minutesHeld: number;
  fills?: MeltingFill[];
  events?: { id: number; time: number; kind: string; text: string }[];
  minutes?: { time: number; combined: number; vwap: number | null }[];
}

export interface MeltingEvent {
  id: number;
  day: string;
  tradeId: number | null;
  time: number;
  kind: string;
  text: string;
}

export interface MeltingState {
  config: MeltingConfig;
  now: number;
  marketOpen: boolean;
  mode: "paper" | "live";
  day: MeltingDay | null;
  plan: string | null;
  straddles: MeltingStraddle[];
  todayTrades: MeltingTrade[];
  openTrades: MeltingTrade[];
  dayNet: number;
  events: MeltingEvent[];
  attention: MeltingTrade[];
}

export interface MeltingDaySummary extends MeltingDay {
  trades: number;
  wins: number;
  grossPnl: number;
  charges: number;
  netPnl: number;
  points: number;
}
