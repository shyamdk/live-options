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

export interface Crossover {
  time: number;
  direction: "bullish" | "bearish";
}

export interface PstrategyData {
  symbol?: string;
  resolution?: PstrategyResolution;
  error?: string;
  candles: PstrategyCandle[];
  consolidations: ConsolidationBox[];
  momentumCandles: MomentumCandle[];
  ema9: (number | null)[];
  ema20: (number | null)[];
  crossovers: Crossover[];
}
