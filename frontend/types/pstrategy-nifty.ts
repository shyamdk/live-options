export type PstrategyNiftyResolution = "1m" | "3m";

export interface PstrategyNiftyCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface PstrategyNiftyConsolidationBox {
  startTime: number;
  endTime: number;
  support: number;
  resistance: number;
}

export interface PstrategyNiftyMomentumCandle {
  time: number;
  side: "long" | "short";
}

export interface PstrategyNiftyCandlesData {
  resolution?: PstrategyNiftyResolution;
  error?: string;
  candles: PstrategyNiftyCandle[];
  consolidations: PstrategyNiftyConsolidationBox[];
  momentumCandles: PstrategyNiftyMomentumCandle[];
  emaSlowValues: (number | null)[];
}

export interface PstrategyNiftyTrade {
  id: number;
  resolution: PstrategyNiftyResolution;
  side: "CE" | "PE";
  strike: number;
  expiry: string;
  lots: number;
  lotSize: number;
  entryTime: number;
  entryPremium: number;
  entryUnderlyingPrice: number;
  stopLossPercent: number;
  peakPremium: number | null;
  bestUnderlyingClose: number;
  trailStopUnderlying: number | null;
  status: "open" | "closed";
  exitTime: number | null;
  exitPremium: number | null;
  exitReason: string | null;
  realizedPnl: number | null;
  currentPremium?: number | null;
  unrealizedPnl?: number | null;
  netUnrealizedPnl?: number | null;
  netRealizedPnl?: number | null;
  charges?: number | null;
}
