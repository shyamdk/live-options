export type PstrategyResolution = "1m" | "5m" | "15m";

export interface PstrategyCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface ConsolidationBox {
  startTime: number;
  endTime: number;
  support: number;
  resistance: number;
}

export interface MomentumCandle {
  time: number;
  side: "long" | "short";
}

export type ExitReason = "target" | "stop" | "ema_exit" | "trail_stop";

export interface PstrategyTrade {
  side: "long" | "short";
  status: "open" | "closed";
  entryTime: number;
  entryPrice: number;
  stopLoss: number;
  peakPrice: number;
  trailStop: number | null;
  exitTime: number | null;
  exitPrice: number | null;
  exitReason: ExitReason | null;
  pnlPercent: number | null;
  pnlAmountInr: number | null;
  currentPrice?: number | null;
  unrealizedPnlPercent?: number | null;
  unrealizedPnlAmountInr?: number | null;
}

export interface Crossover {
  time: number;
  direction: "bullish" | "bearish";
}

export interface EmaSettings {
  enabled: boolean;
  fast: number;
  slow: number;
}

export interface PstrategyData {
  symbol?: string;
  resolution?: PstrategyResolution;
  error?: string;
  emaEnabled: boolean;
  emaFast: number;
  emaSlow: number;
  leverage: number;
  paperCapitalInr: number;
  candles: PstrategyCandle[];
  consolidations: ConsolidationBox[];
  momentumCandles: MomentumCandle[];
  trades: PstrategyTrade[];
  rsi: (number | null)[];
  emaFastValues: (number | null)[];
  emaSlowValues: (number | null)[];
  crossovers: Crossover[];
}
