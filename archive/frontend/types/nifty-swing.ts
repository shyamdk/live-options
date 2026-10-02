export type NiftySwingResolution = "5m" | "15m" | "30m" | "1h";

export interface NiftySwingCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface NiftySwingIndicators {
  resolution?: NiftySwingResolution;
  error?: string;
  candles: NiftySwingCandle[];
  ema200: (number | null)[];
  macdLine: (number | null)[];
  signalLine: (number | null)[];
  histogram: (number | null)[];
  supertrend: (number | null)[];
  supertrendDirection: ("up" | "down" | null)[];
}

export interface NiftySwingTrade {
  side: "long" | "short";
  status: "open" | "closed" | "error";
  error?: string;
  entryTime: number | null;
  entryPrice: number | null;
  tranches: number;
  quantity: number;
  stopLoss?: number;
  peakPrice?: number;
  trailStop?: number | null;
  exitTime: number | null;
  exitPrice: number | null;
  exitReason: string | null;
  pnlPercent: number | null;
  pnlAmount: number | null;
  currentPrice?: number | null;
  unrealizedPnlPercent?: number | null;
  unrealizedPnlAmount?: number | null;
}

export interface NiftySwingLiveTrade {
  id: number;
  side: "long" | "short";
  mode: "shadow" | "live";
  status: "open" | "closed";
  entryTime: number;
  entryPrice: number;
  quantity: number;
  tranches: number;
  stopLoss: number | null;
  exitTime: number | null;
  exitPrice: number | null;
  exitReason: string | null;
  pnlInr: number | null;
  orderId: string | null;
  note: string | null;
}

export interface NiftySwingLiveStatus {
  liveEnabled: boolean;
  shadowMode: boolean;
  mode: "shadow" | "live";
  quantityPerTranche: number;
  maxCapitalRupees: number;
  maxDailyLossRupees: number;
  resolution: NiftySwingResolution;
  productType: string;
  openPositions: number;
  todayRealizedPnlInr: number;
  trades: NiftySwingLiveTrade[];
}
