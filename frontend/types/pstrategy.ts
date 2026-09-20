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
  candles: PstrategyCandle[];
  consolidations: ConsolidationBox[];
  momentumCandles: MomentumCandle[];
  emaFastValues: (number | null)[];
  emaSlowValues: (number | null)[];
  crossovers: Crossover[];
}
