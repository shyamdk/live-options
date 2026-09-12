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

export type CryptoSwingSymbol = "BTCUSD" | "ETHUSD";

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
