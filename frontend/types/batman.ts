export type BatmanMode = "monthly" | "weekly";

export type BatmanConfig = Record<string, number | string | boolean> & {
  mode: BatmanMode;
  enabled: boolean;
  capital: number;
  baseLots: number;
  entryTime: string;
  targetPercent: number;
  stopPercent: number;
  lotSize: number;
};

export interface BatmanLegPlan {
  action: "BUY" | "SELL";
  qty: number;
  optionType: "CE" | "PE";
  strike: number;
  role: "inner" | "short" | "outer";
  price: number;
  ltp: number | null;
  bid: number | null;
  ask: number | null;
  iv: number | null;
  delta: number | null;
  distance: number;
  distancePercent: number;
}

export interface BatmanPreview {
  error?: string;
  config: BatmanConfig;
  entryDate?: string;
  entryAt?: number;
  series?: string;
  currentMonthly?: string | null;
  exitBy?: number;
  daysToExpiryAtEntry?: number;
  spot?: number;
  legs?: BatmanLegPlan[];
  buyOffset?: number;
  sellGap?: number;
  hedgeGap?: number;
  creditShifts?: number;
  credit?: number;
  creditPercent?: number;
  creditOk?: boolean;
  extraCallLots?: number;
  balanceMove?: number;
  balanceTable?: { extraCallLots: number; t0Down: number; t0Up: number }[];
  t0Down?: number;
  t0Up?: number;
  t0DownPercent?: number;
  t0UpPercent?: number;
  expiryMaxProfit?: number;
  expiryMaxLoss?: number;
  breakevens?: number[];
  payoff?: { price: number; expiry: number; today: number }[];
  targetAmount?: number;
  stopAmount?: number;
  expectedMove?: number;
  events?: string[];
}

export interface BatmanLeg {
  id: number;
  action: "BUY" | "SELL";
  optionType: "CE" | "PE";
  role: string;
  strike: number;
  lots: number;
  entryPrice: number;
  exitPrice: number | null;
  lastLtp: number | null;
  lastBid: number | null;
  lastAsk: number | null;
}

export interface BatmanTrade {
  id: number;
  mode: BatmanMode;
  sessionDate: string;
  trigger: string;
  expiry: string;
  entryTime: number;
  spot: number;
  capital: number;
  lotSize: number;
  baseLots: number;
  buyOffset: number;
  sellGap: number;
  hedgeGap: number;
  extraCallLots: number;
  credit: number;
  creditPercent: number;
  targetPercent: number;
  stopPercent: number;
  exitBy: number;
  status: "OPEN" | "CLOSED";
  exitTime: number | null;
  exitReason: string | null;
  lastMtm: number | null;
  lastUpdate: number | null;
  notes: string | null;
  legs: BatmanLeg[];
  grossPnl: number;
  estimatedCharges: number;
  netPnl: number;
  returnPercent: number;
  targetAmount: number;
  stopAmount: number;
  mtmHistory?: { time: number; mtm: number; spot: number | null }[];
  currentSpot?: number;
  payoff?: { price: number; expiry: number; today: number }[];
  breakevens?: number[];
}

export interface BatmanAnalysis extends Omit<BatmanPreview, "config"> {
  error?: string;
  series: string;
  dte?: number;
  atmIv?: number | null;
  expiries: { expiry: string; dte: number; monthly: boolean }[];
  suggested: { buyOffset: number; sellGap: number; hedgeGap: number; balanceMove: number } | null;
  inputs?: {
    baseLots: number;
    shortRatio: number;
    outerRatio: number;
    buyOffset: number;
    sellGap: number;
    hedgeGap: number;
    extraCallLots: number | null;
    capital: number;
    balanceMove: number;
  };
  autoExtraCallLots?: boolean;
}
