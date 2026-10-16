export type SimpleCrossoverSide = "CE" | "PE";

export interface SimpleCrossoverCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface SimpleCrossoverPoint {
  time: number;
  price: number;
  direction: "up" | "down";
  rsi: number | null;
}

export interface SimpleCrossoverCurrent {
  emaFast: number | null;
  emaSlow: number | null;
  rsi: number | null;
  rsiSma: number | null;
  gap: number | null;
}

export interface SimpleCrossoverDayDirection {
  label: "Up" | "Down" | "Sideways";
  changePercent: number;
  dayOpen: number;
  current: number;
}

export type SimpleCrossoverExitReason =
  | "target_5"
  | "target_10"
  | "stop_loss"
  | "trailing_stop"
  | "cross_under"
  | "plain_target"
  | "eod";

export interface SimpleCrossoverExitLeg {
  lots: number;
  exitTime: number;
  exitPremium: number;
  exitReason: SimpleCrossoverExitReason;
}

export interface SimpleCrossoverTrade {
  id: number;
  underlying: string;
  side: SimpleCrossoverSide;
  strike: number;
  expiry: string;
  securityId: string;
  exchangeSegment: string;
  lots: number;
  lotSize: number;
  entryTime: number;
  entryPremium: number;
  entryEmaGap: number | null;
  entryPcr: number | null;
  entryCeOiChange: number | null;
  entryPeOiChange: number | null;
  dayDirection: "Up" | "Down" | "Sideways" | null;
  timeframeMinutes?: number;
  signalTime?: number | null;
  signalClose?: number | null;
  signalSource?: "live" | "dhan" | null;
  plainCrossover?: boolean;
  plainTargetPercent?: number | null;
  status: "open" | "closed";
  currentPremium: number | null;
  remainingLots: number;
  remainingQuantity: number;
  target1Hit: boolean;
  target2Hit: boolean;
  peakPremium: number | null;
  stopLossPercent: number;
  stopLossPrice: number;
  trailingStopPrice: number | null;
  unrealizedPnl: number | null;
  exitTime: number | null;
  exitPremium: number | null;
  exitReason: SimpleCrossoverExitReason | null;
  realizedPnl: number | null;
  exitLegs: SimpleCrossoverExitLeg[];
  charges: number | null;
  netPnl: number | null;
  comment: string | null;
  createdAt: string;
}

export interface SimpleCrossoverConfig {
  dayDirectionFilterEnabled: boolean;
  tradeOnSideways: boolean;
  stopLossPercent: number;
  timeframeMinutes: 1 | 3;
  plainCrossover: boolean;
  plainTargetPercent: number;
}

export interface SimpleCrossoverData {
  timeframeMinutes?: number;
  error?: string;
  underlying?: string;
  side?: SimpleCrossoverSide;
  strike?: number;
  expiry?: string;
  candles: SimpleCrossoverCandle[];
  emaFastValues: (number | null)[];
  emaSlowValues: (number | null)[];
  rsiValues: (number | null)[];
  rsiSmaValues: (number | null)[];
  gapValues: (number | null)[];
  crossovers: SimpleCrossoverPoint[];
  lastCrossover: SimpleCrossoverPoint | null;
  current: SimpleCrossoverCurrent;
  gapTrend: "increasing" | "decreasing" | "flat" | null;
  dayDirection: SimpleCrossoverDayDirection | null;
}
