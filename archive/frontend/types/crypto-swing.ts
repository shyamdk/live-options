export interface DeltaWalletBalance {
  asset_symbol?: string;
  asset?: { symbol?: string };
  balance?: string | number;
  available_balance?: string | number;
}

export interface CryptoSwingWallet {
  connected: boolean;
  error: string | null;
  balances: DeltaWalletBalance[];
}

export interface CryptoCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export type CryptoSwingSymbol = "BTCUSD" | "ETHUSD" | "XAUTUSD";

export interface CryptoSwingTrade {
  symbol: CryptoSwingSymbol;
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

export interface CryptoSwingLiveTrade {
  id: number;
  symbol: CryptoSwingSymbol;
  side: "long" | "short";
  mode: "shadow" | "live";
  status: "open" | "closed";
  entryTime: number;
  entryPrice: number;
  sizeContracts: number;
  notionalUsd: number;
  stopLoss: number | null;
  tranches: number;
  exitTime: number | null;
  exitPrice: number | null;
  exitReason: string | null;
  pnlUsd: number | null;
  orderId: string | null;
  note: string | null;
}

export interface CryptoSwingLiveStatus {
  liveEnabled: boolean;
  shadowMode: boolean;
  mode: "shadow" | "live";
  riskPercentPerTrade: number;
  maxDailyLossPercent: number;
  maxConcurrentPositions: number;
  minMarginBufferPercent: number;
  leverage: string;
  openPositions: number;
  todayRealizedPnlUsd: number;
  trades: CryptoSwingLiveTrade[];
}

export interface CryptoSwingIndicators {
  symbol?: CryptoSwingSymbol;
  resolution?: string;
  error?: string;
  candles: CryptoCandle[];
  ema200: (number | null)[];
  macdLine: (number | null)[];
  signalLine: (number | null)[];
  histogram: (number | null)[];
  supertrend: (number | null)[];
  supertrendDirection: ("up" | "down" | null)[];
}
