export type SimpleCrossoverXautSide = "long" | "short";

export interface SimpleCrossoverXautCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface SimpleCrossoverXautPoint {
  time: number;
  price: number;
  direction: "up" | "down";
  rsi: number | null;
}

export interface SimpleCrossoverXautCurrent {
  emaFast: number | null;
  emaSlow: number | null;
  rsi: number | null;
  rsiSma: number | null;
  gap: number | null;
}

export interface SimpleCrossoverXautDayDirection {
  label: "Up" | "Down" | "Sideways";
  changePercent: number;
  dayOpen: number;
  current: number;
}

export type SimpleCrossoverXautExitReason = "cross_under" | "cross_over" | "rsi_peak" | "rsi_trough" | "day_boundary";

export interface SimpleCrossoverXautTrade {
  id: number;
  side: SimpleCrossoverXautSide;
  quantity: number;
  entryTime: number;
  entryPrice: number;
  entryEmaGap: number | null;
  dayDirection: "Up" | "Down" | "Sideways" | null;
  margin: number | null;
  leverage: number | null;
  status: "open" | "closed";
  currentPrice: number | null;
  exitTime: number | null;
  exitPrice: number | null;
  exitReason: SimpleCrossoverXautExitReason | null;
  realizedPnl: number | null;
  charges: number | null;
  netPnl: number | null;
  netPnlPercent: number | null;
  comment: string | null;
  createdAt: string;
}

export interface SimpleCrossoverXautConfig {
  dayDirectionFilterEnabled: boolean;
  tradeOnSideways: boolean;
  rsiExitEnabled: boolean;
  rsiLongExitThreshold: number;
  rsiShortExitThreshold: number;
  marginPerTrade: number;
  leverage: number;
  entryGapFilterEnabled: boolean;
  minEntryGap: number;
  maxEntryGap: number;
}

export interface SimpleCrossoverXautData {
  error?: string;
  symbol?: string;
  candles: SimpleCrossoverXautCandle[];
  emaFastValues: (number | null)[];
  emaSlowValues: (number | null)[];
  rsiValues: (number | null)[];
  rsiSmaValues: (number | null)[];
  gapValues: (number | null)[];
  crossovers: SimpleCrossoverXautPoint[];
  lastCrossover: SimpleCrossoverXautPoint | null;
  current: SimpleCrossoverXautCurrent;
  gapTrend: "increasing" | "decreasing" | "flat" | null;
  dayDirection: SimpleCrossoverXautDayDirection | null;
}
