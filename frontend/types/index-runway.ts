export type RunwayTradeMode = "straddle" | "follow";

export type RunwayEstimate = { median: number; p75: number; hit40: number };

export type RunwayConfig = {
  enabled: boolean;
  minAbsTrigPts: number;
  minVix: number;
  minAbsIvChg: number;
  minRange5: number;
  tradeMode: RunwayTradeMode;
  lots: number;
  holdMinutes: number;
  maxOpen: number;
  entryStart: string;
  entryEnd: string;
  notify: boolean;
  lotSize: number;
  estimates: { from: number; to: number | null; median: number; p75: number; hit40: number }[];
};

// Trigger-minute features (bar T-1 -> bar T); keys follow the backtest columns.
export type RunwayFeatures = Record<string, number | string | boolean | null | RunwayEstimate | undefined> & {
  atmStrike: number;
  spotPrev: number;
  spotNow: number;
  trigPts: number;
  vixPrev: number | null;
  vixNow: number | null;
  vixChg: number | null;
  range5: number | null;
  ivChgAvg: number | null;
  dteMinutes: number;
  oiUpdated: boolean;
  estimate?: RunwayEstimate | null;
};

export type RunwayLeg = { option: "CE" | "PE"; strike: number; securityId: string; entry: number; exit: number | null };

export type RunwayTrade = {
  id: number;
  day: string;
  signalTime: number;
  mode: RunwayTradeMode;
  direction: "UP" | "DOWN";
  status: "OPEN" | "CLOSED";
  expiry: string;
  atmStrike: number;
  lots: number;
  quantity: number;
  legs: RunwayLeg[];
  entryTime: number;
  exitDue: number;
  exitTime: number | null;
  exitReason: string | null;
  spotEntry: number | null;
  spotExit: number | null;
  trigPts: number | null;
  estMove: number | null;
  estP75: number | null;
  estHit40: number | null;
  actualMove: number | null;
  hit40: boolean | null;
  grossPnl: number | null;
  charges: number | null;
  netPnl: number | null;
  vix: number | null;
  vixChg: number | null;
  ivChg: number | null;
  features: RunwayFeatures;
};

export type RunwaySignal = {
  time: number;
  day: string;
  close: number;
  trigPts: number | null;
  range5: number | null;
  vix: number | null;
  vixChg: number | null;
  ivChg: number | null;
  clCeRoc3: number | null;
  clPeRoc3: number | null;
  estimate: RunwayEstimate | null;
  fwdMove: number | null;
  fwdMinutes: number | null;
  hit40: boolean | null;
};

export type RunwayState = {
  config: RunwayConfig;
  marketOpen: boolean;
  monitorEnabled: boolean;
  lastCheck: number | null;
  lastFeatures: RunwayFeatures | null;
  lastReasons: string[];
  lastMatched: boolean;
  skipped: string | null;
  error: string | null;
  openTrades: RunwayTrade[];
  stats: { days: number; minutes: number; scored: number; hits: number; signals: number; signalsScored: number; signalHits: number };
};
